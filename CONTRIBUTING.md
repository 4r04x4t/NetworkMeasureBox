# Contributing to NetworkMeasureBox

Thank you for helping. NMB is used to show an internet provider what a line really does, so a wrong number is worse than a missing feature. These rules exist to keep the results trustworthy. Magyarul: [CONTRIBUTING.hu.md](CONTRIBUTING.hu.md).

## Before you start

- For anything bigger than a small fix, open an issue first and say what you want to change and why.
- Read [docs/TESTING.md](docs/TESTING.md): it says what has been tested, where, and how to test.
- NMB is developed and tested on one 1000/300 Mbps home fibre line with a Raspberry Pi 4. If you test on something else (another line, board or distribution), that is welcome: say exactly what it was.

## Rules for code

- **Python 3.10 or newer, standard library only.** No new pip packages; system tools (`ip`, `nft`, `dnsmasq`, `iw`, `nmcli`) are called with full error handling, and the code must cope with them missing.
- **Honest results.** Never store a result under another engine's name, never fill a value that was not measured, never keep a result that is physically impossible. If something failed, store it as failed with the reason.
- **Do not harm the network the box is on.** Anything that hands out addresses, changes routes or sends traffic must check first that it is safe (see the Wi-Fi sharing: it never serves DHCP where another server answers) and must undo itself when switched off.
- **Respect the services you measure against.** Keep to their limits (Ookla at most hourly) and identify the client honestly.
- **Settings:** every new setting has a default that is safe when the user never touches it, is read in `load_config`, written in `save_config`, and is documented.
- **Web UI:** every new text goes through `t('key', 'English fallback')` with the key in all five languages (`nmb/web/i18n.py`); no Hungarian text in the other languages. Every endpoint the Web UI calls is also an action of `nmb-cli` (`nmb/tui/catalog.py`).
- **Small, readable changes.** One topic per pull request. Comments say why, not what.

## Testing (required)

Every pull request says how it was tested. A pull request without a test record is not merged.

1. **Unit tests, always:**
   ```sh
   python3 -m unittest discover -s tests
   node --check nmb/web/assets/dashboard.js   # if it changed
   bash -n setup.sh                           # if it changed
   ```
   New behaviour gets new tests. Tests mock the system and run without root, network or a box.
2. **On a real device, for anything that touches the network, the system or measuring.** Install it the way users get it (`git archive` and `setup.sh`), run the feature for real, and measure what it claims (for network features: the interface byte counters before and after). Use a veth pair and a network namespace instead of the port you are connected through. Put the device back as it was.
3. **In a VM, for installer and distribution changes:** clean install, install again over it, reboot.
4. **Update [docs/TESTING.md](docs/TESTING.md) and [docs/TESTING.hu.md](docs/TESTING.hu.md)** with a row: where, result, how.

Write down what you did **not** test. "Not tried on real hardware" is a useful sentence; "works" without saying where is not.

## The pull request

- Fill in the template (`.github/pull_request_template.md`); it asks for the test record.
- Update [CHANGELOG.md](CHANGELOG.md) under *Unreleased* for every change a user can notice (Keep a Changelog: Added, Changed, Fixed, Removed).
- Update the README (both languages) when behaviour or settings change.
- Commit messages: `type(scope): what changed` (`feat`, `fix`, `docs`, `test`, `refactor`), with the reason in the body when it is not obvious.
- If an AI assistant wrote part of the change, say so; you are still responsible for having read and tested it.

## Security issues

Do not open a public issue for a security problem. Write to the maintainer through the address on the GitHub profile, with the steps to reproduce.

## Licence

By contributing you agree that your contribution is published under the project's MIT licence.
