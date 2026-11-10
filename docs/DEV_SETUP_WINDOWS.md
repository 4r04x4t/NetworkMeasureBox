# Developing NetworkMeasureBox on Windows

This guide moves NMB development (by a person or by Claude Code / another LLM agent) from a Linux PC to a Windows 10 or 11 PC, without losing access to the measurement box. Magyarul: [DEV_SETUP_WINDOWS.hu.md](DEV_SETUP_WINDOWS.hu.md).

**Summary:** develop inside **WSL2 (Ubuntu)**, not in plain Windows. Reach the box over **Tailscale**, so it works from any network, also when the box is in router mode or you are away from home.

## Why WSL2

The code, the installer and the tests are written for Linux:

- `setup.sh`, the helper scripts and the deploy steps are bash, with `sed`, `awk`, `tar` and `ssh`;
- the tests use `fcntl`, packet sockets (`AF_PACKET`), network namespaces, and POSIX paths and permissions;
- Git for Windows changes line endings, which breaks shell scripts.

In WSL2 all of this works as on Linux. In plain Windows (PowerShell or Git Bash) only part of the tests run, and deploying to the box is unreliable.

## 1. Install

In an administrator PowerShell:

```powershell
wsl --install -d Ubuntu-24.04
```

Restart, open "Ubuntu" from the Start menu and create your Linux user. Then inside Ubuntu:

```bash
sudo apt update
sudo apt install -y git python3 python3-venv openssh-client rsync curl jq sqlite3 build-essential libcurl4-openssl-dev libssl-dev
```

`build-essential` and the two `-dev` packages are only needed to build the native RTR client (`components/open-rmbt`) on the PC. The box builds it itself during `setup.sh`.

**Claude Code** (when an agent does the development): install it inside WSL, not in Windows, so its shell is the Linux one:

```bash
curl -fsSL https://claude.ai/install.sh | bash
```

## 2. Tailscale: the way to the box

