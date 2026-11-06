"""Internationalization (i18n) for NetworkMeasureBox Telegram bot.

Supports 5 languages:
- Hungarian (hu)
- English (en)
- German (de)
- French (fr)
- Ukrainian (uk)

Provides per-chat language persistence in SQLite, localized persistent reply
keyboards, localized inline buttons, comprehensive multi-language command
dispatching, and proactive alerts.
"""
from __future__ import annotations

import logging
import sqlite3
import time
from typing import Any, Dict, List, Optional, Tuple

from nmb.config import Config
from nmb.bot.messages import LANGUAGE_ORDER, MESSAGES
from nmb.db import database as db

log = logging.getLogger("nmb.bot.i18n")

SUPPORTED_LANGUAGES = ["hu", "en", "de", "fr", "uk"]
DEFAULT_LANGUAGE = "en"

LANG_INFO: Dict[str, Dict[str, str]] = {
    "hu": {"flag": "🇭🇺", "name": "Magyar", "english": "Hungarian"},
    "en": {"flag": "🇬🇧", "name": "English", "english": "English"},
    "de": {"flag": "🇩🇪", "name": "Deutsch", "english": "German"},
    "fr": {"flag": "🇫🇷", "name": "Français", "english": "French"},
    "uk": {"flag": "🇺🇦", "name": "Українська", "english": "Ukrainian"},
}


# =============================================================================
# 1. Per-Chat Language Storage (SQLite kv table)
# =============================================================================

def get_chat_lang(chat_id: int, cfg: Optional[Config] = None) -> str:
    """Retrieve the selected language for a Telegram chat.

    Checks:
    1. SQLite kv table: `telegram_lang_{chat_id}`
    2. Configured web / system language in `cfg`
    3. Falls back to DEFAULT_LANGUAGE ('en')
    """
    try:
        conn = db.connect(readonly=True)
        row = conn.execute(
            "SELECT v FROM kv WHERE k = ?",
            (f"telegram_lang_{chat_id}",)
        ).fetchone()
        conn.close()
        if row and row["v"] in SUPPORTED_LANGUAGES:
            return row["v"]
    except Exception as e:
        log.debug("could not read telegram_lang_%d from db: %s", chat_id, e)

    if cfg:
        web_lang = getattr(getattr(cfg, "web", None), "language", None)
        if web_lang in SUPPORTED_LANGUAGES:
            return web_lang

    return DEFAULT_LANGUAGE


def set_chat_lang(chat_id: int, lang: str) -> bool:
    """Persist the selected language for a Telegram chat into SQLite kv table."""
    clean_lang = lang.lower().strip()
    if clean_lang not in SUPPORTED_LANGUAGES:
        return False

    try:
        conn = db.connect()
        with db.tx(conn):
            conn.execute(
                "INSERT OR REPLACE INTO kv (k, v, ts) VALUES (?, ?, ?)",
                (f"telegram_lang_{chat_id}", clean_lang, int(time.time() * 1000))
            )
        conn.close()
        log.info("updated telegram_lang_%d to %s", chat_id, clean_lang)
        return True
    except Exception as e:
        log.error("failed to save telegram_lang_%d: %s", chat_id, e)
        return False


# =============================================================================
# 2. Keyboards (Main Reply Keyboard & Language Selection)
# =============================================================================

def get_main_keyboard(lang: str = DEFAULT_LANGUAGE) -> Dict[str, Any]:
    """Generate localized persistent Telegram reply keyboard."""
    lang = lang if lang in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE

    keyboards = {
        "hu": [
            [{"text": "📊 Gyors Sebességmérés"}, {"text": "📈 Hálózati Riport Letöltése"}],
            [{"text": "📡 Ping & Telemetria"}, {"text": "🛡️ Reklámblokkoló"}],
            [{"text": "🦎 Tailscale & VPN"}, {"text": "📶 Wi-Fi Kliensszonda"}],
            [{"text": "⚙️ Rendszerállapot"}, {"text": "ℹ️ Parancsok & Súgó"}],
            [{"text": "🌐 Nyelv / Language"}]
        ],
        "en": [
            [{"text": "📊 Quick Speed Test"}, {"text": "📈 Download Broadband Report"}],
            [{"text": "📡 Ping & Telemetry"}, {"text": "🛡️ Ad Blocker"}],
            [{"text": "🦎 Tailscale & VPN"}, {"text": "📶 Wi-Fi Client Probe"}],
            [{"text": "⚙️ System Status"}, {"text": "ℹ️ Commands & Help"}],
            [{"text": "🌐 Language / Nyelv"}]
        ],
        "de": [
            [{"text": "📊 Schneller Speedtest"}, {"text": "📈 Breitbandbericht herunterladen"}],
            [{"text": "📡 Ping & Telemetrie"}, {"text": "🛡️ Werbeblocker"}],
            [{"text": "🦎 Tailscale & VPN"}, {"text": "📶 WLAN-Clientsonde"}],
            [{"text": "⚙️ Systemstatus"}, {"text": "ℹ️ Befehle & Hilfe"}],
            [{"text": "🌐 Sprache / Language"}]
        ],
        "fr": [
            [{"text": "📊 Test de débit rapide"}, {"text": "📈 Télécharger le rapport haut débit"}],
            [{"text": "📡 Ping & Télémétrie"}, {"text": "🛡️ Bloqueur de pub"}],
            [{"text": "🦎 Tailscale & VPN"}, {"text": "📶 Sonde Wi-Fi client"}],
            [{"text": "⚙️ État du système"}, {"text": "ℹ️ Commandes & Aide"}],
            [{"text": "🌐 Langue / Language"}]
        ],
        "uk": [
            [{"text": "📊 Швидкий тест швидкості"}, {"text": "📈 Завантажити широкосмуговий звіт"}],
            [{"text": "📡 Пінг та телеметрія"}, {"text": "🛡️ Блокувальник реклами"}],
            [{"text": "🦎 Tailscale та VPN"}, {"text": "📶 Клієнтський Wi-Fi зонд"}],
            [{"text": "⚙️ Стан системи"}, {"text": "ℹ️ Команди та довідка"}],
            [{"text": "🌐 Мова / Language"}]
        ]
    }

    return {
        "keyboard": keyboards[lang],
        "resize_keyboard": True,
        "persistent": True
    }


def get_language_keyboard() -> Dict[str, Any]:
    """Generate inline keyboard for switching language."""
    return {
        "inline_keyboard": [
            [
                {"text": "🇭🇺 Magyar", "callback_data": "/lang hu"},
                {"text": "🇬🇧 English", "callback_data": "/lang en"}
            ],
            [
                {"text": "🇩🇪 Deutsch", "callback_data": "/lang de"},
                {"text": "🇫🇷 Français", "callback_data": "/lang fr"}
            ],
            [
                {"text": "🇺🇦 Українська", "callback_data": "/lang uk"}
            ]
        ]
    }


def get_menu_aliases() -> Dict[str, str]:
    """Return dictionary mapping button labels in all 5 languages to commands."""
    return {
        # Speed Test
        "📊 gyors sebességmérés": "/test",
        "📊 gyorsmérés": "/test",
        "gyorsmérés": "/test",
        "📊 quick speed test": "/test",
        "quick speed test": "/test",
        "speed test": "/test",
        "📊 schneller speedtest": "/test",
        "schneller speedtest": "/test",
        "speedtest": "/test",
        "📊 test de débit rapide": "/test",
        "test de débit": "/test",
        "📊 швидкий тест швидкості": "/test",
        "тест швидкості": "/test",

        # Broadband / SLA Report
        "📈 hálózati riport letöltése": "/report",
        "hálózati riport": "/report",
        "📈 szélessávú riport letöltése": "/report",
        "📈 szélessávú riport": "/report",
        "szélessávú riport": "/report",
        "📈 download broadband report": "/report",
        "download broadband report": "/report",
        "broadband report": "/report",
        "📈 breitbandbericht herunterladen": "/report",
        "breitbandbericht": "/report",
        "📈 télécharger le rapport haut débit": "/report",
        "rapport haut débit": "/report",
        "📈 завантажити широкосмуговий звіт": "/report",
        "широкосмуговий звіт": "/report",

        # Ping & Telemetry
        "📡 ping & telemetria": "/ping",
        "ping & telemetria": "/ping",
        "📡 ping & telemetry": "/ping",
        "ping & telemetry": "/ping",
        "📡 ping & telemetrie": "/ping",
        "ping & telemetrie": "/ping",
        "📡 ping & télémétrie": "/ping",
        "ping & télémétrie": "/ping",
        "📡 пінг та телеметрія": "/ping",
        "пінг та телеметрія": "/ping",

        # Ad Blocker
        "🛡️ reklámblokkoló": "/adblock",
        "reklámblokkoló": "/adblock",
        "🛡️ ad blocker": "/adblock",
        "ad blocker": "/adblock",
        "🛡️ werbeblocker": "/adblock",
        "werbeblocker": "/adblock",
        "🛡️ bloqueur de pub": "/adblock",
        "bloqueur de pub": "/adblock",
        "🛡️ блокувальник реклами": "/adblock",
        "блокувальник реклами": "/adblock",

        # Tailscale & VPN
        "🦎 tailscale & vpn": "/vpn",
        "tailscale & vpn": "/vpn",
        "tailscale": "/tailscale",
        "vpn": "/vpn",
        "🦎 tailscale and vpn": "/vpn",
        "🦎 tailscale та vpn": "/vpn",

        # Wi-Fi Probe
        "📶 wi-fi kliensszonda": "/wifi",
        "wi-fi kliensszonda": "/wifi",
        "wifi kliensszonda": "/wifi",
        "📶 wi-fi client probe": "/wifi",
        "wi-fi client probe": "/wifi",
        "📶 wlan-clientsonde": "/wifi",
        "wlan-clientsonde": "/wifi",
        "📶 sonde wi-fi client": "/wifi",
        "sonde wi-fi client": "/wifi",
        "📶 клієнтський wi-fi зонд": "/wifi",
        "клієнтський wi-fi зонд": "/wifi",

        # System Status
        "⚙️ rendszerállapot": "/status",
        "rendszerállapot": "/status",
        "⚙️ system status": "/status",
        "system status": "/status",
        "status": "/status",
        "⚙️ systemstatus": "/status",
        "systemstatus": "/status",
        "⚙️ état du système": "/status",
        "état du système": "/status",
        "⚙️ стан системи": "/status",
        "стан системи": "/status",

        # Commands & Help
        "ℹ️ parancsok & súgó": "/help",
        "parancsok & súgó": "/help",
        "ℹ️ menü": "/help",
        "menü": "/help",
        "menu": "/help",
        "súgó": "/help",
        "help": "/help",
        "ℹ️ commands & help": "/help",
        "commands & help": "/help",
        "commands": "/help",
        "ℹ️ befehle & hilfe": "/help",
        "befehle & hilfe": "/help",
        "hilfe": "/help",
        "ℹ️ commandes & aide": "/help",
        "commandes & aide": "/help",
        "aide": "/help",
        "ℹ️ команди та довідка": "/help",
        "команди та довідка": "/help",
        "довідка": "/help",

        # Language
        "🌐 nyelv / language": "/lang",
        "🌐 language / nyelv": "/lang",
        "🌐 sprache / language": "/lang",
        "🌐 langue / language": "/lang",
        "🌐 мова / language": "/lang",
        "nyelv": "/lang",
        "language": "/lang",
        "sprache": "/lang",
        "langue": "/lang",
        "мова": "/lang",
    }


