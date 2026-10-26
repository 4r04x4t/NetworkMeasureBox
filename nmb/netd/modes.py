"""Network modes: Mode A (Active Gateway / NAT / AP) and Mode B (Passive Inline Bridge).

Each mode provides setup() and teardown() ensuring clean, idempotent transitions.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
from abc import ABC, abstractmethod
from typing import List, Optional

from nmb.config import NetworkConfig
from nmb.netd import firewall, interfaces
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

    def setup(self) -> bool:
        log.info("initializing Mode A (Active Gateway / NAT)")
        self.lan_ifaces = []

        # 1. Bring up WAN
        if getattr(self.cfg, "wan_mac", None):
            interfaces.set_mac_address(self.cfg.wan_interface, self.cfg.wan_mac)
        wan = self._setup_vlan_if_needed()
        interfaces.set_link_up(self.cfg.wan_interface)
        interfaces.set_link_up(wan)
        self.active_wan = wan

        if self.cfg.pppoe_enabled and self.cfg.pppoe_user:
            log.info("launching PPPoE client on %s", wan)
            self.svc_mgr.start_pppd(wan)
            self.active_wan = "ppp0"

        # 2. Configure LAN interfaces (Single LAN or Bridge br-lan for Multi-LAN ports)
        lan_ports = getattr(self.cfg, "lan_ports", None) or [self.cfg.lan_interface]
        lan_ports = [p.strip() for p in lan_ports if p.strip() and interfaces.interface_exists(p.strip())]

        if len(lan_ports) > 1:
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
        elif interfaces.interface_exists(self.cfg.lan_interface):
            log.info("configuring fallback LAN interface %s with %s", self.cfg.lan_interface, self.cfg.gateway_ip)
            interfaces.flush_ip_addresses(self.cfg.lan_interface)
            interfaces.set_link_up(self.cfg.lan_interface)
            interfaces.add_ip_address(self.cfg.lan_interface, f"{self.cfg.gateway_ip}/24")
            self.lan_ifaces.append(self.cfg.lan_interface)

        # 3. Configure Wi-Fi Diagnostic AP if enabled
        if self.cfg.wifi_enabled and interfaces.interface_exists(self.cfg.wlan_interface):
            log.info("configuring Diagnostic Wi-Fi on %s", self.cfg.wlan_interface)
            interfaces.set_link_up(self.cfg.wlan_interface)
            self.svc_mgr.start_hostapd(self.cfg.wlan_interface)
            self.lan_ifaces.append(self.cfg.wlan_interface)

        # 4. Start dnsmasq for LAN interfaces
        if self.lan_ifaces:
            self.svc_mgr.start_dnsmasq(self.lan_ifaces)

        # 5. Enable NAT and IPv4 forwarding
        firewall.enable_nat_mode_a(self.active_wan, self.lan_ifaces)

        # 6. Bring up Secondary WAN2 if configured
        wan2 = getattr(self.cfg, "wan2_interface", "")
        if wan2 and interfaces.interface_exists(wan2):
            interfaces.set_link_up(wan2)
            log.info("secondary WAN2 interface %s brought up", wan2)
            firewall.enable_nat_for_wan2(wan2, self.lan_ifaces)

        return True

    def teardown(self) -> bool:
        log.info("tearing down Mode A")
        firewall.disable_nat()
        self.svc_mgr.stop_all()

        if interfaces.interface_exists("br-lan"):
            lan_ports = getattr(self.cfg, "lan_ports", None) or []
            interfaces.teardown_bridge("br-lan", [p for p in lan_ports if p != "br-lan"])

        if interfaces.interface_exists(self.cfg.lan_interface):
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
        }


class ModeB(NetworkMode):
    """Mode B: Passive Inline Probe (Transparent Bridge)."""

    def setup(self) -> bool:
        log.info("initializing Mode B (Passive Inline Bridge)")
        # 1. Clean up any lingering Mode A processes or NAT
        firewall.disable_nat()
        self.svc_mgr.stop_all()

        # 2. Setup transparent bridge br0 with wan + lan interfaces
        members = [self.cfg.wan_interface, self.cfg.lan_interface]
        ok = interfaces.setup_bridge(self.cfg.bridge_interface, members)
        if not ok:
            log.error("failed to setup bridge %s", self.cfg.bridge_interface)
            return False

        # 3. Trigger DHCP request on br0 if no IP assigned so probe can communicate
        self._request_management_ip()
        return True

    def _request_management_ip(self) -> None:
        """Attempt to obtain an IP on br0 using dhclient / udhcpc / dhcpcd if present."""
        br = self.cfg.bridge_interface
        current_addrs = interfaces.get_ip_addresses(br)
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
        members = [self.cfg.wan_interface, self.cfg.lan_interface]
        return interfaces.teardown_bridge(self.cfg.bridge_interface, members)

    def get_status(self) -> dict:
        br = self.cfg.bridge_interface
        return {
            "mode": "mode_b",
            "bridge": br,
            "bridge_state": interfaces.get_operstate(br),
            "bridge_addrs": interfaces.get_ip_addresses(br),
            "wan_interface": self.cfg.wan_interface,
            "wan_carrier": interfaces.get_carrier(self.cfg.wan_interface),
            "lan_interface": self.cfg.lan_interface,
            "lan_carrier": interfaces.get_carrier(self.cfg.lan_interface),
        }


class ModeStandalone(NetworkMode):
    """Mode Standalone: Endpoint Probe on existing LAN (does not alter physical interfaces)."""

    def setup(self) -> bool:
        log.info("initializing Standalone Mode (LAN endpoint probe)")
        firewall.disable_nat()
        self.svc_mgr.stop_all()

        # Identify active interface from default gateway route or fallback to configured wan_interface
        default_iface = interfaces.get_default_gateway_iface()
        self.active_wan = default_iface if default_iface and interfaces.interface_exists(default_iface) else self.cfg.wan_interface
        log.info("standalone mode active on interface: %s", self.active_wan)
        return True

    def teardown(self) -> bool:
        log.info("tearing down Standalone Mode")
        return True

    def get_status(self) -> dict:
        iface = self.active_wan or self.cfg.wan_interface
        return {
            "mode": "standalone",
            "interface": iface,
            "carrier": interfaces.get_carrier(iface),
            "addresses": interfaces.get_ip_addresses(iface),
            "operstate": interfaces.get_operstate(iface),
        }

