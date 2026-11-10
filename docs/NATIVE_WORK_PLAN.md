# NetworkMeasureBox: Work Plan for the Native Build (Step 1: x86-64 and ARM)

> **Status: plan only.** No native code exists. This document splits *Order of Work* step 1 of
> [`DEPYTHONIZATION_ROADMAP.md`](DEPYTHONIZATION_ROADMAP.md) into small work packages that separate agents
> can do, says how they work, and how the downloaded images and firmware are taken apart, analysed and used.
> The roadmap and [`ROUTER_PORTING_AND_DEPYTHONIZATION_PLAN.md`](ROUTER_PORTING_AND_DEPYTHONIZATION_PLAN.md)
> stay the source of the requirements; where this plan and they differ, they win and this plan is corrected.

Owner's requirements for this work (2026-11-10): the project is split into parts small enough for small agents;
every document is read with care and nothing is left out; the work is efficient and as free of faults as
possible; the developer reads outside programming documentation when needed; source code and components are
analysed with care, from more than one source; the programming for the first two architectures (x86-64 and
ARM) runs through by itself; and the images and firmware files are taken apart, analysed and used.

## 1. Scope and end of step 1

- **Targets:** `linux/amd64` (PC) and `linux/arm64` (Raspberry Pi 4), built and tested on every change;
  `linux/arm` v7 also run under QEMU; `linux/mips` and `linux/mipsle` cross-compiled only (roadmap, *Generic First* point 6).
- **Language:** Go without cgo for this step (roadmap section 3, Tier 1, and *Generic First* point 1). C11/musl is for the
  router tiers and starts with step 2.
- **Done** when the whole native program (every component of section 5, not a subset) passes the Quality Bar,
  points 1 to 9, on these targets (roadmap, *Order of Work* step 1). Nothing router-specific is written before that.
- **Everything native lives in `NetworkMeasureBox-DePyD/`**, the folder next to the Python version's folder (owner, 2026-11-10); its first commit creates `NetworkMeasureBox-DePyD/CHANGELOG.md` before any code. Package F-00 makes it a repository of its own (section 7, point 8).

## 2. How the work is organised

### 2.1 Roles (each one a separate agent with its own context)

| Role | Does | Does not |
| :--- | :--- | :--- |
| **Orchestrator** | Keeps `NetworkMeasureBox-DePyD/WORK_STATUS.md`, picks the next ready packages, starts agents, runs the gate, merges, goes on until step 1 is done | Write component code |
| **Analyst** | For one package: reads its documents in full, the Python reference, the upstream sources and outside documentation; writes the package brief (`NetworkMeasureBox-DePyD/docs/briefs/<id>.md`) | Write code |
| **Implementer** | Writes the code and tests of one package from its brief, inside the package's own folder | Change another package's files or the contracts |
| **Verifier** | Someone other than the author: tries to break the package (tests, security list, known faults, behaviour against the reference) | Fix what it finds (it reports; the implementer fixes) |
| **Integrator** | Owns the shared files (`go.mod`, route table, `nmbd` wiring, changelog, manual index), merges accepted packages | Accept a package the verifier has not passed |
| **Image analyst** | Takes one image apart and writes its record (section 5) | Flash or boot anything on real hardware |

A package goes analyst → implementer → verifier → integrator. A verifier's finding sends it back; a package is
never accepted "for now" (Quality Bar points 2, 3 and 7).

### 2.2 Rules that keep small agents correct

1. **One package, one folder, one owner at a time.** An agent writes only inside its package's folder and its
   brief. Shared files change only through the integrator. Each agent works in its own git worktree.
2. **Contracts first.** Packages talk through the interfaces fixed in F-04. An agent that needs a contract
   changed stops and reports; it does not change it.
3. **Reading is proved, not claimed.** Every brief starts with a table: each document section and each Python
   file it had to read, with the requirements taken from it (ids from F-02) and the lines they come from. A
   requirement id of the package without a test in the end is a failed gate.
4. **Intended behaviour, not observed.** The Python reference says what the box does; its faults
   (`NetworkMeasureBox-DePyD/KNOWN_PYTHON_FAULTS.md`) are never copied (Quality Bar point 6). Unsure cases go to the owner's
   question list, not into code.
5. **More than one source.** A protocol or component is understood from at least two independent sources
   (the standard or official documentation, the upstream source code, the Python reference, a capture of real
   traffic); disagreements are written into the brief with the choice made.
