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
| Telegram bot and alerts | Box, unit tests | ✅ | 2026-11-08 on the Pi 4, through the real command handler with a stand-in client: every command, menu button and inline button in all 11 languages (338 runs, 0 failures); `/mode`, `/heal`, `/backup`, `/drivers` with good and bad input in all 11 (66 runs, 0 failures, no Hungarian outside Hungarian). Reversible commands for real, then undone: `/kill` on an own `sleep`, `/backup create` + `send` (39 MB) + delete, `/vpn add`/`qr`/`conf`/`del` with a test client, `/heal fix`. A mixed speed test started from the real bot (Cloudflare 860/293, Fast.com 814/320, RTR 607/310, iPerf3 503/315). One real alert, marked as a test, reached the chat. Found and fixed: nine commands called functions whose arguments had changed (the old mocks invented return values, so the tests were green); the bot ran week-old code because the installer never restarted it. Not run: reboot, purge, updates, mode change, Wi-Fi connect, VPN start/stop |
| SMTP, OONI, drive swap | — | — | |
| 512 MB RAM | VM-D13 (463 MB usable) | ✅ | 25 min, all services, a test every minute: 26 of 26 tests ok, 182–222 MB available, no swap, no OOM, no restarts; web server 40 MB, probe 31 MB, both flat |
| Backup and restore | VM-D13 | ✅ | Create, download, list, restore from the list and from an uploaded file; config and all measurements come back; a truncated upload is refused and changes nothing. Fixed: the restored database could be lost to its old `-wal` journal, the older boot partition copy overwrote the restored config, the restored config was not readable by `nmb`, and an uploaded backup was world-readable |
| Power loss | VM-D13 | ✅ | QEMU killed during a running speed test and right after starting a snapshot: both databases pass `integrity_check`, config intact, all services up; the interrupted test is simply missing. The snapshot is atomic (tmp, fsync, rename). Up to 15 minutes of results can be lost, by design (tmpfs) |
| Ookla on the Box: chosen server, pause, no substitute | Box, unit tests | ✅ | Found on the Box: the built-in Yettel ID (10390) was wrong ("No servers defined"), a paused Ookla was replaced by an RTR result, the pause was lost on restart, `/api/status` failed on a failed test. All fixed; the pause now survives a restart and paused runs add no rows |
| Per-engine intervals | Unit tests | ✅ | RTR with 30 min is skipped within 30 min and runs after; 0 runs every time; Ookla cannot be set below 60 min |
| Update from GitHub (no Git install) | Unit tests | ⚠️ | Safe unpacking (path traversal refused), check against GitHub (mocked), status file, root and commit checks. Not yet run against the real repository on a box |
| Reinstall with `setup.sh` | VM-distro (Ubuntu 26.04, Alpine 3.22, Rocky 10) | ✅ | Settings, admin password and measurements kept; a stale file in `/opt/nmb` removed; config 0640 `nmb:nmb` |
| Central collector and remote control | Local collector and box client, unit tests | ✅ | Upload (repeat adds nothing), search by case number, earlier case number and customer number, CSV, diagnostics and events only with consent, remote speed test run and reported, commands refused without consent or from another site, unknown commands refused on both sides, secrets stored as hashes (0600). Not yet run between two machines |
| Storage guard | Box, unit tests | ⚠️ | On the Box (116 GB) it keeps 2048 MB free and deleted nothing, as it should. `nmb-cli` `storage.save` (a wrong number is refused), `storage.cleanup` and `/api/storage/status` run on the Box. Unit tests: target by disk size, oldest logs first, newest backup kept, measurements of the last 7 days kept. Not yet run on a really full disk; the Web UI *Disk space* card not yet opened in a browser |
| Saving settings from two programs at once | Box, unit tests | ✅ | Found on the Box: `nmb-web` starting while `nmb-cli` saved left a broken `nmb.conf` (a duplicated section and a cut line), and every program failed to read it. Fixed (one save at a time, own temporary file); a unit test saves a short and a long config from four threads 60 times and the file always parses. Found later: the Telegram token vanished, because each program wrote back its whole old copy of the settings. Fixed with a three-way merge (a save writes only what that program changed); `tests/test_config_merge.py` saves a token from one copy and another setting from an older copy, and both survive. On the Box the token survived four installs and several saves since |
| USB tethering over 5G (Netgear Nighthawk M6 Pro, US AT&T model; USB product name MR6X00) | Box, unit tests | ⚠️ | 2026-11-08. Plugged in, it appeared as `eth1` (`rndis_host`, 0846:68e1); before the fix it would have counted as wired Ethernet, now it is recognised as tethering and the box kept measuring on `eth0`. `nmb-cli run usb.uplink enabled=true`: a private address from the hotspot's DHCP, default route still on `eth0`, source rule 152 in place. A mixed run with `interface=eth1`: Ookla 105.3/17.7 Mbps, Cloudflare 69.2/18.6, Fast.com 63.6/17.9, RTR 196.7/44.0, all stored as `fwa` on `eth1` with the mobile operator's public IP (not the home line's); 506 MB on the `eth1` counters. To check: RTR is much faster than the others over 5G and its row has no client IP; failover to USB when the cable fails is not built (the outage probe would then measure the mobile link) **Update 2026-11-08 evening:** a test asked for USB with `nmb-speed -i eth1` ran on `eth0` (the option was ignored); fixed, then all four engines measured on `eth1` (bytes counted there). **2026-11-09:** RTR with `--bind` over `eth1`: 81 MB on `eth1`, 130 Mbit/s down, the row has the mobile operator's public IP (same as Cloudflare over USB, not the home line's), ping minimum 29.9 ms against median 31.0 ms, jitter 0.26 ms. |
| USB tethering as the only internet (Nighthawk M6 Pro, 5G) | Box | ⚠️ | 2026-11-08, live. Cable pulled: the default route moved to Wi-Fi (metric 600), USB stayed unused, `auto` measured on `wlan0`. Wi-Fi then disconnected (a restore timer armed first): within about 12 s the box added `default via <hotspot> dev eth1 metric 900`, stayed reachable over Tailscale through 5G, `auto` measured on `eth1` (Cloudflare 76.2/25.3 Mbps, stored as `fwa`). Cable and Wi-Fi back: the USB route was removed within 10 s and `uplink_usb_fallback_end` was written. Found and fixed on the way: the fallback events used severity `warning`, which the schema refuses, so they were not stored (now a test inserts into the real schema). Not yet run: router mode with USB as WAN (a PC on the Ethernet port, a Wi-Fi client) **Failed 2026-11-08 20:02** (guided scenario): with the cable moved from the router to a laptop, a static default route on `eth0` (metric 50, set by the box itself) stayed, beat Wi-Fi and USB, and the box lost its internet and Tailscale; no USB fallback, no sharing to the laptop. Fixed (dead routes are removed, `ignore_routes_with_linkdown`); not yet re-tested. |
| Router mode with USB tethering as WAN (Nighthawk M6 Pro, 5G) | Box | ⚠️ | 2026-11-08, live, two rounds with a laptop on the Ethernet port and on the box's Wi-Fi; logs saved and analysed. Working: bridge `eth0` + `wlan0`, NAT to `eth1`, DHCP to the laptop by cable and Wi-Fi (after fixing the access point start and NetworkManager unbridging the port). Two faults found, reproduced and fixed: (1) the box lost its own internet in router mode because the radio kept its home Wi-Fi lease and default route (metric 600) after becoming the access point; Tailscale's own log showed `defaultRoute=wlan0`; (2) the DHCP guard never saw the home router on the bridged port: the DISCOVER left with another interface's address as source (dnsmasq ignores it) and the IPv4-only packet socket never got the bridged port's frames; with a raw frame from 0.0.0.0 and `ETH_P_ALL` the probe found a test server in a namespace both plain and bridged (the old code found it in neither), and the home router. Recovery when the USB device was pulled worked (the mode rebuilt with `eth0` as WAN). To run again with the fixes: internet for cable and Wi-Fi clients, then the home router on the port **Not working yet as a whole:** in no live round did a client (cable or Wi-Fi) get confirmed internet through the box; the owner could not browse through the cable. The DHCP guard and the WAN switch work. To re-test with `nmb-selftest scenario usb`, which counts the clients' forwarded packets. **2026-11-08 21:00, live, passed:** with the dead-route fix, router mode on USB shared the 5G internet to a Windows laptop on the cable and to a client on the box's Wi-Fi (2.4 GHz, 802.11n only); the owner browsed on both, the Web UI was reachable locally and Tailscale stayed up; 462 packets from the laptop counted out of `eth1` in 75 s. The laptop first kept its 192.168.77.x lease from Wi-Fi sharing and had no internet until the port's link dropped; fixed (router mode now drops the wired LAN ports' link for 4 s after setup). Home router back on the port: the DHCP guard stopped serving after 50 s and `eth0` became the WAN. Still open: 5 GHz and Wi-Fi 5/6 on the access point; the cable-to-laptop fallback with the new link drop |
| Wi-Fi access point password | Box, unit tests | ✅ | The shared factory password is refused by the access point and by the Web UI save; an empty one or one outside 8–63 characters too; `/api/config` reports only `wifi_psk_set`, never the password; the installer log has no password line. On the Box: the password is unique and valid (checked without reading it); the access point is off |
| `nmb-cli` covers the Web UI | Box, unit tests | ✅ | `tests/test_tui.py` fails for a Web UI endpoint without a CLI action; the endpoints the Web UI really calls were compared by hand with the catalog (aliases and prefixes aside): the two diagnostic downloads, the main Wi-Fi role and the disk settings were missing and were added |
| Installer restarts every service | Box | ✅ | After `setup.sh` the `ActiveEnterTimestamp` of `nmb-web`, `nmb-netd` and `nmb-telegram` is later than the start of the install; before the fix the bot kept running code from two days earlier |
| No secrets in output | Box, review | ✅ | Install log, `/api/config`, bot answers and the diagnostic bundle checked for tokens and passwords: only presence flags. Tests on the box check secrets only for being empty or the factory value, never print them |

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

### 2a. Live self-test on the box (`nmb-selftest`)

`sudo nmb-selftest` checks the running box in about a minute; `--full` also drives the Telegram bot through every command and button in all 11 languages (a few minutes). One group: `sudo nmb-selftest router usb`. The report goes to `/var/log/nmb/selftest-<time>.json`; the exit code is 1 when a check failed.

| Group | What it checks |
|---|---|
| services | nmb units active, no tracebacks in the last hour, netd state file |
| internet | default route, ping, DNS, HTTPS |
| config | Wi-Fi password not weak or factory, Telegram token set (never shown), `nmb.conf` not world-readable, event severities fit the schema |
| web | all 11 languages complete and without Hungarian outside Hungarian; status, USB, storage and config endpoints; `/api/config` returns no secrets |
| cli | `nmb-cli menu`, every screen, `latest` for every engine |
| usb | device kind, address, profile never default, source rule to table 152, USB default route only without other internet, ping and HTTPS over USB |
| router | only in router mode: bridge members, DHCP server, NAT on the WAN, the box's own route; then a simulated LAN client (network namespace on a veth in `br-lan`) gets a lease and reaches the internet, DNS and HTTPS |
| dhcp-probe | the DHCP guard against a throwaway dnsmasq: found on a plain port, found on a bridge port, no false alarm without it |
| speed | last 48 h per engine: errors with the most common messages, rate-limit pauses, rows without the client IP, single ping samples, median download against Ookla/Cloudflare on the same link |
| wifi-ap | radio bands (HT40/VHT per band) against the running `hostapd.conf`, refused hostapd starts |
| collector | a copy of the database uploaded to a local collector (or `--collector-url`, token from `NMB_SELFTEST_COLLECTOR_TOKEN`): every speed test arrives once, sending again adds nothing. The box's own upload position is not touched |
| telegram | only with `--full` or by name |

The checks only build throwaway objects (namespaces, veth pairs, a test bridge, a database copy) and remove them; they never change the mode, the settings or the uplinks, and never print secrets or public addresses.

**Guided USB tethering scenario** (needs a person to move cables): `sudo systemd-run --unit=nmb-scenario -p StandardOutput=file:/var/log/nmb/scenario-usb.log nmb-selftest scenario usb`. It runs as a service because the box's link changes during the run; the current instruction is in `/run/nmb/scenario.json` and the log. Steps: speed tests bound to USB (every engine, bytes counted on the USB interface, USB data counter), Wi-Fi shared on the LAN port to a laptop, USB fallback when the box leaves its Wi-Fi (the laptop now on USB, an automatic test over USB), router mode with USB as WAN (simulated client, laptop on the cable, a device on the box's Wi-Fi, forwarded packets counted in a throwaway nftables table), the DHCP guard when the cable goes back to the home router (limit 90 s), restore, and optionally unplugging the USB device. Settings are saved first and put back at the end, after a crash, or by a separate restore service after 45 minutes (`sudo nmb-selftest restore` does it by hand). `--plan` prints the steps, `--steps router,guard,restore` runs some.

