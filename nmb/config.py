"""NetworkMeasureBox configuration parser and defaults.

Reads /etc/nmb/nmb.conf (or path in NMB_CONFIG) with structured defaults.
Uses configparser (standard library).
"""
from __future__ import annotations

import configparser
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

DEFAULT_CONFIG_PATH = Path(os.environ.get("NMB_CONFIG", "/etc/nmb/nmb.conf"))
FALLBACK_CONFIG_PATH = Path("/opt/nmb/config/nmb.conf")

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
lan_interface = eth1
wlan_interface = wlan0
bridge_interface = br0

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
sample_window_sec = 3
cooldown_sec = 10

[speedtest]
schedule_cron = 0 */6 * * *
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
port = 8080
auth_enabled = true
admin_password = admin

[logging]
level = DEBUG
file_enabled = true
file_path = /var/log/nmb/nmb_developer.log
max_bytes = 10485760
backup_count = 5
console_enabled = true
log_requests = true

[duckdns]
enabled = false
domain = 
token = 
update_interval_min = 10
custom_ip = 

[wireguard]
enabled = false
port = 51820
subnet = 10.8.0.1/24
public_endpoint = 

[openvpn]
enabled = false
proto = udp
port = 1194
subnet = 10.9.0.0
public_endpoint = 

