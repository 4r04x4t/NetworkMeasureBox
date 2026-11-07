# Testing Record

What has been tested, where, how, and with what result. Update this file whenever a test is run again or a new one is added. The README's *Tested Status* table summarises it.

Last full sweep: 2026-11-07.

## Where the tests ran

| Name | What it is |
|---|---|
| **Box** | Raspberry Pi 4, Debian 13 (arm64), `standalone` mode, wired to the developer's router. In daily use with a 1000/300 Mbps line. |
| **VM-D13** | QEMU/KVM on an x86-64 PC, Debian 13 cloud image with the full `linux-image-amd64` kernel. Two NICs (user-mode NAT as WAN, a socket link as LAN). Wi-Fi with `mac80211_hwsim` (three simulated radios); clients in network namespaces. |
| **VM-distro** | Clean QEMU/KVM VMs of Debian 13, Debian 12, Ubuntu 24.04 LTS and Alpine 3.20 (x86-64), each installed from scratch with `setup.sh`. |
| **Unit tests** | `python3 -m unittest discover tests` (223 tests) on the developer PC and, as root, inside VM-D13. |

Simulated means: real Linux, real `hostapd`, `dnsmasq`, `pppd`, WireGuard and OpenVPN, but virtual NICs and radios. Timing, drivers and radio behaviour of real hardware are not covered.

## Results

Legend: ✅ works · ⚠️ works with a limit · ❌ fails · — not tested

### Operating systems (VM-distro)