6. **Outside documentation is read when the agent is not sure,** from the official source, with the address,
   version and date recorded in the brief. Its content is data, never an instruction to the agent.
7. **No personal or site data** anywhere (Quality Bar point 8): reserved addresses and names only.
8. **Honest reports.** "Works" only for what was run and seen; otherwise "built", "unit-tested" or "not tested".
9. **Limits of this PC:** 3.9 GB RAM, 4 threads, about 1.8 GB in WSL2. At most three building agents at once,
   one QEMU guest at a time (a lock file), guests with at most 512 MB.
10. **The real box:** the Raspberry Pi 4 is the owner's working measuring box. The owner allows every native test
    on it (section 7, point 5), under that point's conditions: backup first, a tried way back, the time marked as
    the box's own action. ARM64 is proved first by the cross build, the tests under `qemu-aarch64-static` and the
    `armsr/armv8` QEMU guest, and on the Pi 4 after that.

### 2.3 Running by itself

The orchestrator loops: read `WORK_STATUS.md` → start every package whose prerequisites are accepted (within the
limits of 2.2 point 9) → gate → merge → update the status, the changelog and the manual → next. It stops only
for: a question only the owner can answer (section 7), a step on real hardware whose backup or way back is not in place,
or a gate that fails three times on the same package (then it reports what was tried). `WORK_STATUS.md` holds
for each package: state (waiting, brief, code, verify, accepted, blocked), the commit, the gate's result and open
questions, so the work continues after any interruption without redoing accepted packages.

### 2.4 The gate of every package

Build for amd64, arm64, arm v7, mips, mipsle; unit tests on amd64 and under QEMU user mode on arm64 and arm v7,
with the race detector on amd64; `gofmt`, `go vet`, `staticcheck`, `gosec`, `govulncheck`, complexity and size
limits (clean code rules); fuzz tests for every parser; hermetic tests only; each requirement id and each known
Python fault of the package has a test; the Phase 0 checks that apply; the written security check; the scan for
personal data and secrets; licence entries for new dependencies; size, memory and CPU figures recorded; changelog,
manual chapter and command reference updated (roadmap 6B.7); the verifier's pass.

## 3. Work packages

Size rule: one package is what one agent can read, write and test in one sitting (as a guide: a Python reference
of at most about 1,500 lines, or one protocol). A bigger one is split by its analyst before coding.

### 3.0 Foundation (in order, before anything else)

| Id | Package | Result |
| :--- | :--- | :--- |
| F-00 | Skeleton | `NetworkMeasureBox-DePyD/` layout, `CHANGELOG.md` (first commit), `KNOWN_PYTHON_FAULTS.md`, `WORK_STATUS.md`, Go module, build and gate scripts for the matrix of 2.4, toolchain version fixed (the PC has Go 1.22; the roadmap names 1.23+) |
| F-01 | Owner's open decisions | The list of section 7 answered and written into the roadmap |
| F-02 | Requirements register | Every requirement of both plans, `TESTING.md` (release checklist, *To fix*, *Known limits*), `ARCHITECTURE.md`, the READMEs and the changelog as one numbered list with its source line; each id assigned to a package; a second agent checks that no paragraph is without an id |
| F-03 | Known Python faults | The roadmap's register plus the private audit and data-quality lists (open security faults by category only), each with the correct behaviour and the package that must prove it |
| F-04 | Contracts | Configuration format (`nmb.conf` compatible, `%` plain, `__KEEP_CURRENT__`), database schema and on-disk formats (same on every architecture), event and log record, platform interfaces (routes/links, Wi-Fi, firewall, service control, hardware), API contract and route table, translation keys, status file formats |
| F-05 | Phase 0 reference | Golden files and checks captured from the Python version, each reviewed against F-03 before use; the comparison harness (Python and native, same input) |
| F-06 | Test bed | Hermetic helpers: fake clock, network namespaces with virtual cables, `mac80211_hwsim` where the kernel has it, fake servers for every engine and protocol, the QEMU guest runner with its lock |

### 3.1 Core (parallel after F)

