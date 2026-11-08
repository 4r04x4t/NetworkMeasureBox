"""NetworkMeasureBox configuration parser and defaults.

Reads /etc/nmb/nmb.conf (or path in NMB_CONFIG) with structured defaults.
Uses configparser (standard library).
"""
from __future__ import annotations

import configparser
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

log = logging.getLogger("nmb.config")


class _TolerantParser(configparser.ConfigParser):
    """One bad value must not stop every service, and % is ordinary text in values such as passwords."""

    def __init__(self) -> None:
        super().__init__(interpolation=None)

    def _convert(self, getter, section, option, **kwargs):
        try:
            return getter(section, option, **kwargs)
        except ValueError:
            log.warning("ignoring invalid value for [%s] %s; using the default", section, option)
            if "fallback" in kwargs and kwargs["fallback"] is not configparser._UNSET:
                return kwargs["fallback"]
            defaults = _TolerantParser()
            defaults.read_string(DEFAULT_CONFIG_TEXT)
            return getattr(defaults, getter.__name__)(section, option)

    def getint(self, section, option, **kwargs):
        return self._convert(super().getint, section, option, **kwargs)

    def getfloat(self, section, option, **kwargs):
        return self._convert(super().getfloat, section, option, **kwargs)

    def getboolean(self, section, option, **kwargs):
        return self._convert(super().getboolean, section, option, **kwargs)

DEFAULT_CONFIG_PATH = Path(os.environ.get("NMB_CONFIG", "/etc/nmb/nmb.conf"))
FALLBACK_CONFIG_PATH = Path("/opt/nmb/config/nmb.conf")

DRIVE_CONFIG_LOCATIONS = [
    Path("/boot/firmware/nmb.conf"),  # Debian / Raspberry Pi OS Bookworm FAT32 partition
    Path("/boot/nmb.conf"),           # Bullseye / Armbian / Generic EFI FAT32 partition
    Path("/boot/firmware/nmb.ini"),
    Path("/boot/nmb.ini"),
]


def find_drive_config_path() -> Optional[Path]:
    """Search for drive-editable config file on FAT32 boot partition or removable media."""
    for loc in DRIVE_CONFIG_LOCATIONS:
        if loc.is_file():
            return loc
    return None


def get_writable_drive_config_target() -> Optional[Path]:
    """Find appropriate writable drive location to mirror nmb.conf."""
    for loc in DRIVE_CONFIG_LOCATIONS:
        parent = loc.parent
        if parent.is_dir():
            try:
                test = parent / ".nmb_drive_write_test"
                test.touch()
                test.unlink(missing_ok=True)
                return loc
            except OSError:
                continue
    return None


SECRET_MARK = "__KEEP_CURRENT__"
_SECRET_KEY = re.compile(r"(password|psk|token|auth_key|secret)", re.I)
_CONFIG_LINE = re.compile(r"^(\s*)([A-Za-z0-9_.-]+)(\s*=\s*)(.*)$")


def mask_secrets(text: str) -> str:
    """Replace secret values, because anyone holding the SD card can read the boot partition."""
    out = []
    for line in text.splitlines():
        match = _CONFIG_LINE.match(line)
        if match and match.group(4).strip() and _SECRET_KEY.search(match.group(2)):
            line = f"{match.group(1)}{match.group(2)}{match.group(3)}{SECRET_MARK}"
        out.append(line)
    return "\n".join(out) + "\n"


def unique_wifi_password(text: str) -> str:
    """Replace the shared factory Wi-Fi password, which would be the same on every box."""
    import secrets
    return re.sub(r"(?m)^(wifi_psk\s*=\s*)NetworkMeasureBox123\s*$", lambda m: m.group(1) + secrets.token_urlsafe(12), text)


def merge_drive_config(drive_text: str, current_text: str) -> str:
    """Apply an edited drive file, keeping current secrets wherever it still has the mark."""
    current = _TolerantParser()
    try:
        current.read_string(current_text)
    except configparser.Error:
        current = _TolerantParser()
    section = ""
    out = []
    for line in drive_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            section = stripped[1:-1]
        match = _CONFIG_LINE.match(line)
        if match and match.group(4).strip() == SECRET_MARK:
            key = match.group(2)
            if not current.has_option(section, key):
                continue
            line = f"{match.group(1)}{key}{match.group(3)}{current.get(section, key)}"
        out.append(line)
    # With no current file the marked secrets are gone, so at least avoid the shared default.
    return unique_wifi_password("\n".join(out) + "\n")


def sync_drive_config(source_path: Path = DEFAULT_CONFIG_PATH) -> Optional[Path]:
    """Synchronize /etc/nmb/nmb.conf to drive-editable FAT32 boot partition."""
    if not source_path.is_file():
        return None
    target = get_writable_drive_config_target()
    if not target:
        # The boot partition belongs to root; the web server asks the helper to write it.
        if os.geteuid() != 0 and Path("/usr/local/bin/nmb-helper").exists():
            import subprocess
            done = subprocess.run(["sudo", "-n", "/usr/local/bin/nmb-helper", "sync-drive-config"],
                                  capture_output=True, timeout=30, check=False)
            if done.returncode == 0:
                return next((loc for loc in DRIVE_CONFIG_LOCATIONS if loc.parent.is_dir()), None)
        return None
    try:
        content = mask_secrets(source_path.read_text(encoding="utf-8"))
        header = (
            "# ==============================================================================\n"
            "# NetworkMeasureBox - Drive-Editable Configuration (Boot/Storage Partition)\n"
            "# Edit this file directly in Windows, macOS, or Linux when the SD card\n"
            "# or USB drive is plugged into your PC.\n"
            f"# Passwords and tokens show {SECRET_MARK}: leave it to keep the value, or type a new one.\n"
            "# ==============================================================================\n\n"
        )
        if not content.startswith("# ==="):
            content = header + content
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".tmp")
        tmp.write_text(content, encoding="utf-8")
        tmp.replace(target)
        log.info("synchronized configuration to drive-editable location: %s", target)
        return target
    except Exception as e:
        log.debug("drive config sync failed: %s", e)
        return None

DEFAULT_CONFIG_TEXT = """# NetworkMeasureBox configuration file
[system]
box_id = nmb-01
data_dir = /var/lib/nmb
run_dir = /run/nmb
log_dir = /var/log/nmb
# Memory profile: auto (auto-detects <= 512MB RAM), low (embedded router mode), standard (1GB-2GB), performance (4GB+)
memory_profile = auto

[network]
# Operational mode: auto, mode_a (active gateway), mode_b (passive inline), standalone (endpoint probe)
mode = standalone
wan_interface = eth0
wan2_interface = 
wan2_proto = dhcp
wan2_ip = 
wan2_netmask = 255.255.255.0
wan2_gateway = 
wan2_mac = 
wan_mode = single
lan_interface = eth1
lan_ports = eth1
bridge_interface = br0
dmz_interface = 
measurement_interface = wan

# Mode A (Active Gateway / PPPoE / NAT / Wi-Fi) settings
gateway_ip = 192.168.100.1
gateway_netmask = 255.255.255.0
dhcp_range_start = 192.168.100.100
dhcp_range_end = 192.168.100.200
dhcp_lease_time = 12h

# PPPoE configuration (optional on WAN)
pppoe_enabled = false
pppoe_user = 
pppoe_password = 
pppoe_vlan = 0

# Diagnostic Wi-Fi AP (hostapd)
wifi_enabled = true
wifi_ssid = NMB-Diagnostic
wifi_psk = NetworkMeasureBox123
wifi_band = auto
wifi_standard = auto
wifi_channel = 0
wifi_channel_width = auto
wifi_country_code = auto
wifi_security = wpa2

# Auto-detection & failover tuning
check_interval_sec = 5
failover_timeout_sec = 15
detection_targets = 1.1.1.1,8.8.8.8,9.9.9.9
dns_fallback_enabled = true
dns_fallback_servers = 1.1.1.1,8.8.8.8,9.9.9.9,208.67.222.222

[probe]
targets = 1.1.1.1,8.8.8.8,9.9.9.9,185.222.222.222
ping_interval_ms = 500
socket_buffer_kb = 256
batch_flush_sec = 10
outage_loss_seconds = 15.0

[traffic_gate]
mode = percent
threshold_percent = 2.0
threshold_kbps = 500
# Experimental: only run speed tests on a provably idle network, and stop them when traffic appears.
experimental_stop = false

[speedtest]
schedule_cron = 0 * * * *
# Stop scheduled tests for the day at this much test traffic, for mobile data. 0 = no limit
daily_data_limit_mb = 0
idle_wait_max_sec = 1800
idle_threshold_mode = percent
idle_threshold_percent = 2.0
idle_threshold_kbps = 500
port_throttle_ports = 80,443,8080,8443,5060,53
server_id = auto
server_name = 
server_host = 

[isp]
name = 
account_id = 
circuit_id = 
contract_down_mbps = 1000.0
guaranteed_down_mbps = 0.0
contract_up_mbps = 300.0
guaranteed_up_mbps = 0.0
connection_type = fiber

[smtp]
enabled = false
host = localhost
port = 587
tls = true
user = 
password = 
from_addr = nmb-reports@example.com
to_addrs = support@isp.com,admin@example.com

[telegram]
enabled = false
token = 
allowed_chat_ids = 
alert_loss_threshold_pct = 5.0
alert_latency_threshold_ms = 100.0
alert_jitter_threshold_ms = 30.0

[guest_wifi]
enabled = false
interface = wlan0
ssid = 
password = 
security = auto
metric = 600
auto_reconnect = true

[web]
enabled = true
host = 0.0.0.0
port = 80
auth_enabled = true
admin_password = admin
public_results = false

[logging]
level = INFO
file_enabled = true
file_path = /var/log/nmb/nmb_developer.log
max_bytes = 10485760
backup_count = 5
console_enabled = true
log_requests = true

[ooni]
# Optional add-on: runs weekly when enabled.
enabled = false

[collector]
# Send measurements to a central collector (nmb-collector) run by an ISP or a specialist.
enabled = false
url = 
token = 
case_id = 
interval_min = 15
# With consent: also send the full network diagnostics (interfaces, routes, DNS, NAT, Wi-Fi,
# traceroute, LAN device list, events) so a specialist can see the whole connection.
share_diagnostics = false
# With consent: the collector may ask the box to run a speed test, send fresh diagnostics or
# upload now. Nothing else: no shell commands and no setting changes.
allow_remote_control = false

[duckdns]
enabled = false
provider = duckdns
domain = 
token = 
update_interval_min = 10
custom_ip = 
custom_ipv6 = 
ipv6_mode = auto 

[wireguard]
enabled = false
port = 51820
subnet = 10.8.0.1/24
subnet_ipv6 = fd42:42:42::1/64
dns = 1.1.1.1, 2606:4700:4700::1111
public_endpoint = 

[openvpn]
enabled = false
proto = udp
port = 1194
subnet = 10.9.0.0
subnet_ipv6 = fd42:42:43::/64
dns = 1.1.1.1, 2606:4700:4700::1111
public_endpoint = 

[proxy]
enabled = false
port = 8443
auth_enabled = false
username = 
password = 
tls_enabled = false
listen_ipv6 = true
dns = 1.1.1.1, 2606:4700:4700::1111

[tailscale]
enabled = false
auth_key = 
hostname = networkmeasurebox
accept_routes = false
advertise_exit_node = false
accept_dns = false
"""


