"""The words for how the box was connected (nmb/common/net_setup.py), in all 11 languages, one source.

The dossier, the Web UI and the Telegram bot read these texts from here, so the three never differ.
Every language has every key (tests/test_measurement_setup.py checks it); a missing one falls back to
English, never to Hungarian.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from nmb.common.net_setup import ISP_PATHS, MODES, SOURCES, UPLINK_KINDS, label_codes

LANGUAGES = ("en", "hu", "de", "fr", "uk", "ro", "it", "es", "pt", "pt-br", "zh")

_KEYS = (
    "setup_title", "setup_intro", "setup_label",
    "setup_col_from", "setup_col_to", "setup_col_mode", "setup_col_link", "setup_col_path", "setup_col_source",
    "setup_none", "setup_unknown", "setup_warn_behind", "setup_mixed", "setup_partly_unknown",
    "setup_mode_standalone", "setup_mode_mode_a", "setup_mode_mode_b",
    "setup_short_standalone", "setup_short_mode_a", "setup_short_mode_b",
    "setup_link_ethernet", "setup_link_pppoe", "setup_link_wifi", "setup_link_usb", "setup_link_bridge",
    "setup_link_passthrough", "setup_link_lag",
    "setup_path_direct_pppoe", "setup_path_direct_public", "setup_path_direct_cgnat", "setup_path_behind_router",
    "setup_short_direct", "setup_short_behind_router",
    "setup_src_recorded", "setup_src_changed", "setup_src_derived",
)

# One tuple per key, in the order of LANGUAGES: en, hu, de, fr, uk, ro, it, es, pt, pt-br, zh.
_T = {
    "setup_title": (
        "Measurement setup", "Mérési bekötés", "Messaufbau", "Configuration de mesure",
        "Схема підключення під час вимірювань", "Modul de conectare la măsurare", "Configurazione di misura",
        "Configuración de medición", "Configuração de medição", "Configuração de medição", "测量接入方式"),
    "setup_intro": (
        "How the box was connected while it measured. \"Direct to the ISP\": the box held the ISP's address itself "
        "(its own PPPoE session, or a public or carrier-grade NAT (CGNAT) address on the measuring link). \"Behind "
        "another router\": the box had a private address, so a router (the customer's or the ISP's own) stood "
        "between the box and the ISP and may affect the results. \"Reconstructed from the event log\": determined "
        "afterwards from the stored data; \"unknown\": cannot be told for sure.",
        "Hogyan csatlakozott a mérőeszköz a mérések idején. „Közvetlenül a szolgáltatón”: a mérőeszköz maga kapta a "
        "szolgáltató címét (saját PPPoE-kapcsolat, vagy nyilvános vagy szolgáltatói NAT-os (CGNAT) cím a mérő "
        "kapcsolaton). „Másik router mögött”: a mérőeszköznek privát címe volt, tehát egy router (az előfizetőé vagy "
        "a szolgáltatóé) állt közte és a szolgáltató között, és ez befolyásolhatja az eredményeket. „Eseménynaplóból "
        "visszaállítva”: utólag, a tárolt adatokból megállapítva; „ismeretlen”: nem állapítható meg biztosan.",
        "Wie die Messbox während der Messungen angeschlossen war. „Direkt am Anbieter“: die Box hatte selbst die "
        "Adresse des Anbieters (eigene PPPoE-Sitzung, oder eine öffentliche oder Carrier-Grade-NAT-Adresse (CGNAT) am "
        "Messanschluss). „Hinter einem anderen Router“: die Box hatte eine private Adresse, also stand ein Router (des "
        "Kunden oder des Anbieters) zwischen ihr und dem Anbieter, und er kann die Ergebnisse beeinflussen. „Aus dem "
        "Ereignisprotokoll rekonstruiert“: nachträglich aus den gespeicherten Daten bestimmt; „unbekannt“: nicht "
        "sicher feststellbar.",
        "Comment le boîtier était raccordé pendant les mesures. « Directement chez le fournisseur » : le boîtier "
        "avait lui-même l'adresse du fournisseur (sa propre session PPPoE, ou une adresse publique ou de NAT opérateur "
        "(CGNAT) sur le lien de mesure). « Derrière un autre routeur » : le boîtier avait une adresse privée, donc un "
        "routeur (du client ou du fournisseur) se trouvait entre lui et le fournisseur et peut influencer les "
        "résultats. « Reconstitué depuis le journal » : déterminé après coup à partir des données enregistrées ; "
        "« inconnu » : impossible à établir avec certitude.",
        "Як пристрій був підключений під час вимірювань. «Напряму до провайдера»: пристрій сам мав адресу провайдера "
        "(власний сеанс PPPoE або публічну чи CGNAT-адресу на каналі вимірювання). «За іншим роутером»: пристрій мав "
        "приватну адресу, тобто між ним і провайдером був роутер (абонента чи провайдера), який може впливати на "
        "результати. «Відновлено з журналу подій»: визначено згодом зі збережених даних; «невідомо»: точно "
        "встановити неможливо.",
        "Cum era conectat dispozitivul în timpul măsurătorilor. „Direct la furnizor”: dispozitivul avea chiar adresa "
        "furnizorului (propria sesiune PPPoE sau o adresă publică ori CGNAT pe legătura de măsurare). „În spatele "
        "altui router”: dispozitivul avea o adresă privată, deci un router (al clientului sau al furnizorului) se afla "
        "între el și furnizor și poate influența rezultatele. „Reconstituit din jurnal”: stabilit ulterior din datele "
        "stocate; „necunoscut”: nu se poate stabili sigur.",
        "Come era collegato il dispositivo durante le misure. «Direttamente al fornitore»: il dispositivo aveva "
        "l'indirizzo del fornitore (una propria sessione PPPoE, o un indirizzo pubblico o CGNAT sul collegamento di "
        "misura). «Dietro un altro router»: il dispositivo aveva un indirizzo privato, quindi un router (del cliente o "
        "del fornitore) era tra il dispositivo e il fornitore e può influire sui risultati. «Ricostruito dal "
        "registro»: determinato in seguito dai dati salvati; «sconosciuto»: non determinabile con certezza.",
        "Cómo estaba conectado el dispositivo durante las mediciones. «Directo al proveedor»: el dispositivo tenía la "
        "dirección del proveedor (su propia sesión PPPoE, o una dirección pública o CGNAT en el enlace de medición). "
        "«Detrás de otro router»: el dispositivo tenía una dirección privada, así que un router (del cliente o del "
        "proveedor) estaba entre él y el proveedor y puede influir en los resultados. «Reconstruido del registro»: "
        "determinado después a partir de los datos guardados; «desconocido»: no se puede establecer con certeza.",
        "Como o dispositivo estava ligado durante as medições. «Direto ao fornecedor»: o dispositivo tinha o próprio "
        "endereço do fornecedor (sessão PPPoE própria, ou um endereço público ou CGNAT na ligação de medição). «Atrás "
        "de outro router»: o dispositivo tinha um endereço privado, portanto um router (do cliente ou do fornecedor) "
        "estava entre ele e o fornecedor e pode influenciar os resultados. «Reconstruído a partir do registo»: "
        "determinado depois a partir dos dados guardados; «desconhecido»: não é possível determinar com certeza.",
        "Como o dispositivo estava conectado durante as medições. «Direto na operadora»: o dispositivo tinha o próprio "
        "endereço da operadora (sessão PPPoE própria, ou um endereço público ou CGNAT no link de medição). «Atrás de "
        "outro roteador»: o dispositivo tinha um endereço privado, então um roteador (do cliente ou da operadora) "
        "estava entre ele e a operadora e pode influenciar os resultados. «Reconstruído pelo registro»: determinado "
        "depois a partir dos dados salvos; «desconhecido»: não é possível determinar com certeza.",
        "测量期间设备的接入方式。“直连运营商”：设备自己持有运营商的地址（自己的 PPPoE 会话，或测量链路上的公网地址或运营商级 NAT（CGNAT）"
        "地址）。“在另一台路由器后面”：设备使用私有地址，因此设备与运营商之间有一台路由器（用户的或运营商的），它可能影响测量结果。"
        "“根据事件日志重建”：事后根据已存储的数据确定；“未知”：无法确定。"),
    "setup_label": ("Setup", "Bekötés", "Aufbau", "Raccordement", "Підключення", "Conectare", "Collegamento",
                    "Conexión", "Ligação", "Conexão", "接入方式"),
    "setup_col_from": ("From", "Kezdete", "Von", "Début", "Від", "De la", "Da", "Desde", "De", "De", "开始"),
    "setup_col_to": ("To", "Vége", "Bis", "Fin", "До", "Până la", "A", "Hasta", "Até", "Até", "结束"),
    "setup_col_mode": ("Mode", "Üzemmód", "Betriebsart", "Mode", "Режим", "Mod", "Modalità", "Modo", "Modo", "Modo",
                       "工作模式"),
    "setup_col_link": ("Link", "Kapcsolat", "Verbindung", "Liaison", "Канал", "Legătură", "Linea", "Enlace",
                       "Tipo de ligação", "Tipo de link", "链路"),
    "setup_col_path": ("Path to the ISP", "Útvonal a szolgáltatóig", "Weg zum Anbieter", "Chemin vers le fournisseur",
                       "Шлях до провайдера", "Calea spre furnizor", "Percorso verso il fornitore", "Camino al proveedor",
                       "Caminho até ao fornecedor", "Caminho até a operadora", "到运营商的路径"),
    "setup_col_source": ("Source", "Forrás", "Quelle", "Source", "Джерело", "Sursă", "Fonte", "Origen", "Origem",
                         "Origem", "来源"),
    "setup_none": (
        "No record of how the box was connected in this period.",
        "Erre az időszakra nincs feljegyzés a bekötésről.",
        "Für diesen Zeitraum ist nicht aufgezeichnet, wie die Box angeschlossen war.",
        "Aucun enregistrement du raccordement pour cette période.",
        "Для цього періоду немає запису про підключення пристрою.",
        "Pentru această perioadă nu există o înregistrare a conectării.",
        "Per questo periodo non c'è registrazione del collegamento.",
        "No hay registro de la conexión en este periodo.",
        "Não há registo da ligação neste período.",
        "Não há registro da conexão neste período.",
        "此期间没有设备接入方式的记录。"),
    "setup_unknown": ("unknown", "ismeretlen", "unbekannt", "inconnu", "невідомо", "necunoscut", "sconosciuto",
                      "desconocido", "desconhecido", "desconhecido", "未知"),
    "setup_warn_behind": (
        "Measured behind another router: that router may limit the speed and add delay or loss, and the ISP can "
        "point to it.",
        "Másik router mögött mérve: az a router korlátozhatja a sebességet, és késleltetést vagy csomagvesztést "
        "okozhat; a szolgáltató hivatkozhat rá.",
        "Hinter einem anderen Router gemessen: dieser Router kann die Geschwindigkeit begrenzen und Verzögerung oder "
        "Verluste verursachen; der Anbieter kann darauf verweisen.",
        "Mesuré derrière un autre routeur : ce routeur peut limiter le débit et ajouter du délai ou des pertes ; le "
        "fournisseur peut s'y référer.",
        "Виміряно за іншим роутером: цей роутер може обмежувати швидкість і додавати затримку чи втрати; провайдер "
        "може на це посилатися.",
        "Măsurat în spatele altui router: acel router poate limita viteza și poate adăuga întârziere sau pierderi; "
        "furnizorul poate invoca acest lucru.",
        "Misurato dietro un altro router: quel router può limitare la velocità e aggiungere ritardo o perdite; il "
        "fornitore può farvi riferimento.",
        "Medido detrás de otro router: ese router puede limitar la velocidad y añadir retardo o pérdidas; el "
        "proveedor puede alegarlo.",
        "Medido atrás de outro router: esse router pode limitar a velocidade e acrescentar atraso ou perdas; o "
        "fornecedor pode invocá-lo.",
        "Medido atrás de outro roteador: esse roteador pode limitar a velocidade e acrescentar atraso ou perdas; a "
        "operadora pode alegar isso.",
        "在另一台路由器后面测量：该路由器可能限制速度并增加延迟或丢包；运营商可能以此为由。"),
    "setup_mixed": (
        "The setup changed during this period; see the table.",
        "Az időszak alatt változott a bekötés; lásd a táblázatot.",
        "Der Aufbau hat sich in diesem Zeitraum geändert; siehe Tabelle.",
        "Le raccordement a changé pendant cette période ; voir le tableau.",
        "Підключення змінювалося протягом періоду; див. таблицю.",
        "Conectarea s-a schimbat în această perioadă; vezi tabelul.",
        "Il collegamento è cambiato in questo periodo; vedi la tabella.",
        "La conexión cambió en este periodo; vea la tabla.",
        "A ligação mudou neste período; veja a tabela.",
        "A conexão mudou neste período; veja a tabela.",
        "此期间接入方式有变化；见表格。"),
    "setup_partly_unknown": (
        "not known for part of the period", "az időszak egy részére nem ismert",
        "für einen Teil des Zeitraums nicht bekannt", "inconnu pour une partie de la période",
        "для частини періоду невідомо", "necunoscut pentru o parte a perioadei",
        "non noto per parte del periodo", "desconocido durante parte del periodo",
        "desconhecido em parte do período", "desconhecido em parte do período", "部分时段未知"),
    "setup_mode_standalone": (
        "Standalone (client on an existing network)", "Önálló (kliens egy meglévő hálózaton)",
        "Eigenständig (Client in einem bestehenden Netz)", "Autonome (client d'un réseau existant)",
        "Автономний (клієнт у наявній мережі)", "Autonom (client într-o rețea existentă)",
        "Autonomo (client in una rete esistente)", "Independiente (cliente en una red existente)",
        "Autónomo (cliente numa rede existente)", "Independente (cliente em uma rede existente)",
        "独立（现有网络中的客户端）"),
    "setup_mode_mode_a": ("Router mode", "Router mód", "Routermodus", "Mode routeur", "Режим роутера", "Mod router",
                          "Modalità router", "Modo router", "Modo router", "Modo roteador", "路由模式"),
    "setup_mode_mode_b": ("Transparent bridge", "Átlátszó híd", "Transparente Bridge", "Pont transparent",
                          "Прозорий міст", "Punte transparentă", "Bridge trasparente", "Puente transparente",
                          "Ponte transparente", "Ponte transparente", "透明网桥"),
    "setup_short_standalone": ("Standalone", "Önálló", "Eigenständig", "Autonome", "Автономний", "Autonom", "Autonomo",
                               "Independiente", "Autónomo", "Independente", "独立"),
    "setup_short_mode_a": ("Router", "Router", "Router", "Routeur", "Роутер", "Router", "Router", "Router", "Router",
                           "Roteador", "路由"),
    "setup_short_mode_b": ("Bridge", "Híd", "Bridge", "Pont", "Міст", "Punte", "Bridge", "Puente", "Ponte", "Ponte",
                           "网桥"),
    "setup_link_ethernet": ("Ethernet", "Ethernet", "Ethernet", "Ethernet", "Ethernet", "Ethernet", "Ethernet",
                            "Ethernet", "Ethernet", "Ethernet", "以太网"),
    "setup_link_pppoe": ("PPPoE", "PPPoE", "PPPoE", "PPPoE", "PPPoE", "PPPoE", "PPPoE", "PPPoE", "PPPoE", "PPPoE",
                         "PPPoE"),
    "setup_link_wifi": ("Wi-Fi client", "Wi-Fi kliens", "WLAN-Client", "Client Wi-Fi", "Wi-Fi клієнт", "Client Wi-Fi",
                        "Client Wi-Fi", "Cliente Wi-Fi", "Cliente Wi-Fi", "Cliente Wi-Fi", "Wi-Fi 客户端"),
    "setup_link_usb": ("USB tethering (mobile)", "USB-megosztás (mobil)", "USB-Tethering (mobil)", "Partage USB (mobile)",
                       "USB-модем (мобільний)", "Tethering USB (mobil)", "Tethering USB (mobile)",
                       "Anclaje USB (móvil)", "Partilha USB (móvel)", "Ancoragem USB (celular)", "USB 共享网络（移动）"),
    "setup_link_bridge": ("Inline bridge", "Soros híd", "Inline-Bridge", "Pont en ligne", "Прохідний міст",
                          "Punte în linie", "Bridge in linea", "Puente en línea", "Ponte em linha", "Ponte em linha",
                          "串联网桥"),
    "setup_link_passthrough": (
        "Ethernet with LAN passthrough", "Ethernet LAN-átjárással", "Ethernet mit LAN-Durchleitung",
        "Ethernet avec passage LAN", "Ethernet з пропуском LAN", "Ethernet cu trecere LAN",
        "Ethernet con passthrough LAN", "Ethernet con paso LAN", "Ethernet com passagem LAN",
        "Ethernet com passagem LAN", "带 LAN 直通的以太网"),
    "setup_link_lag": ("Link aggregation", "Linkaggregáció", "Link-Aggregation", "Agrégation de liens",
                       "Агрегація каналів", "Agregare de legături", "Aggregazione di link", "Agregación de enlaces",
                       "Agregação de ligações", "Agregação de links", "链路聚合"),
    "setup_path_direct_pppoe": (
        "Direct to the ISP (own PPPoE session)", "Közvetlenül a szolgáltatón (saját PPPoE-kapcsolat)",
        "Direkt am Anbieter (eigene PPPoE-Sitzung)", "Directement chez le fournisseur (session PPPoE propre)",
        "Напряму до провайдера (власний сеанс PPPoE)", "Direct la furnizor (sesiune PPPoE proprie)",
        "Direttamente al fornitore (sessione PPPoE propria)", "Directo al proveedor (sesión PPPoE propia)",
        "Direto ao fornecedor (sessão PPPoE própria)", "Direto na operadora (sessão PPPoE própria)",
        "直连运营商（自己的 PPPoE 会话）"),
    "setup_path_direct_public": (
        "Direct to the ISP (public address)", "Közvetlenül a szolgáltatón (nyilvános cím)",
        "Direkt am Anbieter (öffentliche Adresse)", "Directement chez le fournisseur (adresse publique)",
        "Напряму до провайдера (публічна адреса)", "Direct la furnizor (adresă publică)",
        "Direttamente al fornitore (indirizzo pubblico)", "Directo al proveedor (dirección pública)",
        "Direto ao fornecedor (endereço público)", "Direto na operadora (endereço público)", "直连运营商（公网地址）"),
    "setup_path_direct_cgnat": (
        "Direct to the ISP (carrier-grade NAT address)", "Közvetlenül a szolgáltatón (szolgáltatói NAT-os cím)",
        "Direkt am Anbieter (Carrier-Grade-NAT-Adresse)", "Directement chez le fournisseur (adresse de NAT opérateur)",
        "Напряму до провайдера (адреса CGNAT)", "Direct la furnizor (adresă CGNAT)",
        "Direttamente al fornitore (indirizzo CGNAT)", "Directo al proveedor (dirección CGNAT)",
        "Direto ao fornecedor (endereço CGNAT)", "Direto na operadora (endereço CGNAT)", "直连运营商（CGNAT 地址）"),
    "setup_path_behind_router": (
        "Behind another router (private address)", "Másik router mögött (privát cím)",
        "Hinter einem anderen Router (private Adresse)", "Derrière un autre routeur (adresse privée)",
        "За іншим роутером (приватна адреса)", "În spatele altui router (adresă privată)",
        "Dietro un altro router (indirizzo privato)", "Detrás de otro router (dirección privada)",
        "Atrás de outro router (endereço privado)", "Atrás de outro roteador (endereço privado)",
        "在另一台路由器后面（私有地址）"),
    "setup_short_direct": ("direct to the ISP", "közvetlenül a szolgáltatón", "direkt am Anbieter",
                           "direct chez le fournisseur", "напряму до провайдера", "direct la furnizor",
                           "diretto al fornitore", "directo al proveedor", "direto ao fornecedor",
                           "direto na operadora", "直连运营商"),
    "setup_short_behind_router": ("behind another router", "másik router mögött", "hinter einem anderen Router",
                                  "derrière un autre routeur", "за іншим роутером", "în spatele altui router",
                                  "dietro un altro router", "detrás de otro router", "atrás de outro router",
                                  "atrás de outro roteador", "在另一台路由器后面"),
    "setup_src_recorded": ("recorded", "rögzítve", "aufgezeichnet", "enregistré", "записано", "înregistrat",
                           "registrato", "registrado", "registado", "registrado", "已记录"),
    "setup_src_changed": ("changed during the test", "mérés közben megváltozott", "während der Messung geändert",
                          "modifié pendant le test", "змінилося під час тесту", "schimbat în timpul testului",
                          "cambiato durante il test", "cambió durante la prueba", "mudou durante o teste",
                          "mudou durante o teste", "测试期间发生变化"),
    "setup_src_derived": ("reconstructed from the event log", "eseménynaplóból visszaállítva",
                          "aus dem Ereignisprotokoll rekonstruiert", "reconstitué depuis le journal",
                          "відновлено з журналу подій", "reconstituit din jurnal", "ricostruito dal registro",
                          "reconstruido del registro", "reconstruído a partir do registo", "reconstruído pelo registro",
                          "根据事件日志重建"),
}

TEXTS: Dict[str, Dict[str, str]] = {lang: {k: _T[k][i] for k in _KEYS} for i, lang in enumerate(LANGUAGES)}


def _lang(lang: Optional[str]) -> str:
    code = (lang or "en").lower().replace("_", "-")
    return code if code in TEXTS else "en"


def texts(lang: Optional[str]) -> Dict[str, str]:
    """Every setup text in one language (English for an unknown language)."""
    return dict(TEXTS[_lang(lang)])


def mode_label(code: Optional[str], lang: Optional[str], short: bool = False) -> str:
    t = TEXTS[_lang(lang)]
    if code not in MODES:
        return t["setup_unknown"]
    return t[f"setup_short_{code}" if short else f"setup_mode_{code}"]


def link_label(code: Optional[str], lang: Optional[str]) -> str:
    t = TEXTS[_lang(lang)]
    return t[f"setup_link_{code}"] if code in UPLINK_KINDS else t["setup_unknown"]


def path_label(code: Optional[str], lang: Optional[str], short: bool = False) -> str:
    t = TEXTS[_lang(lang)]
    if code not in ISP_PATHS:
        return t["setup_unknown"]
    if short:
        return t["setup_short_behind_router" if code == "behind_router" else "setup_short_direct"]
    return t[f"setup_path_{code}"]


def source_label(code: Optional[str], lang: Optional[str]) -> str:
    t = TEXTS[_lang(lang)]
    return t[f"setup_src_{code}"] if code in SOURCES else t["setup_unknown"]


def summary(row: Dict[str, Any], lang: Optional[str], short: bool = True) -> str:
    """"Router · PPPoE · direct to the ISP"; each unknown part says so. Plain text (escape it for HTML)."""
    mode, kind, path, _ = label_codes(row)
    if mode is None and kind is None and path is None:
        return TEXTS[_lang(lang)]["setup_unknown"]
    return " · ".join((mode_label(mode, lang, short=short), link_label(kind, lang), path_label(path, lang, short=short)))
