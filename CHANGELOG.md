# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Fast.com (Netflix) as a measuring engine, in pure Python through Fast.com's own API: up to five nearby Netflix Open Connect servers, latency to each, 8 streams over them for download and upload, the "stable" speed Fast.com shows, latency under load and bufferbloat. Each row keeps the ISP, ASN and location Fast.com sees, every server with its latency and its share of the transfer, and the speed every half second. In the Web UI, the Telegram bot (`/test fastcom`), `nmb-speed --engine fastcom` and `nmb-cli`; part of the mixed run, scheduled every 6 hours by default (`fastcom_interval_min`).
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
