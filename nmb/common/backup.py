"""NetworkMeasureBox Unified Backup and Disaster Recovery Engine.

Provides atomic, consistent backup creation and restoration for:
- Complete system configuration (/etc/nmb/nmb.conf)
- Persistent and live SQLite measurement database (via SQLite online backup API)
- WireGuard keys, peer list, and server configuration
- OpenVPN PKI, server keys, and client certificates
- Hardware identity and MAC records
- Manifest with SHA-256 integrity verification
- Safe rollback protection with automatic pre-restore checkpoints
"""
from __future__ import annotations

import configparser
import datetime
import hashlib
import io
import json
import logging
import os
import shutil
import socket
import sqlite3
import subprocess
import tarfile
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger("nmb.common.backup")

APP_VERSION = "2.4.0"
BACKUP_DIR = Path(os.environ.get("NMB_BACKUP_DIR", "/var/lib/nmb/backups"))
CONFIG_PATH = Path(os.environ.get("NMB_CONFIG", "/etc/nmb/nmb.conf"))
PERSIST_DB_PATH = Path(os.environ.get("NMB_PERSIST_DB", "/var/lib/nmb/persist/nmb.db"))
LIVE_DB_PATH = Path(os.environ.get("NMB_LIVE_DB", "/var/lib/nmb/live/nmb.db"))
WG_DIR = Path(os.environ.get("NMB_WG_DIR", "/var/lib/nmb/wireguard"))
OV_DIR = Path(os.environ.get("NMB_OV_DIR", "/var/lib/nmb/openvpn"))
RMBT_UUID_PATH = Path("/var/lib/nmb/.rmbt_client_uuid")
FACTORY_MAC_PATH = Path("/etc/nmb/factory_mac_eth0")
RESOLV_ORIG_PATH = Path("/etc/nmb/resolv.conf.system_orig")


def _ensure_backup_dir() -> Path:
    """Ensure local backup directory exists with proper restrictive permissions."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(BACKUP_DIR, 0o750)
    except Exception:
        pass
    return BACKUP_DIR


def _sha256_file(path: Path) -> str:
    """Compute SHA-256 hex digest of a file in streaming chunks."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def _format_bytes(bytes_count: int) -> str:
    """Format bytes count into human-readable string."""
    if bytes_count <= 0:
        return "0 B"
    sizes = ["B", "KB", "MB", "GB"]
    k = 1024
    i = 0
    val = float(bytes_count)
    while val >= k and i < len(sizes) - 1:
        val /= k
        i += 1
    return f"{val:.1f} {sizes[i]}"


