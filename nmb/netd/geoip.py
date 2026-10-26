"""
GeoIP Context and Wi-Fi Regulatory Domain helper for NetworkMeasureBox.
Provides international and multi-country operational context for diagnostic reports and autonomous tuning.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import threading
import time
import urllib.request
from typing import Any, Dict, Optional, Tuple

log = logging.getLogger("nmb.netd.geoip")

_geoip_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}
_geoip_lock = threading.Lock()
GEOIP_CACHE_TTL = 3600.0  # 1 hour cache


def get_public_geoip(ip: Optional[str] = None, timeout: float = 2.5) -> Dict[str, Any]:
    """Retrieve public IP GeoIP metadata (Country, City, ASN, ISP).
    
    Returns dict:
      {
        "ip": str,
        "country": str,
        "country_code": str,
        "city": str,
        "asn": str,
        "isp": str,
        "summary": str,  # e.g. "203.0.113.195 (Country: US / United States, City: Seattle, ASN: AS15169 - Example ISP)"
      }
    """
    clean_ip = (ip or "").strip()
    
    # 1. Resolve IP if not supplied
    if not clean_ip or clean_ip.lower() in ("none", "n/a", "auto"):
        try:
            from nmb.netd.interfaces import get_dual_stack_ips
            dual = get_dual_stack_ips()
            clean_ip = dual.get("public_ipv4") or dual.get("public_ipv6") or dual.get("ipv4") or ""
        except Exception as e:
            log.debug("error resolving dual stack ip for geoip: %s", e)

    # Check cache
    cache_key = clean_ip or "_caller_ip_"
    now = time.time()
    with _geoip_lock:
        if cache_key in _geoip_cache:
            cached_time, cached_val = _geoip_cache[cache_key]
            if now - cached_time < GEOIP_CACHE_TTL:
                return dict(cached_val)

    # Default fallback object
    result: Dict[str, Any] = {
        "ip": clean_ip or "Unknown",
        "country": "Unknown",
        "country_code": "--",
        "city": "Unknown",
        "asn": "N/A",
        "isp": "Unknown ISP",
        "source": "fallback",
        "summary": f"{clean_ip or 'N/A'} (Country: -- / Unknown, City: Unknown, ASN: N/A)",
    }

    # 2. Try online GeoIP lookup via ip-api.com
    endpoint = f"http://ip-api.com/json/{clean_ip}" if clean_ip and not _is_private_ip(clean_ip) else "http://ip-api.com/json/"
    endpoint += "?fields=status,message,country,countryCode,regionName,city,isp,org,as,query"

    try:
        req = urllib.request.Request(endpoint, headers={"User-Agent": "NetworkMeasureBox-GeoIP/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data.get("status") == "success":
                ret_ip = data.get("query") or clean_ip
                c_code = data.get("countryCode") or "--"
                c_name = data.get("country") or "Unknown"
                city = data.get("city") or "Unknown"
                as_raw = data.get("as") or ""
                isp = data.get("org") or data.get("isp") or "Unknown ISP"

                # Parse ASN (e.g. "AS15169 Google LLC" -> "AS15169 - Google LLC")
                asn_short = "N/A"
                if as_raw.startswith("AS"):
                    parts = as_raw.split(" ", 1)
                    asn_code = parts[0]
                    asn_short = f"{asn_code} - {isp}"
                elif isp:
                    asn_short = isp

                result = {
                    "ip": ret_ip,
                    "country": c_name,
                    "country_code": c_code,
                    "city": city,
                    "asn": asn_short,
                    "isp": isp,
                    "source": "ip-api",
                    "summary": f"{ret_ip} (Country: `{c_code} / {c_name}`, City: `{city}`, ASN: `{asn_short}`)",
                }
                with _geoip_lock:
                    _geoip_cache[cache_key] = (now, result)
                    if ret_ip:
                        _geoip_cache[ret_ip] = (now, result)
                return result
    except Exception as e:
        log.debug("ip-api query failed: %s", e)

    # 3. Fallback to OONI probe history
    try:
        from nmb.probe.ooni import get_ooni_history
        ooni_hist = get_ooni_history(limit=1)
        if ooni_hist:
            h = ooni_hist[0]
            c_code = h.get("country_code", "--")
            asn_num = h.get("asn", 0)
            net_name = h.get("network_name", "Unknown ISP")
            asn_str = f"AS{asn_num} - {net_name}" if asn_num else net_name
            result.update({
                "country_code": c_code,
                "country": c_code,
                "asn": asn_str,
                "isp": net_name,
                "source": "ooni_history",
                "summary": f"{clean_ip or 'N/A'} (Country: `{c_code}`, City: `N/A`, ASN: `{asn_str}`)",
            })
            with _geoip_lock:
                _geoip_cache[cache_key] = (now, result)
            return result
    except Exception:
        pass

    with _geoip_lock:
        _geoip_cache[cache_key] = (now, result)
    return result


def _is_private_ip(ip_str: str) -> bool:
    import ipaddress
    try:
        ip_obj = ipaddress.ip_address(ip_str)
        return ip_obj.is_private or ip_obj.is_loopback
    except Exception:
        return False


def get_wifi_regulatory_domain() -> Dict[str, Any]:
    """Inspect the active kernel Wi-Fi regulatory domain via iw."""
    iw_bin = shutil.which("iw") or "/usr/sbin/iw"
    country_code = "00"
    reg_rule = "UNSET"
    raw_text = ""

    if os.path.exists(iw_bin) and os.access(iw_bin, os.X_OK):
        try:
            res = subprocess.run([iw_bin, "reg", "get"], capture_output=True, text=True, timeout=3.0)
            if res.returncode == 0:
                raw_text = res.stdout
                for line in raw_text.splitlines():
                    m = re.match(r"^country\s+([A-Za-z0-9]{2}):\s*(.*)", line.strip())
                    if m:
                        country_code = m.group(1).upper()
                        reg_rule = m.group(2).strip()
                        break
        except Exception as e:
            log.debug("error running iw reg get: %s", e)

    return {
        "country_code": country_code,
        "rule": reg_rule,
        "is_unset": country_code in ("00", "99"),
        "raw": raw_text,
    }


def set_wifi_regulatory_domain(country_code: str) -> bool:
    """Set the system Wi-Fi regulatory domain via nmb-helper or iw."""
    cc = country_code.strip().upper()
    if not cc or len(cc) != 2:
        return False

    # Try privileged helper first
    helper_candidates = ["/usr/local/bin/nmb-helper", "/opt/nmb/bin/nmb-helper", "nmb-helper"]
    for h in helper_candidates:
        if shutil.which(h) or os.path.exists(h):
            try:
                cmd = ["sudo", h, "wifi-reg-set", cc] if os.geteuid() != 0 else [h, "wifi-reg-set", cc]
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=5.0)
                if res.returncode == 0:
                    log.info("successfully set regulatory domain to %s via %s", cc, h)
                    return True
            except Exception as e:
                log.debug("helper wifi-reg-set exception: %s", e)

    # Direct iw fallback
    iw_bin = shutil.which("iw") or "/usr/sbin/iw"
    if os.path.exists(iw_bin):
        try:
            cmd = ["sudo", iw_bin, "reg", "set", cc] if os.geteuid() != 0 else [iw_bin, "reg", "set", cc]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=5.0)
            if res.returncode == 0:
                log.info("successfully set regulatory domain to %s via iw", cc)
                return True
        except Exception as e:
            log.debug("direct iw reg set exception: %s", e)

    return False
