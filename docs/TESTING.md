# Testing Record

What has been tested, where, how, and with what result. Update this file whenever a test is run again or a new one is added. The README's *Tested Status* table summarises it.

Last full sweep: 2026-11-07. Last update: 2026-11-08.

## Where the tests ran

**Test line:** NMB is developed and tested on one home fibre (FTTH) connection with a 1000/300 Mbps plan, from a Hungarian ISP, with the box behind the home router, a GL.iNet Flint 4. Every speed, CPU and timing figure in this README and in the testing record comes from that line and a Raspberry Pi 4. Much slower lines (DSL, mobile) and faster ones (2.5 or 10 Gbps) have not been tested; above about 1 Gbps the Pi 4's single gigabit port and its CPU become the limit before the line does.

| Name | What it is |
|---|---|
| **Box** | Raspberry Pi 4, Debian 13 (arm64), `standalone` mode, wired to the developer's main router, a GL.iNet Flint 4. In daily use on a 1000/300 Mbps home fibre (FTTH) line. |
| **VM-D13** | QEMU/KVM on an x86-64 PC, Debian 13 cloud image with the full `linux-image-amd64` kernel. Two NICs (user-mode NAT as WAN, a socket link as LAN). Wi-Fi with `mac80211_hwsim` (three simulated radios); clients in network namespaces. |
| **VM-distro** | Clean QEMU/KVM VMs of Debian 13, Debian 12, Ubuntu 24.04 LTS and Alpine 3.20 (x86-64), each installed from scratch with `setup.sh`. |
| **Unit tests** | `python3 -m unittest discover tests` (303 tests) on the developer PC and, as root, inside VM-D13. |

Simulated means: real Linux, real `hostapd`, `dnsmasq`, `pppd`, WireGuard and OpenVPN, but virtual NICs and radios. Timing, drivers and radio behaviour of real hardware are not covered.

## Results

Legend: ✅ works · ⚠️ works with a limit · ❌ fails · — not tested

### Operating systems (VM-distro)

