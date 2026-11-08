"""Service supervisor for Mode A helper daemons (dnsmasq, hostapd, pppd).

Manages runtime config generation in /run/nmb and clean subprocess lifecycle.
"""
from __future__ import annotations

import dataclasses
import logging
import os
import shutil
import signal
import subprocess
import time
from pathlib import Path
from typing import Dict, List, Optional

from nmb.config import NetworkConfig

log = logging.getLogger("nmb.netd.services")

DMZ_GATEWAY = "192.168.200.1"
DMZ_DHCP_START = "192.168.200.100"
DMZ_DHCP_END = "192.168.200.200"

HOSTAPD_ATTEMPTS = (
    {},
    {"wifi_standard": "ax", "wifi_channel_width": "80"},
    {"wifi_standard": "ac", "wifi_channel_width": "80"},
    {"wifi_standard": "n", "wifi_channel_width": "20"},
    # Last resort: without a regulatory database the kernel allows no 5/6 GHz
    # channels, so a 2.4 GHz network beats having no Wi-Fi at all.
    {"wifi_band": "2.4ghz", "wifi_channel": 6, "wifi_standard": "n", "wifi_channel_width": "20"},
)


def _service_active(unit: str) -> bool:
    systemctl = shutil.which("systemctl")
    if not systemctl:
        return False
    return subprocess.run([systemctl, "is-active", "--quiet", unit], capture_output=True, check=False).returncode == 0


