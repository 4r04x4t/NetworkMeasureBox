# NetworkMeasureBox (NMB)

**Production-grade, autonomous network quality measurement, SLA verification, and ISP fault escalation appliance.**

Designed for Linux single-board computers (Raspberry Pi, Odroid, Rockchip, x86 appliances) booting from microSD cards. Built entirely using standard Linux utilities and Python standard library (zero external pip dependencies).

---

## Architecture & System Overview

```
                               ┌────────────────────────────────────────────────────────┐
                               │                    ISP Edge (Modem/ONT)                │
                               └───────────────────────────┬────────────────────────────┘
                                                           │
                                                           ▼
┌──────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│ NetworkMeasureBox Appliance (SBC, microSD)                                                                       │
│                                                                                                                  │
│  ┌──────────────────────────────────────────────┐          ┌──────────────────────────────────────────────────┐  │
│  │ Dual-Mode Network Daemon (nmb-netd)          │          │ High-Frequency Probe Engine (nmb-probe)          │  │
│  │ • Mode A: PPPoE/NAT/hostapd AP/dnsmasq DHCP  │          │ • Sub-second ICMP Echo Polling (500ms)           │  │
│  │ • Mode B: Passive Transparent Bridge (br0)   │          │ • RFC 3550 Jitter & Multi-target Loss Tracking   │  │
│  │ • Auto-failover detection & debouncing       │          │ • Outage window detection & event logging        │  │
│  └──────────────────────┬───────────────────────┘          └────────────────────────┬─────────────────────────┘  │
│                         │                                                           │                            │
│                         ▼                                                           ▼                            │
│  ┌──────────────────────────────────────────────┐          ┌──────────────────────────────────────────────────┐  │
│  │ Traffic-Gated Measurement Engine (nmb-speed) │          │ Data Analytics & Report Generator (nmb-report)   │  │
│  │ • /proc/net/dev idle gate (<500 kbps window) │          │ • Standalone HTML dossier with embedded SVGs     │  │
│  │ • Ookla Speedtest CLI & CDN fallback wrapper │          │ • Raw RFC 4180 CSV telemetry exporter            │  │
│  │ • Net-neutrality TCP/UDP port throttle check │          │ • Automated SMTP dispatch for ISP fault tickets  │  │
│  └──────────────────────┬───────────────────────┘          └────────────────────────┬─────────────────────────┘  │
│                         │                                                           │                            │
│                         ▼                                                           ▼                            │
│  ┌────────────────────────────────────────────────────────────────────────────────────────────────────────────┐  │
│  │ Storage Architecture (microSD Longevity & Flash Protection)                                                │  │
│  │ • Hot SQLite WAL database in RAM tmpfs (/var/lib/nmb/live/nmb.db)                                          │  │
│  │ • Consistent online snapshots to microSD (/var/lib/nmb/persist/nmb.db) every 15 min & at shutdown         │  │
│  │ • ext4 noatime,commit=600, volatile journald, swap disabled, 10G NIC ring buffer & sysctl BBR tuning       │  │
│  └────────────────────────────────────────────────────────────────────────────────────────────────────────────┘  │
│                                                                                                                  │
│  ┌──────────────────────────────────────────────┐          ┌──────────────────────────────────────────────────┐  │
│  │ Telegram Management Bot (nmb-telegram)       │          │ Embedded Web Management UI & API (nmb-web)       │  │
│  │ • /status, /ping, /test, /report, /mode      │          │ • Port 8080 responsive dark-mode dashboard       │  │
│  │ • Proactive push alerts (outages & loss >5%) │          │ • REST API, live SVG graphs, config editor       │  │
│  └──────────────────────────────────────────────┘          └──────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
                                                           │
                                                           ▼
                               ┌────────────────────────────────────────────────────────┐
                               │                 Customer LAN / Router                  │
                               └────────────────────────────────────────────────────────┘
```

---

## Quickstart / Automated Installation

Run the unattended one-line installer on a fresh Debian, Ubuntu, Raspberry Pi OS, or Alpine Linux system:

```bash
sudo ./setup.sh
```

The installer will automatically:
1. Install network tools (`iproute2`, `nftables`, `iptables`, `ethtool`, `dnsmasq`, `hostapd`, `ppp`, `speedtest`).
2. Configure tmpfs mounts and flash longevity parameters for microSD cards.
3. Apply kernel sysctl buffers (10G burst optimization, BBR congestion control, unprivileged ICMP).
4. Deploy the application into `/opt/nmb` and install CLI wrappers into `/usr/local/bin/`.
5. Enable and launch the systemd target (`nmb.target`).

After installation, open the web dashboard in your browser:
```
http://<appliance-ip>:8080
```

---

## Command Line Utilities

| Binary | Description | Key Commands |
|---|---|---|
| `nmb-netd` | Network mode daemon | `nmb-netd --status`<br>`nmb-netd --switch auto\|mode_a\|mode_b` |
| `nmb-probe` | Continuous latency/jitter probe engine | `nmb-probe --verbose` |
| `nmb-speed` | Speedtest & net-neutrality runner | `nmb-speed --trigger manual`<br>`nmb-speed --force --ports 80,443,8080` |
| `nmb-report` | HTML dossier & CSV generator | `nmb-report --window 24h --html /path/dossier.html`<br>`nmb-report --json-summary`<br>`nmb-report --send-email` |
| `nmb-telegram` | Management Telegram Bot daemon | `nmb-telegram` |
| `nmb-web` | Embedded management web UI | `nmb-web --port 8080` |

---

## Configuration Reference (`/etc/nmb/nmb.conf`)

Edit `/etc/nmb/nmb.conf` or manage via the Web UI Settings tab:

```ini
[network]
mode = auto                   # auto, mode_a (active gateway), mode_b (passive bridge)
wan_interface = eth0
lan_interface = eth1
wlan_interface = wlan0
bridge_interface = br0

# Mode A Settings
gateway_ip = 192.168.100.1
dhcp_range_start = 192.168.100.100
dhcp_range_end = 192.168.100.200
pppoe_enabled = false
pppoe_user = 
pppoe_password = 
wifi_enabled = true
wifi_ssid = NMB-Diagnostic
wifi_psk = NetworkMeasureBox123

[isp]
name = Example Fiber Internet
account_id = CUST-104928
circuit_id = CKT-FIBER-01
contract_down_mbps = 1000.0
contract_up_mbps = 500.0

[telegram]
enabled = false
token = 
allowed_chat_ids = 
alert_loss_threshold_pct = 5.0

[smtp]
enabled = false
host = localhost
port = 587
tls = true
to_addrs = support@isp.com
```

---

## Service Management (`systemd`)

The entire suite is grouped under `nmb.target`:

```bash
# Check overall status
sudo systemctl status nmb.target

# Restart all services
sudo systemctl restart nmb.target

# View live probe engine logs
sudo journalctl -u nmb-probe -f

# View mode switching events
sudo journalctl -u nmb-netd -f
```
