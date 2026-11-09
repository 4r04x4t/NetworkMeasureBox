# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `docs/DEV_SETUP_WINDOWS.md` (and Hungarian): developing on Windows with WSL2, reaching the box over Tailscale, SSH keys, safe sudo, GitHub access, deploying with `setup.sh`, the guided scenarios and moving the agent's memory.
- Settings from a USB stick: `nmb.conf` at the top level of a stick is applied once when plugged in (only its keys, secrets never wiped by empty values, backup first, `nmb-import-result.txt` written back with names only). Template `config/usb-import.example.conf`; `[usb_import] enabled = false` turns it off.
- `nmb-selftest pppoe`: NMB's own pppd command against a throwaway PPPoE server (right password connects and carries traffic, wrong password is refused, the password is on no command line); `--pppoe-real` dials the real line on the WAN port in a separate namespace. Passed on the Pi 4 (simulated line).
- Scenarios stop and restore when Tailscale is offline for 2 minutes; `nmb-selftest internet` checks Tailscale; `nmb-selftest router` checks the Web UI and SSH from the LAN.
- `nmb-selftest scenario router`: a guided live test of router mode with the Ethernet port as WAN (router mode up with a simulated client, a real device on the box's Wi-Fi and its traffic counted, the Web UI from that device, a WAN cable loss and return, restore). Stopping a scenario (`systemctl stop`) now restores the settings too.
- `nmb-selftest scenario usb`: a guided live test with USB tethering (speed tests bound to USB, Wi-Fi shared on the LAN port, USB fallback, router mode on USB with real clients, the DHCP guard, restore, unplugging the device); it waits for each cable move, counts the clients' forwarded packets, and always puts the settings back (also after 45 minutes by a separate service).
- `nmb-selftest`: live checks on a running box (services, internet, settings, web and terminal interfaces, USB tethering, router mode with a simulated LAN client, the DHCP guard against a throwaway server, speed engines against each other, the Wi-Fi access point, the central collector, and with `--full` the Telegram bot in all 11 languages). Throwaway namespaces only; never prints secrets. See TESTING.md, 2a.
- De-Pythonization roadmap 4.27: USB tethering in the native build (sysfs driver detection, netlink hotplug, built-in DHCP client, table 152, fallback, router mode, data limit), with kernel packages per platform (Pi 4, x86-64, own distribution, OpenWrt, flash-limited targets, MikroTik); porting plan 7G for routers; the USB tethering drivers added to the base distribution criteria.
- USB tethering as the only internet: with no wired or Wi-Fi default route the box adds one through USB (metric 900) and removes it when another is back; both switches are events. In router mode (Mode A) USB becomes the WAN when no DHCP server answers on the Ethernet port, which then joins the LAN with the Wi-Fi access point; a DHCP server on that port stops the box's DHCP at once. LAN-port sharing takes USB as its upstream when the Wi-Fi uplink is down.
- De-Pythonization roadmap: the central collector server is ported to a native static binary too, with the same protocol and data layout; USB tethering, fallback and router mode added to the features the native build must match.
- USB tethering (`[usb_uplink]`): a phone, mobile hotspot or modem on USB as a measuring link, with its own profile that never takes the default route, a source rule (table 152), the measurement link `usb`, its own daily data limit, results stored as mobile; Web UI card, `nmb-cli` (`usb.uplink`, `usb.off`), all 11 languages. Tested on the Pi 4 over 5G with a Netgear Nighthawk M6 Pro (US AT&T model).
- Porting plan 1.3: MikroTik devices (container on RouterOS v7, or OpenWrt instead of RouterOS) and MediaTek SoC families (MT7620/MT7628, MT7621, MT7622, Filogic MT7981B, MT7986A, MT7988A) as planned targets, with offload notes; figures to verify.
- De-Pythonization roadmap 6A: more base candidates (Fedora IoT, Ubuntu Core, NixOS, Buildroot/Yocto, balenaOS), an eighth criterion (the base itself brings no Python) and an evaluation order (OpenWrt, Debian, Alpine, Fedora IoT).
- Porting plan: candidates for the base of NMB's own distribution compared against fixed criteria (Debian, Raspberry Pi OS Lite, OpenWrt, Alpine, VyOS, IPFire; pfSense and OPNsense excluded as FreeBSD), with an evaluation plan.
- Porting plan, NMB's own distribution: the distribution is NMB's own, the kernel is not; it ships the stock Raspberry Pi kernel on the Pi 4 and the base distribution's LTS kernel on x86-64, unchanged, so kernel fixes come from their maintainers. Recommended build: a Debian-based image (`mmdebstrap`/`debos`).
- De-Pythonization roadmap and porting plan: *Generic First* — the native code is written platform- and architecture-independent and proven on a PC (x86-64) and the Raspberry Pi 4 (ARM64) before any router work, with a build matrix (amd64 and arm64 built and tested, arm, mips and mipsle cross-compiled from the start).
- Testing record (`docs/TESTING.md`, `docs/TESTING.hu.md`): the bot, settings-merge, Wi-Fi password, CLI coverage, service restart and secrets results; new rules for mocks, restarted processes, long checks on the box and secrets; the release checklist grows from 18 to 24 steps.
- Web UI: a *Disk space* card in the settings (automatic cleanup on/off, minimum free space, days of measurements always kept, "Check and clean up now" and the current free space), in all 11 languages.
- `nmb-cli`: automatic disk cleanup settings and "clean up now" (`storage.save`, `storage.cleanup`, new `/api/storage/*` endpoints), the main Wi-Fi client port role in `ports.roles`, and the diagnostic bundle and deep snapshot downloads.
- The de-Pythonization roadmap and the porting plan set a quality bar: the native build must run at least as flawlessly as the Python version, fix the bugs it finds instead of carrying them over, and be measurably better, with the evidence written down before it replaces a Python component.
- A release checklist in the testing record (English and Hungarian): 18 areas, each with what to do and what counts as passed.
- The de-Pythonization roadmap and the porting plan list the features added in November 2026 and the rules learned from their fixes, which the native build must keep.
- Six more languages: Romanian, Italian, Spanish, Portuguese (Portugal and Brazil) and Simplified Chinese, in the Web UI (all 1362 texts), the logout page, the terminal UI, the results page, the charts and the report. The Telegram bot speaks them too: menus, answers, the language menu, the admin answers and alerts.
- The README and the testing record explain why scheduled Ookla tests run at most once an hour: Ookla blocks the public IP address that tests too often, shown on the test line when a new public IP (after a restart of the main router, suggested by the box's owner) passed at once while the old one stayed blocked.
- The porting plan requires for every port and the native `nmbd` on all devices: an owner-enabled maintenance mode with full access for developers and developer LLM agents (keys only, audit log, time limit), detailed structured logging that spares flash, crash evidence kept across reboots, and fixes applied next to the running version with automatic rollback and a written recovery path per device. Planned only.
- Storage guard (`[storage]`, on by default): before the disk fills up, the box deletes the oldest logs, backups, reports and journal, and only then the oldest measurements (the last 7 days are kept). The free space it keeps depends on the size of the disk. `setup.sh` stops with a clear message when less than 500 MB is free, and uses smaller logs on disks under 8 GB.
- CONTRIBUTING.md (English and Hungarian) and a pull request template: how to test a change and what to write down about it.
- The testing record says how to test (unit tests, on a box, without risking the box's own connection, in VMs) and lists what is still to test and how.
- NMB's own Linux distribution, built on the de-Pythonized `nmbd`, is in the porting plan. Planned only.
- ASUS RT-AC57U v1 (MediaTek MT7621AT, 128 MiB RAM, 16 MiB flash) is listed as a planned router target. Planned only, like the other routers.
- Wi-Fi shared on a LAN port (`[wifi_share]`, off by default): when the box is on Wi-Fi and the port has no internet of its own, devices on that port get addresses from the box (192.168.77.0/24 by default) and reach the internet through the box's Wi-Fi. The box never hands out addresses where another DHCP server answers: it checks before starting, every minute, and right after a cable is plugged in (stopping its own DHCP first). Web UI card under the schedule, `nmb-cli run wifi.share`.
- In Ports & Drivers each wireless interface can be the *Guest Wi-Fi client* or the *Main Wi-Fi client (measuring)*. One interface cannot be both; taking the guest client's radio away turns the guest client off, and the automatic choice of the main client skips the guest client's radio.
- The README and the testing record say on what line NMB is developed and tested: one 1000/300 Mbps home fibre (FTTH) connection, with a Raspberry Pi 4.
- Fast.com (Netflix) as a measuring engine, in pure Python through Fast.com's own API: up to five nearby Netflix Open Connect servers, latency to each, 8 streams over them for download and upload, the "stable" speed Fast.com shows, latency under load and bufferbloat. Each row keeps the ISP, ASN and location Fast.com sees, every server with its latency and its share of the transfer, and the speed every half second. The home page shows it in a table: how Fast.com sees the box (ISP, ASN, place), the stable, mean and peak speed, the latency under load and every Netflix server with its latency and its share. In the Web UI, the Telegram bot (`/test fastcom`), `nmb-speed --engine fastcom` and `nmb-cli`; part of the mixed run every time (`fastcom_interval_min`, 0 by default). Transfers use plain HTTP with 16 streams for 15 s each way, since on a Raspberry Pi 4 TLS used most of the CPU and the result dropped when other services ran.
- iPerf3 rows that only stored an address (older rows) now show the server's name in the statistics, the history and the CSV: from the public iPerf3 list, else the city, country and ISP of the address from GeoIP.
- Wi-Fi uplink for measuring: the box can join the owner's own Wi-Fi (`[wifi_uplink]`, its own `nmb-uplink` NetworkManager profile, separate from the guest Wi-Fi client), and `[network] measurement_link` chooses where speed tests run: `auto` (Ethernet when a cable is connected, otherwise Wi-Fi), `ethernet` or `wifi`. With both links up, tests bound to Wi-Fi really leave over Wi-Fi (source routing). Set it in the Web UI under the schedule or with `nmb-cli run wifi.uplink`.
- iPerf3 "Download, then upload" direction (now the default in the iPerf3 tab), shown as one result.
- iPerf3 results name the server (place and provider, from the public list or GeoIP) instead of only its address.
- Several iPerf3 servers for automatic tests, tested one after the other, each in its own row ("Add to the automatic list" in the iPerf3 tab, `extra_servers` under `[iperf]`, `nmb-cli run iperf.auto`). Servers that do not answer are left out.
- "Use this server for automatic tests" in the iPerf3 tab saves the server with its streams, duration, protocol and direction.
- `nmb-cli latest [engine]`: the newest result of every engine, or of one.
- iPerf3 can be the only automatic engine, and joins the mixed run, when an iPerf3 server is set and answers; it has its own interval (`iperf3_interval_min`). Without a working server it is left out without an empty row.
- Central measurement collector (`nmb-collector`) for an ISP or a specialist: boxes whose owner turns it on send speed tests and hourly ping summaries; with separate consent also events and hourly full network diagnostics, and remote control (speed test, fresh diagnostics, upload; nothing else). Boxes are found by a permanent unique ID, name, current or earlier case number, customer number or ISP. Web UI card and `nmb-cli run collector.save` / `collector.send` on the box.
- Each engine has its own minimum interval for scheduled tests (`ookla_interval_min`, at least 60; `rtr_interval_min`, `cloudflare_interval_min`), set in the Web UI under the schedule.
- A "Refresh from Ookla" button next to the Ookla server choice on the home page and in the server list.
- Update from GitHub in a few clicks: on a box installed with `setup.sh` (no git), "Apply Stable Update" in the Web UI, `nmb-cli update --apply --yes` or `nmb-heal update --apply` downloads the newest version, runs its tests, backs up settings and measurements, installs it and puts the previous version back if the install fails. The Web UI shows each step.
- Ubuntu 26.04 LTS, Alpine 3.22 and Rocky Linux 10 are tested: clean install, reinstall and reboot.
- Fedora and RHEL support (tested on Fedora 45 and AlmaLinux 10): a `dnf` branch in `setup.sh` that enables EPEL on RHEL and its rebuilds and opens the NMB ports in firewalld. `nmb-helper upgrade` and `check-updates` work with `dnf` and `apk` too.
- Optional results without password: with `public_results = true` (off by default), devices on the local network can open `/results` and download the report and CSV files without logging in. Settings still need the password.
- A warning in the Web UI, the API and the log when the schedule runs Ookla more often than hourly, since Ookla then blocks the box; it also shows how long Ookla stays paused.
- A testing record, `docs/TESTING.md` (and `docs/TESTING.hu.md`): where each feature was tested, how, and with what result.
- This changelog, covering the project from its first commit.
- A plan for a separate Keep a Changelog file for the native rewrite, kept from its first commit.
- A real DMZ in router mode: its own subnet and DHCP, internet access, and no access to the LAN or the box beyond DHCP and DNS.
- A DNS interception test and a NAT mapping check (endpoint-independent or symmetric) in the diagnostic bundle.
- Port checks for 22, 5060 and 6881.
- Telegram alerts for high latency and high jitter. Latency alerts were documented but did not exist.
- A daily data limit for scheduled tests, for mobile and other metered connections.
- Clean code rules in the native rewrite plans, to avoid spaghetti code.
- The `nmb-cli` terminal interface and the changelog rule in the architecture document.

### Changed

- The Wi-Fi access point runs only in router mode. In standalone and bridge mode the radio stays a Wi-Fi client of the home network (the box's second internet), and is handed back to NetworkManager and reconnected if an access point held it. Before, `wifi_enabled = true` also turned the radio into an access point in standalone mode, which cut the box off its Wi-Fi network.
- NMB's own distribution moved from the porting plan into the de-Pythonization roadmap (section 6A) and made explicitly Python-free: no device (router, Raspberry Pi 4, x86-64, own distribution) ships or needs Python; the distribution is built once `nmbd` meets the Quality Bar.
- Scheduled iPerf3 tests run at most hourly by default (`iperf3_interval_min = 60`), since public iPerf3 servers take one client at a time.
- The home page only shows results: buttons choose the newest result of any engine (mixed) or of one engine. The engine, the Ookla server, the interface and the schedule are set under Measurement & Servers, which the home page links to. In `nmb-cli` the schedule moved to the same screen.
- Recommended iPerf3 defaults for automatic tests: 4 parallel TCP streams, 10 s, download and then upload one after the other (`auto_direction = both`), with a short pause and a retry before the upload, since many public servers take one client at a time.
- No country is built in: the Ookla server choice comes only from Ookla's current list of servers near the box (the built-in list had wrong IDs, such as 10390 for Yettel, which Ookla answers with "No servers defined"); the Wi-Fi country defaults to automatic; the ISP name, examples and placeholders no longer name Hungarian providers; regulator-specific status codes are now neutral status codes with English descriptions.
- The Ookla server choice is labelled as the Ookla Speedtest server everywhere, with a note that RTR-NetTest, Cloudflare and iPerf3 choose their own servers.
- Scheduled Ookla tests run at most once an hour, however often the schedule runs, since Ookla blocks boxes that test more often. RTR-NetTest, Cloudflare and iPerf3 still run every time, and manual Ookla tests are not held back.
- The speed test list no longer shows skipped runs (busy network, manual mode); a line says how many were left out. Failed runs show the reason instead of 0.00 Mbps.
- The CLI Terminal and the task manager no longer act as root, because the web server runs as `nmb`.
- Editing the boot partition copy of the config now uses `__KEEP_CURRENT__` for passwords and tokens.
- The diagnostic bundle runs fewer MTR cycles, so it finishes faster without root.
- READMEs list the operating systems tested in a simulated environment on a PC: Debian 13, Debian 12, Ubuntu 24.04 LTS and Alpine 3.20.
- READMEs now state what has been tested, and describe features as they work, for example the bridge needing an IP address and the self-update needing a Git checkout.
- Documentation describes the security model and which services run as root.

### Fixed

- Web UI, DynDNS: with unsaved changes the card's badge got the whole warning sentence and squeezed the title into a column one letter wide; the badge now says "Unsaved" and the header wraps. After saving, the live status is fetched again once the update has run (it showed "never" and the old error until a reload). The live card no longer says DuckDNS when dynv6 is used (11 languages).
- `nmb-selftest dyndns` checks the name in public DNS (the home router's resolver can cache an old address) and warns about an AAAA record on a line without IPv6.
- DynDNS: turned on with a domain but no token, it updated nothing and said nothing; it now logs it and the status shows "the token is missing". `nmb-selftest dyndns` checks the token, a recent successful update and that the name points at the current line.
- Telegram bot: a speed test blocked the bot for its whole duration (minutes with all engines), so it did not answer anything else; tests now run in their own thread and a second one is refused politely. The result shows only this test's own rows (one line per engine), not whatever row was newest, and the start message no longer promises 15-25 seconds.
- Speed tests: one at a time on the whole box. The lock was per process, so a Telegram test and a scheduled test of the web server could run at once and measure each other's traffic; a scheduled test now skips, a manual, web or Telegram test waits up to 10 minutes.
- PPPoE: the user name and password were on the pppd command line, readable by every local user with `ps`; they are now in a private options file.
- Standalone mode with the access point on: devices could join but got no address. Starting the access point flushed every address from the radio, including its own one added just before, so dnsmasq failed ("unknown interface wlan0"). Only a DHCP client's dynamic addresses and routes are removed now; `nmb-selftest wifi-ap` fails when an access point has no address or no DHCP. (Regression from the 2026-11-08 fix for the radio's leftover client lease.)
- RTR (native client): the test never used the asked link (no source address was passed; it now gets `--bind`), the row had no client IP (it is now asked over the same link), and the ping minimum and jitter were invented (minimum = median, jitter a fixed 500 µs); the client now reports the real minimum and jitter, and an older binary leaves them empty.
- Ookla: scheduled runs during a rate-limit pause are stored as skipped, not as failed tests.
- iPerf3: a server whose last five tests all failed is left out for 6 hours (one extra server failed 282 of 283 tests and was tried every minute).
- Wi-Fi password: the shared factory password is gone from the built-in defaults and the example config, so it can no longer come back from them; the installer first restores the owner's password from the root-only copy, and only generates a new one when there is none.
- Router mode: a PC on the LAN port kept an address from before (for example from Wi-Fi sharing) and had no internet until its cable was replugged. After setting up, router mode now drops the wired LAN ports' link for 4 seconds so devices ask again. With this, router mode on USB tethering passed live: laptop on the cable and a Wi-Fi client (2.4 GHz) browsed over 5G, Web UI and Tailscale reachable, DHCP guard stopped serving 50 s after the home router came back.
- `nmb-selftest scenario`: the client packet counter used an invalid nftables rule; the "laptop got an address" check could count the simulated client's lease.
- Router mode, Wi-Fi sharing and the USB fallback failed when the box's cable moved from the home router to a laptop: the box's own static default route on `eth0` (metric 50) stayed, beat Wi-Fi and USB, and the box lost its internet and Tailscale, while Wi-Fi sharing thought the port had its own internet. `nmb-netd` now removes default routes through a port with no link or no address, and the kernel ignores routes on a port without link (`ignore_routes_with_linkdown`). `nmb-selftest` fails on such a route.
- Secrets the owner typed (Telegram token, Wi-Fi password, other tokens) are kept in a root-only copy for 30 days (`/var/lib/nmb/secrets.keep`); `nmb-selftest` reports one that went missing and `sudo nmb-selftest secrets-restore` puts it back. The USB scenario restores them itself.
- Settings: an update could wipe the Telegram token. The editable copy on the boot partition counted as newer after an update, and its empty token replaced the real one. The copy is now taken over only when it was really edited, and an empty secret there never replaces a set one.
- `nmb-netd` logs a loop part that takes longer than 15 s, and `kill -USR1` dumps its stacks to the journal (on the box the loop went silent for 8 minutes while the cable moved, and USB never took over).
- `nmb-selftest`: a weak or factory Wi-Fi password is a failure even with the access point off.
- `nmb-speed --interface` (`-i`) was read but never used, so a test asked for USB (or any other link) ran on the default link. Found by the USB scenario.
- Central collector: a box with a wrong token and a large backlog got "Broken pipe" instead of "the collector refused the token", because the collector answered before reading the upload. Found box → collector over Tailscale; the collector between two machines now tested (8592 speed tests, 560 ping hours).
- Web router settings: the save button, card titles, WAN type, DNS mode, DHCP and Wi-Fi on/off choices and the MAC/DNS buttons were English in every language; now translated into all 11 languages.
- Router mode now moves its WAN to USB tethering when the WAN port keeps only an IPv6 link-local address (cable moved from the home router to a PC). Live: the WAN moved to USB, the laptop got an address, and with the home router plugged back in the box stopped its DHCP within a minute and took eth0 as WAN again. Not shown: that the laptop or a Wi-Fi client actually reached the internet through the box.
- The DHCP guard (Wi-Fi sharing and router mode) never saw a router on a bridged port, and could miss one on any port: the DISCOVER went through the IP stack, which gave it another interface's address as the source (DHCP servers such as dnsmasq ignore that), and the offers were read with an IPv4-only packet socket, which gets a bridge port's frames only after the bridge has taken them. The probe now sends a complete frame from 0.0.0.0 and reads with `ETH_P_ALL`; reproduced and verified on the box with a test DHCP server in a network namespace, plain and bridged.
- Router mode on USB tethering lost the box's own internet: the radio that became the access point kept its home Wi-Fi address and default route (metric 600), which beat USB's 900. The access point now starts on a radio without client addresses, and router mode on USB removes every default route that does not go through USB.
- Router mode on USB tethering lost its internet: a stale default route that NetworkManager left on the Ethernet port (now a bridged LAN port) counted as "another internet", so the USB route was removed. In router mode the USB route now stays, routes through bridge ports or on a link that is down never count, and router mode removes default routes through its LAN ports.
- Router mode lost its LAN port to NetworkManager (its DHCP on the port failed and it unbridged the port); LAN ports are released while router mode runs and given back afterwards, as is the Wi-Fi radio when the access point stops.
- The access point never started when the web server had left `hostapd.conf` in `/run/nmb` (the daemon could not change its mode); generated configs now replace the old file.
- Router and bridge modes could use a USB phone, hotspot or modem as a LAN port (the default LAN name `eth1` is often the hotspot) and serve DHCP to it; such interfaces are now never LAN ports, and tearing down router mode no longer removes their address.
- A phone, mobile hotspot (for example a Netgear Nighthawk) or cellular modem on USB was treated as wired Ethernet when its interface was named like one (`enx…`, `eth1`), so speed tests could run over the mobile link and be stored as the wired line, and it could take the box's default route. Such interfaces are now recognised by their driver (`rndis_host`, `cdc_ncm`, `cdc_ether`, `ipheth`, `qmi_wwan`, `cdc_mbim`) and are never used as the wired line; USB Ethernet dongles stay wired.
- Wi-Fi access point password: the shared factory password (`NetworkMeasureBox123`, public in the repository) is no longer a fallback anywhere; the access point does not start with it, with an empty one or with one outside 8-63 characters, and the Web UI refuses to save such a password. The settings show only whether a password is set (it never leaves the box through the API), and the installer no longer prints the generated password into its log.
- Saving the settings from one service (web, network daemon, bot, `nmb-cli`) could undo what another service had saved, because each wrote its whole in-memory copy; this is how an entered Telegram token could disappear. A save now only writes the settings that service changed itself.
- The installer warns when Telegram is enabled without a bot token (it only checks that the value is empty).
- Telegram bot: `/heal`, `/wifi`, `/wifi scan`, `/wifi connect`, `/tasks` (showed 0 for CPU, memory and disk), `/kill`, `/tailscale` (showed a running Tailscale as inactive), `/backup` and `/drivers` (listed no adapters) called functions whose arguments or results had changed.
- The installer now restarts the Telegram bot when it runs, so the bot no longer keeps old code after an upgrade (this caused "cannot import name 'bridge_master'").
- A bot error with no text now names the error type instead of an empty message.
- The Telegram bot showed a non-compliant SLA result ("NEM MEGFELELŐ") as compliant, because it matched the shorter word inside it first.
- Seven Web UI texts described older behaviour (no Fast.com in the mixed run, "falls back to RTR-NetTest" while Ookla is paused, "RTR/Cloudflare failover" on a refusal, no main Wi-Fi client role); corrected in every language.
- The Ookla CLI could not keep its settings since the Web UI runs as `nmb` (its home `/home/nmb` does not exist and systemd keeps homes read-only), so every Ookla test started as a brand-new client. It now has its own home, `/var/lib/nmb/ookla`, and `setup.sh` carries over the licence accepted earlier as root. Whether this is what made Ookla refuse the box is not yet proven.
- Saving the settings from two programs at once (for example the Web UI starting while `nmb-cli` saves) could leave a broken `nmb.conf`: both wrote the same temporary file, so the start of one config ended up over the end of the other, and every program then failed to read it. Saves now run one at a time, each with its own temporary file.
- The Wi-Fi status showed no network name, signal or band, and the access-point check never saw an access point, because `iw` is in `/usr/sbin`, which is not on the `nmb` user's path.
- A test bound to Wi-Fi left over Ethernet when the Wi-Fi was joined outside NMB (netplan or a saved profile) and both links were on the same subnet; the source rule is now kept then too.
- Cloudflare results no longer link to Cloudflare's front page as if it were the result, and a missing bufferbloat grade shows `--` instead of a made-up `A+`.
- iPerf3 results were labelled OOKLA in the speed test list, and an upload-only iPerf3 run showed 0.00 Mbps download.
- "Stop iPerf Server" did nothing: the server runs as the root unit `nmb-iperf3`, which the web server could not stop with `pkill`; start and stop now use `systemctl`.
- A busy or unreachable iPerf3 server no longer adds failed rows to scheduled runs.
- The home card showed a failed run ("-- Mbps", "Upload only", "A+"); it now shows the last real result, says when a newer attempt failed, when the next Ookla test can run, and when the result is from an earlier chosen server.
- The home page schedule line overflowed with the full Ookla warning and showed the label twice ("Accuracy Gate::"); it now shows a short note with the full text on hover, and wraps.
- When Ookla failed or paused, the box ran RTR-NetTest or Cloudflare instead and the home page kept showing an old Ookla result. Ookla failures are now reported as such, and while Ookla is paused no rows are added.
- The Ookla pause was kept only in memory, so every restart asked Ookla again early and made its block longer. It is now kept in `/var/lib/nmb/ookla_cooldown.json`.
- The status page failed (`/api/status` error) once the history held a failed speed test.
- Reinstalling or upgrading with `setup.sh` now saves the measurements still in RAM first and replaces the program files instead of copying over them, so files removed from the project no longer stay behind in `/opt/nmb`.
- Restoring a backup could lose the restored measurements: the old database's `-wal` journal was replayed onto the new file. Databases are now restored through SQLite's backup API.
- A restored config could be overwritten at once by the older boot partition copy, and was written readable only by root, so the web server could not read it. An uploaded backup file was readable by every user.
- `nmb-helper upgrade` ran only `apt-get update`: a second `exec` never ran, so packages were not upgraded. It also ran `apt-get` on Alpine.
- The update check used `sudo nmb-helper` without its path, which fails where `sudo` does not search `/usr/local/bin` (RHEL).
- `nmb-web --config FILE` saved settings to `/etc/nmb/nmb.conf` instead of FILE.
- `setup.sh` stops with a clear message on Debian derivatives without systemd, such as Devuan, instead of failing halfway.
- Install on Ubuntu 22.04: polkit 0.105 ignores the JavaScript rule, so the web server could not manage services. `setup.sh` now also installs a `.pkla` rule there, and picks `policykit-1` where `polkitd` does not exist.
- OpenVPN rejected every client: the server certificate had no TLS server usage, which clients check. New certificates carry it, and an old one is reissued from the same CA, so issued profiles keep working.
- The HTTPS proxy took 20 seconds per request on networks with a broken IPv6 route; it now tries IPv6 and IPv4 addresses side by side. Stopping it now frees its port, and it no longer forwards to the box's own loopback or link-local addresses.
- Guest Wi-Fi: the `nmb` user may now control NetworkManager (polkit), reconnecting no longer fails on a stale profile, errors show NetworkManager's own message, and a disconnected client is no longer reported as connected.
- 5 GHz Wi-Fi never started on systems without the regulatory database. `setup.sh` installs `wireless-regdb` and `iw`, and the access point falls back to 2.4 GHz rather than none.
- Router mode answers a client's DHCP renewal at once after the box restarts (`dhcp-authoritative`).
- Self-update rolled back every update on a real box, because three tests depended on the machine's interfaces, config and network; they are now independent of it. `nmb-heal update --json` and `nmb-heal fix --json` print only JSON.
- The software reported version 2.4.0 instead of 2.5.0.
- Ookla results no longer claim a server they did not use. When Ookla refused a test, the box used to run a one-second Cloudflare download, store it as an Ookla result under the chosen server's name, and report far lower speeds. That fallback is removed; a fallback test is now stored and logged under its own engine (RTR-NetTest or Cloudflare).
- An Ookla rate limit ("Limit reached: Too many requests") now pauses Ookla for the whole box (30 min, doubling up to 4 h) instead of quarantining one server after another. The chosen server is no longer silently swapped, and a result from a different server is flagged with `requested_server_id`.

- Kernel network tuning now runs in `nmb-netd`, which has root; the unprivileged web server no longer fills its log with `sysctl: permission denied`, and the tuning button asks `nmb-netd` to re-apply it.
- The installer's closing summary shows colours instead of raw `\033` codes.

- Wireless router mode now works: Wi-Fi and LAN share a bridge, a Wi-Fi failure no longer stops wired DHCP, and `hostapd` steps down to an older standard if it rejects a setting.
- If the main config file is lost, restoring it from the boot partition no longer writes the `__KEEP_CURRENT__` marks as values or brings back the shared factory Wi-Fi password. Passwords and tokens must then be entered again.
- Running setup again on Alpine no longer stops halfway when a service is already restarting.
- On Alpine (OpenRC), the Web UI listens on port 80 instead of falling back to 8080, the RTR client is built, and the summary shows the OpenRC status command.
- On systems without `eth0`, such as Ubuntu with `ens3`, setup now writes the real network interface names into a new config.
- PPPoE redials after the line drops, instead of staying offline.
- `dnsmasq` no longer conflicts with the built-in DNS filter in router mode, which could leave clients without DHCP.
- WPA3 access points connect, because the cipher setting was missing.
- Network settings saved in the Web UI take effect again without a restart. This was broken when the web server stopped running as root.
- The diagnostic snapshot no longer copies thousands of lines into the system journal, and is written to the boot drive at most once an hour.

### Security

- Removed a way for local users to gain root: self-repair and speed test code could run files from `/tmp`.
- The `nmb` user can no longer run `ip` through sudo, which allowed root access.
- The privileged helper refuses VPN configs with command lines, and package names that look like options.
- The language setting can no longer be changed without logging in.
- The DNS filter's control socket is limited to the box's own services.
- API values with control characters are refused, which prevented adding lines to service config files.
- Update references that git could read as options are refused.
- The web UI, DNS and iPerf3 refuse public addresses, on IPv4 and IPv6, through a new firewall rule.
- Passwords and tokens are no longer copied to the boot partition, and a chosen admin password is no longer stored there.
- The web server runs as the `nmb` user instead of root.
- The Ookla download is installed only if its checksum matches.
- The Tor service that comes with the OONI package is disabled, because NMB does not use it.

## [2.5.0] - 2026-11-07

First entry of this changelog. It summarizes all work since the first commit on 2026-10-26, when no releases or tags existed.

### Added

- Network modes: standalone probe, gateway with NAT, DHCP and Wi-Fi access point, and transparent bridge, with multi-WAN failover and LAN port roles.
- LAN passthrough and link aggregation for a probe behind a router.
- Continuous ICMP latency, jitter, loss and outage measurement.
- Speed tests with Ookla, Cloudflare, RTR-NetzTest (native C client) and iPerf3, plus port throttling checks.
- Scheduled tests down to second-level intervals, with server quarantine when a server rate-limits.
- Traffic gate that postpones tests when the box sees other traffic.
- Experimental, off-by-default stop on network traffic, which only tests a provably idle network and stops running tests when other traffic appears. It reads client-side ports or the router's UPnP counters.
- Web dashboard in five languages with selectable themes, device explorer, packet sniffer, traceroute, task manager and web terminal.
- `nmb-cli` terminal interface with the WebGUI menus, mouse and hotkeys, JSON commands for scripts and LLMs, log listing, and a logo.
- Multilingual Telegram bot with menus and alerts.
- HTML dossier, CSV export and LLM diagnostic bundle.
- WireGuard, OpenVPN and Tailscale management, DynDNS (DuckDNS, dynv6) and an HTTP proxy.
- Built-in DNS ad-blocker with Pi-hole style lists and CLI compatibility.
- Optional weekly OONI Probe runs, off by default.
- Hardware driver detection and installation.
- Backup, restore, factory reset and data purge.
- Self-healing audit and repair with update rollback.
- Low-memory profiles, tested only on the Raspberry Pi 4.
- Plans for a native rewrite and router ports. No router port exists yet.

### Changed

- New installs run speed tests every hour instead of every 6 hours. Upgrades keep the configured schedule.
- The schedule setting is now the only thing that starts speed tests, because `nmb-speed.timer` is removed.
- Dashboard split into separate HTML, CSS and JS files.
- Default log level is INFO.
- Cloudflare tests use fixed-time transfers.
- TLS streams that drop and reconnect during a Cloudflare test are logged as information, and their number is stored with the result.

### Removed

- `nmb-speed.timer`.
- The unused SQM selector and the unused `sample_window_sec` and `cooldown_sec` settings.

### Fixed

- A single invalid setting or a `%` sign in a value no longer stops the services.
- A wrong web port or address no longer locks users out of the dashboard.
- Bridge mode requests an IPv4 address, measures on the bridge and reads forwarded traffic from the WAN port.
- Factory reset leaves a config the services can read, and updates the saved login notes.
- Installation leaves no failed units, and `nmb.target` runs afterwards.
- Self-heal from Telegram and alerts calls the repair function correctly.
- Update verification has enough time, runs from the repository and does not touch the live database.
- Skipped speed tests no longer appear as 0 Mbps or replace real results.
- The iperf3 server check no longer connects to the port, which logged a failed test every few seconds.
- Impossible Cloudflare results, missing imports, API errors on invalid request bodies and incorrect README commands.
- Many mobile layout, theme persistence and translation errors, including Hungarian text in other languages.

### Security

- Factory reset and log purge require explicit confirmation in the CLI and the web API.
- Each box gets its own Wi-Fi password, also after a factory reset.
- Narrower sudo rights, brute-force and CSRF protection, and escaping of external values in the dashboard.
- Personal data removed from the repository, and subscriber data masked in the LLM bundle.

[Unreleased]: https://github.com/4r04x4t/NetworkMeasureBox/compare/6046ea4...HEAD
[2.5.0]: https://github.com/4r04x4t/NetworkMeasureBox/compare/9699189...6046ea4
