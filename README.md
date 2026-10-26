# NetworkMeasureBox (NMB)

**Production-grade, autonomous network quality measurement, SLA verification, ISP fault escalation appliance, and high-performance intelligent Linux router.**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Platform: Linux](https://img.shields.io/badge/Platform-Linux%20%28Debian%20%7C%20Alpine%20%7C%20OpenWrt%20%7C%20Arch%29-green.svg)](https://kernel.org)
[![Python: 3.9+](https://img.shields.io/badge/Python-3.9%2B%20%28Zero%20External%20Pip%20Deps%29-yellow.svg)](https://python.org)
[![Hardware: 512MB+ RAM](https://img.shields.io/badge/RAM-512MB%20to%2064GB-purple.svg)](#embedded--low-memory-optimization-512-mb-ram-support)
[![Languages: EN HU DE UK FR](https://img.shields.io/badge/Languages-EN%20%7C%20HU%20%7C%20DE%20%7C%20UK%20%7C%20FR-orange.svg)](#responsive-webgui--rest-api)

> 📖 **[Kattints ide a részletes magyar nyelvű leíráshoz / Read the comprehensive Hungarian Guide](README.hu.md)**

---

## What is NetworkMeasureBox?

**NetworkMeasureBox (NMB)** is an autonomous, 24/7 network intelligence appliance engineered to settle disputes between broadband consumers/enterprises and Internet Service Providers (ISPs).

When internet connections experience micro-outages, packet drops, severe evening speed degradations, or bufferbloat, ISP support typically responds with: *"Everything looks good on our end; the issue must be your internal home network or Wi-Fi."*

NMB eliminates this finger-pointing by placing an unbiased, carrier-grade measurement system directly at your network perimeter. It operates either as your **primary high-performance router (Mode A)** or as an **invisible, passive inline bridge (Mode B)** between your modem/ONT and existing router. It continuously gathers forensic telemetry, computes RFC 3550 jitter, verifies net-neutrality throttling, and generates legal-grade HTML dossiers with embedded vector SVGs to prove contractual SLA breaches directly to ISP support or telecommunications regulators (e.g., NMHH, FCC, BEREC, RTR).

---

## System Architecture

```
                               ┌────────────────────────────────────────────────────────┐
                               │                    ISP Edge (Modem/ONT)                │
                               └───────────────────────────┬────────────────────────────┘
                                                           │
                                                           ▼
┌──────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│ NetworkMeasureBox Appliance (SBC, x86 Mini PC, 512MB Router)                                                     │
│                                                                                                                  │
│  ┌──────────────────────────────────────────────┐          ┌──────────────────────────────────────────────────┐  │
│  │ Dual-Mode Network Daemon (nmb-netd)          │          │ High-Frequency Probe Engine (nmb-probe)          │  │
│  │ • Mode A: Router (PPPoE/NAT/hostapd/dnsmasq) │          │ • Sub-second ICMP Echo Polling (500ms)           │  │
│  │ • Mode B: Passive Transparent Bridge (br0)   │          │ • RFC 3550 Jitter & Multi-target Loss Tracking   │  │
│  │ • Multi-WAN failover & Multi-LAN br-lan      │          │ • Micro-outage window logging                    │  │
│  └──────────────────────┬───────────────────────┘          └────────────────────────┬─────────────────────────┘  │
│                         │                                                           │                            │
│                         ▼                                                           ▼                            │
│  ┌──────────────────────────────────────────────┐          ┌──────────────────────────────────────────────────┐  │
│  │ Traffic-Gated Measurement Engine (nmb-speed) │          │ Data Analytics & Report Generator (nmb-report)   │  │
│  │ • /proc/net/dev idle gate (<500 kbps window) │          │ • Standalone HTML dossier with embedded SVGs     │  │
│  │ • 5 Engines: Ookla, Cloudflare, RTR, iPerf,FW│          │ • Raw RFC 4180 CSV telemetry exporter            │  │
│  │ • Net-neutrality TCP/UDP port throttle check │          │ • Automated SMTP dispatch for ISP fault tickets  │  │
│  └──────────────────────┬───────────────────────┘          └────────────────────────┬─────────────────────────┘  │
│                         │                                                           │                            │
│                         ▼                                                           ▼                            │
│  ┌────────────────────────────────────────────────────────────────────────────────────────────────────────────┐  │
│  │ Storage Architecture & Memory Optimization (512MB RAM & Flash Protection)                                  │  │
│  │ • Hot SQLite WAL database in RAM tmpfs (/var/lib/nmb/live/nmb.db)                                          │  │
│  │ • Atomic consistent snapshots to microSD (/var/lib/nmb/persist/nmb.db) every 15 min & at shutdown          │  │
│  │ • Embedded memory profiles (48MB cap, malloc_trim(0) heap reclaim), ext4 commit=600, volatile journald     │  │
│  └────────────────────────────────────────────────────────────────────────────────────────────────────────────┘  │
│                                                                                                                  │
│  ┌──────────────────────────────────────────────┐          ┌──────────────────────────────────────────────────┐  │
│  │ Telegram Management Bot (nmb-telegram)       │          │ Embedded Web Management UI & API (nmb-web)       │  │
│  │ • /status, /ping, /test, /report, /mode      │          │ • Port 8080 responsive dark-mode dashboard       │  │
│  │ • Proactive push alerts (outages & loss >5%) │          │ • 14+ subtabs, 5 languages (100% parity), Logout │  │
│  └──────────────────────────────────────────────┘          └──────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
                                                           │
                                                           ▼
                               ┌────────────────────────────────────────────────────────┐
                               │                 Customer LAN / Devices                 │
                               └────────────────────────────────────────────────────────┘
```

---

## Core Capabilities

### 1. Dual Operating Modes
* **Mode A (Active Gateway / Router)**:
  * Full router replacement with PPPoE client (including 802.1Q VLAN tagging), dynamic DHCP or static IP WAN.
  * Local gateway services: `dnsmasq` DHCP server, DNS caching, and iptables/nftables NAT masquerading.
  * Integrated Wi-Fi Access Point (`hostapd`) supporting IEEE 802.11 b/g/n/ac/ax/be across 2.4 GHz, 5 GHz, and 6 GHz bands.
  * Smart Queue Management (SQM) with CAKE and fq_codel algorithms to eliminate bufferbloat under line saturation.
* **Mode B (Passive Transparent Inline Bridge)**:
  * Inserts invisibly between an existing modem/ONT and router without taking an IP address on the customer subnet.
  * Operates as a stealth Layer 2 bridge (`br0`) to audit line telemetry with zero interference.
* **Auto-Failover**: Automatically detects carrier loss and can switch operational states.

### 2. Multi-NIC, Multi-WAN & Multi-LAN Architecture
* **Port Role Assignment Matrix**: Interactive WebGUI matrix mapping physical network cards (PCIe, USB, onboard) to:
  * **WAN 1 (Primary)**: Main uplink.
  * **WAN 2 (Secondary)**: Failover backup or active-active load-balancing uplink with independent DHCP/static settings.
  * **LAN (br-lan Bridge)**: Any number of physical Ethernet ports automatically grouped into unified Linux network bridge `br-lan` (`192.168.100.1/24`).
  * **DMZ**: Isolated physical port.
  * **Guest Wi-Fi Client Probe**: Dedicated wireless card for client probe testing.
* **Target Interface Benchmarking**: Speed tests can be pinned to specific network interfaces via CLI (`-i` / `--interface`) or WebGUI dropdown to compare WAN1 vs WAN2 throughput directly.

### 3. Automated Hardware Driver & Firmware Management
* Detects physical controllers (Realtek RTL8111/8168/8125/8126, Intel e1000e/igb/igc/ixgbe, Broadcom, MediaTek MT7921, Qualcomm Atheros, ASIX USB, Aquantia 10G).
* Inspects `dmesg` ring buffer to detect missing non-free kernel firmware blobs.
* Built-in one-click package installer via `nmb-helper install-drivers` across Debian (`apt`), OpenWrt (`opkg`), Alpine (`apk`), Arch (`pacman`), and Fedora (`dnf`) with real-time WebGUI terminal logging.

### 4. 5 Complementary Measurement Engines
1. **High-Frequency ICMP Probe (`nmb-probe`)**: 500ms continuous sampling to 4 independent reference targets (ISP Gateway, Cloudflare `1.1.1.1`, Google `8.8.8.8`, Quad9 `9.9.9.9`), RFC 3550 jitter calculation, p95/p99 latency tracking, and exact outage duration logging.
2. **Ookla Speedtest CLI**: Official Ookla binary runner with automatic server detection or custom server targeting.
3. **Cloudflare Speed Engine**: Official multipart 100MB/25MB CDN edge throughput benchmarking.
4. **RTR-Netztest (RMBT)**: Open-source regulatory benchmark conforming to European BEREC and Austrian RTR standards.
5. **iPerf3 Client & Managed Server**: Local LAN and public WAN throughput benchmarking across TCP and UDP with parallel threads.
6. **Net-Neutrality Port Throttle Checker**: Audits whether the ISP throttles specific ports (HTTP 80, HTTPS 443, Alt-HTTP 8080, SSH 22, BitTorrent, VoIP).
7. **Traffic Gate**: Monitors `/proc/net/dev` and postpones scheduled tests if existing customer LAN traffic exceeds 500 kbps.

### 5. Embedded & Low-Memory Optimization (512 MB RAM Support)
Specially engineered to run seamlessly on resource-constrained **512 MB RAM routers** (e.g., ASUS routers or SBCs running embedded Linux/OpenWrt):
* **`embedded` profile**: Restricts hot SQLite RAM DB to 48 MB, trims SQLite cache to 2 MB, limits TCP buffers to 8 MB.
* **Native Heap Reclaim**: Proactively invokes `libc.malloc_trim(0)` and Python garbage collection to immediately release unmapped heap memory back to the Linux kernel.
* **`standard` (1-2GB) & `performance` (4GB+) profiles**: Scalable buffer tuning for multi-gigabit workloads.

### 6. Storage Protection & microSD Longevity
* **Hot RAM Database**: Live telemetry runs in tmpfs (`/var/lib/nmb/live/`) using SQLite Write-Ahead Logging (WAL). Zero constant disk writes to flash memory.
* **Atomic Snapshots**: The SQLite Online Backup API copies a consistent snapshot to persistent flash storage (`/var/lib/nmb/persist/nmb.db`) every 15 minutes and upon system shutdown.
* **Filesystem Optimizations**: ext4 mounted with `noatime,commit=600`, swap disabled, journald set to `Storage=volatile`.

### 7. Responsive WebGUI & REST API
* Modern dark-themed dashboard on **port 8080**.
* Live inline SVG graphs, historical speed records, network device explorer (ARP sweep & MAC vendor lookup), real-time syslog inspector, and one-click diagnostic LLM bundle generation.
* **100% Internationalization (i18n)**: Fully translated into 5 languages with complete key parity:
  * 🇬🇧 English (EN)
  * 🇭🇺 Hungarian (HU)
  * 🇩🇪 German (DE)
  * 🇺🇦 Ukrainian (UK)
  * 🇫🇷 French (FR)
* HTTP Basic Authentication with dedicated secure Logout functionality.

### 8. Official HTML Dossier & Telegram Bot
* **Standalone Evidence Dossier**: Generates an offline HTML report with embedded vector SVGs, SLA contract breach analysis tables, and micro-outage audits that can be submitted to ISP support or legal authorities.
* **Telegram Bot (`nmb-telegram`)**: Real-time push alerts on outages or packet loss > 5%, plus remote command execution (`/status`, `/ping`, `/test`, `/report`, `/mode`).

---

## Quickstart / Automated Installation

Run the unattended one-line installer on a fresh Debian, Ubuntu, Raspberry Pi OS, or Alpine Linux system:

```bash
git clone https://github.com/4r04x4t/NetworkMeasureBox.git
cd NetworkMeasureBox
sudo ./setup.sh
```

The installer will automatically:
1. Install network tools (`iproute2`, `nftables`, `iptables`, `ethtool`, `pciutils`, `usbutils`, `dnsmasq`, `hostapd`, `ppp`, `speedtest`).
2. Configure tmpfs mounts and flash longevity parameters for microSD cards.
3. Apply kernel sysctl buffers (10G burst optimization, BBR congestion control, unprivileged ICMP).
4. Deploy the application into `/opt/nmb` and install CLI wrappers into `/usr/local/bin/`.
5. Enable and launch the systemd target (`nmb.target`).

After installation, open the web dashboard in your browser:
```
http://<appliance-ip>:8080
```
* **Default credentials**: `admin` / `admin` (change immediately in the Settings tab).

---

## Command Line Utilities

| Binary | Description | Key Commands |
|---|---|---|
| `nmb-netd` | Network daemon (Router / Bridge / Multi-WAN) | `nmb-netd --status`<br>`nmb-netd --switch auto\|mode_a\|mode_b` |
| `nmb-probe` | Continuous latency/jitter ICMP engine | `nmb-probe --verbose` |
| `nmb-speed` | Speedtest & net-neutrality runner | `nmb-speed --trigger manual`<br>`nmb-speed --engine cloudflare`<br>`nmb-speed --interface eth0` |
| `nmb-report` | HTML dossier & CSV generator | `nmb-report --window 24h --html dossier.html`<br>`nmb-report --json-summary`<br>`nmb-report --send-email` |
| `nmb-telegram` | Management Telegram Bot daemon | `nmb-telegram` |
| `nmb-web` | Embedded management web UI & REST API | `nmb-web --port 8080` |
| `nmb-helper` | Privileged helper utility (drivers, routing) | `sudo nmb-helper install-drivers all`<br>`sudo nmb-helper tune` |

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

# View speedtest runner logs
sudo journalctl -u nmb-speed -f
```

---

## License

This project is licensed under the **MIT License** — free for personal, community, and commercial use.