@dataclass
class OoniConfig:
    enabled: bool = False


@dataclass
class SystemConfig:
    box_id: str = "nmb-01"
    data_dir: Path = Path("/var/lib/nmb")
    run_dir: Path = Path("/run/nmb")
    log_dir: Path = Path("/var/log/nmb")
    sqm_algorithm: str = "cake"
    memory_profile: str = "auto"  # auto, low, standard, performance
    # The file this config was loaded from with an explicit path; save_config writes back there.
    config_path: str = ""


@dataclass
class NetworkConfig:
    mode: str = "standalone"  # auto, mode_a, mode_b, standalone
    wan_interface: str = "eth0"
    wan2_interface: str = ""
    wan2_proto: str = "dhcp"   # dhcp, static, pppoe
    wan2_ip: str = ""
    wan2_netmask: str = "255.255.255.0"
    wan2_gateway: str = ""
    wan2_mac: str = ""
    wan_mode: str = "single"   # single, failover, loadbalance

    lan_interface: str = "eth1"
    lan_ports: List[str] = field(default_factory=lambda: ["eth1"])
    dmz_interface: str = ""
    measurement_interface: str = "wan"  # wan, wan2, all, or interface name
    wlan_interface: str = "wlan0"
    bridge_interface: str = "br0"

    # LAN passthrough / link aggregation (standalone probe behind a router)
    lan_passthrough_enabled: bool = False
    passthrough_ports: List[str] = field(default_factory=list)
    lag_enabled: bool = False
    lag_ports: List[str] = field(default_factory=list)
    lag_mode: str = "802.3ad"
    lag_hash_policy: str = "layer3+4"
    lacp_rate: str = "fast"

    # Mode A settings
    gateway_ip: str = "192.168.100.1"
    gateway_netmask: str = "255.255.255.0"
    dhcp_enabled: bool = True
    dhcp_range_start: str = "192.168.100.100"
    dhcp_range_end: str = "192.168.100.200"
    dhcp_lease_time: str = "12h"

    wan_proto: str = "dhcp"   # dhcp, pppoe, static
    wan_ip: str = ""
    wan_netmask: str = "255.255.255.0"
    wan_gateway: str = ""
    pppoe_enabled: bool = False
    pppoe_user: str = ""
    pppoe_password: str = ""
    pppoe_vlan: int = 0
    pppoe_service_name: str = ""
    wan_mac: str = ""
    dns_mode: str = "auto"     # auto, custom
    dns_primary: str = "1.1.1.1"
    dns_secondary: str = "8.8.8.8"
    dns_fallback_enabled: bool = True
    dns_fallback_servers: List[str] = field(default_factory=lambda: ["1.1.1.1", "8.8.8.8", "9.9.9.9", "208.67.222.222"])

    wifi_enabled: bool = True
    wifi_ssid: str = "NMB-Diagnostic"
    wifi_psk: str = "NetworkMeasureBox123"
    wifi_band: str = "auto"              # "auto", "2.4ghz", "5ghz", "6ghz"
    wifi_standard: str = "auto"          # "auto", "be", "ax", "ac", "n", "g", "a", "b"
    wifi_channel: int = 0                # 0 = auto channel selection
    wifi_channel_width: str = "auto"     # "auto", "20", "40", "80", "160", "320"
    wifi_country_code: str = "auto"      # ISO regulatory domain: auto, 00 (world) or a country code such as US or DE
    wifi_security: str = "wpa2"

    # Detection & failover
    check_interval_sec: float = 5.0
    failover_timeout_sec: float = 15.0
    detection_targets: List[str] = field(default_factory=lambda: ["1.1.1.1", "8.8.8.8", "9.9.9.9"])


CONNECTION_TYPES: Dict[str, str] = {
    "fiber": "Fiber / FTTH / GPON",
    "docsis": "Cable TV / DOCSIS / Coax",
    "xdsl": "xDSL (VDSL2 / ADSL2+)",
    "fwa": "Mobile / 4G / 5G / Fixed Wireless (FWA)",
    "dialup": "Dial-Up Modem",
    "satellite": "Satellite (Starlink / Sat)",
    "ethernet": "Structured Ethernet / Leased Line",
    "other": "Other Network",
}


@dataclass
class ISPConfig:
    name: str = ""
    account_id: str = ""
    circuit_id: str = ""
    contract_down_mbps: float = 1000.0
    guaranteed_down_mbps: float = 0.0
    contract_up_mbps: float = 300.0
    guaranteed_up_mbps: float = 0.0
    connection_type: str = "fiber"  # fiber, docsis, xdsl, fwa, dialup, satellite, ethernet, other


@dataclass
class SMTPConfig:
    enabled: bool = False
    host: str = "localhost"
    port: int = 587
    tls: bool = True
    user: str = ""
    password: str = ""
    from_addr: str = "nmb-reports@example.com"
    to_addrs: List[str] = field(default_factory=lambda: ["support@isp.com"])


@dataclass
class TelegramConfig:
    enabled: bool = False
    token: str = ""
    allowed_chat_ids: List[int] = field(default_factory=list)
    alert_loss_threshold_pct: float = 5.0
    alert_latency_threshold_ms: float = 100.0
    alert_jitter_threshold_ms: float = 30.0
    alert_on_loss: bool = True
    alert_on_latency: bool = True


@dataclass
class WebConfig:
    enabled: bool = True
    host: str = "0.0.0.0"
    port: int = 80
    auth_enabled: bool = True
    admin_username: str = "admin"
    admin_password: str = "admin"
    terminal_enabled: bool = False
    # Off by default. When on, devices on the local network may view and download
    # results without the password (read only); settings still need the password.
    public_results: bool = False
    language: str = "en"
    theme: str = "default"
    tls_enabled: bool = False
    tls_cert: str = "/etc/nmb/server.crt"
    tls_key: str = "/etc/nmb/server.key"


@dataclass
class IPerfConfig:
    enabled: bool = False
    target_host: str = ""
    target_port: int = 5201
    duration: int = 10      # seconds per direction
    protocol: str = "tcp"
    parallel: int = 4       # one TCP stream rarely fills a fast line over a long path
    # Automatic tests: "both" measures download (-R) and then upload, one after the other;
    # "download" or "upload" measures one direction only.
    auto_direction: str = "both"
    # More servers for automatic tests, tested one after the other: "host:port, host:port".
    extra_servers: str = ""
    reverse: bool = False
    bidir: bool = False
    schedule_cron: str = "0 */12 * * *"  # kept for older configs; scheduled iPerf3 uses [speedtest] iperf3_interval_min


