"""Unit tests for expanded Telegram bot commands, client, and proactive alerts."""
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from nmb.bot.alerts import AlertMonitor
from nmb.bot.client import TelegramClient
from nmb.bot.commands import CommandHandler, format_bytes
from nmb.config import Config
from nmb.db import database as db


class MockTelegramClient:
    def __init__(self):
        self.sent_messages = []
        self.sent_documents = []
        self.sent_photos = []

    def send_message(self, chat_id: int, text: str, parse_mode: str = "HTML", reply_markup: dict = None) -> bool:
        self.sent_messages.append((chat_id, text, parse_mode))
        self.last_reply_markup = reply_markup
        return True

    def send_chat_action(self, chat_id: int, action: str = "typing") -> bool:
        return True

    def answer_callback_query(self, callback_query_id: str, text: str = None, show_alert: bool = False) -> bool:
        return True

    def send_document(self, chat_id: int, filename: str, content: bytes, caption: str = "") -> bool:
        self.sent_documents.append((chat_id, filename, content, caption))
        return True

    def send_photo(self, chat_id: int, photo_bytes: bytes, caption: str = "", filename: str = "image.png") -> bool:
        self.sent_photos.append((chat_id, photo_bytes, caption, filename))
        return True


class TestTelegramBot(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmpdir.name)

        # Mock database setup
        self.db_path = self.tmp_path / "nmb.db"
        self.orig_live_env = os.environ.get("NMB_LIVE_DB")
        self.orig_persist_env = os.environ.get("NMB_PERSIST_DB")
        os.environ["NMB_LIVE_DB"] = str(self.db_path)
        os.environ["NMB_PERSIST_DB"] = str(self.db_path)

        conn = db.connect()
        db.init(conn)
        conn.close()

        self.cfg = Config()
        self.cfg.system.box_id = "test-box-01"
        self.cfg.telegram.enabled = True
        self.cfg.telegram.token = "123456:TEST_TOKEN"
        self.cfg.telegram.allowed_chat_ids = [999999]

        self.mock_client = MockTelegramClient()
        self.handler = CommandHandler(self.cfg, self.mock_client)
        self.alerts = AlertMonitor(self.cfg, self.mock_client)

    def tearDown(self):
        if self.orig_live_env is not None:
            os.environ["NMB_LIVE_DB"] = self.orig_live_env
        else:
            os.environ.pop("NMB_LIVE_DB", None)

        if self.orig_persist_env is not None:
            os.environ["NMB_PERSIST_DB"] = self.orig_persist_env
        else:
            os.environ.pop("NMB_PERSIST_DB", None)

        self.tmpdir.cleanup()

    def test_format_bytes(self):
        self.assertEqual(format_bytes(500), "500.0 B")
        self.assertEqual(format_bytes(2048), "2.0 KB")
        self.assertEqual(format_bytes(1048576 * 5), "5.0 MB")
        self.assertEqual(format_bytes(1073741824 * 3.5), "3.5 GB")

    def test_help_command(self):
        self.handler.handle_command(999999, "/help")
        self.assertEqual(len(self.mock_client.sent_messages), 1)
        chat_id, text, _ = self.mock_client.sent_messages[0]
        self.assertEqual(chat_id, 999999)
        self.assertIn("NetworkMeasureBox", text)
        self.assertIn("test-box-01", text)
        self.assertIn("/vpn", text)
        self.assertIn("/adblock", text)
        self.assertIn("/heal", text)
        self.assertIn("/tasks", text)

    def test_status_command(self):
        self.handler.handle_command(999999, "/status")
        self.assertEqual(len(self.mock_client.sent_messages), 1)
        _, text, _ = self.mock_client.sent_messages[0]
        self.assertTrue("System Status" in text or "Rendszerállapot" in text)
        self.assertTrue("Üzemmód" in text or "Mode" in text)

    def test_ping_command(self):
        self.handler.handle_command(999999, "/ping")
        self.assertEqual(len(self.mock_client.sent_messages), 1)
        _, text, _ = self.mock_client.sent_messages[0]
        self.assertTrue("Valós Idejű" in text or "Real-Time Probe Latency" in text)

    @patch("nmb.bot.commands.run_measurement_cycle", return_value=True)
    def test_speedtest_command(self, mock_cycle):
        # Insert mock test in speedtest table
        conn = db.connect()
        with db.tx(conn):
            conn.execute(
                """INSERT INTO speedtest (ts, trigger, status, down_bps, up_bps, ping_us, jitter_us, server_name, engine)
                   VALUES (?, 'telegram', 'ok', 500000000, 100000000, 8500, 1200, 'Test Mirror', 'cloudflare')""",
                (db.now_ms(),)
            )
        conn.close()

        self.handler.handle_command(999999, "/test cloudflare")
        mock_cycle.assert_called_once_with(
            self.cfg, trigger="telegram", force=True, run_port_check=True, engine="cloudflare"
        )
        self.assertEqual(len(self.mock_client.sent_messages), 2)
        _, result_text, _ = self.mock_client.sent_messages[1]
        self.assertTrue("CLOUDFLARE" in result_text)
        self.assertIn("500.0 Mbps", result_text)
        self.assertIn("100.0 Mbps", result_text)

    def test_vpn_status_and_clients(self):
        self.handler.handle_command(999999, "/vpn")
        self.assertEqual(len(self.mock_client.sent_messages), 1)
        _, text, _ = self.mock_client.sent_messages[0]
        self.assertIn("VPN Server Status", text)
        self.assertIn("1. WireGuard", text)
        self.assertIn("2. OpenVPN", text)

        self.handler.handle_command(999999, "/vpn clients")
        self.assertEqual(len(self.mock_client.sent_messages), 2)
        _, text2, _ = self.mock_client.sent_messages[1]
        self.assertIn("Configured VPN Clients:", text2)

    @patch("nmb.netd.wireguard.add_peer", autospec=True)
    @patch("nmb.netd.wireguard.get_client_config", autospec=True)
    @patch("nmb.netd.wireguard.get_client_qr_png_bytes", autospec=True)
    def test_vpn_add_wireguard_peer(self, mock_qr, mock_conf, mock_add):
        mock_add.return_value = {
            "id": "peer-uuid-1",
            "name": "testphone",
            "allowed_ips": "10.66.66.2/32"
        }
        mock_conf.return_value = "[Interface]\nPrivateKey = abc\nAddress = 10.66.66.2/32\n"
        mock_qr.return_value = b"\x89PNG\r\n\x1a\nfake_png_data"

        self.handler.handle_command(999999, "/vpn add testphone")

        mock_add.assert_called_once()
        # Should send 1 photo (QR) and 1 document (.conf)
        self.assertEqual(len(self.mock_client.sent_photos), 1)
        chat_id, photo_bytes, caption, fname = self.mock_client.sent_photos[0]
        self.assertEqual(chat_id, 999999)
        self.assertEqual(photo_bytes, b"\x89PNG\r\n\x1a\nfake_png_data")
        self.assertIn("WireGuard client created", caption)

        self.assertEqual(len(self.mock_client.sent_documents), 1)
        doc_chat, doc_fname, doc_bytes, doc_cap = self.mock_client.sent_documents[0]
        self.assertEqual(doc_fname, "testphone.conf")
        self.assertIn(b"[Interface]", doc_bytes)

    @patch("nmb.netd.adblock.set_adblock_enabled", autospec=True)
    @patch("nmb.netd.adblock.add_blacklist_entry", autospec=True)
    @patch("nmb.netd.adblock.remove_blacklist_entry", autospec=True)
    @patch("nmb.netd.adblock.add_whitelist_entry", autospec=True)
    @patch("nmb.netd.adblock.trigger_gravity_update", autospec=True)
    def test_adblock_commands(self, mock_grav, mock_wl, mock_rm_bl, mock_bl, mock_set_en):
        # /adblock status
        self.handler.handle_command(999999, "/adblock")
        self.assertEqual(len(self.mock_client.sent_messages), 1)
        self.assertIn("DNS Ad-Blocker & Sinkhole", self.mock_client.sent_messages[0][1])

        # /adblock on
        self.handler.handle_command(999999, "/adblock on")
        mock_set_en.assert_called_with(True, self.cfg)
        self.assertIn("ENABLED", self.mock_client.sent_messages[1][1])

        # /adblock off
        self.handler.handle_command(999999, "/adblock off")
        mock_set_en.assert_called_with(False, self.cfg)
        self.assertIn("DISABLED", self.mock_client.sent_messages[2][1])

        # /adblock block tracker.com
        self.handler.handle_command(999999, "/adblock block tracker.com")
        mock_bl.assert_called_with("tracker.com")
        self.assertIn("Domain Blocked", self.mock_client.sent_messages[3][1])

        # /adblock unblock tracker.com
        self.handler.handle_command(999999, "/adblock unblock tracker.com")
        mock_rm_bl.assert_called_with("tracker.com")
        mock_wl.assert_called_with("tracker.com")
        self.assertIn("Domain Whitelisted", self.mock_client.sent_messages[4][1])

        # /adblock update
        self.handler.handle_command(999999, "/adblock update")
        mock_grav.assert_called_once()

        # /adblock guide
        self.handler.handle_command(999999, "/adblock guide")
        self.assertIn("Router DHCP DNS setup", self.mock_client.sent_messages[-1][1])

    @patch("nmb.common.heal.audit_system_health", autospec=True)
    @patch("nmb.common.heal.auto_heal_all", autospec=True)
    def test_heal_commands(self, mock_heal, mock_audit):
        mock_audit.return_value = {
            "critical_issues": 0,
            "services": {"nmb-netd": {"active": True}},
            "database": {"integrity_ok": True, "table_count": 12},
            "missing_binaries": [],
            "missing_symlinks": []
        }
        self.handler.handle_command(999999, "/heal")
        self.assertIn("ALL COMPONENTS HEALTHY", self.mock_client.sent_messages[1][1])

        mock_heal.return_value = {
            "repairs_executed": ["Restarted failed daemon nmb-probe"],
            "audit_after": {"critical_issues": 0}
        }
        self.handler.handle_command(999999, "/heal fix")
        self.assertIn("Repairs finished", self.mock_client.sent_messages[3][1])

    def test_tasks_command(self):
        self.handler.handle_command(999999, "/tasks")
        self.assertEqual(len(self.mock_client.sent_messages), 1)
        _, text, _ = self.mock_client.sent_messages[0]
        self.assertIn("System Resource Load & Process Table", text)
        self.assertIn("<b>CPU:</b>", text)
        self.assertIn("Memory:", text)

    @patch("nmb.netd.guest_wifi.scan_wifi_networks", autospec=True)
    def test_wifi_scan_command(self, mock_scan):
        mock_scan.return_value = [
            {"ssid": "Home-Guest", "signal": 88, "channel": 6, "security": "WPA2", "in_use": False}
        ]
        self.handler.handle_command(999999, "/wifi scan")
        self.assertIn("Home-Guest", self.mock_client.sent_messages[1][1])
        self.assertIn("88%", self.mock_client.sent_messages[1][1])

    @patch("nmb.common.backup.create_backup", autospec=True)
    def test_backup_create_command(self, mock_create):
        from pathlib import Path
        mock_create.return_value = (True, Path("/nonexistent/nmb-backup-test.tar.gz"), {"file_count": 3})
        self.handler.handle_command(999999, "/backup create test_snap")
        self.assertIn("System Backup Created", self.mock_client.sent_messages[1][1])
        self.assertIn("nmb-backup-test.tar.gz", self.mock_client.sent_messages[1][1])

    def test_drivers_command(self):
        self.handler.handle_command(999999, "/drivers")
        self.assertEqual(len(self.mock_client.sent_messages), 1)
        self.assertIn("Hardware Network Controllers & Drivers", self.mock_client.sent_messages[0][1])

    @patch("nmb.report.llm_bundle.generate_llm_diagnostic_bundle", autospec=True)
    def test_ai_bundle_command(self, mock_bundle):
        mock_bundle.return_value = "# NetworkMeasureBox AI Diagnostics\nAll systems nominal."
        self.handler.handle_command(999999, "/ai")
        self.assertEqual(len(self.mock_client.sent_documents), 1)
        _, filename, content, _ = self.mock_client.sent_documents[0]
        self.assertTrue(filename.endswith(".md"))
        self.assertIn(b"AI Diagnostics", content)

    def test_proactive_outage_alert(self):
        conn = db.connect()
        # Trigger outage alert
        with db.tx(conn):
            conn.execute(
                "INSERT INTO outage (start_ts, cause) VALUES (?, 'Core gateway unreachable')",
                (db.now_ms(),)
            )

        self.alerts.check_outages(conn)
        self.assertEqual(len(self.mock_client.sent_messages), 1)
        self.assertIn("CRITICAL NETWORK OUTAGE DETECTED", self.mock_client.sent_messages[0][1])

        # Second check while still ongoing: alert dedup prevents re-alerting!
        self.alerts.check_outages(conn)
        self.assertEqual(len(self.mock_client.sent_messages), 1)

        # Resolve outage
        with db.tx(conn):
            conn.execute(
                "UPDATE outage SET end_ts = ? WHERE end_ts IS NULL",
                (db.now_ms(),)
            )

        self.alerts.check_outages(conn)
        self.assertEqual(len(self.mock_client.sent_messages), 2)
        self.assertIn("NETWORK OUTAGE RESOLVED", self.mock_client.sent_messages[1][1])
        conn.close()


if __name__ == "__main__":
    unittest.main()
