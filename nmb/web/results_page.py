"""Read-only results page and the rules for showing it without the password.

With ``[web] public_results = true``, devices on the local network may open these
pages and downloads without logging in, so a person hosting the box can hand the
results to a specialist. Everything else, including every setting, still needs
the password, and requests from public addresses always do.
"""
from __future__ import annotations

import html
import ipaddress

# Read-only result pages and downloads; none of them shows settings or secrets.
PUBLIC_RESULT_PATHS = frozenset({
    "/results",
    "/dossier", "/dossier.html", "/report.html", "/export/report.html", "/api/export/dossier",
    "/export/csv", "/api/export/csv",
    "/export/speedtests.csv", "/export/speedtests", "/api/export/speedtests",
    "/export/speedtests_detailed.csv",
})

LANGS = ("en", "hu", "de", "fr", "uk")

TEXT = {
    "en": {
        "title": "Measurement results",
        "intro": "Download the results of this measurement box and send them to the specialist who asked for them.",
        "report": "Full report (HTML, last 24 hours)",
        "speed": "Speed tests (CSV)",
        "speed_detailed": "Speed tests with every detail (CSV)",
        "ping": "Ping summary (CSV, last 24 hours)",
        "note": "Read only. Changing settings needs the administrator password.",
    },
    "hu": {
        "title": "Mérési eredmények",
        "intro": "Töltsd le a mérőeszköz eredményeit, és küldd el annak a szakembernek, aki kérte.",
        "report": "Teljes riport (HTML, utolsó 24 óra)",
        "speed": "Sebességmérések (CSV)",
        "speed_detailed": "Sebességmérések minden részlettel (CSV)",
        "ping": "Ping-összesítő (CSV, utolsó 24 óra)",
        "note": "Csak olvasható. A beállítások módosításához rendszergazdai jelszó kell.",
    },
    "de": {
        "title": "Messergebnisse",
        "intro": "Laden Sie die Ergebnisse dieser Messbox herunter und senden Sie sie an die Fachperson, die sie angefordert hat.",
        "report": "Vollständiger Bericht (HTML, letzte 24 Stunden)",
        "speed": "Geschwindigkeitstests (CSV)",
        "speed_detailed": "Geschwindigkeitstests mit allen Details (CSV)",
        "ping": "Ping-Übersicht (CSV, letzte 24 Stunden)",
        "note": "Nur lesend. Für Änderungen an den Einstellungen ist das Administratorpasswort nötig.",
    },
    "fr": {
        "title": "Résultats de mesure",
        "intro": "Téléchargez les résultats de ce boîtier de mesure et envoyez-les au spécialiste qui les a demandés.",
        "report": "Rapport complet (HTML, dernières 24 heures)",
        "speed": "Tests de débit (CSV)",
        "speed_detailed": "Tests de débit avec tous les détails (CSV)",
        "ping": "Résumé des pings (CSV, dernières 24 heures)",
        "note": "Lecture seule. Modifier les réglages demande le mot de passe administrateur.",
    },
    "uk": {
        "title": "Результати вимірювань",
        "intro": "Завантажте результати цього вимірювального пристрою та надішліть їх фахівцеві, який їх попросив.",
        "report": "Повний звіт (HTML, останні 24 години)",
        "speed": "Тести швидкості (CSV)",
        "speed_detailed": "Тести швидкості з усіма подробицями (CSV)",
        "ping": "Підсумок ping (CSV, останні 24 години)",
        "note": "Лише перегляд. Для зміни налаштувань потрібен пароль адміністратора.",
    },
}


def is_local_client(ip: str) -> bool:
    """True for loopback and private (LAN, VPN) addresses, never for public ones."""
    try:
        addr = ipaddress.ip_address(ip.split("%", 1)[0])
    except ValueError:
        return False
    if getattr(addr, "ipv4_mapped", None):
        addr = addr.ipv4_mapped
    return addr.is_loopback or addr.is_private or addr.is_link_local


def allows_without_password(public_results: bool, method: str, path: str, client_ip: str) -> bool:
    """Whether this request may skip the login."""
    return (
        public_results
        and method in ("GET", "HEAD")
        and path in PUBLIC_RESULT_PATHS
        and is_local_client(client_ip)
    )


def render_results_page(lang: str, box_id: str = "") -> str:
    """The landing page with the download links, in the box's language."""
    lang = lang if lang in TEXT else "en"
    t = TEXT[lang]
    q = f"?lang={lang}"
    links = [
        (f"/dossier{q}", t["report"]),
        ("/export/speedtests.csv", t["speed"]),
        ("/export/speedtests_detailed.csv", t["speed_detailed"]),
        ("/export/csv", t["ping"]),
    ]
    items = "\n".join(f'      <li><a href="{href}" download>{html.escape(label)}</a></li>' for href, label in links)
    box = f" · {html.escape(box_id)}" if box_id else ""
    return f"""<!doctype html>
<html lang="{lang}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(t["title"])}</title>
  <style>
    body {{ font-family: system-ui, sans-serif; max-width: 640px; margin: 32px auto; padding: 0 16px; background: #0f172a; color: #e2e8f0; }}
    h1 {{ font-size: 1.4rem; }}
    a {{ color: #38bdf8; }}
    li {{ margin: 12px 0; font-size: 1.05rem; }}
    .note {{ color: #94a3b8; font-size: 0.9rem; margin-top: 24px; }}
  </style>
</head>
<body>
  <h1>{html.escape(t["title"])}{box}</h1>
  <p>{html.escape(t["intro"])}</p>
  <ul>
{items}
  </ul>
  <p class="note">{html.escape(t["note"])}</p>
</body>
</html>
"""
