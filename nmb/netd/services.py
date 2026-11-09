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
from typing import Any, Dict, List, Optional

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


def _write_private(path: Path, content: str, mode: int = 0o600) -> None:
    """Write a generated config as a new file owned by this process, then set its mode.

    The run directory is shared with the web server (group nmb); a file left there by another user
    can be rewritten but not chmod-ed by nmb-netd, which runs without CAP_FOWNER, so the old file is
    replaced instead of edited.
    """
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(content)
    os.chmod(tmp, mode)
    os.replace(tmp, path)


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
        _write_private(conf_file, conf_content, mode=0o644)

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

    def return_to_network_manager(self, iface: str, reconnect: bool = False) -> None:
        """Give an interface back to NetworkManager (its saved Wi-Fi or Ethernet profile reconnects).

        reconnect: also ask it to connect now when it is not, since a device that was disconnected by
        hand (or taken by an access point) does not connect again by itself.
        """
        nmcli = shutil.which("nmcli")
        if nmcli:
            subprocess.run([nmcli, "device", "set", iface, "managed", "yes"], capture_output=True, timeout=10, check=False)
            if reconnect:
                st = subprocess.run([nmcli, "-g", "GENERAL.STATE", "device", "show", iface],
                                    capture_output=True, text=True, timeout=10, check=False).stdout.strip()
                if not st.startswith("100"):
                    subprocess.run([nmcli, "--wait", "0", "device", "connect", iface],
                                   capture_output=True, timeout=10, check=False)

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
        # NetworkManager leaves the client's address and routes on a device it lets go. On an access point
        # they are poison: the old default route through the radio (metric 600) would beat the real WAN
        # (USB tethering has 900) and send the box's own traffic into its own access point.
        ip_bin = shutil.which("ip")
        if ip_bin:
            # Only what a DHCP client left (dynamic address, its routes): the access point's own static
            # address, added just before in standalone mode, must stay, or dnsmasq cannot bind (2026-11-09).
            subprocess.run([ip_bin, "-4", "addr", "flush", "dev", iface, "dynamic"], capture_output=True, timeout=10, check=False)
            subprocess.run([ip_bin, "-4", "route", "flush", "dev", iface, "proto", "dhcp"], capture_output=True, timeout=10, check=False)
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
            _write_private(conf_file, conf_content)
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
            self.return_to_network_manager(self.cfg.wlan_interface or "wlan0")

    def start_pppd(self, iface: str) -> bool:
        pppd_bin = shutil.which("pppd")
        if not pppd_bin:
            log.error("pppd binary not found")
            return False
        pid_file = self.run_dir / "pppd.pid"
        cmd = build_pppd_cmd(pppd_bin, self.cfg, iface, self.run_dir / "ppp-options")
        proc = ManagedProcess("pppd", cmd, pid_file)
        self.processes["pppd"] = proc
        return proc.start()

    def pppd_exit_code(self) -> Optional[int]:
        """pppd's exit code once it has given up, None while it runs (or was never started here)."""
        proc = self.processes.get("pppd")
        if proc is None or proc.proc is None:
            return None
        return proc.proc.poll()

    def stop_pppd(self) -> None:
        if "pppd" in self.processes:
            self.processes["pppd"].stop()
            del self.processes["pppd"]

    def stop_all(self) -> None:
        self.stop_pppd()
        self.stop_dnsmasq()
        self.stop_hostapd()


def kernel_pppoe_plugin() -> str:
    """The pppd kernel-mode PPPoE plugin when installed ("pppoe.so" on pppd 2.5, "rp-pppoe.so" before)."""
    if os.environ.get("NMB_PPPOE_USERSPACE") == "1":
        return ""
    for base in sorted(Path("/usr/lib/pppd").glob("*"), reverse=True):
        for name in ("pppoe.so", "rp-pppoe.so"):
            if (base / name).is_file():
                return name
    return ""


def _ppp_quote(value: str) -> str:
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


# pppd exit codes (pppd(8)) that mean something to the owner.
PPPD_EXIT_AUTH = 19
PPPD_EXIT_TEXT = {
    PPPD_EXIT_AUTH: "the ISP refused the PPPoE user name or password",
    8: "no PPPoE server answered on the WAN port (cable, ONT or service name)",
    10: "the PPP link could not be negotiated with the ISP",
    15: "the ISP stopped answering on the PPP link",
    16: "the PPPoE line went down",
}


def build_pppd_cmd(pppd_bin: str, cfg: Any, iface: str, options_file: Path, linkname: str = "nmb-pppoe",
                   default_route: bool = True, maxfail: int = 3, peer_dns: bool = True) -> List[str]:
    """The pppd command for PPPoE on iface. The user name and password go into a private options file:
    on the command line (as before 2026-11-09) every local user could read them with `ps`.

    maxfail: pppd gives up after this many failed attempts in a row, and nmb-netd decides when to dial
    again (ModeA.check_pppd). With `maxfail 0` pppd redialed every 8 s for ever, also with a wrong
    password: 5 refused logins in 40 s on 2026-11-09, after which the ISP did not answer for a while."""
    options_file.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(options_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(f"user {_ppp_quote(cfg.pppoe_user)}\npassword {_ppp_quote(cfg.pppoe_password)}\n")
    os.chmod(options_file, 0o600)
    service = str(getattr(cfg, "pppoe_service_name", "") or "").strip()
    plugin = kernel_pppoe_plugin()
    if plugin:
        # Kernel PPPoE: the user-space `pppoe` program (pty) tops out around 300-400 Mbit/s on a
        # Raspberry Pi 4, which would cap what a 1000 Mbit/s line can show (2026-11-09).
        cmd = [pppd_bin, "plugin", plugin, f"nic-{iface}"]
        if service:
            cmd += ["pppoe-service", service]
        cmd += ["noauth", "file", str(options_file)]
    else:
        pppoe_opt = f"pppoe -I {iface} -T 1412"
        if service:
            pppoe_opt += f" -S {service}"
        cmd = [pppd_bin, "pty", pppoe_opt, "noauth", "file", str(options_file)]
    if default_route:
        cmd += ["defaultroute", "replacedefaultroute"]
    if peer_dns:
        # The ISP's DNS servers (Debian's ip-up.d/0000usepeerdns writes them into /etc/resolv.conf).
        cmd.append("usepeerdns")
    return cmd + [
        "hide-password",
        # Redial for as long as the line stays down.
        "persist",
        # Without echo requests pppd never notices a dead line, so it never redials.
        "lcp-echo-interval", "10",
        "lcp-echo-failure", "3",
        "maxfail", str(int(maxfail)),
        "holdoff", "5",
        "nodetach",
        "mtu", "1492",
        "mru", "1492",
        "linkname", linkname,
    ]