### 3. Without risking the box's own connection

- **A LAN client:** a veth pair with one end in a network namespace (`ip netns add t; ip link add v0 type veth peer name v1; ip link set v1 netns t`). The namespace is a device plugged into the box. Never test DHCP or routing on the port you are connected through.
- **A second DHCP server:** `dnsmasq --port=0 --interface=v1 --bind-interfaces --dhcp-range=...` inside the namespace.
- **Simulated Wi-Fi:** `mac80211_hwsim` in a VM (VM-D13). Real radios behave differently; mark such results as simulated.
- **Speed engines:** run one engine at a time; Ookla at most once an hour from the same public IP, or Ookla blocks it for hours.

### 4. In virtual machines (installers, other distributions, network modes)

- A clean cloud image per distribution, installed from scratch with `setup.sh`; then install again over it and reboot. Check that settings, the admin password and measurements survive, and that `/etc/nmb/nmb.conf` is `0640 nmb:nmb`.
- Network modes and the access point in VM-D13 (two NICs, simulated radios, clients in namespaces).

### 5. Mocks must match the real code

A mock that invents a return value keeps a test green while the real call fails. Patch with `autospec=True` (`@patch("nmb.x.y", autospec=True)`), so a renamed argument fails the test, and give the mock the shape the real function returns (a tuple stays a tuple). When in doubt, print the real result on the box once and copy its shape into the test.

