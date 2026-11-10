"""OpenVPN client names can never reach the PKI's own files (CA, server key) — 2026-11-10."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from nmb.netd import openvpn


class ClientNameTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="nmb-test-ovpn-"))
        pki = self.tmp / "pki"
        pki.mkdir()
        for n in ("ca.crt", "ca.key", "server.crt", "server.key", "tls-crypt.key", "phone.crt", "phone.key"):
            (pki / n).write_text(f"-----{n}-----")
        clients = self.tmp / "clients.json"
        clients.write_text(json.dumps({"clients": [{"name": "phone"}]}))
        for p in (mock.patch.object(openvpn, "PKI_DIR", pki), mock.patch.object(openvpn, "CLIENTS_FILE", clients),
                  mock.patch.object(openvpn, "init_pki", return_value=None),
                  mock.patch.object(openvpn, "_ensure_dir", return_value=None)):
            p.start()
            self.addCleanup(p.stop)

    def test_profile_only_for_recorded_clients(self):
        for name in ("ca", "server", "tls-crypt", "../pki/ca", "", "nobody", "phone/../ca"):
            self.assertIsNone(openvpn.get_unified_ovpn_profile(name, endpoint_host="203.0.113.1"), name)
        profile = openvpn.get_unified_ovpn_profile("phone", endpoint_host="203.0.113.1")
        self.assertIsNotNone(profile)
        self.assertIn("-----phone.key-----", profile)
        self.assertNotIn("-----ca.key-----", profile)
        self.assertNotIn("-----server.key-----", profile)

    def test_reserved_names_cannot_be_created_or_deleted(self):
        for name in ("ca", "server", "CA", "tls-crypt", "dh"):
            self.assertEqual(openvpn.add_client(name)["status"], "error", name)
            self.assertFalse(openvpn.delete_client(name), name)
        self.assertTrue((openvpn.PKI_DIR / "ca.key").exists())
        self.assertTrue((openvpn.PKI_DIR / "server.key").exists())

    def test_name_rules(self):
        self.assertTrue(openvpn.valid_client_name("laptop_work-2"))
        for bad in ("a b", "x" * 65, "ca", "server", "../x", "a/b", ""):
            self.assertFalse(openvpn.valid_client_name(bad), bad)


class RevocationTest(unittest.TestCase):
    """A deleted client cannot connect again: ccd-exclusive with an allow-list kept by root."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="nmb-test-ovpn-ccd-"))
        self.pki = self.tmp / "pki"
        self.pki.mkdir()
        self.ccd = self.tmp / "ccd"
        self.clients = self.tmp / "clients.json"
        self.clients.write_text(json.dumps({"clients": [{"name": "phone"}, {"name": "laptop"}, {"name": "../evil"},
                                                        {"name": "ca"}]}))
        for n in ("phone.crt", "phone.key", "laptop.crt", "laptop.key"):
            (self.pki / n).write_text(n)
        self.helper = mock.patch.object(openvpn, "run_helper", return_value=(0, ""))
        for p in (mock.patch.object(openvpn, "PKI_DIR", self.pki), mock.patch.object(openvpn, "CLIENTS_FILE", self.clients),
                  mock.patch.object(openvpn, "CCD_DIR", self.ccd), mock.patch.object(openvpn, "_ensure_dir", return_value=None)):
            p.start()
            self.addCleanup(p.stop)
        self.run_helper = self.helper.start()
        self.addCleanup(self.helper.stop)

    def test_server_config_enforces_the_allow_list(self):
        conf = openvpn.generate_server_config()
        self.assertIn(f"client-config-dir {self.ccd}", conf)
        self.assertIn("\nccd-exclusive\n", conf)

    def test_allow_list_has_only_valid_recorded_clients(self):
        (self.ccd).mkdir()
        (self.ccd / "old-client").write_text("")
        self.assertEqual(openvpn.write_ccd_allowlist(), 2)
        self.assertEqual(sorted(p.name for p in self.ccd.iterdir()), ["laptop", "phone"])
        self.assertFalse((self.tmp / "evil").exists())

    def test_delete_revokes_and_restarts(self):
        self.assertTrue(openvpn.delete_client("phone"))
        self.run_helper.assert_called_with("openvpn-ccd-revoke")
        self.assertFalse((self.pki / "phone.key").exists())
        openvpn.write_ccd_allowlist()
        self.assertEqual(sorted(p.name for p in self.ccd.iterdir()), ["laptop"])

    def test_old_config_without_final_newline_gets_separate_lines(self):
        import subprocess
        helper = Path(__file__).resolve().parent.parent / "bin" / "nmb-helper"
        funcs = helper.read_text().split('case "${1:-}" in')[0].split("cd / || exit 1", 1)[1]
        conf = self.tmp / "server.conf"
        conf.write_text("port 1194\nverb 3")                       # no newline at the end, like older files
        for _ in range(2):                                          # running twice adds nothing more
            subprocess.run(["sh", "-c", funcs + f'append_ccd_directives "{conf}"'], check=True)
        self.assertEqual(conf.read_text().splitlines(),
                         ["port 1194", "verb 3", "client-config-dir /etc/openvpn/nmb-ccd", "ccd-exclusive"])
        self.assertTrue(openvpn.generate_server_config().endswith("\n"))

    def test_helper_script_keeps_the_allow_list(self):
        helper = (Path(__file__).resolve().parent.parent / "bin" / "nmb-helper").read_text()
        self.assertIn("openvpn-ccd-revoke)", helper)
        self.assertIn("python3 -I", helper)
        apply_block = helper.split("    openvpn-apply)")[1].split(";;")[0]
        self.assertIn("openvpn_ccd_sync", apply_block)


if __name__ == "__main__":
    unittest.main()