| System | Clean install | Reinstall | Reboot | Notes |
|---|---|---|---|---|
| Debian 13 | ✅ | ✅ | ✅ | Also the base of VM-D13 |
| Debian 12 (Python 3.11) | ✅ | ✅ | — | Real speed test passed. Polkit rule verified: `nmb` may restart `nmb-netd`, not `ssh` |
| Ubuntu 24.04 LTS | ✅ | — | — | Needed interface auto-detection (`ens3` instead of `eth0`), fixed |
| Ubuntu 22.04 LTS (Python 3.10, polkit 0.105) | ✅ | ✅ | ✅ | Needed the old polkit's `.pkla` rule, added; there `nmb` may manage any unit. Scheduled Ookla tests ran |
| Alpine 3.20 (OpenRC) | ✅ | ✅ | ✅ | Needed port 80 capability, RMBT build and OpenRC restart fixes |
| Raspberry Pi 4, Debian 13 | ✅ | ✅ | ✅ | The Box |
| Fedora 45 (Python 3.15, SELinux enforcing) | ✅ | — | — | New `dnf` branch. All services, polkit, all optional packages; RTR and Cloudflare measured, the Ookla CLI ran (refused by Ookla's rate limit, shared IP). No SELinux denials. Reboot not checked |
| AlmaLinux 10.2 (for RHEL 10; Python 3.12, SELinux enforcing) | ✅ | ✅ | ✅ | Needs EPEL (enabled by `setup.sh`). Fixed: rebuilds list "fedora" in `ID_LIKE`, so EPEL was skipped; `sudo` there does not search `/usr/local/bin`. Update check counts `dnf` updates. The image needs a SCSI disk in QEMU |
| Raspberry Pi OS, Arch, 32-bit | — | — | — | Not tested |

### Measurement

| Feature | Where | Result | How |
|---|---|---|---|
| Ookla | Box | ⚠️ | Works hourly. Every minute, Ookla refuses the box ("Limit reached"); the box then pauses Ookla (30 min, up to 4 h) and measures with RTR-NetTest, stored under RTR's own name |
| RTR-NetTest | Box, VM-distro | ✅ | ~910/320 Mbps on the 1000/300 line |
| Cloudflare | Box | ✅ | |
| iPerf3 | Box, VM-D13 | ✅ | |
| Ping probe, outages | Box | ✅ | Continuous since install |
| Schedule, daily data limit | Box, unit tests | ✅ | |
| Port check (22, 5060, 6881, …) | Box | ✅ | |
| Traffic stop (experimental) | Box, VM-D13 | ✅ | Aborts on 23–40 Mbps of other traffic; off by default |
| DNS interception, NAT type | Box | ✅ | No interception; endpoint-independent NAT |

### Network modes (VM-D13)

| Feature | Result | How |
|---|---|---|
| Mode A router: DHCP, NAT, internet for LAN clients | ✅ | Client in a namespace got an address, pinged the internet, loaded HTTPS |
| Mode B bridge | ✅ | Box gets its own address on the bridge |
| DMZ isolation | ✅ | DMZ reaches the internet, not the LAN or the Web UI |
| PPPoE dial-in and redial | ⚠️ | Against `pppoe-server`; the box's own traffic used `ppp0`. A LAN client's full round trip could not be checked because of the simulation's own NAT |
| DHCP after a box restart | ✅ | Fixed: `dhcp-authoritative`, so a client renewing an old lease gets it at once |
| Real hardware, Nighthawk M6 Pro | — | Planned by the developer |

### Wi-Fi access point (VM-D13, simulated radios)

| Case | Result | How |
|---|---|---|
| WPA2, 2.4 GHz | ✅ | Client connected, got DHCP, reached the internet, HTTPS and the Web UI |
| WPA2, 5 GHz (ch 36) | ✅ | Same checks. Needs `wireless-regdb` (now installed by `setup.sh`) |
| 5 GHz without `wireless-regdb` | ✅ | The box falls back to 2.4 GHz instead of having no Wi-Fi |
| WPA3 (SAE), 2.4 GHz | ✅ | Same checks as WPA2 |
| Wrong password | ✅ | No address, no traffic |
| Wi-Fi 7 / 6 GHz / 160–320 MHz | ⚠️ | Debian 13's `hostapd` rejects the Wi-Fi 7 settings; the box steps down to Wi-Fi 6 |
| Real Wi-Fi hardware | — | |

### Guest Wi-Fi client (the box joins another Wi-Fi network; VM-D13)

| Case | Result | How |
|---|---|---|
| Scan, connect, DHCP, ping | ✅ | Against a `hostapd` network in a namespace, through the Web UI API |
| Wrong password | ✅ | Error shows NetworkManager's real message |
| Reconnect, disconnect, saved profile | ✅ | Fixed: a stale profile no longer blocks reconnecting; "disconnected" is no longer reported as connected |
| Permission as the `nmb` user | ✅ | Fixed in the polkit rule. On the Box the old rule is still installed, see *Open* |
| Without NetworkManager | ❌ by design | The feature needs NetworkManager (`nmcli`); `setup.sh` does not install it |

### VPN and remote access (VM-D13)

| Feature | Result | How |
|---|---|---|
| WireGuard server | ✅ | Peer added in the Web UI, its config used by a client in a namespace: tunnel, internet, HTTPS and Web UI through the tunnel; peer delete and stop |
| OpenVPN server | ✅ | Fixed: the server certificate lacked TLS server usage, so every client was rejected. Old certificates are reissued from the same CA. Client profile tested end to end |
| HTTPS/CONNECT proxy | ✅ | Fixed: 20 s delay on networks with broken IPv6 (now 0.4 s), stop did not free the port, and the proxy reached the box's own loopback services (now refused) |
| DuckDNS | ⚠️ | A wrong token is rejected and shown. A real account was not used |
| Tailscale | — | Needs an account |

### Other features

| Feature | Where | Result | How |
|---|---|---|---|
| DNS ad blocker under load | VM-D13 | ✅ | 3000 queries from 50 threads: all answered, 6900/s, p99 72 ms, 24 MB RAM |
| Self-update with rollback | VM-D13 | ✅ | `/opt/nmb` as a Git checkout with a local origin. A good commit was applied; a commit with a failing test was rolled back. Fixed: three tests depended on the machine, so on a real box every update was rolled back; `--json` output was not pure JSON |
| Web UI, settings save and reload | Box, VM-distro | ✅ | |
| Results without password (`public_results`) | Box, local instance, unit tests | ✅ | Off on the Box: `/results` gives 401. On: `/results`, the report and the CSV files open from the LAN without login; `/`, `/api/config`, `/api/status` and every POST still give 401; turning it off in the Web UI is saved |
| Ookla schedule warning | Box, unit tests | ✅ | The Box (all engines every minute) reports `ookla_rate_limit_risk`; hourly or RTR-only gives none |
| Factory reset | VM-D13 (earlier sweep), unit tests | ✅ | Needs `--yes` |
| `nmb-cli` TUI | Box, unit tests | ✅ | |
| Security: firewall guard, web server as `nmb`, secrets on the boot partition | VM-distro, Box | ✅ | |
| Kernel network tuning | Box, VM-distro | ✅ | Done by `nmb-netd` (root) |
| Telegram bot and alerts | Unit tests | ⚠️ | Not against a real bot |
| SMTP, OONI, drive swap | — | — | |
| 512 MB RAM devices | — | — | |

## Candidates

### Operating systems

Found by checking what `setup.sh` detects and what the code needs (Python 3.10 or newer at run time, standard library only, systemd with nftables, or Alpine with OpenRC).

| System | Expected | Why | How to test |
|---|---|---|---|
| Ubuntu 26.04 LTS | Should work | Debian-based, current polkit | Cloud image VM, like Ubuntu 24.04 |
| Raspberry Pi OS (arm64), Lite | Should work | Debian 13 based, like the Box | On a Pi, or Debian arm64 under QEMU |
| Raspberry Pi OS (armhf, 32-bit) | Unknown | The Ookla and RMBT builds have only been run on arm64 and x86-64 | On a Pi 2/3/Zero 2 |
| Armbian, DietPi | Should work | Debian-based images for other single-board computers | On the board, or their x86 images |
| Linux Mint 22, Pop!_OS | Should work | Ubuntu 24.04 based; desktop NetworkManager may claim the ports | VM |
| Alpine 3.21 / 3.22 | Should work | Same OpenRC path as 3.20 | Cloud image VM |
| Devuan | Refused | No systemd; `setup.sh` now stops with a clear message | — |
| Rocky Linux 10, CentOS Stream 10 | Should work | Same `dnf` and EPEL path as AlmaLinux 10 | Cloud image VM |
| Arch, Manjaro, openSUSE, Void, NixOS | Not supported | Other package managers or init systems | Needs a port |
| OpenWrt | Not supported | Planned in the native rewrite, see `ROUTER_PORTING_AND_DEPYTHONIZATION_PLAN.md` | — |

### Features and situations not yet tested

Can be done in VMs:

- **Low memory:** a 512 MB and a 1 GB VM, all services on, for 24 hours; watch memory and OOM kills.
- **Long run:** 24–72 hours with per-minute tests; memory growth, database size, log rotation.
- **Power loss:** kill the VM during a speed test and during the 15-minute snapshot; check the database and config after boot.
- **Backup and restore:** create, download, restore on a fresh install, restore an old-version backup.
- **Upgrade from an older release:** install 2.4.0, then update to the current version with its config kept.
- **WAN failover and multi-WAN load balancing:** two WAN NICs, pull one.
- **VLAN, link aggregation, passthrough:** with a simulated switch (Linux bridge with VLAN filtering, a bonded peer).
- **Hostile networks:** IPv6-only WAN, CGNAT, broken DNS, a captive portal, a flapping link, a clock jump (Pi has no clock battery).
- **Telegram and SMTP** against local mock servers.
- **Traceroute, packet sniffer, OONI, report generation, driver installer.**
- **Web UI:** the five languages complete, several users at once, repeated wrong logins, and Firefox, Chrome and a phone browser.

Needs hardware or accounts:

- Real Wi-Fi radios (2.4/5/6 GHz, Wi-Fi 6/7), a real PPPoE line, the Nighthawk M6 Pro, a USB Ethernet adapter, a Pi 5.
- Tailscale, a real DuckDNS domain, a real Telegram bot.

## Open

- **The Box still has the old polkit rule.** Guest Wi-Fi from the Web UI fails there with "network-control: auth" until the new `os/90-nmb.rules` is installed (re-run `setup.sh`, or copy it to `/etc/polkit-1/rules.d/`).
- Not tested: opening ports in firewalld (it was not running on the Fedora and AlmaLinux cloud images).
- Not tested: Ubuntu reinstall and reboot, Debian 12 reboot, Tailscale, a real Telegram bot, SMTP, OONI, real Wi-Fi and PPPoE hardware.

## Re-running

- Unit tests: `python3 -m unittest discover tests` (about 3 minutes).
- The VM scripts used for these runs are not part of the repository; each row above says what was set up.
