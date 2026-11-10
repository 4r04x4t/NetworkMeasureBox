"""Update an installed box from the GitHub repository, without git.

``setup.sh`` copies the program to /opt/nmb without a git checkout, so the box
downloads the newest commit of the repository as an archive instead:

1. ask GitHub for the newest commit of the branch;
2. download that commit's archive and unpack it safely;
3. run the project's tests on the unpacked copy; nothing on the box changes
   unless they pass;
4. take a backup of settings and measurements;
5. run the new ``setup.sh``, which keeps settings and measurements and replaces
   the program files;
6. check that the web server answers again; if the install or the check
   fails, put the previous program files back and restart the services.

The steps run as root through ``nmb-helper self-update``. The web server only
starts them and reads the progress from ``STATUS_FILE``, since ``setup.sh``
restarts the web server itself.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO = os.environ.get("NMB_UPDATE_REPO", "4r04x4t/NetworkMeasureBox")
BRANCH = os.environ.get("NMB_UPDATE_BRANCH", "main")
INSTALL_DIR = Path(os.environ.get("NMB_INSTALL_DIR", "/opt/nmb"))
COMMIT_FILE = INSTALL_DIR / ".source-commit"
STATE_DIR = Path(os.environ.get("NMB_UPDATE_STATE_DIR", "/var/lib/nmb"))
STATUS_FILE = STATE_DIR / "update_status.json"
WORK_DIR = STATE_DIR / "update-work"
LOG_FILE = Path("/var/log/nmb/update.log")
CODE_DIRS = ("nmb", "bin", "os", "components", "docs")
MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
USER_AGENT = "NetworkMeasureBox-updater"
STEPS = ("download", "test", "backup", "install", "verify")
_SHA_RE = re.compile(r"[0-9a-f]{40}")


def _get(url: str, timeout: float = 20.0) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - fixed https URLs
        return resp.read(MAX_ARCHIVE_BYTES + 1)


def installed_commit() -> str:
    try:
        sha = COMMIT_FILE.read_text().strip()
    except OSError:
        return ""
    return sha if _SHA_RE.fullmatch(sha) else ""


def upstream_commit() -> Dict[str, str]:
    data = json.loads(_get(f"https://api.github.com/repos/{REPO}/commits/{BRANCH}"))
    sha = str(data.get("sha", ""))
    if not _SHA_RE.fullmatch(sha):
        raise ValueError("GitHub returned no commit")
    msg = str((data.get("commit") or {}).get("message", "")).splitlines()
    return {"sha": sha, "title": msg[0] if msg else ""}


def _compare(old: str, new: str) -> Dict[str, Any]:
    """GitHub's view of the installed commit against the newest one: status ("ahead" = GitHub is newer,
    "behind" = the box is newer, "identical", "diverged", "unknown" = GitHub does not have the installed
    commit, "error") and the new commits' titles."""
    if not old:
        return {"status": "unknown", "changelog": []}
    try:
        data = json.loads(_get(f"https://api.github.com/repos/{REPO}/compare/{old}...{new}"))
    except urllib.error.HTTPError as e:
        return {"status": "unknown" if e.code in (404, 422) else "error", "changelog": []}
    except (urllib.error.URLError, ValueError, OSError):
        return {"status": "error", "changelog": []}
    lines = []
    for c in reversed(data.get("commits") or []):
        title = str((c.get("commit") or {}).get("message", "")).splitlines()
        lines.append(f"{str(c.get('sha', ''))[:8]} {title[0] if title else ''}".strip())
    return {"status": str(data.get("status") or "error"), "changelog": lines[:10]}


def _changelog(old: str, new: str) -> List[str]:
    return _compare(old, new)["changelog"]


