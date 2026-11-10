# 🌐 NetworkMeasureBox (NMB) — Router Porting & 100% De-Pythonization Specification
## Native Systems Engineering Plan for ASUS RT-AXE7800, ASUS RT-N12+ (MT7620N), TP-Link TL-WR740N (v4.23), TP-Link TL-WR1043ND v1, TP-Link Archer C6 v2.0 and ASUS RT-AC57U v1

> **Status: PLANNED, NOT IMPLEMENTED.** NMB is currently developed and run only on the Raspberry Pi 4 (Python). No router software or firmware exists yet. All binary sizes, memory figures, CPU loads and throughput values in this document are design targets, not measurements.

---

## 1. Executive Summary & Hardware Target Matrix

**Order of work (owner, 2026-11-10):** first the generic x86-64 and ARM images and the complete native program (`DEPYTHONIZATION_ROADMAP.md`, *Order of Work*, step 1); the first router is then the **TP-Link TL-WR1043ND v1** (section 1.2), whose firmware is unpacked and analysed while it is being programmed; the other targets of this plan follow only after that, in an order the owner sets then. Every target uses the optimised Web UI of `DEPYTHONIZATION_ROADMAP.md` section 4.4A, with its router size budget (the whole UI at most 150 KB compressed). Everything in this plan is planned; no router port exists yet.

This document is the architectural plan for porting **NetworkMeasureBox (NMB)** directly onto commercial router hardware with **100% de-pythonization** (zero Python runtime, zero external Python libraries, zero interpreted dependencies).

The system is planned to be re-engineered as a **native, single-binary appliance (`nmbd`)** written in **Go (Tier 1)** and **C11 with Musl libc (Tier 2 & 3)**, targeting three distinct hardware tiers based on official WikiDevi / OpenWrt hardware profiles:

```mermaid
graph TD
    subgraph Router1["Tier 1: High-End Flagship (ARM64 / ARMv8)"]
        R1_HW["ASUS RT-AXE7800 (FCC ID: MSQ-RTAXE5H00)<br/>Broadcom BCM6756 Quad-Core ARM @ 1.7 GHz<br/>512 MB DDR4 RAM | 256 MB NAND Flash<br/>1x 2.5GbE + 4x 1GbE | Tri-Band Wi-Fi 6E (AXE7800)"]
        R1_ARCH["Language: Go 1.23+ / C11 Monolith<br/>OS: Asuswrt / Asuswrt-Merlin (GNUton) / OpenWrt<br/>Storage: RAM tmpfs + NAND Flash Persistence<br/>Throughput: 2.5 Gbps Line-Rate Saturation"]
    end

    subgraph Router2["Tier 2: Low-Budget SOHO (MIPSle)"]
        R2_HW["ASUS RT-N12+ (FCC ID: MSQ-RT1901)<br/>MediaTek MT7620N ver:2 eco:6 MIPS24KEc @ 580 MHz<br/>32 MB DDR SDRAM | 8 MB SPI NOR Flash<br/>1x 100M WAN + 4x 100M LAN | Wi-Fi 4 300Mbps 2T2R"]
        R2_ARCH["Language: Pure C11 (musl-libc) Monolith<br/>OS: OpenWrt 23.05 (Target: ramips/mt7620)<br/>Storage: RAM tmpfs + SPI Flash (/overlay)<br/>Throughput: 100 Mbps Line-Rate (<14% CPU)"]
    end

    subgraph Router3["Tier 3: Extreme Constraint Legacy (MIPSbe)"]
        R3_HW["TP-Link TL-WR740N v4.x / v4.23 (FCC ID: TE7WR741NDV4)<br/>Qualcomm Atheros AR9331 MIPS 24Kc @ 400 MHz<br/>32 MB DDR SDRAM | 4 MiB (4 MB) SPI NOR Flash<br/>1x 100M WAN + 4x 100M LAN | Wi-Fi 4 150Mbps 1T1R"]
        R3_ARCH["Language: Micro-C11 (musl, -Os, UPX-LZMA)<br/>OS: Minimal Stripped OpenWrt (Target: ath79/generic)<br/>Storage: 100% RAM-only Circular Ring Buffer<br/>Throughput: 100 Mbps Line-Rate (<22% CPU)"]
    end

    R1_HW --> R1_ARCH
    R2_HW --> R2_ARCH
    R3_HW --> R3_ARCH
```

### 1.1 Hardware Specifications & Constraint Comparison (WikiDevi Verified)