# =============================================================================
# 3. Measurement Status & Verdict Helpers
# =============================================================================

def get_measurement_status(code: int, lang: str = DEFAULT_LANGUAGE) -> Tuple[str, str]:
    """Return localized measurement status badge and description for speed test results."""
    lang = lang if lang in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE

    badges = {
        "hu": {
            1: ("🟢 MEGFELELŐ", "1: Sikeres mérés (Megfelel a garantált értékeknek)"),
            6: ("🔴 NEM MEGFELELŐ", "6: Letöltés és feltöltés elmaradás a garantált értéktől"),
            14: ("🟡 LETÖLTÉS HIBA", "14: Letöltés elmaradás a garantált értéktől"),
            15: ("🟡 FELTÖLTÉS HIBA", "15: Feltöltés elmaradás a garantált értéktől")
        },
        "en": {
            1: ("🟢 COMPLIANT", "1: Compliant measurement (Meets guaranteed speeds)"),
            6: ("🔴 NON-COMPLIANT", "6: Download and upload speeds below guaranteed thresholds"),
            14: ("🟡 DOWNLOAD DEFICIT", "14: Download speed below guaranteed threshold"),
            15: ("🟡 UPLOAD DEFICIT", "15: Upload speed below guaranteed threshold")
        },
        "de": {
            1: ("🟢 KONFORM", "1: Konforme Messung (Garantiertes SLA erfüllt)"),
            6: ("🔴 NICHT KONFORM", "6: Download- und Upload-Rate unterhalb der Garantie"),
            14: ("🟡 DOWNLOAD-DEFIZIT", "14: Download-Rate unterhalb der Garantie"),
            15: ("🟡 UPLOAD-DEFIZIT", "15: Upload-Rate unterhalb der Garantie")
        },
        "fr": {
            1: ("🟢 CONFORME", "1: Mesure conforme (Respecte les débits garantis)"),
            6: ("🔴 NON CONFORME", "6: Débits de téléchargement et téléversement non conformes"),
            14: ("🟡 DÉFICIT TÉLÉCHARGEMENT", "14: Débit de téléchargement inférieur au seuil garanti"),
            15: ("🟡 DÉFICIT TÉLÉVERSEMENT", "15: Débit de téléversement inférieur au seuil garanti")
        },
        "uk": {
            1: ("🟢 ВІДПОВІДАЄ", "1: Відповідає нормам (Досягнуто гарантованих швидкостей)"),
            6: ("🔴 НЕ ВІДПОВІДАЄ", "6: Швидкість завантаження та вивантаження нижче гарантованої"),
            14: ("🟡 ДЕФІЦИТ ЗАВАНТАЖЕННЯ", "14: Швидкість завантаження нижче гарантованого порогу"),
            15: ("🟡 ДЕФІЦИТ ВИВАНТАЖЕННЯ", "15: Швидкість вивантаження нижче гарантованого порогу")
        }
    }

    lang_dict = badges.get(lang, badges["en"])
    return lang_dict.get(code, lang_dict.get(1, ("⚪ UNKNOWN", "Unknown SLA state")))


def get_sla_verdict(verdict: str, lang: str = DEFAULT_LANGUAGE) -> str:
    """Translate the SLA verdict computed by NMB."""
    lang = lang if lang in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE
    v = (verdict or "").strip().upper()

    translations = {
        "hu": {
            "BREACHED": "SLA ALATT",
            "DEGRADED": "ROMLÁS",
            "COMPLIANT": "MEGFELEL",
            "MEGFELELŐ": "MEGFELELŐ",
            "NEM MEGFELELŐ": "NEM MEGFELELŐ",
            "FIGYELMEZTETÉS": "FIGYELMEZTETÉS",
            "UNKNOWN": "ISMERETLEN",
        },
        "en": {
            "BREACHED": "BELOW TARGETS",
            "DEGRADED": "DEGRADED",
            "COMPLIANT": "MEETS TARGETS",
            "MEGFELELŐ": "COMPLIANT",
            "NEM MEGFELELŐ": "NON-COMPLIANT",
            "FIGYELMEZTETÉS": "WARNING",
            "UNKNOWN": "UNKNOWN",
        },
        "de": {
            "BREACHED": "UNTER DEN ZIELEN",
            "DEGRADED": "BEEINTRÄCHTIGT",
            "COMPLIANT": "ZIELE ERFÜLLT",
            "MEGFELELŐ": "KONFORM",
            "NEM MEGFELELŐ": "NICHT KONFORM",
            "FIGYELMEZTETÉS": "WARNUNG",
            "UNKNOWN": "UNBEKANNT",
        },
        "fr": {
            "BREACHED": "SOUS LES OBJECTIFS",
            "DEGRADED": "DÉGRADÉ",
            "COMPLIANT": "OBJECTIFS ATTEINTS",
            "MEGFELELŐ": "CONFORME",
            "NEM MEGFELELŐ": "NON CONFORME",
            "FIGYELMEZTETÉS": "AVERTISSEMENT",
            "UNKNOWN": "INCONNU",
        },
        "uk": {
            "BREACHED": "НИЖЧЕ ЦІЛЕЙ",
            "DEGRADED": "ПОГІРШЕНО",
            "COMPLIANT": "ЦІЛІ ДОСЯГНУТО",
            "MEGFELELŐ": "ВІДПОВІДАЄ",
            "NEM MEGFELELŐ": "НЕ ВІДПОВІДАЄ",
            "FIGYELMEZTETÉS": "ПОПЕРЕДЖЕННЯ",
            "UNKNOWN": "НЕВІДОМО",
        }
    }

    t_map = translations.get(lang, translations["en"])
    for orig, trans in t_map.items():
        if orig in v:
            return trans
    return v


# =============================================================================
# 4. Localized String Resources
# =============================================================================