1. Install Tailscale for **Windows** (https://tailscale.com/download) and log in with **the same account as the box**. Windows and WSL2 share the network, so WSL reaches the box through it too.
2. Find the box's Tailscale address in the Tailscale admin console or with `tailscale status`. It is a `100.x.y.z` address. **Do not write it into the repository**: it belongs to the owner's private network.
3. Test from WSL:

```bash
ping -c 2 <box-tailscale-ip>
```

Use the Tailscale address for all box work, not the LAN address. The LAN address changes with DHCP, and it is unreachable when the box is in router mode or you are on another network.

## 3. SSH to the box

Password login works, but a key is better for an agent (no password in commands):

```bash
ssh-keygen -t ed25519 -C "nmb-dev-windows"
ssh-copy-id user@<box-tailscale-ip>
ssh user@<box-tailscale-ip> 'hostname; systemctl is-active nmb-netd nmb-web'
```

Optional, in `~/.ssh/config`:

```
Host nmb-box
    HostName <box-tailscale-ip>
    User user
    ServerAliveInterval 20
```

Then `ssh nmb-box` is enough. `ServerAliveInterval` keeps the session alive when the box changes routes.

**sudo on the box:** never put the password on a command line, in a script or in a log. Pass it on standard input from a private file, and delete the file afterwards:

```bash
umask 077; printf '%s\n' '<sudo-password>' > ~/.nmb-pw
ssh nmb-box 'sudo -S -p "" nmb-selftest' < ~/.nmb-pw
rm -f ~/.nmb-pw
```

## 4. The repository and GitHub

Keep the repository inside the WSL file system (for example `~/src`), not under `/mnt/c/...`. That is several times faster, and file permissions and line endings stay correct.

```bash
mkdir -p ~/src && cd ~/src
git clone git@github.com:4r04x4t/NetworkMeasureBox.git
cd NetworkMeasureBox
git config core.autocrlf false
```

Push access: either an SSH key on GitHub (`cat ~/.ssh/id_ed25519.pub` → GitHub, Settings → SSH keys), or the GitHub CLI:

```bash
sudo apt install -y gh
gh auth login            # paste the token at the prompt, never as an argument
```

Give a token only the `repo` and `workflow` scopes. Never write a token into a remote URL (`https://user:token@...`) or into `.git/config`.

## 5. Unit tests

```bash
python3 -m unittest discover -s tests
```

They must all pass before every commit. They need no network and no root. The live checks (`nmb-selftest`) run on the box, not on the PC.

**If a test fails only now and then:** check the WSL clock first. On 2026-11-10 the wall clock of the WSL2 VM jumped forward one hour for about 0.1 s every 5 s (two WSL distributions were running; it stopped after the Windows clock was set again), and a DynDNS test failed in about 1 run out of 20. This prints the number of jumps in 30 s; it must be 0:

```bash
python3 -c 'import time
p=time.time(); pm=time.monotonic(); j=0
while time.monotonic()<pm+30:
    t=time.time(); m=time.monotonic(); j+=abs((t-p)-(m-pm))>0.5; p,pm=t,m; time.sleep(0.01)
print("clock jumps in 30 s:", j)'
```

`journalctl` showing "Clock change detected" every few seconds means the same.

## 6. Installing a change on the box

> **Never run the test suite as root (or as `nmb`) on a working box.** Some tests save settings and lists without a path, and on the box that is the real `/etc/nmb/nmb.conf` (2026-11-10: the PPPoE login, the Telegram chat and more were overwritten). Run it the way the updater does, as `nobody` on a copy: `python3 -c "from pathlib import Path; import tempfile; from nmb.common import updater; t = tempfile.mkdtemp(); print(updater.run_tests_sandboxed(Path('.'), t))"` from the unpacked source, as root (it drops to nobody itself). The output goes to `/var/log/nmb/update.log`.


Always the way users get it, with `setup.sh`, never by copying single files (except for a quick try, which you say you did):

```bash
sha=$(git rev-parse HEAD)
git archive HEAD -o /tmp/nmb.tar
scp /tmp/nmb.tar nmb-box:/tmp/nmbd.tar
ssh nmb-box "rm -rf /tmp/nmbd && mkdir /tmp/nmbd && tar xf /tmp/nmbd.tar -C /tmp/nmbd && cd /tmp/nmbd && \
  sudo -S -p '' sh -c 'env NMB_SOURCE_COMMIT=$sha bash setup.sh > /tmp/setupd.log 2>&1; echo rc=\$?; cd /; rm -rf /tmp/nmbd /tmp/nmbd.tar'" < ~/.nmb-pw
```

The full commit id (40 characters) is what `setup.sh` records in `/opt/nmb/.source-commit`; a short one is dropped, and the update check then does not know the installed version.

In router mode the install restarts `nmb-netd`, so PPPoE dials again and the SSH connection may stall for about 20 s: start it detached and wait for it. Keep its log out of `/var/log`, a 48 MB RAM disk on the box (a full one stopped an install halfway on 2026-11-10):

```bash
sha=$(git rev-parse HEAD)
git archive HEAD -o /tmp/nmb.tar
scp /tmp/nmb.tar nmb-box:/tmp/nmbd.tar
ssh nmb-box "rm -rf /tmp/nmbd && mkdir /tmp/nmbd && tar xf /tmp/nmbd.tar -C /tmp/nmbd && cd /tmp/nmbd && \
  sudo -S -p '' sh -c 'setsid nohup env NMB_SOURCE_COMMIT=$sha bash setup.sh > /var/lib/nmb/persist/logs/setup-deploy.log 2>&1 < /dev/null &'" < ~/.nmb-pw
until ssh nmb-box '! pgrep -f "[b]ash setup.sh"'; do sleep 10; done
ssh nmb-box 'tail -3 /var/lib/nmb/persist/logs/setup-deploy.log; cat /opt/nmb/.source-commit; rm -rf /tmp/nmbd /tmp/nmbd.tar'
```

Clean up afterwards: the box's `/tmp` is a 256 MB tmpfs, and leftover copies once filled it. Then check the box:

```bash
ssh nmb-box 'sudo -S -p "" nmb-selftest' < ~/.nmb-pw
```

## 7. Tests that cut the box's own link

Router mode, USB tethering and cable moves change the box's routes. Run them only through the guided scenarios, which run as a service on the box, keep the settings to restore, stop and restore when Tailscale is offline for 2 minutes, and restore after 45 minutes whatever happens:

```bash
ssh nmb-box "sudo -S -p '' systemd-run --unit=nmb-scenario -p StandardOutput=file:/var/log/nmb/scenario-router.log nmb-selftest scenario router" < ~/.nmb-pw
ssh nmb-box 'tail -f /var/log/nmb/scenario-router.log'
```

By hand: `sudo nmb-selftest restore`. See [TESTING.md](TESTING.md), sections 2a and 7.

## 8. The agent's memory

Claude Code keeps its notes about the project (state of the work, how to reach the box, the owner's rules) per machine, in `~/.claude/projects/<path-of-the-repository>/memory/`. A new machine starts without them. Either:

- copy the folder from the old PC into WSL, under the folder named after the new repository path (it appears after Claude Code has been started once in the repository), or
- tell the agent in the first message where the work stands, and ask it to save that.

These notes may hold how to reach the box. Do not put them into the repository.

## 9. Rules that stay

- No secrets in the repository, in commits or in logs: tokens, passwords, keys, the Wi-Fi password.
- No public addresses of the owner (home line, mobile) and no Tailscale address in the repository.
- Ookla at most once an hour; no code to dodge its rate limits.
- Every user-visible change in `CHANGELOG.md`; documentation in English and Hungarian.
- Honest results: a test that has not passed live is not described as working ([TESTING.md](TESTING.md)).

## Checklist

| Step | Done when |
|---|---|
| WSL2 Ubuntu | `wsl -l -v` shows version 2 |
| Tailscale | `ping <box-tailscale-ip>` answers from WSL |
| SSH | `ssh nmb-box hostname` works without a password |
| Repository | cloned under `~/src`, `core.autocrlf false` |
| GitHub | `git push --dry-run` works |
| Unit tests | `python3 -m unittest discover -s tests` passes |
| Box | `nmb-selftest` on the box: no failure |
| Agent memory | copied, or the state given in the first message |
