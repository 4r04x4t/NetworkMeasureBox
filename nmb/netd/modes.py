"""Network modes: Mode A (Active Gateway / NAT / AP) and Mode B (Passive Inline Bridge).

Each mode provides setup() and teardown() ensuring clean, idempotent transitions.
"""
from __future__ import annotations

import ipaddress
import logging
import shutil
import subprocess
import time
from pathlib import Path
from abc import ABC, abstractmethod
from typing import List, Optional

from nmb.config import NetworkConfig
from nmb.netd import firewall, interfaces, lan_topology
from nmb.netd.services import ServiceManager

log = logging.getLogger("nmb.netd.modes")


class NetworkMode(ABC):
    def __init__(self, cfg: NetworkConfig, svc_mgr: ServiceManager):
        self.cfg = cfg
        self.svc_mgr = svc_mgr
        self.active_wan = cfg.wan_interface

    @abstractmethod
    def setup(self) -> bool:
        """Apply network configuration for this mode."""
        pass

    @abstractmethod
    def teardown(self) -> bool:
        """Tear down this mode cleanly."""
        pass

    @abstractmethod
    def get_status(self) -> dict:
        """Return diagnostic status dict for this mode."""
        pass


class ModeA(NetworkMode):
    """Mode A: Active Gateway / PPPoE / NAT Router with dnsmasq and hostapd."""

    def __init__(self, cfg: NetworkConfig, svc_mgr: ServiceManager):
        super().__init__(cfg, svc_mgr)
        self.lan_ifaces: List[str] = []
        self.wan_fail_count = 0
        self.wan_ok_count = 0
        self.full_cfg = None          # set by the daemon: the USB tethering settings live outside [network]
        self.usb_wan = None           # USB interface when it is the WAN (nothing upstream on the WAN port)
        self.needs_resetup = False
        self._usb_guard_ts = 0.0
        self.on_wan2 = False
        self.pppoe_iface = ""         # the port pppd dials on, while PPPoE is the WAN
        self.pppoe_error = ""         # why pppd gave up last time, for the status page
        self.pppoe_auth_fails = 0     # refused logins in a row: each one doubles the pause
        self._pppd_retry_at = 0.0

    def _setup_vlan_if_needed(self) -> str:
        if self.cfg.pppoe_vlan > 0:
            vlan_iface = f"{self.cfg.wan_interface}.{self.cfg.pppoe_vlan}"
            ip_bin = shutil.which("ip")
            if ip_bin and not interfaces.interface_exists(vlan_iface):
                log.info("creating 802.1Q VLAN interface %s (id %d)", vlan_iface, self.cfg.pppoe_vlan)
                interfaces.set_link_up(self.cfg.wan_interface)
                interfaces.run_cmd([
                    ip_bin, "link", "add", "link", self.cfg.wan_interface,
                    "name", vlan_iface, "type", "vlan", "id", str(self.cfg.pppoe_vlan)
                ], check=False)
                interfaces.set_link_up(vlan_iface)
            return vlan_iface
        return self.cfg.wan_interface

    def _configure_wan_ip(self, iface: str, proto: str, ip: str, netmask: str, gateway: str) -> None:
        """Apply the configured static address or request a DHCP lease."""
        if proto == "static" and ip:
            prefix = ipaddress.ip_network(f"0.0.0.0/{netmask or '255.255.255.0'}").prefixlen
            interfaces.flush_ip_addresses(iface)
            interfaces.add_ip_address(iface, f"{ip}/{prefix}")
            ip_bin = shutil.which("ip")
            if gateway and ip_bin:
                interfaces.run_cmd([ip_bin, "route", "replace", "default", "via", gateway, "dev", iface], check=False)
        elif proto == "dhcp" and not interfaces.get_ip_addresses(iface):
            if not interfaces.request_dhcp_lease(iface):
                log.warning("no DHCP lease obtained on %s", iface)

    def _apply_wan2_routing(self, wan2: str) -> None:
        """Failover: WAN2 as a higher-metric default. Loadbalance: multipath default route."""
        mode = getattr(self.cfg, "wan_mode", "single")
        ip_bin = shutil.which("ip")
        gw2 = self.cfg.wan2_gateway or interfaces.get_default_gateway(wan2)
        if mode not in ("failover", "loadbalance") or not ip_bin or not gw2:
            if mode in ("failover", "loadbalance"):
                log.warning("WAN mode %s not applied: no gateway found on %s", mode, wan2)
            return
        if mode == "failover":
            interfaces.run_cmd([ip_bin, "route", "replace", "default", "via", gw2, "dev", wan2, "metric", "200"], check=False)
            return
        primary = ["nexthop"]
        gw1 = self.cfg.wan_gateway or interfaces.get_default_gateway(self.active_wan)
        if gw1 and self.active_wan != "ppp0":
            primary += ["via", gw1]
        primary += ["dev", self.active_wan, "weight", "1"]
        interfaces.run_cmd(
            [ip_bin, "route", "replace", "default", *primary, "nexthop", "via", gw2, "dev", wan2, "weight", "1"],
            check=False,
        )

    def check_wan_failover(self) -> None:
        """Move the default route to WAN2 after 3 failed checks, and back after 3 good ones."""
        wan2 = getattr(self.cfg, "wan2_interface", "")
        ip_bin = shutil.which("ip")
        ping_bin = shutil.which("ping")
        if getattr(self.cfg, "wan_mode", "single") != "failover" or not wan2 or not ip_bin or not ping_bin:
            return
        target = (getattr(self.cfg, "detection_targets", None) or ["1.1.1.1"])[0]
        result = interfaces.run_cmd([ping_bin, "-c", "1", "-W", "2", "-I", self.active_wan, target], check=False)
        self.wan_fail_count = 0 if result.returncode == 0 else self.wan_fail_count + 1
        self.wan_ok_count = self.wan_ok_count + 1 if result.returncode == 0 else 0

        if not self.on_wan2 and self.wan_fail_count >= 3:
            gateway = self.cfg.wan2_gateway or interfaces.get_default_gateway(wan2)
            if gateway:
                log.warning("primary WAN %s is failing; switching default route to %s", self.active_wan, wan2)
                interfaces.run_cmd([ip_bin, "route", "replace", "default", "via", gateway, "dev", wan2, "metric", "10"], check=False)
                self.on_wan2 = True
        elif self.on_wan2 and self.wan_ok_count >= 3:
            log.warning("primary WAN %s recovered; removing failover route", self.active_wan)
            interfaces.run_cmd([ip_bin, "route", "del", "default", "dev", wan2, "metric", "10"], check=False)
            self.on_wan2 = False

    # Pause before dialing again after pppd gave up: a refused login waits 10, 20, then 30 minutes (an ISP
    # may lock an account or a port after many refused logins); a line problem waits 30 seconds.
    PPPD_AUTH_PAUSE_SEC = 600
    PPPD_AUTH_PAUSE_MAX_SEC = 1800
    PPPD_LINE_PAUSE_SEC = 30

    def check_pppd(self, now: Optional[float] = None) -> None:
        """Every loop: when pppd has given up (maxfail), note why and dial again after a pause."""
        import time as _t
        from nmb.netd.services import PPPD_EXIT_AUTH, PPPD_EXIT_TEXT
        if not self.pppoe_iface or self.active_wan != "ppp0":
            return
        now = _t.monotonic() if now is None else now
        if self._pppd_retry_at:
            if now >= self._pppd_retry_at:
                log.info("PPPoE: dialing again on %s", self.pppoe_iface)
                self._pppd_retry_at = 0.0
                self.svc_mgr.start_pppd(self.pppoe_iface)
            return
        rc = self.svc_mgr.pppd_exit_code()
        if rc is None:
            if self.pppoe_error and interfaces.get_ip_addresses("ppp0"):
                log.info("PPPoE is up again on %s", self.pppoe_iface)
                self.pppoe_error, self.pppoe_auth_fails = "", 0
            return
        why = PPPD_EXIT_TEXT.get(rc, f"pppd stopped (exit code {rc})")
        if rc == PPPD_EXIT_AUTH:
            self.pppoe_auth_fails += 1
            pause = min(self.PPPD_AUTH_PAUSE_SEC * self.pppoe_auth_fails, self.PPPD_AUTH_PAUSE_MAX_SEC)
        else:
            pause = self.PPPD_LINE_PAUSE_SEC
        self.pppoe_error = why
        self._pppd_retry_at = now + pause
        log.warning("PPPoE: %s; dialing again in %d s", why, pause)
        if rc == PPPD_EXIT_AUTH:
            from nmb.netd.usb_uplink import _log_event
            _log_event("pppoe_auth_refused", f"The ISP refused the PPPoE login (attempt {self.pppoe_auth_fails}); "
                                             f"check the user name and password in Router > PPPoE. Next try in {pause // 60} min.")

    def _usb_wan_candidate(self) -> Optional[str]:
        """USB tethering as the WAN: only when it is up and nothing upstream answers on the WAN port.

        "Nothing upstream" means no DHCP server answers there (a PC plugged into the port is fine,
        the home router is not); PPPoE or a static WAN always keep the port as WAN.
        """
        full = self.full_cfg
        if full is None or not getattr(getattr(full, "usb_uplink", None), "enabled", False):
            return None
        if ((self.cfg.pppoe_enabled or getattr(self, 'auto_pppoe', False)) and self.cfg.pppoe_user) or str(self.cfg.wan_proto).lower() == "static":
            return None
        from nmb.netd import usb_uplink
        ui = usb_uplink.uplink_interface(full)
        if not ui or ui == self.cfg.wan_interface:
            return None
        uip, ugw = usb_uplink._address_and_gateway(ui)
        if not (uip and ugw):
            return None
        from nmb.netd.wifi_share import probe_dhcp_servers
        wan = self.cfg.wan_interface
        if interfaces.interface_exists(wan) and interfaces.get_carrier(wan):
            interfaces.set_link_up(wan)
            servers = [x for x in probe_dhcp_servers(wan) if x != self.cfg.gateway_ip]
            if servers:
                log.info("Mode A: a DHCP server answers on %s (%s); it stays the WAN", wan, ", ".join(servers))
                return None
        return ui

    def check_usb_wan(self) -> None:
        """Every minute: rebuild the mode when the WAN source must change (USB <-> the WAN port)."""
        import time as _t
        now = _t.monotonic()
        if now - self._usb_guard_ts < 60:
            return
        self._usb_guard_ts = now
        full = self.full_cfg
        if self.usb_wan:
            from nmb.netd import usb_uplink
            gone = not (full and getattr(full.usb_uplink, "enabled", False)) or usb_uplink.uplink_interface(full) != self.usb_wan
            servers = []
            wan = self.cfg.wan_interface
            carrier = interfaces.get_carrier(wan)
            if not gone and carrier:
                from nmb.netd.wifi_share import probe_dhcp_servers
                servers = [x for x in probe_dhcp_servers(wan) if x != self.cfg.gateway_ip]
            log.info("Mode A USB WAN check: %s carrier=%s, foreign DHCP servers=%s", wan, carrier, servers or "none")
            if gone or servers:
                why = "the USB device is gone or turned off" if gone else f"a DHCP server answers on {wan} ({', '.join(servers)})"
                log.warning("Mode A: leaving USB WAN: %s", why)
                if servers:
                    # Never keep serving DHCP onto another network: stop it now, rebuild next loop.
                    self.svc_mgr.stop_all()
                self.needs_resetup = True
        elif self.full_cfg is not None and not [a for a in interfaces.get_ip_addresses(self.cfg.wan_interface)
                                                if ":" not in a]:
            # Only an IPv4 lease means internet on the port; the IPv6 link-local address is always there.
            if self._usb_wan_candidate():
                log.warning("Mode A: no internet on %s; switching the WAN to USB tethering", self.cfg.wan_interface)
                self.needs_resetup = True

    def setup(self) -> bool:
        log.info("initializing Mode A (Active Gateway / NAT)")
        self.lan_ifaces = []
        self.needs_resetup = False
        self.usb_wan = self._usb_wan_candidate()
        from nmb.netd import usb_uplink
        usb_uplink.set_router_wan(self.usb_wan)
        if self.usb_wan:
            ok = self._setup_lan_and_nat(self.usb_wan, extra_lan=[self.cfg.wan_interface])
            # A default route through a LAN port (NetworkManager's old lease on the WAN port) would swallow
            # every packet the box sends; the box's own internet is USB now.
            # The box's own internet is USB now: any other default route (a LAN port, the radio that just
            # became the access point) leads nowhere and would win over USB's metric 900.
            res = interfaces.run_cmd(["ip", "-4", "route", "show", "default"], check=False)
            for line in (getattr(res, "stdout", "") or "").splitlines():
                parts = line.split()
                if "dev" in parts and parts[parts.index("dev") + 1] != self.usb_wan:
                    interfaces.run_cmd(["ip", "-4", "route", "del"] + interfaces.route_delete_args(parts), check=False)
            if self.full_cfg is not None:
                usb_uplink.sync_default_fallback(self.full_cfg, allow_rescue=False)
            self._renew_lan_clients([self.cfg.wan_interface])
            return ok

        # 1. Bring up WAN
        if getattr(self.cfg, "wan_mac", None):
            interfaces.set_mac_address(self.cfg.wan_interface, self.cfg.wan_mac)
        wan = self._setup_vlan_if_needed()
        interfaces.set_link_up(self.cfg.wan_interface)
        interfaces.set_link_up(wan)
        self.active_wan = wan

        if (self.cfg.pppoe_enabled or getattr(self, 'auto_pppoe', False)) and self.cfg.pppoe_user:
            log.info("launching PPPoE client on %s", wan)
            self.svc_mgr.start_pppd(wan)
            self.pppoe_iface = wan
            self._pppd_retry_at = 0.0
            self.active_wan = "ppp0"
        else:
            self._configure_wan_ip(wan, self.cfg.wan_proto, self.cfg.wan_ip, self.cfg.wan_netmask, self.cfg.wan_gateway)
        ok = self._setup_lan_and_nat(self.active_wan)
        self._renew_lan_clients(list(getattr(self.cfg, "lan_ports", None) or [self.cfg.lan_interface]))
        return ok

    def _renew_lan_clients(self, ports: List[str]) -> None:
        """Drop the link of wired LAN ports for a moment, so a PC asks for a new address.

        2026-11-08: a laptop kept its 192.168.77.x lease from Wi-Fi sharing after the box switched to router
        mode (192.168.100.x) and had no internet until its cable was replugged.
        """
        for p in ports:
            p = (p or "").strip()
            if not p or p in (self.active_wan, self.usb_wan) or not interfaces.interface_exists(p) \
                    or interfaces.usb_tether_kind(p) or Path(f"/sys/class/net/{p}/wireless").exists() \
                    or not interfaces.get_carrier(p):
                continue
            log.info("Mode A: renewing the address of the device on %s (link down for 4 s)", p)
            interfaces.run_cmd(["ip", "link", "set", p, "down"], check=False)
            time.sleep(4)
            interfaces.run_cmd(["ip", "link", "set", p, "up"], check=False)

    def _setup_lan_and_nat(self, wan_out: str, extra_lan: Optional[List[str]] = None) -> bool:
        """LAN ports, the Wi-Fi access point, DMZ, DHCP and NAT towards wan_out."""
        self.active_wan = wan_out
        if extra_lan:
            log.info("Mode A on USB tethering: WAN %s; %s joins the LAN", wan_out, ", ".join(extra_lan))

        # 2. Configure LAN interfaces (Single LAN or Bridge br-lan for Multi-LAN ports)
        lan_ports = list(getattr(self.cfg, "lan_ports", None) or [self.cfg.lan_interface])
        for extra in extra_lan or []:
            if extra not in lan_ports:
                lan_ports.append(extra)
        # A phone, hotspot or modem on USB is never a LAN port (often named eth1, the default LAN name).
        lan_ports = [p.strip() for p in lan_ports if p.strip() and interfaces.interface_exists(p.strip())
                     and not interfaces.usb_tether_kind(p.strip()) and p.strip() != wan_out]

        # Wi-Fi clients share the LAN subnet through the bridge, so a Wi-Fi failure cannot take down wired DHCP.
        wifi_ap = self.cfg.wifi_enabled and interfaces.interface_exists(self.cfg.wlan_interface)
        # NetworkManager would run DHCP on a LAN port (its netplan profile), fail with no server there,
        # and pull the port out of the bridge; the router owns these ports while Mode A runs.
        self.nm_released = []
        for p in lan_ports:
            self.svc_mgr._release_from_network_manager(p)
            self.nm_released.append(p)
        if len(lan_ports) > 1 or wifi_ap:
            br_name = "br-lan"
            log.info("multi-LAN detected (%s): establishing bridge %s", lan_ports, br_name)
            for p in lan_ports:
                interfaces.flush_ip_addresses(p)
                interfaces.set_link_up(p)
            interfaces.setup_bridge(br_name, lan_ports)
            interfaces.flush_ip_addresses(br_name)
            interfaces.set_link_up(br_name)
            interfaces.add_ip_address(br_name, f"{self.cfg.gateway_ip}/24")
            self.lan_ifaces.append(br_name)
        elif len(lan_ports) == 1:
            single_lan = lan_ports[0]
            log.info("configuring single LAN interface %s with %s", single_lan, self.cfg.gateway_ip)
            interfaces.flush_ip_addresses(single_lan)
            interfaces.set_link_up(single_lan)
            interfaces.add_ip_address(single_lan, f"{self.cfg.gateway_ip}/24")
            self.lan_ifaces.append(single_lan)
        elif interfaces.interface_exists(self.cfg.lan_interface) and not interfaces.usb_tether_kind(self.cfg.lan_interface) \
                and self.cfg.lan_interface != wan_out:
            log.info("configuring fallback LAN interface %s with %s", self.cfg.lan_interface, self.cfg.gateway_ip)
            interfaces.flush_ip_addresses(self.cfg.lan_interface)
            interfaces.set_link_up(self.cfg.lan_interface)
            interfaces.add_ip_address(self.cfg.lan_interface, f"{self.cfg.gateway_ip}/24")
            self.lan_ifaces.append(self.cfg.lan_interface)

        # 3. Configure Wi-Fi Diagnostic AP if enabled
        if self.cfg.wifi_enabled and interfaces.interface_exists(self.cfg.wlan_interface):
            log.info("configuring Diagnostic Wi-Fi on %s", self.cfg.wlan_interface)
            from nmb.netd.wifi import unblock_wifi
            unblock_wifi()
            interfaces.set_link_up(self.cfg.wlan_interface)
            if not self.svc_mgr.start_hostapd(self.cfg.wlan_interface, bridge="br-lan"):
                log.error("Wi-Fi access point failed to start on %s; wired LAN stays available", self.cfg.wlan_interface)

        # 3b. DMZ port: its own subnet, isolated from the LAN by the firewall rules below
        self.dmz_iface = ""
        dmz = getattr(self.cfg, "dmz_interface", "")
        if dmz and interfaces.interface_exists(dmz) and dmz not in lan_ports and dmz != self.cfg.wan_interface and dmz != wan_out:
            from nmb.netd.services import DMZ_GATEWAY
            interfaces.flush_ip_addresses(dmz)
            interfaces.set_link_up(dmz)
            interfaces.add_ip_address(dmz, f"{DMZ_GATEWAY}/24")
            self.dmz_iface = dmz
        elif dmz:
            log.warning("DMZ port %s is missing or also used as LAN or WAN; DMZ not set up", dmz)

        # 4. Start dnsmasq for LAN interfaces
        if self.lan_ifaces or self.dmz_iface:
            self.svc_mgr.start_dnsmasq(self.lan_ifaces, dmz_iface=self.dmz_iface)

        # 5. Enable NAT and IPv4 forwarding
        firewall.enable_nat_mode_a(self.active_wan, self.lan_ifaces, dmz_iface=self.dmz_iface)

        # 6. Bring up Secondary WAN2 if configured
        wan2 = getattr(self.cfg, "wan2_interface", "")
        if wan2 and interfaces.interface_exists(wan2) and not self.usb_wan:
            interfaces.set_link_up(wan2)
            log.info("secondary WAN2 interface %s brought up", wan2)
            self._configure_wan_ip(wan2, self.cfg.wan2_proto, self.cfg.wan2_ip, self.cfg.wan2_netmask, "")
            firewall.enable_nat_for_wan2(wan2, self.lan_ifaces)
            self._apply_wan2_routing(wan2)

        return True

    def teardown(self) -> bool:
        if getattr(self, "dmz_iface", ""):
            interfaces.flush_ip_addresses(self.dmz_iface)
            self.dmz_iface = ""
        log.info("tearing down Mode A")
        firewall.disable_nat()
        self.svc_mgr.stop_all()

        if interfaces.interface_exists("br-lan"):
            lan_ports = list(getattr(self.cfg, "lan_ports", None) or [])
            if self.usb_wan and self.cfg.wan_interface not in lan_ports:
                lan_ports.append(self.cfg.wan_interface)
            interfaces.teardown_bridge("br-lan", [p for p in lan_ports if p != "br-lan" and not interfaces.usb_tether_kind(p)])
        if self.usb_wan and interfaces.interface_exists(self.cfg.wan_interface):
            interfaces.flush_ip_addresses(self.cfg.wan_interface)
        for p in getattr(self, "nm_released", []):
            self.svc_mgr.return_to_network_manager(p)
        self.nm_released = []
        self.usb_wan = None
        self.pppoe_iface = ""
        self._pppd_retry_at = 0.0
        from nmb.netd import usb_uplink
        usb_uplink.set_router_wan(None)

        if interfaces.interface_exists(self.cfg.lan_interface) and not interfaces.usb_tether_kind(self.cfg.lan_interface):
            interfaces.flush_ip_addresses(self.cfg.lan_interface)

        if self.cfg.pppoe_vlan > 0:
            vlan_iface = f"{self.cfg.wan_interface}.{self.cfg.pppoe_vlan}"
            if interfaces.interface_exists(vlan_iface):
                ip_bin = shutil.which("ip")
                if ip_bin:
                    interfaces.run_cmd([ip_bin, "link", "delete", "dev", vlan_iface], check=False)

        self.lan_ifaces = []
        return True

    def get_status(self) -> dict:
        wan2_iface = getattr(self.cfg, "wan2_interface", "")
        return {
            "mode": "mode_a",
            "wan_interface": self.active_wan,
            "wan_carrier": interfaces.get_carrier(self.cfg.wan_interface),
            "wan_addrs": interfaces.get_ip_addresses(self.active_wan),
            "wan2_interface": wan2_iface,
            "wan2_carrier": interfaces.get_carrier(wan2_iface) if wan2_iface else False,
            "wan2_addrs": interfaces.get_ip_addresses(wan2_iface) if wan2_iface else [],
            "lan_interfaces": self.lan_ifaces,
            "lan_ports": getattr(self.cfg, "lan_ports", [self.cfg.lan_interface]),
            "lan_carrier": interfaces.get_carrier(self.cfg.lan_interface),
            "lan_addrs": interfaces.get_ip_addresses(self.lan_ifaces[0]) if self.lan_ifaces else [],
            "dnsmasq_running": self.svc_mgr.processes.get("dnsmasq") is not None and self.svc_mgr.processes["dnsmasq"].is_running(),
            "hostapd_running": self.svc_mgr.processes.get("hostapd") is not None and self.svc_mgr.processes["hostapd"].is_running(),
            "pppoe_running": self.svc_mgr.processes.get("pppd") is not None and self.svc_mgr.processes["pppd"].is_running(),
            "pppoe_error": self.pppoe_error,
        }