[proxy]
enabled = false
port = 8443
auth_enabled = false
username = 
password = 
tls_enabled = false
"""


@dataclass
class SystemConfig:
    box_id: str = "nmb-01"
    data_dir: Path = Path("/var/lib/nmb")
    run_dir: Path = Path("/run/nmb")
    log_dir: Path = Path("/var/log/nmb")
    sqm_algorithm: str = "cake"
    memory_profile: str = "auto"  # auto, low, standard, performance


@dataclass
class NetworkConfig:
    mode: str = "standalone"  # auto, mode_a, mode_b, standalone
    wan_interface: str = "eth0"
    lan_interface: str = "eth1"
    wlan_interface: str = "wlan0"
    bridge_interface: str = "br0"

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
    wifi_country_code: str = "auto"      # ISO regulatory domain (auto, HU, US, DE, 00)
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


@dataclass
class WebConfig:
    enabled: bool = True
    host: str = "0.0.0.0"
    port: int = 8080
    auth_enabled: bool = True
    admin_username: str = "admin"
    admin_password: str = "admin"
    language: str = "en"
    tls_enabled: bool = False
    tls_cert: str = "/etc/nmb/server.crt"
    tls_key: str = "/etc/nmb/server.key"


@dataclass
class IPerfConfig:
    enabled: bool = False
    target_host: str = ""
    target_port: int = 5201
    duration: int = 10
    protocol: str = "tcp"
    parallel: int = 1
    reverse: bool = False
    bidir: bool = False
    schedule_cron: str = "0 */12 * * *"


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
    schedule_cron: str = "0 */6 * * *"
    automated_engine: str = "ookla"           # "ookla", "cloudflare", "rtr", "all"
    idle_wait_max_sec: float = 1800.0
    idle_threshold_mode: str = "percent"      # "percent" (< 2% network load) or "fixed" (custom kbps)
    idle_threshold_percent: float = 2.0       # dynamic network load threshold (e.g. 2.0%)
    idle_threshold_kbps: int = 500            # fallback fixed kbps
    server_id: Optional[int] = None           # Manually selected server ID for automated measurements!
    server_name: str = ""
    server_host: str = ""
    port_throttle_ports: List[int] = field(default_factory=lambda: [80, 443, 8080, 8443, 5060, 53])


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
class DuckDNSConfig:
    enabled: bool = False
    domain: str = ""
    token: str = ""
    update_interval_min: int = 10
    custom_ip: str = ""


@dataclass
class WireGuardConfig:
    enabled: bool = False
    port: int = 51820
    subnet: str = "10.8.0.1/24"
    public_endpoint: str = ""


@dataclass
class OpenVPNConfig:
    enabled: bool = False
    proto: str = "udp"
    port: int = 1194
    subnet: str = "10.9.0.0"
    public_endpoint: str = ""


@dataclass
class ProxyConfig:
    enabled: bool = False
    port: int = 8443
    auth_enabled: bool = False
    username: str = ""
    password: str = ""
    tls_enabled: bool = False


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
    wireguard: WireGuardConfig = field(default_factory=WireGuardConfig)
    openvpn: OpenVPNConfig = field(default_factory=OpenVPNConfig)
    proxy: ProxyConfig = field(default_factory=ProxyConfig)
    raw_parser: configparser.ConfigParser = field(default_factory=configparser.ConfigParser)


def load_config(path: Path | None = None) -> Config:
    parser = configparser.ConfigParser()
    parser.read_string(DEFAULT_CONFIG_TEXT)

    target_path = path or (
        DEFAULT_CONFIG_PATH if DEFAULT_CONFIG_PATH.exists() else
        FALLBACK_CONFIG_PATH if FALLBACK_CONFIG_PATH.exists() else None
    )

    if target_path and target_path.exists():
        parser.read(target_path)

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
        cfg.network.lan_interface = n.get("lan_interface", cfg.network.lan_interface).strip()
        cfg.network.wlan_interface = n.get("wlan_interface", cfg.network.wlan_interface).strip()
        cfg.network.bridge_interface = n.get("bridge_interface", cfg.network.bridge_interface).strip()

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

    if parser.has_section("speedtest"):
        st = parser["speedtest"]
        cfg.speedtest.schedule_mode = st.get("schedule_mode", getattr(cfg.speedtest, "schedule_mode", "scheduled")).lower().strip()
        cfg.speedtest.schedule_cron = st.get("schedule_cron", cfg.speedtest.schedule_cron)
        cfg.speedtest.automated_engine = st.get("automated_engine", getattr(cfg.speedtest, "automated_engine", "ookla")).lower().strip()
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
        cfg.iperf.schedule_cron = ipf.get("schedule_cron", cfg.iperf.schedule_cron)

    if parser.has_section("web"):
        w = parser["web"]
        cfg.web.enabled = w.getboolean("enabled", fallback=cfg.web.enabled)
        cfg.web.host = w.get("host", cfg.web.host)
        cfg.web.port = w.getint("port", fallback=cfg.web.port)
        cfg.web.auth_enabled = w.getboolean("auth_enabled", fallback=cfg.web.auth_enabled)
        cfg.web.admin_username = w.get("admin_username", getattr(cfg.web, "admin_username", "admin"))
        cfg.web.admin_password = w.get("admin_password", cfg.web.admin_password)
        cfg.web.language = w.get("language", getattr(cfg.web, "language", "en"))
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

    if parser.has_section("duckdns"):
        dd = parser["duckdns"]
        cfg.duckdns.enabled = dd.getboolean("enabled", fallback=cfg.duckdns.enabled)
        cfg.duckdns.domain = dd.get("domain", cfg.duckdns.domain).strip()
        cfg.duckdns.token = dd.get("token", cfg.duckdns.token).strip()
        cfg.duckdns.update_interval_min = dd.getint("update_interval_min", fallback=cfg.duckdns.update_interval_min)
        cfg.duckdns.custom_ip = dd.get("custom_ip", cfg.duckdns.custom_ip).strip()

    if parser.has_section("wireguard"):
        wg = parser["wireguard"]
        cfg.wireguard.enabled = wg.getboolean("enabled", fallback=cfg.wireguard.enabled)
        cfg.wireguard.port = wg.getint("port", fallback=cfg.wireguard.port)
        cfg.wireguard.subnet = wg.get("subnet", cfg.wireguard.subnet).strip()
        cfg.wireguard.public_endpoint = wg.get("public_endpoint", cfg.wireguard.public_endpoint).strip()

    if parser.has_section("openvpn"):
        ov = parser["openvpn"]
        cfg.openvpn.enabled = ov.getboolean("enabled", fallback=cfg.openvpn.enabled)
        cfg.openvpn.proto = ov.get("proto", cfg.openvpn.proto).strip().lower()
        cfg.openvpn.port = ov.getint("port", fallback=cfg.openvpn.port)
        cfg.openvpn.subnet = ov.get("subnet", cfg.openvpn.subnet).strip()
        cfg.openvpn.public_endpoint = ov.get("public_endpoint", cfg.openvpn.public_endpoint).strip()

    if parser.has_section("proxy"):
        px = parser["proxy"]
        cfg.proxy.enabled = px.getboolean("enabled", fallback=cfg.proxy.enabled)
        cfg.proxy.port = px.getint("port", fallback=cfg.proxy.port)
        cfg.proxy.auth_enabled = px.getboolean("auth_enabled", fallback=cfg.proxy.auth_enabled)
        cfg.proxy.username = px.get("username", cfg.proxy.username).strip()
        cfg.proxy.password = px.get("password", cfg.proxy.password).strip()
        cfg.proxy.tls_enabled = px.getboolean("tls_enabled", fallback=cfg.proxy.tls_enabled)

    return cfg


def save_config(cfg: Config, target_path: Path | None = None) -> bool:
    """Atomically write Config back to nmb.conf preserving structure."""
    path = target_path or DEFAULT_CONFIG_PATH
    parser = configparser.ConfigParser()
    if path.exists():
        try:
            parser.read(path)
        except Exception:
            pass

    for sec in ("system", "network", "guest_wifi", "probe", "speedtest", "iperf", "isp", "smtp", "telegram", "web", "logging", "duckdns", "wireguard", "openvpn", "proxy"):
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
    parser["network"]["lan_interface"] = str(cfg.network.lan_interface)
    parser["network"]["wlan_interface"] = str(cfg.network.wlan_interface)
    parser["network"]["bridge_interface"] = str(cfg.network.bridge_interface)
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

    # Speedtest (Automated measurements configuration)
    parser["speedtest"]["schedule_mode"] = str(getattr(cfg.speedtest, "schedule_mode", "scheduled")).lower()
    parser["speedtest"]["schedule_cron"] = str(cfg.speedtest.schedule_cron)
    parser["speedtest"]["automated_engine"] = str(getattr(cfg.speedtest, "automated_engine", "ookla")).lower()
    parser["speedtest"]["idle_wait_max_sec"] = str(cfg.speedtest.idle_wait_max_sec)
    parser["speedtest"]["idle_threshold_mode"] = str(getattr(cfg.speedtest, "idle_threshold_mode", "percent")).lower()
    parser["speedtest"]["idle_threshold_percent"] = str(getattr(cfg.speedtest, "idle_threshold_percent", 2.0))
    parser["speedtest"]["idle_threshold_kbps"] = str(getattr(cfg.speedtest, "idle_threshold_kbps", 500))
    parser["speedtest"]["server_id"] = str(cfg.speedtest.server_id) if cfg.speedtest.server_id else "auto"
    parser["speedtest"]["server_name"] = str(cfg.speedtest.server_name or "")
    parser["speedtest"]["server_host"] = str(cfg.speedtest.server_host or "")
    parser["speedtest"]["port_throttle_ports"] = ",".join(str(p) for p in cfg.speedtest.port_throttle_ports)

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

    # iPerf
    parser["iperf"]["enabled"] = str(cfg.iperf.enabled).lower()
    parser["iperf"]["target_host"] = str(cfg.iperf.target_host)
    parser["iperf"]["target_port"] = str(cfg.iperf.target_port)
    parser["iperf"]["duration"] = str(cfg.iperf.duration)
    parser["iperf"]["protocol"] = str(cfg.iperf.protocol)
    parser["iperf"]["parallel"] = str(cfg.iperf.parallel)
    parser["iperf"]["reverse"] = str(cfg.iperf.reverse).lower()
    parser["iperf"]["bidir"] = str(cfg.iperf.bidir).lower()
    parser["iperf"]["schedule_cron"] = str(cfg.iperf.schedule_cron)

    # Web
    parser["web"]["enabled"] = str(cfg.web.enabled).lower()
    parser["web"]["host"] = str(cfg.web.host)
    parser["web"]["port"] = str(cfg.web.port)
    parser["web"]["auth_enabled"] = str(cfg.web.auth_enabled).lower()
    parser["web"]["admin_username"] = str(getattr(cfg.web, "admin_username", "admin"))
    parser["web"]["admin_password"] = str(cfg.web.admin_password)
    parser["web"]["language"] = str(getattr(cfg.web, "language", "en"))
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

    # DuckDNS
    parser["duckdns"]["enabled"] = str(cfg.duckdns.enabled).lower()
    parser["duckdns"]["domain"] = str(cfg.duckdns.domain)
    parser["duckdns"]["token"] = str(cfg.duckdns.token)
    parser["duckdns"]["update_interval_min"] = str(cfg.duckdns.update_interval_min)
    parser["duckdns"]["custom_ip"] = str(cfg.duckdns.custom_ip)

    # WireGuard
    parser["wireguard"]["enabled"] = str(cfg.wireguard.enabled).lower()
    parser["wireguard"]["port"] = str(cfg.wireguard.port)
    parser["wireguard"]["subnet"] = str(cfg.wireguard.subnet)
    parser["wireguard"]["public_endpoint"] = str(cfg.wireguard.public_endpoint)

    # OpenVPN
    parser["openvpn"]["enabled"] = str(cfg.openvpn.enabled).lower()
    parser["openvpn"]["proto"] = str(cfg.openvpn.proto)
    parser["openvpn"]["port"] = str(cfg.openvpn.port)
    parser["openvpn"]["subnet"] = str(cfg.openvpn.subnet)
    parser["openvpn"]["public_endpoint"] = str(cfg.openvpn.public_endpoint)

    # Proxy
    parser["proxy"]["enabled"] = str(cfg.proxy.enabled).lower()
    parser["proxy"]["port"] = str(cfg.proxy.port)
    parser["proxy"]["auth_enabled"] = str(cfg.proxy.auth_enabled).lower()
    parser["proxy"]["username"] = str(cfg.proxy.username)
    parser["proxy"]["password"] = str(cfg.proxy.password)
    parser["proxy"]["tls_enabled"] = str(cfg.proxy.tls_enabled).lower()

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".tmp")
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            parser.write(f)
            f.flush()
            os.fsync(f.fileno())
        try:
            os.chmod(tmp_path, 0o600)
        except OSError:
            pass
        os.replace(tmp_path, path)
        return True
    except Exception:
        tmp_path.unlink(missing_ok=True)
        return False