@dataclass
class ProbeConfig:
    targets: List[str] = field(default_factory=lambda: ["1.1.1.1", "8.8.8.8", "9.9.9.9", "185.222.222.222"])
    ping_interval_ms: float = 500.0
    socket_buffer_kb: int = 256
    batch_flush_sec: float = 10.0
    outage_loss_seconds: float = 15.0


@dataclass
class SpeedtestConfig:
    schedule_mode: str = "scheduled"          # "scheduled" (periodic automation) or "manual" (disabled / on-demand only)
    schedule_cron: str = "0 * * * *"
    automated_engine: str = "ookla"           # "ookla", "cloudflare", "rtr", "all"
    # Per-engine minimum minutes between scheduled tests (0 = every scheduled run).
    # Ookla never runs more often than hourly, since it blocks boxes that test more often.
    ookla_interval_min: int = 60
    rtr_interval_min: int = 0
    cloudflare_interval_min: int = 0
    iperf3_interval_min: int = 0
    idle_wait_max_sec: float = 1800.0
    idle_threshold_mode: str = "percent"      # "percent" (< 2% network load) or "fixed" (custom kbps)
    idle_threshold_percent: float = 2.0       # dynamic network load threshold (e.g. 2.0%)
    idle_threshold_kbps: int = 500            # fallback fixed kbps
    daily_data_limit_mb: float = 0.0          # Scheduled tests stop for the day at this usage; 0 = no limit
    traffic_stop_enabled: bool = False        # Experimental: strict idle check and stop on foreign traffic
    server_id: Optional[int] = None           # Manually selected server ID for automated measurements!
    server_name: str = ""
    server_host: str = ""
    port_throttle_ports: List[int] = field(default_factory=lambda: [80, 443, 8080, 8443, 5060, 53])
    user_agent: str = ""                      # Custom User-Agent string when mode is 'custom'
    user_agent_mode: str = "auto_fresh"       # 'auto_fresh', 'custom', or preset key


@dataclass
class LoggingConfig:
    level: str = "DEBUG"
    file_enabled: bool = True
    file_path: str = "/var/log/nmb/nmb_developer.log"
    max_bytes: int = 10485760  # 10 MB
    backup_count: int = 5
    console_enabled: bool = True
    log_requests: bool = True


@dataclass
class GuestWiFiConfig:
    enabled: bool = False
    interface: str = "wlan0"
    ssid: str = ""
    password: str = ""
    security: str = "auto"
    metric: int = 600
    auto_reconnect: bool = True


@dataclass
class CollectorConfig:
    enabled: bool = False
    url: str = ""          # e.g. https://collector.example.net:8600
    token: str = ""        # the collector's ingest token
    case_id: str = ""      # ticket or customer number the measurements belong to
    interval_min: int = 15
    share_diagnostics: bool = False  # full network diagnostics and events, only with consent
    allow_remote_control: bool = False  # collector may start a speed test, diagnostics or an upload


@dataclass
class DuckDNSConfig:
    enabled: bool = False
    provider: str = "duckdns"  # "duckdns" or "dynv6"
    domain: str = ""
    token: str = ""
    update_interval_min: int = 10
    custom_ip: str = ""
    custom_ipv6: str = ""
    ipv6_mode: str = "auto"  # "auto", "custom", "none"


@dataclass
class WireGuardConfig:
    enabled: bool = False
    port: int = 51820
    subnet: str = "10.8.0.1/24"
    subnet_ipv6: str = "fd42:42:42::1/64"
    dns: str = "1.1.1.1, 2606:4700:4700::1111"
    public_endpoint: str = ""


@dataclass
class OpenVPNConfig:
    enabled: bool = False
    proto: str = "udp"
    port: int = 1194
    subnet: str = "10.9.0.0"
    subnet_ipv6: str = "fd42:42:43::/64"
    dns: str = "1.1.1.1, 2606:4700:4700::1111"
    public_endpoint: str = ""


@dataclass
class ProxyConfig:
    enabled: bool = False
    port: int = 8443
    auth_enabled: bool = False
    username: str = ""
    password: str = ""
    tls_enabled: bool = False
    listen_ipv6: bool = True
    dns: str = "1.1.1.1, 2606:4700:4700::1111"


@dataclass
class TailscaleConfig:
    enabled: bool = False
    auth_key: str = ""
    hostname: str = "networkmeasurebox"
    accept_routes: bool = False
    advertise_exit_node: bool = False
    accept_dns: bool = False