class ModeB(NetworkMode):
    """Mode B: Passive Inline Probe (Transparent Bridge)."""

    def __init__(self, cfg: NetworkConfig, svc_mgr: ServiceManager):
        super().__init__(cfg, svc_mgr)
        self.wlan_active = False

    def setup(self) -> bool:
        log.info("initializing Mode B (Passive Inline Bridge)")
        # 1. Clean up any lingering Mode A processes or NAT
        firewall.disable_nat()
        self.svc_mgr.stop_all()

        # 2. Setup transparent bridge br0 with wan + lan interfaces
        members = self._bridge_members()
        ok = interfaces.setup_bridge(self.cfg.bridge_interface, members)
        if not ok:
            log.error("failed to setup bridge %s", self.cfg.bridge_interface)
            return False

        # 3. Trigger DHCP request on br0 if no IP assigned so probe can communicate
        self._request_management_ip()

        # 4. Bring up Diagnostic Wi-Fi AP if enabled
        wlan = self.cfg.wlan_interface or "wlan0"
        # The access point runs only in router mode (owner's choice, 2026-11-09). Here the radio stays a Wi-Fi
        # client of the home network, which is the box's second internet; give it back if an AP held it.
        if interfaces.interface_exists(wlan):
            self.svc_mgr.return_to_network_manager(wlan, reconnect=True)

        return True

    def _bridge_members(self) -> List[str]:
        """WAN plus every physical LAN port; br-lan is only a Mode A device."""
        lan_ports = getattr(self.cfg, "lan_ports", None) or [self.cfg.lan_interface]
        return [self.cfg.wan_interface] + [p for p in lan_ports if p != "br-lan" and not interfaces.usb_tether_kind(p)]

    def _request_management_ip(self) -> None:
        """Attempt to obtain an IP on br0 using dhclient / udhcpc / dhcpcd if present."""
        br = self.cfg.bridge_interface
        # A bridge always gets an IPv6 link-local address, which gives no route to the internet.
        current_addrs = [a for a in interfaces.get_ip_addresses(br) if "." in a]
        if current_addrs:
            log.info("bridge %s already has address: %s", br, current_addrs)
            return

        for client, cmd in [
            ("dhclient", ["dhclient", "-1", "-v", br]),
            ("udhcpc", ["udhcpc", "-i", br, "-n", "-q"]),
            ("dhcpcd", ["dhcpcd", "-1", "-t", "10", br]),
        ]:
            if shutil.which(client):
                log.info("requesting management lease on %s using %s", br, client)
                res = subprocess.run(cmd, capture_output=True, text=True)
                if res.returncode == 0:
                    log.info("successfully obtained IP lease on %s", br)
                    return
                log.debug("%s exited %d: %s", client, res.returncode, res.stderr.strip())

    def teardown(self) -> bool:
        log.info("tearing down Mode B")
        if self.wlan_active:
            self.svc_mgr.stop_hostapd()
            self.svc_mgr.stop_dnsmasq()
            wlan = self.cfg.wlan_interface or "wlan0"
            if interfaces.interface_exists(wlan):
                interfaces.flush_ip_addresses(wlan)
            self.wlan_active = False

        members = self._bridge_members()
        return interfaces.teardown_bridge(self.cfg.bridge_interface, members)

    def get_status(self) -> dict:
        br = self.cfg.bridge_interface
        wlan = self.cfg.wlan_interface or "wlan0"
        return {
            "mode": "mode_b",
            "bridge": br,
            "bridge_state": interfaces.get_operstate(br),
            "bridge_addrs": interfaces.get_ip_addresses(br),
            "wan_interface": self.cfg.wan_interface,
            "wan_carrier": interfaces.get_carrier(self.cfg.wan_interface),
            "lan_interface": self.cfg.lan_interface,
            "lan_carrier": interfaces.get_carrier(self.cfg.lan_interface),
            "wifi_enabled": self.cfg.wifi_enabled,
            "wlan_interface": wlan,
            "wlan_carrier": interfaces.get_carrier(wlan) if interfaces.interface_exists(wlan) else False,
            "wlan_addrs": interfaces.get_ip_addresses(wlan) if interfaces.interface_exists(wlan) else [],
            "hostapd_running": self.svc_mgr.processes.get("hostapd") is not None and self.svc_mgr.processes["hostapd"].is_running(),
            "dnsmasq_running": self.svc_mgr.processes.get("dnsmasq") is not None and self.svc_mgr.processes["dnsmasq"].is_running(),
        }


