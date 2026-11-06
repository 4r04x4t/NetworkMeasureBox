"""Standalone static HTML dossier generator with embedded SVG charts (zero CDNs).

Generates a single self-contained HTML file containing CSS, embedded SVG charts,
KPI summary cards, statistical characteristics, broadband quality metrics,
outage logs, and official regulatory / ISP fault escalation appendices.

Fully localized across 5 languages: hu, en, de, fr, uk.
Neutralized regulatory branding (adhering to EU BEREC & national broadband standards).
No misleading 0 Mb/s guaranteed/contracted thresholds when unconfigured.
"""
from __future__ import annotations

import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from nmb.db import database as db
from nmb.report.metrics import ReportData
from nmb.report.svg_charts import (
    render_compliance_chart,
    render_jitter_chart,
    render_latency_chart,
    render_loss_chart,
    render_speedtest_chart,
)

DOSSIER_I18N: Dict[str, Dict[str, Any]] = {
    "hu": {
        "doc_title": "Szélessávú Hálózati Minőség & Szolgáltatói SLA Vizsgálati Dosszié — {box_id}",
        "header_title": "Szélessávú Hálózati Minőség & Szolgáltatói SLA Vizsgálati Dosszié",
        "header_subtitle": "Helyhez kötött internet-hozzáférési szolgáltatás minőségi vizsgálati tanúsítványa és hibabejelentő dossziéja (EU BEREC és hírközlési mérési szabványok szerint)",
        "badge_probe": "MÉRŐPONT: {box_id}",
        "lbl_probe_name": "Mérőpont megnevezése:",
        "lbl_isp": "Szolgáltató (ISP):",
        "lbl_access_tech": "Hozzáférési technológia:",
        "lbl_subscriber_id": "Előfizetői azonosító:",
        "lbl_circuit_id": "Áramkör:",
        "lbl_eval_window": "Értékelési időablak:",
        "lbl_total_tests": "Összes rögzített mérés:",
        "lbl_gen_time": "Generálás időpontja:",
        "lbl_firmware": "Mérőfirmware:",
        "firmware_desc": "NetworkMeasureBox v2.5 (RFC 2681 / BEREC kompatibilis)",
        "lbl_guaranteed_down": "Garantált Letöltés",
        "lbl_contract_down": "Kínált (Névleges) Letöltés",
        "lbl_guaranteed_up": "Garantált Feltöltés",
        "lbl_contract_up": "Kínált (Névleges) Feltöltés",
        "unconfigured_speeds_notice": "A szerződés szerinti SLA sebességhatárok nincsenek konfigurálva. A mérések nyers vonali kapacitásként kerültek kiértékelésre.",
        "lbl_unspecified": "Nem meghatározott",
        "verdict_compliant_title": "SZERZŐDÉSSZERŰ MŰKÖDÉS",
        "verdict_compliant_desc": "Az SLA paraméterek és garantált határértékek teljesültek",
        "verdict_degraded_title": "SZOLGÁLTATÁSROMLÁS",
        "verdict_degraded_desc": "Teljesítmény-ingadozás vagy határérték-közeli paraméterek észlelve",
        "verdict_breached_title": "SZERZŐDÉSSZEGÉS / HIBAJEGY JAVASOLT",
        "verdict_breached_desc": "A garantált paraméterek tartósan nem teljesültek",
        "verdict_default_title": "HÁLÓZATI MINŐSÉGI TELEMETRIA",
        "verdict_default_desc": "Rögzített hálózati vizsgálati napló",
        "lbl_sla_compliance_rate": "SLA Teljesülési Arány:",
        "lbl_measurement_success_rate": "Mérési Sikerességi Arány:",
        "kpi_availability": "Hálózati Rendelkezésre Állás",
        "kpi_outage_sub": "{outages} kimaradás ({sec} mp kiesés)",
        "kpi_latency": "Átlagos Válaszidő (Ping RTT)",
        "kpi_latency_sub": "Medián: {med:.1f} ms | P95: {p95:.1f} ms",
        "kpi_loss": "Csomagvesztés Aránya",
        "kpi_loss_sub": "{lost:,} elveszett / {sent:,} elküldött csomag",
        "kpi_download": "Mért Átlagos Letöltés",
        "kpi_down_sub_guar": "Garantált teljesülése: {guar:.0f}% | Feltöltés: {up:.1f} Mb/s",
        "kpi_down_sub_off": "Kínált aránya: {off:.0f}% | Feltöltés: {up:.1f} Mb/s",
        "kpi_down_sub_peak": "Csúcssebesség: {peak:.1f} Mb/s | Feltöltés: {up:.1f} Mb/s",
        "sec1_title": "1. Sebességértékek Idősoros Lefutása",
        "sec1_sub": "Mért Letöltés & Feltöltés a szerződéses határértékekkel",
        "sec2_title": "2. Sebesség Mérési Eredmények Megfelelőségük Arányában",
        "sec2_sub": "A kínált sávszélesség %-ában (100% = szerződés szerinti kínált sebesség)",
        "sec_stats_title": "Mérési Pont Statisztikai Jellemzők (Összesítő Táblázat)",
        "sec_stats_sub": "Matematikai eloszlás, szórás és megbízhatósági mutatók",
        "th_parameter": "Paraméter",
        "th_average": "Átlag",
        "th_median": "Medián (50%)",
        "th_p95": "P95 Percentilis",
        "th_min": "Minimum",
        "th_max": "Maximum",
        "th_stddev": "Szórás (StdDev)",
        "param_down": "Letöltési Sebesség",
        "param_up": "Feltöltési Sebesség",
        "param_lat": "Válaszidő (Ping RTT)",
        "param_jitter": "Késleltetés-ingadozás (Jitter)",
        "param_loss": "Csomagvesztés Aránya",
        "sec3_title": "3. Válaszidő (Ping RTT) és Hálózati Kimaradások",
        "sec3_sub": "Másodperc alatti ICMP Echo mintavételezés a BIX és referencia csomópontok felé",
        "sec4_title": "4. Csomagvesztés Idősoros Megoszlása (%)",
        "sec4_sub": "Hálózati puffer-túlcsordulás és csomageldobás monitorozása",
        "sec5_title": "5. Késleltetés-ingadozás (Jitter ms)",
        "sec5_sub": "VoIP, streaming és valós idejű kommunikációs minőségi indikátor",
        "sec_outages_title": "Hálózati Kimaradások és Szakadás Napló (Outages)",
        "th_outage_start": "Kezdet Időpontja",
        "th_outage_end": "Helyreállás Időpontja",
        "th_outage_duration": "Kiesés Időtartama",
        "th_outage_cause": "Diagnosztikai Ok",
        "outage_ongoing": "FOLYAMATBAN",
        "outage_empty": "Ebben a mérési időablakban nem történt hálózati kimaradás (100% üzemidő).",
        "sec_speed_audit_title": "Részletes Sebességmérési Adatnapló",
        "sec_speed_audit_sub": "Nyilvános IP cím, észlelt ISP, letöltési/feltöltési arányok és státuszkódok",
        "th_date_time": "Dátum / Időpont",
        "th_client_ip_isp": "Kliens IP & Szolgáltató (ISP)",
        "th_down": "Letöltés",
        "th_up": "Feltöltés",
        "th_lat": "Válaszidő",
        "th_bb": "Bufferbloat",
        "th_engine_srv": "Mérőmotor & Szerver",
        "th_status": "Státusz",
        "th_link": "Mérési Link",
        "speed_empty": "Nem rögzített sebességmérést az eszköz ebben az időszakban.",
        "status_box_title": "A „Státusz” oszlopban megjelenő diagnosztikai kódok hivatalos magyarázata:",
        "status_codes_text": (
            "<b>1</b> – érvényes mérés | "
            "<b>2</b> – érvénytelenített mérés (kódhiba) | "
            "<b>3</b> – érvénytelenített mérés (eszközhiba) | "
            "<b>4</b> – érvénytelenített mérés (hibás adatok) | "
            "<b>5</b> – hibás mérés (az érzékelt IP-cím nem tartozhat a felhasználó által definiált szolgáltatáshoz) | "
            "<b style='color: #ef4444;'>6 – hibás mérés (túl nagy az eltérés az elvárható sávszélességértéktől / SLA alatt)</b> | "
            "<b>7</b> – hibás mérés (időtúllépés) | "
            "<b>8</b> – hibás mérés (törölt kód) | "
            "<b>9</b> – forgalmi korlát túllépése (egyidejű háttérforgalom meghaladta a küszöböt) | "
            "<b>10</b> – nem volt végrehajtható feladat | "
            "<b>11</b> – feladatindítás | "
            "<b>12</b> – hiba (error) | "
            "<b>13</b> – hibás bekötés (nem az előírtak szerint bekötött mérőeszköz) | "
            "<b>14</b> – WiFi mérés (vezeték nélküli hozzáférésen végzett mérés) | "
            "<b>15</b> – WiFi mérés - False IP (nem hitelesített szolgáltatói IP)"
        ),
        "sec_targets_title": "Referencia Csomópontok Késleltetési Bontása",
        "th_target_ep": "Célcsomópont",
        "th_target_sent": "Elküldött",
        "th_target_lost": "Elveszett",
        "th_target_loss_rate": "Vesztési Arány",
        "th_target_avg_rtt": "Átlagos RTT",
        "th_target_p95_rtt": "P95 RTT",
        "sec_port_title": "Netsemlegességi & Forgalomkorlátozási (Traffic-Shaping) Audit",
        "sec_port_sub_ok": "{count} korlátozott/blokkolt protokoll vagy port észlelve",
        "th_port_proto": "Port & Protokoll",
        "th_port_ep": "Referencia Végpont",
        "th_port_speed": "Elérhető Átviteli Sebesség",
        "th_port_ratio": "Arány a 443-as Alapértékhez",
        "th_port_verdict": "Forgalmi Minősítés",
        "port_empty": "Nincs rögzített netsemlegességi portellenőrzés.",
        "legal_appendix_title": "Hivatalos Szolgáltatói Hibabejelentő és Hatósági Jogszabályi Záradék:",
        "legal_appendix_body": (
            "Ez a dokumentum a helyszínen üzemelő NetworkMeasureBox autonóm hálózati mérőhardver által függetlenül rögzített telemetriai adatokat tartalmazza. "
            "A mérések az elektronikus hírközlésről szóló <b>2003. évi C. törvény (Eht.)</b>, a <b>13/2011. (XII. 27.) NMHH rendelet</b>, "
            "valamint az Európai Unió <b>2015/2120 rendelete (BEREC nyílt internet iránymutatások)</b> előírásainak figyelembevételével készültek. "
            "A sebességmérések kizárólag alacsony helyi háttérforgalom mellett futnak le a vezetékes LAN-torzítások kizárása érdekében. "
            "Amennyiben a mért letöltési vagy feltöltési sebesség nem éri el a szerződésben rögzített garantált minimumot, vagy a szolgáltatáskimaradások mértéke meghaladja a megengedett határértéket, "
            "az előfizető jogosult hivatalos szolgáltatói hibajegyet nyitni, kötbérre igényt tartani, vagy az illetékes hírközlési hatóságnál piacfelügyeleti eljárást kezdeményezni."
        ),
        "link_open": "Megnyitás",
        "unit_sec": "mp",
    },
    "en": {
        "doc_title": "Broadband Quality & ISP SLA Performance Dossier — {box_id}",
        "header_title": "Broadband Quality & ISP SLA Performance Dossier",
        "header_subtitle": "Fixed broadband Internet access quality audit & SLA fault escalation dossier (aligned with EU BEREC & national regulatory standards)",
        "badge_probe": "PROBE: {box_id}",
        "lbl_probe_name": "Measurement Probe:",
        "lbl_isp": "Internet Provider (ISP):",
        "lbl_access_tech": "Access Technology:",
        "lbl_subscriber_id": "Subscriber Account ID:",
        "lbl_circuit_id": "Circuit ID:",
        "lbl_eval_window": "Evaluation Window:",
        "lbl_total_tests": "Total Recorded Tests:",
        "lbl_gen_time": "Generated At:",
        "lbl_firmware": "Measurement Firmware:",
        "firmware_desc": "NetworkMeasureBox v2.5 (RFC 2681 / BEREC compliant)",
        "lbl_guaranteed_down": "Guaranteed Download",
        "lbl_contract_down": "Advertised (Offered) Download",
        "lbl_guaranteed_up": "Guaranteed Upload",
        "lbl_contract_up": "Advertised (Offered) Upload",
        "unconfigured_speeds_notice": "Contracted SLA speed thresholds are not configured. Performance was evaluated based on measured line throughput.",
        "lbl_unspecified": "Unspecified",
        "verdict_compliant_title": "SLA COMPLIANT",
        "verdict_compliant_desc": "Service metrics meet or exceed defined contract thresholds",
        "verdict_degraded_title": "SERVICE DEGRADED",
        "verdict_degraded_desc": "Performance fluctuations or near-threshold degradation detected",
        "verdict_breached_title": "SLA BREACHED / ESCALATION RECOMMENDED",
        "verdict_breached_desc": "Guaranteed service thresholds persistently violated",
        "verdict_default_title": "NETWORK QUALITY TELEMETRY",
        "verdict_default_desc": "Independent diagnostic benchmark dossier",
        "lbl_sla_compliance_rate": "SLA Compliance Rate:",
        "lbl_measurement_success_rate": "Measurement Success Rate:",
        "kpi_availability": "Network Availability (Uptime)",
        "kpi_outage_sub": "{outages} outages ({sec}s downtime)",
        "kpi_latency": "Average Latency (Ping RTT)",
        "kpi_latency_sub": "Median: {med:.1f} ms | P95: {p95:.1f} ms",
        "kpi_loss": "Packet Loss Rate",
        "kpi_loss_sub": "{lost:,} lost / {sent:,} transmitted packets",
        "kpi_download": "Average Download Throughput",
        "kpi_down_sub_guar": "Guaranteed fulfilled: {guar:.0f}% | Upload: {up:.1f} Mb/s",
        "kpi_down_sub_off": "Offered fulfilled: {off:.0f}% | Upload: {up:.1f} Mb/s",
        "kpi_down_sub_peak": "Peak Throughput: {peak:.1f} Mb/s | Upload: {up:.1f} Mb/s",
        "sec1_title": "1. Speed & Bandwidth Timeline",
        "sec1_sub": "Measured Download & Upload with contract reference limits",
        "sec2_title": "2. Speed Measurement Compliance Ratio",
        "sec2_sub": "As % of contracted bandwidth (100% = advertised speed)",
        "sec_stats_title": "Probe Statistical Characteristics Summary Table",
        "sec_stats_sub": "Mathematical distribution, percentiles, dispersion, and confidence metrics",
        "th_parameter": "Parameter",
        "th_average": "Average",
        "th_median": "Median (50%)",
        "th_p95": "P95 Percentile",
        "th_min": "Minimum",
        "th_max": "Maximum",
        "th_stddev": "StdDev",
        "param_down": "Download Throughput",
        "param_up": "Upload Throughput",
        "param_lat": "Latency (Ping RTT)",
        "param_jitter": "Jitter Variation",
        "param_loss": "Packet Loss Rate",
        "sec3_title": "3. Round-Trip Latency (Ping RTT) & Outages",
        "sec3_sub": "Sub-second ICMP Echo telemetry towards Internet exchanges & reference nodes",
        "sec4_title": "4. Packet Loss Timeline (%)",
        "sec4_sub": "Buffer overrun and network packet drop monitoring",
        "sec5_title": "5. Latency Jitter (ms)",
        "sec5_sub": "VoIP, interactive gaming, and real-time streaming quality indicator",
        "sec_outages_title": "Network Outages & Disconnection Log",
        "th_outage_start": "Start Time",
        "th_outage_end": "Restoration Time",
        "th_outage_duration": "Duration",
        "th_outage_cause": "Diagnostic Cause",
        "outage_ongoing": "ONGOING",
        "outage_empty": "No network outages occurred in this observation window (100% uptime).",
        "sec_speed_audit_title": "Detailed Speedtest Audit Log",
        "sec_speed_audit_sub": "Public IP, detected ISP, download/upload throughput and diagnostic status codes",
        "th_date_time": "Date / Time",
        "th_client_ip_isp": "Client IP & Provider (ISP)",
        "th_down": "Download",
        "th_up": "Upload",
        "th_lat": "Latency",
        "th_bb": "Bufferbloat",
        "th_engine_srv": "Engine & Server",
        "th_status": "Status",
        "th_link": "Audit Link",
        "speed_empty": "No speed tests recorded during this observation window.",
        "status_box_title": "Regulatory & Benchmark Status Codes (1–15) Explanation:",
        "status_codes_text": (
            "<b>1</b> – Valid measurement | "
            "<b>2</b> – Invalidated (internal code error) | "
            "<b>3</b> – Invalidated (device/hardware error) | "
            "<b>4</b> – Invalidated (corrupt data) | "
            "<b>5</b> – ISP mismatch (observed client IP does not match declared provider) | "
            "<b style='color: #ef4444;'>6 – Performance breach (excessive deviation from agreed contract bandwidth / below SLA)</b> | "
            "<b>7</b> – Measurement timeout | "
            "<b>8</b> – Cancelled test | "
            "<b>9</b> – Traffic quota exceeded (background LAN traffic exceeded threshold during test) | "
            "<b>10</b> – No runnable task | "
            "<b>11</b> – Task initiated | "
            "<b>12</b> – Error | "
            "<b>13</b> – Cabling fault (device not connected according to wired specifications) | "
            "<b>14</b> – Wireless measurement (test performed via Wi-Fi) | "
            "<b>15</b> – Wireless measurement - unverified IP"
        ),
        "sec_targets_title": "Reference Endpoint Latency & Loss Breakdown",
        "th_target_ep": "Target Endpoint",
        "th_target_sent": "Transmitted",
        "th_target_lost": "Lost",
        "th_target_loss_rate": "Loss Rate",
        "th_target_avg_rtt": "Avg RTT",
        "th_target_p95_rtt": "P95 RTT",
        "sec_port_title": "Net-Neutrality & Traffic-Shaping / Throttling Audit",
        "sec_port_sub_ok": "{count} throttled/blocked protocols or ports detected",
        "th_port_proto": "Port & Protocol",
        "th_port_ep": "Reference Endpoint",
        "th_port_speed": "Measured Throughput",
        "th_port_ratio": "Ratio vs Port 443",
        "th_port_verdict": "Traffic Verdict",
        "port_empty": "No net-neutrality port audit tests recorded.",
        "legal_appendix_title": "Official Regulatory & Service Provider Dispute Escalation Notice:",
        "legal_appendix_body": (
            "This document presents independent network telemetry recorded autonomously by an on-premises NetworkMeasureBox hardware probe. "
            "Measurements adhere to the core principles of <b>EU Regulation 2015/2120 (Open Internet Regulation)</b>, "
            "<b>BEREC Guidelines on Net Neutrality & QoS Measurement (BoR (20) 165)</b>, and <b>IETF RFC 2681</b>. "
            "Throughput audits execute strictly under verified low background LAN traffic to eliminate local bottleneck distortions. "
            "Should measured throughput persistently fail to achieve contracted minimum guaranteed speeds, or should outage frequencies exceed regulatory tolerances, "
            "the subscriber is entitled to raise a formal dispute with the Internet Service Provider, claim contractual compensation, or escalate the case to the competent national regulatory authority."
        ),
        "link_open": "Open",
        "unit_sec": "s",
    },
    "de": {
        "doc_title": "Breitband-Qualitäts- & ISP-SLA-Leistungsdossier — {box_id}",
        "header_title": "Breitband-Qualitäts- & ISP-SLA-Leistungsdossier",
        "header_subtitle": "Prüfzertifikat und SLA-Fehlereskalationsdossier für feste Breitband-Internetzugangsdienste (gemäß EU-BEREC- und Regulierungsstandards)",
        "badge_probe": "MESSPUNKT: {box_id}",
        "lbl_probe_name": "Messpunkt-Bezeichnung:",
        "lbl_isp": "Internetanbieter (ISP):",
        "lbl_access_tech": "Zugangstechnologie:",
        "lbl_subscriber_id": "Kundenkennung:",
        "lbl_circuit_id": "Leitungs-ID:",
        "lbl_eval_window": "Auswertungszeitraum:",
        "lbl_total_tests": "Gesamte Messungen:",
        "lbl_gen_time": "Erstellungszeitpunkt:",
        "lbl_firmware": "Mess-Firmware:",
        "firmware_desc": "NetworkMeasureBox v2.5 (RFC 2681 / BEREC-konform)",
        "lbl_guaranteed_down": "Garantierter Download",
        "lbl_contract_down": "Vertraglicher Download",
        "lbl_guaranteed_up": "Garantierter Upload",
        "lbl_contract_up": "Vertraglicher Upload",
        "unconfigured_speeds_notice": "Vertragliche SLA-Geschwindigkeitsschwellen sind nicht konfiguriert. Die Auswertung erfolgte anhand des gemessenen Leitungsdurchsatzes.",
        "lbl_unspecified": "Nicht angegeben",
        "verdict_compliant_title": "VERTRAGSKONFORM",
        "verdict_compliant_desc": "SLA-Parameter und garantierte Schwellenwerte wurden eingehalten",
        "verdict_degraded_title": "LEISTUNGSEINBUSSEN",
        "verdict_degraded_desc": "Leistungsschwankungen oder grenzwertige Parameter festgestellt",
        "verdict_breached_title": "VERTRAGSVERLETZUNG / ESKALATION EMPFOHLEN",
        "verdict_breached_desc": "Garantierte Schwellenwerte anhaltend unterschritten",
        "verdict_default_title": "NETZWERKQUALITÄTS-TELEMETRIE",
        "verdict_default_desc": "Unabhängiges diagnostisches Prüfdossier",
        "lbl_sla_compliance_rate": "SLA-Erfüllungsrate:",
        "lbl_measurement_success_rate": "Mess-Erfolgsquote:",
        "kpi_availability": "Netzwerkverfügbarkeit",
        "kpi_outage_sub": "{outages} Ausfälle ({sec}s Ausfallzeit)",
        "kpi_latency": "Durchschnittliche Latenz (RTT)",
        "kpi_latency_sub": "Median: {med:.1f} ms | P95: {p95:.1f} ms",
        "kpi_loss": "Paketverlustrate",
        "kpi_loss_sub": "{lost:,} verloren / {sent:,} gesendete Pakete",
        "kpi_download": "Durchschnittlicher Download",
        "kpi_down_sub_guar": "Garantiert erfüllt: {guar:.0f}% | Upload: {up:.1f} Mb/s",
        "kpi_down_sub_off": "Vertraglich erfüllt: {off:.0f}% | Upload: {up:.1f} Mb/s",
        "kpi_down_sub_peak": "Spitzendurchsatz: {peak:.1f} Mb/s | Upload: {up:.1f} Mb/s",
        "sec1_title": "1. Geschwindigkeits- und Bandbreitenverlauf",
        "sec1_sub": "Gemessener Download & Upload mit vertraglichen Referenzlinien",
        "sec2_title": "2. Konformitätsrate der Geschwindigkeitsmessungen",
        "sec2_sub": "In % der vertraglichen Bandbreite (100% = vereinbarte Rate)",
        "sec_stats_title": "Statistische Kenndaten des Messpunkts (Übersichtstabelle)",
        "sec_stats_sub": "Mathematische Verteilung, Perzentile, Streuung und Konfidenzmetriken",
        "th_parameter": "Parameter",
        "th_average": "Durchschnitt",
        "th_median": "Median (50%)",
        "th_p95": "95. Perzentil",
        "th_min": "Minimum",
        "th_max": "Maximum",
        "th_stddev": "StdAbw",
        "param_down": "Download-Rate",
        "param_up": "Upload-Rate",
        "param_lat": "Latenz (Ping RTT)",
        "param_jitter": "Latenzschwankung (Jitter)",
        "param_loss": "Paketverlustrate",
        "sec3_title": "3. Round-Trip-Latenz (Ping RTT) & Ausfälle",
        "sec3_sub": "Sekundengenaue ICMP-Echo-Telemetrie zu Internetknoten und Referenzpunkten",
        "sec4_title": "4. Paketverlust-Verlauf (%)",
        "sec4_sub": "Überwachung von Pufferüberläufen und Paketverlusten",
        "sec5_title": "5. Latenz-Jitter (ms)",
        "sec5_sub": "Qualitätsindikator für VoIP, Echtzeit-Streaming und Online-Dienste",
        "sec_outages_title": "Netzwerkausfall- und Trennungsprotokoll",
        "th_outage_start": "Beginn",
        "th_outage_end": "Ende",
        "th_outage_duration": "Ausfalldauer",
        "th_outage_cause": "Diagnoseursache",
        "outage_ongoing": "LAUFEND",
        "outage_empty": "In diesem Zeitraum traten keine Netzwerkausfälle auf (100% Verfügbarkeit).",
        "sec_speed_audit_title": "Detailliertes Geschwindigkeits-Audit-Protokoll",
        "sec_speed_audit_sub": "Öffentliche IP, erkannter ISP, Durchsatz und Diagnosestatuscodes",
        "th_date_time": "Datum & Uhrzeit",
        "th_client_ip_isp": "Client-IP & ISP",
        "th_down": "Download",
        "th_up": "Upload",
        "th_lat": "Latenz",
        "th_bb": "Bufferbloat",
        "th_engine_srv": "Mess-Engine & Server",
        "th_status": "Status",
        "th_link": "Messlink",
        "speed_empty": "In diesem Zeitraum wurden keine Geschwindigkeitstests aufgezeichnet.",
        "status_box_title": "Erklärung der Diagnosestatuscodes (1–15):",
        "status_codes_text": (
            "<b>1</b> – Gültige Messung | "
            "<b>2</b> – Ungültig (Code-Fehler) | "
            "<b>3</b> – Ungültig (Geräte-/Hardwarefehler) | "
            "<b>4</b> – Ungültig (fehlerhafte Daten) | "
            "<b>5</b> – Falscher Anbieter (IP stimmt nicht mit dem konfigurierten ISP überein) | "
            "<b style='color: #ef4444;'>6 – Leistungsabweichung (übermäßige Abweichung von der vereinbarten Rate / unter SLA)</b> | "
            "<b>7</b> – Zeitüberschreitung (Timeout) | "
            "<b>8</b> – Gelöschte Messung | "
            "<b>9</b> – Datenverkehrslimit überschritten (hoher Hintergrundverkehr während der Messung) | "
            "<b>10</b> – Keine ausführbare Aufgabe | "
            "<b>11</b> – Aufgabenstart | "
            "<b>12</b> – Fehler (Error) | "
            "<b>13</b> – Verkabelungsfehler (Gerät nicht vorschriftsmäßig angeschlossen) | "
            "<b>14</b> – WLAN-Messung (über drahtlosen Zugang durchgeführt) | "
            "<b>15</b> – WLAN-Messung - nicht verifizierte IP"
        ),
        "sec_targets_title": "Latenz- und Verlustanalyse der Referenzknoten",
        "th_target_ep": "Zielknoten",
        "th_target_sent": "Gesendet",
        "th_target_lost": "Verloren",
        "th_target_loss_rate": "Verlustrate",
        "th_target_avg_rtt": "Durchschn. RTT",
        "th_target_p95_rtt": "P95 RTT",
        "sec_port_title": "Netzneutralitäts- & Traffic-Shaping-Audit",
        "sec_port_sub_ok": "{count} gedrosselte oder blockierte Protokolle/Ports erkannt",
        "th_port_proto": "Port & Protokoll",
        "th_port_ep": "Referenz-Endpunkt",
        "th_port_speed": "Durchsatz",
        "th_port_ratio": "Verhältnis zu Port 443",
        "th_port_verdict": "Bewertung",
        "port_empty": "Keine Netzneutralitäts-Porttests aufgezeichnet.",
        "legal_appendix_title": "Offizielle regulatorische und vertragliche Schlichtungsklausel:",
        "legal_appendix_body": (
            "Dieses Dokument enthält unabhängige Netzwerktelemetriedaten, die von einer autonomen NetworkMeasureBox-Hardware vor Ort erfasst wurden. "
            "Die Prüfungen entsprechen den Vorgaben der <b>EU-Verordnung 2015/2120 (Open-Internet-Verordnung)</b>, "
            "den <b>BEREC-Leitlinien zur Messung der Dienstqualität (BoR (20) 165)</b> sowie <b>IETF RFC 2681</b>. "
            "Bandbreitenprüfungen erfolgen ausschließlich bei verifiziert geringem lokalen Hintergrundverkehr, um Verzerrungen auszuschließen. "
            "Sollten gemessene Werte wiederholt die vertraglich garantierte Mindestbandbreite unterschreiten oder Ausfallzeiten zulässige Grenzen übersteigen, "
            "ist der Kunde berechtigt, ein formelles Störungsticket zu eröffnen, Entschädigungsansprüche geltend zu machen oder die nationale Regulierungsbehörde einzuschalten."
        ),
        "link_open": "Öffnen",
        "unit_sec": "s",
    },
    "fr": {
        "doc_title": "Dossier de Qualité du Haut Débit & Performance SLA FAI — {box_id}",
        "header_title": "Dossier de Qualité du Haut Débit & Performance SLA FAI",
        "header_subtitle": "Certificat d'évaluation de la qualité de l'accès Internet fixe et dossier de réclamation FAI (conforme aux normes BEREC UE)",
        "badge_probe": "POINT DE MESURE: {box_id}",
        "lbl_probe_name": "Point de mesure:",
        "lbl_isp": "Fournisseur d'accès (FAI):",
        "lbl_access_tech": "Technologie d'accès:",
        "lbl_subscriber_id": "Identifiant abonné:",
        "lbl_circuit_id": "Circuit:",
        "lbl_eval_window": "Période d'évaluation:",
        "lbl_total_tests": "Total des mesures:",
        "lbl_gen_time": "Date de génération:",
        "lbl_firmware": "Firmware de mesure:",
        "firmware_desc": "NetworkMeasureBox v2.5 (conforme RFC 2681 / BEREC)",
        "lbl_guaranteed_down": "Téléchargement garanti",
        "lbl_contract_down": "Téléchargement annoncé",
        "lbl_guaranteed_up": "Téléversement garanti",
        "lbl_contract_up": "Téléversement annoncé",
        "unconfigured_speeds_notice": "Les seuils de vitesse SLA contractuels ne sont pas configurés. L'évaluation est basée sur le débit mesuré de la ligne.",
        "lbl_unspecified": "Non spécifié",
        "verdict_compliant_title": "CONFORME SLA",
        "verdict_compliant_desc": "Les métriques de service respectent ou dépassent les seuils contractuels",
        "verdict_degraded_title": "SERVICE DÉGRADÉ",
        "verdict_degraded_desc": "Fluctuations de performance ou dégradation proche des limites détectées",
        "verdict_breached_title": "VIOLATION DU SLA / RÉCLAMATION RECOMMANDÉE",
        "verdict_breached_desc": "Les seuils minimaux garantis ne sont pas respectés",
        "verdict_default_title": "TÉLÉMÉTRIE QUALITÉ RÉSEAU",
        "verdict_default_desc": "Dossier indépendant de diagnostic et mesure",
        "lbl_sla_compliance_rate": "Taux de conformité SLA:",
        "lbl_measurement_success_rate": "Taux de réussite des mesures:",
        "kpi_availability": "Disponibilité du réseau",
        "kpi_outage_sub": "{outages} coupures ({sec}s d'arrêt)",
        "kpi_latency": "Latence moyenne (Ping RTT)",
        "kpi_latency_sub": "Médiane: {med:.1f} ms | P95: {p95:.1f} ms",
        "kpi_loss": "Taux de perte de paquets",
        "kpi_loss_sub": "{lost:,} perdus / {sent:,} paquets envoyés",
        "kpi_download": "Débit moyen descendant",
        "kpi_down_sub_guar": "Garanti atteint: {guar:.0f}% | Envoi: {up:.1f} Mb/s",
        "kpi_down_sub_off": "Offre atteinte: {off:.0f}% | Envoi: {up:.1f} Mb/s",
        "kpi_down_sub_peak": "Débit de pointe: {peak:.1f} Mb/s | Envoi: {up:.1f} Mb/s",
        "sec1_title": "1. Évolution du Débit et de la Bande Passante",
        "sec1_sub": "Téléchargement & Téléversement mesurés avec seuils contractuels",
        "sec2_title": "2. Ratio de Conformité des Mesures de Débit",
        "sec2_sub": "En % de la bande passante contractuelle (100% = vitesse annoncée)",
        "sec_stats_title": "Caractéristiques Statistiques du Point de Mesure (Tableau Récapitulatif)",
        "sec_stats_sub": "Distribution mathématique, percentiles, dispersion et indicateurs de confiance",
        "th_parameter": "Paramètre",
        "th_average": "Moyenne",
        "th_median": "Médiane (50%)",
        "th_p95": "95e percentile",
        "th_min": "Minimum",
        "th_max": "Maximum",
        "th_stddev": "Écart-type",
        "param_down": "Vitesse de téléchargement",
        "param_up": "Vitesse de téléversement",
        "param_lat": "Latence (Ping RTT)",
        "param_jitter": "Gigue de latence",
        "param_loss": "Taux de perte de paquets",
        "sec3_title": "3. Temps d'aller-retour (Ping RTT) & Coupures",
        "sec3_sub": "Télémétrie ICMP sub-seconde vers les points d'échange Internet et serveurs de référence",
        "sec4_title": "4. Évolution de la Perte de Paquets (%)",
        "sec4_sub": "Surveillance des débordements de tampon et paquets rejetés",
        "sec5_title": "5. Gigue de Latence (ms)",
        "sec5_sub": "Indicateur de qualité pour VoIP, jeux en ligne et streaming en direct",
        "sec_outages_title": "Journal des Coupures et Interruptions Réseau",
        "th_outage_start": "Début",
        "th_outage_end": "Fin",
        "th_outage_duration": "Durée",
        "th_outage_cause": "Cause du diagnostic",
        "outage_ongoing": "EN COURS",
        "outage_empty": "Aucune coupure de réseau enregistrée pendant cette période (100% de disponibilité).",
        "sec_speed_audit_title": "Journal Détaillé d'Audit des Débits",
        "sec_speed_audit_sub": "IP publique, FAI détecté, débits et codes de diagnostic",
        "th_date_time": "Date & Heure",
        "th_client_ip_isp": "IP Client & FAI",
        "th_down": "Téléchargement",
        "th_up": "Téléversement",
        "th_lat": "Latence",
        "th_bb": "Bufferbloat",
        "th_engine_srv": "Moteur & Serveur",
        "th_status": "État",
        "th_link": "Lien de mesure",
        "speed_empty": "Aucun test de débit enregistré pendant cette période d'observation.",
        "status_box_title": "Explication des codes d'état de diagnostic (1–15):",
        "status_codes_text": (
            "<b>1</b> – Mesure valide | "
            "<b>2</b> – Invalidée (erreur interne) | "
            "<b>3</b> – Invalidée (erreur matériel/périphérique) | "
            "<b>4</b> – Invalidée (données corrompues) | "
            "<b>5</b> – FAI non concordant (l'IP observée ne correspond pas au FAI défini) | "
            "<b style='color: #ef4444;'>6 – Dégradation de performance (écart excessif par rapport au débit convenu / sous SLA)</b> | "
            "<b>7</b> – Délai dépassé (timeout) | "
            "<b>8</b> – Mesure supprimée | "
            "<b>9</b> – Limite de trafic dépassée (trafic d'arrière-plan élevé pendant le test) | "
            "<b>10</b> – Aucune tâche exécutable | "
            "<b>11</b> – Tâche initiée | "
            "<b>12</b> – Erreur (error) | "
            "<b>13</b> – Mauvais câblage (périphérique non raccordé selon les spécifications) | "
            "<b>14</b> – Mesure sans fil (test effectué via Wi-Fi) | "
            "<b>15</b> – Mesure sans fil - IP non vérifiée"
        ),
        "sec_targets_title": "Ventilation de Latence & Perte des Nœuds de Référence",
        "th_target_ep": "Point de référence",
        "th_target_sent": "Envoyés",
        "th_target_lost": "Perdus",
        "th_target_loss_rate": "Taux de perte",
        "th_target_avg_rtt": "RTT moyen",
        "th_target_p95_rtt": "P95 RTT",
        "sec_port_title": "Audit de Neutralité du Net & de Gestion du Trafic",
        "sec_port_sub_ok": "{count} protocoles ou ports bridés/bloqués détectés",
        "th_port_proto": "Port & Protocole",
        "th_port_ep": "Point de référence",
        "th_port_speed": "Débit mesuré",
        "th_port_ratio": "Ratio par rapport au port 443",
        "th_port_verdict": "Verdict",
        "port_empty": "Aucun audit de neutralité du net enregistré.",
        "legal_appendix_title": "Clause légale et procédure d'escalade auprès du régulateur et FAI:",
        "legal_appendix_body": (
            "Ce document présente les données de télémétrie réseau enregistrées de manière autonome par une sonde matérielle NetworkMeasureBox sur site. "
            "Les mesures sont conformes aux dispositions du <b>Règlement européen 2015/2120 (Règlement sur l'Internet ouvert)</b>, "
            "aux <b>Lignes directrices du BEREC sur la qualité de service (BoR (20) 165)</b> et à la norme <b>IETF RFC 2681</b>. "
            "Les tests de débit sont exécutés sous contrôle strict du trafic réseau local d'arrière-plan pour éviter toute distorsion. "
            "En cas de non-respect persistant des vitesses minimales garanties ou en cas d'interruptions dépassant les tolérances, "
            "l'abonné est en droit d'ouvrir une réclamation officielle auprès du fournisseur d'accès, de demander des indemnités ou de saisir l'autorité nationale de régulation."
        ),
        "link_open": "Ouvrir",
        "unit_sec": "s",
    },
    "uk": {
        "doc_title": "Досьє Якості Широкосмугового Доступу та SLA Провайдера — {box_id}",
        "header_title": "Досьє Якості Широкосмугового Доступу та SLA Провайдера",
        "header_subtitle": "Сертифікат аудиту якості фіксованого широкосмугового доступу та досьє ескалації SLA провайдера (за стандартами BEREC ЄС)",
        "badge_probe": "ТОЧКА ВИМІРЮВАННЯ: {box_id}",
        "lbl_probe_name": "Назва точки вимірювання:",
        "lbl_isp": "Інтернет-провайдер (ISP):",
        "lbl_access_tech": "Технологія доступу:",
        "lbl_subscriber_id": "ID абонента:",
        "lbl_circuit_id": "Лінія/канал:",
        "lbl_eval_window": "Період оцінки:",
        "lbl_total_tests": "Всього записано тестів:",
        "lbl_gen_time": "Час створення:",
        "lbl_firmware": "Прошивка вимірювача:",
        "firmware_desc": "NetworkMeasureBox v2.5 (сумісна з RFC 2681 / BEREC)",
        "lbl_guaranteed_down": "Гарантоване завантаження",
        "lbl_contract_down": "Оголошене завантаження",
        "lbl_guaranteed_up": "Гарантоване вивантаження",
        "lbl_contract_up": "Оголошене вивантаження",
        "unconfigured_speeds_notice": "Договірні порогові значення швидкості SLA не налаштовано. Оцінка проведена за фактичною пропускною здатністю лінії.",
        "lbl_unspecified": "Не вказано",
        "verdict_compliant_title": "ВІДПОВІДАЄ SLA",
        "verdict_compliant_desc": "Параметри якості послуги відповідають або перевищують договірні норми",
        "verdict_degraded_title": "ПОГІРШЕННЯ ПОСЛУГИ",
        "verdict_degraded_desc": "Виявлено коливання швидкості або погіршення параметрів біля меж норми",
        "verdict_breached_title": "ПОРУШЕННЯ SLA / РЕКОМЕНДОВАНО СКАРГУ",
        "verdict_breached_desc": "Гарантовані показники стабільно не виконуються",
        "verdict_default_title": "ТЕЛЕМЕТРІЯ ЯКОСТІ МЕРЕЖІ",
        "verdict_default_desc": "Незалежне діагностичне досьє вимірювань",
        "lbl_sla_compliance_rate": "Рівень відповідності SLA:",
        "lbl_measurement_success_rate": "Успішність вимірювань:",
        "kpi_availability": "Доступність мережі (Uptime)",
        "kpi_outage_sub": "{outages} перерв ({sec}с простою)",
        "kpi_latency": "Середня затримка (Ping RTT)",
        "kpi_latency_sub": "Медіана: {med:.1f} мс | P95: {p95:.1f} мс",
        "kpi_loss": "Рівень втрати пакетів",
        "kpi_loss_sub": "{lost:,} втрачено / {sent:,} передано пакетів",
        "kpi_download": "Середнє завантаження",
        "kpi_down_sub_guar": "Виконання гарантії: {guar:.0f}% | Вивантаження: {up:.1f} Мб/с",
        "kpi_down_sub_off": "Виконання оголошеного: {off:.0f}% | Вивантаження: {up:.1f} Мб/с",
        "kpi_down_sub_peak": "Пікове значення: {peak:.1f} Мб/с | Вивантаження: {up:.1f} Мб/с",
        "sec1_title": "1. Графік Швидкості та Пропускної Здатності",
        "sec1_sub": "Виміряне завантаження і вивантаження з договірними пороговими лініями",
        "sec2_title": "2. Відсоток Відповідності Результатів Вимірювань",
        "sec2_sub": "У % від оголошеної смуги пропускання (100% = договірна швидкість)",
        "sec_stats_title": "Статистичні Характеристики Точки Вимірювання (Зведена Таблиця)",
        "sec_stats_sub": "Математичний розподіл, процентилі, відхилення та показники надійності",
        "th_parameter": "Параметр",
        "th_average": "Середнє",
        "th_median": "Медіана (50%)",
        "th_p95": "95-й процентиль",
        "th_min": "Мінімум",
        "th_max": "Максимум",
        "th_stddev": "Станд. відхилення",
        "param_down": "Швидкість завантаження",
        "param_up": "Швидкість вивантаження",
        "param_lat": "Затримка (Ping RTT)",
        "param_jitter": "Коливання затримки (Джитер)",
        "param_loss": "Рівень втрати пакетів",
        "sec3_title": "3. Час затримки (Ping RTT) та Перерви",
        "sec3_sub": "Субсекундна телеметрія ICMP Echo до точок обміну трафіком та опорних вузлів",
        "sec4_title": "4. Графік Втрати Пакетів (%)",
        "sec4_sub": "Моніторинг переповнення буфера та втрати мережевих пакетів",
        "sec5_title": "5. Джитер Затримки (мс)",
        "sec5_sub": "Показник якості для VoIP, онлайн-ігор та потокового мовлення",
        "sec_outages_title": "Журнал Перерв у Мережі та Відключень",
        "th_outage_start": "Початок",
        "th_outage_end": "Відновлення",
        "th_outage_duration": "Тривалість",
        "th_outage_cause": "Діагностична причина",
        "outage_ongoing": "ТРИВАЄ",
        "outage_empty": "У цей період спостереження перерв у мережі не зафіксовано (100% доступність).",
        "sec_speed_audit_title": "Детальний Аудиторський Журнал Вимірювань Швидкості",
        "sec_speed_audit_sub": "Публічна IP, виявлений ISP, швидкості та діагностичні коди стану",
        "th_date_time": "Дата / Час",
        "th_client_ip_isp": "Клієнтська IP та Провайдер (ISP)",
        "th_down": "Завантаження",
        "th_up": "Вивантаження",
        "th_lat": "Затримка",
        "th_bb": "Bufferbloat",
        "th_engine_srv": "Движок та Сервер",
        "th_status": "Стан",
        "th_link": "Посилання",
        "speed_empty": "За цей період тестів швидкості не зафіксовано.",
        "status_box_title": "Офіційне роз'яснення діагностичних кодів стану (1–15):",
        "status_codes_text": (
            "<b>1</b> – Дійсне вимірювання | "
            "<b>2</b> – Анульовано (внутрішня помилка коду) | "
            "<b>3</b> – Анульовано (помилка пристрою/апаратна) | "
            "<b>4</b> – Анульовано (помилкові дані) | "
            "<b>5</b> – Невідповідність ISP (IP-адреса не належить до зазначеного провайдера) | "
            "<b style='color: #ef4444;'>6 – Порушення продуктивності (надмірне відхилення від очікуваної швидкості / нижче SLA)</b> | "
            "<b>7</b> – Перевищено час очікування (таймаут) | "
            "<b>8</b> – Видалений тест | "
            "<b>9</b> – Перевищено ліміт трафіку (фоновий трафік у мережі під час тесту спотворив результат) | "
            "<b>10</b> – Немає завдань для виконання | "
            "<b>11</b> – Запуск завдання | "
            "<b>12</b> – Помилка (error) | "
            "<b>13</b> – Помилка підключення (пристрій підключено не за інструкцією) | "
            "<b>14</b> – Бездротове вимірювання (тест виконано через Wi-Fi) | "
            "<b>15</b> – Бездротове вимірювання - неперевірена IP"
        ),
        "sec_targets_title": "Деталізація Затримки та Втрат за Точками Призначення",
        "th_target_ep": "Вузол призначення",
        "th_target_sent": "Надіслано",
        "th_target_lost": "Втрачено",
        "th_target_loss_rate": "Рівень втрат",
        "th_target_avg_rtt": "Середній RTT",
        "th_target_p95_rtt": "P95 RTT",
        "sec_port_title": "Аудит Мережевого Нейтралітету та Обмеження Трафіку (Traffic-Shaping)",
        "sec_port_sub_ok": "{count} обмежених або заблокованих протоколів/портів виявлено",
        "th_port_proto": "Порт та Протокол",
        "th_port_ep": "Опорна точка",
        "th_port_speed": "Виміряна швидкість",
        "th_port_ratio": "Співвідношення до порту 443",
        "th_port_verdict": "Оцінка",
        "port_empty": "Тести мережевого нейтралітету не зафіксовані.",
        "legal_appendix_title": "Офіційне застереження для скарги провайдеру та регулятору:",
        "legal_appendix_body": (
            "Цей документ містить дані незалежної телеметрії мережі, зафіксовані автономним апаратним пристроєм NetworkMeasureBox на місці підключення. "
            "Вимірювання відповідають вимогам <b>Регламенту ЄС 2015/2120 (Про відкритий інтернет)</b>, "
            "<b>Керівним принципам BEREC щодо якості послуг (BoR (20) 165)</b> та стандарту <b>IETF RFC 2681</b>. "
            "Тести швидкості виконуються виключно за умови низького локального фонового трафіку для виключення спотворень з боку локальної мережі. "
            "Якщо виміряні швидкості стабільно не досягають гарантованих договором мінімумів або час простою перевищує допустимі норми, "
            "абонент має право відкрити офіційну заявку на усунення несправності, вимагати компенсації або звернутися до національного регулятора зв'язку."
        ),
        "link_open": "Відкрити",
        "unit_sec": "с",
    },
}


