# NetworkMeasureBox (NMB) — Architecture

## 1. System Overview

```mermaid
flowchart LR
    subgraph WAN["ISP Edge"]
        ONT["ONT / Modem"]
    end
    subgraph BOX["NetworkMeasureBox (SBC, microSD)"]
        direction TB
        NETD["nmb-netd<br/>Mode A: PPPoE+NAT+hostapd+dnsmasq<br/>Mode B: Passive inline bridge"]
        PROBE["nmb-probe<br/>latency/jitter engine"]
        GATE["traffic gate<br/>/proc/net/dev sampler"]
        SPEED["nmb-speed<br/>Ookla CLI + port-throttle checker"]
        DB[("SQLite WAL<br/>tmpfs live copy")]
        SNAP["nmb-snapshot<br/>sqlite backup API -> SD"]
        REPORT["nmb-report<br/>HTML/SVG + CSV + SMTP"]
        BOT["nmb-telegram"]
        WEB["nmb-web (config UI)"]
    end
    subgraph LAN["Customer LAN"]
        CLIENTS["Clients / Router"]
    end

    ONT <--> NETD <--> CLIENTS
    NETD -- "active iface, mode" --> DB
    PROBE --> DB
    GATE -- "idle?" --> SPEED --> DB
    DB --> REPORT
    DB --> BOT
    DB <--> WEB
    DB -. "every 15 min + shutdown" .-> SNAP
    BOT -- "/test /report" --> SPEED & REPORT
```

### Process model
| Daemon            | Phase | Privileges                     | Writes DB |
|-------------------|-------|--------------------------------|-----------|
| `nmb-netd`        | 2     | root (netlink, pppd, bridges)  | events    |
| `nmb-probe`       | 3     | `CAP_NET_RAW` only             | samples   |
| `nmb-speed`       | 3     | unprivileged                   | tests     |
| `nmb-report`      | 4     | unprivileged (timer)           | no        |
| `nmb-telegram`    | 5     | unprivileged                   | alerts    |
| `nmb-web`         | 5     | unprivileged, binds 127.0.0.1/LAN | config |
| `nmb-snapshot`    | 1     | unprivileged (timer)           | no        |

All daemons run as user `nmb`. Single-writer contention is handled by WAL + `busy_timeout`; probes batch-insert (1 txn / 10 s) so write lock time stays tiny.

## 2. Storage Strategy (microSD Longevity)

The live database lives in **RAM (tmpfs)**. A consistent snapshot is copied to the SD card
using SQLite's online backup API, **every 15 minutes and when the system shuts down**.

```
              RAM (tmpfs)                         microSD (ext4, noatime,commit=600)
/var/lib/nmb/live/nmb.db  (+ -wal, -shm)  ──backup──▶  /var/lib/nmb/persist/nmb.db
                                           ◀─restore── (when the box boots)
```

- Worst-case data loss on power cut: one snapshot interval (default 15 min).
- SD writes are about 96 sequential snapshot writes per day instead of thousands of small random page writes.
- `/var/log`, `/tmp`, and `/var/tmp` are tmpfs. journald uses `Storage=volatile`.
- Swap is disabled. The ext4 root uses `noatime,commit=600`.

## 3. Directory Layout

```
/opt/nmb/                     # code (read-only at runtime)
  nmb/                        # python package
    db/  netd/  probe/  speed/  report/  bot/  web/
  bin/                        # entry-point wrappers
/etc/nmb/nmb.conf             # INI config (web UI edits this)
/var/lib/nmb/live/            # tmpfs: hot SQLite DB
/var/lib/nmb/persist/         # SD: snapshots + generated reports
/var/lib/nmb/persist/reports/
/run/nmb/                     # tmpfs: pidfiles, sockets, mode state
/var/log/nmb/                 # tmpfs: logs
```

Repository layout mirrors this:
```
nmb/            python package
os/             fstab, journald, sysctl, storage scripts
systemd/        units and timers
config/         default config
docs/
```

## 4. De-Pythonization & Next-Gen Native Architecture

