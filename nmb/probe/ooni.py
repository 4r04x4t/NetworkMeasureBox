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


def get_ooni_run_measurements(run_id: int) -> Dict[str, Any]:
    """Retrieve detailed measurements belonging to a specific OONI probe test run."""
    bin_path = find_ooniprobe_bin()
    if not bin_path:
        return {"status": "error", "message": "ooniprobe binary not found"}

    try:
        proc = subprocess.run(
            [str(bin_path), "list", str(run_id), "--batch"],
            capture_output=True,
            text=True,
            timeout=25,
            check=False,
            env=_get_ooni_env(),
        )
        measurements: List[Dict[str, Any]] = []
        summary: Dict[str, Any] = {"run_id": run_id}

        for line in proc.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                fields = obj.get("fields", {})
                ftype = fields.get("type")
                if ftype == "measurement_item":
                    test_keys_raw = fields.get("test_keys", "{}")
                    test_keys = {}
                    if isinstance(test_keys_raw, str):
                        try:
                            test_keys = json.loads(test_keys_raw)
                        except Exception:
                            pass
                    elif isinstance(test_keys_raw, dict):
                        test_keys = test_keys_raw

                    blocking = test_keys.get("blocking", "")
                    accessible = test_keys.get("accessible", not fields.get("is_anomaly", False))

                    measurements.append({
                        "id": fields.get("id"),
                        "url": fields.get("url", fields.get("test_name", "Unknown")),
                        "test_name": fields.get("test_name", "unknown"),
                        "test_group": fields.get("test_group_name", ""),
                        "category": fields.get("url_category_code", "--"),
                        "country": fields.get("url_country_code", "--"),
                        "is_anomaly": bool(fields.get("is_anomaly", False)),
                        "is_failed": bool(fields.get("is_failed", False)),
                        "failure_msg": fields.get("failure_msg", ""),
                        "blocking": blocking or ("clean" if not fields.get("is_anomaly") else "anomaly"),
                        "accessible": accessible,
                        "runtime": round(float(fields.get("runtime", 0)), 2),
                        "start_time": fields.get("start_time", ""),
                    })
                elif ftype == "measurement_summary":
                    summary.update({
                        "anomaly_count": fields.get("anomaly_count", 0),
                        "total_count": fields.get("total_count", len(measurements)),
                        "network_name": fields.get("network_name", "Unknown"),
                        "asn": fields.get("asn", 0),
                        "country_code": fields.get("network_country_code", "--"),
                        "total_runtime": round(float(fields.get("total_runtime", 0)), 1),
                        "data_down_kb": round(float(fields.get("data_usage_down", 0)), 1),
                        "data_up_kb": round(float(fields.get("data_usage_up", 0)), 1),
                    })
            except Exception:
                continue

        # Sort measurements: anomalies first, then by id
        measurements.sort(key=lambda m: (not m.get("is_anomaly", False), m.get("id", 0)))

        return {
            "status": "ok",
            "run_id": run_id,
            "summary": summary,
            "total": len(measurements),
            "anomalies": sum(1 for m in measurements if m.get("is_anomaly")),
            "measurements": measurements,
        }
    except Exception as e:
        log.error("error retrieving ooni run %s measurements: %s", run_id, e)
        return {"status": "error", "message": str(e)}


OONI_CATEGORIES: Dict[str, str] = {
    "GMB": "Gambling/Betting",
    "FILE": "File Sharing",
    "PORN": "Adult Content",
    "NEWS": "Major News",
    "POL": "Political",
    "HOST": "Hosting/Blogging",
    "COMT": "Communications",
    "ANON": "Anonymization/Circumvention",
    "ALDR": "Alcohol/Drugs",
    "HATE": "Hate Speech",
    "PUBH": "Public Health",
    "REL": "Religion",
    "XCG": "Provocative Attire",
    "LGBT": "LGBTQ+",
    "GRP": "Social Groups",
    "GAME": "Gaming",
    "ENV": "Environment",
    "ECON": "Economics",
    "MMED": "Media Sharing",
    "SRCH": "Search Engines",
    "MISC": "Miscellaneous",
}


