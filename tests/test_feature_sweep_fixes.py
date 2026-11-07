"""Regressions found by the feature sweep in virtual machines (see docs/TESTING.md)."""
import socket
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from nmb.netd import guest_wifi, openvpn, proxy, services


class ProxyTargetTest(unittest.TestCase):
    def test_box_local_targets_are_refused(self):
        for ip in ("127.0.0.1", "::1", "169.254.169.254", "fe80::1", "0.0.0.0", "::ffff:127.0.0.1"):
            self.assertTrue(proxy._is_forbidden_target(ip), ip)

    def test_lan_and_internet_targets_are_allowed(self):
        for ip in ("192.168.100.20", "10.0.2.2", "1.1.1.1", "2606:4700::1111"):
            self.assertFalse(proxy._is_forbidden_target(ip), ip)

    def test_interleave_starts_with_ipv6(self):
        self.assertEqual(proxy._interleave(["1.1.1.1", "2.2.2.2", "::1", "::2"]), ["::1", "1.1.1.1", "::2", "2.2.2.2"])

    def test_dead_address_does_not_delay_a_live_one(self):
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(("127.0.0.2", 0))
        listener.listen(1)
        port = listener.getsockname()[1]
        real = socket.create_connection

        def fake(addr, timeout=None):
            if addr[0] == "2001:db8::1":  # a blackholed IPv6 address
                time.sleep(3)
                raise OSError("timed out")
            return real(("127.0.0.2", addr[1]), timeout=timeout)  # 192.0.2.10 stands in for a live host

        with mock.patch.object(proxy.socket, "create_connection", side_effect=fake):
            start = time.monotonic()
            sock = proxy.connect_first(["2001:db8::1", "192.0.2.10"], port, timeout=5)
            took = time.monotonic() - start
        sock.close()
        listener.close()
        self.assertLess(took, 1.5)

    def test_stop_releases_the_port(self):
        srv = proxy.ProxyServer(host="127.0.0.1", port=0, listen_ipv6=False)
        ok, _ = srv.start()
        self.assertTrue(ok)
        port = srv.sock.getsockname()[1]
        srv.stop()
        srv.thread.join(2)
        self.assertFalse(srv.thread.is_alive())
        probe = socket.socket()
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind(("127.0.0.1", port))
        probe.close()


class GuestWifiStateTest(unittest.TestCase):
    def _status(self, dev_show: str, scan):
        def run(cmd, timeout=15.0):
            return 0, dev_show, ""
        with mock.patch.object(guest_wifi.shutil, "which", return_value="/usr/bin/nmcli"), \
             mock.patch.object(guest_wifi, "_run_cmd", side_effect=run), \
             mock.patch.object(guest_wifi, "scan_wifi_networks", return_value=scan):
            return guest_wifi.get_guest_wifi_status(iface="wlan1")

    def test_disconnected_is_not_connected(self):
        stale = [{"in_use": True, "ssid": "Cafe", "bssid": "x", "channel": 6, "signal": 90, "security": "WPA2"}]
        res = self._status("GENERAL.STATE:30 (disconnected)\nGENERAL.CONNECTION:--\n", stale)
        self.assertFalse(res["connected"])

    def test_connected_state(self):
        res = self._status("GENERAL.STATE:100 (connected)\nGENERAL.CONNECTION:Cafe\n", [])
        self.assertTrue(res["connected"])

    def test_run_cmd_returns_the_real_error(self):
        code, _, err = guest_wifi._run_cmd(["sh", "-c", "echo key-mgmt missing >&2; exit 4"])
        self.assertEqual(code, 4)
        self.assertIn("key-mgmt missing", err)


class OpenVpnCertificateTest(unittest.TestCase):
    def test_server_certificate_allows_tls_server_auth(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            run = lambda *a: subprocess.run(list(a), check=True, capture_output=True)
            run("openssl", "ecparam", "-name", "prime256v1", "-genkey", "-noout", "-out", str(d / "ca.key"))
            run("openssl", "req", "-new", "-x509", "-days", "1", "-key", str(d / "ca.key"), "-out", str(d / "ca.crt"), "-subj", "/CN=t")
            run("openssl", "ecparam", "-name", "prime256v1", "-genkey", "-noout", "-out", str(d / "s.key"))
            run("openssl", "req", "-new", "-key", str(d / "s.key"), "-out", str(d / "s.csr"), "-subj", "/CN=s")
            openvpn._sign_csr(d / "s.csr", d / "s.crt", d / "ca.crt", d / "ca.key", "serverAuth")
            self.assertTrue(openvpn._has_server_usage(d / "s.crt"))
            run("openssl", "x509", "-req", "-days", "1", "-in", str(d / "s.csr"), "-CA", str(d / "ca.crt"),
                "-CAkey", str(d / "ca.key"), "-CAcreateserial", "-out", str(d / "old.crt"))
            self.assertFalse(openvpn._has_server_usage(d / "old.crt"))


class HostapdFallbackTest(unittest.TestCase):
    def test_last_attempt_is_plain_2ghz(self):
        last = services.HOSTAPD_ATTEMPTS[-1]
        self.assertEqual(last["wifi_band"], "2.4ghz")
        self.assertEqual(last["wifi_standard"], "n")


class VersionTest(unittest.TestCase):
    def test_app_version_is_the_latest_release(self):
        import re
        from nmb.common import backup
        text = (Path(__file__).resolve().parent.parent / "CHANGELOG.md").read_text()
        latest = re.search(r"^## \[(\d+\.\d+\.\d+)\]", text, re.M).group(1)
        self.assertEqual(backup.APP_VERSION, latest)


if __name__ == "__main__":
    unittest.main()