| Metric / Parameter | Tier 1: ASUS RT-AXE7800 | Tier 2: ASUS RT-N12+ | Tier 3: TP-Link TL-WR740N (v4.23) |
| :--- | :--- | :--- | :--- |
| **WikiDevi Reference** | [ASUS RT-AXE7800](https://wikidevi.wi-cat.ru/ASUS_RT-AXE7800) | [ASUS RT-N12 series](https://wikidevi.wi-cat.ru/ASUS_RT-N12_series) | [TP-LINK TL-WR740N v4.x](https://wikidevi.wi-cat.ru/TP-LINK_TL-WR740N_v4.x) |
| **FCC ID** | `MSQ-RTAXE5H00` | `MSQ-RT1901` | `TE7WR741NDV4` |
| **SoC / Chipset** | **Broadcom BCM6756** | **MediaTek MT7620N (ver:2 eco:6)** | **Qualcomm Atheros AR9331** |
| **Switch Chip** | Broadcom BCM53134O | MediaTek MT7620N Integrated | Qualcomm Atheros AR9331 Integrated |
| **CPU Architecture** | ARM Cortex-A7 / ARMv8 (64-bit capable) | MIPS 24KEc (mipsel, 32-bit little-endian) | MIPS 24Kc (mips, 32-bit big-endian) |
| **CPU Cores & Clock** | **4 Cores @ 1.7 GHz** | **1 Core @ 580 MHz** | **1 Core @ 400 MHz** |
| **Hardware FPU** | Hardware IEEE 754 FPU & NEON SIMD | No (Soft-Float emulation: `-msoft-float`) | No (Soft-Float emulation: `-msoft-float`) |
| **System RAM** | **512 MB DDR4 RAM** | **32 MB DDR SDRAM** | **32 MB DDR SDRAM** |
| **Available RAM (Free)** | **~380 MB – 420 MB free** after boot | **~12 MB – 14 MB free** after OpenWrt boot | **~8 MB – 10 MB free** after minimal boot |
| **Flash Storage** | **256 MB NAND Flash** (Macronix) | **8 MB SPI NOR Flash** (Winbond W25Q64) | **4 MiB (4 MB) SPI Flash** (Winbond W25Q32) |
| **Available Flash for NMB** | > 100 MB writable (`/jffs`) | ~2.1 MB on SquashFS overlay | **< 650 KB** (Compressed!) |
| **Wired Network (WAN/LAN)** | **1x 2.5GbE (WAN/LAN) + 1x 1GbE (WAN/LAN) + 3x 1GbE (LAN)** | 1x 100M WAN + 4x 100M LAN | 1x 100M WAN + 4x 100M LAN |
| **USB Expansion** | 1x USB 3.0 / USB 3.2 Gen 1 | None | None |
| **Wireless (Wi-Fi)** | Tri-Band Wi-Fi 6E (AXE7800: 2.4G 574M + 5G 4804M + 6G 2402M) | Single-Band Wi-Fi 4 (2.4 GHz 2T2R 300 Mbps) | Single-Band Wi-Fi 4 (2.4 GHz 1T1R 150 Mbps) |
| **Target Platform / OS** | Asuswrt / Asuswrt-Merlin (GNUton) / OpenWrt `bcm4908` | OpenWrt `ramips/mt7620` (profile: `asus_rt-n12p`) | Stripped OpenWrt `ath79/generic` (`tplink_tl-wr740n-v4`) |
| **De-Pythonized Engine** | **Go 1.23+ Static Binary** or **C11** | **C11 Monolith (`musl-libc`)** | **Micro-C11 (`musl`, `-Os`, UPX LZMA)** |
| **Executable Binary Size** | ~12 MB (Go) or ~1.5 MB (C11) | ~850 KB (C11) / ~320 KB (UPX) | **< 380 KB (C11) / ~178 KB (UPX)** |
| **Active Memory Envelope** | 18 MB – 24 MB RSS | 2.5 MB – 3.8 MB RSS | **1.2 MB – 1.8 MB RSS** |
| **Primary Data Storage** | SQLite WAL (RAM) + Flash Sync | In-Memory SQLite or Flat Ring Buffer | **Zero Flash Writes**: RAM-only Ring Buffer |

---

### 1.2 Additional Planned Targets

| Metric / Parameter | TP-Link TL-WR1043ND v1.x | TP-Link Archer C6 v2.x (EU) | ASUS RT-AC57U v1 |
| :--- | :--- | :--- | :--- |
| **WikiDevi Reference** | [TP-LINK TL-WR1043ND v1.x](https://wikidevi.wi-cat.ru/TP-LINK_TL-WR1043ND_v1.x) | [TP-LINK Archer C6 v2.x](https://wikidevi.wi-cat.ru/TP-LINK_Archer_C6_v2.x) | [ASUS RT-AC57U](https://wikidevi.wi-cat.ru/ASUS_RT-AC57U) |
| **FCC ID** | `TE7WR1043NX` | `TE7A6` | none listed (EEC/RU0000040239 in the page body) |
| **SoC** | Atheros AR9132 @ 400 MHz | Qualcomm Atheros QCA9563 @ 775 MHz | MediaTek MT7621AT, 2 cores @ 880 MHz |
| **RAM** | 32 MiB | 128 MiB DDR2 | 128 MiB (Winbond W631GG6KB-15) |
| **Flash** | 8 MiB | 8 MiB SPI | 16 MiB (Spansion S25FL128SAIF00) |
| **Switch Chip** | Realtek RTL8366RB | Qualcomm Atheros QCA8337N | in the MT7621AT |
| **Wired Network** | 1x 1GbE WAN + 4x 1GbE LAN | 1x 1GbE WAN + 4x 1GbE LAN | 1x 1GbE WAN + 4x 1GbE LAN |
| **Wi-Fi** | 802.11b/g/n, AR9132 + AR9103 (3x3:2) | 2.4 GHz b/g/n (QCA9563), 5 GHz a/n/ac (QCA9886), AC1200 | 2.4 GHz b/g/n MT7603EN (2x2:2), 5 GHz a/n/ac MT7612EN (2x2:2), AC1200 |
| **Other** | | | 1x USB 2.0, serial header J2, 12 V 2 A |
| **Firmware Basis** | OpenWrt (listed as supported; target to confirm) | OpenWrt `ath79` (EU v2 support listed) | WikiDevi lists Padavan (work in progress); OpenWrt `ramips/mt7621` to confirm |
| **Planned Implementation** | C11 / musl, same constraints as the 32 MiB Tier 2 target | C11 / musl; more RAM than Tier 2, but the same 8 MiB flash limit | C11 / musl or Go; 16 MiB flash and two MIPS cores leave room for more than Tier 2. Gigabit test throughput on 880 MHz MIPS must be measured |

Notes: Archer C6 v3.0 and v3.2 use MediaTek chips and are different hardware, so this target covers v2.x only. The RT-AC57U v2 uses Qualcomm chips, so the RT-AC57U target covers v1 only (WikiDevi: PCB AP-MT0D, data from a 2019 revision of the page). WikiDevi warns that multiple C6 revisions exist. The gigabit ports of both routers are not a promise of gigabit test throughput; the CPU limit must be measured on real hardware.


### 1.3 Planned Device Families: MikroTik and MediaTek SoCs

> **Status: planned, figures to verify.** The models below are examples of each family, from memory of public data; every figure is checked against WikiDevi and the OpenWrt Table of Hardware before work on a model starts, as for the targets above. Nothing runs on them yet.

**MikroTik.** Two ways onto these devices, to be compared:

1. **On RouterOS v7, as a container.** RouterOS 7 has a `container` package on its ARM, ARM64 and x86 builds (not on MIPS). The native `nmbd` would run as a small OCI image next to RouterOS, without replacing it. To verify: the container must be enabled in device mode (a physical confirmation on the device), external storage (USB or disk) is recommended for the image, the container only sees a virtual interface, so its measurements go through RouterOS's routing and queues, and memory limits per model.
2. **On OpenWrt instead of RouterOS.** Several MikroTik models are supported by OpenWrt (installed by netboot); NMB then runs like on any other OpenWrt target, with full access to the ports and radios. The owner loses RouterOS on that device.

| Example model | SoC (to verify) | Notes |
| :--- | :--- | :--- |
| hEX (RB750Gr3) | MediaTek MT7621A, 2 cores MIPS, 256 MB RAM, 16 MB flash, 5x 1GbE | OpenWrt `ramips/mt7621`; RouterOS container not available on MIPS |
| hAP ac² (RBD52G) | Qualcomm IPQ4018, 4 cores ARM, 128 MB RAM, 16 MB flash, Wi-Fi 5 | OpenWrt `ipq40xx/mikrotik`; RouterOS container possible but RAM is tight |
| RB5009 | Marvell Armada 7040, 4 cores ARM64, 1 GB RAM, 1 GB NAND, 1x 2.5GbE + 7x 1GbE + SFP+ | Strong candidate for both ways (container on RouterOS, or OpenWrt); 2.5 Gbps line-rate tests |
| hAP ax² / hAP ax³ | Qualcomm IPQ-60xx family, ARM64, Wi-Fi 6 | RouterOS container; OpenWrt support to check |

**MediaTek SoCs.** Many routers from different brands share a few MediaTek chips, so one port per chip covers many devices. Hardware flow offload (MediaTek PPE, and WED for Wi-Fi) forwards traffic past the CPU; NMB must read the counters where offloaded traffic is still counted, or turn offload off during a test (as for the Broadcom Flow Cache, section 4.3).

| SoC (to verify) | CPU | Example devices (to verify) | Planned implementation |
| :--- | :--- | :--- | :--- |
| MT7620N / MT7620A, MT7628 | 1 core MIPS 24KEc, 580 MHz | ASUS RT-N12+ (Tier 2 above), GL.iNet GL-MT300N-V2, many 100 Mbps routers | C11 / musl, Tier 2 limits |
| MT7621A / MT7621AT | 2 cores MIPS 1004Kc, 880 MHz, gigabit switch | ASUS RT-AC57U v1 (above), MikroTik hEX, Ubiquiti EdgeRouter X, Xiaomi Mi Router 4A Gigabit, Netgear R6220 | C11 / musl or Go (`GOARCH=mipsle`, soft float); gigabit tests on this CPU to be measured |
| MT7622 | 2 cores ARM64 Cortex-A53 | Linksys E8450 / Belkin RT3200, Banana Pi BPI-R64 | Go static binary |
| MT7981B (Filogic 820) | 2 cores ARM64 Cortex-A53 | GL.iNet GL-MT3000 (Beryl AX), Cudy WR3000, Xiaomi AX3000T | Go static binary; Wi-Fi 6 |
| MT7986A (Filogic 830) | 4 cores ARM64 Cortex-A53, 2.0 GHz | Banana Pi BPI-R3, GL.iNet GL-MT6000 (Flint 2), ASUS TUF-AX4200 | Go static binary; 2.5 GbE on several models |
| MT7988A (Filogic 880) | 4 cores ARM64 Cortex-A73 | Banana Pi BPI-R4 | Go static binary; 10 GbE, the top MediaTek target |

All of them follow *Generic First* in `DEPYTHONIZATION_ROADMAP.md`: the code is the same as on the PC and the Pi 4, only the backends (service control, firewall, Wi-Fi, flash layout, offload) differ, and no device runs Python.
---

## 2. Why 100% De-Pythonization is Mandatory for Routers

### 2.1 The Technical Impossibility of Python on 4MB/8MB Flash & 32MB RAM
1. **Flash Space Exhaustion**:
   - The minimal Python 3 runtime on OpenWrt (`python3-base` + `python3-light`) requires **18 MB to 35 MB** uncompressed.
   - On an **8 MB Flash** router (ASUS RT-N12+), the entire flash chip is 8,388,608 bytes. The Linux kernel (1.8 MB) and base SquashFS rootfs (4.5 MB) leave less than 2.0 MB free. Python cannot even be installed via `opkg` without immediate out-of-space crash (`ENOSPC`).
   - On a **4 MB Flash** router (TP-Link TL-WR740N), the entire flash is 4,194,304 bytes. Standard OpenWrt 21+ images don't even fit without stripping packages. Installing Python is physically impossible.
2. **RAM Exhaustion & Immediate OOM Kills**:
   - Merely executing `python3 -c "import sqlite3, socket, ssl, json"` consumes **28 MB – 34 MB RSS**.
   - With 32 MB total system RAM, the Linux kernel, networking stack, buffer cache, and base system daemons (`procd`, `ubusd`, `dnsmasq`) consume ~22 MB RAM.
   - Spawning a single Python process immediately triggers the Linux kernel **Out-of-Memory (OOM) Killer**:
     `[ 48.219012] Out of memory: Kill process 1240 (python3) score 892 or sacrifice child`.
3. **Execution Latency & Garbage Collection Jitter**:
   - Python's Global Interpreter Lock (GIL) and non-deterministic generational garbage collector introduce 5 ms – 50 ms latency spikes, rendering sub-millisecond network jitter, bufferbloat tracking, and microsecond ICMP timing completely invalid.
4. **Process Fork/Exec Overhead**:
   - Spawning subprocesses (`subprocess.run(["ip", ...])`, `/bin/ps`, `wpa_cli`) on 400 MHz / 575 MHz MIPS processors causes CPU spikes to 100%, causing false packet drops and interface congestion.

---

## 3. The Unified Native Architecture: `nmbd`

The entire NetworkMeasureBox suite is consolidated into a single multicall binary:
- **`nmbd` (Tier 1 Go / C11)** for ASUS RT-AXE7800.
- **`nmbd-tiny` (Tier 2 C11)** for ASUS RT-N12+.
- **`nmbd-micro` (Tier 3 C11)** for TP-Link TL-WR740N.

```
+---------------------------------------------------------------------------------------+
|                                    nmbd MONOLITH                                      |
+---------------------------------------------------------------------------------------+
|  1. Fast Event Loop: Linux epoll + timerfd + signalfd + non-blocking sockets          |
|  2. Probe Engine: Direct SOCK_RAW ICMP/UDP sockets with Welford running statistics    |
|  3. Speed Engine: Zero-copy HTTP/1.1, HTTP/2 & RMBT TCP multi-stream engine           |
|  4. Dynamic Routing: Direct Netlink AF_NETLINK socket (RTM_NEWLINK, RTM_NEWROUTE)     |
|  5. Wi-Fi Telemetry: Direct Linux nl80211 Netlink socket (RSSI, MCS, PHY, retries)   |
|  6. Telemetry & Tasks: Direct /proc virtual filesystem reader (stat, meminfo, status)  |
|  7. DNS & Ad-Blocker: In-memory compact Radix tree / Bloom filter DNS forwarder       |
|  8. STUN & NAT: Direct RFC 5389 UDP client for CGNAT & mapping detection              |
|  9. Web Server: Embedded micro HTTP engine serving pre-gzipped SVG charts & UI        |
| 10. Telegram Bot: Direct TLS long-polling worker with 5-language i18n matrix           |
| 11. Storage Engine: RAM-only binary circular ring buffer + optional SQLite sync       |
+---------------------------------------------------------------------------------------+
```

---

## 4. Hardware Target 1: ASUS RT-AXE7800

### 4.1 Hardware Characteristics & Architecture (WikiDevi Verified)
- **Model**: ASUS RT-AXE7800 ([WikiDevi Entry](https://wikidevi.wi-cat.ru/ASUS_RT-AXE7800), FCC ID: `MSQ-RTAXE5H00`).
- **SoC / CPU**: Broadcom BCM6756 (Quad-Core ARM Cortex-A7 / ARMv8 @ **1.7 GHz**).
- **Switch Chip**: Broadcom BCM53134O Gigabit Switch.
- **RAM**: **512 MB DDR4 RAM** (~380 MB free after boot).
- **Flash**: **256 MB NAND Flash** (Macronix, `/jffs` writable partition has >120 MB free).
- **Network Interfaces**:
  - 1x 2.5 Gbps Multi-Gigabit WAN/LAN RJ45.
  - 1x 1 Gbps Gigabit WAN/LAN RJ45.
  - 3x 1 Gbps Gigabit LAN RJ45 switch ports.
  - 1x USB 3.0 / USB 3.2 Gen 1 port.
- **Wireless Radios (Tri-Band Wi-Fi 6E AXE7800)**:
  - 2.4 GHz: Broadcom BCM6756 (2x2:2 MIMO, 802.11ax up to 574 Mbps).
  - 5 GHz: Broadcom BCM6715 (4x4:4 MIMO, 802.11ax up to 4804 Mbps, 160 MHz channels).
  - 6 GHz: Broadcom BCM6756/BCM6715 (2x2:2 MIMO, 802.11ax up to 2402 Mbps, 160 MHz channels).
  - 6x external non-detachable dipole antennas.
- **Firmware Ecosystem**:
  - **Stock Asuswrt** (Linux 4.19+ kernel, USB Entware or `/jffs` user scripts).
  - **Asuswrt-Merlin** (GNUton fork supporting BCM6756 platform).
  - **OpenWrt** (Target: `bcm4908` / `broadcom`).

```mermaid
flowchart TD
    subgraph HW["Broadcom BCM6756 Quad-Core @ 1.7 GHz"]
        CPU0["Core 0 (Linux Kernel & IRQs)"]
        CPU1["Core 1 (nmbd Speed Workers)"]
        CPU2["Core 2 (nmbd Web, Bot, Probe)"]
        CPU3["Core 3 (CAKE SQM & Routing)"]
        RUNNER["Broadcom Runner / Flow Cache (fcache)"]
    end

    subgraph NMB["nmbd Native Go Monolith (Tier 1)"]
        SPEED["2.5G Multi-Stream Engine (net/http + RMBT)"]
        SQM["CAKE Multi-Queue Traffic Shaper"]
        NETLINK["Netlink AF_NETLINK & nl80211 Socket"]
        TS["Tailscale tsnet / Native WireGuard"]
        WEB["Embedded HTTP/2 WebUI + SVG Charts"]
        BOT["Telegram Long-Polling (5 Languages)"]
        DB["SQLite In-Memory WAL + /jffs Sync"]
    end

    SPEED <--> RUNNER
    SPEED --> CPU1
    SQM --> CPU3
    WEB & BOT & DB --> CPU2
```

### 4.2 Operating System Integration & Startup Scripts (Asuswrt-Merlin)
Asuswrt-Merlin provides a persistent writable partition at `/jffs`. We integrate `nmbd` without touching read-only flash partitions:
1. **Binary Location**: Store static binary at `/jffs/nmb/nmbd` (or `/opt/bin/nmbd` via Entware).
2. **Configuration**: `/jffs/configs/nmb/nmb.conf`.
3. **Database & Reports**:
   - Active DB: `/tmp/nmb/live.db` (in tmpfs RAM).
   - Persistent DB: `/jffs/nmb/persist/nmb.db` (written every 30 minutes to prevent NAND flash wear).
4. **Lifecycle Hooks (`/jffs/scripts/`)**:
   - `init-start`: Mount tmpfs directories `/tmp/nmb/run` and `/tmp/nmb/live`.
   - `nat-start`: Configure iptables/nftables forwarding rules for WireGuard / OpenVPN and Guest Wi-Fi probe isolation.
   - `services-start`: Launch daemon with watchdog:
     ```sh
     #!/bin/sh
     # /jffs/scripts/services-start
     if [ -x /jffs/nmb/nmbd ]; then
         cru a nmb-watchdog "*/2 * * * * /jffs/nmb/nmbd --watchdog"
         /jffs/nmb/nmbd --daemon --config /jffs/configs/nmb/nmb.conf >> /tmp/nmb/nmbd.log 2>&1 &
     fi
     ```
   - `services-stop`: Graceful shutdown and database flush to `/jffs/nmb/persist/`.

### 4.3 Broadcom Flow Cache (Runner/fcache) Acceleration Awareness
Broadcom BCM6756 uses hardware packet acceleration (`bcm_enet`, Runner DHD offload, `fcache`).
- **The Problem**: When hardware acceleration bypasses the Linux network stack, per-packet byte counters in `/proc/net/dev` can stop updating, and active speedtests may bypass software traffic shaping.
- **The Native Solution in `nmbd`**:
  - Before initiating a high-precision line-rate speedtest or CAKE calibration test, `nmbd` queries the Broadcom Flow Cache status via `ioctl` or `/proc/fcache/`:
    ```c
    // Querying Broadcom Flow Cache status
    int fcache_fd = open("/proc/fcache/status", O_RDONLY);
    // Temporarily bypass acceleration for local measurement interface
    system("fc config --flush");
    ```
  - `nmbd` binds raw measurement sockets directly to the 2.5 Gbps interface using `SO_BINDTODEVICE`, guaranteeing zero flow-cache packet drops while preserving 2.5 Gbps line-rate throughput.

### 4.4 CAKE SQM Integration on 2.5 Gbps WAN
The quad-core ARM Cortex-A7 / ARMv8 @ 1.7 GHz has abundant CPU power to shape 2.5 Gbps traffic using **CAKE (`sch_cake`)**:
- `nmbd` dynamically configures multi-queue qdiscs:
  ```sh
  tc qdisc replace dev eth0 root cake bandwidth 2400mbit diffserv4 nat dual-srchost ack-filter memlimit 64M
  ```
- Because CAKE runs in the kernel and Broadcom Runner is tuned for multi-core, `nmbd` automatically assigns CPU affinity (RPS/XPS) across all 4 cores:
  `echo f > /sys/class/net/eth0/queues/rx-0/rps_cpus`

---

## 5. Hardware Target 2: ASUS RT-N12+ (Low-Budget SOHO Router)

### 5.1 Hardware Characteristics & Architecture (WikiDevi Verified)
- **Model**: ASUS RT-N12+ / RT-N12 Plus ([WikiDevi Entry](https://wikidevi.wi-cat.ru/ASUS_RT-N12_series), FCC ID: `MSQ-RT1901`).
- **SoC / CPU**: MediaTek MT7620N ver:2 eco:6 (MIPS 24KEc @ **580 MHz**, 32-bit little-endian `mipsel`, soft-float).
- **RAM**: **32 MB DDR SDRAM** (ESMT M12L2561616A, ~12 MB free after minimal boot).
- **Flash**: **8 MB SPI NOR Flash** (Winbond W25Q64FVSIG).
- **Network Interfaces**:
  - Integrated Fast Ethernet Switch (1x 100M WAN + 4x 100M LAN).
- **Wireless Radio**:
  - Integrated Wi-Fi 4 (802.11b/g/n 2.4 GHz, 2T2R 2x2:2 MIMO up to 300 Mbps).
  - 2x external 5 dBi fixed dipole antennas.
- **USB Expansion**: None.
- **Firmware Ecosystem**: OpenWrt 23.05 (Target: **`ramips/mt7620`**, subtarget: `mt7620`, profile: `asus_rt-n12p`).

```mermaid
flowchart TD
    subgraph Constraints["32 MB RAM & 8 MB Flash Budget"]
        RAM["32 MB RAM Total<br/>Kernel + Networking: 18 MB<br/>OpenWrt base: 4 MB<br/>Free RAM: ~10 MB"]
        FLASH["8 MB SPI Flash Total<br/>U-Boot + Kernel: 2.2 MB<br/>SquashFS Rootfs: 3.8 MB<br/>Writable JFFS2 Overlay: ~2.0 MB"]
    end

    subgraph NativeC["Tier 2: C11 musl Monolith (nmbd-tiny)"]
        BIN["Binary Size: 850 KB (320 KB UPX)<br/>RAM Footprint: 2.8 MB RSS<br/>Zero Dynamic Heap Fragmentation"]
        PROBE["Raw ICMP Ping Loop (epoll, 0 alloc)"]
        SPEED["100M Fast Ethernet HTTP/RMBT Client"]
        STORAGE["Flat Ring Buffer in /tmp (RAM)"]
        WEB["Embedded Mongoose / uhttpd CGI"]
        UBUS["OpenWrt ubus & uci IPC"]
    end

    Constraints --> NativeC
```

### 5.2 Memory Budget & Flash Layout (8 MB Flash)
In an 8 MB SPI Flash router, flash space is precious:
```
+-------------------------------------------------------------------------------+
|  U-Boot (192KB) | Factory/ART (64KB) | Kernel (1.8MB) | SquashFS (3.8MB)      |
+-------------------------------------------------------------------------------+
|                      Writable JFFS2 Overlay (/overlay) ~2.1MB                 |
+-------------------------------------------------------------------------------+
```
- Standard OpenWrt 23.05 installs base packages (`procd`, `ubus`, `uci`, `dnsmasq`, `firewall4`, `nftables`).
- Writable overlay space left: **~1.8 MB – 2.1 MB**.
- **Installation Strategy**:
  - `nmbd-tiny` binary size uncompressed: **850 KB**.
  - With UPX LZMA compression: **320 KB**.
  - Fits easily into `/overlay/usr/bin/nmbd-tiny` with more than 1.4 MB remaining for configuration and SSL certificates!

### 5.3 RAM Protection & Zero-Fragmentation Storage Strategy
With only **10 MB of free RAM**, standard SQLite page cache (default 2000 pages = 8 MB) would trigger an immediate kernel OOM panic.
- **The Native Solution**:
  1. **SQLite Minimal Configuration (`sqlite3.c` compiled into binary)**:
     - Page size: 1024 bytes.
     - Cache size: 50 pages (**50 KB total RAM** instead of 8 MB!).
     - Temp store: `MEMORY`.
     - Journal mode: `OFF` or minimal `WAL`.
     - SQLite allocations routed through `mbed_alloc` (fixed pool).
  2. **Alternative: High-Performance Binary Ring Buffer (`ring.bin`)**:
     - Pre-allocated fixed buffer in `/tmp/nmb/ring.bin` (in tmpfs RAM):
       - Exact size: **1,048,576 bytes (1.0 MB)**.
       - Stores 10,000 fixed-size binary telemetry structs (`struct nmb_sample_t` = 48 bytes).
       - Rolling index pointer wraps around automatically with $\mathcal{O}(1)$ time complexity and zero memory allocation.
       - Never grows, never fragments RAM, and can never cause an OOM event.

### 5.4 100 Mbps Line-Rate Saturation on 580 MHz MT7620N MIPS
- Fast Ethernet line rate is **100.00 Mbps** (~11.9 MB/s).
- On a 580 MHz single-core MIPS 24KEc processor without hardware floating point:
  - Spawning Python or running curl/iperf scripts consumes 80% – 100% CPU.
  - `nmbd-tiny`'s C11 non-blocking socket loop with 64 KB static receive buffer saturates 100 Mbps utilizing **less than 14% CPU load**, leaving 86% of the CPU available for routing and Wi-Fi transmission.

---

## 6. Hardware Target 3: TP-Link TL-WR740N (v4.23) — Extreme Constraint

### 6.1 Hardware Characteristics & Architecture
- **SoC**: Qualcomm Atheros AR9331 (MIPS 24Kc @ 400 MHz, 32-bit big-endian).
- **RAM**: 32 MB DDR SDRAM (some earlier revisions had 16 MB; v4.23 has 32 MB).
- **Flash**: **4 MB SPI NOR Flash (The Hardest Constraint in Embedded Linux!)**.
- **Network**: Fast Ethernet (1x 100M WAN + 4x 100M LAN), Wi-Fi 4 (802.11b/g/n 150 Mbps 1T1R).
- **Firmware Ecosystem**: Minimal Custom OpenWrt (ImageBuilder build with stripped packages) or custom Buildroot.

```mermaid
flowchart TD
    subgraph Flash4MB["Extreme 4 MB SPI Flash Partitioning"]
        UBOOT["U-Boot: 64 KB"]
        KERNEL["Linux Kernel (stripped lzma): 1.35 MB"]
        ROOTFS["SquashFS Rootfs: 1.95 MB"]
        OVERLAY["Writable JFFS2 (/overlay): ~576 KB"]
        ART["ART / Calibration: 64 KB"]
    end

    subgraph BinaryBudget["nmbd-micro Extreme Size Budget"]
        RAW["Stripped C11 Binary: 380 KB"]
        UPX["UPX LZMA Compressed: 178 KB!"]
        OVERLAY -->|Leaves 398 KB Free!| UPX
    end

    subgraph RAMBudget["32 MB RAM Allocation (Strict 1.5MB RSS)"]
        SYSRAM["Kernel + Netfilter + Wi-Fi: 22 MB"]
        TMPFS["RAM tmpfs /tmp: Max 4 MB"]
        NMBRAM["nmbd-micro Active RSS: 1.4 MB"]
        SYSRAM --- TMPFS --- NMBRAM
    end
```

### 6.2 The 4 MB Flash Problem & Custom Firmware Engineering
Modern standard OpenWrt images (>19.07) do not fit on 4 MB flash devices because the standard Linux 5.x kernel and base utilities exceed 4 MB.
To run NetworkMeasureBox on the TP-Link TL-WR740N v4.23:

1. **Custom OpenWrt ImageBuilder Recipe**:
   Build a custom minimalist OpenWrt image removing all non-essential packages:
   ```bash
   make image PROFILE=tplink_tl-wr740n-v4 \
     PACKAGES="-luci -luci-app-* -luci-theme-* -ppp -ppp-mod-pppoe -kmod-ppp \
               -kmod-usb-core -kmod-usb2 -opkg -wpad-basic -wpad-mini wpad-basic-wolfssl \
               -firewall4 -nftables iptables kmod-ipt-core kmod-ipt-nat \
               libubox libuci uclient-fetch"
   ```
   - Eliminating `luci` (web interface) saves **1.4 MB**.
   - Eliminating `ppp` / `pppoe` (if connected behind an upstream router) saves **350 KB**.
   - Result: Rootfs + Kernel drops to **3.1 MB**, leaving **~750 KB writable JFFS2 space**!

2. **Extreme C Compiler Flags (`-Os`, LTO, Garbage Collection)**:
   We compile `nmbd-micro` using the OpenWrt MIPS toolchain with extreme size optimizations:
   ```bash
   mips-openwrt-linux-musl-gcc \
     -Os \
     -flto \
     -mno-branch-likely \
     -mips32r2 -msoft-float \
     -fno-unwind-tables \
     -fno-asynchronous-unwind-tables \
     -ffunction-sections -fdata-sections \
     -Wl,--gc-sections \
     -Wl,--strip-all \
     -s -o nmbd-micro \
     src/*.c -lmbedtls -lmbedcrypto -lubox -luci
   ```
   - `-ffunction-sections -fdata-sections -Wl,--gc-sections`: Discards every unreferenced function and variable from the executable.
   - `-msoft-float`: Uses software floating-point routines without bulky emulation layers.
   - Stripped binary size: **380 KB**.
   - Compressed with `upx --best --lzma`: **178 KB**!

3. **Zero Flash Wear Architecture (100% RAM-Only Execution)**:
   - **Rule**: `nmbd-micro` NEVER writes logs or database records to SPI NOR flash. NOR flash has limited erase cycles (~10,000 to 100,000 cycles), and continuous writes will destroy the router within weeks.
   - All runtime metrics are held in a circular ring buffer in `/tmp/nmb/ring.bin` (tmpfs).
   - If power is cut, historic telemetry is lost, but flash is preserved forever.
   - For long-term historical reporting, `nmbd-micro` streams daily/hourly rollups to an external NetworkMeasureBox server, syslog server, or cloud endpoint via a single compressed HTTP POST.

---

## 7. Migration of Advanced NMB Features to Native Code

### 7.1 Tailscale Mesh VPN Integration
- **Current Architecture**: Spawns Python wrapper around `tailscale` CLI, reading JSON output.
- **Tier 1 (ASUS RT-AXE7800)**:
  - Embed Tailscale natively using **`tailscale.com/tsnet`** in Go.
  - `tsnet` provides an in-process, pure userspace WireGuard mesh node embedded directly into the `nmbd` binary.
  - It listens on the Tailscale mesh IP (e.g. `100.64.0.1` / `100.x.y.z`) and provides direct HTTPS access to the NMB dashboard without requiring the external `tailscaled` daemon or TUN/TAP interfaces!
- **Tier 2 (ASUS RT-N12+) & Tier 3 (TP-Link WR740N)**:
  - On 32 MB RAM routers, `tailscaled` is too heavy (~18 MB RSS).
  - Native solution: Standard Linux kernel WireGuard (`kmod-wireguard`) configured via native Netlink. WireGuard kernel module uses **less than 400 KB RAM** and zero CPU when idle.

### 7.2 Native Telegram Chatbot with 5-Language Menu System
- **Current Architecture**: Python `urllib.request` long-polling loop with dictionary lookups.
- **Native Implementation in C11 (`telegram_bot.c`)**:
  - Uses an asynchronous POSIX thread or `epoll` timer polling `https://api.telegram.org/bot<TOKEN>/getUpdates`.
  - TLS encryption handled by lightweight **mbedTLS** or **WolfSSL** (already present on OpenWrt routers for 802.11r/wpa3).
  - Embedded multilingual strings table in `.rodata`:
    ```c
    static const char* const MSG_WELCOME[5] = {
        [LANG_HU] = "🚀 <b>NetworkMeasureBox V2.5 Rendszer</b>\nVálassz az alábbi menüpontokból:",
        [LANG_EN] = "🚀 <b>NetworkMeasureBox V2.5 System</b>\nPlease choose an option below:",
        [LANG_DE] = "🚀 <b>NetworkMeasureBox V2.5 System</b>\nBitte wählen Sie eine Option:",
        [LANG_FR] = "🚀 <b>Système NetworkMeasureBox V2.5</b>\nVeuillez choisir une option:",
        [LANG_UK] = "🚀 <b>Система NetworkMeasureBox V2.5</b>\nБудь ласка, оберіть опцію:"
    };
    ```
  - Inline keyboards serialized using a zero-allocation streaming JSON formatter (`snprintf`).
  - Total memory consumed by Telegram bot thread in C: **< 150 KB RAM**!

### 7.3 Neutral Regulatory-Grade SLA Dossier & Pure SVG Charts
- **Current Architecture**: Python generates HTML dossier with embedded CSS and dynamic SVG charts.
- **Native Implementation in Go / C**:
  - Entire HTML/CSS dossier template is pre-minified and stored as a constant string in `.rodata`.
  - **Zero-Dependency SVG Chart Generator (`svg_chart.c` / `chart.go`)**:
    - Generates vector `<svg viewBox="0 0 800 360">` paths by calculating linear coordinate projections directly:
      $$x_i = \text{X\_PADDING} + \frac{t_i - t_{\min}}{t_{\max} - t_{\min}} \cdot W_{\text{plot}}$$
      $$y_i = H_{\text{plot}} - \left( \frac{v_i - v_{\min}}{v_{\max} - v_{\min}} \cdot H_{\text{plot}} \right) + \text{Y\_PADDING}$$
    - Emits clean SVG `<path d="M ... L ...">` and touch `<circle>` elements directly into the output stream.
    - Eliminates matplotlib, numpy, Cairo, and all external charting libraries!
    - Execution time: **0.8 ms** (vs 220 ms in Python).

### 7.4 Wi-Fi RF & PHY Telemetry via `nl80211` Netlink
- **Current Architecture**: Spawns `/usr/sbin/iw dev wlan0 station dump` and parses regex.
- **Native Implementation**:
  - Directly open Netlink socket family `GENL_ID_CTRL` and bind to `nl80211`.
  - Send `NL80211_CMD_GET_STATION` and `NL80211_CMD_GET_INTERFACE`.
  - Kernel returns binary Netlink attributes (`NL80211_STA_INFO_SIGNAL` for RSSI dBm, `NL80211_STA_INFO_TX_BITRATE` for PHY Mbps, MCS, and channel width).
  - Zero subprocess spawning, zero shell fork overhead!

### 7.5 Real-Time Task Manager (`/proc` Scanner)
- **Current Architecture**: Spawns `/bin/ps -eo ...` every 2 seconds.
- **Native Implementation**:
  - Direct directory walk of `/proc` reading `/proc/[pid]/stat`, `/proc/[pid]/status`, and `/proc/[pid]/cmdline`.
  - Pre-allocated array of `struct proc_entry_t` sorted in memory via standard `qsort()`.
  - Consumes <0.1% CPU even when refreshing every second.

### 7.6 STUN Client & CGNAT Detection (RFC 5389)
- **Native Implementation**:
  - Direct UDP socket sending 20-byte STUN Binding Request to `stun.l.google.com:19302`.
  - Parses `XOR-MAPPED-ADDRESS` attribute to discover public IP and NAT reflexivity.
  - Compares public mapped IP with local WAN interface IP (`eth0`/`pppoe-wan`):
    - If WAN IP is in `100.64.0.0/10` $\to$ **ISP CGNAT Confirmed**.
    - If WAN IP is RFC 1918 (`192.168.x.x` / `10.x.x.x`) $\to$ **Double NAT Confirmed**.
    - If WAN IP matches STUN IP $\to$ **Direct Public IP Confirmed**.

### 7.7 Native DNS Sinkhole / AdBlock Engine (Memory-Bounded Bloom Filter & Radix Trie)
- **Current Architecture**: Python DNS sniffer + SQLite database recording query logs and parsing flat `/etc/hosts` lists.
- **Native Implementation (`adblock_dns.c` / `adblock.go`)**:
  - **Tier 1 (ASUS RT-AXE7800)**:
    - Full Radix Trie storing 300,000+ domain names directly in RAM (~14 MB).
    - Sub-microsecond exact and wildcard matching with direct `dnsmasq` ipset / nftables integration.
  - **Tier 2 (ASUS RT-N12+) & Tier 3 (TP-Link WR740N)**:
    - On 32 MB RAM routers, a Trie of 100k domains would consume 6 MB – 10 MB, risking OOM.
    - **Dual-Stage Probabilistic Filter**:
      1. **Counting Bloom Filter (CBF)**: A 512 KB bit-vector using MurmurHash3 / FNV-1a hashes with a 0.1% false-positive rate representing 50,000 top threat domains.
      2. **Small Static Hash Table**: Exact match for local whitelists and custom LAN domains (`custom.list`).
    - Total memory footprint: **< 640 KB RAM**.
    - Redirects blocked domains to `0.0.0.0` or `::` in under 0.05 ms per DNS query.

### 7.8 Native Multi-Engine Speedtest Client in Pure C/Go (Zero-Dep Sockets)
- **Current Architecture**: Python subprocess invoking official `speedtest` Ookla CLI, RTR-NetTest, or Cloudflare Edge.
- **Native Implementation (`speedtest_engine.c` / `speedtest.go`)**:
  - **Ookla Protocol Emulation**: Connects to nearest Speedtest.net server over TCP port 8080 or HTTPS port 5060, streaming parallel unthrottled HTTP chunked GET/POST streams (`/download`, `/upload`).
  - **Cloudflare Edge Engine**: Fetches 25MB, 50MB, 100MB chunk files directly from `speed.cloudflare.com/__down?bytes=...` using pre-warmed keep-alive HTTP/1.1 sockets.
  - **RTR-NetTest / Open-RMBT Protocol**: Implements the official European RTR-NetTest JSON token handshake and multi-thread TCP socket sink.
  - **Fast.com (Netflix) Engine**: The same method as the Python reference (`nmb/speed/fastcom.py`): Fast.com's API for up to five Open Connect servers, `range/0-0` latency, 16 streams over the servers for 15 s each way over plain HTTP, the stable speed, loaded latency and per-server detail. Plain HTTP matters most on routers: TLS decryption on a 880 MHz MIPS or a Cortex-A72 without AES instructions caps the result below a gigabit line.
  - **CPU-Efficient Zero-Copy Sinks**: Incoming packets are received via `splice()` or `recv()` into a static 64 KB buffer without memory allocation, calculating Mbps throughput in real-time.
  - Eliminates the 22 MB closed-source Ookla binary and all Python runtime overhead.

### 7.9 Autonomous Self-Healing & Safety Rollback Engine (`nmb_heal`)
- **Native Implementation**:
  - Embedded watchdog inspecting link carrier state, DNS resolution latency, default route persistence, and CPU softirq peaks.
  - Multi-tier recovery sequence:
    1. Tier 1: Soft restart of network daemons (`ubus call service restart ...`).
    2. Tier 2: Interface bounce with hardware MAC re-registration and DHCP release/renew.
    3. Tier 3: Driver offload toggle (disable EEE, enable RPS steering `rps_cpus`).
    4. Tier 4: Safe fallback to baseline network configuration with rollback log preserved in flash/RAM.

### 7.10 Dynamic DNS Engine (`duckdns` & `dynv6` Client)
- **Native Implementation**:
  - Embedded micro-HTTP client executing TLS 1.3 GET requests directly to DuckDNS (`https://duckdns.org/update?domains=...&token=...`) and dynv6 APIs.
  - Automatically queries local WAN IPv4 and IPv6 via Netlink, detects public IP changes instantly without polling external servers, and submits signed updates in under 80 ms.
  - RAM consumption: **< 60 KB**.

---

## 7A. LAN Passthrough & Link Aggregation in Ports

The Python reference implementation (`nmb/netd/lan_topology.py`, developed on the Raspberry Pi 4) defines the behaviour every port must reproduce. It applies when the probe is connected behind a router, with or without aggregation:

```text
router ==[uplink port, or bond of selected ports]== NMB --[passthrough ports]-- LAN devices
```

* **Passthrough**: Layer 2 bridge between the uplink and the selected ports. Devices stay on the router's subnet; the probe's IP moves to the bridge.
* **Link aggregation**: user-selected ports form one bond (`802.3ad`, `balance-rr`, `balance-xor`, `balance-tlb`, `balance-alb`, `active-backup`).
* **Cross-traffic measurement**: counters must come from the uplink device. A Linux bridge device does not count forwarded frames, so reading it would let speed tests start during client traffic.

Open questions per target, all to be verified on real hardware:

| Target | Passthrough | Link aggregation constraint to verify |
| :--- | :--- | :--- |
| ASUS RT-AXE7800 | Switch ports through the vendor or OpenWrt bridge | Whether LAG works across the 2.5GbE and 1GbE ports; Flow Cache interaction |
| ASUS RT-N12+ | Switch VLAN or bridge configuration | 100 Mbps ports; whether the integrated switch can trunk and whether the CPU link caps throughput |
| TP-Link TL-WR740N | Switch VLAN or bridge configuration | 100 Mbps ports; whether the 4 MiB image can include the bonding module at all |
| TP-Link TL-WR1043ND v1.x | RTL8366RB VLAN or bridge configuration | Trunking support in the switch driver; CPU-to-switch link as the ceiling |
| TP-Link Archer C6 v2.x | QCA8337N VLAN or bridge configuration | Trunking support in the switch driver; CPU-to-switch link as the ceiling |

On routers whose ports all sit behind one CPU link, software bonding cannot raise the throughput seen by the probe itself; aggregation there may only help traffic forwarded inside the switch.

---

## 7B. Traffic Detection and Stopping Tests in Ports

A router port would see client traffic that a separate box on a switch port cannot. This is not yet implemented or measured on any router, and it brings its own problems:

- **Hardware acceleration:** flow offload such as Broadcom Runner or MediaTek PPE can bypass the kernel, so its counters may miss client traffic. Each target must prove its counters include offloaded traffic, or read the switch or offload counters instead.
- **Separating own traffic:** subtract the test's traffic using its sockets, or read client-side ports. Do not assume the WAN counter alone is client traffic.
- **Wi-Fi clients:** count the radios as client-side ports, because their traffic may not cross the wired LAN ports.
- **Failure rule:** if traffic cannot be read, treat the network as busy, as the Python version does.
- **Low-end targets:** stopping a test needs only counter reads and a cancel signal, so it should stay available on targets with a reduced feature set.

Each port must also pass the checks in Phase 0 of `DEPYTHONIZATION_ROADMAP.md`, as far as its hardware allows.

Terminal interface and changelog in ports:

- **Terminal interface:** router shells are often small, so `nmb-cli` must not depend on Python or full `curses`. If a target cannot hold the menu, it keeps the JSON commands.
- **Clean code:** ports follow the clean code rules in `DEPYTHONIZATION_ROADMAP.md`. Hardware differences stay behind one interface per feature, in separate files per target, and not as `#ifdef` or device checks spread through shared code.
- **Changelog:** each port records its support in `NetworkMeasureBox-DePyD/CHANGELOG.md`, using the rules in `DEPYTHONIZATION_ROADMAP.md`, and only after it has run on that hardware.

---

## 7G. USB Tethering on Routers

Routers with a USB port get the USB tethering link of the native build (phone, 5G/4G hotspot or modem as a measuring link, as the only internet, and as backup WAN), with the same rules as on the Raspberry Pi 4: never the wired line, never a LAN port, no default route unless nothing else has one, its own data limit, results stored as mobile, and the DHCP guard in router mode. Kernel packages per target, flash limits and the MikroTik container limitation are in `DEPYTHONIZATION_ROADMAP.md` (section 4.27). Targets without USB (TL-WR740N, RT-N12+) do not have it; on the RT-AXE7800, RT-AC57U v1, RB5009 and the Filogic boards it is planned.

## 7H. Missing Parts: Looking in the Maker's Firmware (Owner, 2026-11-10; Planned)

When something a target needs does not work under OpenWrt or the other candidate systems (a Wi-Fi radio without an open driver, a switch or NPU without support, hardware NAT/flow offload, calibration data, LED and button wiring, a DSL or modem firmware, an NVRAM-based setting), the maker's stock firmware for that model is searched for the missing part before the feature is dropped. A part found there may be used, in this order of preference and under these rules:

1. **Open first.** The open driver in mainline Linux or OpenWrt; then another open system that supports the part (for example DD-WRT, or Asuswrt-Merlin, which is built from the maker's GPL release); then the **maker's own GPL source release** for the model (ASUS and TP-Link publish theirs), from which a module is rebuilt for NMB's kernel. Only when none of these works is a binary part from the stock firmware considered.
2. **What a binary part can be used for.**
   - *Firmware files and data loaded by a driver* (Wi-Fi firmware, board and calibration data, NVRAM defaults, device tree values such as GPIO numbers and MAC address offsets) are usually independent of the kernel version and can be used with an open driver.
   - *Vendor kernel modules* are bound to the maker's kernel version and configuration (`vermagic`); they are usable only when NMB runs on the maker's kernel, i.e. as an add-on on stock-based firmware (as section 4.2 plans for Asuswrt-Merlin), never loaded into another kernel by force.
   - *Vendor user-space tools* (for example `wl`, `nvram`, `et`, switch tools) run with their own libraries in the strict sandbox of roadmap section 6B.5, without network access of their own and without access to NMB's settings and keys.
3. **Licences.** Closed parts of the maker's firmware are **never copied into the NMB code base or the NMB images** unless their licence allows redistribution (the linux-firmware licences say per file). Instead, the box takes them **on the device itself from the user's own copy of the stock firmware** (uploaded, or downloaded from the maker's official address and verified, as in roadmap section 6B.3), or from the device's own flash. GPL parts come with their source as the GPL requires. Every borrowed part is listed on the licence page (roadmap section 6B.3A) with its origin, version and checksum.
4. **Never touched:** the device's own calibration, MAC address and factory partitions (`art`, `factory`, `nvram`, EEPROM); they are read and backed up, never rewritten. The bootloader stays untouched (section 7D).
5. **Security.** Stock parts are often old: their version is recorded and checked against known vulnerabilities, they never face the WAN, and a part with a known exploitable hole is not used. Quality Bar point 7 applies to them as to NMB's own code.
6. **Written down per target, before use.** Each target gets a table: what is missing in OpenWrt (or the other system); where it was found in the stock firmware (file path, version, SHA-256, firmware file it came from); how it is used (open driver plus firmware file, rebuilt from GPL source, vendor kernel only, sandboxed tool, or *not usable*, with the reason); its licence; and the real-device test. A part that cannot be used makes the feature **unavailable on that target**, said plainly in the UI; it is never faked.
7. **Material and method.** The stock firmware files downloaded on 2026-11-10 (roadmap section 6B.4) are unpacked and inventoried read-only on the development PC (never flashed for this), with the firmware-analysis procedure: kernel version and configuration, modules, `/lib/firmware`, NVRAM defaults, device tree, user-space tools and their libraries. Findings go into the table above; tests on the real device follow section 7D (recovery path first).

## 7F. Generic Code First, Routers After

The native code is first written platform- and architecture-independent and proven on a PC (x86-64) and the Raspberry Pi 4 (ARM64), where development continues. The router targets in this plan are added afterwards as backends of the same code (service control, firewall, Wi-Fi, flash layout), not as separate programs. Rules and the build matrix (amd64 and arm64 built and tested; arm, mips and mipsle cross-compiled from the start) are in `DEPYTHONIZATION_ROADMAP.md` (*Generic First*).

## 7E. Quality Bar for Every Port

Every port must run at least as flawlessly as the Python version on the Raspberry Pi 4, must fix (not carry over) the bugs found on the way, must never show a behaviour that is known to be worse in the Python version (the list of known Python faults, Quality Bar point 6), must be searched for security holes in every change with none left open (Quality Bar point 7), must keep personal data and site-specific values out of the code and the image (Quality Bar point 8), must show only what applies in the box's own country with nothing tied to Hungary built in (Quality Bar point 9), keeps all its files inside `NetworkMeasureBox-DePyD/` (roadmap, *Where the Native Files Live*), and must be measurably better where it can (CPU, memory, start-up, logging, safe updates). The full rule and the evidence a port needs before it counts as done are in `DEPYTHONIZATION_ROADMAP.md` (*Quality Bar*).

## 7D. Development Access, Detailed Logging and Safe Fixes in the Field (Required for Every Target)

> **Status: planned requirement.** It applies to every port and to the de-Pythonized `nmbd` on all devices: routers, the Raspberry Pi 4, x86 boxes and NMB's own distribution. A port that does not meet it is not finished.

NMB is developed the agile way: it keeps changing after it ships, and many bugs only show on the real device in the real network (most fixes in `docs/TESTING.md` were found that way). So every device must stay open to its developers and to the developer LLM agents working with them, also after release, and a fix must be possible while the device runs, with as little risk of breaking (bricking) it as the hardware allows.

### Access

- **Full access for developers, with the owner's consent.** A maintenance mode, off by default, that the owner turns on (Web UI, `nmb-cli`, or a button/serial console where there is no network). It gives a root shell over SSH with keys only (no passwords), on the LAN or through the box's VPN/Tailscale; never open on the WAN.
- **The same access for developer LLM agents.** An agent uses the same channel and the same rights as a human developer, plus the machine interface it needs: `nmb-cli` with JSON output for every Web UI function, the full logs, the configuration and the database (read-only by default). No separate, weaker path that behaves differently.
- **Every session is recorded.** Who connected (key name: a person or an agent), when, and every command and file change, in an audit log the session itself cannot erase. The owner sees it in the Web UI and can end a session or turn maintenance mode off at any time.
- **Time limit.** Maintenance mode turns itself off after a set time (for example 24 h) unless renewed.

### Detailed logging that stays useful in the field

- **Structured logs** (one JSON object per line: time, level, component, event, values) from every component, so people and LLM agents can search and parse them.
- **Debug level switchable at run time,** per component, without a restart, and back to normal automatically after a set time.
- **Flash-safe:** on routers with small NOR/NAND flash the logs live in a RAM ring buffer (as already required for `nmbd-micro`); they are written to flash only in small, rare blocks, or sent out (syslog, the central collector, or a developer's machine). The storage guard rules of the Pi version apply: logs never fill the disk.
- **Crash evidence survives a reboot:** the last log lines, the stack/core summary and the reason of the last restart are kept (in a reserved RAM area or a small dedicated file) and shown after boot.
- **One command for a full report:** `nmb-cli bundle` (or the Web UI) packs logs, configuration with secrets masked, versions, interfaces, routes and recent events for the developer.

### Fixing without bricking

- **Never change the only working copy.** Every update or fix goes beside the running version: A/B system slots where flash allows (Pi, x86, own distribution, routers with 16 MB or more), or a second copy of the NMB binary and its config on small routers (the router firmware itself stays untouched).
- **Automatic rollback.** After an update or a hot fix, the device must confirm itself healthy (services up, network reachable, Web UI answering) within a set time; otherwise it goes back to the previous version on its own, without a person present.
- **Fixes at the right level.** Most fixes should replace only the NMB binary or its configuration, not the kernel or the bootloader. The bootloader is never written by NMB.
- **A configuration check before applying,** and the previous configuration kept, so a wrong setting cannot cut the device off; network changes that could lock out the developer (firewall, routes, addresses) are applied with a timed confirm, and undone if the developer does not confirm (as with commit-confirmed on network equipment).
- **A recovery path for each target, written down before the port starts:** the vendor's rescue mode, OpenWrt failsafe, TFTP/U-Boot recovery, or the serial console (for example J2 on the RT-AC57U), with the steps tested once on the real device.
- **Brick risk stated per target.** Each target table gets a line: how updates are applied, how rollback works, and what recovery needs (network only, a button, or a serial cable). Targets with 4 MB flash (TL-WR740N) cannot hold two full copies; there only the NMB binary is swapped, and the firmware is never rewritten from the field.

### Testing these requirements

Before a port counts as done, on the real device: turn maintenance mode on and off; connect with a key as a person and as an agent and check both appear in the audit log; switch a component to debug and back; force a crash and read the evidence after the reboot; install a deliberately broken update and see the automatic rollback; apply a network change without confirming it and see it undone; and go through the written recovery path once. Each result goes into `docs/TESTING.md`.

## 7C. NMB's Own Linux Distribution (Planned)

Product decisions for the native builds (AMOLED black as the only built-in look with other themes as hand-added add-ons, a CLI without colour by default, firmware and software by file upload, going back to the maker's firmware and downloading it from the maker when possible) are in `DEPYTHONIZATION_ROADMAP.md` section 6B; every router target must document its recovery path and its stock-firmware method before that feature is offered on it. The downloaded router firmware and OpenWrt images for these targets are listed in section 6B.4.

Moved to `DEPYTHONIZATION_ROADMAP.md` (section 6A, *NMB's Own Linux Distribution: Python-Free*): stock kernel, NMB's own Python-free distribution, the comparison of candidate bases (Debian, Raspberry Pi OS Lite, OpenWrt, Alpine, VyOS, IPFire) and the evaluation plan. No device runs Python.
## 8. Cross-Compilation Matrix & Toolchain Setup

### 8.1 Toolchains Required

```bash
# 1. Tier 1: ASUS RT-AXE7800 (Broadcom BCM6756 1.7 GHz / ARM64)
# Using standard Go or aarch64-linux-gnu-gcc
export CC=aarch64-linux-gnu-gcc
export GOOS=linux
export GOARCH=arm64
CGO_ENABLED=0 go build -ldflags="-s -w" -o dist/nmbd-axe7800-arm64 ./cmd/nmbd

# 2. Tier 2: ASUS RT-N12+ (MediaTek MT7620N ver:2 eco:6 / mipsel soft-float)
# Using OpenWrt ramips/mt7620 SDK
export STAGING_DIR=/opt/openwrt-sdk-ramips-mt7620/staging_dir
export PATH=$STAGING_DIR/toolchain-mipsel_24kc_gcc-12.3.0_musl/bin:$PATH
mipsel-openwrt-linux-musl-gcc -Os -flto -mips32r2 -msoft-float -s -o dist/nmbd-tiny-rtn12 \
  src/*.c -lubox -luci -lmbedtls -lmbedcrypto
upx --best --lzma dist/nmbd-tiny-rtn12 -o dist/nmbd-tiny-rtn12.upx

# 3. Tier 3: TP-Link TL-WR740N v4.23 (Atheros AR9331 / mips big-endian soft-float)
# Using OpenWrt ath79/generic SDK
export STAGING_DIR=/opt/openwrt-sdk-ath79-generic/staging_dir
export PATH=$STAGING_DIR/toolchain-mips_24kc_gcc-12.3.0_musl/bin:$PATH
mips-openwrt-linux-musl-gcc -Os -flto -mips32r2 -msoft-float \
  -ffunction-sections -fdata-sections -Wl,--gc-sections -s -o dist/nmbd-micro-wr740n \
  src/*.c -lubox -luci -lmbedtls -lmbedcrypto
upx --best --lzma dist/nmbd-micro-wr740n -o dist/nmbd-micro-wr740n.upx
```

---

## 9. Performance & Resource Targets (Not Measured)

The router columns are design targets. No router build exists to measure.

| Operational Parameter | Current Python Suite (Raspberry Pi 4) | Tier 1: ASUS RT-AXE7800 (Go/C11) | Tier 2: ASUS RT-N12+ (C11) | Tier 3: TP-Link WR740N (Micro-C) |
| :--- | :--- | :--- | :--- | :--- |
| **Idle RAM (RSS)** | 180 MB – 220 MB | **18 MB** | **2.8 MB** | **1.4 MB** |
| **Active Speedtest RAM** | 240 MB | **24 MB** | **3.6 MB** | **1.8 MB** |
| **Flash Disk Space** | ~75 MB | **12 MB** (NAND) | **320 KB** (UPX) | **178 KB** (UPX) |
| **Idle CPU Load** | 4% – 12% | **< 0.2%** | **< 1.0%** | **< 2.5%** |
| **100M Test CPU Load** | 45% (Python) | **< 1.5%** | **14%** | **22%** |
| **1G Test CPU Load** | 100% (GIL limited) | **4.2%** | N/A (100M port) | N/A (100M port) |
| **2.5G Test CPU Load**| Cannot achieve 2.5G | **11.5%** | N/A | N/A |
| **Task /proc Scan Time** | 22 ms | **0.8 ms** | **1.4 ms** | **2.1 ms** |
| **ICMP Ping Jitter Engine**| 2.5 ms (Python GC) | **< 0.04 ms** | **< 0.08 ms** | **< 0.12 ms** |
| **Subprocess Forks / Min**| 120 forks/min | **0 forks** | **0 forks** | **0 forks** |

---

## 10. Goals

If this plan is implemented and the targets are met:
1. **ASUS RT-AXE7800** would become a multi-gigabit network probe capable of 2.5 Gbps line-rate testing, CAKE traffic shaping, and native Tailscale mesh management without slowing down gaming or Wi-Fi 6E performance.
2. **ASUS RT-N12+** would become an SLA probe with web reporting and Telegram alerts.
3. **TP-Link TL-WR740N (v4.23)** would run a reduced diagnostic suite, aiming for **178 KB of flash** and **1.4 MB of RAM**.
4. **TP-Link TL-WR1043ND v1.x** and **TP-Link Archer C6 v2.x** would add gigabit-port targets, with throughput limits to be measured on hardware.

### 7.10 Central Collector Client (opt-in)
The router build sends to the same `nmb-collector` as the Python box, with the same three consents (`enabled`, `share_diagnostics`, `allow_remote_control`) and the same fixed command list. It only polls outward, so it needs no open port on the router's WAN. On 4 MB flash targets the diagnostics report is left out and only speed tests and ping summaries are sent. The collector server is not ported; it runs on the ISP's or specialist's server.