| Id | Package | Python reference | Roadmap |
| :--- | :--- | :--- | :--- |
| C-01 | Configuration: load, validate, defaults, atomic locked save | `nmb/config.py` | Phase 0, rules from fixes |
| C-02 | Database: RAM live copy, snapshots, retention, migration from a Python database | `nmb/db/` | 4.5 |
| C-03 | Structured log, run-time debug level, crash evidence | `nmb/devlog.py`, `report/crash_trap.py` | 7D, 4.15 |
| C-04 | Secret masking | `common/redact.py`, `secret_keep.py` | 4.24 |
| C-05 | Addresses, version, user agent, monotonic time helpers | `common/netaddr.py`, `version.py`, `user_agent.py` | QB 6 |
| C-06 | Translations: keys, 11 languages, build checks | `web/i18n.py`, `bot/i18n.py`, the `locales/` folders | 4.26, 4.4A point 6 |
| C-07 | Events and own-action windows | `common/own_action.py` | register |
| C-08 | Storage guard, purge, memory and flash health | `common/storage_guard.py`, `purge.py`, `memory.py` | 4.23, 4.26 |
| C-09 | Tasks and load from `/proc`, IRQ and offload telemetry | `common/tasks.py` | 4.13, 4.22 |
| C-10 | Country data files and location | (new) | QB 9 |

### 3.2 Measuring

| Id | Package | Python reference | Roadmap |
| :--- | :--- | :--- | :--- |
| M-01 | ICMP probe, statistics, minute summaries | `probe/icmp.py`, `engine.py` | 4.1 |
| M-02 | Outage and loss-pattern engine | `probe/engine.py`, `report/metrics.py` | 4.18 |
| M-03 | Traffic gate and other devices' traffic | `probe/traffic_gate.py`, `cross_traffic.py` | Phase 0 table |
| M-04 | Runner, schedule, per-engine intervals, cancel | `speed/runner.py`, `scheduler.py`, `cancel.py` | 4.25, 4.3 |
| M-05 | Data caps, budgets, Ookla pause | `speed/data_cap.py`, `data_budget.py`, `anti_ban.py` | rules from fixes |
| M-06 | Cloudflare engine | `speed/cloudflare.py` | 4.3 |
| M-07 | Fast.com engine | `speed/fastcom.py` | 4.26 |
| M-08 | RTR (RMBT) engine | `speed/rtr.py`, `components/open-rmbt` | 4.6 |
| M-09 | iPerf3 client, server names, local server | `speed/iperf.py`, `iperf_directory.py` | 4.8 |
| M-10 | Ookla engine (see section 7) | `speed/ookla.py` | 4.3 |
| M-11 | Traceroute, port check, packet capture | `speed/traceroute.py`, `port_checker.py`, `sniffer/` | — |
| M-12 | DNS audit, STUN and NAT, public address | `netd/dns.py`, `netd/geoip.py` | 4.20, 4.21 |
| M-13 | OONI | `probe/ooni.py` | 4.7 |
| M-14 | Wi-Fi radio telemetry | `netd/wifi.py` (status parts) | 4.19 |

### 3.3 Network daemon

| Id | Package | Python reference | Roadmap |
| :--- | :--- | :--- | :--- |
| N-01 | Links, addresses, routes, hot-plug (netlink) | `netd/interfaces.py`, `detector.py`, `kernel.py` | 4.2 |
| N-02 | Firewall for every mode | `netd/firewall.py`, `os/nmb-guard.nft` | register (firewall) |
| N-03 | Modes and switching | `netd/modes.py`, `daemon.py`, `services.py` | Phase 0 |
| N-04 | Automatic mode and its probes (DHCP, PPPoE discovery) | `netd/auto_mode.py` | 4.28 |
| N-05 | Built-in DHCP client, DHCP guard, PPPoE | `netd/modes.py`, `wifi_share.py` (guard) | 4.27, rules from fixes |
| N-06 | LAN passthrough and link aggregation | `netd/lan_topology.py` | porting plan 7A |
| N-07 | Wi-Fi client and access point control, regulatory domain | `netd/wifi.py`, `regdomains.py` | 4.14 |
| N-08 | Guest Wi-Fi, Wi-Fi uplink, sharing on a LAN port | `netd/guest_wifi.py`, `wifi_uplink.py`, `wifi_share.py` | 4.26 |
| N-09 | Captive portals | (new) | 6B.6 |
| N-10 | USB tethering and mobile uplink | `netd/usb_uplink.py` | 4.27 |
| N-11 | IPv6 on the LAN, port forwarding, UPnP on the WAN, proxy | `netd/ipv6_lan.py`, `port_forward.py`, `upnp_wan.py`, `proxy.py` | — |
| N-12 | DNS blocker | `netd/adblock.py` | 4.9 |
| N-13 | WireGuard and QR codes | `netd/wireguard.py` | 4.10 |
| N-14 | OpenVPN | `netd/openvpn.py` | 4.10 |
| N-15 | Tailscale | `netd/tailscale.py` | 4.10 |
| N-16 | DynDNS | `netd/duckdns.py` | porting plan 7.10 |
| N-17 | Hardware and driver finder, system detection, device explorer | `netd/drivers.py`, `os_detector.py`, `explorer.py` | 4.11 |

