"""nmb-helper only does what NMB needs as root: fixed names, paths and packages (2026-11-10 review)."""
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
HELPER = ROOT / "bin" / "nmb-helper"


def _helper_list(name):
    m = re.search(rf'^{name}="([^"]*)"', HELPER.read_text(), re.M)
    return set(m.group(1).split())


def _run(*args):
    return subprocess.run(["sh", str(HELPER), *args], capture_output=True, text=True, timeout=20, cwd="/tmp")


class AllowListsMatchTheCodeTest(unittest.TestCase):
    def test_links_and_folders(self):
        from nmb.common import heal
        self.assertEqual(_helper_list("CORE_LINKS"), set(heal.CORE_SYMLINKS))
        self.assertEqual(_helper_list("CORE_DIRS"), {str(d) for d in heal.CORE_DIRECTORIES})

    def test_repair_packages(self):
        from nmb.common import heal
        apt_pkgs = {m["pkg"] for m in heal.CORE_BINARIES.values()} - {"open-rmbt-source", "speedtest"}
        self.assertEqual(_helper_list("REPAIR_PACKAGES"), apt_pkgs)

    def test_driver_packages(self):
        listed = set(re.findall(r'"package":\s*"([A-Za-z0-9.+_-]+)"', (ROOT / "nmb/netd/drivers.py").read_text()))
        self.assertTrue(listed)
        self.assertEqual(listed - _helper_list("DRIVER_PACKAGES"), set())


class HelperRefusesTest(unittest.TestCase):
    """Refusals happen before any root action, so they can be checked as a normal user."""

    def assertRefused(self, *args):
        res = _run(*args)
        self.assertNotEqual(res.returncode, 0, args)
        self.assertIn("Refusing", res.stderr, args)

    def test_symlink(self):
        self.assertRefused("heal-symlink", "evil", "/opt/nmb/bin/evil")
        self.assertRefused("heal-symlink", "nmb-web", "/etc/passwd")
        self.assertRefused("heal-symlink", "../x", "/opt/nmb/bin/../x")

    def test_permissions(self):
        self.assertRefused("heal-permissions", "/etc")
        self.assertRefused("heal-permissions", "/var/lib/nmb/../../etc")

    def test_restore_config(self):
        self.assertRefused("heal-restore-config", "/etc/shadow")
        self.assertRefused("heal-restore-config", "/boot/firmware/../../etc/shadow")

    def test_install_file(self):
        self.assertRefused("heal-install-file", "/bin/sh", "/usr/local/bin/evil")
        tmp = tempfile.NamedTemporaryFile(delete=False)
        tmp.close()
        self.addCleanup(os.unlink, tmp.name)
        self.assertRefused("heal-install-file", tmp.name, "/usr/local/bin/speedtest")   # not prepared by root

    def test_packages(self):
        self.assertRefused("install-drivers", "-oAPT::Update::Pre-Invoke::=x")
        self.assertRefused("install-drivers", "openssh-server")
        self.assertRefused("heal-pkg-install", "openssh-server")
        self.assertRefused("heal-pkg-install", "")


class RestoreConfigTest(unittest.TestCase):
    def test_only_drive_copies_and_marks_never_become_values(self):
        from nmb import config
        tmp = Path(tempfile.mkdtemp(prefix="nmb-test-restore-"))
        mirror = tmp / "nmb.conf.drive"
        mirror.write_text(f"[web]\nadmin_password = {config.SECRET_MARK}\n[network]\nmode = auto\n")
        dest = tmp / "etc" / "nmb.conf"
        self.assertFalse(config.install_drive_config(mirror, dest))              # not one of the drive paths
        with mock.patch.object(config, "DRIVE_CONFIG_PATHS", (mirror,)):
            self.assertTrue(config.install_drive_config(mirror, dest, owner="no-such-user-nmb-test"))
        text = dest.read_text()
        self.assertIn("mode = auto", text)
        self.assertNotIn(config.SECRET_MARK, text)
        self.assertEqual(dest.stat().st_mode & 0o777, 0o640)


if __name__ == "__main__":
    unittest.main()


class SshKeysOnlyTest(unittest.TestCase):
    """Optional keys-only SSH (owner's choice, 2026-11-10) can never lock the owner out."""

    def setUp(self):
        text = HELPER.read_text()
        self.block = text.split("    ssh-keys-only)")[1].split("\n        ;;\n    openvpn-ccd-sync)")[0]

    def test_keys_checked_before_writing_and_setting_verified(self):
        on = self.block.split("            on)")[1].split("            off)")[0]
        self.assertLess(on.index("authorized_keys"), on.index('> "$DROPIN"'))
        self.assertIn("sshd -t", on)
        self.assertIn("passwordauthentication no", on)
        self.assertIn('rm -f "$DROPIN"', on)                     # an unaccepted setting is removed again

    def test_drop_in_is_read_first(self):
        # sshd takes the first value it reads; the Pi image ships 50-cloud-init.conf allowing passwords
        self.assertIn("/etc/ssh/sshd_config.d/01-nmb-keys-only.conf", self.block)
        from nmb.web import server
        self.assertEqual(server.SSH_KEYS_ONLY_DROPIN, "/etc/ssh/sshd_config.d/01-nmb-keys-only.conf")

    def test_unknown_argument_refused(self):
        res = _run("ssh-keys-only", "maybe")
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("Usage", res.stderr)
