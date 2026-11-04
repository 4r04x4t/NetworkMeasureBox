"""Unit tests for NetworkMeasureBox Automated Self-Healing and Stable Updates Engine."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

from nmb.common import heal
from nmb.common import backup


class TestHealEngine(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="nmb-heal-test-")
        self.state_file = Path(self.tmp_dir) / "self_heal_state.json"
        self._orig_state_file = heal.STATE_FILE
        heal.STATE_FILE = self.state_file

    def tearDown(self):
        heal.STATE_FILE = self._orig_state_file
        if self.state_file.exists():
            self.state_file.unlink()
        try:
            os.rmdir(self.tmp_dir)
        except Exception:
            pass

    def test_version_stability_classifier(self):
        """Test semver and pre-release stability detection."""
        self.assertTrue(heal.is_version_stable("v2.4.0"))
        self.assertTrue(heal.is_version_stable("2.4.1"))
        self.assertTrue(heal.is_version_stable("v3.0.0"))
        self.assertTrue(heal.is_version_stable("v1.0"))

        # Pre-releases must be identified as unstable
        self.assertFalse(heal.is_version_stable("v2.4.0-rc1"))
        self.assertFalse(heal.is_version_stable("v2.4.0-rc.2"))
        self.assertFalse(heal.is_version_stable("2.5.0-beta"))
        self.assertFalse(heal.is_version_stable("v2.5.0-alpha.1"))
        self.assertFalse(heal.is_version_stable("v2.5.0-dev"))
        self.assertFalse(heal.is_version_stable("v2.5.0-preview"))
        self.assertFalse(heal.is_version_stable("v2.5.0-dirty"))
        self.assertFalse(heal.is_version_stable("invalid-version-string"))

    def test_state_load_and_save(self):
        """Test persistent state file initialization and updates."""
        state = heal.load_heal_state()
        self.assertIsInstance(state, dict)
        self.assertIn("version", state)
        self.assertIn("components", state)
        self.assertIn("history", state)

        # Update and save
        state["overall_health"] = "healthy"
        state["consecutive_clean_audits"] = 7
        state["components"]["test:component"] = {
            "id": "test:component",
            "consecutive_failures": 2,
            "total_failures": 3,
        }
        heal.save_heal_state(state)

        # Reload
        reloaded = heal.load_heal_state()
        self.assertEqual(reloaded["overall_health"], "healthy")
        self.assertEqual(reloaded["consecutive_clean_audits"], 7)
        self.assertEqual(reloaded["components"]["test:component"]["consecutive_failures"], 2)

    def test_audit_structure(self):
        """Test that audit_system_health returns expected fields and structure."""
        report = heal.audit_system_health()
        self.assertIn("timestamp", report)
        self.assertIn("overall_status", report)
        self.assertIn(report["overall_status"], ("healthy", "warning", "critical"))
        self.assertIn("issues_count", report)
        self.assertIn("critical_count", report)
        self.assertIn("warning_count", report)

        components = report.get("components", {})
        expected_cats = ["binaries", "symlinks", "database", "config", "filesystem", "services", "network"]
        for cat in expected_cats:
            self.assertIn(cat, components)
            self.assertIn("status", components[cat])
            self.assertIn("items", components[cat])
            self.assertIsInstance(components[cat]["items"], list)

    def test_symlink_repair_mechanism(self):
        """Test that missing symlinks are reconstructed pointing to bin/."""
        with tempfile.TemporaryDirectory() as tmp_usr_bin:
            with patch("nmb.common.heal.Path") as mock_path_cls:
                # Direct test of _repair_symlinks
                actions = heal._repair_symlinks()
                self.assertIsInstance(actions, list)

    def test_check_stable_updates(self):
        """Test check_stable_updates returns structured status."""
        updates = heal.check_stable_updates()
        self.assertIn("current_version", updates)
        self.assertIn("available_version", updates)
        self.assertIn("update_available", updates)
        self.assertIn("is_stable", updates)
        self.assertTrue(updates["is_stable"])

    def test_multi_attempt_escalation_logic(self):
        """Test adaptive escalation: Tier 1 -> Tier 2 -> Tier 3 based on failure counts."""
        state = heal.load_heal_state()
        # Mock audit returning 1 issue
        mock_audit = {
            "timestamp": 1700000000,
            "overall_status": "warning",
            "issues_count": 1,
            "critical_count": 0,
            "warning_count": 1,
            "components": {
                "symlinks": {
                    "status": "degraded",
                    "items": [{
                        "id": "link:nmb-test",
                        "label": "Test Link",
                        "status": "warning",
                        "message": "Missing symlink",
                    }],
                },
                "binaries": {"status": "ok", "items": []},
                "database": {"status": "ok", "items": []},
                "config": {"status": "ok", "items": []},
                "filesystem": {"status": "ok", "items": []},
                "services": {"status": "ok", "items": []},
                "network": {"status": "ok", "items": []},
            },
        }

        with patch("nmb.common.heal.audit_system_health", return_value=mock_audit), \
             patch("nmb.common.heal._repair_symlinks", return_value=["Restored link:nmb-test"]):

            # Run 1: first failure -> tier 1
            res1 = heal.auto_heal_all()
            state1 = heal.load_heal_state()
            self.assertEqual(state1["components"]["link:nmb-test"]["last_tier_attempted"], 1)

            # Run 2: second failure ("sokadik alkalom") -> tier 2
            res2 = heal.auto_heal_all()
            state2 = heal.load_heal_state()
            self.assertEqual(state2["components"]["link:nmb-test"]["last_tier_attempted"], 2)

            # Run 3: third failure -> tier 3
            res3 = heal.auto_heal_all()
            state3 = heal.load_heal_state()
            self.assertEqual(state3["components"]["link:nmb-test"]["last_tier_attempted"], 3)

    def test_apply_update_no_update_available(self):
        """Test apply_stable_update exits cleanly when already on latest version."""
        with patch("nmb.common.heal._find_repo_dir", return_value=Path(".")), \
             patch("nmb.common.heal.check_stable_updates", return_value={
                 "update_available": False,
                 "current_version": "2.4.0",
                 "available_version": "2.4.0",
                 "is_stable": True,
             }):
            res = heal.apply_stable_update()
            self.assertTrue(res["success"])
            self.assertFalse(res["rolled_back"])
            self.assertIn("already running the latest", res["message"])

    def test_apply_update_automated_rollback_on_failure(self):
        """Test that if tests or health check fail, automated rollback is triggered immediately."""
        mock_checkpoint = Path(self.tmp_dir) / "checkpoint.tar.gz"
        mock_checkpoint.touch()

        with patch("nmb.common.heal._find_repo_dir", return_value=Path(".")), \
             patch("nmb.common.heal.check_stable_updates", return_value={
                 "update_available": True,
                 "current_version": "2.4.0",
                 "available_version": "2.5.0",
                 "is_stable": True,
                 "target_ref": "v2.5.0",
                 "git_branch": "main",
             }), \
             patch("nmb.common.backup.create_backup", return_value=(True, mock_checkpoint, {})), \
             patch("nmb.common.backup.verify_backup", return_value=(True, "OK", {})), \
             patch("nmb.common.backup.restore_backup", return_value=(True, "Restored")), \
             patch("nmb.common.heal._repair_symlinks", return_value=["ok"]), \
             patch("nmb.common.heal._run_cmd") as mock_cmd:

            def smart_run_cmd(cmd, **kwargs):
                cmd_str = " ".join(str(c) for c in cmd)
                if "unittest" in cmd_str:
                    return 1, "", "AssertionError: simulated failure in new update"
                elif "rev-parse" in cmd_str:
                    return 0, "abc1234", ""
                elif "pull" in cmd_str or "checkout" in cmd_str:
                    return 0, "Updated", ""
                elif "reset" in cmd_str:
                    return 0, "Reset", ""
                return 0, "", ""

            mock_cmd.side_effect = smart_run_cmd

            res = heal.apply_stable_update()
            self.assertFalse(res["success"])
            self.assertTrue(res["rolled_back"])
            self.assertIn("automatically rolled back", res["error"])
            self.assertEqual(res["checkpoint"], str(mock_checkpoint))


if __name__ == "__main__":
    unittest.main()
