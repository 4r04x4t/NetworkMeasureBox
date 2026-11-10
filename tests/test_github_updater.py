"""Updating a box installed without git from the GitHub repository."""
import io
import json
import tarfile
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from nmb.common import updater

OLD = "a" * 40
NEW = "b" * 40


def _tar(path: Path, files: dict) -> Path:
    with tarfile.open(path, "w:gz") as tar:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return path


GOOD = {
    "NetworkMeasureBox-x/setup.sh": b"#!/bin/sh\n",
    "NetworkMeasureBox-x/nmb/common/backup.py": b"APP_VERSION = '9'\n",
    "NetworkMeasureBox-x/tests/test_x.py": b"",
}


class UnpackTest(unittest.TestCase):
    def test_good_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = updater.unpack(_tar(Path(tmp) / "a.tgz", GOOD), Path(tmp) / "out")
            self.assertTrue((src / "setup.sh").exists())

    def test_path_traversal_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = dict(GOOD, **{"NetworkMeasureBox-x/../../evil": b"x"})
            with self.assertRaises(ValueError):
                updater.unpack(_tar(Path(tmp) / "a.tgz", bad), Path(tmp) / "out")
            self.assertFalse((Path(tmp).parent / "evil").exists())

    def test_archive_without_installer_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                updater.unpack(_tar(Path(tmp) / "a.tgz", {"x/readme": b"hi"}), Path(tmp) / "out")


class CheckTest(unittest.TestCase):
    status = "ahead"

    def _get(self, url, timeout=20.0):
        if "/compare/" in url:
            if self.status == "404":
                raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
            return json.dumps({"status": self.status,
                               "commits": [{"sha": NEW, "commit": {"message": "fix: thing\n\nbody"}}]}).encode()
        return json.dumps({"sha": NEW, "commit": {"message": "fix: thing"}}).encode()

    def test_newer_commit_is_offered(self):
        with mock.patch.object(updater, "installed_commit", return_value=OLD), \
             mock.patch.object(updater, "_get", side_effect=self._get):
            res = updater.check()
        self.assertTrue(res["update_available"])
        self.assertEqual(res["target_ref"], NEW)
        self.assertEqual(res["changelog"], ["bbbbbbbb fix: thing"])

    def test_same_commit_is_up_to_date(self):
        with mock.patch.object(updater, "installed_commit", return_value=NEW), \
             mock.patch.object(updater, "_get", side_effect=self._get):
            self.assertFalse(updater.check()["update_available"])

    def test_box_ahead_of_github_is_not_offered_older_code(self):
        # 2026-11-10: the box ran commits not on GitHub yet and /heal updates offered an "update" back.
        for status, word in (("behind", "newer than GitHub"), ("diverged", "not offered"), ("404", "not on GitHub"),
                             ("identical", "")):
            self.status = status
            with mock.patch.object(updater, "installed_commit", return_value=OLD), \
                 mock.patch.object(updater, "_get", side_effect=self._get):
                res = updater.check()
            self.assertFalse(res["update_available"], status)
            self.assertIn(word, res["message"])

    def test_unreachable_github_is_not_an_update(self):
        with mock.patch.object(updater, "_get", side_effect=urllib.error.URLError("offline")):
            res = updater.check()
        self.assertFalse(res["update_available"])
        self.assertEqual(res["error"], "unreachable")


class StatusAndGuardTest(unittest.TestCase):
    def test_status_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(updater, "STATE_DIR", Path(tmp)), \
             mock.patch.object(updater, "STATUS_FILE", Path(tmp) / "s.json"), \
             mock.patch.object(updater, "LOG_FILE", Path(tmp) / "u.log"):
            self.assertEqual(updater.read_status(), {"state": "idle"})
            updater._write_status("running", "test", commit="bbbbbbbb")
            st = updater.read_status()
        self.assertEqual((st["state"], st["step_no"], st["steps"]), ("running", 2, 5))

    def test_apply_needs_root_and_a_valid_commit(self):
        with mock.patch("os.geteuid", return_value=1000):
            self.assertEqual(updater.apply()["state"], "failed")
        with mock.patch("os.geteuid", return_value=0):
            self.assertEqual(updater.apply("not-a-commit; rm -rf /")["state"], "failed")

    def test_heal_starts_the_github_update_without_git(self):
        from nmb.common import heal
        from nmb.common import updater
        with mock.patch.object(heal, "_find_repo_dir", return_value=None), \
             mock.patch.object(updater, "check", return_value={"update_available": True, "target_ref": NEW}), \
             mock.patch.object(heal, "_run_helper_or_sudo", return_value=(0, '{"state": "started"}')) as helper:
            res = heal.apply_stable_update()
        self.assertTrue(res["started"])
        helper.assert_called_once_with("self-update", ["start", NEW], timeout=120)

    def test_heal_apply_does_nothing_when_the_box_is_not_behind(self):
        from nmb.common import heal, updater
        with mock.patch.object(heal, "_find_repo_dir", return_value=None), \
             mock.patch.object(updater, "check", return_value={"update_available": False,
                                                               "message": "The installed version is newer than GitHub"}), \
             mock.patch.object(heal, "_run_helper_or_sudo") as helper:
            res = heal.apply_stable_update()
        self.assertTrue(res["up_to_date"])
        self.assertIn("newer than GitHub", res["message"])
        helper.assert_not_called()


if __name__ == "__main__":
    unittest.main()


class BotApplyMessageTest(unittest.TestCase):
    def test_started_update_is_not_reported_as_installed(self):
        from nmb.bot.commands import CommandHandler
        from nmb.common import heal
        from nmb.config import Config
        client = mock.MagicMock()
        h = CommandHandler(Config(), client)
        with mock.patch.object(heal, "apply_stable_update", return_value={"success": True, "started": True, "target": "bbbbbbbb"}):
            h.handle_command(1, "/heal apply")
        text = " ".join(str(c.args[1]) for c in client.send_message.call_args_list)
        self.assertIn("bbbbbbbb", text)
        self.assertNotIn("Update installed", text)
        self.assertNotIn("tests passed", text)



class SandboxedTestRunTest(unittest.TestCase):
    """The update's test run never sees the box's real settings (2026-11-10: tests as root wrote into them)."""

    def test_env_points_everything_at_throwaway_files(self):
        import tempfile as tf
        from pathlib import Path as P
        with tf.TemporaryDirectory() as srcdir, tf.TemporaryDirectory() as tmp:
            src = P(srcdir)
            (src / "tests").mkdir()
            (src / "config").mkdir()
            (src / "config" / "nmb.conf.example").write_text("[network]\n")
            calls = []
            with mock.patch.object(updater, "_run", side_effect=lambda cmd, **kw: calls.append((cmd, kw)) or 0), \
                 mock.patch.object(updater.os, "geteuid", return_value=1000):
                self.assertEqual(updater.run_tests_sandboxed(src, tmp), 0)
            cmd, kw = calls[0]
            env = kw["env"]
            self.assertTrue(env["NMB_CONFIG"].startswith(tmp))
            self.assertTrue(P(env["NMB_CONFIG"]).exists())
            for key in ("NMB_LIVE_DB", "NMB_PERSIST_DB", "NMB_MEASURE_LOCK", "NMB_DYNDNS_STATE", "NMB_BACKUP_DIR",
                        "NMB_PERSIST_LOG_DIR"):
                self.assertTrue(env[key].startswith(tmp), key)
            self.assertTrue(str(kw["cwd"]).startswith(tmp))     # a copy, not the download
            self.assertIsNone(kw["preexec"])                    # not root here; as root it drops to nobody
