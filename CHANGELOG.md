# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- This changelog, covering the project from its first commit.
- A plan for a separate Keep a Changelog file for the native rewrite, kept from its first commit.
- The `nmb-cli` terminal interface and the changelog rule in the architecture document.

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