STRINGS: Dict[str, Dict[str, str]] = {
    # -------------------------------------------------------------------------
    # HUNGARIAN (hu)
    # -------------------------------------------------------------------------
    "hu": {
        "status_title": "📊 Rendszerállapot & Telemetria",
        "bot_title": "NetworkMeasureBox Irányító Chatbot",
        "device_id": "Eszközazonosító",
        "public_ip": "Nyilvános IP",
        "isp": "Szolgáltató (ISP)",
        "mode": "Üzemmód",
        "uptime_24h": "24h Rendelkezésre állás",
        "latency_rtt": "Késleltetés (RTT)",
        "packet_loss": "Csomagvesztés",
        "sla_verdict": "SLA eredmény (NMB értékelés)",
        "compliance": "Megfelelőség",
        "latest_speed": "Legutóbbi Sebesség",
        "services_security": "Szolgáltatások & Biztonság",
        "download": "Letöltés",
        "upload": "Feltöltés",
        "server": "Mérőszerver",
        "speed_result_label": "Eredmény a garantált sebességhez képest",
        "speed_starting": "<i>🚀 Sebességmérés indítása{engine_str}... Kérlek várj kb. 15-25 másodpercet!</i>",
        "speed_error": "⚠️ Sebességmérés hiba: {error}",
        "speed_result_title": "<b>📊 Sebességmérés Eredmény ({engine})</b>",
        "ping_header": "<b>📡 Valós Idejű Válaszidő & Csomagvesztés (Elmúlt 60 mp):</b>\n",
        "ping_no_resp": "Nincs válasz",
        "ping_loss_label": "vesztés",
        "report_generating": "<i>📊 24 órás hálózati minőségi és SLA vizsgálati dosszié generálása...</i>",
        "report_caption": "<b>📋 Hálózati SLA Vizsgálati Dosszié (24h)</b>\nEszköz: <code>{box_id}</code> | Szolgáltató: <b>{isp}</b>\nMinősítés: <b>{verdict}</b>\nSLA Teljesülés: <b>{sla:.0f}%</b> | Elérhetőség: <b>{uptime:.2f}%</b>",
        "report_fail": "A jegyzőkönyv elkészült, de a fájlküldés nem sikerült.",
        "tailscale_title": "<b>🦎 Tailscale Mesh VPN Állapot</b>",
        "tailscale_active": "🟢 AKTÍV ÉS CSATLAKOZVA",
        "tailscale_login_req": "🟡 HITELESÍTÉS SZÜKSÉGES",
        "tailscale_inactive": "⚫ INAKTÍV ({backend_state})",
        "tailscale_desc_active": "A mérődoboz sikeresen csatlakozott a Tailscale hálózathoz. Bárhonnan biztonságosan elérheted a WebGUI-t ezen az IP-n:\n👉 <code>http://{ip}:8080</code>",
        "tailscale_desc_login": "Az eszköz vár a hitelesítésre. Nyisd meg a linket a jóváhagyáshoz:\n👉 <a href=\"{url}\">{url}</a>",
        "tailscale_desc_inactive": "A Tailscale jelenleg nincs csatlakoztatva vagy nincs bejelentkezve.",
        "tailscale_role": "Szerepkör: Adminisztráció & WebGUI távoli elérés (nem NAT-ol vagy irányít át internet forgalmat)",
        "vpn_hub_title": "<b>🛡️ VPN Szerver Hub Állapot</b>",
        "vpn_wg_section": "<b>1. WireGuard Nagysebességű VPN:</b>",
        "vpn_ovpn_section": "<b>2. OpenVPN Robusztus Fallback Szerver:</b>",
        "vpn_clients_title": "<b>Konfigurált VPN Kliensek:</b>\n",
        "vpn_wg_peers": "<b>🛡️ WireGuard Kliensek:</b>",
        "vpn_ovpn_clients": "<b>🔒 OpenVPN Kliensek:</b>",
        "vpn_no_wg": "<i>Nincsenek konfigurált WireGuard kliensek.</i>",
        "vpn_no_ovpn": "<i>Nincsenek konfigurált OpenVPN kliensek.</i>",
        "adblock_title": "<b>🛡️ DNS Reklámblokkoló & Sinkhole (Pi-hole Motor)</b>",
        "adblock_enabled": "🟢 <b>DNS Reklámblokkoló & Sinkhole BEKAPCSOLVA</b>. A hálózati hirdetések és nyomkövetők blokkolása aktív.",
        "adblock_disabled": "🔴 <b>DNS Reklámblokkoló & Sinkhole KIKAPCSOLVA</b>. A DNS lekérdezések szűretlenül továbbítódnak.",
        "adblock_blocked_msg": "🚫 <b>Domain Blokkolva</b>: <code>{domain}</code> hozzáadva az egyéni feketelistához.",
        "adblock_unblocked_msg": "✅ <b>Domain Engedélyezve</b>: <code>{domain}</code> eltávolítva a feketelistáról és engedélyezve.",
        "adblock_update_msg": "🔄 Gravitáció blokklisták letöltése és fordítása folyamatban.",
        "tasks_title": "<b>📊 Rendszererőforrás Terhelés & Folyamattábla</b>",
        "wifi_title": "<b>📶 Wi-Fi & Vendég Wi-Fi Szonda Állapot</b>",
        "wifi_connected": "🟢 CSATLAKOZVA",
        "wifi_disconnected": "⚪ NINCS CSATLAKOZTATVA",
        "wifi_scan_title": "<b>🔍 Észlelt Wi-Fi Hálózatok ({count} találat):</b>\n",
        "wifi_no_networks": "Nem található észlelhető Wi-Fi hálózat.",
        "backup_title": "<b>📦 Tárolt Rendszermentések:</b>\n",
        "backup_none": "Nincsenek helyi mentések a <code>/var/lib/nmb/backups/</code> könyvtárban.",
        "backup_created": "✅ <b>Rendszermentés Elkészült!</b>\n\nFájlnév: <code>{fname}</code>\nMéret: <b>{size}</b>\nTartalom: Konfiguráció (/etc/nmb), Adatbázis történet, WireGuard és OpenVPN titkos kulcsok.\n\nLetöltés mobilra: <code>/backup send {fname}</code>",
        "drivers_title": "<b>🔧 Hardver Hálózati Vezérlők & Illesztőprogramok:</b>\n",
        "reboot_confirm": "⚠️ <b>Újraindítás Megerősítése Szükséges</b>\nA NetworkMeasureBox biztonságos újraindításához küldd el a következőt:\n👉 <code>/reboot now</code>",
        "reboot_starting": "🔄 <b>NetworkMeasureBox újraindítása most...</b> A kapcsolat kb. 45 másodperc múlva helyreáll.",
        "unknown_cmd": "Ismeretlen parancs: <code>{cmd}</code>. Nyomd meg a menü gombok egyikét vagy használd a /help parancsot.",
        "lang_title": "🌐 <b>Nyelv Kiválasztása</b>",
        "lang_desc": "Jelenlegi nyelv: <b>{curr_lang}</b>\n\nVálassz egy nyelvet az alábbi gombok segítségével:",
        "lang_updated": "🌐 A bot nyelve sikeresen módosítva: <b>{flag} {name}</b>!\nA menü és az összes jövőbeli üzenet ezen a nyelven jelenik meg.",
        "help_message": """<b>NetworkMeasureBox Irányító Chatbot</b>
<i>Eszközazonosító: {box_id}</i>

<b>📡 Hálózati Mérések & Diagnosztika:</b>
• /status - Rendszerállapot, Uptime, CPU és SLA megfelelőség
• /ping - Valós idejű késleltetés és csomagvesztés referencia csomópontok felé
• /test (vagy /speed) <code>[ookla|cloudflare|rtr]</code> - Sebességmérés futtatása
• /report - 24 órás mérési és SLA megfelelőségi riport letöltése (.html fájl)
• /ai - AI diagnosztikai naplócsomag letöltése LLM-ekhez (.md fájl)
• /mode <code>[auto|standalone|mode_a|mode_b]</code> - Üzemmód váltás

<b>🛡️ Biztonság, VPN & Tailscale:</b>
• /tailscale - Tailscale mesh VPN állapot, WebGUI link & belépés
• /vpn - WireGuard & OpenVPN állapot és kliensek
• /vpn clients - Csatlakozott kliensek és adatforgalom
• /vpn add <code>&lt;név&gt;</code> - Új WireGuard kliens + azonnali QR kód és .conf!
• /vpn qr <code>&lt;név&gt;</code> - QR kód újraküldése mobil párosításhoz
• /vpn conf <code>&lt;név&gt;</code> - Konfigurációs profil letöltése

<b>🦆 Dinamikus DNS (DuckDNS / dynv6):</b>
• /dyndns - DynDNS státusz, nyilvános IP és frissítési visszaszámláló
• /dyndns update - Azonnali kézi szinkronizáció

<b>🛡️ DNS Reklámblokkoló (Pi-hole Sinkhole):</b>
• /adblock - Blokkolt hirdetések, Gravity adatbázis és arány
• /adblock on | /adblock off - Reklámblokkolás ki/be kapcsolása
• /adblock block <code>&lt;domain&gt;</code> - Domain tiltása
• /adblock unblock <code>&lt;domain&gt;</code> - Domain engedélyezése
• /adblock update - Gravitáció blokklisták letöltése és frissítése

<b>📶 Wi-Fi & Vendég Wi-Fi Szonda:</b>
• /wifi - Wi-Fi szonda telemetria, jelerősség és izolációs riasztás
• /wifi scan - Környező 2.4/5 GHz-es Wi-Fi hálózatok keresése

<b>⚙️ Rendszer & Erőforrások:</b>
• /tasks (vagy /top) - CPU, RAM, Disk, Hőmérséklet és top folyamatok
• /heal - Autonóm öngyógyító és hibajavító alrendszer
• /backup - Biztonsági mentések kezelése és letöltése
• /drivers - Hálózati kártya és vezérlő illesztőprogramok
• /reboot - Eszköz biztonságos újraindítása
• /sla - Az SLA eredmény magyarázata
• /purge - Tárolt adatok törlése
• /lang - Nyelv megváltoztatása (HU, EN, DE, FR, UK)""",
        # Inline Button Labels
        "btn_quick_test": "📊 Gyorsmérés",
        "btn_report": "📈 SLA Dosszié",
        "btn_ping_details": "📡 Ping Részletek",
        "btn_top_resources": "⚙️ Erőforrások (Top)",
        "btn_tailscale": "🦎 Tailscale",
        "btn_adblock": "🛡️ Reklámblokkoló",
        "btn_refresh": "🔄 Frissítés",
        "btn_speedtest": "🚀 Sebességmérés",
        "btn_status": "📊 Rendszerállapot",
        "btn_main_menu": "🏠 Főmenü",
        "btn_vpn_clients": "👥 Kliensek Listája",
        "btn_enable": "🟢 Bekapcsolás",
        "btn_disable": "🔴 Kikapcsolás",
        "btn_update_gravity": "🔄 Blokklisták Frissítése",
        "btn_wifi_scan": "🔍 Wi-Fi Keresés",
        "btn_probe_refresh": "🔄 Szonda Frissítés",
        "btn_vpn_hub": "🛡️ VPN Hub (WireGuard)",
        "btn_auth_open": "🔑 Hitelesítés Megnyitása",
        "btn_rtr": "🔄 RTR-NetTest",
        "btn_ookla": "⚡ Ookla",
        "btn_cloudflare": "☁️ Cloudflare",
    },

    # -------------------------------------------------------------------------
    # ENGLISH (en)
    # -------------------------------------------------------------------------
    "en": {
        "status_title": "📊 System Status & Telemetry",
        "bot_title": "NetworkMeasureBox Management Chatbot",
        "device_id": "Device ID",
        "public_ip": "Public IP",
        "isp": "Internet Provider (ISP)",
        "mode": "Operating Mode",
        "uptime_24h": "24h Availability",
        "latency_rtt": "Latency (RTT)",
        "packet_loss": "Packet Loss",
        "sla_verdict": "SLA result (NMB evaluation)",
        "compliance": "Compliance",
        "latest_speed": "Latest Speed",
        "services_security": "Services & Security",
        "download": "Download",
        "upload": "Upload",
        "server": "Measurement Server",
        "speed_result_label": "Result against guaranteed speed",
        "speed_starting": "<i>🚀 Starting speed test{engine_str}... Please wait approximately 15-25 seconds!</i>",
        "speed_error": "⚠️ Speed test error: {error}",
        "speed_result_title": "<b>📊 Speed Test Result ({engine})</b>",
        "ping_header": "<b>📡 Real-Time Probe Latency & Packet Loss (Past 60s):</b>\n",
        "ping_no_resp": "No response",
        "ping_loss_label": "loss",
        "report_generating": "<i>📊 Generating 24-hour official SLA compliance dossier...</i>",
        "report_caption": "<b>📋 SLA Network Dossier (24h)</b>\nDevice: <code>{box_id}</code> | ISP: <b>{isp}</b>\nSLA result: <b>{verdict}</b>\nSLA Compliance: <b>{sla:.0f}%</b> | Uptime: <b>{uptime:.2f}%</b>",
        "report_fail": "Dossier was generated, but document upload failed.",
        "tailscale_title": "<b>🦎 Tailscale Mesh VPN Status</b>",
        "tailscale_active": "🟢 ACTIVE & CONNECTED",
        "tailscale_login_req": "🟡 AUTHENTICATION REQUIRED",
        "tailscale_inactive": "⚫ INACTIVE ({backend_state})",
        "tailscale_desc_active": "The measure box is securely connected to your Tailscale mesh network. You can access the WebGUI securely from anywhere at:\n👉 <code>http://{ip}:8080</code>",
        "tailscale_desc_login": "Device is awaiting web authorization. Open this URL to approve access:\n👉 <a href=\"{url}\">{url}</a>",
        "tailscale_desc_inactive": "Tailscale is currently disconnected or not logged in.",
        "tailscale_role": "Role: Administration & secure WebGUI remote access (no WAN routing or NAT override)",
        "vpn_hub_title": "<b>🛡️ VPN Server Hub Status</b>",
        "vpn_wg_section": "<b>1. WireGuard High-Performance VPN:</b>",
        "vpn_ovpn_section": "<b>2. OpenVPN Robust Fallback Server:</b>",
        "vpn_clients_title": "<b>Configured VPN Clients:</b>\n",
        "vpn_wg_peers": "<b>🛡️ WireGuard Peers:</b>",
        "vpn_ovpn_clients": "<b>🔒 OpenVPN Clients:</b>",
        "vpn_no_wg": "<i>No WireGuard peers configured.</i>",
        "vpn_no_ovpn": "<i>No OpenVPN clients configured.</i>",
        "adblock_title": "<b>🛡️ DNS Ad-Blocker & Sinkhole (Pi-hole Engine)</b>",
        "adblock_enabled": "🟢 <b>DNS Ad-Blocker & Sinkhole ENABLED</b>. Network ads and tracking are now actively filtered.",
        "adblock_disabled": "🔴 <b>DNS Ad-Blocker & Sinkhole DISABLED</b>. DNS queries forwarded unfiltered.",
        "adblock_blocked_msg": "🚫 <b>Domain Blocked</b>: <code>{domain}</code> added to custom blacklist.",
        "adblock_unblocked_msg": "✅ <b>Domain Whitelisted</b>: <code>{domain}</code> removed from blacklist & allowed.",
        "adblock_update_msg": "🔄 Gravity blocklist download and compilation initiated.",
        "tasks_title": "<b>📊 System Resource Load & Process Table</b>",
        "wifi_title": "<b>📶 Wi-Fi & Guest Wi-Fi Station Status</b>",
        "wifi_connected": "🟢 CONNECTED",
        "wifi_disconnected": "⚪ DISCONNECTED",
        "wifi_scan_title": "<b>🔍 Detected Wi-Fi Networks ({count} found):</b>\n",
        "wifi_no_networks": "No detectable Wi-Fi access points found.",
        "backup_title": "<b>📦 Stored Device Backups:</b>\n",
        "backup_none": "No local backups found in <code>/var/lib/nmb/backups/</code>.",
        "backup_created": "✅ <b>System Backup Created!</b>\n\nFilename: <code>{fname}</code>\nSize: <b>{size}</b>\nIncludes: Config (/etc/nmb), Database history, WireGuard & OpenVPN cryptographic keys.\n\nTo download to your phone: <code>/backup send {fname}</code>",
        "drivers_title": "<b>🔧 Hardware Network Controllers & Drivers:</b>\n",
        "reboot_confirm": "⚠️ <b>Reboot Confirmation Required</b>\nTo safely restart the NetworkMeasureBox host, send:\n👉 <code>/reboot now</code>",
        "reboot_starting": "🔄 <b>Rebooting NetworkMeasureBox now...</b> Connectivity will resume in ~45 seconds.",
        "unknown_cmd": "Unknown command: <code>{cmd}</code>. Tap one of the menu buttons below or type /help.",
        "lang_title": "🌐 <b>Language Settings</b>",
        "lang_desc": "Current language: <b>{curr_lang}</b>\n\nPlease select your preferred language using the buttons below:",
        "lang_updated": "🌐 Bot language successfully changed to <b>{flag} {name}</b>!\nThe menu and all future responses are now localized in {name}.",
        "help_message": """<b>NetworkMeasureBox Management Chatbot</b>
<i>Device ID: {box_id}</i>

<b>📡 Network Measurements & Diagnostics:</b>
• /status - System status, Uptime, CPU and SLA compliance
• /ping - Real-time latency and packet loss to reference endpoints
• /test (or /speed) <code>[ookla|cloudflare|rtr]</code> - Run speed test
• /report - Download 24-hour official SLA compliance dossier (.html file)
• /ai - Download AI diagnostic snapshot bundle for LLMs (.md file)
• /mode <code>[auto|standalone|mode_a|mode_b]</code> - Switch operating mode

<b>🛡️ Security, VPN & Tailscale:</b>
• /tailscale - Tailscale mesh VPN status, WebGUI link & login
• /vpn - WireGuard & OpenVPN server status and clients
• /vpn clients - Connected clients and data transfer
• /vpn add <code>&lt;name&gt;</code> - Create new client + instant QR code & .conf!
• /vpn qr <code>&lt;name&gt;</code> - Resend QR code for mobile pairing
• /vpn conf <code>&lt;name&gt;</code> - Download client profile

<b>🦆 Dynamic DNS (DuckDNS / dynv6):</b>
• /dyndns - DynDNS status, public IP and countdown timer
• /dyndns update - Force immediate IP synchronization

<b>🛡️ DNS Ad-Blocker (Pi-hole Sinkhole):</b>
• /adblock - Sinkhole statistics, Gravity database and block ratio
• /adblock on | /adblock off - Enable / disable ad blocking
• /adblock block <code>&lt;domain&gt;</code> - Blacklist domain
• /adblock unblock <code>&lt;domain&gt;</code> - Whitelist domain
• /adblock update - Download and compile Gravity blocklists

<b>📶 Wi-Fi & Guest Wi-Fi Station Probe:</b>
• /wifi - Wireless telemetry, signal strength and isolation alerts
• /wifi scan - Scan surrounding 2.4/5 GHz Wi-Fi networks

<b>⚙️ System & Resources:</b>
• /tasks (or /top) - CPU, RAM, Disk, Temperature and top processes
• /heal - Autonomous self-healing and repair subsystem
• /backup - Manage and download full disaster recovery backups
• /drivers - Network controllers and hardware drivers
• /reboot - Safely restart the device host
• /sla - What the SLA result means
• /purge - Delete stored data
• /lang - Change interface language (EN, HU, DE, FR, UK)""",
        # Inline Button Labels
        "btn_quick_test": "📊 Quick Test",
        "btn_report": "📈 SLA Dossier",
        "btn_ping_details": "📡 Ping Details",
        "btn_top_resources": "⚙️ Resources (Top)",
        "btn_tailscale": "🦎 Tailscale",
        "btn_adblock": "🛡️ Ad Blocker",
        "btn_refresh": "🔄 Refresh",
        "btn_speedtest": "🚀 Speed Test",
        "btn_status": "📊 System Status",
        "btn_main_menu": "🏠 Main Menu",
        "btn_vpn_clients": "👥 Clients List",
        "btn_enable": "🟢 Enable",
        "btn_disable": "🔴 Disable",
        "btn_update_gravity": "🔄 Update Gravity",
        "btn_wifi_scan": "🔍 Wi-Fi Scan",
        "btn_probe_refresh": "🔄 Probe Refresh",
        "btn_vpn_hub": "🛡️ VPN Hub (WireGuard)",
        "btn_auth_open": "🔑 Open Authorization",
        "btn_rtr": "🔄 RTR-NetTest",
        "btn_ookla": "⚡ Ookla",
        "btn_cloudflare": "☁️ Cloudflare",
    },

    # -------------------------------------------------------------------------
    # GERMAN (de)
    # -------------------------------------------------------------------------
    "de": {
        "status_title": "📊 Systemstatus & Telemetrie",
        "bot_title": "NetworkMeasureBox Verwaltungs-Chatbot",
        "device_id": "Geräte-ID",
        "public_ip": "Öffentliche IP",
        "isp": "Internetanbieter (ISP)",
        "mode": "Betriebsmodus",
        "uptime_24h": "24h Verfügbarkeit",
        "latency_rtt": "Latenz (RTT)",
        "packet_loss": "Paketverlust",
        "sla_verdict": "SLA-Ergebnis (NMB-Bewertung)",
        "compliance": "SLA-Konformität",
        "latest_speed": "Letzte Messung",
        "services_security": "Dienste & Sicherheit",
        "download": "Download",
        "upload": "Upload",
        "server": "Messserver",
        "speed_result_label": "Ergebnis gegenüber garantierter Geschwindigkeit",
        "speed_starting": "<i>🚀 Starte Speedtest{engine_str}... Bitte ca. 15-25 Sekunden warten!</i>",
        "speed_error": "⚠️ Speedtest-Fehler: {error}",
        "speed_result_title": "<b>📊 Speedtest-Ergebnis ({engine})</b>",
        "ping_header": "<b>📡 Echtzeit-Latenz & Paketverlust (Letzte 60s):</b>\n",
        "ping_no_resp": "Keine Antwort",
        "ping_loss_label": "Verlust",
        "report_generating": "<i>📊 Generiere 24-Stunden-SLA-Prüfbericht...</i>",
        "report_caption": "<b>📋 Offizieller SLA-Netzwerkbericht (24h)</b>\nGerät: <code>{box_id}</code> | ISP: <b>{isp}</b>\nBehördliche Bewertung: <b>{verdict}</b>\nSLA-Konformität: <b>{sla:.0f}%</b> | Verfügbarkeit: <b>{uptime:.2f}%</b>",
        "report_fail": "Der Bericht wurde erstellt, der Dokumentenversand ist jedoch fehlgeschlagen.",
        "tailscale_title": "<b>🦎 Tailscale Mesh-VPN Status</b>",
        "tailscale_active": "🟢 AKTIV & VERBUNDEN",
        "tailscale_login_req": "🟡 AUTHENTIFIZIERUNG ERFORDERLICH",
        "tailscale_inactive": "⚫ INAKTIV ({backend_state})",
        "tailscale_desc_active": "Die Messbox ist sicher mit Ihrem Tailscale-Mesh-Netzwerk verbunden. Sie können das WebGUI sicher von überall unter dieser IP erreichen:\n👉 <code>http://{ip}:8080</code>",
        "tailscale_desc_login": "Das Gerät wartet auf Autorisierung. Öffnen Sie diesen Link zur Freigabe:\n👉 <a href=\"{url}\">{url}</a>",
        "tailscale_desc_inactive": "Tailscale ist derzeit getrennt oder nicht angemeldet.",
        "tailscale_role": "Rolle: Administration & WebGUI-Fernzugriff (keine Weiterleitung von normalem Internetverkehr)",
        "vpn_hub_title": "<b>🛡️ VPN-Server-Hub Status</b>",
        "vpn_wg_section": "<b>1. WireGuard Hochleistungs-VPN:</b>",
        "vpn_ovpn_section": "<b>2. OpenVPN Ausfallsicherer Server:</b>",
        "vpn_clients_title": "<b>Konfigurierte VPN-Clients:</b>\n",
        "vpn_wg_peers": "<b>🛡️ WireGuard-Peers:</b>",
        "vpn_ovpn_clients": "<b>🔒 OpenVPN-Clients:</b>",
        "vpn_no_wg": "<i>Keine WireGuard-Peers konfiguriert.</i>",
        "vpn_no_ovpn": "<i>Keine OpenVPN-Clients konfiguriert.</i>",
        "adblock_title": "<b>🛡️ DNS-Werbeblocker & Sinkhole (Pi-hole Engine)</b>",
        "adblock_enabled": "🟢 <b>DNS-Werbeblocker & Sinkhole AKTIVIERT</b>. Werbung und Tracking werden netzwerkweit gefiltert.",
        "adblock_disabled": "🔴 <b>DNS-Werbeblocker & Sinkhole DEAKTIVIERT</b>. DNS-Anfragen werden ungefiltert weitergeleitet.",
        "adblock_blocked_msg": "🚫 <b>Domain blockiert</b>: <code>{domain}</code> zur benutzerdefinierten Sperrliste hinzugefügt.",
        "adblock_unblocked_msg": "✅ <b>Domain freigegeben</b>: <code>{domain}</code> von Sperrliste entfernt und erlaubt.",
        "adblock_update_msg": "🔄 Download und Kompilierung der Gravity-Blocklisten gestartet.",
        "tasks_title": "<b>📊 Systemauslastung & Prozesstabelle</b>",
        "wifi_title": "<b>📶 WLAN- & Gast-WLAN-Sondenstatus</b>",
        "wifi_connected": "🟢 VERBUNDEN",
        "wifi_disconnected": "⚪ NICHT VERBUNDEN",
        "wifi_scan_title": "<b>🔍 Erkannte WLAN-Netzwerke ({count} gefunden):</b>\n",
        "wifi_no_networks": "Keine WLAN-Netzwerke in Reichweite erkannt.",
        "backup_title": "<b>📦 Gespeicherte Systemsicherungen:</b>\n",
        "backup_none": "Keine lokalen Backups in <code>/var/lib/nmb/backups/</code> gefunden.",
        "backup_created": "✅ <b>Systemsicherung erfolgreich erstellt!</b>\n\nDateiname: <code>{fname}</code>\nGröße: <b>{size}</b>\nEnthält: Konfiguration (/etc/nmb), Datenbankverlauf, kryptografische WireGuard- und OpenVPN-Schlüssel.\n\nHerunterladen: <code>/backup send {fname}</code>",
        "drivers_title": "<b>🔧 Hardware-Netzwerk-Controller & Treiber:</b>\n",
        "reboot_confirm": "⚠️ <b>Neustart-Bestätigung erforderlich</b>\nUm das Gerät sicher neu zu starten, senden Sie:\n👉 <code>/reboot now</code>",
        "reboot_starting": "🔄 <b>Starte NetworkMeasureBox neu...</b> Verbindung wird in ca. 45 Sekunden wiederhergestellt.",
        "unknown_cmd": "Unbekannter Befehl: <code>{cmd}</code>. Drücken Sie eine der Menütasten oder nutzen Sie /help.",
        "lang_title": "🌐 <b>Spracheinstellungen</b>",
        "lang_desc": "Aktuelle Sprache: <b>{curr_lang}</b>\n\nBitte wählen Sie die gewünschte Sprache aus:",
        "lang_updated": "🌐 Bot-Sprache erfolgreich auf <b>{flag} {name}</b> umgestellt!\nDas Menü und alle zukünftigen Ausgaben sind nun auf Deutsch lokalisiert.",
        "help_message": """<b>NetworkMeasureBox Verwaltungs-Chatbot</b>
<i>Geräte-ID: {box_id}</i>

<b>📡 Netzwerkmessungen & Diagnose:</b>
• /status - Systemstatus, Uptime, CPU und SLA-Konformität
• /ping - Echtzeit-Latenz und Paketverlust zu Referenz-Knoten
• /test (oder /speed) <code>[ookla|cloudflare|rtr]</code> - Speedtest ausführen
• /report - 24-Stunden-SLA-Prüfbericht herunterladen (.html)
• /ai - AI-Diagnoseprotokoll für LLMs herunterladen (.md)
• /mode <code>[auto|standalone|mode_a|mode_b]</code> - Betriebsmodus wechseln

<b>🛡️ Sicherheit, VPN & Tailscale:</b>
• /tailscale - Tailscale Mesh-VPN Status, WebGUI-Link & Login
• /vpn - WireGuard- & OpenVPN-Status und Clients
• /vpn clients - Verbundene Clients und Datenübertragung
• /vpn add <code>&lt;Name&gt;</code> - Neuen WireGuard-Client + QR-Code & .conf erstellen!
• /vpn qr <code>&lt;Name&gt;</code> - QR-Code für Smartphone-Kopplung erneut senden
• /vpn conf <code>&lt;Name&gt;</code> - Konfigurationsprofil herunterladen

<b>🦆 Dynamisches DNS (DuckDNS / dynv6):</b>
• /dyndns - DynDNS-Status, öffentliche IP und Synchronisationszähler
• /dyndns update - Sofortige manuelle Synchronisation erzwingen

<b>🛡️ DNS-Werbeblocker (Pi-hole Sinkhole):</b>
• /adblock - Blockierte Anfragen, Gravity-Datenbank und Quote
• /adblock on | /adblock off - Werbeblocker ein-/ausschalten
• /adblock block <code>&lt;Domain&gt;</code> - Domain sperren
• /adblock unblock <code>&lt;Domain&gt;</code> - Domain freigeben
• /adblock update - Gravity-Blocklisten herunterladen und kompilieren

<b>📶 WLAN- & Gast-WLAN-Sonde:</b>
• /wifi - WLAN-Sondentelemetrie, Signalstärke und Isolationswarnung
• /wifi scan - Umgebende 2.4/5 GHz WLAN-Netzwerke scannen

<b>⚙️ System & Ressourcen:</b>
• /tasks (oder /top) - CPU, RAM, Speicher, Temperatur und Top-Prozesse
• /heal - Autonomes Selbstheilungs- und Reparatursystem
• /backup - Systemsicherungen verwalten und herunterladen
• /drivers - Netzwerk-Controller und Treiberstatus
• /reboot - Gerät sicher neu starten
• /sla - Bedeutung des SLA-Ergebnisses
• /purge - Gespeicherte Daten löschen
• /lang - Sprache ändern (DE, EN, HU, FR, UK)""",
        # Inline Button Labels
        "btn_quick_test": "📊 Schnelltest",
        "btn_report": "📈 SLA-Dossier",
        "btn_ping_details": "📡 Ping-Details",
        "btn_top_resources": "⚙️ Ressourcen (Top)",
        "btn_tailscale": "🦎 Tailscale",
        "btn_adblock": "🛡️ Werbeblocker",
        "btn_refresh": "🔄 Aktualisieren",
        "btn_speedtest": "🚀 Speedtest",
        "btn_status": "📊 Systemstatus",
        "btn_main_menu": "🏠 Hauptmenü",
        "btn_vpn_clients": "👥 Client-Liste",
        "btn_enable": "🟢 Aktivieren",
        "btn_disable": "🔴 Deaktivieren",
        "btn_update_gravity": "🔄 Gravity aktualisieren",
        "btn_wifi_scan": "🔍 WLAN-Scan",
        "btn_probe_refresh": "🔄 Sonde aktualisieren",
        "btn_vpn_hub": "🛡️ VPN-Hub (WireGuard)",
        "btn_auth_open": "🔑 Anmeldung öffnen",
        "btn_rtr": "🔄 RTR-NetTest",
        "btn_ookla": "⚡ Ookla",
        "btn_cloudflare": "☁️ Cloudflare",
    },

    # -------------------------------------------------------------------------
    # FRENCH (fr)
    # -------------------------------------------------------------------------
    "fr": {
        "status_title": "📊 État du Système & Télémétrie",
        "bot_title": "Chatbot de Gestion NetworkMeasureBox",
        "device_id": "Identifiant de l'appareil",
        "public_ip": "IP Publique",
        "isp": "Fournisseur d'accès (FAI)",
        "mode": "Mode de fonctionnement",
        "uptime_24h": "Disponibilité 24h",
        "latency_rtt": "Latence (RTT)",
        "packet_loss": "Perte de paquets",
        "sla_verdict": "Résultat SLA (évaluation NMB)",
        "compliance": "Conformité SLA",
        "latest_speed": "Dernier débit",
        "services_security": "Services & Sécurité",
        "download": "Téléchargement",
        "upload": "Téléversement",
        "server": "Serveur de mesure",
        "speed_result_label": "Résultat par rapport au débit garanti",
        "speed_starting": "<i>🚀 Démarrage du test de débit{engine_str}... Veuillez patienter 15 à 25 secondes!</i>",
        "speed_error": "⚠️ Erreur du test de débit: {error}",
        "speed_result_title": "<b>📊 Résultat du test de débit ({engine})</b>",
        "ping_header": "<b>📡 Latence en temps réel & Perte de paquets (Dernières 60s):</b>\n",
        "ping_no_resp": "Aucune réponse",
        "ping_loss_label": "perte",
        "report_generating": "<i>📊 Génération du dossier d'audit officiel SLA 24h...</i>",
        "report_caption": "<b>📋 Dossier d'audit réseau officiel (24h)</b>\nAppareil: <code>{box_id}</code> | FAI: <b>{isp}</b>\nVerdict réglementaire: <b>{verdict}</b>\nConformité SLA: <b>{sla:.0f}%</b> | Disponibilité: <b>{uptime:.2f}%</b>",
        "report_fail": "Le dossier a été généré, mais l'envoi du document a échoué.",
        "tailscale_title": "<b>🦎 État du VPN Mesh Tailscale</b>",
        "tailscale_active": "🟢 ACTIF & CONNECTÉ",
        "tailscale_login_req": "🟡 AUTHENTIFICATION REQUISE",
        "tailscale_inactive": "⚫ INACTIF ({backend_state})",
        "tailscale_desc_active": "Le boîtier de mesure est connecté en toute sécurité à votre réseau Tailscale. Accédez à l'interface WebGUI partout depuis cette adresse:\n👉 <code>http://{ip}:8080</code>",
        "tailscale_desc_login": "L'appareil attend votre autorisation. Ouvrez ce lien pour approuver l'accès:\n👉 <a href=\"{url}\">{url}</a>",
        "tailscale_desc_inactive": "Tailscale est actuellement déconnecté ou non connecté.",
        "tailscale_role": "Rôle: Administration & accès WebGUI distant sécurisé (aucun routage de trafic Internet externe)",
        "vpn_hub_title": "<b>🛡️ État du Hub Serveur VPN</b>",
        "vpn_wg_section": "<b>1. VPN Haute Performance WireGuard:</b>",
        "vpn_ovpn_section": "<b>2. Serveur OpenVPN de Secours:</b>",
        "vpn_clients_title": "<b>Clients VPN Configurés:</b>\n",
        "vpn_wg_peers": "<b>🛡️ Pairs WireGuard:</b>",
        "vpn_ovpn_clients": "<b>🔒 Clients OpenVPN:</b>",
        "vpn_no_wg": "<i>Aucun pair WireGuard configuré.</i>",
        "vpn_no_ovpn": "<i>Aucun client OpenVPN configuré.</i>",
        "adblock_title": "<b>🛡️ Bloqueur de Pub & Sinkhole DNS (Moteur Pi-hole)</b>",
        "adblock_enabled": "🟢 <b>Bloqueur de Pub DNS ACTIVÉ</b>. Les publicités et traceurs sont activement filtrés.",
        "adblock_disabled": "🔴 <b>Bloqueur de Pub DNS DÉSACTIVÉ</b>. Les requêtes DNS sont transmises sans filtrage.",
        "adblock_blocked_msg": "🚫 <b>Domaine Bloqué</b>: <code>{domain}</code> ajouté à la liste noire personnalisée.",
        "adblock_unblocked_msg": "✅ <b>Domaine Autorisé</b>: <code>{domain}</code> retiré de la liste noire et autorisé.",
        "adblock_update_msg": "🔄 Téléchargement et compilation des listes Gravity en cours.",
        "tasks_title": "<b>📊 Charge des Ressources Système & Processus</b>",
        "wifi_title": "<b>📶 État de la Sonde Wi-Fi & Réseau Invité</b>",
        "wifi_connected": "🟢 CONNECTÉ",
        "wifi_disconnected": "⚪ DÉCONNECTÉ",
        "wifi_scan_title": "<b>🔍 Réseaux Wi-Fi Détectés ({count} trouvés):</b>\n",
        "wifi_no_networks": "Aucun point d'accès Wi-Fi détecté.",
        "backup_title": "<b>📦 Sauvegardes Système Disponibles:</b>\n",
        "backup_none": "Aucune sauvegarde locale trouvée dans <code>/var/lib/nmb/backups/</code>.",
        "backup_created": "✅ <b>Sauvegarde Système Créée!</b>\n\nNom: <code>{fname}</code>\nTaille: <b>{size}</b>\nContient: Configuration (/etc/nmb), Historique SQL, Clés cryptographiques WireGuard & OpenVPN.\n\nTélécharger: <code>/backup send {fname}</code>",
        "drivers_title": "<b>🔧 Contrôleurs Réseau Matériels & Pilotes:</b>\n",
        "reboot_confirm": "⚠️ <b>Confirmation de Redémarrage Requise</b>\nPour redémarrer NetworkMeasureBox en toute sécurité, envoyez:\n👉 <code>/reboot now</code>",
        "reboot_starting": "🔄 <b>Redémarrage de NetworkMeasureBox en cours...</b> La connectivité reprendra dans environ 45 secondes.",
        "unknown_cmd": "Commande inconnue: <code>{cmd}</code>. Appuyez sur un bouton du menu ou tapez /help.",
        "lang_title": "🌐 <b>Paramètres de Langue</b>",
        "lang_desc": "Langue actuelle: <b>{curr_lang}</b>\n\nVeuillez sélectionner votre langue préférée:",
        "lang_updated": "🌐 La langue du bot a été changée pour <b>{flag} {name}</b>!\nLe menu et tous les messages sont désormais traduits en français.",
        "help_message": """<b>Chatbot de Gestion NetworkMeasureBox</b>
<i>Identifiant: {box_id}</i>

<b>📡 Mesures Réseau & Diagnostics:</b>
• /status - État du système, Disponibilité, CPU et conformité SLA
• /ping - Latence en temps réel et perte de paquets vers les nœuds
• /test (ou /speed) <code>[ookla|cloudflare|rtr]</code> - Lancer un test de débit
• /report - Télécharger le dossier d'audit SLA 24h (.html)
• /ai - Télécharger le snapshot de diagnostic pour LLM (.md)
• /mode <code>[auto|standalone|mode_a|mode_b]</code> - Changer le mode réseau

<b>🛡️ Sécurité, VPN & Tailscale:</b>
• /tailscale - État du VPN Mesh Tailscale, lien WebGUI & connexion
• /vpn - État des serveurs WireGuard & OpenVPN et clients
• /vpn clients - Clients connectés et volume de transfert
• /vpn add <code>&lt;nom&gt;</code> - Créer un client WireGuard + QR code et .conf!
• /vpn qr <code>&lt;nom&gt;</code> - Renvoyer le QR code pour smartphone
• /vpn conf <code>&lt;nom&gt;</code> - Télécharger le profil de configuration

<b>🦆 DNS Dynamique (DuckDNS / dynv6):</b>
• /dyndns - État DynDNS, IP publique et compte à rebours de sync
• /dyndns update - Forcer une synchronisation immédiate

<b>🛡️ Bloqueur de Pub DNS (Moteur Pi-hole):</b>
• /adblock - Requêtes bloquées, base Gravity et taux de blocage
• /adblock on | /adblock off - Activer / désactiver le filtrage
• /adblock block <code>&lt;domaine&gt;</code> - Bloquer un domaine
• /adblock unblock <code>&lt;domaine&gt;</code> - Autoriser un domaine
• /adblock update - Mettre à jour les listes Gravity

<b>📶 Sonde Wi-Fi & Réseau Invité:</b>
• /wifi - Télémétrie Wi-Fi, force du signal et alertes d'isolation
• /wifi scan - Scanner les réseaux sans fil 2.4/5 GHz alentours

<b>⚙️ Système & Ressources:</b>
• /tasks (ou /top) - CPU, RAM, Disque, Température et top processus
• /heal - Sous-système d'autoréparation autonome
• /backup - Gérer et télécharger les sauvegardes complètes
• /drivers - Contrôleurs réseau et pilotes matériels
• /reboot - Redémarrer l'appareil en toute sécurité
• /sla - Signification du résultat SLA
• /purge - Supprimer les données stockées
• /lang - Changer la langue (FR, EN, HU, DE, UK)""",
        # Inline Button Labels
        "btn_quick_test": "📊 Test rapide",
        "btn_report": "📈 Dossier SLA",
        "btn_ping_details": "📡 Détails du Ping",
        "btn_top_resources": "⚙️ Ressources (Top)",
        "btn_tailscale": "🦎 Tailscale",
        "btn_adblock": "🛡️ Bloqueur de pub",
        "btn_refresh": "🔄 Actualiser",
        "btn_speedtest": "🚀 Test de débit",
        "btn_status": "📊 État du système",
        "btn_main_menu": "🏠 Menu principal",
        "btn_vpn_clients": "👥 Liste des clients",
        "btn_enable": "🟢 Activer",
        "btn_disable": "🔴 Désactiver",
        "btn_update_gravity": "🔄 Mettre à jour Gravity",
        "btn_wifi_scan": "🔍 Recherche Wi-Fi",
        "btn_probe_refresh": "🔄 Actualiser sonde",
        "btn_vpn_hub": "🛡️ Hub VPN (WireGuard)",
        "btn_auth_open": "🔑 Ouvrir l'autorisation",
        "btn_rtr": "🔄 RTR-NetTest",
        "btn_ookla": "⚡ Ookla",
        "btn_cloudflare": "☁️ Cloudflare",
    },

    # -------------------------------------------------------------------------
    # UKRAINIAN (uk)
    # -------------------------------------------------------------------------
    "uk": {
        "status_title": "📊 Стан системи та телеметрія",
        "bot_title": "Керуючий чат-бот NetworkMeasureBox",
        "device_id": "Ідентифікатор пристрою",
        "public_ip": "Публічна IP-адреса",
        "isp": "Провайдер (ISP)",
        "mode": "Режим роботи",
        "uptime_24h": "Доступність за 24г",
        "latency_rtt": "Затримка (RTT)",
        "packet_loss": "Втрата пакетів",
        "sla_verdict": "Результат SLA (оцінка NMB)",
        "compliance": "Відповідність SLA",
        "latest_speed": "Остання швидкість",
        "services_security": "Служби та безпека",
        "download": "Завантаження",
        "upload": "Вивантаження",
        "server": "Сервер тестування",
        "speed_result_label": "Результат щодо гарантованої швидкості",
        "speed_starting": "<i>🚀 Запуск тесту швидкості{engine_str}... Зачекайте приблизно 15-25 секунд!</i>",
        "speed_error": "⚠️ Помилка вимірювання швидкості: {error}",
        "speed_result_title": "<b>📊 Результат тесту швидкості ({engine})</b>",
        "ping_header": "<b>📡 Затримка в реальному часі та втрата пакетів (Останні 60с):</b>\n",
        "ping_no_resp": "Немає відповіді",
        "ping_loss_label": "втрата",
        "report_generating": "<i>📊 Створення 24-годинного офіційного протоколу перевірки SLA...</i>",
        "report_caption": "<b>📋 Офіційний звіт аудиту мережі SLA (24г)</b>\nПристрій: <code>{box_id}</code> | Провайдер: <b>{isp}</b>\nНормативний вердикт: <b>{verdict}</b>\nВідповідність SLA: <b>{sla:.0f}%</b> | Доступність: <b>{uptime:.2f}%</b>",
        "report_fail": "Звіт створено, але не вдалося надіслати файл.",
        "tailscale_title": "<b>🦎 Стан Mesh VPN Tailscale</b>",
        "tailscale_active": "🟢 АКТИВНО ТА ПІДКЛЮЧЕНО",
        "tailscale_login_req": "🟡 ПОТРІБНА АВТОРИЗАЦІЯ",
        "tailscale_inactive": "⚫ НЕАКТИВНО ({backend_state})",
        "tailscale_desc_active": "Вимірювальний модуль успішно підключено до вашої мережі Tailscale. Ви можете безпечно отримати доступ до WebGUI з будь-якого місця за адресою:\n👉 <code>http://{ip}:8080</code>",
        "tailscale_desc_login": "Пристрій очікує авторизації. Відкрийте посилання для підтвердження:\n👉 <a href=\"{url}\">{url}</a>",
        "tailscale_desc_inactive": "Tailscale наразі відключено або не виконано вхід.",
        "tailscale_role": "Роль: Адміністрування та безпечний віддалений доступ до WebGUI (без маршрутизації інтернет-трафіку)",
        "vpn_hub_title": "<b>🛡️ Стан вузла VPN-серверів</b>",
        "vpn_wg_section": "<b>1. Високошвидкісний VPN WireGuard:</b>",
        "vpn_ovpn_section": "<b>2. Відмовостійкий сервер OpenVPN:</b>",
        "vpn_clients_title": "<b>Налаштовані клієнти VPN:</b>\n",
        "vpn_wg_peers": "<b>🛡️ Клієнти WireGuard:</b>",
        "vpn_ovpn_clients": "<b>🔒 Клієнти OpenVPN:</b>",
        "vpn_no_wg": "<i>Клієнти WireGuard не налаштовані.</i>",
        "vpn_no_ovpn": "<i>Клієнти OpenVPN не налаштовані.</i>",
        "adblock_title": "<b>🛡️ Блокувальник реклами DNS (Двигун Pi-hole)</b>",
        "adblock_enabled": "🟢 <b>Блокувальник реклами DNS УВІМКНЕНО</b>. Мережева реклама та трекери активно фільтруються.",
        "adblock_disabled": "🔴 <b>Блокувальник реклами DNS ВИМКНЕНО</b>. Запити DNS надсилаються без фільтрації.",
        "adblock_blocked_msg": "🚫 <b>Домен заблоковано</b>: <code>{domain}</code> додано до власного чорного списку.",
        "adblock_unblocked_msg": "✅ <b>Домен дозволено</b>: <code>{domain}</code> видалено з чорного списку та дозволено.",
        "adblock_update_msg": "🔄 Завантаження та компіляція списків блокування Gravity триває.",
        "tasks_title": "<b>📊 Навантаження системних ресурсів і таблиця процесів</b>",
        "wifi_title": "<b>📶 Стан Wi-Fi зонда та гостьової мережі</b>",
        "wifi_connected": "🟢 ПІДКЛЮЧЕНО",
        "wifi_disconnected": "⚪ ВІДКЛЮЧЕНО",
        "wifi_scan_title": "<b>🔍 Виявлені мережі Wi-Fi ({count} знайдено):</b>\n",
        "wifi_no_networks": "Wi-Fi мереж не виявлено.",
        "backup_title": "<b>📦 Збережені резервні копії системи:</b>\n",
        "backup_none": "Локальних резервних копій у <code>/var/lib/nmb/backups/</code> не знайдено.",
        "backup_created": "✅ <b>Резервну копію системи створено!</b>\n\nІм'я файлу: <code>{fname}</code>\nРозмір: <b>{size}</b>\nМістить: Конфігурацію (/etc/nmb), Історію бази даних, Ключі WireGuard та OpenVPN.\n\nЗавантажити на телефон: <code>/backup send {fname}</code>",
        "drivers_title": "<b>🔧 Апаратні мережеві контролери та драйвери:</b>\n",
        "reboot_confirm": "⚠️ <b>Потрібне підтвердження перезавантаження</b>\nЩоб безпечно перезавантажити пристрій NetworkMeasureBox, надішліть:\n👉 <code>/reboot now</code>",
        "reboot_starting": "🔄 <b>Перезавантаження NetworkMeasureBox...</b> Зв'язок відновиться приблизно через 45 секунд.",
        "unknown_cmd": "Невідома команда: <code>{cmd}</code>. Натисніть одну з кнопок меню або введіть /help.",
        "lang_title": "🌐 <b>Налаштування мови</b>",
        "lang_desc": "Поточна мова: <b>{curr_lang}</b>\n\nОберіть бажану мову за допомогою кнопок нижче:",
        "lang_updated": "🌐 Мову бота успішно змінено на <b>{flag} {name}</b>!\nМеню та всі подальші повідомлення будуть відображатися українською мовою.",
        "help_message": """<b>Керуючий чат-бот NetworkMeasureBox</b>
<i>Ідентифікатор: {box_id}</i>

<b>📡 Вимірювання мережі та діагностика:</b>
• /status - Стан системи, Uptime, CPU та відповідність SLA
• /ping - Затримка в реальному часі та втрата пакетів до вузлів
• /test (або /speed) <code>[ookla|cloudflare|rtr]</code> - Запустити тест швидкості
• /report - Завантажити 24-годинний офіційний звіт SLA (.html)
• /ai - Завантажити пакет діагностики для LLM (.md)
• /mode <code>[auto|standalone|mode_a|mode_b]</code> - Змінити режим роботи

<b>🛡️ Безпека, VPN та Tailscale:</b>
• /tailscale - Стан Tailscale mesh VPN, посилання WebGUI та вхід
• /vpn - Стан серверів WireGuard та OpenVPN і клієнти
• /vpn clients - Підключені клієнти та обсяг трафіку
• /vpn add <code>&lt;ім'я&gt;</code> - Створити клієнта WireGuard + QR-код і .conf!
• /vpn qr <code>&lt;ім'я&gt;</code> - Надіслати QR-код для мобільного пристрою
• /vpn conf <code>&lt;ім'я&gt;</code> - Завантажити конфігураційний файл

<b>🦆 Динамічний DNS (DuckDNS / dynv6):</b>
• /dyndns - Стан DynDNS, публічна IP та таймер оновлення
• /dyndns update - Примусова ручна синхронізація

<b>🛡️ Блокувальник реклами DNS (Двигун Pi-hole):</b>
• /adblock - Статистика блокування, база Gravity та відсоток
• /adblock on | /adblock off - Увімкнути / вимкнути блокування
• /adblock block <code>&lt;домен&gt;</code> - Заблокувати домен
• /adblock unblock <code>&lt;домен&gt;</code> - Дозволити домен
• /adblock update - Завантажити та скомпілювати списки Gravity

<b>📶 Wi-Fi зонд та гостьова мережа:</b>
• /wifi - Телеметрія Wi-Fi, потужність сигналу та попередження ізоляції
• /wifi scan - Пошук мереж Wi-Fi 2.4/5 ГГц навколо

<b>⚙️ Система та ресурси:</b>
• /tasks (або /top) - CPU, RAM, Диск, Температура та топ процесів
• /heal - Модуль автономного самовідновлення та виправлення
• /backup - Керування та завантаження резервних копій
• /drivers - Мережеві контролери та драйвери
• /reboot - Безпечне перезавантаження пристрою
• /sla - Що означає результат SLA
• /purge - Видалення збережених даних
• /lang - Змінити мову (UK, EN, HU, DE, FR)""",
        # Inline Button Labels
        "btn_quick_test": "📊 Швидкий тест",
        "btn_report": "📈 Досьє SLA",
        "btn_ping_details": "📡 Деталі пінг",
        "btn_top_resources": "⚙️ Ресурси (Top)",
        "btn_tailscale": "🦎 Tailscale",
        "btn_adblock": "🛡️ Блокувальник реклами",
        "btn_refresh": "🔄 Оновити",
        "btn_speedtest": "🚀 Тест швидкості",
        "btn_status": "📊 Стан системи",
        "btn_main_menu": "🏠 Головне меню",
        "btn_vpn_clients": "👥 Список клієнтів",
        "btn_enable": "🟢 Увімкнути",
        "btn_disable": "🔴 Вимкнути",
        "btn_update_gravity": "🔄 Оновити Gravity",
        "btn_wifi_scan": "🔍 Пошук Wi-Fi",
        "btn_probe_refresh": "🔄 Оновити зонд",
        "btn_vpn_hub": "🛡️ VPN Hub (WireGuard)",
        "btn_auth_open": "🔑 Відкрити авторизацію",
        "btn_rtr": "🔄 RTR-NetTest",
        "btn_ookla": "⚡ Ookla",
        "btn_cloudflare": "☁️ Cloudflare",
    }
}