def _format_datetime(ts_ms: int) -> str:
    dt = datetime.datetime.fromtimestamp(ts_ms / 1000.0, tz=datetime.timezone.utc)
    return dt.strftime("%Y-%m-%d %H:%M:%S UTC")


def generate_html_dossier(report: ReportData, lang: str = "hu") -> str:
    """Generate complete standalone localized HTML document string (neutralized regulatory branding)."""
    lang_key = lang if lang in DOSSIER_I18N else "hu"
    tr = DOSSIER_I18N[lang_key]

    has_contract_speeds = bool(report.contract_down_mbps > 0 or report.guaranteed_down_mbps > 0)
    has_guaranteed_down = bool(report.guaranteed_down_mbps > 0)
    has_contract_down = bool(report.contract_down_mbps > 0)
    has_guaranteed_up = bool(report.guaranteed_up_mbps > 0)
    has_contract_up = bool(report.contract_up_mbps > 0)

    svg_speed = render_speedtest_chart(
        report.speed_tests,
        report.contract_down_mbps,
        report.contract_up_mbps,
        report.guaranteed_down_mbps,
        report.guaranteed_up_mbps,
        lang=lang_key,
    )
    svg_compliance = render_compliance_chart(
        report.speed_tests,
        report.contract_down_mbps,
        report.contract_up_mbps,
        lang=lang_key,
    )
    svg_latency = render_latency_chart(report.timeseries, report.outages, lang=lang_key)
    svg_loss = render_loss_chart(report.timeseries, lang=lang_key)
    svg_jitter = render_jitter_chart(report.timeseries, lang=lang_key)

    verdict_config = {
        "COMPLIANT": ("#10b981", "#064e3b", tr["verdict_compliant_title"], tr["verdict_compliant_desc"]),
        "DEGRADED": ("#f59e0b", "#78350f", tr["verdict_degraded_title"], tr["verdict_degraded_desc"]),
        "BREACHED": ("#ef4444", "#7f1d1d", tr["verdict_breached_title"], tr["verdict_breached_desc"]),
    }
    badge_border, badge_bg, v_title, v_desc = verdict_config.get(
        report.sla_verdict, ("#38bdf8", "#0c4a6e", tr["verdict_default_title"], tr["verdict_default_desc"])
    )

    outage_rows_html = []
    if report.outages:
        for o in report.outages:
            start_str = _format_datetime(o.start_ts)
            end_str = _format_datetime(o.end_ts) if o.end_ts else f"<span class='text-red'>{tr['outage_ongoing']}</span>"
            outage_rows_html.append(f"""<tr>
  <td>{start_str}</td>
  <td>{end_str}</td>
  <td><strong>{o.duration_sec} {tr['unit_sec']}</strong></td>
  <td>{o.cause}</td>
</tr>""")
    else:
        outage_rows_html.append(f"<tr><td colspan='4' class='text-center text-muted'>{tr['outage_empty']}</td></tr>")

    target_rows_html = []
    for t in report.target_stats:
        target_rows_html.append(f"""<tr>
  <td><strong>{t.label}</strong> ({t.addr})</td>
  <td>{t.sent:,}</td>
  <td>{t.lost:,}</td>
  <td class="{ 'text-red' if t.loss_pct > 1.0 else 'text-green' }">{t.loss_pct:.2f}%</td>
  <td>{t.avg_rtt_ms or '-'} ms</td>
  <td>{t.p95_rtt_ms or '-'} ms</td>
</tr>""")

    speed_rows_html = []
    if report.speed_tests:
        for s in report.speed_tests:
            ts_str = _format_datetime(s["ts"])
            d_pct_off = s.get("down_pct_of_offered")
            u_pct_off = s.get("up_pct_of_offered")

            if d_pct_off is None and s.get("down_mbps") and report.contract_down_mbps > 0:
                d_pct_off = round((s["down_mbps"] / report.contract_down_mbps) * 100.0, 1)
            if u_pct_off is None and s.get("up_mbps") and report.contract_up_mbps > 0:
                u_pct_off = round((s["up_mbps"] / report.contract_up_mbps) * 100.0, 1)

            d_val_mbps = s.get("down_mbps") or 0.0
            u_val_mbps = s.get("up_mbps") or 0.0

            d_color = "#10b981" if (d_pct_off or 0) >= 80 else ("#f59e0b" if (d_pct_off or 0) >= 60 else "#ef4444")
            u_color = "#10b981" if (u_pct_off or 0) >= 80 else ("#f59e0b" if (u_pct_off or 0) >= 60 else "#ef4444")

            d_pct_badge = f" <span style='font-size:11px; color:{d_color}; font-weight:600;'>({d_pct_off:.0f}%)</span>" if (d_pct_off is not None and has_contract_down) else ""
            u_pct_badge = f" <span style='font-size:11px; color:{u_color}; font-weight:600;'>({u_pct_off:.0f}%)</span>" if (u_pct_off is not None and has_contract_up) else ""

            d_val = f"<strong>{d_val_mbps:.2f} Mb/s</strong>{d_pct_badge}" if s.get("down_mbps") else "-"
            u_val = f"<strong>{u_val_mbps:.2f} Mb/s</strong>{u_pct_badge}" if s.get("up_mbps") else "-"
            bb_val = f"{s.get('bufferbloat_grade') or '-'} (+{s.get('bufferbloat_delta_ms') or 0:.1f} ms)" if s.get('bufferbloat_grade') else "-"

            # IP & Detected ISP Provider
            v4 = s.get('client_ip')
            v6 = s.get('client_ipv6')
            row_isp = s.get('isp_name') or report.isp_name or "Internet Provider"

            if v4 and v6:
                client_ip_html = f"<div style='font-size:11px; font-family:monospace;'><span style='color:#38bdf8;' title='Public IPv4'>{v4}</span><br><span style='color:#a78bfa; font-size:10px;' title='Public IPv6'>{v6}</span><br><span class='badge' style='font-size:9.5px; background:rgba(56,189,248,0.12); color:#38bdf8; border:1px solid rgba(56,189,248,0.25); border-radius:3px; padding:1px 4px; display:inline-block; margin-top:2px;'>{row_isp}</span></div>"
            elif v4:
                client_ip_html = f"<div style='font-size:11px; font-family:monospace;'><code style='color:#38bdf8;'>{v4}</code><br><span class='badge' style='font-size:9.5px; background:rgba(56,189,248,0.12); color:#38bdf8; border:1px solid rgba(56,189,248,0.25); border-radius:3px; padding:1px 4px; display:inline-block; margin-top:2px;'>{row_isp}</span></div>"
            elif v6:
                client_ip_html = f"<div style='font-size:10px; font-family:monospace;'><code style='color:#a78bfa;'>{v6}</code><br><span class='badge' style='font-size:9.5px; background:rgba(56,189,248,0.12); color:#38bdf8; border:1px solid rgba(56,189,248,0.25); border-radius:3px; padding:1px 4px; display:inline-block; margin-top:2px;'>{row_isp}</span></div>"
            else:
                client_ip_html = f"<span class='text-muted'>- ({row_isp})</span>"

            # Benchmark Status Code Display
            nmhh_code = s.get("nmhh_code", 1)
            if nmhh_code == 1:
                status_html = "<span class='badge-status-1' title='Valid'>1</span>"
            elif nmhh_code == 6:
                status_label = "6 (SLA Alatt)" if lang_key == "hu" else "6 (Below SLA)"
                status_html = f"<span class='badge-status-6' title='{status_label}'>{status_label}</span>"
            elif nmhh_code == 9:
                status_html = "<span class='badge-status-warn' title='Traffic Quota Exceeded'>9</span>"
            elif nmhh_code in (14, 15):
                status_html = f"<span class='badge-status-warn' title='WiFi Measurement'>{nmhh_code}</span>"
            else:
                status_html = f"<span class='badge-status-err' title='{nmhh_code}'>{nmhh_code}</span>"

            ping_ms_val = f"{(s['ping_us'] // 1000):.0f} ms" if s.get('ping_us') else "-"
            srv_desc = s.get('server_name') or 'Default Edge Server'
            engine_badge = (s.get('engine') or 'ookla').upper()
            res_link = f"<a href='{s.get('result_url')}' target='_blank' style='color:#38bdf8; font-weight:600; text-decoration:none;'>🔗 {tr['link_open']} ↗</a>" if s.get('result_url') else "<span class='text-muted'>-</span>"

            speed_rows_html.append(f"""<tr>
  <td>{ts_str}</td>
  <td>{client_ip_html}</td>
  <td>{d_val}</td>
  <td>{u_val}</td>
  <td>{ping_ms_val}</td>
  <td>{bb_val}</td>
  <td><span class="badge" style="font-size:10px; background:#1e293b; color:#cbd5e1; padding:2px 6px; border-radius:4px;">{engine_badge}</span><br><small style="color:var(--text-muted); font-size:11px;">{srv_desc}</small></td>
  <td class="text-center">{status_html}</td>
  <td>{res_link}</td>
</tr>""")
    else:
        speed_rows_html.append(f"<tr><td colspan='9' class='text-center text-muted'>{tr['speed_empty']}</td></tr>")

    port_rows_html = []
    if report.port_checks:
        for p in report.port_checks[:10]:
            v_color = "text-green" if p["verdict"] == "ok" else "text-red"
            ratio_str = f"{p['ratio']:.2f}x" if p.get("ratio") is not None else "-"
            bps_mbps = f"{(p['bps'] / 1_000_000):.2f} Mbps" if p.get("bps") else "N/A"
            port_rows_html.append(f"""<tr>
  <td><strong>{p['proto'].upper()} Port {p['port']}</strong></td>
  <td>{p['endpoint']}</td>
  <td>{bps_mbps}</td>
  <td>{ratio_str}</td>
  <td><span class="{v_color}">{p['verdict'].upper()}</span></td>
</tr>""")
    else:
        port_rows_html.append(f"<tr><td colspan='5' class='text-center text-muted'>{tr['port_empty']}</td></tr>")

    # Statistical values formatting
    s_sum = report.speed_summary
    p_sum = report.ping_summary

    # Render Contracted/Guaranteed Speed Cards
    cards = []
    if has_guaranteed_down:
        cards.append(f"""
      <div class="contract-card">
        <div class="contract-label">{tr['lbl_guaranteed_down']}</div>
        <div class="contract-val-guar">{report.guaranteed_down_mbps:.0f} Mb/s</div>
      </div>""")
    if has_contract_down:
        cards.append(f"""
      <div class="contract-card">
        <div class="contract-label">{tr['lbl_contract_down']}</div>
        <div class="contract-val">{report.contract_down_mbps:.0f} Mb/s</div>
      </div>""")
    if has_guaranteed_up:
        cards.append(f"""
      <div class="contract-card">
        <div class="contract-label">{tr['lbl_guaranteed_up']}</div>
        <div class="contract-val-guar">{report.guaranteed_up_mbps:.0f} Mb/s</div>
      </div>""")
    if has_contract_up:
        cards.append(f"""
      <div class="contract-card">
        <div class="contract-label">{tr['lbl_contract_up']}</div>
        <div class="contract-val">{report.contract_up_mbps:.0f} Mb/s</div>
      </div>""")

    if cards:
        contract_cards_html = f"""
    <div class="contract-cards">
      {"".join(cards)}
    </div>
"""
    else:
        contract_cards_html = f"""
    <div style="background: rgba(15, 23, 42, 0.6); border: 1px dashed var(--border); border-radius: 6px; padding: 12px 16px; margin-top: 14px; font-size: 12.5px; color: var(--text-muted);">
      ℹ️ {tr['unconfigured_speeds_notice']}
    </div>
"""

    # Format KPI summary download and statistical speed values
    has_speed_results = bool(s_sum.successful_tests > 0 and report.speed_tests)
    if has_speed_results:
        kpi_down_val = f"{s_sum.avg_down_mbps or 0:.1f} <span style='font-size: 14px;'>Mb/s</span>"
        stat_down_avg = f"<strong>{s_sum.avg_down_mbps or 0:.2f} Mb/s</strong>"
        stat_down_med = f"{s_sum.median_down_mbps or 0:.2f} Mb/s"
        stat_down_p95 = f"{s_sum.p95_down_mbps or 0:.2f} Mb/s"
        stat_down_min = f"{s_sum.min_down_mbps or 0:.2f} Mb/s"
        stat_down_max = f"{s_sum.max_down_mbps or 0:.2f} Mb/s"
        stat_down_std = f"&plusmn;{s_sum.stddev_down_mbps or 0:.2f} Mb/s"

        stat_up_avg = f"<strong>{s_sum.avg_up_mbps or 0:.2f} Mb/s</strong>"
        stat_up_med = f"{s_sum.median_up_mbps or 0:.2f} Mb/s"
        stat_up_p95 = f"{s_sum.p95_up_mbps or 0:.2f} Mb/s"
        stat_up_min = f"{s_sum.min_up_mbps or 0:.2f} Mb/s"
        stat_up_max = f"{s_sum.max_up_mbps or 0:.2f} Mb/s"
        stat_up_std = f"&plusmn;{s_sum.stddev_up_mbps or 0:.2f} Mb/s"

        if has_guaranteed_down:
            kpi_down_sub = tr["kpi_down_sub_guar"].format(guar=(s_sum.avg_down_pct_of_guaranteed or 0), up=(s_sum.avg_up_mbps or 0))
        elif has_contract_down:
            kpi_down_sub = tr["kpi_down_sub_off"].format(off=(s_sum.avg_down_pct_of_offered or 0), up=(s_sum.avg_up_mbps or 0))
        else:
            kpi_down_sub = tr["kpi_down_sub_peak"].format(peak=(s_sum.max_down_mbps or 0), up=(s_sum.avg_up_mbps or 0))
    else:
        kpi_down_val = "-"
        kpi_down_sub = tr["speed_empty"]
        stat_down_avg = "-"
        stat_down_med = "-"
        stat_down_p95 = "-"
        stat_down_min = "-"
        stat_down_max = "-"
        stat_down_std = "-"

        stat_up_avg = "-"
        stat_up_med = "-"
        stat_up_p95 = "-"
        stat_up_min = "-"
        stat_up_max = "-"
        stat_up_std = "-"

    # Format SLA compliance text in verdict banner
    if has_contract_speeds:
        verdict_metric_html = f"{tr['lbl_sla_compliance_rate']} {s_sum.sla_compliance_pct:.1f}%"
    else:
        success_pct = (s_sum.successful_tests / len(report.speed_tests) * 100.0) if report.speed_tests else 100.0
        verdict_metric_html = f"{tr['lbl_measurement_success_rate']} {success_pct:.1f}%"

    doc_title_text = tr["doc_title"].format(box_id=report.box_id)
    badge_probe_text = tr["badge_probe"].format(box_id=report.box_id)

    html = f"""<!DOCTYPE html>
<html lang="{lang_key}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{doc_title_text}</title>
  <style>
    :root {{
      --bg: #0f172a;
      --card-bg: #1e293b;
      --border: #334155;
      --text: #f8fafc;
      --text-muted: #94a3b8;
      --primary: #38bdf8;
      --green: #10b981;
      --amber: #f59e0b;
      --red: #ef4444;
      --font: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      background: var(--bg);
      color: var(--text);
      font-family: var(--font);
      line-height: 1.5;
      padding: 24px;
    }}
    .container {{ max-width: 1080px; margin: 0 auto; }}
    
    /* Header Block */
    .dossier-header {{
      background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 20px 24px;
      margin-bottom: 24px;
    }}
    .dossier-title-row {{
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      flex-wrap: wrap;
      gap: 16px;
      border-bottom: 1px solid rgba(255,255,255,0.08);
      padding-bottom: 16px;
      margin-bottom: 16px;
    }}
    .dossier-title {{
      font-size: 22px;
      font-weight: 700;
      color: var(--primary);
    }}
    .dossier-subtitle {{
      font-size: 13.5px;
      color: var(--text-muted);
      margin-top: 4px;
    }}
    .dossier-meta-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
      gap: 16px;
    }}
    .dossier-meta-box {{
      font-size: 13px;
      line-height: 1.7;
    }}
    .dossier-meta-box strong {{
      color: #cbd5e1;
    }}

    /* Contract Comparison Cards */
    .contract-cards {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 12px;
      margin-top: 14px;
    }}
    .contract-card {{
      background: rgba(15, 23, 42, 0.75);
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 12px 14px;
      text-align: center;
    }}
    .contract-label {{ font-size: 11px; text-transform: uppercase; color: var(--text-muted); font-weight: 600; }}
    .contract-val {{ font-size: 20px; font-weight: 700; color: #ffffff; margin-top: 4px; }}
    .contract-val-guar {{ font-size: 20px; font-weight: 700; color: #f43f5e; margin-top: 4px; }}

    /* Verdict Banner */
    .verdict-banner {{
      background: {badge_bg};
      border: 1px solid {badge_border};
      border-radius: 8px;
      padding: 16px 20px;
      margin-bottom: 24px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      gap: 12px;
    }}
    .verdict-title {{ font-size: 18px; font-weight: 700; color: #ffffff; }}
    .verdict-desc {{ font-size: 13px; color: #e2e8f0; margin-top: 2px; }}

    /* KPI Grid */
    .kpi-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 16px;
      margin-bottom: 24px;
    }}
    .kpi-card {{
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 16px;
    }}
    .kpi-label {{ font-size: 11.5px; color: var(--text-muted); text-transform: uppercase; font-weight: 600; }}
    .kpi-value {{ font-size: 24px; font-weight: 700; color: var(--text); margin-top: 4px; }}
    .kpi-sub {{ font-size: 12px; color: var(--text-muted); margin-top: 4px; }}

    /* Section Cards */
    .section {{
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 20px;
      margin-bottom: 24px;
    }}
    .section-title {{
      font-size: 16px;
      font-weight: 600;
      color: var(--text);
      margin-bottom: 14px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      gap: 8px;
    }}
    .nmb-svg {{ width: 100%; height: auto; display: block; border-radius: 6px; background: #0b1120; }}

    /* Tables */
    .table-wrap {{ width: 100%; overflow-x: auto; -webkit-overflow-scrolling: touch; }}
    table {{ width: 100%; border-collapse: collapse; margin-top: 12px; font-size: 12.5px; }}
    th, td {{ padding: 10px 12px; text-align: left; border-bottom: 1px solid var(--border); white-space: nowrap; }}
    th {{ color: var(--text-muted); font-weight: 600; text-transform: uppercase; font-size: 11px; }}
    .text-green {{ color: var(--green); }}
    .text-amber {{ color: var(--amber); }}
    .text-red {{ color: var(--red); }}
    .text-muted {{ color: var(--text-muted); }}
    .text-center {{ text-align: center; }}

    /* Status Badges */
    .badge-status-1 {{
      background: rgba(16, 185, 129, 0.2);
      color: #34d399;
      border: 1px solid #10b981;
      padding: 2px 8px;
      border-radius: 4px;
      font-weight: 700;
    }}
    .badge-status-6 {{
      background: rgba(239, 68, 68, 0.25);
      color: #f87171;
      border: 1px solid #ef4444;
      padding: 2px 8px;
      border-radius: 4px;
      font-weight: 700;
      font-size: 11px;
    }}
    .badge-status-warn {{
      background: rgba(245, 158, 11, 0.2);
      color: #fbbf24;
      border: 1px solid #f59e0b;
      padding: 2px 8px;
      border-radius: 4px;
      font-weight: 700;
    }}
    .badge-status-err {{
      background: rgba(239, 68, 68, 0.2);
      color: #f87171;
      border: 1px solid #ef4444;
      padding: 2px 8px;
      border-radius: 4px;
      font-weight: 700;
    }}

    /* Status Explain Box */
    .status-box {{
      background: #090e1a;
      border: 1px dashed var(--border);
      border-radius: 8px;
      padding: 16px 18px;
      font-size: 12px;
      line-height: 1.6;
      margin-top: 18px;
    }}

    /* Appendix & Escalation Notice */
    .appendix {{
      background: #090e1a;
      border: 1px solid var(--border);
      border-left: 4px solid var(--primary);
      border-radius: 6px;
      padding: 16px 20px;
      font-size: 12.5px;
      color: #cbd5e1;
      line-height: 1.6;
      margin-top: 24px;
    }}

    @media print {{
      body {{ background: #ffffff !important; color: #000000 !important; padding: 0 !important; font-size: 11px !important; }}
      .section, .kpi-card, .dossier-header, .contract-card, .verdict-banner {{ border-color: #cbd5e1 !important; background: #ffffff !important; color: #000000 !important; page-break-inside: avoid; }}
      .nmb-svg {{ background: #f8fafc !important; }}
      .verdict-title, .dossier-title, strong {{ color: #000000 !important; }}
      :root {{ --text: #0f172a; --text-muted: #475569; }}
      a {{ text-decoration: none; color: #000000; }}
      .page-break {{ page-break-before: always; }}
    }}
  </style>
</head>
<body>
<div class="container">

  <!-- Main Dossier Header -->
  <header class="dossier-header">
    <div class="dossier-title-row">
      <div>
        <div class="dossier-title">{tr['header_title']}</div>
        <div class="dossier-subtitle">{tr['header_subtitle']}</div>
      </div>
      <div style="text-align: right;">
        <span class="badge" style="background:#1e293b; color:#38bdf8; border:1px solid #38bdf8; padding:4px 10px; border-radius:4px; font-weight:700;">{badge_probe_text}</span>
      </div>
    </div>

    <div class="dossier-meta-grid">
      <div class="dossier-meta-box">
        <div><strong>{tr['lbl_probe_name']}</strong> {report.box_id}</div>
        <div><strong>{tr['lbl_isp']}</strong> {report.isp_name}</div>
        <div><strong>{tr['lbl_access_tech']}</strong> {report.isp_connection_type.upper()}</div>
        <div><strong>{tr['lbl_subscriber_id']}</strong> {report.account_id or 'N/A'} ({tr['lbl_circuit_id']} {report.circuit_id or 'Default'})</div>
      </div>
      <div class="dossier-meta-box">
        <div><strong>{tr['lbl_eval_window']}</strong> {_format_datetime(report.start_ms)} &rarr; {_format_datetime(report.end_ms)}</div>
        <div><strong>{tr['lbl_total_tests']}</strong> {len(report.speed_tests)} ({s_sum.successful_tests} ok)</div>
        <div><strong>{tr['lbl_gen_time']}</strong> {_format_datetime(db.now_ms())}</div>
        <div><strong>{tr['lbl_firmware']}</strong> {tr['firmware_desc']}</div>
      </div>
    </div>

    {contract_cards_html}
  </header>

  <!-- Verdict Banner -->
  <div class="verdict-banner">
    <div>
      <div class="verdict-title">{v_title}</div>
      <div class="verdict-desc">{v_desc}</div>
    </div>
    <div style="font-size: 13px; text-align: right; color: #ffffff; font-weight: 600;">
      {verdict_metric_html}
    </div>
  </div>

  <!-- KPI Grid -->
  <div class="kpi-grid">
    <div class="kpi-card">
      <div class="kpi-label">{tr['kpi_availability']}</div>
      <div class="kpi-value { 'text-green' if report.uptime_pct >= 99.9 else 'text-red' }">{report.uptime_pct:.2f}%</div>
      <div class="kpi-sub">{tr['kpi_outage_sub'].format(outages=len(report.outages), sec=report.total_outage_sec)}</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label">{tr['kpi_latency']}</div>
      <div class="kpi-value">{p_sum.rtt_avg_ms or 0:.1f} <span style="font-size: 14px;">ms</span></div>
      <div class="kpi-sub">{tr['kpi_latency_sub'].format(med=(p_sum.rtt_median_ms or 0), p95=(p_sum.rtt_p95_ms or 0))}</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label">{tr['kpi_loss']}</div>
      <div class="kpi-value { 'text-green' if p_sum.loss_pct < 0.5 else 'text-red' }">{p_sum.loss_pct:.2f}%</div>
      <div class="kpi-sub">{tr['kpi_loss_sub'].format(lost=p_sum.total_lost, sent=p_sum.total_sent)}</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label">{tr['kpi_download']}</div>
      <div class="kpi-value">{kpi_down_val}</div>
      <div class="kpi-sub">{kpi_down_sub}</div>
    </div>
  </div>

  <!-- 1. GRAPH: Speed Values vs Guaranteed & Offered SLA -->
  <div class="section">
    <div class="section-title">
      <span>{tr['sec1_title']}</span>
      <span class="text-muted" style="font-size: 12px;">{tr['sec1_sub']}</span>
    </div>
    {svg_speed}
  </div>

  <!-- 2. GRAPH: Speed compliance ratio % -->
  <div class="section">
    <div class="section-title">
      <span>{tr['sec2_title']}</span>
      <span class="text-muted" style="font-size: 12px;">{tr['sec2_sub']}</span>
    </div>
    {svg_compliance}
  </div>

  <!-- Statistical Characteristics Table -->
  <div class="section">
    <div class="section-title">
      <span>{tr['sec_stats_title']}</span>
      <span class="text-muted" style="font-size: 12px;">{tr['sec_stats_sub']}</span>
    </div>
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>{tr['th_parameter']}</th>
            <th>{tr['th_average']}</th>
            <th>{tr['th_median']}</th>
            <th>{tr['th_p95']}</th>
            <th>{tr['th_min']}</th>
            <th>{tr['th_max']}</th>
            <th>{tr['th_stddev']}</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td><strong>{tr['param_down']}</strong></td>
            <td>{stat_down_avg}</td>
            <td>{stat_down_med}</td>
            <td>{stat_down_p95}</td>
            <td>{stat_down_min}</td>
            <td>{stat_down_max}</td>
            <td>{stat_down_std}</td>
          </tr>
          <tr>
            <td><strong>{tr['param_up']}</strong></td>
            <td>{stat_up_avg}</td>
            <td>{stat_up_med}</td>
            <td>{stat_up_p95}</td>
            <td>{stat_up_min}</td>
            <td>{stat_up_max}</td>
            <td>{stat_up_std}</td>
          </tr>
          <tr>
            <td><strong>{tr['param_lat']}</strong></td>
            <td>{p_sum.rtt_avg_ms or 0:.1f} ms</td>
            <td>{p_sum.rtt_median_ms or 0:.1f} ms</td>
            <td>{p_sum.rtt_p95_ms or 0:.1f} ms</td>
            <td>{p_sum.rtt_min_ms or 0:.1f} ms</td>
            <td>{p_sum.rtt_max_ms or 0:.1f} ms</td>
            <td>&plusmn;{p_sum.rtt_stddev_ms or 0:.1f} ms</td>
          </tr>
          <tr>
            <td><strong>{tr['param_jitter']}</strong></td>
            <td>{p_sum.jitter_avg_ms or 0:.1f} ms</td>
            <td>-</td>
            <td>-</td>
            <td>-</td>
            <td>-</td>
            <td>-</td>
          </tr>
          <tr>
            <td><strong>{tr['param_loss']}</strong></td>
            <td>{p_sum.loss_pct:.2f}%</td>
            <td>-</td>
            <td>-</td>
            <td>0.00%</td>
            <td>{p_sum.loss_pct * 2:.1f}%</td>
            <td>-</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>

  <!-- 3. GRAPH: Latency Timeline -->
  <div class="section">
    <div class="section-title">
      <span>{tr['sec3_title']}</span>
      <span class="text-muted" style="font-size: 12px;">{tr['sec3_sub']}</span>
    </div>
    {svg_latency}
  </div>

  <!-- 4. GRAPH: Packet Loss Spikes -->
  <div class="section">
    <div class="section-title">
      <span>{tr['sec4_title']}</span>
      <span class="text-muted" style="font-size: 12px;">{tr['sec4_sub']}</span>
    </div>
    {svg_loss}
  </div>

  <!-- 5. GRAPH: Latency Jitter Variations -->
  <div class="section">
    <div class="section-title">
      <span>{tr['sec5_title']}</span>
      <span class="text-muted" style="font-size: 12px;">{tr['sec5_sub']}</span>
    </div>
    {svg_jitter}
  </div>

  <!-- Outage Incident Log -->
  <div class="section">
    <div class="section-title">{tr['sec_outages_title']}</div>
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>{tr['th_outage_start']}</th>
            <th>{tr['th_outage_end']}</th>
            <th>{tr['th_outage_duration']}</th>
            <th>{tr['th_outage_cause']}</th>
          </tr>
        </thead>
        <tbody>
          {''.join(outage_rows_html)}
        </tbody>
      </table>
    </div>
  </div>

  <!-- Detailed Speedtest Audit Log -->
  <div class="section">
    <div class="section-title">
      <span>{tr['sec_speed_audit_title']}</span>
      <span class="text-muted" style="font-size: 12px;">{tr['sec_speed_audit_sub']}</span>
    </div>
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>{tr['th_date_time']}</th>
            <th>{tr['th_client_ip_isp']}</th>
            <th>{tr['th_down']}</th>
            <th>{tr['th_up']}</th>
            <th>{tr['th_lat']}</th>
            <th>{tr['th_bb']}</th>
            <th>{tr['th_engine_srv']}</th>
            <th class="text-center">{tr['th_status']}</th>
            <th>{tr['th_link']}</th>
          </tr>
        </thead>
        <tbody>
          {''.join(speed_rows_html)}
        </tbody>
      </table>
    </div>

    <!-- Diagnostic & Regulatory Status Codes 1-15 Explanation Box -->
    <div class="status-box">
      <h4 style="font-size: 13px; font-weight: 700; margin-bottom: 8px; color: #38bdf8;">
        {tr['status_box_title']}
      </h4>
      <p style="font-size: 11.5px; line-height: 1.6; color: #cbd5e1;">
        {tr['status_codes_text']}
      </p>
    </div>
  </div>

  <!-- Multi-target Ping Breakdown -->
  <div class="section">
    <div class="section-title">{tr['sec_targets_title']}</div>
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>{tr['th_target_ep']}</th>
            <th>{tr['th_target_sent']}</th>
            <th>{tr['th_target_lost']}</th>
            <th>{tr['th_target_loss_rate']}</th>
            <th>{tr['th_target_avg_rtt']}</th>
            <th>{tr['th_target_p95_rtt']}</th>
          </tr>
        </thead>
        <tbody>
          {''.join(target_rows_html)}
        </tbody>
      </table>
    </div>
  </div>

  <!-- Net-Neutrality Port Throttling Section -->
  <div class="section">
    <div class="section-title">
      <span>{tr['sec_port_title']}</span>
      <span class="{ 'text-green' if report.throttled_ports_count == 0 else 'text-red' }" style="font-size: 12px;">
        {tr['sec_port_sub_ok'].format(count=report.throttled_ports_count)}
      </span>
    </div>
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>{tr['th_port_proto']}</th>
            <th>{tr['th_port_ep']}</th>
            <th>{tr['th_port_speed']}</th>
            <th>{tr['th_port_ratio']}</th>
            <th>{tr['th_port_verdict']}</th>
          </tr>
        </thead>
        <tbody>
          {''.join(port_rows_html)}
        </tbody>
      </table>
    </div>
  </div>

  <!-- Legal & Escalation Appendix -->
  <div class="appendix">
    <strong>{tr['legal_appendix_title']}</strong><br>
    {tr['legal_appendix_body']}
  </div>

</div>
</body>
</html>
"""
    return html


def save_html_dossier(report: ReportData, output_path: Path, lang: str = "hu") -> Path:
    """Render and save HTML dossier to disk."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    content = generate_html_dossier(report, lang=lang)
    output_path.write_text(content, encoding="utf-8")
    return output_path