For resource-constrained embedded routers, OpenWrt CPEs (16MB Flash / 32MB–64MB RAM), and multi-gigabit line-rate throughput without Python runtime overhead, refer to the [De-Pythonization Architecture Blueprint](DEPYTHONIZATION_ROADMAP.md), which details the migration of all core engines and merged ecosystem components into a unified static binary (`nmbd`) in **Go** and **C11**.

For target-specific implementations on commercial router hardware (**ASUS ROG Rapture GT-AXE7800 / RT-AXE7800**, **ASUS RT-N12+**, and **TP-Link TL-WR740N v4.23**), see the [Router Porting & 100% De-Pythonization Specification](ROUTER_PORTING_AND_DEPYTHONIZATION_PLAN.md).

## 5. Telegram Bot Integration & Proactive Automation (`nmb-telegram`)

The `nmb-telegram` daemon runs alongside `nmb-web` to provide mobile chat management and proactive incident alerts without external dependencies (pure Python standard library HTTPS multipart/form-data client).

### Interactive Commands
- **📡 Diagnostics**: `/status`, `/ping`, `/test [ookla|cloudflare|rtr|iperf]`, `/report` (HTML dossier), `/ai` (Markdown bundle), `/mode`
- **🛡️ VPN Hub**:
  - `/vpn` - WireGuard & OpenVPN daemon status and client counts
  - `/vpn clients` - Connected peer roster with IP, latest handshake, and RX/TX traffic
  - `/vpn add <name> [wg|ovpn]` - Creates client peer, automatically dispatches QR code PNG image & `.conf` file
  - `/vpn qr <name>` - Generates and sends QR code image for camera scan pairing
  - `/vpn conf <name>` - Sends downloadable configuration profile
  - `/vpn start [wg|ovpn]` / `/vpn stop [wg|ovpn]` - Daemon process toggles
  - `/vpn del <name>` - Peer revocation
- **🛡️ DNS Ad-Blocker (Pi-hole Sinkhole)**:
  - `/adblock` - Queries today, blocked count, sinkhole %, Gravity domain count
  - `/adblock on` / `/adblock off` - Enable or disable DNS sinkhole
  - `/adblock block <domain>` / `/adblock unblock <domain>` - Custom domain blacklisting and whitelisting
  - `/adblock update` - Background Gravity compilation
  - `/adblock guide` - Home router DHCP DNS setup instructions
- **🩺 Self-Healing**:
  - `/heal audit` - Component health audit
  - `/heal fix [tier]` - Automated repair escalation (Tiers 1–3)
  - `/heal updates` - Verified stable release check
  - `/heal apply` - Atomic update with automatic pre-checkpoint & rollback
- **📊 Tasks & Process Load**: `/tasks` (or `/top`), `/kill <pid> [signal]`
- **📶 Wi-Fi & Guest Wi-Fi**: `/wifi` (telemetry), `/wifi scan` (nearby APs), `/wifi connect <ssid> [pw]`, `/wifi saved`
- **📦 Backups**: `/backup list`, `/backup create [label]`, `/backup send <filename>` (sends `.tar.gz` archive directly in Telegram)
- **🔧 Hardware & Power**: `/drivers`, `/reboot now`

### Proactive Background Alerting (`AlertMonitor`)
Stateful alerts with SQLite deduplication (alert table):
1. **Network Outages**: Triggers when all probe targets become unreachable; alerts on start and resolution with total outage duration.
2. **Rolling Packet Loss**: Triggers when 5-minute rolling packet loss exceeds configured threshold (e.g. 10.0%); resolves when normalized.
3. **Core Daemon Failures**: Proactively monitors `nmb-netd`, `nmb-web`, `nmb-probe`, and `nmb-scheduler`. When a service crashes, alerts the admin and triggers automated Tier 1 self-healing recovery.
4. **Hardware Thermal Overheating**: Proactively reads SoC thermal sensor (`/sys/class/thermal/thermal_zone0/temp`). Warns if temperature exceeds 82°C.
5. **Critically Low Disk Storage**: Warns if available root disk space drops below 500 MB.
6. **Dual-WAN Automatic Failover**: Alerts when primary WAN link fails and traffic fails over to secondary WAN or mobile uplink.