class ModeStandalone(NetworkMode):
    """Endpoint probe on an existing LAN, with optional LAN passthrough and link aggregation."""

    def __init__(self, cfg: NetworkConfig, svc_mgr: ServiceManager):
        super().__init__(cfg, svc_mgr)
        self.wlan_active = False
        self.topology: Optional[lan_topology.Topology] = None

    def setup(self) -> bool:
        log.info("initializing Standalone Mode (LAN endpoint probe)")
        firewall.disable_nat()
        self.svc_mgr.stop_all()

        # Identify active interface from default gateway route or fallback to configured wan_interface
        default_iface = interfaces.get_default_gateway_iface()
        self.active_wan = default_iface if default_iface and interfaces.interface_exists(default_iface) else self.cfg.wan_interface

        # LAN passthrough / link aggregation: the probe's IP moves to the bridge or bond. In mode = auto on a
        # box with several wired ports, the other ports join the WAN port's bridge (switch-like).
        topo_cfg = self.cfg
        auto_pt = list(getattr(self, "auto_passthrough", []) or [])
        if auto_pt and not self.cfg.lan_passthrough_enabled and not self.cfg.lag_enabled:
            import dataclasses
            topo_cfg = dataclasses.replace(self.cfg, lan_passthrough_enabled=True, passthrough_ports=auto_pt)
        self.topology = lan_topology.apply_topology(topo_cfg)
        if self.topology:
            self.active_wan = self.topology.ip_device
            if not interfaces.get_ip_addresses(self.active_wan) and not interfaces.request_dhcp_lease(self.active_wan):
                log.warning("no DHCP lease obtained on %s", self.active_wan)
        log.info("standalone mode active on interface: %s", self.active_wan)

        # 2. Configure Diagnostic Wi-Fi AP if enabled (crucial for wireless access in non-router mode)
        wlan = self.cfg.wlan_interface or "wlan0"
        # The access point runs only in router mode (owner's choice, 2026-11-09). Here the radio stays a Wi-Fi
        # client of the home network, which is the box's second internet; give it back if an AP held it.
        if interfaces.interface_exists(wlan):
            self.svc_mgr.return_to_network_manager(wlan, reconnect=True)

        return True

    def teardown(self) -> bool:
        log.info("tearing down Standalone Mode")
        lan_topology.teardown_topology(self.topology)
        self.topology = None
        if self.wlan_active:
            self.svc_mgr.stop_hostapd()
            self.svc_mgr.stop_dnsmasq()
            firewall.disable_nat()
            wlan = self.cfg.wlan_interface or "wlan0"
            if interfaces.interface_exists(wlan):
                interfaces.flush_ip_addresses(wlan)
            self.wlan_active = False
        return True

    def get_status(self) -> dict:
        iface = self.active_wan or self.cfg.wan_interface
        wlan = self.cfg.wlan_interface or "wlan0"
        return {
            "mode": "standalone",
            "interface": iface,
            "carrier": interfaces.get_carrier(iface),
            "addresses": interfaces.get_ip_addresses(iface),
            "operstate": interfaces.get_operstate(iface),
            "lan_topology": lan_topology.get_runtime_status(self.cfg),
            "wifi_enabled": self.cfg.wifi_enabled,
            "wlan_interface": wlan,
            "wlan_carrier": interfaces.get_carrier(wlan) if interfaces.interface_exists(wlan) else False,
            "wlan_addrs": interfaces.get_ip_addresses(wlan) if interfaces.interface_exists(wlan) else [],
            "hostapd_running": self.svc_mgr.processes.get("hostapd") is not None and self.svc_mgr.processes["hostapd"].is_running(),
            "dnsmasq_running": self.svc_mgr.processes.get("dnsmasq") is not None and self.svc_mgr.processes["dnsmasq"].is_running(),
        }