### 6. Every process must run the new code

An installed file does nothing while an old process keeps the old one in memory. After an install compare each service's start time with the install time (`systemctl show -p ActiveEnterTimestamp nmb-web nmb-netd nmb-probe nmb-telegram`); every one must be newer. The same after a settings change that a service only reads at start.

### 7. Running long checks on the box

- Run them as a transient unit, not in the SSH session: `sudo systemd-run --unit=nmb-check --uid=nmb -p StandardOutput=file:/tmp/nmb-check.out python3 -u /tmp/check.py`. Do not create the output file beforehand (systemd cannot open a file another user made in `/tmp`).
- Give every step its own time limit and print one line per step, so a hang shows where it is.
- Never `pkill -f` a pattern that also matches your own SSH command line.
- Before cutting a link the box is reached through, arm a way back that does not depend on you, and make it a service that sleeps, not a timer: `systemd-run --unit=nmb-restore sh -c 'sleep 360; nmcli device connect wlan0'`. A transient timer (`--on-active`) fired 3.5 minutes late once, after an install reloaded systemd. Keep a second path open (Tailscale over the other link).
- Skip what changes the line or the box (speed tests from a menu button, reboot, purge, updates) unless that is the test; map a button label to its command before deciding.
- Use test chat IDs that are not real chats, and say in the record which real messages were sent.