for _key, _values in MESSAGES.items():
    for _lang, _value in zip(LANGUAGE_ORDER, _values):
        STRINGS[_lang].setdefault(_key, _value)


def t(key: str, lang: str = DEFAULT_LANGUAGE, **kwargs) -> str:
    """Retrieve translated string by key with fallback to English."""
    lang = lang if lang in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE
    tmpl = STRINGS.get(lang, {}).get(key)
    if not tmpl:
        tmpl = STRINGS.get("en", {}).get(key)
    if not tmpl:
        tmpl = key
    if kwargs:
        try:
            return tmpl.format(**kwargs)
        except Exception:
            log.debug("suppressed exception", exc_info=True)
            return tmpl
    return tmpl


# =============================================================================
# 5. Proactive Alerts Localization
# =============================================================================

ALERT_TEMPLATES: Dict[str, Dict[str, str]] = {
    "hu": {
        "outage_start": "🚨 <b>KRITIKUS HÁLÓZATI KIMARADÁS ÉSZLELVE</b>\n\nMinden mérési célpont elérhetetlen.\nKiváltó ok: <i>{cause}</i>\nEszközazonosító: <code>{box_id}</code>",
        "outage_resolved": "✅ <b>HÁLÓZATI KIMARADÁS MEGSZŰNT</b>\n\nInternetkapcsolat helyreállt.\nTeljes kiesési idő: <b>{dur}s</b>\nEszközazonosító: <code>{box_id}</code>",
        "packet_loss_firing": "⚠️ <b>MAGAS CSOMAGVESZTÉS RIASZTÁS</b>\n\nCsomagvesztés: <b>{loss:.1f}%</b> (küszöbérték: {threshold:.1f}%)\nCsomagok: {lost} elveszett / {sent} elküldött (elmúlt 5 perc)\nEszközazonosító: <code>{box_id}</code>",
        "packet_loss_resolved": "✅ <b>CSOMAGVESZTÉS HELYREÁLLT</b>\n\nA csomagvesztés normalizálódott: <b>{loss:.1f}%</b>.",
        "service_failure_firing": "🚨 <b>RENDSZERSZOLGÁLTATÁS LEÁLLÁS ÉSZLELVE</b>\n\nLeállt szolgáltatás(ok): {services}\nAutomatikus 1. szintű öngyógyítás elindítása...",
        "service_failure_resolved": "✅ <b>MINDEN RENDSZERSZOLGÁLTATÁS HELYREÁLLT</b>\n\nAz összes alapvető daemon aktív és működőképes.",
        "overheat_firing": "🔥 <b>HARDVER TÚLMELEGEDÉS FIGYELMEZTETÉS</b>\n\nSoC / CPU Hőmérséklet: <b>{temp:.1f}°C</b> (határérték: 82°C)\nEllenőrizze a hűtést és a szellőzést.",
        "overheat_resolved": "✅ <b>HŐMÉRSÉKLET NORMALIZÁLÓDOTT</b>\n\nA CPU hőmérséklete visszatért a biztonságos tartományba: <b>{temp:.1f}°C</b>.",
        "low_disk_firing": "💾 <b>ALACSONY TÁRHELY FIGYELMEZTETÉS</b>\n\nSzabad hely a gyökérpartíción: <b>{free:.0f} MB</b> (&lt; 500 MB)\nRégi mentések törlése javasolt: <code>/backup list</code>",
        "low_disk_resolved": "✅ <b>TÁRHELY HELYREÁLLT</b>\n\nSzabad lemezterület: <b>{free:.0f} MB</b>.",
        "wan_failover_firing": "🔀 <b>AUTOMATIKUS WAN ÁTKAPCSOLÁS (FAILOVER)</b>\n\nElsődleges WAN (<code>{primary}</code>) kapcsolat megszakadt.\nÁtkapcsolva a tartalék interfészre: <code>{active}</code>.",
        "wan_failover_resolved": "✅ <b>ELSŐDLEGES WAN KAPCSOLAT HELYREÁLLT</b>\n\nA forgalom visszairányítva az elsődleges interfészre: <code>{primary}</code>.",
    },
    "en": {
        "outage_start": "🚨 <b>CRITICAL NETWORK OUTAGE DETECTED</b>\n\nAll probe targets unreachable.\nCause: <i>{cause}</i>\nDevice ID: <code>{box_id}</code>",
        "outage_resolved": "✅ <b>NETWORK OUTAGE RESOLVED</b>\n\nInternet connectivity restored.\nTotal downtime: <b>{dur}s</b>\nDevice ID: <code>{box_id}</code>",
        "packet_loss_firing": "⚠️ <b>HIGH PACKET LOSS ALERT</b>\n\nRolling loss: <b>{loss:.1f}%</b> (threshold: {threshold:.1f}%)\nPackets: {lost} lost / {sent} sent (past 5 min)\nDevice ID: <code>{box_id}</code>",
        "packet_loss_resolved": "✅ <b>PACKET LOSS RECOVERED</b>\n\nPacket loss normalized to <b>{loss:.1f}%</b>.",
        "service_failure_firing": "🚨 <b>SYSTEM SERVICE FAILURE DETECTED</b>\n\nFailed service(s): {services}\nTriggering automated Self-Healing Tier 1 recovery...",
        "service_failure_resolved": "✅ <b>ALL SYSTEM SERVICES RESTORED</b>\n\nAll core daemons are active and operational.",
        "overheat_firing": "🔥 <b>HARDWARE OVERHEATING WARNING</b>\n\nSoC / CPU Temperature: <b>{temp:.1f}°C</b> (limit: 82°C)\nCheck ambient airflow or cooling.",
        "overheat_resolved": "✅ <b>TEMPERATURE NORMALIZED</b>\n\nCPU temperature returned to safe range: <b>{temp:.1f}°C</b>.",
        "low_disk_firing": "💾 <b>LOW DISK STORAGE WARNING</b>\n\nFree space on root partition: <b>{free:.0f} MB</b> (&lt; 500 MB)\nConsider clearing old backups: <code>/backup list</code>",
        "low_disk_resolved": "✅ <b>DISK STORAGE RECOVERED</b>\n\nFree disk space: <b>{free:.0f} MB</b>.",
        "wan_failover_firing": "🔀 <b>WAN FAILOVER ENGAGED</b>\n\nPrimary WAN (<code>{primary}</code>) link failed.\nSwitched to backup interface: <code>{active}</code>.",
        "wan_failover_resolved": "✅ <b>PRIMARY WAN LINK RESTORED</b>\n\nTraffic routed back to primary interface: <code>{primary}</code>.",
    },
    "de": {
        "outage_start": "🚨 <b>KRITISCHER NETZWERKAUSFALL ERKANNT</b>\n\nAlle Messziele nicht erreichbar.\nUrsache: <i>{cause}</i>\nGeräte-ID: <code>{box_id}</code>",
        "outage_resolved": "✅ <b>NETZWERKAUSFALL BEHOBEN</b>\n\nInternetverbindung wiederhergestellt.\nGesamtausfallzeit: <b>{dur}s</b>\nGeräte-ID: <code>{box_id}</code>",
        "packet_loss_firing": "⚠️ <b>WARNUNG: HOHER PAKETVERLUST</b>\n\nPaketverlust: <b>{loss:.1f}%</b> (Schwellenwert: {threshold:.1f}%)\nPakete: {lost} verloren / {sent} gesendet (letzte 5 Min.)\nGeräte-ID: <code>{box_id}</code>",
        "packet_loss_resolved": "✅ <b>PAKETVERLUST NORMALISIERT</b>\n\nPaketverlust normalisiert auf <b>{loss:.1f}%</b>.",
        "service_failure_firing": "🚨 <b>SYSTEMDIENST-AUSFALL ERKANNT</b>\n\nAusgefallene(r) Dienst(e): {services}\nAutomatische Selbstheilung (Stufe 1) gestartet...",
        "service_failure_resolved": "✅ <b>ALLE SYSTEMDIENSTE WIEDERHERGESTELLT</b>\n\nAlle Kern-Daemons sind aktiv und betriebsbereit.",
        "overheat_firing": "🔥 <b>WARNUNG: HARDWARE-ÜBERHITZUNG</b>\n\nSoC / CPU-Temperatur: <b>{temp:.1f}°C</b> (Grenzwert: 82°C)\nBitte Belüftung oder Kühlung prüfen.",
        "overheat_resolved": "✅ <b>TEMPERATUR NORMALISIERT</b>\n\nCPU-Temperatur wieder im sicheren Bereich: <b>{temp:.1f}°C</b>.",
        "low_disk_firing": "💾 <b>WARNUNG: GERINGER SPEICHERPLATZ</b>\n\nFreier Speicher auf Root-Partition: <b>{free:.0f} MB</b> (&lt; 500 MB)\nAlte Backups bereinigen empfohlen: <code>/backup list</code>",
        "low_disk_resolved": "✅ <b>SPEICHERPLATZ WIEDERHERGESTELLT</b>\n\nFreier Speicherplatz: <b>{free:.0f} MB</b>.",
        "wan_failover_firing": "🔀 <b>AUTOMATISCHES WAN-FAILOVER AKTIVIERT</b>\n\nPrimärer WAN-Uplink (<code>{primary}</code>) ausgefallen.\nUmgewechselt auf Backup-Schnittstelle: <code>{active}</code>.",
        "wan_failover_resolved": "✅ <b>PRIMÄRER WAN-UPLINK WIEDERHERGESTELLT</b>\n\nVerkehr wird wieder über primäre Schnittstelle geroutet: <code>{primary}</code>.",
    },
    "fr": {
        "outage_start": "🚨 <b>PANNE RÉSEAU CRITIQUE DÉTECTÉE</b>\n\nToutes les cibles de test sont inaccessibles.\nCause: <i>{cause}</i>\nIdentifiant: <code>{box_id}</code>",
        "outage_resolved": "✅ <b>PANNE RÉSEAU RÉSOLUE</b>\n\nConnectivité Internet rétablie.\nTemps d'arrêt total: <b>{dur}s</b>\nIdentifiant: <code>{box_id}</code>",
        "packet_loss_firing": "⚠️ <b>ALERTE: PERTE DE PAQUETS ÉLEVÉE</b>\n\nPerte glissante: <b>{loss:.1f}%</b> (seuil: {threshold:.1f}%)\nPaquets: {lost} perdus / {sent} envoyés (dernières 5 min)\nIdentifiant: <code>{box_id}</code>",
        "packet_loss_resolved": "✅ <b>PERTE DE PAQUETS NORMALISÉE</b>\n\nPerte de paquets revenue à <b>{loss:.1f}%</b>.",
        "service_failure_firing": "🚨 <b>DÉFAILLANCE D'UN SERVICE SYSTÈME</b>\n\nService(s) défaillant(s): {services}\nDéclenchement de l'autoréparation automatique niveau 1...",
        "service_failure_resolved": "✅ <b>TOUS LES SERVICES SYSTÈME SONT RESTAURÉS</b>\n\nTous les daemons principaux sont actifs et opérationnels.",
        "overheat_firing": "🔥 <b>AVERTISSEMENT: SURCHAUFFE MATÉRIELLE</b>\n\nTempérature SoC / CPU: <b>{temp:.1f}°C</b> (limite: 82°C)\nVérifiez le flux d'air ou le refroidissement.",
        "overheat_resolved": "✅ <b>TEMPÉRATURE NORMALISÉE</b>\n\nTempérature CPU revenue dans la plage de sécurité: <b>{temp:.1f}°C</b>.",
        "low_disk_firing": "💾 <b>ESPACE DISQUE CRITIQUE FAIBLE</b>\n\nEspace libre sur la racine: <b>{free:.0f} Mo</b> (&lt; 500 Mo)\nPensez à supprimer d'anciennes sauvegardes: <code>/backup list</code>",
        "low_disk_resolved": "✅ <b>ESPACE DISQUE RÉCUPÉRÉ</b>\n\nEspace disque libre: <b>{free:.0f} Mo</b>.",
        "wan_failover_firing": "🔀 <b>BASCULEMENT WAN (FAILOVER) ENGAGÉ</b>\n\nLien WAN principal (<code>{primary}</code>) défaillant.\nBasculé sur l'interface de secours: <code>{active}</code>.",
        "wan_failover_resolved": "✅ <b>LIEN WAN PRINCIPAL RESTAURÉ</b>\n\nTrafic réacheminé vers l'interface principale: <code>{primary}</code>.",
    },
    "uk": {
        "outage_start": "🚨 <b>ВИЯВЛЕНО КРИТИЧНИЙ ЗБІЙ МЕРЕЖІ</b>\n\nУсі тестові вузли недоступні.\nПричина: <i>{cause}</i>\nІдентифікатор: <code>{box_id}</code>",
        "outage_resolved": "✅ <b>ЗБІЙ МЕРЕЖІ ВИРІШЕНО</b>\n\nЗв'язок з Інтернетом відновлено.\nЗагальний час простою: <b>{dur}с</b>\nІдентифікатор: <code>{box_id}</code>",
        "packet_loss_firing": "⚠️ <b>ПОПЕРЕДЖЕННЯ: ВИСОКА ВТРАТА ПАКЕТІВ</b>\n\nВтрата пакетів: <b>{loss:.1f}%</b> (поріг: {threshold:.1f}%)\nПакети: {lost} втрачено / {sent} надіслано (за 5 хв)\nІдентифікатор: <code>{box_id}</code>",
        "packet_loss_resolved": "✅ <b>ВТРАТУ ПАКЕТІВ НОРМАЛІЗОВАНО</b>\n\nВтрата пакетів знизилася до <b>{loss:.1f}%</b>.",
        "service_failure_firing": "🚨 <b>ВИЯВЛЕНО ЗБІЙ СИСТЕМНОЇ СЛУЖБИ</b>\n\nСлужба(и), що зупинилися: {services}\nЗапуск автоматичного відновлення рівня 1...",
        "service_failure_resolved": "✅ <b>УСІ СИСТЕМНІ СЛУЖБИ ВІДНОВЛЕНО</b>\n\nУсі ключові демони активні та працездатні.",
        "overheat_firing": "🔥 <b>ПОПЕРЕДЖЕННЯ: ПЕРЕГРІВ ОБЛАДНАННЯ</b>\n\nТемпература SoC / CPU: <b>{temp:.1f}°C</b> (ліміт: 82°C)\nПеревірте охолодження або вентиляцію.",
        "overheat_resolved": "✅ <b>ТЕМПЕРАТУРУ НОРМАЛІЗОВАНО</b>\n\nТемпература процесора повернулася в безпечну норму: <b>{temp:.1f}°C</b>.",
        "low_disk_firing": "💾 <b>ПОПЕРЕДЖЕННЯ: ЗАКІНЧУЄТЬСЯ МІСЦЕ НА ДИСКУ</b>\n\nВільне місце на кореневому розділі: <b>{free:.0f} МБ</b> (&lt; 500 МБ)\nРекомендовано видалити старі бекапи: <code>/backup list</code>",
        "low_disk_resolved": "✅ <b>ВІЛЬНЕ МІСЦЕ ВІДНОВЛЕНО</b>\n\nВільний простір на диску: <b>{free:.0f} МБ</b>.",
        "wan_failover_firing": "🔀 <b>АКТИВОВАНО АВАРІЙНЕ ПЕРЕМИКАННЯ WAN</b>\n\nОсновний канал WAN (<code>{primary}</code>) недоступний.\nПереключено на резервний інтерфейс: <code>{active}</code>.",
        "wan_failover_resolved": "✅ <b>ОСНОВНИЙ КАНАЛ WAN ВІДНОВЛЕНО</b>\n\nТрафік знову спрямовано через основний інтерфейс: <code>{primary}</code>.",
    }
}


def format_alert(alert_key: str, lang: str = DEFAULT_LANGUAGE, **kwargs) -> str:
    """Format proactive alert message in the target language."""
    lang = lang if lang in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE
    templates = ALERT_TEMPLATES.get(lang, ALERT_TEMPLATES["en"])
    tmpl = templates.get(alert_key, ALERT_TEMPLATES["en"].get(alert_key, f"Alert: {alert_key}"))
    try:
        return tmpl.format(**kwargs)
    except Exception:
        log.debug("suppressed exception", exc_info=True)
        return tmpl