def get_ooni_anomaly_breakdown(run_id: Optional[int] = None) -> Dict[str, Any]:
    """Extract tested categories, anomaly counts, and blocking types from OONI run measurements.
    
    Returns structured summary:
      {
        "total_anomalies": int,
        "category_counts": {"GMB": 12, "FILE": 3},
        "formatted_categories": "15 anomalies [12x Gambling/Betting (GMB), 3x File Sharing (FILE)]",
        "anomaly_nature": "Likely regulatory / ISP compliance blocklist (DNS sinkhole / HTTP 451)",
        "blocking_types": ["dns", "http-failure"],
      }
    """
    if run_id is None:
        hist = get_ooni_history(limit=5)
        # Find latest run that has anomalies, or fallback to first
        target_run = next((h for h in hist if h.get("anomaly_count", 0) > 0), None)
        if not target_run and hist:
            target_run = hist[0]
        if target_run:
            run_id = target_run.get("id")

    if not run_id:
        return {
            "total_anomalies": 0,
            "category_counts": {},
            "formatted_categories": "None (0 anomalies detected)",
            "anomaly_nature": "Clean (No regulatory blocklists or DPI tampering detected)",
            "blocking_types": [],
        }

    meas_data = get_ooni_run_measurements(run_id)
    measurements = meas_data.get("measurements", []) if isinstance(meas_data, dict) else []

    cat_counts: Dict[str, int] = {}
    total_anomalies = 0
    blocking_types = set()

    for m in measurements:
        if m.get("is_anomaly"):
            total_anomalies += 1
            code = (m.get("category") or "MISC").upper()
            cat_counts[code] = cat_counts.get(code, 0) + 1
            blk = m.get("blocking")
            if blk and blk != "clean":
                blocking_types.add(blk)

    if total_anomalies == 0:
        return {
            "total_anomalies": 0,
            "category_counts": {},
            "formatted_categories": "None (0 anomalies detected across all tested categories)",
            "anomaly_nature": "Clean (No regulatory blocklists or DPI tampering detected)",
            "blocking_types": [],
        }

    # Format sorted category items: e.g. [12x Gambling/Betting (GMB), 3x File Sharing (FILE)]
    items_str = []
    for code, count in sorted(cat_counts.items(), key=lambda x: -x[1]):
        name = OONI_CATEGORIES.get(code, code)
        items_str.append(f"{count}x {name} ({code})")

    formatted = f"{total_anomalies} anomalies [{', '.join(items_str)}]"

    # Formulate Anomaly Nature based on detected blocking methods and categories
    blk_terms = []
    if any("dns" in b.lower() for b in blocking_types):
        blk_terms.append("DNS sinkhole")
    if any("http" in b.lower() for b in blocking_types):
        blk_terms.append("HTTP 451")
    if any("tcp" in b.lower() or "reset" in b.lower() for b in blocking_types):
        blk_terms.append("TCP reset")

    blk_suffix = f" ({' / '.join(blk_terms)})" if blk_terms else " (DNS sinkhole / HTTP 451)"

    compliance_codes = {"GMB", "FILE", "PORN", "ALDR", "MISC", "HOST", "MMED", "SRCH"}
    pol_codes = {"POL", "NEWS", "COMT", "ANON", "LGBT", "REL"}

    comp_count = sum(cnt for c, cnt in cat_counts.items() if c in compliance_codes)
    pol_count = sum(cnt for c, cnt in cat_counts.items() if c in pol_codes)

    if comp_count >= pol_count:
        anomaly_nature = f"Likely regulatory / ISP compliance blocklist{blk_suffix}"
    else:
        anomaly_nature = f"Potential information controls / access restrictions{blk_suffix}"

    return {
        "total_anomalies": total_anomalies,
        "category_counts": cat_counts,
        "formatted_categories": formatted,
        "anomaly_nature": anomaly_nature,
        "blocking_types": list(blocking_types),
    }



