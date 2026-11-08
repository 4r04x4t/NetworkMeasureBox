# NetworkMeasureBox (NMB)

**Autonomous network quality measurement and SLA reporting software for Linux, with optional router and bridge modes. Developed and run on the Raspberry Pi 4.**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Platform: Linux](https://img.shields.io/badge/Developed%20on-Raspberry%20Pi%204-green.svg)](https://kernel.org)
[![Python: 3.9+](https://img.shields.io/badge/Python-3.9%2B%20%28Zero%20External%20Pip%20Deps%29-yellow.svg)](https://python.org)
[![VPN: WireGuard & Tailscale](https://img.shields.io/badge/VPN-WireGuard%20%7C%20OpenVPN%20%7C%20Tailscale-blueviolet.svg)](#8-universal-remote-access-vpn-hub--tailscale-mesh)
[![Router ports: planned](https://img.shields.io/badge/Router%20Ports-Planned%2C%20not%20implemented-lightgrey.svg)](#15-100-de-pythonization-architecture--commercial-router-porting)
[![Languages: EN HU DE UK FR](https://img.shields.io/badge/Languages-EN%20%7C%20HU%20%7C%20DE%20%7C%20UK%20%7C%20FR-orange.svg)](#responsive-webgui--rest-api)

> 📖 **[Kattints ide a részletes magyar nyelvű leíráshoz / Read the comprehensive Hungarian Guide](README.hu.md)**

---

## What is NetworkMeasureBox?

**NetworkMeasureBox (NMB)** runs 24/7 and records your connection quality, to give you evidence when you dispute a problem with your Internet Service Provider (ISP).

When internet connections experience micro-outages, packet drops, severe evening speed degradations, or bufferbloat, ISP support typically responds with: *"Everything looks good on our end; the issue must be your internal home network or Wi-Fi."*

NMB records independent measurements at your network edge. It can run behind your router (`standalone`), as a router (Mode A), or as a transparent bridge between modem and router (Mode B), and it keeps latency, jitter, packet loss, outage and speed data for reports. Only traffic passing through the box is visible to it, so where you connect it affects what it can measure.

---

## System Architecture

```
                               ┌────────────────────────────────────────────────────────┐
                               │                    ISP Edge (Modem/ONT)                │
                               └───────────────────────────┬────────────────────────────┘
                                                           │
                                                           ▼
┌──────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│ NetworkMeasureBox on a Raspberry Pi 4 or Linux PC                                                               │
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
│  │ • /proc/net/dev idle gate (2% of capacity)    │          │ • Standalone HTML dossier with embedded SVGs     │  │
│  │ • Engines: Ookla, Cloudflare, Fast.com, RTR,  │          │ • Raw RFC 4180 CSV telemetry exporter            │  │
│  │ • TCP port throttling check                  │          │ • Automated SMTP dispatch for ISP fault tickets  │  │
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
│  │ • Proactive push alerts (outages & loss >5%) │          │ • Tabs and subtabs in 11 languages, Logout       │  │
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
  * Router with DHCP or static IP WAN. A PPPoE client (with 802.1Q VLAN tagging) redials after a dropped line; it is tested against a simulated ISP only.
  * Local gateway services: `dnsmasq` DHCP server, DNS caching, and iptables/nftables NAT masquerading.
  * Wi-Fi access point (`hostapd`) on the LAN bridge. It adapts to the radio and steps down if `hostapd` rejects a setting. See Tested Status.
* **Mode B (Passive Transparent Inline Bridge)**:
  * Bridges an existing modem/ONT and router at Layer 2. The box itself requests an IP address through DHCP so it can measure, so the upstream connection must offer it one.
  * Measures on the bridge (`br0`). If the box stops, the connection stops too. PPPoE or single-address connections are not handled yet.
* **WAN failover**: With WAN2 configured, Mode A moves the default route to WAN2 after failed connectivity checks.

### 2. Multi-NIC, Multi-WAN & Multi-LAN Architecture
* **Port Role Assignment Matrix**: Interactive WebGUI matrix mapping physical network cards (PCIe, USB, onboard) to:
  * **WAN 1 (Primary)**: Main uplink.
  * **WAN 2 (Secondary)**: Failover backup, or load balancing through a multipath default route, with independent DHCP/static settings. Not tested on real lines.
  * **LAN (br-lan Bridge)**: Any number of physical Ethernet ports automatically grouped into unified Linux network bridge `br-lan` (`192.168.100.1/24`).
  * **DMZ**: In Mode A, the DMZ port gets its own subnet (`192.168.200.0/24`) with DHCP. Its devices reach the internet, but not the LAN, and the box only for DHCP and DNS.
  * **Guest Wi-Fi Client Probe**: Dedicated wireless card for client probe testing.
  * **Storage guard** (`[storage]`, on by default): `nmb-netd` checks the disk every 10 minutes and keeps free a share that depends on its size (15 % up to 2 GB, 10 % up to 16 GB, 5 % above; at least 200 MB, at most 2 GB; `min_free_mb` overrides it). When less is free it deletes, oldest first: rotated logs, diagnostic bundles and crash reports; update backups except the newest; old reports; the system journal down to 32 MB; large active NMB logs; and only then measurements, a day at a time, keeping the last `keep_days` (7) days. Deleted measurements are recorded as an event. `setup.sh` stops when less than 500 MB is free and uses smaller logs on disks under 8 GB.
  * **Measuring over Wi-Fi**: The box can join your own Wi-Fi to measure over it (`[wifi_uplink]`: `ssid`, `password`, `interface`, `hidden`, `enabled`; its own NetworkManager profile `nmb-uplink`, separate from the guest client). `[network] measurement_link` chooses where speed tests run: `auto` (Ethernet when a cable is connected, otherwise Wi-Fi), `ethernet` or `wifi`. With a cable and Wi-Fi both up, the default route stays on Ethernet, and a source rule (table 150) makes tests bound to Wi-Fi really leave over Wi-Fi. Set it in the Web UI under the schedule, or with `nmb-cli run wifi.uplink`. Needs NetworkManager. Each wireless interface can be given its role in Ports & Drivers: 📶 *Guest Wi-Fi client* or 📡 *Main Wi-Fi client (measuring)*; one interface cannot be both, and with `interface = auto` the main client skips the radio of an enabled guest client.
  * **USB tethering** (`[usb_uplink]`, off by default): a phone, mobile hotspot (for example a Netgear Nighthawk) or cellular modem on USB is recognised by its driver (`rndis_host`, `cdc_ncm`, `cdc_ether`, `ipheth`, `qmi_wwan`, `cdc_mbim`) and never taken for the wired line. Turned on, it gets its own NetworkManager profile (`nmb-usb-uplink`) with an address but never the default route, so the box's traffic and the outage probe stay on the cable; `measurement_link = usb` (or a manual test on that interface) measures over it through a source rule (table 152). Results over USB are stored as mobile (`fwa`); tests over USB have their own daily data limit (`daily_limit_mb`, default 1024 MB, 0 = none). Web UI card, `nmb-cli run usb.uplink ...`, in all 11 languages.
  * **Wi-Fi shared on a LAN port** (`[wifi_share]`, off by default): when the box is on Wi-Fi and a wired port has no internet of its own, devices plugged into that port get an address from the box (`address = 192.168.77.1/24` by default, DHCP .100–.200, the Wi-Fi's DNS servers) and reach the internet through the box's Wi-Fi (NAT, its own routing table 151). The box never hands out addresses on a network that has its own DHCP: it sends a DHCP request on the port before it starts, every minute while it runs, and right after a cable is plugged in (with its own DHCP stopped first), and stops if any other server answers or the port gets a default route. The replies are read from a packet socket, so the box's firewall cannot hide them. Web UI card under the schedule, `nmb-cli run wifi.share enabled=true lan_interface=eth0`.
* **LAN Passthrough & Link Aggregation** (standalone probe behind a router, WebGUI: Ports & Drivers):
  * **Passthrough**: selected ports are bridged to the uplink at Layer 2, so devices behind the box stay on the router's subnet.
  * **Link aggregation**: tick two or more wired ports or cards to combine them into `bond0` (802.3ad LACP, balance-rr, balance-xor, balance-tlb, balance-alb, active-backup). Works with or without passthrough.
  * 802.3ad needs LACP on the router or switch; balance-rr and balance-xor need a static LAG there. Except with balance-rr, one TCP connection stays on one link, so the combined speed appears with multi-stream tests.
* **Target Interface Benchmarking**: Speed tests can be pinned to specific network interfaces via CLI (`-i` / `--interface`) or WebGUI dropdown to compare WAN1 vs WAN2 throughput directly.

### 3. Automated Hardware Driver & Firmware Management
* Detects physical controllers (Realtek RTL8111/8168/8125/8126, Intel e1000e/igb/igc/ixgbe, Broadcom, MediaTek MT7921, Qualcomm Atheros, ASIX USB, Aquantia 10G).
* Inspects `dmesg` ring buffer to detect missing non-free kernel firmware blobs.
* Built-in one-click package installer via `nmb-helper install-drivers`, tested on Raspberry Pi OS (`apt`); code paths for `opkg`, `apk`, `pacman` and `dnf` exist but are untested, with real-time WebGUI terminal logging.

### 4. Measurement Engines & Checks
1. **High-Frequency ICMP Probe (`nmb-probe`)**: 500ms continuous sampling to the gateway and public targets (by default `1.1.1.1`, `8.8.8.8`, `9.9.9.9`, `185.222.222.222`), RFC 3550 jitter calculation, p95/p99 latency tracking, and exact outage duration logging.
2. **Ookla Speedtest CLI**: Official Ookla binary runner with automatic server detection or custom server targeting. The server list always comes from Ookla (the servers nearest to the box, refreshed every few minutes or with one click); nothing is built in.
   * **Warning**: Ookla limits how often one box may test, and every few minutes it soon refuses the box ("Limit reached") and blocks it for a while. So scheduled Ookla tests run at most once an hour, however often the schedule runs, and a manual Ookla test runs when asked. If Ookla still refuses, the box pauses Ookla (30 min, doubling up to 4 h, kept across restarts) and stores no other engine\'s result in its place. The Web UI shows the hourly limit and any pause.
   * **Why at most once an hour (`ookla_interval_min`, at least 60):** Ookla allows its free Speedtest CLI only for personal use and limits how often one public IP address may test. When the limit is hit it answers "Limit reached: Too many requests received", and every further attempt, refused ones too, keeps the block going. On the test line the box first ran Ookla every minute for hours without a problem (4 November 2026); after days of frequent tests Ookla blocked the line's address, and the block held through every hourly retry. It was the box's owner who suggested getting a new address: after a restart of the main router (GL.iNet Flint 4) the line got a new public IP, and the very first Ookla test went through at once (934/325 Mbps, 8 November 2026). So the block is on the public IP, not on the box or its settings, and it covers every device behind that address. Scheduled tests are therefore held to at most one an hour; after a refusal the box pauses Ookla (30 min, doubling up to 4 h, kept across restarts) instead of retrying, and stores no other engine's result in its place. NMB does not change the IP address by itself to get around the block. Manual tests are not held back, so use them sparingly; the server list refresh also asks Ookla.
3. **Cloudflare Speed Engine**: Timed 4-stream download and upload against the Cloudflare edge (about 1.2 GB per run at gigabit speed).
4. **Fast.com (Netflix)**: Built in, in pure Python (no Node, Go or browser needed), using Fast.com's own API the way `gesquive/fast-cli` and `sindresorhus/fast-cli` do. Fast.com names up to five Netflix Open Connect servers near the box; the box measures latency to each (the `range/0-0` request Fast.com itself times, plus the TCP handshake), then, over plain HTTP, 16 parallel streams spread over the servers for 15 s each way, leaving out the first 3 s of TCP ramp-up. Plain HTTP because on a Raspberry Pi 4 TLS took 77–88 % of the CPU at 910 Mbps and the result dropped when other services ran at the same time; plain HTTP needs 50–56 %. In isolated runs on the test line every variant reached the line speed (about 910 Mbps), so Fast.com does not hold the box back. The result shows the "stable" speed, as Fast.com does: the mean from the moment the speed settles. Each row also keeps, in `raw_json`: the ISP, ASN, city and country Fast.com sees; every server with its city, country, latency samples and its own share of the download and upload; the speed every half second; the peak and the plain mean; the latency under load in both directions and the bufferbloat grade. It is part of the mixed run every time, like Cloudflare (`fastcom_interval_min = 0`); about 2.2 GB per run at gigabit speed.
5. **RTR-Netztest (RMBT)**: Open-source benchmark from the Austrian regulator RTR.
6. **iPerf3 Client & Managed Server**: Local LAN and public WAN throughput benchmarking across TCP and UDP with parallel threads. Results, the statistics and the CSV name each server (place and provider from the public iPerf3 list; for a server known only by its address, the city, country and ISP from GeoIP), also for older rows that stored only the address.
7. **Port Throttling Check**: Compares TCP throughput on common ports (80, 443, 8080, 8443, 53, SSH 22, SIP 5060 and BitTorrent 6881 by default) against a port 443 baseline. It can show a difference, but cannot prove the ISP caused it.
8. **Traffic Gate**: Monitors `/proc/net/dev` and postpones a test if the box sees traffic above the threshold (2% of capacity by default). In plain `standalone` mode the box only sees its own traffic, so other devices do not count; other traffic only reaches its counters when it passes through the box.
9. **Stop on Network Traffic (experimental, off by default)**: Enabled with `experimental_stop = true` under `[traffic_gate]` or the Web UI switch. Scheduled tests then need a limit of at most 500 kbps, retry every 5 minutes after a deferral, and stop without saving partial results if other traffic appears. Ping keeps running and manual tests are not stopped. A voice call fits under the limit; video and torrents do not. The box reads other devices' traffic from client-side ports (bridge, gateway, or its own access point) or the router's UPnP counters. If neither is available, no scheduled speed tests run. For a full view, wire the box as a bridge between the ISP endpoint and the router, which needs two Ethernet ports (on a Raspberry Pi 4, a USB 3 gigabit adapter as the second). This has not yet been tried on a real bridge.
10. **OONI Probe (optional, off by default)**: Weekly censorship and net-neutrality run, enabled in the Web UI or with `enabled = true` under `[ooni]`. It does not use the Traffic Gate.

**Speed test schedule**: New installs test every hour (`schedule_cron = 0 * * * *`), changeable in the Web UI. The schedule sets how often the box checks; each engine also has its own minimum interval (`ookla_interval_min`, at least 60; `rtr_interval_min` and `cloudflare_interval_min`, 0 = every run; `fastcom_interval_min`, 0 by default) under `[speedtest]` or in the Web UI, so RTR-NetTest can run every minute while Ookla runs hourly. iPerf3 runs on the same schedule with its own `iperf3_interval_min`, against one or more servers (`target_host` and `extra_servers`; by default 4 TCP streams, 10 s, download then upload), alone or in the mixed run, but only when an iPerf3 server is set under `[iperf]` and answers; otherwise it is left out without an empty row. The speed test list shows only real measurements; skipped and failed runs are counted in one line. `nmb-web` starts scheduled tests, so it must be running; upgrades keep the configured schedule.

### 5. Embedded & Low-Memory Optimization (512 MB RAM Support)
Memory-saving profiles for constrained Linux systems. These have only been run on the Raspberry Pi 4, not on routers:
* **`low` profile**: Restricts hot SQLite RAM DB to 48 MB, trims SQLite cache to 2 MB, limits TCP buffers to 8 MB.
* **Native Heap Reclaim**: Proactively invokes `libc.malloc_trim(0)` and Python garbage collection to immediately release unmapped heap memory back to the Linux kernel.
* **`standard` (1-2GB) & `performance` (4GB+) profiles**: Scalable buffer tuning for multi-gigabit workloads.

### 6. Storage Protection & microSD Longevity
* **Hot RAM Database**: Live telemetry runs in tmpfs (`/var/lib/nmb/live/`) using SQLite Write-Ahead Logging (WAL). This keeps most writes away from flash.
* **Atomic Snapshots**: The SQLite Online Backup API copies a consistent snapshot to persistent flash storage (`/var/lib/nmb/persist/nmb.db`) every 15 minutes and upon system shutdown.
* **Filesystem Optimizations**: ext4 with `noatime,commit=600`, and `/tmp`, `/var/tmp` and `/var/log` in RAM, so logs are lost on restart.

### 7. Responsive WebGUI & REST API
* Modern dark-themed router dashboard on **standard HTTP port 80** (with automatic unprivileged fallback to port 8080 for development).
* **Mobile-First Ergonomics**: Sub-navigation bars (`.router-subnav`, `.remote-subnav`, `.adblock-subnav`) are styled as resilient horizontal swipe ribbons (`flex: 0 0 auto`, `nowrap`) with container-relative `scrollTo`, eliminating vertical pill squeezing and letter-wrapping on small smartphone screens (360px–420px).
* Live inline SVG graphs, historical speed records, network device explorer (ARP sweep & MAC vendor lookup), real-time syslog inspector, and one-click diagnostic LLM bundle generation.
* **Translations**: The Web UI, the terminal UI (`nmb-cli`), the results page, the charts and the report (dossier) have the same text keys in 11 languages; some technical terms stay in English, and action names in `nmb-cli` are English. The Telegram bot speaks all 11 too (menus, answers, admin answers, alerts).
  * 🇬🇧 English (EN)
  * 🇭🇺 Hungarian (HU)
  * 🇩🇪 German (DE)
  * 🇺🇦 Ukrainian (UK)
  * 🇫🇷 French (FR)
  * 🇷🇴 Romanian (RO)
  * 🇮🇹 Italian (IT)
  * 🇪🇸 Spanish (ES)
  * 🇵🇹 Portuguese, Portugal (PT)
  * 🇧🇷 Portuguese, Brazil (PT-BR)
  * 🇨🇳 Chinese, Simplified (ZH)
  The six newer languages live in `nmb/web/locales/` and `nmb/report/locales/`, one JSON file each; a missing text is shown in English, never in another language.
* HTTP Basic Authentication with dedicated secure Logout functionality.

### 8. Universal Remote Access, VPN Hub & Tailscale Mesh
* **PiVPN 1-Click Client Generator**:
  * Dual-Protocol VPN Server: **WireGuard** (UDP 51820, high-speed, battery efficient) and **OpenVPN** (UDP 1194, Elliptic Curve `prime256v1`).
  * Dual-Stack Tunneling: Full IPv4 (`10.8.0.0/24`, `10.9.0.0/24`) and direct IPv6 ULA (`fd42:42:42::/64`, `fd42:42:43::/64`).
  * Instant Client Pairing: Enter client name $\to$ automatically generates configuration profile and interactive camera-scannable QR code directly on the WebUI and in Telegram!
  * Peer Management: Real-time connected peer roster with endpoint IPs, latest handshake, RX/TX transfer statistics, and revocation toggles.
* **Tailscale Secure Mesh Remote Access**:
  * **Management-Plane Isolation**: Direct encrypted access to the WebUI dashboard from anywhere in the world without public port forwarding, dynamic DNS, or firewall opening.
  * Completely bypasses Carrier-Grade NAT (CGNAT) and multi-router cascades.
  * Real-time MagicDNS domain, Tailscale IPv4/IPv6 status, and one-click Connect / Disconnect controls directly from the WebUI.
* **DynDNS & Forward Proxy**:
  * Integrated DuckDNS dynamic DNS updater.
  * Optional built-in HTTP CONNECT forward proxy with required authentication.

### 9. Embedded DNS Ad-Blocker & Privacy Shield (Pi-hole Alternative)
* **High-Performance In-Memory Sinkhole**:
  * Blocks tracking, intrusive telemetry, malware, and advertisement domains before they ever reach customer LAN devices.
  * Pre-configured blocklist subscriptions (StevenBlack unified hosts, AdAway, etc.) with automatic background Gravity updates.
* **Custom Control & Live Audit**:
  * Real-time DNS query statistics: Total queries today, blocked queries, sinkhole percentage, and active Gravity domain count.
  * Custom domain blacklist, whitelist, and wildcard RegEx filtering (`/api/adblock/regex/add`).
  * DNS query log inspection in the WebUI.

### 10. Advanced Forensic Diagnostics & Root-Cause Telemetry
* **Wi-Fi RF & PHY Telemetry (read through `iw`)**:
  * RSSI signal strength in dBm, where the driver reports it.
  * RX/TX PHY bitrates, MCS (Modulation and Coding Scheme) index, channel width (20/40/80/160 MHz), and hardware retry/fail counters (`tx_retries`, `tx_failed`).
* **DNS Hijacking & Comparative Resolver Matrix**:
  * Concurrently audits 4 independent resolver tiers: Local Gateway/DHCP, Cloudflare (`1.1.1.1`), Google (`8.8.8.8`), and Quad9 (`9.9.9.9`).
  * Verifies DNSSEC validation (`ad` Authenticated Data bit) and compares cached vs uncached response times.
  * Tests for DNS interception by asking an address where no DNS server exists; any answer means port 53 is intercepted.
* **RFC 5389 STUN Client & Carrier-Grade NAT (CGNAT) Detection**:
  * Classifies upstream topology into:
    * **Direct Public IP**: Local WAN IP matches external STUN reflexive IP.
    * **Carrier-Grade NAT (ISP CGNAT)**: Upstream WAN IP falls within RFC 6598 (`100.64.0.0/10`).
    * **Double NAT**: Local WAN IP is an RFC 1918 private address (`192.168.x.x` or `10.x.x.x`).
    * **NAT mapping**: Endpoint-independent (same public port towards two STUN servers) or symmetric. Full cone and restricted types are not distinguished.
* **CPU Interrupt (IRQ/SoftIRQ) & NIC Offload Telemetry**:
  * Tracks per-core interrupt and SoftIRQ distribution to catch CPU0 saturation bottlenecks (the classic Gigabit bottleneck on Raspberry Pi and MIPS routers).
  * Inspects Receive Packet Steering (RPS/XPS) bitmasks (`/sys/class/net/<iface>/queues/rx-*/rps_cpus`) and NIC hardware offloads (checksumming, TSO, GRO via `ethtool`).
* **Micro-Outage & Loss Pattern Correlation**:
  * Continuously classifies dropped packets: isolates micro-burst jitter from catastrophic macro-outages ($\ge 5\text{s}$).
  * Compares loss at the gateway and on public targets, to suggest whether a problem is local or further upstream. This is an indication, not proof.
* **Storage I/O & Flash Filesystem Health**:
  * `%iowait` CPU tracking to detect failing or saturated microSD / flash storage.
  * Free filesystem capacity tracking.
  * Kernel `dmesg`/`kmsg` ring-buffer traps catching hardware I/O and ext4/squashfs corruptions.
* **Sanitized Configuration & PII Masking**:
  * Built-in redactor protecting customer privacy: automatically masks bot tokens, chat IDs, Wi-Fi PSKs, ISP account numbers, and circuit IDs before generating dossiers or exporting diagnostic snapshots.

### 11. Multilingual Telegram Chatbot with Interactive Touch Menus
* Fully autonomous chatbot (`nmb-telegram`) providing mobile management without browser access:
  * **Interactive Touch Menus**: Inline keyboards for 1-click status audits, instant ping matrix, on-demand speed tests, and VPN QR generation.
  * **Languages**: Switches between **English**, **Hungarian**, **German**, **French** and **Ukrainian**.
  * **Instant SLA Dossier Delivery**: Sends complete `.html` reports directly into the chat for forwarding to ISP technicians.
  * **Proactive Push Alerts**: Alerts on outages, and when packet loss, latency or jitter stays above its threshold for 5 minutes.

### 12. SLA Dossier & Pure SVG Charts
* **Neutral International Branding**:
  * Completely neutral title: *"Broadband Quality & ISP SLA Performance Dossier"* / *"Szélessávú Hálózati Minőség & Szolgáltatói SLA Vizsgálati Dosszié"*.
  * Makes no official or regulatory claim. The SLA result is NMB's own evaluation against fixed thresholds, not a decision by an authority or an ISP.
  * **Accurate Contractual Speed Handling**: Guaranteed speed cards displaying `0 Mb/s` or unspecified parameters are automatically suppressed to avoid deceptive compliance reporting; explicit disclaimers guide SLA verification.
  * **Prominent IP & ISP Attribution**: Every measurement sample and telemetry table prominently highlights the detected client IPv4/IPv6 addresses alongside the verified ISP provider identity.
* **Pure Mathematical SVG Vector Engine**:
  * Zero external charting dependencies: emits responsive `<svg viewBox="0 0 800 380">` with cubic bezier curves, dual y-axes (Mbps & ms), SLA threshold baselines, and touch dot overlays.
  * Exportable directly in 11 languages via `/dossier?lang=...` or Telegram `/report`.

### 13. Real-Time Task Manager (Embedded htop Engine)
* Direct `/proc` virtual filesystem reader replacing heavy `ps` process spawning.
* Real-time process monitoring: PID, User, Priority, Nice, VIRT, RES, CPU%, MEM%, runtime, and command arguments.
* Interactive filtering: System Services vs User Apps vs NMB Daemons.
* In-line signal management: SIGTERM or SIGKILL from the WebUI, limited to processes the `nmb` user may signal.

### 14. Autonomous Self-Healing & Safety Rollback Watchdog (`nmb-heal`)
* Automated background health audits of binaries, database, permissions and connectivity, with repairs.
* **Update from GitHub in a few clicks**: "Apply Stable Update" in the Web UI, `nmb-cli update --apply --yes` or `nmb-heal update --apply`. On the standard install (`/opt/nmb`, no Git data) the box downloads the newest commit of this repository, runs its tests (nothing changes if they fail), backs up settings and measurements, installs it with `setup.sh` (which keeps settings and measurements and replaces the program files) and puts the previous version back if the install or the web server check fails. The Web UI shows each step; the log is `/var/log/nmb/update.log`. A Git checkout updates with `git pull` and rolls back to the previous commit.

### 15. Central Measurement Collector (`nmb-collector`)
An ISP or a specialist runs `nmb-collector` on their own server; boxes whose owner agrees send their results to it. Everything is off until the box owner turns it on (Web UI → System → Central measurement collector, or `[collector]` in `nmb.conf`), with three separate consents:

| Setting | What the collector gets |
|---|---|
| `enabled` | Speed tests (failed ones too), an hourly ping summary per target, the box's unique ID, its name, the case number, the ISP, the customer number and the subscribed speeds |
| `share_diagnostics` | Also the box's events and, hourly, the full network diagnostics: interfaces, routes, MTU, DNS, NAT, Wi-Fi, traceroute, the devices on the LAN and the settings with every secret masked |
| `allow_remote_control` | The collector may start a speed test (engine and Ookla server), ask for fresh diagnostics or an upload. Nothing else: no shell commands, no setting changes. The box asks the collector for work every minute, so nothing connects into the owner's network |

Every box has a permanent random ID (such as `nmb-k7q2-x9mf-3hwd`, shown in the Web UI), since the box name is `nmb-01` on every box unless changed. In the collector's password-protected web pages a box is found by this ID, its name, its current or an earlier case number, the customer number or the ISP; its page shows averages against the subscribed speeds, results per engine, ping per target, events, the diagnostics history, the remote commands and a CSV download.

Setting up a collector (standard library only, Python 3.10 or newer):
```bash
git clone https://github.com/4r04x4t/NetworkMeasureBox.git /opt/nmb-collector
useradd --system nmb-collector
/opt/nmb-collector/bin/nmb-collector --data /var/lib/nmb-collector set-password
/opt/nmb-collector/bin/nmb-collector --data /var/lib/nmb-collector token-add support-team   # give this token to the box owner
chown -R nmb-collector /var/lib/nmb-collector
cp /opt/nmb-collector/os/nmb-collector.service /etc/systemd/system/ && systemctl enable --now nmb-collector
```
It listens on port 8600. Put it behind an HTTPS reverse proxy or start it with `--cert` and `--key`, since tokens and the admin password travel with every request.

### 16. Planned De-Pythonization & Router Porting
> **Status: planned only.** NMB is developed and run on the Raspberry Pi 4. No router software or firmware exists yet; the figures below are design targets, not measurements.

The plan for running NetworkMeasureBox on commercial routers with as little as **4MB Flash and 32MB RAM**:
* **Generic first**: the native code is written platform- and architecture-independent, and built, tested and proven on a PC (x86-64) and the Raspberry Pi 4 (ARM64) before any router work; router targets are added later as backends of the same code. See *Generic First* in `DEPYTHONIZATION_ROADMAP.md`.
* **Quality bar**: the native build must run at least as flawlessly as the Python version, fix the bugs found on the way instead of carrying them over, and be measurably better (CPU, memory, start-up, logging, safe updates); a component replaces its Python counterpart only with that evidence written down. See *Quality Bar* in `DEPYTHONIZATION_ROADMAP.md`.
* **Unified Single Binary (`nmbd`)**: Written in **Go 1.23+** (Tier 1) and **C11 with Musl libc** (Tier 2 & 3), completely eliminating Python 3, pip, and all runtime packages.
* **Target Hardware Porting Specifications & WikiDevi Profiles**:
  * **[ASUS RT-AXE7800](https://wikidevi.wi-cat.ru/ASUS_RT-AXE7800)**:
    * Broadcom BCM6756 Quad-Core ARM Cortex-A7 @ 1.7 GHz, 512 MB DDR4 RAM, 256 MB NAND Flash, 1x 2.5GbE + 1x 1GbE WAN/LAN + 3x 1GbE LAN, Tri-Band Wi-Fi 6E, USB 3.2 Gen 1.
    * OS: Asuswrt / Asuswrt-Merlin (GNUton fork) or upstream OpenWrt `bcm4908`.
    * Native daemon: Go 1.23+ single binary or C11; 2.5 Gbps line-rate testing, multi-threaded CAKE SQM, Flow Cache bypass, in-process `tsnet` Tailscale.
  * **[ASUS RT-N12+](https://wikidevi.wi-cat.ru/ASUS_RT-N12_series)**:
    * MediaTek MT7620N ver:2 eco:6 MIPS24KEc @ 580 MHz (`ramips/mt7620`), 32 MB DDR SDRAM, 8 MB SPI Flash, Fast Ethernet (100 Mbps).
    * OS: OpenWrt `ramips/mt7620`.
    * Native daemon: Monolithic C11 with musl libc (<850 KB, ~2.8 MB RAM RSS), 100 Mbps line-rate testing at <14% CPU.
  * **[TP-Link TL-WR740N v4.x / v4.23](https://wikidevi.wi-cat.ru/TP-LINK_TL-WR740N_v4.x)**:
    * Qualcomm Atheros AR9331 MIPS 24Kc @ 400 MHz (`ath79/generic` / `ar71xx`), 32 MB DDR SDRAM, **4 MB SPI Flash**, Fast Ethernet (100 Mbps).
    * OS: Stripped OpenWrt `ath79/generic` (no LuCI, minimal kernel).
    * Native daemon: Micro-C11 with `-Os`, stripped, UPX-LZMA compressed (**178 KB binary**), 1.4 MB RAM RSS, 100% RAM-only circular ring-buffer (`tmpfs`) with zero flash writes.
  * **[TP-Link TL-WR1043ND v1.x](https://wikidevi.wi-cat.ru/TP-LINK_TL-WR1043ND_v1.x)**:
    * Atheros AR9132 @ 400 MHz, 32 MiB RAM, 8 MiB Flash, Realtek RTL8366RB, 1x 1GbE WAN + 4x 1GbE LAN.
  * **[TP-Link Archer C6 v2.x](https://wikidevi.wi-cat.ru/TP-LINK_Archer_C6_v2.x)**:
    * Qualcomm Atheros QCA9563 @ 775 MHz, 128 MiB RAM, 8 MiB Flash, QCA8337N, 1x 1GbE WAN + 4x 1GbE LAN, AC1200.
  * **[ASUS RT-AC57U v1](https://wikidevi.wi-cat.ru/ASUS_RT-AC57U)**:
    * MediaTek MT7621AT, 2 cores @ 880 MHz, 128 MiB RAM, 16 MiB SPI flash, switch in the SoC, 1x 1GbE WAN + 4x 1GbE LAN, 2.4 GHz MT7603EN (b/g/n 2x2) + 5 GHz MT7612EN (a/n/ac 2x2), AC1200, 1x USB 2.0.
    * v2 uses Qualcomm chips and is different hardware; this target covers v1 only. WikiDevi lists Padavan as work in progress; OpenWrt `ramips/mt7621` is the likely base, to be confirmed.
* **Planned device families**: MikroTik devices (native `nmbd` as a container on RouterOS v7, or on OpenWrt instead of RouterOS; for example hEX, hAP ac², RB5009) and routers with MediaTek SoCs (MT7620/MT7628, MT7621, MT7622, Filogic MT7981B, MT7986A, MT7988A), one port per chip. Figures to verify; see section 1.3 of the porting plan.
* **Development access and safe fixes (required for every port)**: every device keeps an owner-enabled maintenance mode with full root access for developers and developer LLM agents (SSH keys only, every session in an audit log, switched off after a set time), detailed structured logs that do not wear out flash, crash evidence that survives a reboot, and fixes applied next to the running version with automatic rollback, so a fix in the field is unlikely to brick the device. See section 7D of the porting plan.
* **NMB's own Linux distribution (planned)**: a minimal image for the Raspberry Pi 4 and later x86-64, built on the de-Pythonized `nmbd`: read-only system, a separate data partition, A/B updates with automatic rollback. The base (Debian, OpenWrt, Alpine or another network-oriented distribution) is chosen by a comparison in the porting plan. The distribution is NMB's own, the Linux kernel is not: it uses the stock kernel of its base (the Raspberry Pi kernel on the Pi 4, the base distribution's LTS kernel on x86-64), unchanged. No device runs Python. See section 6A of `DEPYTHONIZATION_ROADMAP.md`.
* **Key Native Subsystems (Zero Python)**:
  * **Memory-Bounded DNS Sinkhole / AdBlock**: 512 KB Counting Bloom Filter (MurmurHash3, 0.1% FPR) and Trie running in <640 KB RAM on 32MB routers.
  * **Zero-Dependency Speedtest Socket Sinks**: In-process TCP/TLS client streaming directly to Ookla, Cloudflare Edge, Fast.com (Netflix Open Connect) and RTR-NetTest endpoints using `splice()`/`recv()` zero-copy buffers without external binaries.
  * **Autonomous Self-Healing Engine (`nmb_heal`)**: Multi-tier watchdog (service restart, link bounce, driver offload toggling, configuration rollback).
  * **Dynamic DNS Client**: Direct TLS 1.3 Netlink-aware updater for `duckdns` and `dynv6` (<60 KB RAM).
* Full technical blueprints available in:
  * 📄 **[`docs/ROUTER_PORTING_AND_DEPYTHONIZATION_PLAN.md`](docs/ROUTER_PORTING_AND_DEPYTHONIZATION_PLAN.md)**
  * 📄 **[`docs/DEPYTHONIZATION_ROADMAP.md`](docs/DEPYTHONIZATION_ROADMAP.md)**

---

## Tested Status

What has actually been run, so you can judge what to rely on. The full record (where, what, how, with what result): [docs/TESTING.md](docs/TESTING.md).

**Test line:** NMB is developed and tested on one home fibre (FTTH) connection with a 1000/300 Mbps plan, from a Hungarian ISP, with the box behind the home router, a GL.iNet Flint 4. Every speed, CPU and timing figure in this README and in the testing record comes from that line and a Raspberry Pi 4. Much slower lines (DSL, mobile) and faster ones (2.5 or 10 Gbps) have not been tested; above about 1 Gbps the Pi 4's single gigabit port and its CPU become the limit before the line does.

| Area | Status |
|---|---|
| Raspberry Pi 4, Debian 13, `standalone` mode | In daily use |
| Clean install, x86-64 | Tested in a simulated environment on a PC with these operating systems: Debian 13, Debian 12, Ubuntu 26.04 LTS, Ubuntu 24.04 LTS, Ubuntu 22.04 LTS, Fedora 45, AlmaLinux 10 and Rocky Linux 10 (for RHEL 10) and Alpine 3.22 / 3.20. Install, services, Web UI, a real speed test, reinstall and (on Alpine) reboot |
| `mode_a` router and `mode_b` bridge | Tested in virtual machines, with DHCP, NAT, DMZ isolation and client traffic. Not on Raspberry Pi hardware |
| Wi-Fi access point | WPA2 on 2.4 and 5 GHz and WPA3 on 2.4 GHz, with simulated radios and a real client. Not on real Wi-Fi hardware |
| Wi-Fi 7, 6 GHz, 160/320 MHz | Not verified. The hostapd in Debian 13 rejected the Wi-Fi 7 settings, so NMB steps down to an older standard |
| PPPoE | Dial-in and redial after a dropped line tested against a simulated ISP. Not on a real line |
| VLAN, multi-WAN load balancing, link aggregation | Code exists, not tested on a real line |
| Other distributions (such as Raspberry Pi OS, Arch), 32-bit systems | Not tested; setup supports Debian-based systems, Fedora, RHEL and its rebuilds, and Alpine |
| Devices with 512 MB RAM | Tested in a VM with 512 MB: 25 minutes of tests every minute, no out-of-memory kill, no swap used |
| Reinstall and upgrade with `setup.sh` | Tested on Ubuntu 26.04, Alpine 3.22 and Rocky Linux 10: settings and measurements kept, removed files cleaned up, services back after a reboot |
| Update from GitHub (no Git install) | Unit tests only (download, safe unpacking, test gate, status). Not yet run against the real repository |
| Central collector and remote control | Tested with a real collector and box client on one machine: upload, search by case number, CSV, diagnostics only with consent, remote speed test, refusal without consent, cross-site requests refused. Not yet run between two machines |
| WireGuard and OpenVPN server, HTTPS proxy | Tested in a VM with a real client: tunnel, internet and Web UI through the tunnel |
| Guest Wi-Fi client | Tested in a VM against a simulated network. Needs NetworkManager |
| Self-update with rollback | Tested from a Git checkout in a VM: a good update is applied, a broken one rolled back |
| DuckDNS | Only tested with a wrong token (rejected) |
| Telegram, SMTP, Tailscale, OONI | Not tested with real accounts |

NMB is a personal project, not a certified measuring instrument. Its results can support a complaint, but they do not replace a regulator's or ISP's own measurement.

---

## Quickstart / Automated Installation

Run the installer. Tested in a simulated environment on a PC with Debian 13, Debian 12, Ubuntu 26.04 LTS, Ubuntu 24.04 LTS, Ubuntu 22.04 LTS, Fedora 45, AlmaLinux 10 and Rocky Linux 10 (for RHEL 10) and Alpine 3.22 / 3.20 (x86-64), and on a Raspberry Pi 4 with Debian 13 (see Tested Status):

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
* **Default credentials**: `admin` / `admin` unless installed with `RANDOM_ADMIN_PASSWORD=1` (saved to `/var/lib/nmb/credentials.txt`; see Security Model for the boot partition copy). Change immediately in the Settings tab.

---

## Command Line Utilities

| Binary | Description | Key Commands |
|---|---|---|
| `nmb-netd` | Network daemon (Router / Bridge / Multi-WAN) | `nmb-netd --status`<br>`nmb-netd --switch auto\|standalone\|mode_a\|mode_b` |
| `nmb-probe` | Continuous latency/jitter ICMP engine | `nmb-probe --verbose` |
| `nmb-speed` | Speedtest & net-neutrality runner | `nmb-speed --trigger manual`<br>`nmb-speed --engine ookla\|cloudflare\|fastcom\|rtr\|iperf3\|all`<br>`nmb-speed --interface eth0` |
| `nmb-ooni` | Optional OONI Probe add-on | `nmb-ooni status`<br>`nmb-ooni run websites` |
| `nmb-report` | HTML dossier & CSV generator | `nmb-report --window 24h --html dossier.html`<br>`nmb-report --json-summary`<br>`nmb-report --send-email` |
| `nmb-adblock` | High-performance DNS sinkhole | `nmb-adblock status`<br>`nmb-adblock update`<br>`nmb-adblock -b domain.com` |
| `nmb-heal` | Self-healing watchdog & safety rollback | `nmb-heal audit`<br>`nmb-heal status`<br>`nmb-heal fix` |
| `nmb-driver` | Hardware driver & firmware autodiscovery | `nmb-driver scan`<br>`nmb-driver missing`<br>`sudo nmb-driver install` |
| `nmb-telegram` | Management Telegram Bot daemon | `nmb-telegram` |
| `nmb-cli` | WebGUI menus in the terminal (SSH, mouse, hotkeys) and JSON commands | `nmb-cli`<br>`nmb-cli menu`<br>`nmb-cli show tab-home`<br>`nmb-cli run speed.run engine=cloudflare`<br>`nmb-cli run speed.run engine=fastcom`<br>`nmb-cli logs dev -n 50 --level warning`<br>`nmb-cli latest` / `nmb-cli latest ookla`<br>`nmb-cli update` / `nmb-cli update --apply --yes`<br>`nmb-cli run collector.send` |
| `nmb-collector` | Central collector for an ISP or a specialist (runs on their server, not on the box) | `nmb-collector set-password`<br>`nmb-collector token-add <name>`<br>`nmb-collector serve --port 8600` |
| `nmb-web` | Embedded management web UI & REST API | `nmb-web` (port 80 / dev 8080) |
| `nmb-helper` | Privileged helper utility (drivers, routing) | `sudo nmb-helper install-drivers all`<br>`sudo nmb-helper tune` |

---

## Interactive Telegram Bot Commands

When `nmb-telegram` is configured, you can manage the entire appliance directly from Telegram with interactive touch menus:

| Command | Description |
|---|---|
| `/menu` | Opens the main interactive Touch Menu (Inline Keyboards) |
| `/status` | Real-time appliance status: uptime, WAN mode, public IP, ISP name, CPU/RAM load |
| `/ping` | Instant latency, jitter, and packet loss matrix to the reference targets |
| `/test [engine]` | Runs an on-demand speedtest (`ookla`, `cloudflare`, `fastcom`, `rtr`, `iperf`) with bufferbloat rating |
| `/report [window]` | Generates and sends the SLA Dossier (`.html`) directly into the chat |
| `/ai` | Exports the sanitized Markdown diagnostic snapshot for external LLM analysis |
| `/mode [auto\|a\|b]`| Views or switches operational mode (Active Router vs Passive Bridge) |
| `/vpn` | PiVPN Hub status: active WireGuard & OpenVPN tunnels, connected client counts |
| `/vpn clients` | Displays connected peer roster with handshake times, endpoints, and RX/TX traffic |
| `/vpn qr <name>` | Generates and dispatches a camera-scannable QR code PNG for instant device pairing |
| `/vpn conf <name>`| Dispatches the downloadable `.conf` profile for WireGuard or OpenVPN |
| `/vpn add <name>` | Creates a new VPN client profile and returns the QR code |
| `/adblock` | DNS Sinkhole status: total queries today, blocked queries, blocklist domain count |
| `/adblock on\|off` | Enables or disables the DNS Ad-Blocker sinkhole |
| `/sla` | Explains what the SLA result means |
| `/purge [category] confirm` | Shows or deletes stored data (settings, passwords and VPN keys are kept) |
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

# View scheduled speed test logs (started by nmb-web)
sudo journalctl -u nmb-web -f
```

---

## Security Model

* **Web server user**: `nmb-web` runs as the `nmb` user with only the network capabilities it needs. Polkit lets it manage its own services and reboot; `nmb-helper` handles other privileged tasks. As a result, the CLI Terminal and the task manager cannot act as root. On polkit 0.105 (Ubuntu 22.04) the rule cannot name units, so there `nmb` may manage any systemd service.
* **Public addresses**: `nmb-guard` blocks ports 80, 53 and 5201 from public IPv4 and IPv6 addresses. Local networks, VPN and Tailscale still work, and the box's own outgoing tests are not affected. It needs systemd and `nftables`, so it is not installed on Alpine.
* **Boot partition**: the copy at `/boot/firmware/nmb.conf` shows `__KEEP_CURRENT__` instead of passwords and tokens. Leave the mark to keep a value, or type a new value to change it. `nmb_credentials.txt` is only kept there while the password is the default or was generated during install.
* **Destructive actions**: factory reset needs `--yes` in the CLI and `RESET` in the API. Data and log purges need `PURGE`.
* **Downloads**: the Ookla archive is installed only if its SHA-256 matches.
* **Results without password** (optional, off by default): with `public_results = true` in `[web]` (Settings → admin credentials), devices on the local network or VPN can open `/results` and download the report and CSV files without logging in, for example when the box is hosted by someone else who sends the results to a specialist. Only these read-only pages open; settings, tests and the diagnostic bundle still need the password, and requests from public addresses always do.
* **Central collector** (optional, off by default): sends only after the owner turns it on, and the full diagnostics and remote control need their own consent each. Remote control is a fixed list (speed test, diagnostics, upload); the box asks the collector for work, so no port is opened. The collector stores tokens and its admin password only as hashes, refuses admin forms from other sites, and its token is masked in the boot partition copy.
* **Tor**: the OONI package installs Tor, but setup disables the service because NMB does not use it.
* **Not encrypted**: the Web UI uses HTTP by default, so use it only on a trusted network or through a VPN.

---

## Changelog

Changes are listed in [CHANGELOG.md](CHANGELOG.md).

---

## License

This project is licensed under the **MIT License** — free for personal, community, and commercial use.