### 8. Secrets

Never read, print or copy a token, password or key while testing, not even into a log. Check only what matters: empty or not, equal to a known factory value or not, the right length. Ask the owner to enter a lost secret again.

### What to record

For every row: where (Box, VM name, unit tests), the result (✅ ⚠️ ❌), and how: what was set up, what was measured, numbers, and what was found and fixed on the way. Something that was not tried is written as not tried, not as working.

## Release checklist

Run before every release on the Box (and, for installer changes, on one VM). Each line says what to do and what counts as passed. Write the result into the tables above.

| # | Area | What to do | Passed when |
|---|---|---|---|
| 1 | Unit tests | `python3 -m unittest discover -s tests`, `node --check nmb/web/assets/dashboard.js`, `bash -n setup.sh` | All OK |
| 2 | Upgrade install | `git archive HEAD` to the box, `sudo bash setup.sh` | Exit 0; `nmb-web`, `nmb-netd`, `nmb-probe` (and `nmb-telegram` if used) active and started after the install; no failed `nmb*` unit; `/opt/nmb/.source-commit` is the new commit; settings, admin password, Telegram token and measurements kept; `nmb.conf` readable and `0640 nmb:nmb`; no password or token in `/root/nmb-setup.log` |
| 3 | Clean install | One VM per supported family (Debian/Ubuntu, Fedora/RHEL, Alpine) from scratch | Same as 2, plus the dashboard answers and a first RTR test runs |
| 4 | Ookla | One scheduled run, at most once an hour | A row with download, upload, ping and the chosen server; if refused: one error row, a pause, no other engine's result in its place |
| 5 | RTR-NetTest, Cloudflare, Fast.com | One manual run each (`nmb-cli run speed.run engine=...`) | A row under its own engine name; speeds plausible for the line (on the test line 850–940 down, 300–330 up); Fast.com row has `raw_json` with servers, samples and loaded latency |
| 6 | iPerf3 | One run against the configured server | Row named after the server (place and provider), not only the address |
| 7 | Mixed run | Schedule engine `all`, wait one cycle | One row per engine, each with its own name; Ookla only if its hour is over |
| 8 | Measurement link | Set `wifi`, run one test, read `wlan0`/`eth0` byte counters before and after; set back to `auto` | The traffic went over the chosen link; `auto` uses Ethernet when a cable is in |
| 9 | Wi-Fi shared on a LAN port | veth pair + namespace as in *How to test*; then a second DHCP server in the namespace | Client gets an address and reaches the internet through Wi-Fi; with the second server the box stops its DHCP, address, NAT and rule within about 2 minutes; everything removed when turned off |
| 10 | Wireless roles | Ports & Drivers: set `wlan0` to main, save; then guest | The device explorer shows the right banner; guest status no longer claims the main network |
| 11 | Storage guard | `storage_guard.run(cfg, force=True)` as root on the Box; on a VM with a filled disk | Box: nothing deleted, target shown; VM: rotated logs first, measurements of the last 7 days kept, an event written |
| 12 | Settings | Save from the Web UI and `nmb-cli` at the same time a few times; change one setting in the Web UI, then another with `nmb-cli` | `nmb.conf` still parses; no duplicated section; both changes are there, and the Telegram token and other secrets are unchanged (the bot still starts) |
| 13 | Languages | Switch through all 11 languages on the dashboard, the settings tabs, the logout page and `/results`; open the report with `?lang=` for each; `/lang` in the bot for each | No raw keys or `{placeholders}`, no broken layout, no Hungarian outside Hungarian, in the Web UI and the bot |
| 14 | Web UI | Open every tab with the browser console open | No JavaScript errors; every tab loads its data |
| 15 | Reports and exports | Download the report, speed CSV, detailed CSV and ping CSV | Files open; the new engines and iPerf3 names appear |
| 16 | Telegram (if configured) | Every menu button and the commands `/status`, `/ping`, `/report`, `/tailscale`, `/vpn`, `/wifi`, `/wifi scan`, `/tasks`, `/heal`, `/backup`, `/drivers`, `/mode`; one `/test`; `/kill` on an own `sleep`; `/backup create` then delete it; `/vpn add` and `/vpn del` with a test name; one test alert | Every answer in the chat's language with real data (no `0.0 B`, no "no controllers", Tailscale state matching `tailscale status`); no "Error (...)" text; the speed test arrives; everything created is removed. With the stand-in client script: every command and button in all 11 languages, 0 failures |
| 17 | Reboot | `sudo reboot`, wait 3 minutes | All services up; settings, the last snapshot and the Ookla pause state survive |
| 18 | Wi-Fi access point | Try to save the factory password and a 6-character one; check `/api/config` | Both refused; `/api/config` has `wifi_psk_set` and no password; the access point does not start without a valid password |
| 19 | `nmb-cli` | `nmb-cli menu`; `nmb-cli run storage.save keep_days=7`, `storage.cleanup`, `dev.bundle`; one bad value | The new actions are listed and work; a bad value is refused with a message |
| 20 | Disk space card | Open it in the Web UI, save, press "Check and clean up now" | Values load, save and come back after a reload; the free space line updates |
| 21 | Services restarted | `systemctl show -p ActiveEnterTimestamp` for every `nmb*` service | All later than the install |
| 22 | Secrets | `grep -iE 'token\|password\|psk' /root/nmb-setup.log`; `nmb-cli api GET /api/config` | Only flags such as `wifi_psk_set`, no values |
| 23 | Logs after the run | `journalctl -p err -u 'nmb*' --since <start>` | No new errors except the ones the test caused on purpose |
| 24 | Put back | Undo test settings, test interfaces, rules, test clients and test chat languages | The box is as it was before the checklist |

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