def get_ooni_measurement_detail(msmt_id: int) -> Dict[str, Any]:
    """Retrieve complete deep inspection details for a single OONI measurement."""
    bin_path = find_ooniprobe_bin()
    if not bin_path:
        return {"status": "error", "message": "ooniprobe binary not found"}

    try:
        proc = subprocess.run(
            [str(bin_path), "show", str(msmt_id), "--batch"],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
            env=_get_ooni_env(),
        )

        for line in proc.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                fields = obj.get("fields", {})
                if fields.get("type") == "measurement_json" or "measurement_json" in fields:
                    raw = fields.get("measurement_json") or fields
                    test_keys = raw.get("test_keys", {})

                    # Extract DNS queries summary
                    dns_queries = []
                    for q in test_keys.get("queries", []):
                        answers = [a.get("ipv4") or a.get("hostname") or str(a) for a in q.get("answers", []) if isinstance(a, dict)]
                        dns_queries.append({
                            "hostname": q.get("hostname", ""),
                            "query_type": q.get("query_type", "A"),
                            "failure": q.get("failure"),
                            "answers": answers,
                        })

                    # Extract TCP connects
                    tcp_connects = []
                    for tc in test_keys.get("tcp_connect", []):
                        status = tc.get("status", {})
                        tcp_connects.append({
                            "ip": tc.get("ip", ""),
                            "port": tc.get("port", 0),
                            "blocked": status.get("blocked", False) if isinstance(status, dict) else False,
                            "failure": status.get("failure") if isinstance(status, dict) else None,
                            "success": status.get("success", False) if isinstance(status, dict) else False,
                        })

                    # Extract HTTP requests
                    http_requests = []
                    for hr in test_keys.get("requests", []):
                        req = hr.get("request", {})
                        resp = hr.get("response", {})
                        http_requests.append({
                            "url": req.get("url", ""),
                            "method": req.get("method", "GET"),
                            "status_code": resp.get("code", 0),
                            "failure": hr.get("failure"),
                        })

                    return {
                        "status": "ok",
                        "id": msmt_id,
                        "url": raw.get("input", ""),
                        "test_name": raw.get("test_name", ""),
                        "start_time": raw.get("measurement_start_time", ""),
                        "runtime": round(float(raw.get("test_runtime", 0)), 2),
                        "probe": {
                            "asn": raw.get("probe_asn", ""),
                            "network": raw.get("probe_network_name", ""),
                            "cc": raw.get("probe_cc", ""),
                        },
                        "resolver": {
                            "asn": raw.get("resolver_asn", ""),
                            "network": raw.get("resolver_network_name", ""),
                            "ip": raw.get("resolver_ip", ""),
                        },
                        "verdict": {
                            "accessible": test_keys.get("accessible", True),
                            "blocking": test_keys.get("blocking", ""),
                            "dns_consistency": test_keys.get("dns_consistency", ""),
                            "client_resolver": test_keys.get("client_resolver", ""),
                        },
                        "dns_queries": dns_queries,
                        "tcp_connects": tcp_connects,
                        "http_requests": http_requests,
                        "network_events": test_keys.get("network_events", [])[:15],
                        "raw_json": raw,
                    }
            except Exception:
                continue

        return {"status": "error", "message": f"Measurement #{msmt_id} data not found."}
    except Exception as e:
        log.error("error retrieving measurement %s: %s", msmt_id, e)
        return {"status": "error", "message": str(e)}


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


def validate_target_url(url: str) -> tuple[bool, str]:
    """Validate target URL for OONI probe to prevent SSRF and argument injection."""
    if not url:
        return True, ""
    clean = url.strip()
    if clean.startswith("-") or any(c in clean for c in " \t\r\n'\"`$<>|;&"):
        return False, "Target URL contains invalid characters or starts with hyphen."
    if not clean.startswith(("http://", "https://")):
        clean = f"https://{clean}"
    try:
        from urllib.parse import urlparse
        import ipaddress
        parsed = urlparse(clean)
        if parsed.scheme not in ("http", "https"):
            return False, "Only HTTP and HTTPS URLs are permitted."
        host = (parsed.hostname or "").strip().lower()
        if not host:
            return False, "Invalid host in target URL."
        if host in ("localhost", "127.0.0.1", "::1", "0.0.0.0") or host.endswith(".local") or host.endswith(".internal"):
            return False, "Scanning local loopback or internal addresses is not permitted."
        try:
            ip = ipaddress.ip_address(host)
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                return False, f"Scanning private IP address {ip} is not permitted."
        except ValueError:
            pass
        return True, clean
    except Exception as e:
        return False, f"URL parse error: {e}"


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

    validated_url = None
    if test_type == "websites" and target_url:
        is_valid, clean_or_err = validate_target_url(target_url)
        if not is_valid:
            return {"status": "error", "message": f"Invalid target URL: {clean_or_err}"}
        validated_url = clean_or_err

    with _ooni_lock:
        if _ooni_running:
            return {"status": "busy", "message": "An OONI Probe test is already in progress."}
        _ooni_running = True
        _ooni_current_test = test_type
        _ooni_progress = 0

    log.info("starting OONI probe test: type=%s, target=%s, upload=%s", test_type, validated_url, upload_results)

    cmd = [str(bin_path), "run", test_type, "--batch"]
    if not upload_results:
        cmd.append("--no-collector")

    if test_type == "websites" and validated_url:
        cmd.extend(["--input", validated_url])

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
