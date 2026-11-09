"""Menu tree read from the WebGUI page, plus the views and actions of each screen."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

DASHBOARD_HTML = Path(__file__).resolve().parent.parent / "web" / "assets" / "dashboard.html"

SUBTAB_PARENTS = {
    "switchAdblockSubtab": "tab-adblock",
    "switchRemoteSubtab": "tab-remote",
    "switchSyslogSubtab": "tab-syslog",
    "switchRouterSubtab": "tab-info",
}


@dataclass(frozen=True)
class Field:
    name: str
    kind: str = "text"  # text, int, float, bool, secret, choice
    choices: Tuple[str, ...] = ()


@dataclass(frozen=True)
class Action:
    id: str
    label: str
    method: str
    path: str
    fields: Tuple[Field, ...] = ()
    confirm: str = ""  # Text the user must type; RESET and PURGE are also sent to the API.
    download: bool = False


@dataclass
class Screen:
    key: str
    label: str
    i18n: str = ""
    views: Tuple[str, ...] = ()
    actions: Tuple[Action, ...] = ()


@dataclass
class Tab:
    key: str
    label: str
    i18n: str
    screen: Screen
    subs: List[Screen]


def _fields(spec: str) -> Tuple[Field, ...]:
    out = []
    for part in spec.split():
        name, _, kind = part.partition(":")
        if kind.startswith("choice(") and kind.endswith(")"):
            out.append(Field(name, "choice", tuple(kind[7:-1].split("|"))))
        else:
            out.append(Field(name, kind or "text"))
    return tuple(out)


def A(action_id: str, label: str, path: str, fields: str = "", method: str = "POST",
      confirm: str = "", download: bool = False) -> Action:
    return Action(action_id, label, method, path, _fields(fields), confirm, download)


NET_ADDR = "wan_proto:choice(dhcp|static|pppoe) wan_ip wan_netmask wan_gateway wan_mac dns_mode dns_primary dns_secondary"
SCHEDULE = ("schedule_mode:choice(scheduled|manual) schedule_cron daily_data_limit_mb:float automated_engine:choice(ookla|cloudflare|fastcom|rtr|iperf3|all) "
            "ookla_interval_min:int rtr_interval_min:int cloudflare_interval_min:int fastcom_interval_min:int iperf3_interval_min:int "
            "idle_threshold_mode:choice(percent|fixed) idle_threshold_percent:float idle_threshold_kbps:int")
IPERF_AUTO = ("iperf_target_host iperf_port:int iperf_duration:int iperf_protocol:choice(tcp|udp) iperf_parallel:int "
              "iperf_direction:choice(both|download|upload|bidir) iperf_extra_servers")

CONTENT: Dict[str, Tuple[Tuple[str, ...], Tuple[Action, ...]]] = {
    "tab-home": (("/api/status", "/api/scheduler/status"), (
        A("speed.run", "Run speed test", "/api/speedtest", "engine:choice(ookla|cloudflare|fastcom|rtr|iperf3|all) server_id:int interface"),
        A("speed.cancel", "Cancel speed test", "/api/speedtest/cancel"),
        A("speed.stop", "Stop speed test", "/api/speedtest/stop"),
        A("traffic.stop", "Stop on network traffic (experimental)", "/api/speedtest/traffic-stop", "enabled:bool"),
        A("export.csv", "Export CSV", "/api/export/csv", method="GET", download=True),
        A("export.dossier", "Export dossier", "/api/export/dossier", method="GET", download=True),
    )),
    "tab-ping": (("/api/status",), ()),
    "tab-config": (("/api/config",), (
        A("config.general", "Save general settings", "/api/config", "box_id memory_profile:choice(auto|low|standard|performance) language:choice(en|hu|de|fr|uk) theme iperf_target_host iperf_port:int iperf_protocol:choice(tcp|udp) iperf_duration:int iperf_parallel:int iperf_reverse:bool iperf_server_enabled:bool iperf_server_port:int"),
    )),
    "tab-speed": (("/api/status", "/api/speed/anti-ban"), (
        A("speed.export", "Export speed tests", "/api/export/speedtests", method="GET", download=True),
        A("antiban.clear", "Clear server quarantine", "/api/speed/anti-ban/clear"),
    )),
    "tab-iperf": (("/api/iperf/status", "/api/iperf/server", "/api/iperf/servers"), (
        A("iperf.run", "Run iPerf3 test", "/api/iperf/run", "host port:int duration:int parallel:int reverse:bool bidir:bool udp:bool target_bandwidth"),
        A("iperf.server", "iPerf3 server start/stop", "/api/iperf/server", "action:choice(start|stop) port:int"),
        A("iperf.toggle", "Toggle iPerf3 server", "/api/iperf/server/toggle"),
        A("iperf.probe", "Probe server", "/api/iperf/probe", "host port:int", method="GET"),
    )),
    "tab-traceroute": (("/api/traceroute/status",), (
        A("trace.run", "Run traceroute", "/api/traceroute/run", "host max_hops:int method:choice(icmp|udp|tcp) ip_version"),
        A("trace.stop", "Stop traceroute", "/api/traceroute/stop"),
    )),
    "tab-adblock/dash": (("/api/adblock/status", "/api/adblock/charts", "/api/adblock/gravity/status", "/api/adblock/update/status"), (
        A("adblock.toggle", "Enable or disable", "/api/adblock/toggle", "enabled:bool"),
        A("adblock.enable", "Enable", "/api/adblock/enable"),
        A("adblock.disable", "Disable for a time", "/api/adblock/disable", "duration:int"),
        A("adblock.update", "Update blocklists", "/api/adblock/update"),
        A("adblock.gravity", "Update gravity", "/api/adblock/gravity/update"),
    )),
    "tab-adblock/log": (("/api/adblock/querylog",), ()),
    "tab-adblock/domains": (("/api/adblock/whitelist", "/api/adblock/blacklist", "/api/adblock/regex"), (
        A("allow.add", "Allow domain", "/api/adblock/whitelist/add", "domain"),
        A("allow.del", "Remove allowed domain", "/api/adblock/whitelist/remove", "domain"),
        A("block.add", "Block domain", "/api/adblock/blacklist/add", "domain"),
        A("block.del", "Remove blocked domain", "/api/adblock/blacklist/remove", "domain"),
        A("regex.add", "Add regex", "/api/adblock/regex/add", "pattern kind comment"),
        A("regex.del", "Remove regex", "/api/adblock/regex/remove", "pattern kind"),
    )),
    "tab-adblock/adlists": (("/api/adblock/adlists",), (
        A("adlist.add", "Add list", "/api/adblock/adlists/add", "url name"),
        A("adlist.del", "Remove list", "/api/adblock/adlists/remove", "url"),
        A("adlist.toggle", "Enable or disable list", "/api/adblock/adlists/toggle", "url enabled:bool"),
    )),
    "tab-adblock/localdns": (("/api/adblock/localdns",), (
        A("ldns.add", "Add local record", "/api/adblock/localdns/add", "domain ip"),
        A("ldns.del", "Remove local record", "/api/adblock/localdns/remove", "domain"),
    )),
    "tab-adblock/guide": (("/api/adblock/guide",), ()),
    "tab-ooni": (("/api/ooni/status", "/api/ooni/results"), (
        A("ooni.toggle", "Enable or disable OONI", "/api/ooni/toggle", "enabled:bool"),
        A("ooni.run", "Run OONI test", "/api/ooni/run", "test_type:choice(websites|middlebox|im|circumvention|all) url"),
        A("ooni.measurement", "Show measurement", "/api/ooni/measurement", "id", method="GET"),
    )),
    "tab-remote/vpnhub": (("/api/wireguard/status", "/api/openvpn/status", "/api/tailscale/status", "/api/proxy/status"), ()),
    "tab-remote/tailscale": (("/api/tailscale/status",), (
        A("ts.save", "Save settings", "/api/tailscale/save", "enabled:bool auth_key:secret hostname"),
        A("ts.up", "Connect", "/api/tailscale/up", "auth_key:secret hostname"),
        A("ts.down", "Disconnect", "/api/tailscale/down"),
        A("ts.logout", "Log out", "/api/tailscale/logout", confirm="YES"),
    )),
    "tab-remote/guide": (("/api/wireguard/endpoints",), ()),
    "tab-remote/wireguard": (("/api/wireguard/status", "/api/wireguard/endpoints"), (
        A("wg.save", "Save settings", "/api/wireguard/save", "port:int subnet subnet_ipv6 dns public_endpoint"),
        A("wg.toggle", "Enable or disable", "/api/wireguard/toggle", "enabled:bool"),
        A("wg.add", "Add peer", "/api/wireguard/peer/add", "name client_ip client_ipv6"),
        A("wg.del", "Delete peer", "/api/wireguard/peer/delete", "name", confirm="YES"),
        A("wg.conf", "Download peer config", "/api/wireguard/peer/config", "name", method="GET", download=True),
        A("wg.qr", "Download peer QR", "/api/wireguard/peer/qr", "name", method="GET", download=True),
    )),
    "tab-remote/openvpn": (("/api/openvpn/status",), (
        A("ovpn.save", "Save settings", "/api/openvpn/save", "proto:choice(udp|tcp) port:int subnet subnet_ipv6 dns public_endpoint"),
        A("ovpn.toggle", "Enable or disable", "/api/openvpn/toggle", "enabled:bool"),
        A("ovpn.add", "Add client", "/api/openvpn/client/add", "name"),
        A("ovpn.del", "Delete client", "/api/openvpn/client/delete", "name", confirm="YES"),
        A("ovpn.conf", "Download client config", "/api/openvpn/client/config", "name", method="GET", download=True),
    )),
    "tab-remote/duckdns": (("/api/dyndns/status", "/api/duckdns/status"), (
        A("ddns.save", "Save settings", "/api/dyndns/save", "enabled:bool provider domain token:secret update_interval_min:int ipv6_mode:choice(auto|custom|none) custom_ip custom_ipv6"),
        A("ddns.update", "Update now", "/api/dyndns/update"),
    )),
    "tab-remote/proxy": (("/api/proxy/status",), (
        A("proxy.save", "Save settings", "/api/proxy/config", "enabled:bool port:int auth_enabled:bool username password:secret tls_enabled:bool listen_ipv6:bool dns"),
        A("proxy.start", "Start", "/api/proxy/start"),
        A("proxy.stop", "Stop", "/api/proxy/stop"),
    )),
    "tab-explorer": (("/api/explorer/devices",), (
        A("explorer.scan", "Scan network", "/api/explorer/scan", "iface"),
    )),
    "tab-sniffer": (("/api/sniffer/stats",), (
        A("sniffer.ctl", "Start, stop or clear", "/api/sniffer/control", "action:choice(start|stop|clear) iface"),
        A("sniffer.pcap", "Download capture", "/api/sniffer/pcap", method="GET", download=True),
    )),
    "tab-qos": (("/api/system/interfaces", "/api/system/tasks"), ()),
    "tab-portscan": (("/api/status",), (
        A("port.check", "Run port check", "/api/portcheck"),
    )),
    "tab-script": (("/api/scheduler/status", "/api/speedtest/servers", "/api/user-agent", "/api/wifi-uplink/status", "/api/wifi-share/status", "/api/storage/status", "/api/usb-uplink/status"), (
        A("wifi.uplink", "Measurement link and Wi-Fi uplink", "/api/wifi-uplink/save",
          "measurement_link:choice(auto|ethernet|wifi|usb) ssid password:secret interface hidden:bool enabled:bool"),
        A("wifi.uplink.disconnect", "Disconnect the Wi-Fi uplink", "/api/wifi-uplink/disconnect"),
        A("wifi.share", "Share the Wi-Fi internet on a LAN port (own DHCP)", "/api/wifi-share/save",
          "enabled:bool lan_interface address"),
        A("usb.uplink", "USB tethering (phone, mobile hotspot, modem)", "/api/usb-uplink/save",
          "enabled:bool interface daily_limit_mb:int measurement_link:choice(auto|ethernet|wifi|usb)"),
        A("usb.off", "Turn the USB tethering link off", "/api/usb-uplink/disconnect"),
        A("storage.save", "Automatic disk cleanup settings", "/api/storage/save", "auto_cleanup:bool min_free_mb:int keep_days:int"),
        A("storage.cleanup", "Check the disk and clean up now", "/api/storage/cleanup"),
        A("server.default", "Set scheduled server", "/api/speedtest/scheduled-server", "server_id:int server_name server_host"),
        A("schedule.set", "Change schedule", "/api/speedtest/schedule", SCHEDULE),
        A("engine.set", "Set engine", "/api/speedtest/engine", "engine:choice(ookla|cloudflare|fastcom|rtr|iperf3|all)"),
        A("iperf.auto", "iPerf3 servers and settings for automatic tests", "/api/speedtest/schedule", IPERF_AUTO),
        A("servers.refresh", "Refresh the Ookla server list from Ookla", "/api/speedtest/servers", "refresh:choice(1)", method="GET"),
        A("ua.save", "Set User-Agent", "/api/user-agent", "user_agent user_agent_mode"),
        A("ua.fresh", "Fresh User-Agent", "/api/user-agent/fresh", "category"),
        A("ua.generate", "Generate User-Agent", "/api/user-agent/generate", "category"),
    )),
    "tab-syslog/syslog": (("/api/system/syslog",), (
        A("syslog.dl", "Download system log", "/api/system/syslog/download", method="GET", download=True),
    )),
    "tab-syslog/devlog": (("/api/dev/logs", "/api/dev/crashes"), (
        A("log.level", "Set log level", "/api/dev/loglevel", "level:choice(DEBUG|INFO|WARNING|ERROR) persist:bool"),
        A("log.clear", "Clear developer log", "/api/dev/logs/clear", confirm="YES"),
        A("dev.bundle", "Download the diagnostic bundle", "/api/dev/diagnostic-bundle.tar.gz", method="GET", download=True),
        A("dev.snapshot", "Download the deep system snapshot", "/api/dev/invasive-log.md", method="GET", download=True),
        A("crash.clear", "Clear crash reports", "/api/dev/crashes/clear", confirm="YES"),
        A("log.dl", "Download developer log", "/api/dev/logs/download", method="GET", download=True),
        A("log.purge", "Purge all logs", "/api/system/logs/purge", "include_db:bool include_journal:bool", confirm="PURGE"),
    )),
    "tab-syslog/audit": (("/api/dev/invasive-log",), (
        A("audit.gen", "Generate diagnostic snapshot", "/api/dev/invasive-log/generate"),
    )),
    "tab-terminal": ((), (
        A("term.exec", "Run command", "/api/terminal/exec", "command timeout:int"),
    )),
    "tab-tasks": (("/api/system/tasks",), (
        A("task.kill", "Stop process", "/api/system/tasks/kill", "pid:int signal:choice(15|9|1)", confirm="YES"),
        A("mem.trim", "Trim memory", "/api/system/trim_memory"),
    )),
    "tab-info/rsub-wan": (("/api/system/info", "/api/network/mac", "/api/network/preferred-interface", "/api/network/dns"), (
        A("wan.save", "Save WAN settings", "/api/config", NET_ADDR + " wan2_interface wan2_proto wan2_ip wan2_netmask wan2_gateway wan2_mac wan_mode pppoe_enabled:bool pppoe_user pppoe_password:secret pppoe_vlan:int pppoe_service_name", confirm="YES"),
        A("mac.set", "Set or reset MAC", "/api/network/mac", "action:choice(set|reset) mac", confirm="YES"),
        A("dns.test", "Test DNS", "/api/network/dns/test", "domain"),
        A("dns.fallback", "Apply DNS fallback", "/api/network/dns/fallback", "servers"),
        A("dns.restore", "Restore DNS", "/api/network/dns/restore"),
        A("wired.prio", "Enforce wired priority", "/api/network/enforce-wired-priority"),
    )),
    "tab-info/rsub-lan": (("/api/system/interfaces", "/api/network/devices"), (
        A("lan.save", "Save LAN settings", "/api/config", "gateway_ip gateway_netmask dhcp_enabled:bool dhcp_range_start dhcp_range_end dhcp_lease_time", confirm="YES"),
        A("lan.scan", "Scan devices", "/api/network/devices/scan", "iface"),
    )),
    "tab-info/rsub-portfwd": (("/api/port-forward",), (
        A("pf.save", "Port forwarding and UPnP on or off", "/api/port-forward/save", "enabled:bool upnp:bool"),
        A("pf.rules", 'Port forwarding rules, as a JSON list: [{"name":"nas","proto":"tcp","ext":"8443","ip":"192.168.100.20","port":443,"on":true}]',
          "/api/port-forward/save", "rules:json"),
    )),
    "tab-info/rsub-wifi": (("/api/network/wifi/status", "/api/network/wifi/capabilities"), (
        A("wifi.save", "Save Wi-Fi settings", "/api/config", "wifi_enabled:bool wifi_ssid wifi_psk:secret wifi_band wifi_standard wifi_channel:int wifi_channel_width wifi_country_code wifi_security", confirm="YES"),
    )),
    "tab-info/rsub-guest": (("/api/network/wifi/guest/status", "/api/network/wifi/guest/saved", "/api/network/wifi/guest/scan"), (
        A("guest.connect", "Connect to Wi-Fi", "/api/network/wifi/guest/connect", "ssid password:secret interface metric:int save:bool hidden:bool bssid"),
        A("guest.disconnect", "Disconnect", "/api/network/wifi/guest/disconnect", "interface disable:bool"),
        A("guest.activate", "Use saved network", "/api/network/wifi/guest/saved/activate", "name"),
        A("guest.delete", "Delete saved network", "/api/network/wifi/guest/saved/delete", "name", confirm="YES"),
        A("guest.save", "Save guest settings", "/api/config", "guest_wifi_enabled:bool guest_wifi_interface guest_wifi_ssid guest_wifi_security guest_wifi_metric:int guest_wifi_auto_reconnect:bool"),
    )),
    "tab-info/rsub-ports": (("/api/system/ports", "/api/network/lan-topology", "/api/system/drivers", "/api/system/drivers/status"), (
        A("ports.roles", "Set port roles", "/api/system/interface_roles", "wan1 wan2 wan_mode lan_ports guest wifi_main dmz measurement_interface", confirm="YES"),
        A("topology.save", "Set passthrough and LAG", "/api/network/lan-topology", "lan_passthrough_enabled:bool passthrough_ports lag_enabled:bool lag_ports lag_mode lag_hash_policy lacp_rate", confirm="YES"),
        A("driver.install", "Install driver", "/api/system/install_drivers", "package", confirm="YES"),
    )),
    "tab-info/rsub-mode": (("/api/status",), (
        A("mode.set", "Switch network mode", "/api/mode", "mode:choice(auto|standalone|mode_a|mode_b)", confirm="YES"),
    )),
    "tab-info/rsub-schedule": (("/api/scheduler/status",), (
        A("schedule.router", "Change schedule", "/api/speedtest/schedule", SCHEDULE),
    )),
    "tab-info/rsub-isp": (("/api/config",), (
        A("isp.save", "Save ISP details", "/api/config", "isp_name connection_type account_id circuit_id contract_down_mbps:float guaranteed_down_mbps:float contract_up_mbps:float guaranteed_up_mbps:float"),
    )),
    "tab-info/rsub-kernel": (("/api/system/kernel-tuning",), (
        A("kernel.apply", "Apply kernel tuning", "/api/system/kernel-tuning/apply", confirm="YES"),
        A("mem.profile", "Set memory profile", "/api/system/memory_profile", "memory_profile:choice(auto|low|standard|performance)"),
    )),
    "tab-info/rsub-system": (("/api/system/info", "/api/system/updates/status", "/api/theme", "/api/i18n", "/api/collector/status"), (
        A("cred.save", "Change login", "/api/system/credentials", "username password:secret", confirm="YES"),
        A("collector.save", "Central collector settings", "/api/collector/save",
          "enabled:bool url token:secret case_id interval_min:int share_diagnostics:bool allow_remote_control:bool", confirm="YES"),
        A("collector.send", "Send to the collector now", "/api/collector/send"),
        A("lang.set", "Set language", "/api/i18n", "lang:choice(en|hu|de|fr|uk)"),
        A("theme.set", "Set WebGUI theme", "/api/system/theme", "theme"),
        A("updates.check", "Check for updates", "/api/system/updates/check", method="GET"),
        A("updates.apply", "Install system updates", "/api/system/updates/upgrade", confirm="YES"),
        A("svc.restart", "Restart services", "/api/system/restart-services", confirm="YES"),
        A("svc.reload", "Reload settings", "/api/system/reload"),
        A("sys.reboot", "Reboot", "/api/system/reboot", confirm="YES"),
    )),
    "tab-info/rsub-backup": (("/api/backup/list", "/api/system/purge", "/api/config/drive-status"), (
        A("backup.create", "Create backup", "/api/backup/create", "type:choice(config|full) comment"),
        A("backup.restore", "Restore backup", "/api/backup/restore", "filename restore_db:bool restore_vpn:bool", confirm="YES"),
        A("backup.delete", "Delete backup", "/api/backup/delete", "filename", confirm="YES"),
        A("backup.dl", "Download backup", "/api/backup/download", "file", method="GET", download=True),
        A("drive.sync", "Sync settings to boot drive", "/api/config/drive-sync"),
        A("data.purge", "Purge data", "/api/system/purge", "categories", confirm="PURGE"),
        A("factory.reset", "Factory reset", "/api/backup/reset", "keep_measurements:bool", confirm="RESET"),
    )),
    "tab-info/rsub-heal": (("/api/heal/status", "/api/heal/updates", "/api/heal/update/status"), (
        A("heal.audit", "Run audit", "/api/heal/audit"),
        A("heal.fix", "Repair", "/api/heal/fix", "tier:int"),
        A("heal.update", "Apply stable update", "/api/heal/update/apply", "ref", confirm="YES"),
    )),
    "tab-info/rsub-telegram": (("/api/telegram/status",), (
        A("tg.save", "Save settings", "/api/telegram/save", "enabled:bool bot_token:secret chat_ids alert_on_loss:bool alert_on_latency:bool loss_threshold_pct:float latency_threshold_ms:float"),
        A("tg.service", "Start or stop bot", "/api/telegram/service", "action:choice(start|stop|restart)"),
        A("tg.test", "Send test message", "/api/telegram/test", "chat_id"),
    )),
    "tab-telegram": (("/api/telegram/status",), (
        A("tg2.save", "Save settings", "/api/telegram/save", "enabled:bool bot_token:secret chat_ids alert_on_loss:bool alert_on_latency:bool loss_threshold_pct:float latency_threshold_ms:float"),
        A("tg2.service", "Start or stop bot", "/api/telegram/service", "action:choice(start|stop|restart)"),
        A("tg2.test", "Send test message", "/api/telegram/test", "chat_id"),
    )),
    "tab-llm": (("/api/diagnostics/llm",), (
        A("llm.dl", "Download diagnostic bundle", "/api/diagnostics/download", method="GET", download=True),
    )),
}

# Reached through another name, or by the browser only.
NOT_SHOWN = {
    "/api/auth/logout": "HTTP login is browser only",
    "/api/backup/upload": "needs a browser file upload; copy the file over SSH instead",
    "/api/config/drive": "same data as /api/config/drive-status",
    "/api/config/sync-drive": "same as /api/config/drive-sync",
    "/api/dev/crashes/": "needs a crash id; the list is in the developer log screen",
    "/api/dev/logs/raw": "same data as /api/dev/logs",
    "/api/dns": "same as /api/network/dns",
    "/api/duckdns/save": "same as /api/dyndns/save",
    "/api/duckdns/update": "same as /api/dyndns/update",
    "/api/export": "prefix of the export actions",
    "/api/factory-reset": "same as /api/backup/reset",
    "/api/logs/purge": "same as /api/system/logs/purge",
    "/api/mac": "same as /api/network/mac",
    "/api/reboot": "same as /api/system/reboot",
    "/api/system/factory-reset": "same as /api/backup/reset",
    "/api/credentials": "same as /api/system/credentials",
    "/api/network/tailscale/down": "same as /api/tailscale/down",
    "/api/network/tailscale/logout": "same as /api/tailscale/logout",
    "/api/network/tailscale/save": "same as /api/tailscale/save",
    "/api/network/tailscale/status": "same as /api/tailscale/status",
    "/api/network/tailscale/up": "same as /api/tailscale/up",
    "/api/speedtest/default-server": "same as /api/speedtest/scheduled-server",
    "/api/wifi/guest/connect": "same as /api/network/wifi/guest/connect",
    "/api/wifi/guest/disconnect": "same as /api/network/wifi/guest/disconnect",
    "/api/wifi/guest/saved": "same as /api/network/wifi/guest/saved",
    "/api/wifi/guest/saved/activate": "same as /api/network/wifi/guest/saved/activate",
    "/api/wifi/guest/saved/delete": "same as /api/network/wifi/guest/saved/delete",
    "/api/wifi/guest/scan": "same as /api/network/wifi/guest/scan",
    "/api/wifi/guest/status": "same as /api/network/wifi/guest/status",
}


def clean_label(text: str) -> str:
    """Drop emoji and tags; keep accented letters."""
    text = re.sub(r"<[^>]+>", "", text)
    text = "".join(c for c in text if unicodedata.category(c) not in ("So", "Sk", "Cs", "Mn", "Cf"))
    return re.sub(r"\s+", " ", text).strip()


def read_menu(html_path: Path = DASHBOARD_HTML) -> List[Tab]:
    """Build the menu from the WebGUI page so that both always match."""
    html = html_path.read_text(encoding="utf-8")
    tabs: Dict[str, Tab] = {}
    for match in re.finditer(r"<button[^>]*onclick=\"switchTab\('([\w-]+)'\)\"[^>]*>(.*?)</button>", html, re.S):
        key, label = match.group(1), clean_label(match.group(2))
        i18n = re.search(r'data-i18n="([^"]+)"', match.group(0))
        views, actions = CONTENT.get(key, ((), ()))
        tabs[key] = Tab(key, label, i18n.group(1) if i18n else "", Screen(key, label, "", views, actions), [])
    pattern = r"<button[^>]*onclick=\"(switch\w+Subtab)\('([\w-]+)'\)[^\"]*\"[^>]*>(.*?)</button>"
    for match in re.finditer(pattern, html, re.S):
        parent = SUBTAB_PARENTS.get(match.group(1))
        if parent not in tabs:
            continue
        sub, label = match.group(2), clean_label(match.group(3))
        i18n = re.search(r'data-i18n="([^"]+)"', match.group(0))
        key = f"{parent}/{sub}"
        views, actions = CONTENT.get(key, ((), ()))
        if not any(s.key == key for s in tabs[parent].subs):
            tabs[parent].subs.append(Screen(key, label, i18n.group(1) if i18n else "", views, actions))
    return list(tabs.values())


def all_screens(menu: List[Tab]) -> List[Screen]:
    screens: List[Screen] = []
    for tab in menu:
        screens.extend(tab.subs or [tab.screen])
    return screens


def find_action(menu: List[Tab], action_id: str) -> Optional[Action]:
    for screen in all_screens(menu):
        for action in screen.actions:
            if action.id == action_id:
                return action
    return None


def coerce_value(field: Field, raw: str):
    """Convert typed text to the JSON type the API expects."""
    if field.kind == "bool":
        return raw.strip().lower() in ("1", "true", "yes", "on", "y", "i", "igen")
    if field.kind == "int":
        return int(raw)
    if field.kind == "float":
        return float(raw)
    if field.kind == "json":
        import json
        return json.loads(raw)
    return raw


def build_body(action: Action, values: Dict[str, str]) -> dict:
    """Skip blank fields, so that saving one setting leaves the others unchanged."""
    by_name = {f.name: f for f in action.fields}
    body = {}
    for name, raw in values.items():
        if raw == "" or name not in by_name:
            continue
        body[name] = coerce_value(by_name[name], raw)
    if action.confirm in ("RESET", "PURGE"):
        body["confirm"] = action.confirm
    return body
