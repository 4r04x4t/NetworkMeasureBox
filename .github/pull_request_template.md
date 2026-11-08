<!-- See CONTRIBUTING.md (English) or CONTRIBUTING.hu.md (magyar). A pull request without a test record is not merged. -->

## What and why

<!-- What changes for the user, and why. Link the issue. -->

## How it was tested

- [ ] Unit tests: `python3 -m unittest discover -s tests` → <!-- e.g. "Ran 303 tests, OK" -->
- [ ] New or changed behaviour has new tests
- [ ] `node --check nmb/web/assets/dashboard.js` (if the Web UI changed)
- [ ] `bash -n setup.sh` (if setup.sh changed)
- [ ] Translations: every new key in all five languages, no Hungarian in the others

**On a real device or VM** (required for network, system, installer or measuring changes):

| Where (device, OS, line) | What was done | What was measured / seen | Result |
|---|---|---|---|
| <!-- e.g. Raspberry Pi 4, Debian 13, 1000/300 fibre --> | <!-- installed with git archive + setup.sh, ran ... --> | <!-- numbers, byte counters, logs --> | ✅ ⚠️ ❌ |

**Not tested:** <!-- what you did not try, and why -->

## Checklist

- [ ] One topic in this pull request
- [ ] CHANGELOG.md updated under *Unreleased* (if a user can notice the change)
- [ ] README.md and README.hu.md updated (if behaviour or settings changed)
- [ ] docs/TESTING.md and docs/TESTING.hu.md updated with the test above
- [ ] New settings have safe defaults and are read and saved
- [ ] The device was put back as it was after testing
- [ ] Parts written by an AI assistant are named here, and I read and tested them