def check() -> Dict[str, Any]:
    """Compare the installed commit with the newest one on GitHub."""
    current = installed_commit()
    result: Dict[str, Any] = {
        "source": "github",
        "repo": REPO,
        "git_branch": BRANCH,
        "current_commit": current[:8],
        "upstream_commit": "",
        "update_available": False,
        "is_stable": True,
        "target_ref": "",
        "changelog": [],
        "message": "System software is up to date.",
    }
    try:
        up = upstream_commit()
    except (urllib.error.URLError, ValueError, OSError) as e:
        result["message"] = f"Could not reach GitHub: {e}"
        result["error"] = "unreachable"
        return result
    result["upstream_commit"] = up["sha"][:8]
    if up["sha"] == current:
        return result
    if not current:
        result.update(update_available=True, target_ref=up["sha"],
                      changelog=[f"{up['sha'][:8]} {up['title']}"] if up["title"] else [],
                      message=f"The installed version is not known; the newest version on GitHub is {up['sha'][:8]}.")
        return result
    # A different commit is not always a newer one: a box running code that is not on GitHub yet would be
    # "updated" back to older code (2026-11-10: /heal updates offered 2.5.0 -> 2.5.0 on a box ahead of GitHub).
    cmp = _compare(current, up["sha"])
    result["compare"] = cmp["status"]
    if cmp["status"] == "ahead":
        result.update(update_available=True, target_ref=up["sha"],
                      changelog=cmp["changelog"] or ([f"{up['sha'][:8]} {up['title']}"] if up["title"] else []),
                      message=f"A newer version is on GitHub ({up['sha'][:8]}).")
    elif cmp["status"] == "behind":
        result["message"] = f"The installed version ({current[:8]}) is newer than GitHub ({up['sha'][:8]})."
    elif cmp["status"] == "diverged":
        result["message"] = (f"The installed version ({current[:8]}) and GitHub ({up['sha'][:8]}) both have changes "
                             "the other lacks; updating would drop the installed ones, so it is not offered.")
    elif cmp["status"] == "unknown":
        result["message"] = f"The installed version ({current[:8]}) is not on GitHub (not pushed yet); no update offered."
    else:
        result["message"] = "Could not compare the installed version with GitHub; no update offered."
        result["error"] = "compare"
    return result


# ------------------------------------------------------------------------------
# Progress file read by the web server
# ------------------------------------------------------------------------------

def read_status() -> Dict[str, Any]:
    try:
        return json.loads(STATUS_FILE.read_text())
    except (OSError, ValueError):
        return {"state": "idle"}


def _write_status(state: str, step: str = "", **extra: Any) -> None:
    data = {"state": state, "step": step, "step_no": STEPS.index(step) + 1 if step in STEPS else 0,
            "steps": len(STEPS), "ts": int(time.time())}
    data.update(extra)
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATUS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data))
    os.chmod(tmp, 0o644)
    os.replace(tmp, STATUS_FILE)
    _log(f"{state} {step} {extra.get('message', '')}".strip())


def _log(line: str) -> None:
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + line + "\n")
    except OSError:
        pass


# ------------------------------------------------------------------------------
# Download and unpack
# ------------------------------------------------------------------------------

def _safe_members(tar: tarfile.TarFile) -> List[tarfile.TarInfo]:
    members = []
    for m in tar.getmembers():
        name = m.name
        if name.startswith("/") or ".." in Path(name).parts:
            raise ValueError(f"unsafe path in archive: {name}")
        if m.issym() or m.islnk():
            target = Path(name).parent / m.linkname
            if m.linkname.startswith("/") or ".." in Path(os.path.normpath(target)).parts:
                raise ValueError(f"unsafe link in archive: {name}")
        if not (m.isfile() or m.isdir() or m.issym() or m.islnk()):
            continue  # devices, fifos
        members.append(m)
    return members


def unpack(archive: Path, dest: Path) -> Path:
    """Unpack a GitHub archive; returns its single top directory."""
    with tarfile.open(archive, "r:gz") as tar:
        members = _safe_members(tar)
        tops = {Path(m.name).parts[0] for m in members if m.name}
        if len(tops) != 1:
            raise ValueError("archive does not have one top directory")
        kwargs = {"filter": "data"} if hasattr(tarfile, "data_filter") else {}
        tar.extractall(dest, members=members, **kwargs)  # noqa: S202 - members checked above
    src = dest / tops.pop()
    for needed in ("setup.sh", "nmb/common/backup.py", "tests"):
        if not (src / needed).exists():
            raise ValueError(f"archive is missing {needed}")
    return src


def download(sha: str, dest: Path) -> Path:
    data = _get(f"https://codeload.github.com/{REPO}/tar.gz/{sha}", timeout=120)
    if len(data) > MAX_ARCHIVE_BYTES:
        raise ValueError("archive is too large")
    archive = dest / "source.tar.gz"
    archive.write_bytes(data)
    return unpack(archive, dest / "src")


# ------------------------------------------------------------------------------
# Apply
# ------------------------------------------------------------------------------

def _run(cmd: List[str], cwd: Optional[Path] = None, timeout: int = 600, env: Optional[dict] = None) -> int:
    with open(LOG_FILE, "a") if LOG_FILE.parent.exists() else open(os.devnull, "w") as out:
        try:
            return subprocess.run(cmd, cwd=cwd, stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                  timeout=timeout, env=env, check=False).returncode
        except subprocess.TimeoutExpired:
            return 124


def _restart_services() -> None:
    if Path("/run/systemd/system").is_dir():
        _run(["systemctl", "daemon-reload"], timeout=30)
        _run(["systemctl", "restart", "nmb.target"], timeout=120)
    else:
        for svc in ("nmb-db", "nmb-netd", "nmb-probe", "nmb-web"):
            _run(["rc-service", svc, "restart"], timeout=60)


