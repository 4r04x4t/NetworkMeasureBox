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
| Alpine 3.20 (OpenRC) | ✅ | ✅ | ✅ | Needed port 80 capability, RMBT build and OpenRC restart fixes |
| Raspberry Pi 4, Debian 13 | ✅ | ✅ | ✅ | The Box |
| Raspberry Pi OS, Fedora, Arch, 32-bit | — | — | — | Not tested; `setup.sh` supports only Debian-based systems and Alpine |

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
| Factory reset | VM-D13 (earlier sweep), unit tests | ✅ | Needs `--yes` |
| `nmb-cli` TUI | Box, unit tests | ✅ | |
| Security: firewall guard, web server as `nmb`, secrets on the boot partition | VM-distro, Box | ✅ | |
| Kernel network tuning | Box, VM-distro | ✅ | Done by `nmb-netd` (root) |
| Telegram bot and alerts | Unit tests | ⚠️ | Not against a real bot |
| SMTP, OONI, drive swap | — | — | |
| 512 MB RAM devices | — | — | |

## Open

- **The Box still has the old polkit rule.** Guest Wi-Fi from the Web UI fails there with "network-control: auth" until the new `os/90-nmb.rules` is installed (re-run `setup.sh`, or copy it to `/etc/polkit-1/rules.d/`).
- Not tested: Ubuntu reinstall and reboot, Debian 12 reboot, Tailscale, a real Telegram bot, SMTP, OONI, real Wi-Fi and PPPoE hardware.

## Re-running

- Unit tests: `python3 -m unittest discover tests` (about 3 minutes).
- The VM scripts used for these runs are not part of the repository; each row above says what was set up.