@dataclass
class Config:
    system: SystemConfig = field(default_factory=SystemConfig)
    network: NetworkConfig = field(default_factory=NetworkConfig)
    guest_wifi: GuestWiFiConfig = field(default_factory=GuestWiFiConfig)
    probe: ProbeConfig = field(default_factory=ProbeConfig)
    speedtest: SpeedtestConfig = field(default_factory=SpeedtestConfig)
    iperf: IPerfConfig = field(default_factory=IPerfConfig)
    isp: ISPConfig = field(default_factory=ISPConfig)
    smtp: SMTPConfig = field(default_factory=SMTPConfig)
    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    web: WebConfig = field(default_factory=WebConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    duckdns: DuckDNSConfig = field(default_factory=DuckDNSConfig)
    collector: CollectorConfig = field(default_factory=CollectorConfig)
    ooni: OoniConfig = field(default_factory=OoniConfig)
    wireguard: WireGuardConfig = field(default_factory=WireGuardConfig)
    openvpn: OpenVPNConfig = field(default_factory=OpenVPNConfig)
    proxy: ProxyConfig = field(default_factory=ProxyConfig)
    tailscale: TailscaleConfig = field(default_factory=TailscaleConfig)
    raw_parser: configparser.ConfigParser = field(default_factory=_TolerantParser)


def _clamp_settings(cfg: "Config") -> None:
    """Keep values that would stop a service inside their working range."""
    if not 1 <= cfg.web.port <= 65535:
        log.warning("invalid web port %s; using 80", cfg.web.port)
        cfg.web.port = 80
    if not 10 <= cfg.probe.ping_interval_ms <= 60000:
        log.warning("invalid ping interval %s ms; using 500", cfg.probe.ping_interval_ms)
        cfg.probe.ping_interval_ms = 500


def load_config(path: Path | None = None) -> Config:
    parser = _TolerantParser()
    parser.read_string(DEFAULT_CONFIG_TEXT)

    # 1. Check for drive-editable config updates
    if path is None:
        drive_path = find_drive_config_path()
        if drive_path and drive_path.is_file():
            if not DEFAULT_CONFIG_PATH.exists():
                try:
                    DEFAULT_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
                    DEFAULT_CONFIG_PATH.write_text(merge_drive_config(drive_path.read_text(encoding="utf-8"), ""), encoding="utf-8")
                    log.info("imported initial configuration from drive: %s -> %s", drive_path, DEFAULT_CONFIG_PATH)
                except Exception as e:
                    log.debug("could not copy drive config: %s", e)
            else:
                try:
                    drive_mtime = drive_path.stat().st_mtime
                    default_mtime = DEFAULT_CONFIG_PATH.stat().st_mtime
                    # If drive was edited more recently than /etc/nmb/nmb.conf, load & update
                    if drive_mtime > default_mtime + 2.0:
                        log.info("detected newer configuration on drive (%s); applying to %s", drive_path, DEFAULT_CONFIG_PATH)
                        DEFAULT_CONFIG_PATH.write_text(
                            merge_drive_config(drive_path.read_text(encoding="utf-8"), DEFAULT_CONFIG_PATH.read_text(encoding="utf-8")),
                            encoding="utf-8",
                        )
                    elif default_mtime > drive_mtime + 2.0:
                        sync_drive_config(DEFAULT_CONFIG_PATH)
                except Exception as e:
                    log.debug("drive mtime check exception: %s", e)

    def _safe_exists(p: Optional[Path | str]) -> bool:
        if not p:
            return False
        try:
            return Path(p).exists()
        except (PermissionError, OSError):
            return False

    target_path = path or (
        DEFAULT_CONFIG_PATH if _safe_exists(DEFAULT_CONFIG_PATH) else
        find_drive_config_path() if find_drive_config_path() else
        FALLBACK_CONFIG_PATH if _safe_exists(FALLBACK_CONFIG_PATH) else None
    )

    if target_path and _safe_exists(target_path):
        try:
            parser.read(target_path)
        except (PermissionError, OSError):
            pass

    cfg = Config(raw_parser=parser)

    if parser.has_section("system"):
        s = parser["system"]
        cfg.system.box_id = s.get("box_id", cfg.system.box_id)
        cfg.system.data_dir = Path(s.get("data_dir", str(cfg.system.data_dir)))
        cfg.system.run_dir = Path(s.get("run_dir", str(cfg.system.run_dir)))
        cfg.system.log_dir = Path(s.get("log_dir", str(cfg.system.log_dir)))
        cfg.system.sqm_algorithm = s.get("sqm_algorithm", getattr(cfg.system, "sqm_algorithm", "cake")).strip().lower()
        cfg.system.memory_profile = s.get("memory_profile", getattr(cfg.system, "memory_profile", "auto")).strip().lower()

    if parser.has_section("network"):
        n = parser["network"]
        cfg.network.mode = n.get("mode", cfg.network.mode).lower().strip()
        cfg.network.wan_interface = n.get("wan_interface", cfg.network.wan_interface).strip()
        cfg.network.wan2_interface = n.get("wan2_interface", getattr(cfg.network, "wan2_interface", "")).strip()
        cfg.network.wan2_proto = n.get("wan2_proto", getattr(cfg.network, "wan2_proto", "dhcp")).strip()
        cfg.network.wan2_ip = n.get("wan2_ip", getattr(cfg.network, "wan2_ip", "")).strip()
        cfg.network.wan2_netmask = n.get("wan2_netmask", getattr(cfg.network, "wan2_netmask", "255.255.255.0")).strip()
        cfg.network.wan2_gateway = n.get("wan2_gateway", getattr(cfg.network, "wan2_gateway", "")).strip()
        cfg.network.wan2_mac = n.get("wan2_mac", getattr(cfg.network, "wan2_mac", "")).strip()
        cfg.network.wan_mode = n.get("wan_mode", getattr(cfg.network, "wan_mode", "single")).strip().lower()
        if cfg.network.wan_mode == "dual":
            cfg.network.wan_mode = "loadbalance"

        cfg.network.lan_interface = n.get("lan_interface", cfg.network.lan_interface).strip()
        lp = n.get("lan_ports", "")
        if lp:
            cfg.network.lan_ports = [p.strip() for p in lp.split(",") if p.strip()]
        else:
            cfg.network.lan_ports = [cfg.network.lan_interface] if cfg.network.lan_interface else ["eth1"]
        cfg.network.dmz_interface = n.get("dmz_interface", getattr(cfg.network, "dmz_interface", "")).strip()
        cfg.network.measurement_interface = n.get("measurement_interface", getattr(cfg.network, "measurement_interface", "wan")).strip()
        cfg.network.wlan_interface = n.get("wlan_interface", cfg.network.wlan_interface).strip()
        cfg.network.bridge_interface = n.get("bridge_interface", cfg.network.bridge_interface).strip()
        cfg.network.lan_passthrough_enabled = n.getboolean("lan_passthrough_enabled", fallback=False)
        cfg.network.passthrough_ports = [p.strip() for p in n.get("passthrough_ports", "").split(",") if p.strip()]
        cfg.network.lag_enabled = n.getboolean("lag_enabled", fallback=False)
        cfg.network.lag_ports = [p.strip() for p in n.get("lag_ports", "").split(",") if p.strip()]
        cfg.network.lag_mode = n.get("lag_mode", cfg.network.lag_mode).strip()
        cfg.network.lag_hash_policy = n.get("lag_hash_policy", cfg.network.lag_hash_policy).strip()
        cfg.network.lacp_rate = n.get("lacp_rate", cfg.network.lacp_rate).strip()

        cfg.network.gateway_ip = n.get("gateway_ip", cfg.network.gateway_ip).strip()
        cfg.network.gateway_netmask = n.get("gateway_netmask", cfg.network.gateway_netmask).strip()
        cfg.network.dhcp_enabled = n.getboolean("dhcp_enabled", fallback=getattr(cfg.network, "dhcp_enabled", True))
        cfg.network.dhcp_range_start = n.get("dhcp_range_start", cfg.network.dhcp_range_start).strip()
        cfg.network.dhcp_range_end = n.get("dhcp_range_end", cfg.network.dhcp_range_end).strip()
        cfg.network.dhcp_lease_time = n.get("dhcp_lease_time", cfg.network.dhcp_lease_time).strip()

        cfg.network.wan_proto = n.get("wan_proto", getattr(cfg.network, "wan_proto", "dhcp")).strip()
        cfg.network.wan_ip = n.get("wan_ip", getattr(cfg.network, "wan_ip", "")).strip()
        cfg.network.wan_netmask = n.get("wan_netmask", getattr(cfg.network, "wan_netmask", "255.255.255.0")).strip()
        cfg.network.wan_gateway = n.get("wan_gateway", getattr(cfg.network, "wan_gateway", "")).strip()
        cfg.network.pppoe_enabled = n.getboolean("pppoe_enabled", fallback=cfg.network.pppoe_enabled)
        cfg.network.pppoe_user = n.get("pppoe_user", cfg.network.pppoe_user)
        cfg.network.pppoe_password = n.get("pppoe_password", cfg.network.pppoe_password)
        cfg.network.pppoe_vlan = n.getint("pppoe_vlan", fallback=cfg.network.pppoe_vlan)
        cfg.network.pppoe_service_name = n.get("pppoe_service_name", getattr(cfg.network, "pppoe_service_name", "")).strip()
        cfg.network.wan_mac = n.get("wan_mac", getattr(cfg.network, "wan_mac", "")).strip()
        cfg.network.dns_mode = n.get("dns_mode", getattr(cfg.network, "dns_mode", "auto")).strip()
        cfg.network.dns_primary = n.get("dns_primary", getattr(cfg.network, "dns_primary", "1.1.1.1")).strip()
        cfg.network.dns_secondary = n.get("dns_secondary", getattr(cfg.network, "dns_secondary", "8.8.8.8")).strip()

        cfg.network.wifi_enabled = n.getboolean("wifi_enabled", fallback=cfg.network.wifi_enabled)
        cfg.network.wifi_ssid = n.get("wifi_ssid", cfg.network.wifi_ssid)
        cfg.network.wifi_psk = n.get("wifi_psk", cfg.network.wifi_psk)
        cfg.network.wifi_band = n.get("wifi_band", getattr(cfg.network, "wifi_band", "auto")).strip().lower()
        cfg.network.wifi_standard = n.get("wifi_standard", getattr(cfg.network, "wifi_standard", "auto")).strip().lower()
        cfg.network.wifi_channel = n.getint("wifi_channel", fallback=cfg.network.wifi_channel)
        cfg.network.wifi_channel_width = n.get("wifi_channel_width", getattr(cfg.network, "wifi_channel_width", "auto")).strip().lower()
        cfg.network.wifi_country_code = n.get("wifi_country_code", getattr(cfg.network, "wifi_country_code", "auto")).strip().upper()
        if not cfg.network.wifi_country_code:
            cfg.network.wifi_country_code = "AUTO"
        cfg.network.wifi_security = n.get("wifi_security", getattr(cfg.network, "wifi_security", "wpa2")).strip()

        cfg.network.check_interval_sec = n.getfloat("check_interval_sec", fallback=cfg.network.check_interval_sec)
        cfg.network.failover_timeout_sec = n.getfloat("failover_timeout_sec", fallback=cfg.network.failover_timeout_sec)
        dt = n.get("detection_targets", "").strip()
        if dt:
            cfg.network.detection_targets = [t.strip() for t in dt.split(",") if t.strip()]

        cfg.network.dns_fallback_enabled = n.getboolean("dns_fallback_enabled", fallback=getattr(cfg.network, "dns_fallback_enabled", True))
        dfs = n.get("dns_fallback_servers", "").strip()
        if dfs:
            cfg.network.dns_fallback_servers = [s.strip() for s in dfs.split(",") if s.strip()]

    if parser.has_section("probe"):
        p = parser["probe"]
        targets_str = p.get("targets", "").strip()
        if targets_str:
            cfg.probe.targets = [t.strip() for t in targets_str.split(",") if t.strip()]
        cfg.probe.ping_interval_ms = p.getfloat("ping_interval_ms", fallback=cfg.probe.ping_interval_ms)
        cfg.probe.socket_buffer_kb = p.getint("socket_buffer_kb", fallback=cfg.probe.socket_buffer_kb)
        cfg.probe.batch_flush_sec = p.getfloat("batch_flush_sec", fallback=cfg.probe.batch_flush_sec)
        cfg.probe.outage_loss_seconds = p.getfloat("outage_loss_seconds", fallback=cfg.probe.outage_loss_seconds)

    if parser.has_section("traffic_gate"):
        tg = parser["traffic_gate"]
        cfg.speedtest.idle_threshold_mode = tg.get("mode", getattr(cfg.speedtest, "idle_threshold_mode", "percent")).lower().strip()
        cfg.speedtest.idle_threshold_percent = tg.getfloat("threshold_percent", fallback=getattr(cfg.speedtest, "idle_threshold_percent", 2.0))
        cfg.speedtest.idle_threshold_kbps = tg.getint("threshold_kbps", fallback=getattr(cfg.speedtest, "idle_threshold_kbps", 500))
        cfg.speedtest.traffic_stop_enabled = tg.getboolean("experimental_stop", fallback=False)

    if parser.has_section("speedtest"):
        st = parser["speedtest"]
        cfg.speedtest.schedule_mode = st.get("schedule_mode", getattr(cfg.speedtest, "schedule_mode", "scheduled")).lower().strip()
        cfg.speedtest.schedule_cron = st.get("schedule_cron", cfg.speedtest.schedule_cron)
        cfg.speedtest.daily_data_limit_mb = st.getfloat("daily_data_limit_mb", fallback=cfg.speedtest.daily_data_limit_mb)
        cfg.speedtest.automated_engine = st.get("automated_engine", getattr(cfg.speedtest, "automated_engine", "ookla")).lower().strip()
        cfg.speedtest.ookla_interval_min = max(60, min(10080, st.getint("ookla_interval_min", fallback=60)))
        cfg.speedtest.rtr_interval_min = max(0, min(10080, st.getint("rtr_interval_min", fallback=0)))
        cfg.speedtest.cloudflare_interval_min = max(0, min(10080, st.getint("cloudflare_interval_min", fallback=0)))
        cfg.speedtest.iperf3_interval_min = max(0, min(10080, st.getint("iperf3_interval_min", fallback=0)))
        cfg.speedtest.idle_wait_max_sec = st.getfloat("idle_wait_max_sec", fallback=cfg.speedtest.idle_wait_max_sec)
        cfg.speedtest.idle_threshold_mode = st.get("idle_threshold_mode", getattr(cfg.speedtest, "idle_threshold_mode", "percent")).lower().strip()
        cfg.speedtest.idle_threshold_percent = st.getfloat("idle_threshold_percent", fallback=getattr(cfg.speedtest, "idle_threshold_percent", 2.0))
        cfg.speedtest.idle_threshold_kbps = st.getint("idle_threshold_kbps", fallback=getattr(cfg.speedtest, "idle_threshold_kbps", 500))
        sid_raw = st.get("server_id", "").strip()
        if sid_raw and sid_raw.lower() not in ("auto", "none", "null", "closest", "dynamic", "0", ""):
            try:
                cfg.speedtest.server_id = int(sid_raw)
            except ValueError:
                cfg.speedtest.server_id = None
        else:
            cfg.speedtest.server_id = None
        cfg.speedtest.server_name = st.get("server_name", cfg.speedtest.server_name).strip()
        cfg.speedtest.server_host = st.get("server_host", cfg.speedtest.server_host).strip()
        cfg.speedtest.user_agent = st.get("user_agent", getattr(cfg.speedtest, "user_agent", "")).strip()
        cfg.speedtest.user_agent_mode = st.get("user_agent_mode", getattr(cfg.speedtest, "user_agent_mode", "auto_fresh")).strip().lower()
        ports_str = st.get("port_throttle_ports", "").strip()
        if ports_str:
            try:
                cfg.speedtest.port_throttle_ports = [int(p.strip()) for p in ports_str.split(",") if p.strip()]
            except ValueError:
                pass

    if parser.has_section("isp"):
        isp = parser["isp"]
        cfg.isp.name = isp.get("name", cfg.isp.name)
        cfg.isp.account_id = isp.get("account_id", cfg.isp.account_id)
        cfg.isp.circuit_id = isp.get("circuit_id", cfg.isp.circuit_id)
        cfg.isp.contract_down_mbps = isp.getfloat("contract_down_mbps", fallback=cfg.isp.contract_down_mbps)
        cfg.isp.guaranteed_down_mbps = isp.getfloat("guaranteed_down_mbps", fallback=getattr(cfg.isp, "guaranteed_down_mbps", 300.0))
        cfg.isp.contract_up_mbps = isp.getfloat("contract_up_mbps", fallback=cfg.isp.contract_up_mbps)
        cfg.isp.guaranteed_up_mbps = isp.getfloat("guaranteed_up_mbps", fallback=getattr(cfg.isp, "guaranteed_up_mbps", 75.0))
        cfg.isp.connection_type = isp.get("connection_type", getattr(cfg.isp, "connection_type", "fiber")).strip()

    if parser.has_section("smtp"):
        smtp = parser["smtp"]
        cfg.smtp.enabled = smtp.getboolean("enabled", fallback=cfg.smtp.enabled)
        cfg.smtp.host = smtp.get("host", cfg.smtp.host)
        cfg.smtp.port = smtp.getint("port", fallback=cfg.smtp.port)
        cfg.smtp.tls = smtp.getboolean("tls", fallback=cfg.smtp.tls)
        cfg.smtp.user = smtp.get("user", cfg.smtp.user)
        cfg.smtp.password = smtp.get("password", cfg.smtp.password)
        cfg.smtp.from_addr = smtp.get("from_addr", cfg.smtp.from_addr)
        to_str = smtp.get("to_addrs", "")
        if to_str:
            cfg.smtp.to_addrs = [a.strip() for a in to_str.split(",") if a.strip()]

    if parser.has_section("telegram"):
        tg = parser["telegram"]
        cfg.telegram.enabled = tg.getboolean("enabled", fallback=cfg.telegram.enabled)
        cfg.telegram.token = os.environ.get("NMB_TELEGRAM_TOKEN", tg.get("token", cfg.telegram.token))
        chats_str = tg.get("allowed_chat_ids", "")
        if chats_str:
            try:
                cfg.telegram.allowed_chat_ids = [int(c.strip()) for c in chats_str.split(",") if c.strip()]
            except ValueError:
                pass
        cfg.telegram.alert_loss_threshold_pct = tg.getfloat("alert_loss_threshold_pct", fallback=cfg.telegram.alert_loss_threshold_pct)
        cfg.telegram.alert_latency_threshold_ms = tg.getfloat("alert_latency_threshold_ms", fallback=cfg.telegram.alert_latency_threshold_ms)
        cfg.telegram.alert_jitter_threshold_ms = tg.getfloat("alert_jitter_threshold_ms", fallback=cfg.telegram.alert_jitter_threshold_ms)
        cfg.telegram.alert_on_loss = tg.getboolean("alert_on_loss", fallback=cfg.telegram.alert_on_loss)
        cfg.telegram.alert_on_latency = tg.getboolean("alert_on_latency", fallback=cfg.telegram.alert_on_latency)

    if parser.has_section("guest_wifi"):
        gw = parser["guest_wifi"]
        cfg.guest_wifi.enabled = gw.getboolean("enabled", fallback=cfg.guest_wifi.enabled)
        cfg.guest_wifi.interface = gw.get("interface", cfg.guest_wifi.interface)
        cfg.guest_wifi.ssid = gw.get("ssid", cfg.guest_wifi.ssid)
        cfg.guest_wifi.password = gw.get("password", cfg.guest_wifi.password)
        cfg.guest_wifi.security = gw.get("security", cfg.guest_wifi.security)
        cfg.guest_wifi.metric = gw.getint("metric", fallback=cfg.guest_wifi.metric)
        cfg.guest_wifi.auto_reconnect = gw.getboolean("auto_reconnect", fallback=cfg.guest_wifi.auto_reconnect)

    if parser.has_section("iperf"):
        ipf = parser["iperf"]
        cfg.iperf.enabled = ipf.getboolean("enabled", fallback=cfg.iperf.enabled)
        cfg.iperf.target_host = ipf.get("target_host", cfg.iperf.target_host)
        cfg.iperf.target_port = ipf.getint("target_port", fallback=cfg.iperf.target_port)
        cfg.iperf.duration = ipf.getint("duration", fallback=cfg.iperf.duration)
        cfg.iperf.protocol = ipf.get("protocol", cfg.iperf.protocol)
        cfg.iperf.parallel = ipf.getint("parallel", fallback=cfg.iperf.parallel)
        cfg.iperf.reverse = ipf.getboolean("reverse", fallback=cfg.iperf.reverse)
        cfg.iperf.bidir = ipf.getboolean("bidir", fallback=cfg.iperf.bidir)
        direction = ipf.get("auto_direction", cfg.iperf.auto_direction).strip().lower()
        cfg.iperf.auto_direction = direction if direction in ("both", "download", "upload") else "both"
        cfg.iperf.extra_servers = ipf.get("extra_servers", "").strip()
        cfg.iperf.schedule_cron = ipf.get("schedule_cron", cfg.iperf.schedule_cron)

    if parser.has_section("web"):
        w = parser["web"]
        cfg.web.enabled = w.getboolean("enabled", fallback=cfg.web.enabled)
        cfg.web.host = w.get("host", cfg.web.host)
        cfg.web.port = w.getint("port", fallback=cfg.web.port)
        cfg.web.auth_enabled = w.getboolean("auth_enabled", fallback=cfg.web.auth_enabled)
        cfg.web.admin_username = w.get("admin_username", getattr(cfg.web, "admin_username", "admin"))
        cfg.web.admin_password = w.get("admin_password", cfg.web.admin_password)
        cfg.web.terminal_enabled = w.getboolean("terminal_enabled", fallback=False)
        cfg.web.public_results = w.getboolean("public_results", fallback=False)
        cfg.ooni.enabled = parser.getboolean("ooni", "enabled", fallback=False)
        cfg.web.language = w.get("language", getattr(cfg.web, "language", "en"))
        cfg.web.theme = w.get("theme", getattr(cfg.web, "theme", "default")).strip().lower()
        cfg.web.tls_enabled = w.getboolean("tls_enabled", fallback=getattr(cfg.web, "tls_enabled", False))
        cfg.web.tls_cert = w.get("tls_cert", getattr(cfg.web, "tls_cert", "/etc/nmb/server.crt"))
        cfg.web.tls_key = w.get("tls_key", getattr(cfg.web, "tls_key", "/etc/nmb/server.key"))

    if parser.has_section("logging"):
        lg = parser["logging"]
        cfg.logging.level = lg.get("level", cfg.logging.level).strip().upper()
        cfg.logging.file_enabled = lg.getboolean("file_enabled", fallback=cfg.logging.file_enabled)
        cfg.logging.file_path = lg.get("file_path", cfg.logging.file_path).strip()
        cfg.logging.max_bytes = lg.getint("max_bytes", fallback=cfg.logging.max_bytes)
        cfg.logging.backup_count = lg.getint("backup_count", fallback=cfg.logging.backup_count)
        cfg.logging.console_enabled = lg.getboolean("console_enabled", fallback=cfg.logging.console_enabled)
        cfg.logging.log_requests = lg.getboolean("log_requests", fallback=getattr(cfg.logging, "log_requests", True))

    if parser.has_section("collector"):
        co = parser["collector"]
        cfg.collector.enabled = co.getboolean("enabled", fallback=False)
        cfg.collector.url = co.get("url", "").strip()
        cfg.collector.token = co.get("token", "").strip()
        cfg.collector.case_id = co.get("case_id", "").strip()
        cfg.collector.interval_min = max(5, min(1440, co.getint("interval_min", fallback=15)))
        cfg.collector.share_diagnostics = co.getboolean("share_diagnostics", fallback=False)
        cfg.collector.allow_remote_control = co.getboolean("allow_remote_control", fallback=False)

    if parser.has_section("duckdns"):
        dd = parser["duckdns"]
        cfg.duckdns.enabled = dd.getboolean("enabled", fallback=cfg.duckdns.enabled)
        cfg.duckdns.provider = dd.get("provider", getattr(cfg.duckdns, "provider", "duckdns")).strip().lower()
        cfg.duckdns.domain = dd.get("domain", cfg.duckdns.domain).strip()
        cfg.duckdns.token = dd.get("token", cfg.duckdns.token).strip()
        cfg.duckdns.update_interval_min = dd.getint("update_interval_min", fallback=cfg.duckdns.update_interval_min)
        cfg.duckdns.custom_ip = dd.get("custom_ip", cfg.duckdns.custom_ip).strip()
        cfg.duckdns.custom_ipv6 = dd.get("custom_ipv6", getattr(cfg.duckdns, "custom_ipv6", "")).strip()
        cfg.duckdns.ipv6_mode = dd.get("ipv6_mode", getattr(cfg.duckdns, "ipv6_mode", "auto")).strip().lower()

    if parser.has_section("wireguard"):
        wg = parser["wireguard"]
        cfg.wireguard.enabled = wg.getboolean("enabled", fallback=cfg.wireguard.enabled)
        cfg.wireguard.port = wg.getint("port", fallback=cfg.wireguard.port)
        cfg.wireguard.subnet = wg.get("subnet", cfg.wireguard.subnet).strip()
        cfg.wireguard.subnet_ipv6 = wg.get("subnet_ipv6", cfg.wireguard.subnet_ipv6).strip()
        cfg.wireguard.dns = wg.get("dns", cfg.wireguard.dns).strip()
        cfg.wireguard.public_endpoint = wg.get("public_endpoint", cfg.wireguard.public_endpoint).strip()

    if parser.has_section("openvpn"):
        ov = parser["openvpn"]
        cfg.openvpn.enabled = ov.getboolean("enabled", fallback=cfg.openvpn.enabled)
        cfg.openvpn.proto = ov.get("proto", cfg.openvpn.proto).strip().lower()
        cfg.openvpn.port = ov.getint("port", fallback=cfg.openvpn.port)
        cfg.openvpn.subnet = ov.get("subnet", cfg.openvpn.subnet).strip()
        cfg.openvpn.subnet_ipv6 = ov.get("subnet_ipv6", cfg.openvpn.subnet_ipv6).strip()
        cfg.openvpn.dns = ov.get("dns", cfg.openvpn.dns).strip()
        cfg.openvpn.public_endpoint = ov.get("public_endpoint", cfg.openvpn.public_endpoint).strip()

    if parser.has_section("proxy"):
        px = parser["proxy"]
        cfg.proxy.enabled = px.getboolean("enabled", fallback=cfg.proxy.enabled)
        cfg.proxy.port = px.getint("port", fallback=cfg.proxy.port)
        cfg.proxy.auth_enabled = px.getboolean("auth_enabled", fallback=cfg.proxy.auth_enabled)
        cfg.proxy.username = px.get("username", cfg.proxy.username).strip()
        cfg.proxy.password = px.get("password", cfg.proxy.password).strip()
        cfg.proxy.tls_enabled = px.getboolean("tls_enabled", fallback=cfg.proxy.tls_enabled)
        cfg.proxy.listen_ipv6 = px.getboolean("listen_ipv6", fallback=cfg.proxy.listen_ipv6)
        cfg.proxy.dns = px.get("dns", cfg.proxy.dns).strip()

    if parser.has_section("tailscale"):
        ts = parser["tailscale"]
        cfg.tailscale.enabled = ts.getboolean("enabled", fallback=cfg.tailscale.enabled)
        cfg.tailscale.auth_key = ts.get("auth_key", cfg.tailscale.auth_key).strip()
        cfg.tailscale.hostname = ts.get("hostname", cfg.tailscale.hostname).strip()
        cfg.tailscale.accept_routes = ts.getboolean("accept_routes", fallback=cfg.tailscale.accept_routes)
        cfg.tailscale.advertise_exit_node = ts.getboolean("advertise_exit_node", fallback=cfg.tailscale.advertise_exit_node)
        cfg.tailscale.accept_dns = ts.getboolean("accept_dns", fallback=cfg.tailscale.accept_dns)

    _clamp_settings(cfg)
    if path is not None:
        cfg.system.config_path = str(path)
    return cfg


def save_config(cfg: Config, target_path: Path | None = None) -> bool:
    """Atomically write Config back to nmb.conf preserving structure."""
    path = Path(target_path) if target_path else Path(getattr(cfg.system, "config_path", DEFAULT_CONFIG_PATH) or DEFAULT_CONFIG_PATH)
    parser = _TolerantParser()
    if path.exists():
        try:
            parser.read(path)
        except Exception:
            pass

    for sec in ("system", "network", "guest_wifi", "probe", "speedtest", "iperf", "isp", "smtp", "telegram", "web", "logging", "duckdns", "collector", "wireguard", "openvpn", "proxy", "tailscale", "traffic_gate"):
        if not parser.has_section(sec):
            parser.add_section(sec)

    # System
    parser["system"]["box_id"] = str(cfg.system.box_id)
    parser["system"]["data_dir"] = str(cfg.system.data_dir)
    parser["system"]["run_dir"] = str(cfg.system.run_dir)
    parser["system"]["log_dir"] = str(cfg.system.log_dir)
    parser["system"]["sqm_algorithm"] = str(getattr(cfg.system, "sqm_algorithm", "cake"))
    parser["system"]["memory_profile"] = str(getattr(cfg.system, "memory_profile", "auto")).lower()

    # Network
    parser["network"]["mode"] = str(cfg.network.mode)
    parser["network"]["wan_interface"] = str(cfg.network.wan_interface)
    parser["network"]["wan2_interface"] = str(getattr(cfg.network, "wan2_interface", ""))
    parser["network"]["wan2_proto"] = str(getattr(cfg.network, "wan2_proto", "dhcp"))
    parser["network"]["wan2_ip"] = str(getattr(cfg.network, "wan2_ip", ""))
    parser["network"]["wan2_netmask"] = str(getattr(cfg.network, "wan2_netmask", "255.255.255.0"))
    parser["network"]["wan2_gateway"] = str(getattr(cfg.network, "wan2_gateway", ""))
    parser["network"]["wan2_mac"] = str(getattr(cfg.network, "wan2_mac", ""))
    parser["network"]["wan_mode"] = str(getattr(cfg.network, "wan_mode", "single"))
    parser["network"]["lan_interface"] = str(cfg.network.lan_interface)
    parser["network"]["lan_ports"] = ",".join(getattr(cfg.network, "lan_ports", ["eth1"]))
    parser["network"]["dmz_interface"] = str(getattr(cfg.network, "dmz_interface", ""))
    parser["network"]["measurement_interface"] = str(getattr(cfg.network, "measurement_interface", "wan"))
    parser["network"]["wlan_interface"] = str(cfg.network.wlan_interface)
    parser["network"]["bridge_interface"] = str(cfg.network.bridge_interface)
    parser["network"]["lan_passthrough_enabled"] = str(cfg.network.lan_passthrough_enabled).lower()
    parser["network"]["passthrough_ports"] = ",".join(cfg.network.passthrough_ports)
    parser["network"]["lag_enabled"] = str(cfg.network.lag_enabled).lower()
    parser["network"]["lag_ports"] = ",".join(cfg.network.lag_ports)
    parser["network"]["lag_mode"] = str(cfg.network.lag_mode)
    parser["network"]["lag_hash_policy"] = str(cfg.network.lag_hash_policy)
    parser["network"]["lacp_rate"] = str(cfg.network.lacp_rate)
    parser["network"]["gateway_ip"] = str(cfg.network.gateway_ip)
    parser["network"]["gateway_netmask"] = str(cfg.network.gateway_netmask)
    parser["network"]["dhcp_enabled"] = str(getattr(cfg.network, "dhcp_enabled", True)).lower()
    parser["network"]["dhcp_range_start"] = str(cfg.network.dhcp_range_start)
    parser["network"]["dhcp_range_end"] = str(cfg.network.dhcp_range_end)
    parser["network"]["dhcp_lease_time"] = str(cfg.network.dhcp_lease_time)
    parser["network"]["wan_proto"] = str(getattr(cfg.network, "wan_proto", "dhcp"))
    parser["network"]["wan_ip"] = str(getattr(cfg.network, "wan_ip", ""))
    parser["network"]["wan_netmask"] = str(getattr(cfg.network, "wan_netmask", "255.255.255.0"))
    parser["network"]["wan_gateway"] = str(getattr(cfg.network, "wan_gateway", ""))
    parser["network"]["pppoe_enabled"] = str(cfg.network.pppoe_enabled).lower()
    parser["network"]["pppoe_user"] = str(cfg.network.pppoe_user)
    parser["network"]["pppoe_password"] = str(cfg.network.pppoe_password)
    parser["network"]["pppoe_vlan"] = str(cfg.network.pppoe_vlan)
    parser["network"]["pppoe_service_name"] = str(getattr(cfg.network, "pppoe_service_name", ""))
    parser["network"]["wan_mac"] = str(getattr(cfg.network, "wan_mac", ""))
    parser["network"]["dns_mode"] = str(getattr(cfg.network, "dns_mode", "auto"))
    parser["network"]["dns_primary"] = str(getattr(cfg.network, "dns_primary", "1.1.1.1"))
    parser["network"]["dns_secondary"] = str(getattr(cfg.network, "dns_secondary", "8.8.8.8"))
    parser["network"]["wifi_enabled"] = str(cfg.network.wifi_enabled).lower()
    parser["network"]["wifi_ssid"] = str(cfg.network.wifi_ssid)
    parser["network"]["wifi_psk"] = str(cfg.network.wifi_psk)
    parser["network"]["wifi_band"] = str(getattr(cfg.network, "wifi_band", "auto"))
    parser["network"]["wifi_standard"] = str(getattr(cfg.network, "wifi_standard", "auto"))
    parser["network"]["wifi_channel"] = str(cfg.network.wifi_channel)
    parser["network"]["wifi_channel_width"] = str(getattr(cfg.network, "wifi_channel_width", "auto"))
    parser["network"]["wifi_country_code"] = str(getattr(cfg.network, "wifi_country_code", "auto")).upper()
    parser["network"]["wifi_security"] = str(getattr(cfg.network, "wifi_security", "wpa2"))
    parser["network"]["check_interval_sec"] = str(cfg.network.check_interval_sec)
    parser["network"]["failover_timeout_sec"] = str(cfg.network.failover_timeout_sec)
    parser["network"]["detection_targets"] = ",".join(cfg.network.detection_targets)
    parser["network"]["dns_fallback_enabled"] = str(getattr(cfg.network, "dns_fallback_enabled", True)).lower()
    parser["network"]["dns_fallback_servers"] = ",".join(getattr(cfg.network, "dns_fallback_servers", ["1.1.1.1", "8.8.8.8", "9.9.9.9", "208.67.222.222"]))

    # Guest Wi-Fi Client Station / Probe
    parser["guest_wifi"]["enabled"] = str(cfg.guest_wifi.enabled).lower()
    parser["guest_wifi"]["interface"] = str(cfg.guest_wifi.interface)
    parser["guest_wifi"]["ssid"] = str(cfg.guest_wifi.ssid)
    parser["guest_wifi"]["password"] = str(cfg.guest_wifi.password)
    parser["guest_wifi"]["security"] = str(getattr(cfg.guest_wifi, "security", "auto"))
    parser["guest_wifi"]["metric"] = str(getattr(cfg.guest_wifi, "metric", 600))
    parser["guest_wifi"]["auto_reconnect"] = str(getattr(cfg.guest_wifi, "auto_reconnect", True)).lower()

    # Probe
    parser["probe"]["targets"] = ",".join(cfg.probe.targets)
    parser["probe"]["ping_interval_ms"] = str(cfg.probe.ping_interval_ms)
    parser["probe"]["socket_buffer_kb"] = str(cfg.probe.socket_buffer_kb)
    parser["probe"]["batch_flush_sec"] = str(cfg.probe.batch_flush_sec)
    parser["probe"]["outage_loss_seconds"] = str(cfg.probe.outage_loss_seconds)

    # Traffic Gate (Idle enforcement)
    parser["traffic_gate"]["mode"] = str(getattr(cfg.speedtest, "idle_threshold_mode", "percent")).lower()
    parser["traffic_gate"]["threshold_percent"] = str(getattr(cfg.speedtest, "idle_threshold_percent", 2.0))
    parser["traffic_gate"]["threshold_kbps"] = str(getattr(cfg.speedtest, "idle_threshold_kbps", 500))
    parser["traffic_gate"]["experimental_stop"] = str(cfg.speedtest.traffic_stop_enabled).lower()

    # Speedtest (Automated measurements configuration)
    parser["speedtest"]["schedule_mode"] = str(getattr(cfg.speedtest, "schedule_mode", "scheduled")).lower()
    parser["speedtest"]["schedule_cron"] = str(cfg.speedtest.schedule_cron)
    parser["speedtest"]["daily_data_limit_mb"] = str(cfg.speedtest.daily_data_limit_mb)
    parser["speedtest"]["automated_engine"] = str(getattr(cfg.speedtest, "automated_engine", "ookla")).lower()
    parser["speedtest"]["ookla_interval_min"] = str(max(60, int(cfg.speedtest.ookla_interval_min)))
    parser["speedtest"]["rtr_interval_min"] = str(int(cfg.speedtest.rtr_interval_min))
    parser["speedtest"]["cloudflare_interval_min"] = str(int(cfg.speedtest.cloudflare_interval_min))
    parser["speedtest"]["iperf3_interval_min"] = str(int(cfg.speedtest.iperf3_interval_min))
    parser["speedtest"]["idle_wait_max_sec"] = str(cfg.speedtest.idle_wait_max_sec)
    parser["speedtest"]["idle_threshold_mode"] = str(getattr(cfg.speedtest, "idle_threshold_mode", "percent")).lower()
    parser["speedtest"]["idle_threshold_percent"] = str(getattr(cfg.speedtest, "idle_threshold_percent", 2.0))
    parser["speedtest"]["idle_threshold_kbps"] = str(getattr(cfg.speedtest, "idle_threshold_kbps", 500))
    parser["speedtest"]["server_id"] = str(cfg.speedtest.server_id) if cfg.speedtest.server_id else "auto"
    parser["speedtest"]["server_name"] = str(cfg.speedtest.server_name or "")
    parser["speedtest"]["server_host"] = str(cfg.speedtest.server_host or "")
    parser["speedtest"]["port_throttle_ports"] = ",".join(str(p) for p in cfg.speedtest.port_throttle_ports)
    parser["speedtest"]["user_agent"] = str(getattr(cfg.speedtest, "user_agent", "") or "")
    parser["speedtest"]["user_agent_mode"] = str(getattr(cfg.speedtest, "user_agent_mode", "auto_fresh")).lower()

    # ISP
    parser["isp"]["name"] = str(cfg.isp.name)
    parser["isp"]["account_id"] = str(cfg.isp.account_id)
    parser["isp"]["circuit_id"] = str(cfg.isp.circuit_id)
    parser["isp"]["contract_down_mbps"] = str(cfg.isp.contract_down_mbps)
    parser["isp"]["guaranteed_down_mbps"] = str(getattr(cfg.isp, "guaranteed_down_mbps", 300.0))
    parser["isp"]["contract_up_mbps"] = str(cfg.isp.contract_up_mbps)
    parser["isp"]["guaranteed_up_mbps"] = str(getattr(cfg.isp, "guaranteed_up_mbps", 75.0))
    parser["isp"]["connection_type"] = str(getattr(cfg.isp, "connection_type", "fiber"))

    # SMTP
    parser["smtp"]["enabled"] = str(cfg.smtp.enabled).lower()
    parser["smtp"]["host"] = str(cfg.smtp.host)
    parser["smtp"]["port"] = str(cfg.smtp.port)
    parser["smtp"]["tls"] = str(cfg.smtp.tls).lower()
    parser["smtp"]["user"] = str(cfg.smtp.user)
    parser["smtp"]["password"] = str(cfg.smtp.password)
    parser["smtp"]["from_addr"] = str(cfg.smtp.from_addr)
    parser["smtp"]["to_addrs"] = ",".join(cfg.smtp.to_addrs)

    # Telegram
    parser["telegram"]["enabled"] = str(cfg.telegram.enabled).lower()
    parser["telegram"]["token"] = str(cfg.telegram.token)
    parser["telegram"]["allowed_chat_ids"] = ",".join(str(c) for c in cfg.telegram.allowed_chat_ids)
    parser["telegram"]["alert_loss_threshold_pct"] = str(cfg.telegram.alert_loss_threshold_pct)
    parser["telegram"]["alert_latency_threshold_ms"] = str(cfg.telegram.alert_latency_threshold_ms)
    parser["telegram"]["alert_jitter_threshold_ms"] = str(cfg.telegram.alert_jitter_threshold_ms)
    parser["telegram"]["alert_on_loss"] = str(cfg.telegram.alert_on_loss).lower()
    parser["telegram"]["alert_on_latency"] = str(cfg.telegram.alert_on_latency).lower()

    # iPerf
    parser["iperf"]["enabled"] = str(cfg.iperf.enabled).lower()
    parser["iperf"]["target_host"] = str(cfg.iperf.target_host)
    parser["iperf"]["target_port"] = str(cfg.iperf.target_port)
    parser["iperf"]["duration"] = str(cfg.iperf.duration)
    parser["iperf"]["protocol"] = str(cfg.iperf.protocol)
    parser["iperf"]["parallel"] = str(cfg.iperf.parallel)
    parser["iperf"]["reverse"] = str(cfg.iperf.reverse).lower()
    parser["iperf"]["bidir"] = str(cfg.iperf.bidir).lower()
    parser["iperf"]["auto_direction"] = str(cfg.iperf.auto_direction)
    parser["iperf"]["extra_servers"] = str(cfg.iperf.extra_servers)
    parser["iperf"]["schedule_cron"] = str(cfg.iperf.schedule_cron)

    # Web
    parser["web"]["enabled"] = str(cfg.web.enabled).lower()
    parser["web"]["host"] = str(cfg.web.host)
    parser["web"]["port"] = str(cfg.web.port)
    parser["web"]["auth_enabled"] = str(cfg.web.auth_enabled).lower()
    parser["web"]["admin_username"] = str(getattr(cfg.web, "admin_username", "admin"))
    parser["web"]["admin_password"] = str(cfg.web.admin_password)
    parser["web"]["public_results"] = str(cfg.web.public_results).lower()
    if "ooni" not in parser:
        parser["ooni"] = {}
    parser["ooni"]["enabled"] = str(cfg.ooni.enabled).lower()
    parser["web"]["terminal_enabled"] = str(cfg.web.terminal_enabled).lower()
    parser["web"]["language"] = str(getattr(cfg.web, "language", "en"))
    parser["web"]["theme"] = str(getattr(cfg.web, "theme", "default"))
    parser["web"]["tls_enabled"] = str(getattr(cfg.web, "tls_enabled", False)).lower()
    parser["web"]["tls_cert"] = str(getattr(cfg.web, "tls_cert", "/etc/nmb/server.crt"))
    parser["web"]["tls_key"] = str(getattr(cfg.web, "tls_key", "/etc/nmb/server.key"))

    # Logging
    parser["logging"]["level"] = str(cfg.logging.level)
    parser["logging"]["file_enabled"] = str(cfg.logging.file_enabled).lower()
    parser["logging"]["file_path"] = str(cfg.logging.file_path)
    parser["logging"]["max_bytes"] = str(cfg.logging.max_bytes)
    parser["logging"]["backup_count"] = str(cfg.logging.backup_count)
    parser["logging"]["console_enabled"] = str(cfg.logging.console_enabled).lower()
    parser["logging"]["log_requests"] = str(getattr(cfg.logging, "log_requests", True)).lower()

    # Central collector
    parser["collector"]["enabled"] = str(cfg.collector.enabled).lower()
    parser["collector"]["url"] = str(cfg.collector.url)
    parser["collector"]["token"] = str(cfg.collector.token)
    parser["collector"]["case_id"] = str(cfg.collector.case_id)
    parser["collector"]["interval_min"] = str(cfg.collector.interval_min)
    parser["collector"]["share_diagnostics"] = str(cfg.collector.share_diagnostics).lower()
    parser["collector"]["allow_remote_control"] = str(cfg.collector.allow_remote_control).lower()

    # DuckDNS / DynDNS
    parser["duckdns"]["enabled"] = str(cfg.duckdns.enabled).lower()
    parser["duckdns"]["provider"] = str(getattr(cfg.duckdns, "provider", "duckdns"))
    parser["duckdns"]["domain"] = str(cfg.duckdns.domain)
    parser["duckdns"]["token"] = str(cfg.duckdns.token)
    parser["duckdns"]["update_interval_min"] = str(cfg.duckdns.update_interval_min)
    parser["duckdns"]["custom_ip"] = str(cfg.duckdns.custom_ip)
    parser["duckdns"]["custom_ipv6"] = str(getattr(cfg.duckdns, "custom_ipv6", ""))
    parser["duckdns"]["ipv6_mode"] = str(getattr(cfg.duckdns, "ipv6_mode", "auto"))

    # WireGuard
    parser["wireguard"]["enabled"] = str(cfg.wireguard.enabled).lower()
    parser["wireguard"]["port"] = str(cfg.wireguard.port)
    parser["wireguard"]["subnet"] = str(cfg.wireguard.subnet)
    parser["wireguard"]["subnet_ipv6"] = str(cfg.wireguard.subnet_ipv6)
    parser["wireguard"]["dns"] = str(cfg.wireguard.dns)
    parser["wireguard"]["public_endpoint"] = str(cfg.wireguard.public_endpoint)

    # OpenVPN
    parser["openvpn"]["enabled"] = str(cfg.openvpn.enabled).lower()
    parser["openvpn"]["proto"] = str(cfg.openvpn.proto)
    parser["openvpn"]["port"] = str(cfg.openvpn.port)
    parser["openvpn"]["subnet"] = str(cfg.openvpn.subnet)
    parser["openvpn"]["subnet_ipv6"] = str(cfg.openvpn.subnet_ipv6)
    parser["openvpn"]["dns"] = str(cfg.openvpn.dns)
    parser["openvpn"]["public_endpoint"] = str(cfg.openvpn.public_endpoint)

    # Proxy
    parser["proxy"]["enabled"] = str(cfg.proxy.enabled).lower()
    parser["proxy"]["port"] = str(cfg.proxy.port)
    parser["proxy"]["auth_enabled"] = str(cfg.proxy.auth_enabled).lower()
    parser["proxy"]["username"] = str(cfg.proxy.username)
    parser["proxy"]["password"] = str(cfg.proxy.password)
    parser["proxy"]["tls_enabled"] = str(cfg.proxy.tls_enabled).lower()
    parser["proxy"]["listen_ipv6"] = str(cfg.proxy.listen_ipv6).lower()
    parser["proxy"]["dns"] = str(cfg.proxy.dns)

    # Tailscale
    parser["tailscale"]["enabled"] = str(cfg.tailscale.enabled).lower()
    parser["tailscale"]["auth_key"] = str(cfg.tailscale.auth_key)
    parser["tailscale"]["hostname"] = str(cfg.tailscale.hostname)
    parser["tailscale"]["accept_routes"] = str(cfg.tailscale.accept_routes).lower()
    parser["tailscale"]["advertise_exit_node"] = str(cfg.tailscale.advertise_exit_node).lower()
    parser["tailscale"]["accept_dns"] = str(cfg.tailscale.accept_dns).lower()

    tmp_path = path.with_suffix(".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(tmp_path, "w", encoding="utf-8") as f:
            parser.write(f)
            f.flush()
            os.fsync(f.fileno())
        try:
            import shutil
            shutil.chown(tmp_path, group="nmb")
        except Exception:
            pass
        try:
            os.chmod(tmp_path, 0o640)
        except OSError:
            pass
        os.replace(tmp_path, path)
        try:
            import shutil
            shutil.chown(path, group="nmb")
            os.chmod(path, 0o640)
        except Exception:
            pass
        sync_drive_config(path)
        return True
    except (PermissionError, OSError):
        tmp_path.unlink(missing_ok=True)
        # Fallback: attempt write via sudo -n if available, or write to drive config target
        try:
            import io
            import subprocess
            buf = io.StringIO()
            parser.write(buf)
            content = buf.getvalue()
            p = subprocess.run(["sudo", "-n", "tee", str(path)], input=content, text=True, capture_output=True)
            if p.returncode == 0:
                sync_drive_config(path)
                return True
        except Exception:
            pass
        # As last fallback, write directly to drive config if writable
        try:
            d_target = get_writable_drive_config_target()
            if d_target and d_target.exists():
                with open(d_target, "w", encoding="utf-8") as f:
                    parser.write(f)
                return True
        except Exception:
            pass
        return False
    except Exception:
        tmp_path.unlink(missing_ok=True)
        return False
