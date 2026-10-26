"""Comprehensive IEEE 802.11 Wi-Fi Hardware Capability & Multi-Band AP Engine.

Supports all IEEE 802.11 frequencies (2.4 GHz, 5 GHz, 6 GHz / Wi-Fi 6E & 7)
and all standards (802.11a, 802.11b, 802.11g, 802.11n, 802.11ac, 802.11ax, 802.11be).
Dynamically inspects the underlying physical wireless hardware (nl80211 / iw)
to expose available capabilities and enforce valid configurations based on
the device's supported features.
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger("nmb.netd.wifi")

STANDARD_DESCRIPTIONS: Dict[str, Dict[str, str]] = {
    "be": {
        "label": "IEEE 802.11be (Wi-Fi 7 - Extremely High Throughput)",
        "freq": "2.4 GHz, 5 GHz, 6 GHz",
        "max_width": "320 MHz",
        "desc": "Next-gen Wi-Fi 7 with MLO, 4096-QAM and up to 320 MHz channel width.",
    },
    "ax": {
        "label": "IEEE 802.11ax (Wi-Fi 6 & 6E - High Efficiency)",
        "freq": "2.4 GHz, 5 GHz, 6 GHz",
        "max_width": "160 MHz",
        "desc": "High efficiency Wi-Fi 6/6E with OFDMA, MU-MIMO and 6 GHz spectrum support.",
    },
    "ac": {
        "label": "IEEE 802.11ac (Wi-Fi 5 - Very High Throughput)",
        "freq": "5 GHz",
        "max_width": "80 / 160 MHz",
        "desc": "High speed 5 GHz wireless with 256-QAM and 80 MHz channel bonding.",
    },
    "n": {
        "label": "IEEE 802.11n (Wi-Fi 4 - High Throughput)",
        "freq": "2.4 GHz & 5 GHz",
        "max_width": "40 MHz",
        "desc": "MIMO wireless standard with up to 40 MHz channel bonding.",
    },
    "g": {
        "label": "IEEE 802.11g (Legacy 2.4 GHz OFDM)",
        "freq": "2.4 GHz",
        "max_width": "20 MHz",
        "desc": "Standard 2.4 GHz OFDM wireless up to 54 Mbps.",
    },
    "a": {
        "label": "IEEE 802.11a (Legacy 5 GHz OFDM)",
        "freq": "5 GHz",
        "max_width": "20 MHz",
        "desc": "Legacy 5 GHz OFDM wireless up to 54 Mbps.",
    },
    "b": {
        "label": "IEEE 802.11b (Legacy 2.4 GHz DSSS)",
        "freq": "2.4 GHz",
        "max_width": "20 MHz",
        "desc": "Original 2.4 GHz DSSS wireless up to 11 Mbps.",
    },
}

BAND_CHANNELS: Dict[str, List[int]] = {
    "2.4ghz": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13],
    "5ghz": [36, 40, 44, 48, 52, 56, 60, 64, 100, 104, 108, 112, 116, 120, 124, 128, 132, 136, 140, 144, 149, 153, 157, 161, 165],
    "6ghz": [1, 5, 9, 13, 17, 21, 25, 29, 33, 37, 41, 45, 49, 53, 57, 61, 65, 69, 73, 77, 81, 85, 89, 93, 97, 101, 105, 109, 113, 117, 121, 125, 129, 133, 137, 141, 145, 149, 153, 157, 161, 165, 169, 173, 177, 181, 185, 189, 193, 197, 201, 205, 209, 213, 217, 221, 225, 229, 233],
}


def _find_iw_binary() -> Optional[str]:
    """Locate the iw utility in standard search paths."""
    for candidate in ("/usr/sbin/iw", "/sbin/iw", "/usr/bin/iw", "/bin/iw"):
        if os.path.exists(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return shutil.which("iw")


def detect_wifi_capabilities(iface: str = "wlan0") -> Dict[str, Any]:
    """Detect comprehensive hardware capabilities of wireless interface using nl80211/iw.

    Identifies:
    - Supported frequency bands: 2.4 GHz, 5 GHz, 6 GHz
    - Supported standards: 802.11a/b/g/n/ac/ax/be
    - Supported channel widths: 20, 40, 80, 160, 320 MHz
    - Supported security modes: WPA2, WPA3-SAE, OWE
    - Phy info, driver name, regulatory country, available channels
    """
    iw_bin = _find_iw_binary()
    out = ""
    phy_name = "phy0"

    # 1. Determine phy name from sysfs if possible
    phy_link = Path(f"/sys/class/net/{iface}/phy80211")
    if phy_link.exists():
        try:
            phy_name = phy_link.resolve().name
        except Exception:
            pass

    # 2. Query iw list / phy info
    if iw_bin:
        try:
            proc = subprocess.run([iw_bin, "list"], capture_output=True, text=True, timeout=5)
            out = proc.stdout
        except Exception as e:
            log.debug("could not execute %s list: %s", iw_bin, e)

    # 3. Detect Driver and Device Model
    driver_name = "unknown"
    driver_link = Path(f"/sys/class/net/{iface}/device/driver")
    if driver_link.exists():
        try:
            driver_name = driver_link.resolve().name
        except Exception:
            pass

    # 4. Detect Frequency Bands
    supported_bands: List[str] = []
    # Band 1 or frequencies in 2400-2500 MHz
    if "Band 1:" in out or re.search(r"24[0-9]{2}\.[0-9]+ MHz", out):
        supported_bands.append("2.4ghz")
    # Band 2 or frequencies in 5150-5900 MHz
    if "Band 2:" in out or re.search(r"5[1-8][0-9]{2}\.[0-9]+ MHz", out):
        supported_bands.append("5ghz")
    # Band 4 or frequencies in 5925-7125 MHz (Wi-Fi 6E / Wi-Fi 7)
    if "Band 4:" in out or re.search(r"(59[2-9][0-9]|6[0-9]{3}|7[0-1][0-9]{2})\.[0-9]+ MHz", out):
        supported_bands.append("6ghz")

    # Fallback if iw list didn't output (e.g. Raspberry Pi built-in chip)
    if not supported_bands:
        if driver_name in ("brcmfmac", "brcmutil") or Path(f"/sys/class/net/{iface}").exists():
            supported_bands = ["2.4ghz", "5ghz"]

    # 5. Detect Supported Standards (a/b/g/n/ac/ax/be)
    supported_standards: List[str] = []
    if "2.4ghz" in supported_bands:
        supported_standards.extend(["b", "g"])
    if "5ghz" in supported_bands:
        supported_standards.append("a")
    if "HT20" in out or "HT40" in out or "brcmfmac" in driver_name:
        if "n" not in supported_standards:
            supported_standards.append("n")
    if "VHT Capabilities" in out or "brcmfmac" in driver_name:
        if "ac" not in supported_standards:
            supported_standards.append("ac")
    if "HE Capabilities" in out or "HE MAC Capabilities" in out:
        supported_standards.append("ax")
    if "EHT Capabilities" in out or "EHT MAC Capabilities" in out:
        supported_standards.append("be")

    # 6. Detect Supported Channel Widths
    supported_widths: List[str] = ["20"]
    if "HT40" in out or "DSSS/CCK HT40" in out or "n" in supported_standards:
        supported_widths.append("40")
    if "VHT Capabilities" in out or "ac" in supported_standards or "ax" in supported_standards or "be" in supported_standards:
        if "80" not in supported_widths:
            supported_widths.append("80")
    if "160MHz" in out or "160 MHz" in out or "80+80" in out or "VHT160" in out:
        supported_widths.append("160")
    if "320MHz" in out or "320 MHz" in out or "be" in supported_standards:
        supported_widths.append("320")

    # 7. Detect WPA3 SAE Support
    wpa3_supported = bool(re.search(r"SAE", out, re.I)) or ("brcmfmac" in driver_name)

    # 8. Detect AP Mode Support
    ap_mode_supported = bool(re.search(r"\bAP\b", out)) or ("brcmfmac" in driver_name)

    # 9. Parse Available Active Channels per Band
    channels_24: List[int] = []
    channels_5: List[int] = []
    channels_6: List[int] = []
    for match in re.finditer(r"\*\s+([0-9]+)\.0\s+MHz\s+\[([0-9]+)\](?:\s+\(([^)]+)\))?", out):
        mhz = int(match.group(1))
        ch = int(match.group(2))
        flags = match.group(3) or ""
        if "disabled" in flags:
            continue
        if 2412 <= mhz <= 2484:
            channels_24.append(ch)
        elif 5170 <= mhz <= 5885:
            channels_5.append(ch)
        elif 5925 <= mhz <= 7125:
            channels_6.append(ch)

    if not channels_24:
        channels_24 = BAND_CHANNELS["2.4ghz"]
    if not channels_5 and "5ghz" in supported_bands:
        channels_5 = [36, 40, 44, 48, 52, 56, 60, 64, 100, 104, 108, 112, 116, 120, 124, 128, 132, 136, 140, 144, 149, 153, 157, 161]
    if not channels_6 and "6ghz" in supported_bands:
        channels_6 = [1, 5, 9, 33, 65, 97, 129, 161, 193]

    # 10. Highest standard determination
    order = ["be", "ax", "ac", "n", "g", "a", "b"]
    highest_standard = "n"
    for std in order:
        if std in supported_standards:
            highest_standard = std
            break

    # 11. Current Interface Operating Info
    current_info = get_wifi_status(iface)

    return {
        "interface": iface,
        "phy_name": phy_name,
        "driver": driver_name,
        "ap_mode_supported": ap_mode_supported,
        "wpa3_supported": wpa3_supported,
        "supported_bands": supported_bands,
        "supported_standards": supported_standards,
        "supported_widths": supported_widths,
        "highest_standard": highest_standard,
        "standards_catalog": STANDARD_DESCRIPTIONS,
        "channels": {
            "2.4ghz": sorted(list(set(channels_24))),
            "5ghz": sorted(list(set(channels_5))),
            "6ghz": sorted(list(set(channels_6))),
        },
        "current_status": current_info,
    }


def get_wifi_status(iface: str = "wlan0") -> Dict[str, Any]:
    """Get active operating state of wireless interface."""
    iw_bin = _find_iw_binary()
    info: Dict[str, Any] = {
        "is_up": False,
        "mac_address": "",
        "ssid": "",
        "type": "unmanaged",
        "channel": 0,
        "frequency_mhz": 0,
        "channel_width_mhz": 20,
        "txpower_dbm": 0.0,
        "connected_stations": 0,
    }

    iface_path = Path(f"/sys/class/net/{iface}")
    if not iface_path.exists():
        return info

    operstate = iface_path / "operstate"
    if operstate.exists():
        info["is_up"] = (operstate.read_text().strip().lower() in ("up", "dormant"))

    address_path = iface_path / "address"
    if address_path.exists():
        info["mac_address"] = address_path.read_text().strip()

    if iw_bin:
        try:
            proc = subprocess.run([iw_bin, "dev", iface, "info"], capture_output=True, text=True, timeout=3)
            out = proc.stdout
            m_type = re.search(r"type\s+([a-zA-Z_-]+)", out)
            if m_type:
                info["type"] = m_type.group(1)
            m_ssid = re.search(r"ssid\s+(.+)", out)
            if m_ssid:
                info["ssid"] = m_ssid.group(1).strip()
            m_ch = re.search(r"channel\s+([0-9]+)\s+\(([0-9]+)\s+MHz\)(?:,\s+width:\s+([0-9]+)\s+MHz)?", out)
            if m_ch:
                info["channel"] = int(m_ch.group(1))
                info["frequency_mhz"] = int(m_ch.group(2))
                if m_ch.group(3):
                    info["channel_width_mhz"] = int(m_ch.group(3))
            m_tx = re.search(r"txpower\s+([0-9.]+)\s+dBm", out)
            if m_tx:
                info["txpower_dbm"] = float(m_tx.group(1))

            # Count connected stations if in AP mode
            dump_proc = subprocess.run([iw_bin, "dev", iface, "station", "dump"], capture_output=True, text=True, timeout=3)
            stations = re.findall(r"Station\s+([0-9a-fA-F:]{17})", dump_proc.stdout)
            info["connected_stations"] = len(stations)
        except Exception as e:
            log.debug("error querying iw dev info: %s", e)

    return info


def calculate_vht_center_freq(channel: int, width_mhz: int) -> int:
    """Calculate VHT/HE 5 GHz center frequency index for channel bonding."""
    if width_mhz >= 160:
        if 36 <= channel <= 64:
            return 50
        elif 100 <= channel <= 128:
            return 114
    elif width_mhz >= 80:
        groups = [
            (36, 48, 42),
            (52, 64, 58),
            (100, 112, 106),
            (116, 128, 122),
            (132, 144, 138),
            (149, 161, 155),
        ]
        for start, end, center in groups:
            if start <= channel <= end:
                return center
    elif width_mhz >= 40:
        return channel + 2 if channel % 8 == 4 else channel - 2
    return channel


def calculate_6ghz_op_class_and_center(channel: int, width_mhz: int) -> Tuple[int, int]:
    """Calculate 6 GHz operating class and center frequency index for 802.11ax/be."""
    if width_mhz >= 320:
        op_class = 137
        # 320 MHz center groups
        for start in range(1, 233, 64):
            if start <= channel < start + 64:
                return op_class, start + 30
        return op_class, 31
    elif width_mhz >= 160:
        op_class = 134
        for start in range(1, 233, 32):
            if start <= channel < start + 32:
                return op_class, start + 14
        return op_class, 15
    elif width_mhz >= 80:
        op_class = 133
        for start in range(1, 233, 16):
            if start <= channel < start + 16:
                return op_class, start + 6
        return op_class, 7
    elif width_mhz >= 40:
        op_class = 132
        return op_class, channel + 2 if channel % 8 == 1 else channel - 2
    else:
        op_class = 131
        return op_class, channel


def generate_hostapd_config(cfg: Any, iface: str, run_dir: Path) -> Tuple[str, Dict[str, Any]]:
    """Generate high-performance, standards-compliant hostapd.conf.

    Supports:
    - 2.4 GHz, 5 GHz, 6 GHz
    - 802.11b, g, a, n (Wi-Fi 4), ac (Wi-Fi 5), ax (Wi-Fi 6/6E), be (Wi-Fi 7)
    - WPA2, WPA3-SAE, WPA2/WPA3 Mixed
    - Dynamic hardware capability adaptation
    """
    caps = detect_wifi_capabilities(iface)

    # 1. Resolve Effective Band
    req_band = getattr(cfg, "wifi_band", "auto").strip().lower()
    supported_bands = caps.get("supported_bands", ["2.4ghz"])

    if req_band == "auto":
        # Prefer 5 GHz for throughput if supported, else 2.4 GHz
        eff_band = "5ghz" if "5ghz" in supported_bands else "2.4ghz"
    elif req_band in supported_bands:
        eff_band = req_band
    else:
        eff_band = "5ghz" if "5ghz" in supported_bands else "2.4ghz"
        log.warning("Requested Wi-Fi band '%s' not supported by hardware %s; falling back to '%s'",
                    req_band, iface, eff_band)

    # 2. Resolve Effective Standard
    req_std = getattr(cfg, "wifi_standard", "auto").strip().lower()
    supported_stds = caps.get("supported_standards", ["g", "n"])

    if req_std == "auto":
        eff_std = caps.get("highest_standard", "n")
        # If running on 5 GHz and standard is g or b, upgrade to a or ac
        if eff_band == "5ghz" and eff_std in ("b", "g"):
            eff_std = "ac" if "ac" in supported_stds else ("n" if "n" in supported_stds else "a")
    elif req_std in supported_stds:
        eff_std = req_std
    else:
        eff_std = caps.get("highest_standard", "n")
        log.warning("Requested Wi-Fi standard '%s' not supported by hardware %s; falling back to '%s'",
                    req_std, iface, eff_std)

    # 3. Resolve Channel Width
    req_width = str(getattr(cfg, "wifi_channel_width", "auto")).strip().lower()
    supported_widths = caps.get("supported_widths", ["20"])

    if req_width == "auto":
        if eff_std == "be" and "320" in supported_widths and eff_band in ("5ghz", "6ghz"):
            eff_width = 320
        elif eff_std in ("be", "ax") and "160" in supported_widths and eff_band in ("5ghz", "6ghz"):
            eff_width = 160
        elif eff_std in ("be", "ax", "ac") and "80" in supported_widths and eff_band in ("5ghz", "6ghz"):
            eff_width = 80
        elif eff_std in ("be", "ax", "ac", "n") and "40" in supported_widths:
            eff_width = 40
        else:
            eff_width = 20
    else:
        try:
            w_int = int(req_width)
            eff_width = w_int if str(w_int) in supported_widths else 20
        except ValueError:
            eff_width = 20

    # 4. Resolve Channel Number
    raw_channel = getattr(cfg, "wifi_channel", 0)
    try:
        req_ch = int(raw_channel)
    except (ValueError, TypeError):
        req_ch = 0

    valid_channels = caps.get("channels", {}).get(eff_band, BAND_CHANNELS.get(eff_band, [6]))
    if req_ch > 0 and req_ch in valid_channels:
        eff_channel = req_ch
    else:
        # Default channels per band
        if eff_band == "6ghz":
            eff_channel = 1 if 1 in valid_channels else valid_channels[0]
        elif eff_band == "5ghz":
            eff_channel = 36 if 36 in valid_channels else (valid_channels[0] if valid_channels else 36)
        else:
            eff_channel = 6 if 6 in valid_channels else (valid_channels[0] if valid_channels else 6)

    # 5. Build hostapd parameters
    country = str(getattr(cfg, "wifi_country_code", "HU")).strip().upper() or "HU"
    ssid = getattr(cfg, "wifi_ssid", "NetworkMeasureBox-AP")
    psk = getattr(cfg, "wifi_psk", "NetworkMeasureBox123")
    security = getattr(cfg, "wifi_security", "wpa2").strip().lower()

    lines = [
        f"# Auto-generated by NetworkMeasureBox netd (Multi-Band Wi-Fi Engine)",
        f"# Standard: {eff_std.upper()} | Band: {eff_band} | Width: {eff_width} MHz | Channel: {eff_channel}",
        f"interface={iface}",
        f"driver=nl80211",
        f"ssid={ssid}",
        f"country_code={country}",
        f"ieee80211d=1",
        f"wmm_enabled=1",
        f"auth_algs=1",
    ]

    # Hardware Mode (hw_mode)
    if eff_band in ("5ghz", "6ghz"):
        lines.append("hw_mode=a")
        lines.append("ieee80211h=1")  # DFS support
    elif eff_std == "b":
        lines.append("hw_mode=b")
    else:
        lines.append("hw_mode=g")

    lines.append(f"channel={eff_channel}")

    # HT (802.11n) parameters
    if eff_std in ("n", "ac", "ax", "be"):
        lines.append("ieee80211n=1")
        if eff_width >= 40:
            lines.append("ht_capab=[HT40+][SHORT-GI-20][SHORT-GI-40][DSSS_CCK-40]")
        else:
            lines.append("ht_capab=[SHORT-GI-20]")

    # VHT (802.11ac) parameters
    if eff_std in ("ac", "ax", "be") and eff_band in ("5ghz", "6ghz"):
        lines.append("ieee80211ac=1")
        vht_chwidth_code = 2 if eff_width >= 160 else (1 if eff_width >= 80 else 0)
        lines.append(f"vht_oper_chwidth={vht_chwidth_code}")
        center_freq = calculate_vht_center_freq(eff_channel, eff_width)
        lines.append(f"vht_oper_centr_freq_seg0_idx={center_freq}")
        lines.append("vht_capab=[SHORT-GI-80][TX-STBC-2BY1][RX-STBC-1]")

    # HE (802.11ax / Wi-Fi 6 & 6E) parameters
    if eff_std in ("ax", "be"):
        lines.append("ieee80211ax=1")
        lines.append("he_su_beamformer=1")
        lines.append("he_su_beamformee=1")
        lines.append("he_mu_beamformer=1")
        if eff_band == "6ghz":
            op_class, center_6g = calculate_6ghz_op_class_and_center(eff_channel, eff_width)
            lines.append(f"op_class={op_class}")
            lines.append(f"he_oper_centr_freq_seg0_idx={center_6g}")
            he_chwidth_code = 2 if eff_width >= 160 else (1 if eff_width >= 80 else 0)
            lines.append(f"he_oper_chwidth={he_chwidth_code}")

    # EHT (802.11be / Wi-Fi 7) parameters
    if eff_std == "be":
        lines.append("ieee80211be=1")
        lines.append("eht_su_beamformer=1")
        lines.append("eht_su_beamformee=1")
        lines.append("eht_mu_beamformer=1")
        eht_chwidth_code = 3 if eff_width >= 320 else (2 if eff_width >= 160 else (1 if eff_width >= 80 else 0))
        lines.append(f"eht_oper_chwidth={eht_chwidth_code}")

    # Security configuration
    # 6 GHz strictly requires WPA3-SAE with Protected Management Frames (PMF)
    if eff_band == "6ghz" or security == "wpa3":
        lines.extend([
            "wpa=2",
            "wpa_key_mgmt=SAE",
            "ieee80211w=2",
            "sae_pwe=2",
            f"wpa_passphrase={psk}",
        ])
    elif security == "mixed":
        lines.extend([
            "wpa=2",
            "wpa_key_mgmt=WPA-PSK SAE",
            "rsn_pairwise=CCMP",
            "ieee80211w=1",
            "sae_pwe=2",
            f"wpa_passphrase={psk}",
        ])
    elif security == "open":
        lines.append("wpa=0")
    else:  # WPA2 default
        lines.extend([
            "wpa=2",
            "wpa_key_mgmt=WPA-PSK",
            "rsn_pairwise=CCMP",
            f"wpa_passphrase={psk}",
        ])

    conf_content = "\n".join(lines) + "\n"
    metadata = {
        "interface": iface,
        "effective_band": eff_band,
        "effective_standard": eff_std,
        "effective_width_mhz": eff_width,
        "effective_channel": eff_channel,
        "ssid": ssid,
        "country": country,
        "security": security if eff_band != "6ghz" else "wpa3",
    }
    return conf_content, metadata
