"""The installed NMB version, from the file the updater writes (no git needed on the box)."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path


def installed_version() -> str:
    """Short commit of the installed version; "dev-<sha>" in a source checkout; "unknown" otherwise.

    Never a made-up number: the Web UI showed "4047" (another device's firmware number) and the
    diagnostic bundle "unknown (no git metadata)" on an installed box until 2026-11-10.
    """
    try:
        from nmb.common.updater import COMMIT_FILE
        sha = COMMIT_FILE.read_text(encoding="utf-8").strip()
        if re.fullmatch(r"[0-9a-f]{7,40}", sha):
            return sha[:7]
    except (OSError, ImportError):
        pass
    root = Path(__file__).resolve().parents[2]
    try:
        res = subprocess.run(["git", "-C", str(root), "rev-parse", "--short=7", "HEAD"],
                             capture_output=True, text=True, timeout=3, check=False)
        if re.fullmatch(r"[0-9a-f]{7,40}", res.stdout.strip()):
            return "dev-" + res.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return "unknown"