| System | Clean install | Reinstall | Reboot | Notes |
|---|---|---|---|---|
| Debian 13 | ✅ | ✅ | ✅ | Also the base of VM-D13 |
| Debian 12 (Python 3.11) | ✅ | ✅ | — | Real speed test passed. Polkit rule verified: `nmb` may restart `nmb-netd`, not `ssh` |
| Ubuntu 24.04 LTS | ✅ | — | — | Needed interface auto-detection (`ens3` instead of `eth0`), fixed |
| Ubuntu 26.04 LTS (Python 3.14, polkit 127) | ✅ | ✅ | ✅ | Reinstall over a running box: measurements kept (1 speed test, ping samples kept growing), changed admin password kept, config 0640 `nmb:nmb`, a planted stale file in `/opt/nmb` removed, no Tracebacks. RTR test ok |
| Ubuntu 22.04 LTS (Python 3.10, polkit 0.105) | ✅ | ✅ | ✅ | Needed the old polkit's `.pkla` rule, added; there `nmb` may manage any unit. Scheduled Ookla tests ran |
| Rocky Linux 10.2 (Python 3.12, polkit 125) | ✅ | ✅ | ✅ | EPEL enabled by `ID`; reinstall kept measurements and the changed admin password, config 0640 `nmb:nmb`, stale file removed, no Tracebacks. RTR test ok. The 10 GB cloud image needs a disk of at least 10 GB (an 8 GB test overlay did not boot) |
| Alpine 3.22 (OpenRC, Python 3.12) | ✅ | ✅ | ✅ | Reinstall over a running box: measurements and changed admin password kept, config 0640 `nmb:nmb`, stale file removed, no Tracebacks in `/var/log/nmb`. RTR test ok |
| Alpine 3.20 (OpenRC) | ✅ | ✅ | ✅ | Needed port 80 capability, RMBT build and OpenRC restart fixes |
| Raspberry Pi 4, Debian 13 | ✅ | ✅ | ✅ | The Box |
| Fedora 45 (Python 3.15, SELinux enforcing) | ✅ | — | — | New `dnf` branch. All services, polkit, all optional packages; RTR and Cloudflare measured, the Ookla CLI ran (refused by Ookla's rate limit, shared IP). No SELinux denials. Reboot not checked |
| AlmaLinux 10.2 (for RHEL 10; Python 3.12, SELinux enforcing) | ✅ | ✅ | ✅ | Needs EPEL (enabled by `setup.sh`). Fixed: rebuilds list "fedora" in `ID_LIKE`, so EPEL was skipped; `sudo` there does not search `/usr/local/bin`. Update check counts `dnf` updates. The image needs a SCSI disk in QEMU |
| Raspberry Pi OS, Arch, 32-bit | — | — | — | Not tested |

### Measurement

| Feature | Where | Result | How |
|---|---|---|---|
| Ookla | Box | ✅ | Hourly works. Refusals ("Limit reached") are tied to the public IP: after days of frequent tests the line's address stayed blocked through every hourly retry, even with the CLI's settings fixed; at the owner's suggestion the main router (GL.iNet Flint 4) was restarted, the line got a new public IP, and the first scheduled test passed at once: 934.2/325.4 Mbps, 6.9 ms, bufferbloat A, server #2073 (8 Nov 2026). On a refusal the box pauses Ookla (30 min, up to 4 h) and stores no other engine's result in its place |
| RTR-NetTest | Box, VM-distro | ✅ | ~910/320 Mbps on the 1000/300 line |
| Cloudflare | Box | ✅ | |
| Wi-Fi shared on a LAN port | Box (veth + network namespace, `eth0` untouched) | ✅ | A client in the namespace got 192.168.77.116 by DHCP, pinged 1.1.1.1 (11 ms) and downloaded 20 MB over HTTPS through `wlan0`. With a second DHCP server started on the client side, the box stopped its own DHCP, address, NAT and routing rule; when that server went away, sharing came back within 15 s. Found and fixed on the way: replies of the other server were dropped before reaching a normal socket (now a packet socket), dnsmasq offers after up to 3 s (now 8 s with three requests), and `--log-facility=-` kept dnsmasq in the foreground. Not yet tried with a real cable and no Ethernet uplink |
| Measuring over Wi-Fi (`measurement_link = wifi`) | Box | ✅ | Box on its 5 GHz Wi-Fi (joined by netplan) with the cable in: a Fast.com test moved 149/145 MB over `wlan0` and nothing over `eth0`, 104/110 Mbps. Joining a network with the box's own `nmb-uplink` profile not yet tried |
| Fast.com | Box, dev machine | ✅ | 884/314 Mbps on the 1000/300 line, 5 Netflix servers, bufferbloat A |
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
| 512 MB RAM | VM-D13 (463 MB usable) | ✅ | 25 min, all services, a test every minute: 26 of 26 tests ok, 182–222 MB available, no swap, no OOM, no restarts; web server 40 MB, probe 31 MB, both flat |
| Backup and restore | VM-D13 | ✅ | Create, download, list, restore from the list and from an uploaded file; config and all measurements come back; a truncated upload is refused and changes nothing. Fixed: the restored database could be lost to its old `-wal` journal, the older boot partition copy overwrote the restored config, the restored config was not readable by `nmb`, and an uploaded backup was world-readable |
| Power loss | VM-D13 | ✅ | QEMU killed during a running speed test and right after starting a snapshot: both databases pass `integrity_check`, config intact, all services up; the interrupted test is simply missing. The snapshot is atomic (tmp, fsync, rename). Up to 15 minutes of results can be lost, by design (tmpfs) |
| Ookla on the Box: chosen server, pause, no substitute | Box, unit tests | ✅ | Found on the Box: the built-in Yettel ID (10390) was wrong ("No servers defined"), a paused Ookla was replaced by an RTR result, the pause was lost on restart, `/api/status` failed on a failed test. All fixed; the pause now survives a restart and paused runs add no rows |
| Per-engine intervals | Unit tests | ✅ | RTR with 30 min is skipped within 30 min and runs after; 0 runs every time; Ookla cannot be set below 60 min |
| Update from GitHub (no Git install) | Unit tests | ⚠️ | Safe unpacking (path traversal refused), check against GitHub (mocked), status file, root and commit checks. Not yet run against the real repository on a box |
| Reinstall with `setup.sh` | VM-distro (Ubuntu 26.04, Alpine 3.22, Rocky 10) | ✅ | Settings, admin password and measurements kept; a stale file in `/opt/nmb` removed; config 0640 `nmb:nmb` |
| Central collector and remote control | Local collector and box client, unit tests | ✅ | Upload (repeat adds nothing), search by case number, earlier case number and customer number, CSV, diagnostics and events only with consent, remote speed test run and reported, commands refused without consent or from another site, unknown commands refused on both sides, secrets stored as hashes (0600). Not yet run between two machines |
| Storage guard | Box, unit tests | ⚠️ | On the Box (116 GB) it keeps 2048 MB free and deleted nothing, as it should. Unit tests: target by disk size, oldest logs first, newest backup kept, measurements of the last 7 days kept. Not yet run on a really full disk |
| Saving settings from two programs at once | Box, unit tests | ✅ | Found on the Box: `nmb-web` starting while `nmb-cli` saved left a broken `nmb.conf` (a duplicated section and a cut line), and every program failed to read it. Fixed (one save at a time, own temporary file); a unit test saves a short and a long config from four threads 60 times and the file always parses |

## How to test

Every change is tested at the level it can break. Write down what you ran, where, and what you saw; a change without a recorded test is not finished (see [CONTRIBUTING.md](../CONTRIBUTING.md)).

### 1. Unit tests (every change)

```sh
python3 -m unittest discover -s tests          # about 1 minute; must end with OK
node --check nmb/web/assets/dashboard.js       # when the Web UI script changed
bash -n setup.sh                               # when setup.sh changed
```

- New behaviour gets a test in `tests/`. Mock the system (`subprocess`, `/sys`, sockets); tests must pass on a normal PC without root, without network and without the box.
- `tests/test_tui.py` fails when the Web UI calls an endpoint `nmb-cli` does not know: add the action to `nmb/tui/catalog.py`.
- Translations: every key in every language (`tests/test_i18n_locales.py` checks the JSON languages: all keys, same placeholders and HTML as English), no Hungarian text in the other languages:
  `python3 -c "from nmb.web.i18n import TRANSLATIONS as T; k=set(T['en']); print({l: len(k ^ set(v)) for l, v in T.items()})"` must print only zeros.

### 2. On a real box (anything that touches the network, the system or measuring)

1. Install the change the way users get it: `git archive HEAD` to the box, then `sudo bash setup.sh` from the unpacked folder. Do not copy single files, except for a quick try, and say so when you do.
2. Check: `systemctl is-active nmb-web nmb-netd nmb-probe` and `systemctl list-units 'nmb*' --state=failed`.
3. Run the feature for real and look at the result where users see it: the Web UI, `nmb-cli latest`, the database (`sqlite3 -readonly /var/lib/nmb/live/nmb.db`), the logs (`journalctl -u nmb-web -u nmb-netd`).
4. Measure what the feature claims. For network features this means byte counters: read `/sys/class/net/<if>/statistics/{rx,tx}_bytes` before and after, so you know which link the traffic really took.
5. Put the box back as it was: settings, test interfaces, rules. Say what you changed and that you undid it.

### 3. Without risking the box's own connection

- **A LAN client:** a veth pair with one end in a network namespace (`ip netns add t; ip link add v0 type veth peer name v1; ip link set v1 netns t`). The namespace is a device plugged into the box. Never test DHCP or routing on the port you are connected through.
- **A second DHCP server:** `dnsmasq --port=0 --interface=v1 --bind-interfaces --dhcp-range=...` inside the namespace.
- **Simulated Wi-Fi:** `mac80211_hwsim` in a VM (VM-D13). Real radios behave differently; mark such results as simulated.
- **Speed engines:** run one engine at a time; Ookla at most once an hour from the same public IP, or Ookla blocks it for hours.

### 4. In virtual machines (installers, other distributions, network modes)

- A clean cloud image per distribution, installed from scratch with `setup.sh`; then install again over it and reboot. Check that settings, the admin password and measurements survive, and that `/etc/nmb/nmb.conf` is `0640 nmb:nmb`.
- Network modes and the access point in VM-D13 (two NICs, simulated radios, clients in namespaces).

### What to record

For every row: where (Box, VM name, unit tests), the result (✅ ⚠️ ❌), and how: what was set up, what was measured, numbers, and what was found and fixed on the way. Something that was not tried is written as not tried, not as working.

## Release checklist

Run before every release on the Box (and, for installer changes, on one VM). Each line says what to do and what counts as passed. Write the result into the tables above.

| # | Area | What to do | Passed when |
|---|---|---|---|
| 1 | Unit tests | `python3 -m unittest discover -s tests`, `node --check nmb/web/assets/dashboard.js`, `bash -n setup.sh` | All OK |
| 2 | Upgrade install | `git archive HEAD` to the box, `sudo bash setup.sh` | Exit 0; `nmb-web`, `nmb-netd`, `nmb-probe` active; no failed `nmb*` unit; `/opt/nmb/.source-commit` is the new commit; settings, admin password and measurements kept; `nmb.conf` readable and `0640 nmb:nmb` |
| 3 | Clean install | One VM per supported family (Debian/Ubuntu, Fedora/RHEL, Alpine) from scratch | Same as 2, plus the dashboard answers and a first RTR test runs |
| 4 | Ookla | One scheduled run, at most once an hour | A row with download, upload, ping and the chosen server; if refused: one error row, a pause, no other engine's result in its place |
| 5 | RTR-NetTest, Cloudflare, Fast.com | One manual run each (`nmb-cli run speed.run engine=...`) | A row under its own engine name; speeds plausible for the line (on the test line 850–940 down, 300–330 up); Fast.com row has `raw_json` with servers, samples and loaded latency |
| 6 | iPerf3 | One run against the configured server | Row named after the server (place and provider), not only the address |
| 7 | Mixed run | Schedule engine `all`, wait one cycle | One row per engine, each with its own name; Ookla only if its hour is over |
| 8 | Measurement link | Set `wifi`, run one test, read `wlan0`/`eth0` byte counters before and after; set back to `auto` | The traffic went over the chosen link; `auto` uses Ethernet when a cable is in |
| 9 | Wi-Fi shared on a LAN port | veth pair + namespace as in *How to test*; then a second DHCP server in the namespace | Client gets an address and reaches the internet through Wi-Fi; with the second server the box stops its DHCP, address, NAT and rule within about 2 minutes; everything removed when turned off |
| 10 | Wireless roles | Ports & Drivers: set `wlan0` to main, save; then guest | The device explorer shows the right banner; guest status no longer claims the main network |
| 11 | Storage guard | `storage_guard.run(cfg, force=True)` as root on the Box; on a VM with a filled disk | Box: nothing deleted, target shown; VM: rotated logs first, measurements of the last 7 days kept, an event written |
| 12 | Settings | Save from the Web UI and `nmb-cli` at the same time a few times | `nmb.conf` still parses; no duplicated section |
| 13 | Languages | Switch through all 11 languages on the dashboard, the settings tabs, the logout page and `/results`; open the report with `?lang=` for each | No raw keys, no broken layout, no Hungarian outside Hungarian; the bot answers in English in the six newer languages |
| 14 | Web UI | Open every tab with the browser console open | No JavaScript errors; every tab loads its data |
| 15 | Reports and exports | Download the report, speed CSV, detailed CSV and ping CSV | Files open; the new engines and iPerf3 names appear |
| 16 | Telegram (if configured) | `/test fastcom`, `/report`, `/lang` | Answers in the chat's language; Fast.com result arrives |
| 17 | Reboot | `sudo reboot`, wait 3 minutes | All services up; settings, the last snapshot and the Ookla pause state survive |
| 18 | Put back | Undo test settings, test interfaces and rules | The box is as it was before the checklist |

## Still to test

### Needs a real cable or hardware

| What | How |
|---|---|
| Wi-Fi shared on a LAN port, for real | Box on Wi-Fi, Ethernet cable from the box to a laptop (no router): the laptop gets 192.168.77.x and reaches the internet. Then plug the box's cable into the home router: the box must stop its DHCP within seconds and get the router's address |
| Wi-Fi uplink with the box's own profile | `nmb-cli run wifi.uplink ssid=... password=... enabled=true` on a box not yet on Wi-Fi; then a speed test with `measurement_link = wifi`, counters on `wlan0` |
| Guest Wi-Fi and main Wi-Fi on two radios | A USB Wi-Fi adapter as `wlan1`: one main, one guest; both banners in the device explorer |
| Real Wi-Fi radios as an access point | 2.4/5/6 GHz, Wi-Fi 6/7, with real clients |
| PPPoE on a real line, the Nighthawk M6 Pro, a Pi 5 | |
| Planned routers | Nothing runs on routers yet; see the porting plan |

### Can be done now (VM or box)

| What | How |
|---|---|
| Storage guard on a full disk | VM with a small disk (2–4 GB); fill it (`fallocate -l ... /var/tmp/fill`), wait up to 10 minutes or call `storage_guard.run(cfg, force=True)` as root: rotated logs go first, measurements of the last 7 days stay, an event is written |
| Installer on a small or full disk | `setup.sh` with less than 500 MB free must stop with a clear message; on a disk under 8 GB the new config gets 2 × 2 MB logs |
| Saving settings from several programs at once | Web UI and `nmb-cli` saving in a loop for a few minutes; `nmb.conf` must stay readable (the unit test covers threads in one process) |
| Fast.com on a line other than 1000/300 | Compare with RTR-NetTest on the same line |
| Long run | 24–72 hours with per-minute tests: memory, database size, log rotation, storage guard |
| Low memory, longer | 512 MB passed for 25 minutes; 24 hours still to do |
| Upgrade and backup from an older release | Install 2.4.0, update to the current one with its config; restore a 2.4.0 backup |
| WAN failover, load balancing, VLAN, link aggregation | Two WAN NICs, pull one; a Linux bridge with VLAN filtering |
| Hostile networks | IPv6-only WAN, CGNAT, broken DNS, captive portal, flapping link, clock jump |
| Telegram, SMTP | Against local mock servers, then a real bot |
| Update from GitHub on a box | Once the current code is on GitHub |
| Central collector between two machines | Collector on one PC, box on another network |
| Web UI | All 11 languages (the six newer ones were machine-assisted translations: a native speaker should read them), several users at once, wrong logins, Firefox, Chrome and a phone |
| firewalld ports, Debian 12 and Fedora reboot, Tailscale, OONI, a real DuckDNS domain | |

### Operating systems not yet tested

Found by checking what `setup.sh` detects and what the code needs (Python 3.10 or newer, standard library only, systemd with nftables, or Alpine with OpenRC).

| System | Expected | Why | How to test |
|---|---|---|---|
| Raspberry Pi OS (arm64), Lite | Should work | Debian 13 based, like the Box | On a Pi, or Debian arm64 under QEMU |
| Raspberry Pi OS (armhf, 32-bit) | Unknown | The Ookla and RMBT builds have only been run on arm64 and x86-64 | On a Pi 2/3/Zero 2 |
| Armbian, DietPi | Should work | Debian-based images for other single-board computers | On the board, or their x86 images |
| Linux Mint 22, Pop!_OS | Should work | Ubuntu 24.04 based; desktop NetworkManager may claim the ports | VM |
| Devuan | Refused | No systemd; `setup.sh` stops with a clear message | — |
| Arch, Manjaro, openSUSE, Void, NixOS | Not supported | Other package managers or init systems | Needs a port |
| OpenWrt | Not supported | Planned in the native rewrite, see `ROUTER_PORTING_AND_DEPYTHONIZATION_PLAN.md` | — |
| NMB's own distribution | Planned | See the porting plan | — |

## Known limits

- Ookla blocks the public IP address that tests too often, and refused attempts keep the block going; shown on 8 Nov 2026 when a new public IP (main router restarted) passed at once. The box then pauses Ookla (30 min, doubling up to 4 h). NMB does not change the IP to get around it; run Ookla at most hourly.
- Up to 15 minutes of results can be lost on a power cut, by design (the live database is in RAM).
- The VM scripts used for the runs above are not part of the repository; each row says what was set up.