def _web_answers(wait_sec: int = 90) -> bool:
    deadline = time.time() + wait_sec
    while time.time() < deadline:
        for url in ("http://127.0.0.1/", "http://127.0.0.1:8080/"):
            try:
                urllib.request.urlopen(url, timeout=5)  # noqa: S310
                return True
            except urllib.error.HTTPError:
                return True  # 401 means the server is up
            except (urllib.error.URLError, OSError):
                pass
        time.sleep(3)
    return False


def apply(sha: Optional[str] = None) -> Dict[str, Any]:
    """Run the whole update; needs root. Returns the final status."""
    if os.geteuid() != 0:
        return {"state": "failed", "message": "The update must run as root (nmb-helper self-update)."}
    if sha and not _SHA_RE.fullmatch(sha):
        return {"state": "failed", "message": "Invalid commit."}
    old_commit = installed_commit()
    shutil.rmtree(WORK_DIR, ignore_errors=True)
    WORK_DIR.mkdir(parents=True, mode=0o700)
    try:
        _write_status("running", "download")
        sha = sha or upstream_commit()["sha"]
        src = download(sha, WORK_DIR)

        _write_status("running", "test", commit=sha[:8])
        with tempfile.TemporaryDirectory(prefix="nmb-verify-") as tmp:
            env = dict(os.environ, NMB_LIVE_DB=f"{tmp}/live.db", NMB_PERSIST_DB=f"{tmp}/persist.db",
                       NMB_OOKLA_COOLDOWN_FILE=f"{tmp}/ookla_cooldown.json",
                       PYTHONPATH=str(src), PYTHONDONTWRITEBYTECODE="1")
            if _run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-q"], cwd=src, timeout=900, env=env) != 0:
                return _finish("failed", f"The tests of version {sha[:8]} failed; nothing was changed. See {LOG_FILE}.")

        _write_status("running", "backup", commit=sha[:8])
        checkpoint = ""
        try:
            sys.path.insert(0, str(INSTALL_DIR))
            from nmb.common import backup
            ok, path, _ = backup.create_backup(backup_type="full", comment=f"Before update to {sha[:8]}",
                                               custom_filename=f"nmb-auto-pre-update-{int(time.time())}.tar.gz")
            checkpoint = str(path) if ok else ""
        except Exception as e:  # the program-file copy below still allows a rollback
            _log(f"backup failed: {e}")
        prev = WORK_DIR / "previous"
        prev.mkdir()
        for d in CODE_DIRS:
            if (INSTALL_DIR / d).exists():
                shutil.copytree(INSTALL_DIR / d, prev / d, symlinks=True)

        _write_status("running", "install", commit=sha[:8], checkpoint=checkpoint)
        env = dict(os.environ, NMB_NONINTERACTIVE="1", NMB_SOURCE_COMMIT=sha)
        rc = _run(["bash", "setup.sh"], cwd=src, timeout=3600, env=env)

        _write_status("running", "verify", commit=sha[:8], checkpoint=checkpoint)
        if rc == 0 and _web_answers():
            COMMIT_FILE.write_text(sha + "\n")
            return _finish("success", f"Updated to {sha[:8]}.", commit=sha[:8], previous=old_commit[:8], checkpoint=checkpoint)

        for d in CODE_DIRS:
            shutil.rmtree(INSTALL_DIR / d, ignore_errors=True)
            if (prev / d).exists():
                shutil.copytree(prev / d, INSTALL_DIR / d, symlinks=True)
        if old_commit:
            COMMIT_FILE.write_text(old_commit + "\n")
        _restart_services()
        reason = f"setup.sh exited with {rc}" if rc else "the web server did not come back"
        return _finish("rolled_back", f"The update to {sha[:8]} failed ({reason}); the previous version was put back. See {LOG_FILE}.",
                       checkpoint=checkpoint)
    except Exception as e:
        return _finish("failed", f"Update failed before anything was changed: {e}")
    finally:
        shutil.rmtree(WORK_DIR, ignore_errors=True)


def _finish(state: str, message: str, **extra: Any) -> Dict[str, Any]:
    _write_status(state, "", message=message, **extra)
    return read_status()


def main(argv: List[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else "check"
    if cmd == "check":
        print(json.dumps(check(), indent=2))
        return 0
    if cmd == "status":
        print(json.dumps(read_status(), indent=2))
        return 0
    if cmd == "apply":
        res = apply(argv[2] if len(argv) > 2 else None)
        print(json.dumps(res, indent=2))
        return 0 if res.get("state") == "success" else 1
    print("usage: python3 -m nmb.common.updater {check|status|apply [commit]}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