### Needs the box with USB tethering (run `nmb-selftest scenario usb`)

| What | How |
|---|---|
| Wi-Fi sharing on the LAN port with USB as the upstream | Box on Wi-Fi, cable from the router to a laptop, then the box leaves its Wi-Fi: the laptop must keep browsing over USB (scenario steps `wifi-share`, `usb-fallback`; the client's packets out of `eth1` are counted) |
| Router mode drops the LAN ports' link after setup | Laptop on the cable with an address from before (for example 192.168.77.x): without replugging it must get 192.168.100.x and browse within a minute |
| Dead default routes are removed | Cable from the router to a laptop: within one netd loop no default route may stay on `eth0`; Wi-Fi or USB carries the box's traffic and Tailscale stays up (`nmb-selftest internet`: "no dead default route") |
| Access point on 5 GHz, Wi-Fi 5/6 | So far only 2.4 GHz with 802.11n; the Pi 4 radio does 40/80 MHz only on 5 GHz |
| Unplugging the USB device in router mode and in standalone | Scenario step `unplug`: no USB route or rule left, the mode rebuilds with `eth0` |
| Secrets restore | Clear the Telegram token by hand in `nmb.conf`: `nmb-selftest config` must fail with its name, `sudo nmb-selftest secrets-restore` must bring it back and the bot must answer |
| iPerf3 server resting | A server that fails five tests in a row must be left out for 6 hours (log line "left out for up to 6 h"), then tried again |
| Ookla pause | During an Ookla rate-limit pause the schedule must store skipped rows, not errors (`nmb-selftest speed`: no "rate-limit pauses" warning) |
| Collector over the internet with HTTPS | So far box to PC over Tailscale with HTTP; a collector behind a real certificate on another network |

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
| Telegram commands that change the box | On a spare box: `/reboot now`, `/purge ... confirm`, `/heal apply`, `/mode`, `/wifi connect`, `/vpn start`/`stop` |
| Telegram backup over 50 MB | Telegram refuses bigger files; the bot must say so instead of failing quietly |
| Lost settings across real processes | Web UI, `nmb-cli`, bot and `nmb-netd` saving in turns for an hour; every value set stays (the unit test covers two copies in one process) |
| SMTP | Against a local mock server, then a real mailbox |
| Update from GitHub on a box | Once the current code is on GitHub |
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
- The VM scripts and the bot check scripts used for the runs above are not part of the repository; each row says what was set up.
- The bot can send a backup only up to Telegram's 50 MB limit for bots.
- A box that had the old factory Wi-Fi password and no new one gets no access point until a password is set.