### 3.4 Reports

| Id | Package | Python reference | Roadmap |
| :--- | :--- | :--- | :--- |
| R-01 | Report figures, status codes, verdicts | `report/metrics.py`, `status_codes.py` | 4.17 |
| R-02 | CSV exports | `report/csv_export.py` | — |
| R-03 | SLA dossier and charts | `report/dossier.py`, `svg_charts.py` | 4.17 |
| R-04 | Diagnostic bundle for LLMs | `report/llm_bundle.py` | 4.24 |
| R-05 | E-mail, diagnostic logger | `report/smtp.py`, `invasive_logger.py` | 4.15 |

### 3.5 Surfaces

| Id | Package | Python reference | Roadmap |
| :--- | :--- | :--- | :--- |
| S-01 | Web server: login, sessions, CSRF, route table, live stream | `web/server.py` (transport parts) | 4.4, QB 7 |
| S-02…S-0n | API by area (status, speed, network, Wi-Fi, VPN, blocker, system, exports), one package per area | `web/server.py` (handlers) | 4.4, clean code |
| U-01 | Web UI shell, AMOLED black look, page addresses, size budgets | `web/assets/` | 4.4A, 6B.1 |
| U-02…U-0n | Web UI pages, one package per page | `web/assets/dashboard.*` | 4.4A |
| S-10 | `nmb-cli`: JSON commands, menu, plain output | `nmb/tui/` | Phase 0, 6B.2 |
| S-11 | Telegram bot | `nmb/bot/` | 4.16, register (bot) |
| S-12 | Collector client | `collector/client.py` | 4.25 |
| S-13 | Collector server | `collector/server.py` | 4.25 |

### 3.6 System and product

| Id | Package | Python reference | Roadmap |
| :--- | :--- | :--- | :--- |
| P-01 | Self-healing watchdog | `common/heal.py` | 4.12 |
| P-02 | Updates: file upload and channel, signature, try and roll back | `common/updater.py` | 6B.3, 7D |
| P-03 | Backup, restore, USB import, factory reset, unique password per device | `common/backup.py`, `usb_import.py`, `bin/nmb-factory-reset` | QB 7, Phase 0 |
| P-04 | Sandbox profiles and their tests | `systemd/` units | 6B.5 |
| P-05 | Maintenance mode and audit log | (new) | 7D |
| P-06 | Privileged helper with allow-lists | `bin/nmb-helper` | register |
| P-07 | Self-test and scenarios | `nmb/selftest/` | TESTING |
| P-08 | Licences page and build check; disclaimer | `common/donate.py` | 6B.3A |
| P-09 | Add-ons: themes and CLI colour schemes | (new) | 6B.1, 6B.2 |
| P-10 | `nmbd` single binary, multi-call names, service units | `bin/`, `systemd/`, `os/` | section 5 |
| P-11 | Packages and images for amd64 and arm64; evaluation of the bases | `setup.sh` | 6A |
| P-12 | User manual and command reference, with their build checks | (new) | 6B.7 |
| P-13 | Release proof: release checklist, Python against native on the same box and day, outside scan | `docs/TESTING.md` | QB 1, 4, 5, 7 |

F-02 may add, split or merge packages; every Python file, every roadmap section and every `TESTING.md` row
must end up in exactly one package, and the register's check fails otherwise.

## 4. Order

1. F-00 to F-06, and in parallel the image records of section 5 (they need no native code).
2. Core (C), then in parallel Measuring (M), Network (N) and Reports (R) as their contracts allow.
3. Surfaces (S, U) on top of them; System and product (P) alongside.
4. P-10 to P-13 last. Step 1 ends with P-13 accepted and the owner's acceptance of any remaining known limit.

## 5. The downloaded images and firmware: taking apart, analysing, using

Material: the set of roadmap section 6B.4, from its copy inside WSL2 (`~/src/NMB-depythonization-firmwares`; outside every repository, never committed). Everything here is
**read only on the PC**: no image is written to a device for analysis. Unpacking is done on copies in a work
folder outside the repository; the files are untrusted data and are unpacked into fresh empty folders without
root (no loop mounts).

