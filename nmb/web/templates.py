"""Modern, zero-dependency embedded Web UI dashboard template for NetworkMeasureBox.

Open-source network quality, speed benchmark, and traffic diagnostics suite.
Includes multi-engine speed testing (Ookla, Cloudflare Edge, RTR-NetTest / Open-RMBT),
dual analog circular gauges, real-time packet sniffer & flow inspector, and dynamic server directory.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

_ASSETS = Path(__file__).resolve().parent / "assets"


@lru_cache(maxsize=None)
def _read_asset(name: str) -> str:
    with open(_ASSETS / name, encoding="utf-8", newline="") as handle:
        return handle.read()


@lru_cache(maxsize=1)
def _dashboard_template() -> str:
    return (
        _read_asset("dashboard.html")
        .replace("@@NMB_CSS@@", _read_asset("dashboard.css"))
        .replace("@@NMB_JS@@", _read_asset("dashboard.js"))
    )


def get_dashboard_html(initial_theme: str = "default", initial_lang: str = "en") -> str:
    """Return the complete single-page application HTML string with pre-rendered theme & i18n."""
    import json
    from nmb.web.i18n import get_translations_for_lang
    initial_translations = json.dumps(get_translations_for_lang(initial_lang))

    html = _dashboard_template()
    return (
        html.replace("__NMB_INITIAL_THEME__", initial_theme)
        .replace("__NMB_INITIAL_LANG__", initial_lang)
        .replace("__NMB_INITIAL_TRANSLATIONS__", initial_translations)
        .replace("@@NMB_DONATE_JSON@@", donate_json())
    )


def donate_json() -> str:
    """The donation addresses for the page's script (nmb/common/donate.py), safe inside <script>."""
    import json
    from nmb.common import donate
    return json.dumps(donate.as_dicts()).replace("</", "<\\/")


def get_logout_html(initial_theme: str = "default") -> str:
    """Return standalone, responsive dark-mode Logout page."""
    html = _read_asset("logout.html")
    return html.replace("__NMB_INITIAL_THEME__", initial_theme).replace("@@NMB_DONATE_JSON@@", donate_json())
