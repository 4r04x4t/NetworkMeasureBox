"""Every repository file setup.sh installs, or the README points to, must exist and be in git.

The .gitignore leaves out *.conf (secrets); on 2026-11-10 that silently kept two shipped files out of git:
os/nmb-wait-online.conf (the box's update test run failed on the missing file, so the update was refused)
and config/usb-import.example.conf (made on the old development PC, lost in the move, still named in the
README). Outside a git checkout (the update's copy of the code) only the files' presence is checked.
"""
import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _setup_files():
    text = (ROOT / "setup.sh").read_text()
    paths = set(re.findall(r'\$SCRIPT_DIR/([A-Za-z0-9_./-]+)', text))
    return sorted(p for p in paths if not p.startswith(".git") and "." in Path(p).name)


def _readme_files():
    found = set()
    for doc in ("README.md", "README.hu.md"):
        found |= set(re.findall(r'`((?:config|os)/[A-Za-z0-9_.-]+\.[A-Za-z0-9]+)`', (ROOT / doc).read_text()))
    return sorted(found)


class ShippedFilesTest(unittest.TestCase):
    def test_files_exist(self):
        files = _setup_files() + _readme_files()
        self.assertIn("os/nmb-wait-online.conf", files)
        missing = [p for p in files if not (ROOT / p).is_file()]
        self.assertEqual(missing, [])

    @unittest.skipUnless((ROOT / ".git").exists() and shutil.which("git"), "not a git checkout")
    def test_files_are_in_git(self):
        files = _setup_files() + _readme_files()
        tracked = set(subprocess.run(["git", "-C", str(ROOT), "ls-files", "--", *files],
                                     capture_output=True, text=True, check=True).stdout.split())
        # A file that is only on this machine (ignored or never added) would be missing on the box.
        self.assertEqual([p for p in files if p not in tracked], [])


if __name__ == "__main__":
    unittest.main()
