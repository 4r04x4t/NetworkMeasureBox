"""Central collector: boxes send with consent, the collector stores, finds and controls."""
import base64
import json
import os
import sqlite3
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from nmb.collector import client
from nmb.collector import server as col

SCHEMA = (Path(__file__).resolve().parent.parent / "nmb" / "db" / "schema.sql").read_text()


def _cfg(url="", token="", **kw):
    co = SimpleNamespace(enabled=True, url=url, token=token, case_id="TICKET-42", interval_min=15,
                         share_diagnostics=False, allow_remote_control=False)
    for k, v in kw.items():
        setattr(co, k, v)
    return SimpleNamespace(collector=co, system=SimpleNamespace(box_id="nmb-01"),
                           isp=SimpleNamespace(name="DIGI", account_id="C-1001", contract_down_mbps=1000.0,
                                               contract_up_mbps=300.0, connection_type="fiber"))


def _box_db():
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.executescript(SCHEMA)
    now = int(time.time() * 1000)
    conn.execute("INSERT INTO speedtest (ts, trigger, status, engine, down_bps, up_bps, ping_us, server_name) "
                 "VALUES (?, 'schedule', 'ok', 'rtr', 600000000, 300000000, 11000, 'RTR')", (now - 60000,))
    conn.execute("INSERT INTO speedtest (ts, trigger, status, engine, error) VALUES (?, 'schedule', 'error', 'ookla', 'refused')", (now,))
    tid = conn.execute("SELECT id FROM target ORDER BY id LIMIT 1").fetchone()[0]
    hour = (int(time.time() // 3600) - 2) * 3600 * 1000
    conn.execute("INSERT INTO ping_minute (ts, target_id, sent, lost, rtt_min, rtt_avg, rtt_max, jitter_us) VALUES (?, ?, 120, 1, 8000, 9000, 20000, 500)", (hour, tid))
    conn.execute("INSERT INTO event (ts, severity, source, kind, detail) VALUES (?, 'warn', 'probe', 'outage_start', 'WAN down')", (now,))
    conn.commit()
    return conn


class CollectorTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        data = Path(self.tmp.name)
        settings = col.Settings(data)
        settings.set_password("correct horse battery")
        self.token = settings.add_token("support")
        self.httpd = col.make_server(data, "127.0.0.1", 0)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.uid_patch = mock.patch.object(client, "UID_FILE", data / "box_uid")
        self.uid_patch.start()

    def tearDown(self):
        self.uid_patch.stop()
        self.httpd.shutdown()
        self.httpd.server_close()
        self.tmp.cleanup()

    def _get(self, path, password="correct horse battery"):
        req = urllib.request.Request(self.url + path)
        if password:
            req.add_header("Authorization", "Basic " + base64.b64encode(f"admin:{password}".encode()).decode())
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.read().decode()

    def test_box_id_is_unique_and_kept(self):
        a = client.box_uid()
        self.assertRegex(a, r"^nmb-[a-z2-9]{4}-[a-z2-9]{4}-[a-z2-9]{4}$")
        self.assertEqual(client.box_uid(), a)

    def test_upload_search_and_export(self):
        conn = _box_db()
        res = client.send_now(_cfg(self.url, self.token), conn)
        self.assertTrue(res["ok"], res)
        self.assertEqual((res["speedtests"], res["ping_hours"]), (2, 1))
        # Sending again adds nothing.
        self.assertEqual(client.send_now(_cfg(self.url, self.token), conn)["speedtests"], 0)

        uid = client.box_uid()
        found = json.loads(self._get("/api/boxes?q=TICKET-42"))["boxes"]
        self.assertEqual([b["box_uid"] for b in found], [uid])
        self.assertEqual(json.loads(self._get("/api/boxes?q=C-1001"))["boxes"][0]["box_uid"], uid)
        summary = json.loads(self._get(f"/api/box/{uid}"))
        self.assertEqual((summary["ok_tests"], summary["failed_tests"]), (1, 1))
        self.assertIn("600000000", self._get(f"/box/{uid}/speedtests.csv"))
        self.assertIn("TICKET-42", self._get(f"/box/{uid}"))

    def test_earlier_case_number_still_finds_the_box(self):
        conn = _box_db()
        client.send_now(_cfg(self.url, self.token), conn)
        client.send_now(_cfg(self.url, self.token, case_id="TICKET-99"), conn)
        self.assertEqual(len(json.loads(self._get("/api/boxes?q=TICKET-42"))["boxes"]), 1)

    def test_diagnostics_and_events_only_with_consent(self):
        conn = _box_db()
        client.send_now(_cfg(self.url, self.token), conn)
        uid = client.box_uid()
        self.assertIn("has not shared", self._get(f"/box/{uid}?lang=en"))
        with mock.patch("nmb.report.llm_bundle.generate_llm_diagnostic_bundle", return_value="# Diagnostics\nroute default via 192.0.2.1"):
            client.send_now(_cfg(self.url, self.token, share_diagnostics=True), conn)
        page = self._get(f"/box/{uid}/diagnostics")
        self.assertIn("route default via 192.0.2.1", page)
        self.assertIn("WAN down", self._get(f"/box/{uid}"))

    def test_wrong_token_and_no_password_are_refused(self):
        res = client.send_now(_cfg(self.url, "nmbc_wrong"), _box_db())
        self.assertFalse(res["ok"])
        self.assertIn("token", res["message"])
        with self.assertRaises(urllib.error.HTTPError) as e:
            self._get("/", password=None)
        self.assertEqual(e.exception.code, 401)
        with self.assertRaises(urllib.error.HTTPError):
            self._get("/", password="wrong")

    def _admin_post(self, path, form, origin=True):
        data = "&".join(f"{k}={v}" for k, v in form.items()).encode()
        req = urllib.request.Request(self.url + path, data=data, method="POST")
        req.add_header("Authorization", "Basic " + base64.b64encode(b"admin:correct horse battery").decode())
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        if origin:
            req.add_header("Origin", self.url)
        else:
            req.add_header("Origin", "https://evil.example")
        opener = urllib.request.build_opener(type("NoRedirect", (urllib.request.HTTPRedirectHandler,), {"redirect_request": lambda *a, **k: None}))
        try:
            return opener.open(req, timeout=10).status
        except urllib.error.HTTPError as e:
            return e.code

    def test_remote_control_with_consent(self):
        conn = _box_db()
        cfg = _cfg(self.url, self.token, allow_remote_control=True)
        client.send_now(cfg, conn)
        uid = client.box_uid()
        self.assertEqual(self._admin_post(f"/box/{uid}/command", {"kind": "speedtest", "engine": "cloudflare", "server_id": ""}), 303)
        self.assertEqual(self._admin_post(f"/box/{uid}/command", {"kind": "speedtest", "engine": "cloudflare"}, origin=False), 403)
        self.assertEqual(self._admin_post(f"/box/{uid}/command", {"kind": "shell", "cmd": "id"}), 400)
        with mock.patch("nmb.speed.runner.run_measurement_cycle", return_value=True) as run, \
             mock.patch.object(client, "send_now", return_value={"ok": True, "message": "sent"}):
            self.assertEqual(client.poll_once(cfg), 1)
            run.assert_called_once()
            self.assertEqual(run.call_args.kwargs["engine"], "cloudflare")
            client.poll_once(cfg)  # reports the result
        self.assertIn("finished", self._get(f"/box/{uid}"))

    def test_no_remote_control_without_consent(self):
        conn = _box_db()
        cfg = _cfg(self.url, self.token, allow_remote_control=True)
        client.send_now(cfg, conn)
        uid = client.box_uid()
        self._admin_post(f"/box/{uid}/command", {"kind": "upload"})
        cfg.collector.allow_remote_control = False
        client.send_now(cfg, conn)  # the box withdraws consent
        self.assertEqual(self._admin_post(f"/box/{uid}/command", {"kind": "upload"}), 400)
        with mock.patch.object(client, "run_command") as run:
            client.poll_once(cfg)
            run.assert_not_called()
        self.assertIn("refused", self._get(f"/box/{uid}"))

    def test_box_rejects_unknown_commands(self):
        cfg = _cfg(self.url, self.token, allow_remote_control=True)
        self.assertFalse(client.run_command(cfg, {"kind": "shell", "args": {"cmd": "id"}})["ok"])
        self.assertFalse(client.run_command(cfg, {"kind": "speedtest", "args": {"engine": "x; rm -rf /"}})["ok"])

    def test_secrets_are_stored_as_hashes(self):
        stored = (Path(self.tmp.name) / "collector.json").read_text()
        self.assertNotIn(self.token, stored)
        self.assertNotIn("correct horse battery", stored)
        self.assertEqual(oct(os.stat(Path(self.tmp.name) / "collector.json").st_mode & 0o777), "0o600")


if __name__ == "__main__":
    unittest.main()
