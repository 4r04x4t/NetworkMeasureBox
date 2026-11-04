"""HTTP Client & Headless Browser User-Agent management for NetworkMeasureBox.

Provides customizable, auto-refreshing, and modern browser User-Agent strings
to ensure outbound measurement tests (Cloudflare, Ookla, GeoIP, APIs) mimic
fresh headless or desktop clients and avoid anti-bot or WAF throttling.
"""
from __future__ import annotations

import logging
import random
import time
from typing import Any, Dict, List, Optional

log = logging.getLogger("nmb.common.user_agent")

# Curated, realistic modern presets
USER_AGENT_PRESETS: Dict[str, Dict[str, str]] = {
    "headless_chrome_linux": {
        "name": "Headless Chrome (Linux x86_64)",
        "category": "headless",
        "description": "Standard modern headless Chrome on 64-bit Linux server / SBC",
        "ua": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) HeadlessChrome/133.0.6943.126 Safari/537.36",
    },
    "headless_chrome_arm": {
        "name": "Headless Chrome (ARM64 / aarch64)",
        "category": "headless",
        "description": "Modern headless Chrome for Raspberry Pi and ARM single-board computers",
        "ua": "Mozilla/5.0 (X11; Linux aarch64) AppleWebKit/537.36 (KHTML, like Gecko) HeadlessChrome/133.0.6943.126 Safari/537.36",
    },
    "chrome_windows": {
        "name": "Google Chrome (Windows 11)",
        "category": "desktop",
        "description": "Modern Desktop Chrome client running on Windows 11",
        "ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.6943.126 Safari/537.36",
    },
    "chrome_linux": {
        "name": "Google Chrome (Linux Desktop)",
        "category": "desktop",
        "description": "Modern Desktop Chrome client running on Ubuntu / Debian desktop",
        "ua": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.6943.126 Safari/537.36",
    },
    "chrome_mac": {
        "name": "Google Chrome (macOS Sequoia)",
        "category": "desktop",
        "description": "Modern Desktop Chrome on Apple Silicon / macOS",
        "ua": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.6943.126 Safari/537.36",
    },
    "firefox_linux": {
        "name": "Mozilla Firefox (Linux)",
        "category": "desktop",
        "description": "Modern Firefox browser on Linux",
        "ua": "Mozilla/5.0 (X11; Linux x86_64; rv:135.0) Gecko/20100101 Firefox/135.0",
    },
    "firefox_windows": {
        "name": "Mozilla Firefox (Windows 11)",
        "category": "desktop",
        "description": "Modern Firefox browser on Windows 11",
        "ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:135.0) Gecko/20100101 Firefox/135.0",
    },
    "safari_mac": {
        "name": "Apple Safari (macOS)",
        "category": "desktop",
        "description": "Native Apple Safari 18.3 on macOS Sequoia",
        "ua": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.3 Safari/605.1.15",
    },
    "chrome_android": {
        "name": "Chrome Mobile (Android 14)",
        "category": "mobile",
        "description": "Modern mobile Chrome client on Android",
        "ua": "Mozilla/5.0 (Linux; Android 14; Pixel 8 Pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.6943.126 Mobile Safari/537.36",
    },
    "nmb_native": {
        "name": "NetworkMeasureBox Native Client",
        "category": "native",
        "description": "Default NetworkMeasureBox diagnostic probe identification",
        "ua": "NetworkMeasureBox/2.5 (Linux; Headless Diagnostics Client)",
    },
}

DEFAULT_USER_AGENT = USER_AGENT_PRESETS["headless_chrome_linux"]["ua"]


def generate_fresh_user_agent(category: str = "headless") -> str:
    """Generate a statistically realistic, fresh modern browser / headless User-Agent string.

    Dynamically calculates plausible major, minor, and build versions so the client
    always presents a fresh signature that bypasses stale-UA heuristics.
    """
    major_chrome = random.choice([133, 134, 135])
    build_chrome = random.choice([6943, 6998, 7015, 7042])
    patch_chrome = random.randint(40, 160)
    chrome_version = f"{major_chrome}.0.{build_chrome}.{patch_chrome}"

    major_firefox = random.choice([135, 136, 137])
    minor_firefox = random.choice([0, 1])
    firefox_version = f"{major_firefox}.{minor_firefox}" if minor_firefox else f"{major_firefox}.0"

    cat = category.lower().strip()
    if cat in ("headless", "headless_chrome", "headless_client"):
        platform = random.choice(["X11; Linux x86_64", "X11; Linux aarch64", "Windows NT 10.0; Win64; x64"])
        return f"Mozilla/5.0 ({platform}) AppleWebKit/537.36 (KHTML, like Gecko) HeadlessChrome/{chrome_version} Safari/537.36"

    if cat in ("chrome", "desktop_chrome"):
        platform = random.choice([
            "Windows NT 10.0; Win64; x64",
            "X11; Linux x86_64",
            "Macintosh; Intel Mac OS X 10_15_7",
        ])
        return f"Mozilla/5.0 ({platform}) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{chrome_version} Safari/537.36"

    if cat in ("firefox", "desktop_firefox"):
        platform = random.choice(["X11; Linux x86_64; rv:", "Windows NT 10.0; Win64; x64; rv:"])
        return f"Mozilla/5.0 ({platform}{firefox_version}) Gecko/20100101 Firefox/{firefox_version}"

    if cat == "safari":
        safari_ver = random.choice(["18.2", "18.3", "18.4"])
        return f"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/{safari_ver} Safari/605.1.15"

    if cat == "mobile":
        device = random.choice(["Pixel 8 Pro", "Pixel 9", "SM-S928B", "K"])
        return f"Mozilla/5.0 (Linux; Android 14; {device}) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{chrome_version} Mobile Safari/537.36"

    # Default to modern headless Linux client
    return f"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) HeadlessChrome/{chrome_version} Safari/537.36"


def get_effective_user_agent(cfg: Optional[Any] = None) -> str:
    """Resolve the active User-Agent string based on configuration and mode.

    - "custom": uses cfg.speedtest.user_agent if provided
    - "auto_fresh": dynamically rotates a fresh modern headless/desktop UA
    - preset key (e.g. "headless_chrome_linux"): uses curated preset
    - fallback: returns fresh modern headless Chrome UA
    """
    if cfg is None:
        try:
            from nmb.config import load_config
            cfg = load_config()
        except Exception:
            cfg = None

    if cfg is not None:
        st_cfg = getattr(cfg, "speedtest", None)
        if st_cfg is not None:
            mode = getattr(st_cfg, "user_agent_mode", "auto_fresh") or "auto_fresh"
            mode = str(mode).strip().lower()

            if mode == "custom":
                ua = getattr(st_cfg, "user_agent", "")
                if ua and str(ua).strip():
                    return str(ua).strip()
                return generate_fresh_user_agent("headless")

            if mode in USER_AGENT_PRESETS:
                return USER_AGENT_PRESETS[mode]["ua"]

            if mode == "auto_fresh":
                # Generate a fresh modern headless string
                return generate_fresh_user_agent("headless")

            # If user_agent has a direct non-empty string configured
            ua = getattr(st_cfg, "user_agent", "")
            if ua and str(ua).strip():
                return str(ua).strip()

    return DEFAULT_USER_AGENT


def list_user_agent_presets() -> List[Dict[str, str]]:
    """Return all preset options with metadata for GUI selectors."""
    items = []
    for key, data in USER_AGENT_PRESETS.items():
        items.append({
            "key": key,
            "name": data["name"],
            "category": data["category"],
            "description": data["description"],
            "ua": data["ua"],
        })
    return items

