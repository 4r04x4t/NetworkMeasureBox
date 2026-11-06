# NetworkMeasureBox (NMB)

**Production-grade, autonomous network quality measurement, SLA verification, ISP fault escalation appliance, and high-performance intelligent Linux router.**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Platform: Linux](https://img.shields.io/badge/Platform-Linux%20%28Debian%20%7C%20Alpine%20%7C%20OpenWrt%20%7C%20Arch%29-green.svg)](https://kernel.org)
[![Python: 3.9+](https://img.shields.io/badge/Python-3.9%2B%20%28Zero%20External%20Pip%20Deps%29-yellow.svg)](https://python.org)
[![VPN: WireGuard & Tailscale](https://img.shields.io/badge/VPN-WireGuard%20%7C%20OpenVPN%20%7C%20Tailscale-blueviolet.svg)](#8-universal-remote-access-vpn-hub--tailscale-mesh)
[![Hardware: 512MB+ RAM](https://img.shields.io/badge/RAM-512MB%20to%2064GB-purple.svg)](#embedded--low-memory-optimization-512-mb-ram-support)
[![Native: Go & C11 Roadmap](https://img.shields.io/badge/Native%20Port-ASUS%20%7C%20TP--Link%20%28Go%20%26%20C11%29-teal.svg)](#15-100-de-pythonization-architecture--commercial-router-porting)
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
│  │ • /status, /ping, /test, /report, /mode      │          │ • Standard router Port 80 dashboard (dev 8080)   │  │
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
* Modern dark-themed router dashboard on **standard HTTP port 80** (with automatic unprivileged fallback to port 8080 for development).
* Live inline SVG graphs, historical speed records, network device explorer (ARP sweep & MAC vendor lookup), real-time syslog inspector, and one-click diagnostic LLM bundle generation.
* **100% Internationalization (i18n)**: Fully translated into 5 languages with complete key parity:
  * 🇬🇧 English (EN)
  * 🇭🇺 Hungarian (HU)
  * 🇩🇪 German (DE)
  * 🇺🇦 Ukrainian (UK)
  * 🇫🇷 French (FR)
* HTTP Basic Authentication with dedicated secure Logout functionality.

### 8. Universal Remote Access, VPN Hub & Tailscale Mesh
* **PiVPN 1-Click Client Generator**:
  * Dual-Protocol VPN Server: **WireGuard** (UDP 51820, high-speed, battery efficient) and **OpenVPN** (UDP 1194, Elliptic Curve `prime256v1` / Curve25519).
  * Dual-Stack Tunneling: Full IPv4 (`10.8.0.0/24`, `10.9.0.0/24`) and direct IPv6 ULA (`fd42:42:42::/64`, `fd42:42:43::/64`).
  * Instant Client Pairing: Enter client name $\to$ automatically generates configuration profile and interactive camera-scannable QR code directly on the WebUI and in Telegram!
  * Peer Management: Real-time connected peer roster with endpoint IPs, latest handshake, RX/TX transfer statistics, and revocation toggles.
* **Tailscale Secure Mesh Remote Access**:
  * **Management-Plane Isolation**: Direct encrypted access to the WebUI dashboard from anywhere in the world without public port forwarding, dynamic DNS, or firewall opening.
  * Completely bypasses Carrier-Grade NAT (CGNAT) and multi-router cascades.
  * Real-time MagicDNS domain, Tailscale IPv4/IPv6 status, and one-click Connect / Disconnect controls directly from the WebUI.
* **DynDNS & Embedded HTTPS Reverse Proxy**:
  * Integrated DuckDNS dynamic DNS updater.
  * Embedded HTTPS reverse proxy for secure TLS-encrypted LAN access.

### 9. Embedded DNS Ad-Blocker & Privacy Shield (Pi-hole Alternative)
* **High-Performance In-Memory Sinkhole**:
  * Blocks tracking, intrusive telemetry, malware, and advertisement domains before they ever reach customer LAN devices.
  * Pre-configured blocklist subscriptions (StevenBlack unified hosts, AdAway, etc.) with automatic background Gravity updates.
* **Custom Control & Live Audit**:
  * Real-time DNS query statistics: Total queries today, blocked queries, sinkhole percentage, and active Gravity domain count.
  * Custom domain blacklist, whitelist, and wildcard RegEx filtering (`/api/adblock/regex/add`).
  * Live DNS query log inspection streaming directly in the WebUI.

### 10. Advanced Forensic Diagnostics & Root-Cause Telemetry
* **Wi-Fi RF & PHY Telemetry (`nl80211`)**:
  * Real-time RSSI signal strength in exact dBm (e.g. `-52 dBm`) and Noise floor.
  * RX/TX PHY bitrates, MCS (Modulation and Coding Scheme) index, channel width (20/40/80/160 MHz), and hardware retry/fail counters (`tx_retries`, `tx_failed`).
* **DNS Hijacking & Comparative Resolver Matrix**:
  * Concurrently audits 4 independent resolver tiers: Local Gateway/DHCP, Cloudflare (`1.1.1.1`), Google (`8.8.8.8`), and Quad9 (`9.9.9.9`).
  * Verifies DNSSEC validation (`ad` Authenticated Data bit) and compares cached vs uncached response times.
  * Tests for transparent ISP UDP port 53 interception/hijacking.
* **RFC 5389 STUN Client & Carrier-Grade NAT (CGNAT) Detection**:
  * Classifies upstream topology into:
    * **Direct Public IP**: Local WAN IP matches external STUN reflexive IP.
    * **Carrier-Grade NAT (ISP CGNAT)**: Upstream WAN IP falls within RFC 6598 (`100.64.0.0/10`).
    * **Double NAT**: Local WAN IP is an RFC 1918 private address (`192.168.x.x` or `10.x.x.x`).
    * **NAT Mapping Reflexivity**: Classifies Full Cone, Restricted, Port-Restricted, or Symmetric NAT.
* **CPU Interrupt (IRQ/SoftIRQ) & NIC Offload Telemetry**:
  * Tracks per-core interrupt and SoftIRQ distribution to catch CPU0 saturation bottlenecks (the classic Gigabit bottleneck on Raspberry Pi and MIPS routers).
  * Inspects Receive Packet Steering (RPS/XPS) bitmasks (`/sys/class/net/<iface>/queues/rx-*/rps_cpus`) and NIC hardware offloads (checksumming, TSO, GRO via `ethtool`).
* **Micro-Outage & Loss Pattern Correlation**:
  * Continuously classifies dropped packets: isolates micro-burst jitter from catastrophic macro-outages ($\ge 5\text{s}$).
  * Root-cause correlation: Automatically identifies whether an outage is local CPE/gateway failure or upstream ISP transit peering failure.
* **Storage I/O & Flash Filesystem Health**:
  * `%iowait` CPU tracking to detect failing or saturated microSD / flash storage.
  * Filesystem wear and free capacity tracking via standard POSIX `statvfs()`.
  * Kernel `dmesg`/`kmsg` ring-buffer traps catching hardware I/O and ext4/squashfs corruptions.
* **Sanitized Configuration & PII Masking**:
  * Built-in redactor protecting customer privacy: automatically masks bot tokens, chat IDs, Wi-Fi PSKs, ISP account numbers, and circuit IDs before generating dossiers or exporting diagnostic snapshots.

### 11. Multilingual Telegram Chatbot with Interactive Touch Menus
* Fully autonomous chatbot (`nmb-telegram`) providing mobile management without browser access:
  * **Interactive Touch Menus**: Inline keyboards for 1-click status audits, instant ping matrix, on-demand speed tests, and VPN QR generation.
  * **100% Internationalization (i18n)**: Seamless switching between **English (EN)**, **Hungarian (HU)**, **German (DE)**, **French (FR)**, and **Ukrainian (UK)** with zero mixed-language leaks.
  * **Instant SLA Dossier Delivery**: Sends complete `.html` reports directly into the chat for forwarding to ISP technicians.
  * **Proactive Push Alerts**: Immediate alerts on link down, loss $>5\%$, high jitter, or service degradation.

### 12. Regulatory-Grade Broadband SLA Evidence Dossier & Pure SVG Charts
* **Neutral International Branding**:
  * Completely neutral title: *"Broadband Quality & ISP SLA Performance Dossier"* / *"Szélessávú Hálózati Minőség & Szolgáltatói SLA Vizsgálati Dosszié"*.
  * Fully compliant with European BEREC guidelines and international telecom regulatory standards (FCC, RTR, NMHH).
* **Pure Mathematical SVG Vector Engine**:
  * Zero external charting dependencies: emits responsive `<svg viewBox="0 0 800 380">` with cubic bezier curves, dual y-axes (Mbps & ms), SLA threshold baselines, and touch dot overlays.
  * Rendered in sub-millisecond execution time.
  * Exportable directly in 5 languages via `/dossier?lang=...` or Telegram `/report`.

### 13. Real-Time Task Manager (Embedded htop Engine)
* Direct `/proc` virtual filesystem reader replacing heavy `ps` process spawning.
* Real-time process monitoring: PID, User, Priority, Nice, VIRT, RES, CPU%, MEM%, runtime, and command arguments.
* Interactive filtering: System Services vs User Apps vs NMB Daemons.
* In-line signal management: Send SIGTERM or SIGKILL to rogue processes directly from the WebUI.

### 14. Autonomous Self-Healing & Safety Rollback Watchdog (`nmb-heal`)
* Automated background health audits verifying binary integrity, database health, permissions, and network connectivity.
* Cryptographic signature verification and atomic executable replacement (`os.Rename`).
* **Automated Safety Rollback**: If a software update fails integrity checks or breaks critical services, the watchdog automatically reverts to the previous snapshot.
* Hardware Watchdog Timer support (`/dev/watchdog`) to prevent system lockups on remote unattended installations.

### 15. 100% De-Pythonization Architecture & Commercial Router Porting
To run NetworkMeasureBox directly on commercial embedded routers with as little as **4MB Flash and 32MB RAM**, a complete 100% de-pythonization roadmap and implementation specification has been engineered:
* **Unified Single Binary (`nmbd`)**: Written in **Go 1.23+** (Tier 1) and **C11 with Musl libc** (Tier 2 & 3), completely eliminating Python 3, pip, and all runtime packages.
* **Target Hardware Porting Specifications**:
  * **ASUS RT-AXE7800** (Broadcom BCM6756 Quad-Core ARM @ 1.7GHz, 512MB RAM, 256MB Flash, 1x 2.5GbE + 4x 1GbE, Tri-Band Wi-Fi 6E, Asuswrt / Asuswrt-Merlin GNUton): 2.5 Gbps line-rate testing, Flow Cache acceleration bypass, multi-threaded CAKE SQM, and in-process `tsnet` Tailscale.
  * **ASUS RT-N12+** (MediaTek MT7620N ver:2 eco:6 MIPS24KEc @ 580MHz, 32MB RAM, 8MB Flash, Fast Ethernet, OpenWrt `ramips/mt7620`): 850 KB C11 binary (320 KB UPX), 2.8 MB RAM RSS, 100 Mbps line-rate testing at <14% CPU.
  * **TP-Link TL-WR740N v4.x / v4.23** (Atheros AR9331 MIPS 24Kc @ 400MHz, 32MB RAM, **4MB Flash**, Minimal Stripped OpenWrt `ath79/generic`): **178 KB UPX-LZMA compressed binary**, 1.4 MB RAM RSS, 100% RAM-only circular ring-buffer to prevent flash wear!
* Full technical blueprints available in:
  * 📄 **[`docs/ROUTER_PORTING_AND_DEPYTHONIZATION_PLAN.md`](docs/ROUTER_PORTING_AND_DEPYTHONIZATION_PLAN.md)**
  * 📄 **[`docs/DEPYTHONIZATION_ROADMAP.md`](docs/DEPYTHONIZATION_ROADMAP.md)**

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

After installation, open the web dashboard directly in your browser without entering a port:
```
http://<appliance-ip>/
```
* **Default credentials**: `admin` / dynamically generated on setup (mirrored to `/boot/firmware/nmb_credentials.txt` and `/var/lib/nmb/credentials.txt`). Change immediately in the Settings tab.

---

## Command Line Utilities

| Binary | Description | Key Commands |
|---|---|---|
| `nmb-netd` | Network daemon (Router / Bridge / Multi-WAN) | `nmb-netd --status`<br>`nmb-netd --switch auto\|mode_a\|mode_b`<br>`nmb-netd --matrix` |
| `nmb-probe` | Continuous latency/jitter ICMP engine | `nmb-probe --verbose`<br>`nmb-probe --target 1.1.1.1` |
| `nmb-speed` | Speedtest & net-neutrality runner | `nmb-speed --trigger manual`<br>`nmb-speed --engine ookla\|cloudflare\|rtr\|iperf`<br>`nmb-speed --interface eth0` |
| `nmb-report` | HTML dossier & CSV generator | `nmb-report --window 24h --html dossier.html --lang en\|hu\|de\|fr\|uk`<br>`nmb-report --json-summary`<br>`nmb-report --send-email` |
| `nmb-adblock` | High-performance DNS sinkhole | `nmb-adblock --status`<br>`nmb-adblock --update-gravity`<br>`nmb-adblock --block domain.com` |
| `nmb-heal` | Self-healing watchdog & safety rollback | `nmb-heal --audit`<br>`nmb-heal --verify`<br>`nmb-heal --rollback` |
| `nmb-driver` | Hardware driver & firmware autodiscovery | `nmb-driver --scan`<br>`sudo nmb-driver --install-missing` |
| `nmb-telegram` | Management Telegram Bot daemon | `nmb-telegram` |
| `nmb-web` | Embedded management web UI & REST API | `nmb-web` (port 80 / dev 8080) |
| `nmb-helper` | Privileged helper utility (drivers, routing) | `sudo nmb-helper install-drivers all`<br>`sudo nmb-helper tune` |

---

## Interactive Telegram Bot Commands

When `nmb-telegram` is configured, you can manage the entire appliance directly from Telegram with interactive touch menus:

| Command | Description |
|---|---|
| `/menu` | Opens the main interactive Touch Menu (Inline Keyboards) |
| `/status` | Real-time appliance status: uptime, WAN mode, public IP, ISP name, CPU/RAM load |
| `/ping` | Instant latency, jitter, and packet loss matrix to 4 reference targets |
| `/test [engine]` | Runs an on-demand speedtest (`ookla`, `cloudflare`, `rtr`, `iperf`) with bufferbloat rating |
| `/report [window]` | Generates and sends the official Broadband SLA Dossier (`.html`) directly into the chat |
| `/ai` | Exports the sanitized Markdown diagnostic snapshot for external LLM analysis |
| `/mode [auto\|a\|b]`| Views or switches operational mode (Active Router vs Passive Bridge) |
| `/vpn` | PiVPN Hub status: active WireGuard & OpenVPN tunnels, connected client counts |
| `/vpn clients` | Displays connected peer roster with handshake times, endpoints, and RX/TX traffic |
| `/vpn qr <name>` | Generates and dispatches a camera-scannable QR code PNG for instant device pairing |
| `/vpn conf <name>`| Dispatches the downloadable `.conf` profile for WireGuard or OpenVPN |
| `/vpn add <name>` | Creates a new VPN client profile and returns the QR code |
| `/adblock` | DNS Sinkhole status: total queries today, blocked queries, blocklist domain count |
| `/adblock on\|off` | Enables or disables the DNS Ad-Blocker sinkhole |
| `/lang [en\|hu\|de\|fr\|uk]` | Switches the bot's language across 5 supported international languages |

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