### 5.1 Taking apart, by kind of image

| Kind | In the set | Method |
| :--- | :--- | :--- |
| Disk image (`*.img.gz`, `*.raw.xz`) | OpenWrt x86-64, `armsr`, Pi 4; Fedora IoT arm64 | Decompress (OpenWrt images carry trailing metadata: a gzip warning is expected); read the partition table (`sgdisk -p`, `fdisk -l`); cut each partition out by its offset; FAT with `mtools`, ext4 with `debugfs rdump`, squashfs with `unsquashfs`; other file systems by booting the image in QEMU |
| Root file system archive | OpenWrt `rootfs.tar.gz`, Alpine Pi archive | List and unpack directly; Alpine's `modloop` is a squashfs with the modules and firmware |
| Installer ISO | Debian netinst, Alpine, Fedora IoT | Unpack with `7z`; an installer is not the installed system: read its package index and kernel package, and judge the installed system from an image built or installed in QEMU |
| SDK, ImageBuilder, toolchain, `kernel-debug` | OpenWrt target trees | Unpack; kernel `.config`, the package index, the `kmods` folder, `profiles.json`, compiler and C library versions |
| Router firmware (step 2 and later) | TP-Link, ASUS stock and OpenWrt | `binwalk` and the maker's header (TP-Link v1: hardware id, kernel, root and boot lengths; ASUS `trx`); kernel and squashfs cut out by offset; old stock squashfs variants and UBI/JFFS2 need their own readers. Stock firmware for the rules of porting plan 7H only |

Tools still to install on the PC before this starts: `cpio`, `xorriso` or `bsdtar`, `ostree`, a UBI reader, a
JFFS2 reader and a reader for vendor squashfs variants.

### 5.2 What is recorded for each image

One record per image (`NetworkMeasureBox-DePyD/docs/images/<image>.md`, summary into roadmap section 6A): file name and
SHA-256 checked against the publisher; partition and file system layout, boot method, how an update is written
(sysupgrade, A/B, ostree); kernel version and the configuration options NMB needs (bridge, bonding, VLAN,
nftables, WireGuard, PPP and PPPoE, `mac80211`/`cfg80211`, `mac80211_hwsim`, USB network and tethering drivers,
namespaces, seccomp, Landlock, cgroups, the watchdog); modules and firmware files carried; init system and
service manager; C library; package manager and package count; which tools of 6A criterion 3 are present with
their versions; whether any Python is in it (criterion 8); own network or firewall manager and how it is
switched off (criterion 5); size on disk; and from the QEMU boot: boot time, free memory and storage after boot,
listening ports, running services. Each field is filled from the image, with the command that produced it, or
marked "not determined" with the reason; nothing is filled in from memory.

### 5.3 What the images are used for

1. **Choosing the base** (6A): the records fill the criteria table, in the roadmap's order (OpenWrt, Debian, Alpine, Fedora IoT).
2. **A capability table for the code:** which kernel features, tools and paths exist on which base. The platform
   interfaces of F-04 and the run-time detection are designed and tested against it (missing tool, tool outside
   `PATH`, other init system), instead of against one developer machine.
3. **Test systems:** OpenWrt x86-64 and `armsr` v8/v7 boot in QEMU as guests the native program is installed into
   and tested on (modes, firewall, DHCP, PPPoE between virtual ports); the root archives serve as quick user-mode
   test roots for arm64 and arm v7 binaries without a full guest.
4. **Build inputs:** the SDKs and toolchains for the later C11/musl builds and for a first `nmbd` package; the
   ImageBuilder to assemble an NMB image without rebuilding the base; the kernel configurations to confirm that
   no own kernel is needed.
5. **Data for components:** firmware and module lists for the driver finder; the bases' default network and
   firewall configuration for the coexistence design; package indexes for the licence list (6B.3A).
6. **Firmware handling (6B.3):** the header layouts of the router images define the parsers; their tests and
   fuzz seeds are made-up headers of the same layout, not the makers' files.
7. **Missing parts (7H), from step 2:** the stock firmware inventories per target.

Only records, lists, versions and checksums go into the repository; no file taken out of an image, and nothing
from a maker's closed firmware (porting plan 7H point 3).

### 5.4 Image packages