class ManagedProcess:
    def __init__(self, name: str, cmd: List[str], pid_file: Optional[Path] = None):
        self.name = name
        self.cmd = cmd
        self.pid_file = pid_file
        self.proc: Optional[subprocess.Popen] = None

    def start(self) -> bool:
        if self.is_running():
            log.info("process %s is already running", self.name)
            return True

        bin_path = shutil.which(self.cmd[0])
        if not bin_path:
            log.warning("binary %s not found on system; cannot start %s", self.cmd[0], self.name)
            return False

        try:
            log.info("starting %s: %s", self.name, " ".join(self.cmd))
            self.proc = subprocess.Popen(
                self.cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            time.sleep(0.3)
            if self.proc.poll() is not None:
                log.error("process %s exited immediately with code %d", self.name, self.proc.returncode)
                return False
            if self.pid_file:
                self.pid_file.parent.mkdir(parents=True, exist_ok=True)
                self.pid_file.write_text(str(self.proc.pid))
            return True
        except Exception as e:
            log.error("failed to start %s: %s", self.name, e)
            return False

    def is_running(self) -> bool:
        if self.proc and self.proc.poll() is None:
            return True
        if self.pid_file and self.pid_file.exists():
            try:
                pid = int(self.pid_file.read_text().strip())
                os.kill(pid, 0)
                return True
            except (OSError, ValueError):
                return False
        return False

    def stop(self, timeout: float = 3.0) -> None:
        pids_to_kill: List[int] = []
        if self.proc and self.proc.poll() is None:
            pids_to_kill.append(self.proc.pid)
        if self.pid_file and self.pid_file.exists():
            try:
                pid = int(self.pid_file.read_text().strip())
                if pid not in pids_to_kill:
                    pids_to_kill.append(pid)
            except Exception:
                log.debug("suppressed exception", exc_info=True)

        for pid in pids_to_kill:
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass

        start_time = time.time()
        for pid in pids_to_kill:
            while time.time() - start_time < timeout:
                try:
                    os.kill(pid, 0)
                    time.sleep(0.1)
                except OSError:
                    break
            else:
                try:
                    os.kill(pid, signal.SIGKILL)
                except OSError:
                    pass

        if self.pid_file and self.pid_file.exists():
            try:
                self.pid_file.unlink(missing_ok=True)
            except OSError:
                pass
        self.proc = None
        log.info("process %s stopped", self.name)


class ServiceManager:
    """Coordinates dnsmasq, hostapd, and pppd for Mode A."""

    def __init__(self, run_dir: Path, cfg: NetworkConfig):
        self.run_dir = run_dir
        self.cfg = cfg
        self.processes: Dict[str, ManagedProcess] = {}

    def start_dnsmasq(
        self,
        listen_ifaces: List[str],
        gateway_ip: Optional[str] = None,
        dhcp_start: Optional[str] = None,
        dhcp_end: Optional[str] = None,
        netmask: Optional[str] = None,
        dmz_iface: str = "",
    ) -> bool:
        dnsmasq_bin = shutil.which("dnsmasq")
        if not dnsmasq_bin:
            log.error("dnsmasq binary not found")
            return False

        conf_file = self.run_dir / "dnsmasq.conf"
        lease_file = self.run_dir / "dnsmasq.leases"
        pid_file = self.run_dir / "dnsmasq.pid"

        gw_ip = gateway_ip or self.cfg.gateway_ip
        start = dhcp_start or self.cfg.dhcp_range_start
        end = dhcp_end or self.cfg.dhcp_range_end
        mask = netmask or self.cfg.gateway_netmask

        iface_lines = "\n".join(f"interface={iface}" for iface in listen_ifaces + ([dmz_iface] if dmz_iface else []))
        dmz_lines = ""
        if dmz_iface:
            dmz_lines = (f"dhcp-range=set:dmz,{DMZ_DHCP_START},{DMZ_DHCP_END},255.255.255.0,{self.cfg.dhcp_lease_time}\n"
                         f"dhcp-option=tag:dmz,option:router,{DMZ_GATEWAY}\n"
                         f"dhcp-option=tag:dmz,option:dns-server,{DMZ_GATEWAY}\n")
        # The built-in DNS filter owns port 53 when it runs; dnsmasq then serves DHCP only.
        dns_port = "port=0\n" if _service_active("nmb-adblock.service") else ""
        conf_content = f"""# Auto-generated by NetworkMeasureBox netd
{dns_port}domain-needed
bogus-priv
no-resolv
server=1.1.1.1
server=8.8.8.8
server=9.9.9.9
bind-interfaces
# The lease file lives in /run and is lost on reboot; as the only DHCP server on
# its LAN, answer a client's renewal at once instead of making it start over.
dhcp-authoritative
{iface_lines}
dhcp-range=set:lan,{start},{end},{mask},{self.cfg.dhcp_lease_time}
dhcp-option=tag:lan,option:router,{gw_ip}
dhcp-option=tag:lan,option:dns-server,{gw_ip}
{dmz_lines}dhcp-leasefile={lease_file}
pid-file={pid_file}
"""
        self.run_dir.mkdir(parents=True, exist_ok=True)
        conf_file.write_text(conf_content)

        proc = ManagedProcess("dnsmasq", [dnsmasq_bin, "--conf-file=" + str(conf_file), "--keep-in-foreground"], pid_file)
        self.processes["dnsmasq"] = proc
        return proc.start()

    def stop_dnsmasq(self) -> None:
        if "dnsmasq" in self.processes:
            self.processes["dnsmasq"].stop()
            del self.processes["dnsmasq"]

    def _release_from_network_manager(self, iface: str) -> None:
        """NetworkManager would otherwise keep using the radio as a Wi-Fi client."""
        nmcli = shutil.which("nmcli")
        if nmcli:
            subprocess.run([nmcli, "device", "set", iface, "managed", "no"], capture_output=True, timeout=10, check=False)

    def start_hostapd(self, iface: str, bridge: Optional[str] = None) -> bool:
        hostapd_bin = shutil.which("hostapd")
        if not hostapd_bin:
            log.warning("hostapd binary not found; skipping Wi-Fi AP")
            return False

        conf_file = self.run_dir / "hostapd.conf"
        pid_file = self.run_dir / "hostapd.pid"

        from nmb.netd.wifi import generate_hostapd_config, weak_wifi_password
        security = str(getattr(self.cfg, "wifi_security", "wpa2") or "wpa2").strip().lower()
        if security not in ("open", "none") and weak_wifi_password(getattr(self.cfg, "wifi_psk", "")):
            log.error("Wi-Fi access point not started: its password is the shared factory one or not 8-63 characters; set one in Settings > Wi-Fi")
            return False
        self._release_from_network_manager(iface)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        # The radio may report features the installed hostapd cannot use, so step down until one starts.
        for overrides in HOSTAPD_ATTEMPTS:
            cfg = dataclasses.replace(self.cfg, **overrides)
            conf_content, meta = generate_hostapd_config(cfg, iface, self.run_dir)
            if bridge:
                conf_content = conf_content.rstrip("\n") + f"\nbridge={bridge}\n"
            log.info("generated hostapd config for %s: Standard=%s, Band=%s, Ch=%s, Width=%s MHz",
                     iface, meta.get("effective_standard", "").upper(), meta.get("effective_band"),
                     meta.get("effective_channel"), meta.get("effective_width_mhz"))
            conf_file.write_text(conf_content)
            os.chmod(conf_file, 0o600)
            proc = ManagedProcess("hostapd", [hostapd_bin, str(conf_file)], pid_file)
            if proc.start():
                self.processes["hostapd"] = proc
                return True
            log.warning("hostapd did not start with Standard=%s; trying a simpler setup", meta.get("effective_standard"))
        return False

    def stop_hostapd(self) -> None:
        if "hostapd" in self.processes:
            self.processes["hostapd"].stop()
            del self.processes["hostapd"]

    def start_pppd(self, iface: str) -> bool:
        pppd_bin = shutil.which("pppd")
        if not pppd_bin:
            log.error("pppd binary not found")
            return False

        secrets_file = self.run_dir / "ppp-secrets"
        pid_file = self.run_dir / "pppd.pid"

        secrets_file.write_text(f'"{self.cfg.pppoe_user}" * "{self.cfg.pppoe_password}" *\n')
        secrets_file.chmod(0o600)

        pppoe_opt = f"pppoe -I {iface} -T 1412"
        if getattr(self.cfg, "pppoe_service_name", None):
            pppoe_opt += f" -S {self.cfg.pppoe_service_name}"

        cmd = [
            pppd_bin,
            "pty", pppoe_opt,
            "noauth",
            "user", self.cfg.pppoe_user,
            "password", self.cfg.pppoe_password,
            "defaultroute",
            "replacedefaultroute",
            "hide-password",
            # Redial for as long as the line stays down.
            "persist",
            # Without echo requests pppd never notices a dead line, so it never redials.
            "lcp-echo-interval", "10",
            "lcp-echo-failure", "3",
            "maxfail", "0",
            "holdoff", "5",
            "nodetach",
            "usepeerdns",
            "mtu", "1492",
            "mru", "1492",
            "linkname", "nmb-pppoe",
        ]
        proc = ManagedProcess("pppd", cmd, pid_file)
        self.processes["pppd"] = proc
        return proc.start()

    def stop_pppd(self) -> None:
        if "pppd" in self.processes:
            self.processes["pppd"].stop()
            del self.processes["pppd"]

    def stop_all(self) -> None:
        self.stop_pppd()
        self.stop_dnsmasq()
        self.stop_hostapd()
