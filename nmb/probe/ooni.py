"""
OONI Probe (Open Observatory of Network Interference) Engine for NetworkMeasureBox.
Wrapper around probe-cli (https://github.com/ooni/probe-cli).

Detects internet censorship, website tampering/blocking, DPI middlebox manipulations,
instant messaging blocking (WhatsApp, Telegram, Signal), and circumvention tool reachability.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger("nmb.probe.ooni")

OONI_BIN_CANDIDATES = [
    Path("/usr/local/bin/ooniprobe"),
    Path("/usr/bin/ooniprobe"),
    Path("/usr/local/bin/ooniprobe-cli"),
    Path("/usr/bin/ooniprobe-cli"),
]

_ooni_lock = threading.Lock()
_ooni_running = False
_ooni_current_test = ""
_ooni_progress = 0
_latest_test_result: Optional[Dict[str, Any]] = None
_onboarded = False


def _get_ooni_env() -> Dict[str, str]:
    """Ensure OONI probe has a persistent, writable home directory under /var/lib/nmb."""
    env = os.environ.copy()
    ooni_dir = Path(os.environ.get("NMB_OONI_DIR", "/var/lib/nmb/ooni"))
    try:
        ooni_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    env["HOME"] = str(ooni_dir.parent)
    env["OONI_HOME"] = str(ooni_dir)
    return env


def find_ooniprobe_bin() -> Optional[Path]:
    """Find the path to the ooniprobe executable."""
    for p in OONI_BIN_CANDIDATES:
        if p.exists() and os.access(p, os.X_OK):
            return p
    found = shutil.which("ooniprobe") or shutil.which("ooniprobe-cli")
    return Path(found) if found else None


def is_ooni_installed() -> bool:
    """Return True if ooniprobe binary is found on system."""
    return find_ooniprobe_bin() is not None


def get_ooni_version() -> Optional[str]:
    """Return OONI Probe CLI version string."""
    bin_path = find_ooniprobe_bin()
    if not bin_path:
        return None
    try:
        res = subprocess.run([str(bin_path), "version"], capture_output=True, text=True, timeout=5, check=False, env=_get_ooni_env())
        return res.stdout.strip() or "Installed"
    except Exception as e:
        log.debug("error getting ooni version: %s", e)
        return None


def ensure_onboarding() -> bool:
    """Run non-interactive onboarding once so batch runs do not fail."""
    global _onboarded
    if _onboarded:
        return True
    bin_path = find_ooniprobe_bin()
    if not bin_path:
        return False
    try:
        proc = subprocess.run([str(bin_path), "onboard", "--yes"], capture_output=True, text=True, timeout=15, check=False, env=_get_ooni_env())
        if proc.returncode == 0:
            _onboarded = True
            log.info("ooniprobe onboarding verified")
            return True
        log.warning("ooniprobe onboarding returned %d: %s", proc.returncode, proc.stderr)
        return False
    except Exception as e:
        log.debug("ooniprobe onboard exception: %s", e)
        return False


def get_ooni_history(limit: int = 15) -> List[Dict[str, Any]]:
    """Retrieve list of previous OONI probe test runs."""
    bin_path = find_ooniprobe_bin()
    if not bin_path:
        return []
    try:
        proc = subprocess.run([str(bin_path), "list", "--batch"], capture_output=True, text=True, timeout=10, check=False, env=_get_ooni_env())
        results: List[Dict[str, Any]] = []
        for line in proc.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                fields = obj.get("fields", {})
                if fields.get("type") == "result_item":
                    results.append({
                        "id": fields.get("id"),
                        "name": fields.get("name"),
                        "anomaly_count": fields.get("measurement_anomaly_count", 0),
                        "total_count": fields.get("measurement_count", 0),
                        "network_name": fields.get("network_name", "Unknown"),
                        "country_code": fields.get("network_country_code", "--"),
                        "asn": fields.get("asn", 0),
                        "start_time": fields.get("start_time", ""),
                        "is_done": fields.get("is_done", True),
                    })
            except Exception:
                continue
        results.sort(key=lambda r: r.get("id", 0), reverse=True)
        return results[:limit]
    except Exception as e:
        log.debug("ooniprobe list error: %s", e)
        return []


def is_ooni_running() -> bool:
    """Return True if an OONI probe test is currently executing."""
    with _ooni_lock:
        return _ooni_running


def get_ooni_status() -> Dict[str, Any]:
    """Return status summary of OONI Probe subsystem."""
    installed = is_ooni_installed()
    version = get_ooni_version() if installed else None
    with _ooni_lock:
        running = _ooni_running
        cur_test = _ooni_current_test
        prog = _ooni_progress
        latest = _latest_test_result

    history = get_ooni_history(limit=10) if installed else []

    # Calculate overall freedom / censorship status
    total_anomalies = sum(h.get("anomaly_count", 0) for h in history)
    freedom_verdict = "clean"
    if total_anomalies > 0:
        freedom_verdict = "anomalies_detected"

    return {
        "installed": installed,
        "version": version,
        "running": running,
        "current_test": cur_test,
        "progress_percent": prog,
        "freedom_verdict": freedom_verdict,
        "total_anomalies_historical": total_anomalies,
        "latest": latest or (history[0] if history else None),
        "history": history,
    }


def run_ooni_test_sync(
    test_type: str = "websites",
    target_url: Optional[str] = None,
    upload_results: bool = False,
) -> Dict[str, Any]:
    """Execute an OONI probe test synchronously and parse structured output."""
    global _ooni_running, _ooni_current_test, _ooni_progress, _latest_test_result

    bin_path = find_ooniprobe_bin()
    if not bin_path:
        return {"status": "error", "message": "ooniprobe binary is not installed on this system."}

    ensure_onboarding()

    with _ooni_lock:
        if _ooni_running:
            return {"status": "busy", "message": "An OONI Probe test is already in progress."}
        _ooni_running = True
        _ooni_current_test = test_type
        _ooni_progress = 0

    log.info("starting OONI probe test: type=%s, target=%s, upload=%s", test_type, target_url, upload_results)

    cmd = [str(bin_path), "run", test_type, "--batch"]
    if not upload_results:
        cmd.append("--no-collector")

    if test_type == "websites" and target_url:
        clean_url = target_url.strip()
        if not clean_url.startswith(("http://", "https://")):
            clean_url = f"https://{clean_url}"
        cmd.extend(["--input", clean_url])

    start_ts = time.time()
    findings: List[str] = []
    anomalies = 0
    total_tests = 0
    dns_status = "untested"
    http_blocking = "untested"
    middlebox_detected = False

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=_get_ooni_env(),
        )

        if proc.stdout:
            for raw_line in proc.stdout:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    fields = obj.get("fields", {})
                    msg = obj.get("message", "")

                    if "percentage" in fields:
                        try:
                            _ooni_progress = int(float(fields["percentage"]) * 100)
                        except (ValueError, TypeError):
                            pass

                    # Extract key censorship indicators
                    if "DNS analysis result:" in msg:
                        dns_status = msg.split("DNS analysis result:", 1)[1].strip()
                        findings.append(f"DNS: {dns_status}")
                    elif "Blocking:" in msg:
                        blk = msg.split("Blocking:", 1)[1].strip()
                        if blk and blk != "nil":
                            anomalies += 1
                            http_blocking = blk
                            findings.append(f"Blocking Detected: {blk}")
                        else:
                            http_blocking = "clean"
                    elif "Accessible: true" in msg:
                        findings.append("HTTP/TLS: Accessible (Clean)")
                    elif "Accessible: false" in msg:
                        anomalies += 1
                        findings.append("HTTP/TLS: Inaccessible (Blocked)")
                    elif "middlebox" in msg.lower() and "detected" in msg.lower():
                        middlebox_detected = True
                        anomalies += 1
                        findings.append(f"Middlebox Alert: {msg}")
                    elif "connection_refused" in msg or "generic_timeout_error" in msg:
                        # Log probe timeouts
                        if len(findings) < 8:
                            findings.append(msg)
                except Exception:
                    continue

        proc.wait(timeout=180)
        duration_s = round(time.time() - start_ts, 2)

        # Pull latest result from history
        history = get_ooni_history(limit=1)
        latest_meta = history[0] if history else {}
        if latest_meta:
            anomalies = max(anomalies, latest_meta.get("anomaly_count", 0))
            total_tests = max(total_tests, latest_meta.get("total_count", 1))

        verdict = "clean" if anomalies == 0 else "tampered"
        result_dict = {
            "status": "ok",
            "test_type": test_type,
            "target": target_url or "Default Test List",
            "verdict": verdict,
            "anomalies": anomalies,
            "total_tests": total_tests,
            "dns_status": dns_status,
            "http_blocking": http_blocking,
            "middlebox_detected": middlebox_detected,
            "findings": findings[:10],
            "duration_seconds": duration_s,
            "asn": latest_meta.get("asn"),
            "network_name": latest_meta.get("network_name"),
            "country_code": latest_meta.get("country_code"),
            "timestamp": time.time(),
        }

        _latest_test_result = result_dict
        _record_ooni_event(result_dict)
        return result_dict

    except Exception as e:
        log.error("OONI probe test execution failed: %s", e)
        err_res = {
            "status": "error",
            "test_type": test_type,
            "error": str(e),
            "duration_seconds": round(time.time() - start_ts, 2),
        }
        _latest_test_result = err_res
        return err_res

    finally:
        with _ooni_lock:
            _ooni_running = False
            _ooni_current_test = ""
            _ooni_progress = 100


def run_ooni_test_async(
    test_type: str = "websites",
    target_url: Optional[str] = None,
    upload_results: bool = False,
) -> bool:
    """Trigger an OONI probe test in a background thread."""
    with _ooni_lock:
        if _ooni_running:
            return False

    thread = threading.Thread(
        target=run_ooni_test_sync,
        args=(test_type, target_url, upload_results),
        name=f"nmb-ooni-{test_type}",
        daemon=True,
    )
    thread.start()
    return True


def _record_ooni_event(res: Dict[str, Any]) -> None:
    """Record test completion event in system event database."""
    try:
        from nmb.db import database as db
        conn = db.connect()
        verdict = res.get("verdict", "unknown")
        test_type = res.get("test_type", "ooni")
        anomalies = res.get("anomalies", 0)
        sev = "warning" if anomalies > 0 else "info"
        detail = f"OONI Probe [{test_type}]: {verdict.upper()} ({anomalies} anomalies / {res.get('total_tests', 1)} tests) on {res.get('network_name', 'ISP')}"
        with db.tx(conn):
            conn.execute(
                "INSERT INTO event (ts, severity, source, kind, detail) VALUES (?, ?, 'ooni', 'censorship_probe', ?)",
                (db.now_ms(), sev, detail),
            )
        conn.close()
    except Exception as e:
        log.debug("failed to record ooni event: %s", e)