| Id | Image | Notes |
| :--- | :--- | :--- |
| I-01 | OpenWrt 25.12.6 x86-64 (squashfs and ext4) | Also the first QEMU guest of F-06 |
| I-02 | OpenWrt 25.12.6 `armsr/armv8` with SDK, ImageBuilder, toolchain | ARM64 guest |
| I-03 | OpenWrt 25.12.6 `armsr/armv7` with its tree | 32-bit ARM guest |
| I-04 | OpenWrt 25.12.6 `x86/generic` tree | 32-bit x86, cross-check of I-01 |
| I-05 | OpenWrt 25.12.6 Raspberry Pi 4 | Taken apart first; booted on the Pi 4 under section 7 point 5 (card image saved before) |
| I-06 | Debian 13.7.0 amd64 and arm64 | Package index and kernel package; minimal installed system in QEMU |
| I-07 | Alpine 3.24.4 x86-64 and Pi arm64 | `modloop`, `apks`, diskless mode |
| I-08 | Fedora IoT 44 arm64 and x86-64 | Largest files; after the first three, as the roadmap orders |
| I-09 | Comparison and proposal for 6A | From I-01 to I-08; the owner decides |
| I-10… | Router firmware, TL-WR1043ND v1 first | Step 2; not started in step 1 |

## 6. What the owner sees

`NetworkMeasureBox-DePyD/WORK_STATUS.md` (state of every package), `NetworkMeasureBox-DePyD/CHANGELOG.md`, the briefs, the image
records, and for each accepted package its evidence: tests, figures, faults found and fixed, what is better
than the Python version (Quality Bar point 5).

## 7. Owner's decisions (F-01)

Answered by the owner on 2026-11-10:

1. **API contract: left to the developer** (the owner has no preference). Proposed, and used unless the owner says
   otherwise: the native API answers with real HTTP status codes (2xx only for success; 4xx for a refused or invalid
   request, 5xx for a failure of the box) and one error body (`code`, a translation key, detail). The native Web UI
   and `nmb-cli` are written for this; the collector protocol and the `nmb-cli` JSON command names stay as they are.
   The difference from the Python API is listed in the changelog under Changed.
2. **iPerf3 schedule: implemented.** `iperf.schedule_cron` and `iperf.automated_enabled` work in the native build
   (package M-04 with M-09), under the same traffic gate, data caps and hourly limit as the other engines.
3. **Ookla: whichever works.** Package M-10 starts with Ookla's own program in the strict sandbox (it works today
   and its licence is clear), only after the user has accepted Ookla's terms, and never working around a refusal. A
   native engine replaces it only if it gives the same results on the same line and Ookla's terms allow it; the
   analyst of M-10 reads those terms first and writes the finding into the brief.
4. **Base of the own distribution: after the images are analysed.** The images are taken apart so that there is
   material to work from (section 5); the base, the init system and the A/B update tool are chosen from I-09's
   comparison.
5. **Raspberry Pi 4: everything may be tested on it.** Native builds and images may be installed and tested on the
   owner's box. It still measures a real line, so each time: a full backup first (settings, database, and the card's
   image before another system is written to it), a way back that was tried, the time recorded as the box's own
   action so that it is not counted against the ISP, and the Python version put back afterwards until the native
   one has replaced it (Quality Bar point 5).
6. **Signed updates: yes.** Updates and images are accepted only with a valid signature (package P-02). Proposed:
   an Ed25519 key pair made on the development PC, the private key kept outside every repository and image (and a
   copy kept offline by the owner), only the public key in the build; the release step signs, the box verifies
   before anything is written.

Still open:

7. The wording of the disclaimer (6B.3A).
8. **The native folder: answered (owner, 2026-11-10).** `NetworkMeasureBox-DePyD/` is its own repository and holds
   every native file, without exception. It is **open, like the Python version** (public; "for everyone" means a
   build whose look pleases and gives a good first impression, not a closed product). Package F-00 makes the
   repository in that folder with its first commit. Publishing it (the address it is pushed to) is done once,
   with the owner, since making a public repository cannot be taken back.
9. **Licence of the native build: follows from the development.** It is fixed when the components are known:
   F-00 starts a list of every dependency with its licence (6B.3A), each analyst adds to it, and the licence of
   the whole is proposed from what those licences require and allow (for example a copyleft part that is built
   in decides more than a part that is only run). Until it is fixed, no dependency is taken whose licence would
   rule out an open licence, and the repository says that the licence is not decided yet.