def run_helper(cmd: str) -> Tuple[int, str]:
    """Execute privileged system action via nmb-helper."""
    helper_paths = ["/usr/local/bin/nmb-helper", "/opt/nmb/bin/nmb-helper"]
    helper = None
    for p in helper_paths:
        if os.path.exists(p) and os.access(p, os.X_OK):
            helper = p
            break
    if not helper:
        helper = "nmb-helper"

    try:
        proc = subprocess.run(
            ["sudo", "-n", helper, cmd],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        return proc.returncode, proc.stdout + proc.stderr
    except Exception as e:
        return 1, str(e)


def create_backup(
    backup_type: str = "full",
    comment: str = "",
    target_dir: Optional[Path] = None,
    custom_filename: Optional[str] = None,
) -> Tuple[bool, Path, Dict[str, Any]]:
    """Create a verified, consistent .tar.gz backup archive.

    Args:
        backup_type: 'full' (config + DB + VPN keys) or 'config' (config + VPN keys without DB)
        comment: User-supplied description / label for this snapshot
        target_dir: Destination directory (defaults to BACKUP_DIR)
        custom_filename: Optional explicit filename

    Returns:
        (success, archive_path, manifest_dict)
    """
    dest_dir = target_dir or _ensure_backup_dir()
    dest_dir.mkdir(parents=True, exist_ok=True)

    b_type = "config" if backup_type.lower() == "config" else "full"
    ts_now = time.time()
    dt_now = datetime.datetime.fromtimestamp(ts_now, datetime.timezone.utc)
    ts_str = dt_now.strftime("%Y%m%d-%H%M%S")

    if not custom_filename:
        safe_comment_slug = ""
        if comment:
            clean = "".join(c for c in comment if c.isalnum() or c in "-_")[:20]
            if clean:
                safe_comment_slug = f"-{clean}"
        archive_name = f"nmb-backup-{b_type}-{ts_str}{safe_comment_slug}.tar.gz"
    else:
        archive_name = custom_filename

    final_archive_path = dest_dir / archive_name

    staging_dir = Path(tempfile.mkdtemp(prefix="nmb-backup-stage-"))
    try:
        manifest_files: Dict[str, Dict[str, Any]] = {}

        # 1. Configuration files
        cfg_stage_dir = staging_dir / "config"
        cfg_stage_dir.mkdir(parents=True, exist_ok=True)
        if CONFIG_PATH.exists():
            cfg_dst = cfg_stage_dir / "nmb.conf"
            shutil.copy2(CONFIG_PATH, cfg_dst)
            manifest_files["config/nmb.conf"] = {
                "size": cfg_dst.stat().st_size,
                "sha256": _sha256_file(cfg_dst),
            }

        if FACTORY_MAC_PATH.exists():
            mac_dst = cfg_stage_dir / "factory_mac_eth0"
            shutil.copy2(FACTORY_MAC_PATH, mac_dst)
            manifest_files["config/factory_mac_eth0"] = {
                "size": mac_dst.stat().st_size,
                "sha256": _sha256_file(mac_dst),
            }

        if RESOLV_ORIG_PATH.exists():
            res_dst = cfg_stage_dir / "resolv.conf.system_orig"
            shutil.copy2(RESOLV_ORIG_PATH, res_dst)
            manifest_files["config/resolv.conf.system_orig"] = {
                "size": res_dst.stat().st_size,
                "sha256": _sha256_file(res_dst),
            }

        # 2. WireGuard definitions & keys
        if WG_DIR.exists():
            wg_stage_dir = staging_dir / "wireguard"
            wg_stage_dir.mkdir(parents=True, exist_ok=True)
            for item in WG_DIR.iterdir():
                if item.is_file() and not item.name.endswith((".tmp", ".log", ".sock", ".pid")):
                    dst_item = wg_stage_dir / item.name
                    try:
                        shutil.copy2(item, dst_item)
                        manifest_files[f"wireguard/{item.name}"] = {
                            "size": dst_item.stat().st_size,
                            "sha256": _sha256_file(dst_item),
                        }
                    except PermissionError:
                        log.warning("Skipping unreadable wireguard file: %s", item)

        # 3. OpenVPN PKI, keys & certificates
        if OV_DIR.exists():
            ov_stage_dir = staging_dir / "openvpn"
            ov_stage_dir.mkdir(parents=True, exist_ok=True)
            # Copy clients.json, server.conf, and skip ephemeral lease/log/socket files (e.g. ipp.txt)
            ignored_ov_names = {"ipp.txt", "openvpn-status.log", "openvpn.sock"}
            for item in OV_DIR.iterdir():
                if (
                    item.is_file()
                    and item.name not in ignored_ov_names
                    and not item.name.endswith((".tmp", ".log", ".sock", ".pid"))
                ):
                    dst_item = ov_stage_dir / item.name
                    try:
                        shutil.copy2(item, dst_item)
                        manifest_files[f"openvpn/{item.name}"] = {
                            "size": dst_item.stat().st_size,
                            "sha256": _sha256_file(dst_item),
                        }
                    except PermissionError:
                        log.warning("Skipping unreadable openvpn file: %s", item)
            # Copy pki subdirectory
            pki_dir = OV_DIR / "pki"
            if pki_dir.exists() and pki_dir.is_dir():
                dst_pki = ov_stage_dir / "pki"
                dst_pki.mkdir(parents=True, exist_ok=True)
                for cert_file in pki_dir.iterdir():
                    if cert_file.is_file() and not cert_file.name.endswith((".tmp", ".log")):
                        dst_cert = dst_pki / cert_file.name
                        try:
                            shutil.copy2(cert_file, dst_cert)
                            manifest_files[f"openvpn/pki/{cert_file.name}"] = {
                                "size": dst_cert.stat().st_size,
                                "sha256": _sha256_file(dst_cert),
                            }
                        except PermissionError:
                            log.warning("Skipping unreadable cert file: %s", cert_file)

        # 4. RMBT Client UUID
        if RMBT_UUID_PATH.exists():
            rmbt_dst = staging_dir / "rmbt_client_uuid"
            shutil.copy2(RMBT_UUID_PATH, rmbt_dst)
            manifest_files["rmbt_client_uuid"] = {
                "size": rmbt_dst.stat().st_size,
                "sha256": _sha256_file(rmbt_dst),
            }

        # 5. Database (only for full backup)
        if b_type == "full":
            db_stage_dir = staging_dir / "database"
            db_stage_dir.mkdir(parents=True, exist_ok=True)
            db_dst = db_stage_dir / "nmb.db"

            db_source = LIVE_DB_PATH if LIVE_DB_PATH.exists() else PERSIST_DB_PATH
            if db_source.exists():
                try:
                    # Online consistent SQLite backup to avoid WAL locks or corruption
                    src_conn = sqlite3.connect(f"file:{db_source}?mode=ro", uri=True)
                    dst_conn = sqlite3.connect(db_dst)
                    try:
                        src_conn.backup(dst_conn, pages=4096)
                        dst_conn.execute("PRAGMA journal_mode=DELETE")
                        dst_conn.commit()
                    finally:
                        dst_conn.close()
                        src_conn.close()
                except Exception as e:
                    log.warning("SQLite online backup exception: %s, falling back to copy", e)
                    shutil.copy2(db_source, db_dst)

                if db_dst.exists():
                    manifest_files["database/nmb.db"] = {
                        "size": db_dst.stat().st_size,
                        "sha256": _sha256_file(db_dst),
                    }

        # 6. Generate Manifest metadata
        manifest: Dict[str, Any] = {
            "manifest_version": 1,
            "app": "NetworkMeasureBox",
            "nmb_version": APP_VERSION,
            "backup_type": b_type,
            "created_at": ts_now,
            "created_at_iso": dt_now.isoformat(),
            "hostname": socket.gethostname(),
            "comment": comment or ("Full System Backup" if b_type == "full" else "Configuration Only Backup"),
            "files": manifest_files,
            "total_files": len(manifest_files),
        }

        manifest_path = staging_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        # 7. Pack into tar.gz atomically
        temp_archive = final_archive_path.with_suffix(".tar.gz.tmp")
        with tarfile.open(temp_archive, "w:gz") as tar:
            for root, _, files in os.walk(staging_dir):
                for f in sorted(files):
                    f_full = Path(root) / f
                    rel_path = f_full.relative_to(staging_dir).as_posix()
                    tarinfo = tar.gettarinfo(str(f_full), arcname=rel_path)
                    tarinfo.uid = 0
                    tarinfo.gid = 0
                    tarinfo.uname = "root"
                    tarinfo.gname = "root"
                    tarinfo.mtime = int(ts_now)
                    with open(f_full, "rb") as fp:
                        tar.addfile(tarinfo, fp)

        temp_archive.replace(final_archive_path)
        os.chmod(final_archive_path, 0o640)

        manifest["archive_size"] = final_archive_path.stat().st_size
        manifest["archive_size_human"] = _format_bytes(manifest["archive_size"])
        manifest["archive_sha256"] = _sha256_file(final_archive_path)
        manifest["archive_path"] = str(final_archive_path)
        manifest["filename"] = final_archive_path.name

        log.info(
            "Created %s backup: %s (%s, %d files)",
            b_type,
            final_archive_path.name,
            manifest["archive_size_human"],
            len(manifest_files),
        )
        return True, final_archive_path, manifest

    except Exception as e:
        log.error("Failed to create backup: %s", e, exc_info=True)
        return False, final_archive_path, {"error": str(e)}
    finally:
        shutil.rmtree(staging_dir, ignore_errors=True)


def verify_backup(archive_path: Path) -> Tuple[bool, str, Dict[str, Any]]:
    """Validate archive integrity, structure, checksums, and schema.

    Returns:
        (is_valid, status_message, manifest_data)
    """
    if not archive_path.exists() or not archive_path.is_file():
        return False, "Archive file does not exist.", {}

    if not tarfile.is_tarfile(archive_path):
        return False, "File is not a valid tar/gzip archive.", {}

    try:
        with tarfile.open(archive_path, "r:gz") as tar:
            # 1. Security: Path Traversal check
            for member in tar.getmembers():
                if member.name.startswith("/") or ".." in member.name.split("/"):
                    return False, f"Security violation: path traversal detected ({member.name}).", {}

            # 2. Check manifest.json
            try:
                mf_file = tar.extractfile("manifest.json")
                if not mf_file:
                    return False, "Archive is missing manifest.json metadata.", {}
                manifest = json.loads(mf_file.read().decode("utf-8"))
            except Exception as e:
                return False, f"Corrupted or invalid manifest.json: {e}", {}

            # 3. Check recorded files & checksums
            manifest_files = manifest.get("files", {})
            for rel_path, meta in manifest_files.items():
                try:
                    f = tar.extractfile(rel_path)
                    if not f:
                        return False, f"Missing component in archive: {rel_path}", manifest
                    content = f.read()
                    if len(content) != meta.get("size", -1):
                        return False, f"Size mismatch for {rel_path}: expected {meta.get('size')} bytes, got {len(content)}", manifest
                    actual_sha = hashlib.sha256(content).hexdigest()
                    if actual_sha != meta.get("sha256"):
                        return False, f"Checksum verification failed for {rel_path}", manifest
                except KeyError:
                    return False, f"Manifest lists '{rel_path}' which is missing in archive.", manifest

            # 4. Validate nmb.conf parsing if present
            if "config/nmb.conf" in manifest_files:
                f = tar.extractfile("config/nmb.conf")
                if f:
                    cfg_text = f.read().decode("utf-8", errors="replace")
                    parser = configparser.ConfigParser()
                    try:
                        parser.read_string(cfg_text)
                    except Exception as e:
                        return False, f"nmb.conf syntax validation failed: {e}", manifest

            # 5. Validate SQLite database integrity if present
            if "database/nmb.db" in manifest_files:
                f = tar.extractfile("database/nmb.db")
                if f:
                    tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
                    try:
                        tmp_db.write(f.read())
                        tmp_db.close()
                        conn = sqlite3.connect(tmp_db.name)
                        res = conn.execute("PRAGMA quick_check;").fetchone()
                        conn.close()
                        if not res or res[0] != "ok":
                            return False, "SQLite database quick_check integrity failed.", manifest
                    finally:
                        try:
                            os.unlink(tmp_db.name)
                        except Exception:
                            pass

        return True, "Archive verified successfully: structure and checksums are intact.", manifest

    except Exception as e:
        log.error("Archive verification error: %s", e)
        return False, f"Failed to inspect archive: {e}", {}


def restore_backup(
    archive_path: Path,
    restore_db: bool = True,
    restore_vpn: bool = True,
    create_safety_snapshot: bool = True,
) -> Tuple[bool, str]:
    """Safely restore system state from a verified backup archive.

    Performs automatic pre-restore safety snapshot before modifying any system state.
    Restores configurations, SQLite measurements, and cryptographic keys atomically.
    """
    is_valid, msg, manifest = verify_backup(archive_path)
    if not is_valid:
        return False, f"Cannot restore invalid backup archive: {msg}"

    # 1. Automatic safety snapshot before applying restore
    if create_safety_snapshot:
        try:
            create_backup(
                backup_type="full",
                comment="Automatic pre-restore safety checkpoint",
                custom_filename=f"nmb-safety-prerestore-{int(time.time())}.tar.gz",
            )
        except Exception as e:
            log.warning("Pre-restore safety snapshot creation had warning: %s", e)

    temp_extract = Path(tempfile.mkdtemp(prefix="nmb-restore-"))
    try:
        with tarfile.open(archive_path, "r:gz") as tar:
            tar.extractall(temp_extract)

        restored_items: List[str] = []

        # 2. Restore Configuration (/etc/nmb/nmb.conf)
        src_cfg = temp_extract / "config" / "nmb.conf"
        if src_cfg.exists():
            CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
            tmp_cfg = CONFIG_PATH.with_suffix(".tmp")
            shutil.copy2(src_cfg, tmp_cfg)
            os.chmod(tmp_cfg, 0o600)
            tmp_cfg.replace(CONFIG_PATH)
            restored_items.append("nmb.conf")

        # Restore system resolv/MAC files if included
        src_mac = temp_extract / "config" / "factory_mac_eth0"
        if src_mac.exists() and not FACTORY_MAC_PATH.exists():
            shutil.copy2(src_mac, FACTORY_MAC_PATH)

        # 3. Restore Database
        src_db = temp_extract / "database" / "nmb.db"
        if restore_db and src_db.exists():
            PERSIST_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
            tmp_db = PERSIST_DB_PATH.with_suffix(".tmp")
            shutil.copy2(src_db, tmp_db)
            os.chmod(tmp_db, 0o640)
            tmp_db.replace(PERSIST_DB_PATH)

            # Hydrate live DB on tmpfs as well
            if LIVE_DB_PATH.parent.exists():
                tmp_live = LIVE_DB_PATH.with_suffix(".tmp")
                shutil.copy2(src_db, tmp_live)
                os.chmod(tmp_live, 0o640)
                tmp_live.replace(LIVE_DB_PATH)
            restored_items.append("SQLite Database")

        # 4. Restore WireGuard keys & configuration
        src_wg = temp_extract / "wireguard"
        if restore_vpn and src_wg.exists() and src_wg.is_dir():
            WG_DIR.mkdir(parents=True, exist_ok=True)
            os.chmod(WG_DIR, 0o700)
            for item in src_wg.iterdir():
                if item.is_file():
                    dst_f = WG_DIR / item.name
                    shutil.copy2(item, dst_f)
                    os.chmod(dst_f, 0o600)
            restored_items.append("WireGuard VPN keys & peers")
            run_helper("wireguard-apply")

        # 5. Restore OpenVPN PKI & certificates
        src_ov = temp_extract / "openvpn"
        if restore_vpn and src_ov.exists() and src_ov.is_dir():
            OV_DIR.mkdir(parents=True, exist_ok=True)
            os.chmod(OV_DIR, 0o700)
            for item in src_ov.iterdir():
                if item.is_file():
                    dst_f = OV_DIR / item.name
                    shutil.copy2(item, dst_f)
                    os.chmod(dst_f, 0o600)
                elif item.is_dir() and item.name == "pki":
                    dst_pki = OV_DIR / "pki"
                    dst_pki.mkdir(parents=True, exist_ok=True)
                    os.chmod(dst_pki, 0o700)
                    for cert_f in item.iterdir():
                        if cert_f.is_file():
                            dst_cert = dst_pki / cert_f.name
                            shutil.copy2(cert_f, dst_cert)
                            os.chmod(dst_cert, 0o600)
            restored_items.append("OpenVPN PKI & client certificates")
            run_helper("openvpn-apply")

        # 6. Restore RMBT identity
        src_rmbt = temp_extract / "rmbt_client_uuid"
        if src_rmbt.exists():
            shutil.copy2(src_rmbt, RMBT_UUID_PATH)

        # 7. Refresh Firewall & NAT rules
        run_helper("vpn-nat")

        summary_msg = f"System state successfully restored from '{archive_path.name}'. Restored: {', '.join(restored_items)}."
        log.info(summary_msg)
        return True, summary_msg

    except Exception as e:
        log.error("Restore operation failed: %s", e, exc_info=True)
        return False, f"Restore failed unexpectedly: {e}"
    finally:
        shutil.rmtree(temp_extract, ignore_errors=True)


def list_backups(backup_dir: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Scan and list all local backup archives with parsed metadata."""
    dir_path = backup_dir or _ensure_backup_dir()
    if not dir_path.exists():
        return []

    results: List[Dict[str, Any]] = []
    for f in sorted(dir_path.glob("*.tar.gz"), key=lambda p: p.stat().st_mtime, reverse=True):
        if f.name.endswith(".tmp"):
            continue
        st = f.stat()
        item: Dict[str, Any] = {
            "filename": f.name,
            "path": str(f),
            "size_bytes": st.st_size,
            "size_human": _format_bytes(st.st_size),
            "created_at": st.st_mtime,
            "created_at_iso": datetime.datetime.fromtimestamp(st.st_mtime, datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
            "backup_type": "unknown",
            "comment": "",
            "valid": False,
            "has_database": False,
            "has_wireguard": False,
            "has_openvpn": False,
            "file_count": 0,
        }

        # Try reading manifest quickly without extracting all files
        try:
            with tarfile.open(f, "r:gz") as tar:
                mf_file = tar.extractfile("manifest.json")
                if mf_file:
                    mf = json.loads(mf_file.read().decode("utf-8"))
                    item["backup_type"] = mf.get("backup_type", "unknown")
                    item["comment"] = mf.get("comment", "")
                    item["created_at"] = mf.get("created_at", st.st_mtime)
                    item["created_at_iso"] = mf.get("created_at_iso", item["created_at_iso"])
                    item["file_count"] = mf.get("total_files", len(mf.get("files", {})))
                    item["valid"] = True

                    files_dict = mf.get("files", {})
                    item["has_database"] = "database/nmb.db" in files_dict
                    item["has_wireguard"] = any(k.startswith("wireguard/") for k in files_dict)
                    item["has_openvpn"] = any(k.startswith("openvpn/") for k in files_dict)
        except Exception as e:
            item["comment"] = f"Unverified archive ({e})"

        results.append(item)

    return results


def delete_backup(filename: str, backup_dir: Optional[Path] = None) -> Tuple[bool, str]:
    """Delete a stored backup archive safely."""
    clean_name = os.path.basename(filename).strip()
    if not clean_name or ".." in clean_name:
        return False, "Invalid filename."

    target_dir = backup_dir or _ensure_backup_dir()
    target_file = target_dir / clean_name
    if not target_file.exists() or not target_file.is_file():
        return False, f"Backup file '{clean_name}' not found."

    try:
        target_file.unlink()
        return True, f"Backup '{clean_name}' removed."
    except Exception as e:
        return False, f"Failed to delete backup: {e}"


def factory_reset(keep_measurements: bool = False) -> Tuple[bool, str]:
    """Reset system to pristine factory defaults.

    Creates safety backup before wiping configurations.
    """
    from nmb.config import DEFAULT_CONFIG_TEXT

    try:
        # 1. Safety snapshot
        create_backup(
            backup_type="full",
            comment="Automatic pre-factory-reset safety checkpoint",
            custom_filename=f"nmb-safety-pre-factory-reset-{int(time.time())}.tar.gz",
        )

        # 2. Reset /etc/nmb/nmb.conf
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = CONFIG_PATH.with_suffix(".tmp")
        tmp.write_text(DEFAULT_CONFIG_TEXT, encoding="utf-8")
        os.chmod(tmp, 0o600)
        tmp.replace(CONFIG_PATH)

        # 3. Stop VPN daemons
        run_helper("wireguard-stop")
        run_helper("openvpn-stop")

        # 4. If wiping database, reinitialize clean schema
        if not keep_measurements:
            try:
                from nmb.db.database import init, connect
                for p in [LIVE_DB_PATH, PERSIST_DB_PATH]:
                    if p.exists():
                        p.unlink(missing_ok=True)
                conn = connect(LIVE_DB_PATH)
                init(conn)
                conn.close()
            except Exception as e:
                log.warning("Database schema reinit had warning: %s", e)

        run_helper("vpn-nat")
        return True, "Factory reset completed successfully. Default configuration restored."
    except Exception as e:
        log.error("Factory reset failed: %s", e, exc_info=True)
        return False, f"Factory reset failed: {e}"


def main(argv: Optional[List[str]] = None) -> int:
    """Command-line interface for nmb backup management."""
    import argparse

    parser = argparse.ArgumentParser(description="NetworkMeasureBox Backup & Disaster Recovery CLI")
    sub = parser.add_subparsers(dest="command")

    create_p = sub.add_parser("create", help="Create a backup snapshot")
    create_p.add_argument("--type", choices=["full", "config"], default="full", help="Backup type")
    create_p.add_argument("--comment", default="", help="Description or comment")
    create_p.add_argument("--output", default="", help="Output archive path")

    verify_p = sub.add_parser("verify", help="Verify archive integrity")
    verify_p.add_argument("archive", help="Path to .tar.gz archive")

    restore_p = sub.add_parser("restore", help="Restore state from backup archive")
    restore_p.add_argument("archive", help="Path to .tar.gz archive")
    restore_p.add_argument("--no-safety", action="store_true", help="Skip pre-restore safety snapshot")

    sub.add_parser("list", help="List stored local backup archives")

    del_p = sub.add_parser("delete", help="Delete a local backup archive")
    del_p.add_argument("filename", help="Backup archive filename")

    args = parser.parse_args(argv)

    if args.command == "create":
        target = Path(args.output).parent if args.output else None
        fname = Path(args.output).name if args.output else None
        ok, p, mf = create_backup(backup_type=args.type, comment=args.comment, target_dir=target, custom_filename=fname)
        if ok:
            print(f"[OK] Backup created: {p} ({mf.get('archive_size_human')}, {mf.get('total_files')} files)")
            return 0
        else:
            print(f"[ERROR] Failed to create backup: {mf.get('error')}", file=sys.stderr)
            return 1

    elif args.command == "verify":
        ok, msg, mf = verify_backup(Path(args.archive))
        print(f"[{'OK' if ok else 'FAIL'}] {msg}")
        if ok:
            print(json.dumps(mf, indent=2))
        return 0 if ok else 1

    elif args.command == "restore":
        ok, msg = restore_backup(Path(args.archive), create_safety_snapshot=not args.no_safety)
        print(f"[{'OK' if ok else 'FAIL'}] {msg}")
        return 0 if ok else 1

    elif args.command == "list":
        items = list_backups()
        if not items:
            print("No local backups found in /var/lib/nmb/backups.")
            return 0
        print(f"{'FILENAME':<42} {'TYPE':<8} {'SIZE':<10} {'DATE':<22} {'COMMENT'}")
        print("-" * 100)
        for it in items:
            print(f"{it['filename']:<42} {it['backup_type']:<8} {it['size_human']:<10} {it['created_at_iso']:<22} {it['comment']}")
        return 0

    elif args.command == "delete":
        ok, msg = delete_backup(args.filename)
        print(f"[{'OK' if ok else 'FAIL'}] {msg}")
        return 0 if ok else 1

    else:
        parser.print_help()
        return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
