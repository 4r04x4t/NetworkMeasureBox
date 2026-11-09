# NetworkMeasureBox (NMB) — Részletes Rendszerdokumentáció

> **Autonóm hálózatminőség-mérő és SLA-riport szoftver Linuxra, opcionális router és híd móddal. Raspberry Pi 4-en fejlesztve és futtatva.**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Platform: Linux](https://img.shields.io/badge/Fejleszt%C3%A9si%20platform-Raspberry%20Pi%204-green.svg)](https://kernel.org)
[![Python: 3.9+](https://img.shields.io/badge/Python-3.9%2B%20%28Zero%20External%20Pip%20Deps%29-yellow.svg)](https://python.org)
[![VPN: WireGuard & Tailscale](https://img.shields.io/badge/VPN-WireGuard%20%7C%20OpenVPN%20%7C%20Tailscale-blueviolet.svg)](#10-univerzális-távoli-elérés-pivpn-hub-és-tailscale-mesh)
[![Router portok: tervezett](https://img.shields.io/badge/Router%20portok-Tervezett%2C%20nincs%20k%C3%A9sz-lightgrey.svg)](#17-100-os-de-pythonizáció-és-kereskedelmi-router-portolási-terv)
[![Languages: EN HU DE UK FR](https://img.shields.io/badge/Languages-EN%20%7C%20HU%20%7C%20DE%20%7C%20UK%20%7C%20FR-orange.svg)](#8-beépített-webes-felület-webgui-és-többnyelvűség)

---

## Tartalomjegyzék

1. [Mi ez az egész? (A projekt célja és küldetése)](#1-mi-ez-az-egész-a-projekt-célja-és-küldetése)
2. [Főbb Képességek és Funkciók](#2-főbb-képességek-és-funkciók)
3. [Rendszerarchitektúra és Működési Módok (Mode A / Mode B)](#3-rendszerarchitektúra-és-működési-módok)
4. [Több Hálózati Kártya, Port Mátrix és Driver Támogatás (Multi-NIC / Multi-WAN / Multi-LAN)](#4-több-hálózati-kártya-port-mátrix-és-driver-támogatás)
5. [Mérési Motorok és Metrikák](#5-mérési-motorok-és-metrikák)
6. [Alacsony Memóriájú és Beágyazott Architektúra (512 MB RAM Optimalizáció)](#6-alacsony-memóriájú-és-beágyazott-architektúra-512-mb-ram-optimalizáció)
7. [Hardver- és Flash-Védelem (microSD Longevity)](#7-hardver--és-flash-védelem-microsd-longevity)
8. [Beépített Webes Felület (WebGUI) és Többnyelvűség](#8-beépített-webes-felület-webgui-és-többnyelvűség)
9. [Hálózatfelderítő (Device Explorer) & Vendég Wi-Fi Kliens Szonda](#9-hálózatfelderítő-device-explorer--vendég-wi-fi-kliens-szonda)
10. [Univerzális Távoli Elérés, PiVPN Hub és Tailscale Mesh](#10-univerzális-távoli-elérés-pivpn-hub-és-tailscale-mesh)
11. [Beépített DNS Reklámblokkoló és Adatvédelmi Pajzs (Pi-hole Alternatíva)](#11-beépített-dns-reklámblokkoló-és-adatvédelmi-pajzs-pi-hole-alternatíva)
12. [Haladó Törvényszéki Diagnosztika és Kiváltó Ok Elemzés](#12-haladó-törvényszéki-diagnosztika-és-kiváltó-ok-elemzés)
13. [Többnyelvű Telegram Bot Érintőmenüvel és QR Kóddal](#13-többnyelvű-telegram-bot-érintőmenüvel-és-qr-kóddal)
14. [SLA Dosszié és Vektoros SVG Motor](#14-sla-dosszié-és-vektoros-svg-motor)
15. [Valós Idejű Folyamatkezelő (Beágyazott htop Motor)](#15-valós-idejű-folyamatkezelő-beágyazott-htop-motor)
16. [Önjavító Watchdog és Biztonsági Visszaállás (nmb-heal)](#16-önjavító-watchdog-és-biztonsági-visszaállás-nmb-heal)
    * [Központi Mérésgyűjtő (nmb-collector)](#16b-központi-mérésgyűjtő-nmb-collector)
17. [100%-os De-Pythonizáció és Kereskedelmi Router Portolási Terv](#17-100-os-de-pythonizáció-és-kereskedelmi-router-portolási-terv)
18. [Parancssori Eszközök (CLI) és Szolgáltatások](#18-parancssori-eszközök-cli-és-szolgáltatások)
19. [Interaktív Telegram Távvezérlő Parancsok](#19-interaktív-telegram-távvezérlő-parancsok)
20. [Telepítés és Beüzemelés (Quickstart)](#20-telepítés-és-beüzemelés-quickstart)

---

## 1. Mi ez az egész? (A projekt célja és küldetése)

A **NetworkMeasureBox (NMB)** egy olyan nyílt forráskódú, professzionális, folyamatosan futó célszoftver és hardver-illesztő réteg, amely véget vet az internetszolgáltatókkal (ISP) folytatott szubjektív vitáknak.

### A probléma
Amikor egy internetkapcsolat akadozik, csomagokat veszít, késleltetési tüskékkel küzd, vagy az esti órákban a szerződésben vállalt garantált sávszélesség töredékére zuhan, a szolgáltatói ügyfélszolgálat reakciója szinte kivétel nélkül:
> *"Nálunk a vonal rendben van, a hiba biztosan az Ön belső hálózatában, a routerében vagy a Wi-Fi-jében keresendő."*

Egyedi, manuálisan futtatott böngészős sebességtesztekkel a felhasználó tehetetlen: nincs folyamatos audit napló, nem látható a mikroszakadások időpontja, és nem bizonyítható a szolgáltató felé a szerződésszegés vagy a forgalomkorlátozás (net-neutrality throttling).

### A megoldás
A NetworkMeasureBox egy olcsó, energiatakarékos céleszközön (jelenleg Raspberry Pi 4-en fejlesztve és futtatva) a nap 24 órájában, az év 365 napján automatikusan felügyeli és dokumentálja az internetkapcsolatot:
1. **Objektív bizonyítékot gyűjt**: Rögzíti az összes késleltetést, mikroszakadást, jittert és sávszélesség-ingadozást.
2. **A hálózat szélén mér**: Futhat a router mögött (`standalone`), routerként (Mode A), vagy transzparens hídként (Mode B) a modem és a router között. Csak a rajta áthaladó forgalmat látja, ezért a bekötés befolyásolja, mit tud mérni.
3. **Nem zavarja a felhasználót**: A beépített forgalmi kapu (Traffic Gate) csak akkor indít nagy sávszélességű tesztet, ha a doboz által látható forgalom a küszöb alatt van. Hogy mit lát, az a bekötéstől függ. Kísérleti, alapból kikapcsolt funkcióként a futó mérés is leállítható (lásd: Leállás hálózati forgalomra).
4. **SLA dossziét generál**: Egyetlen gombnyomással önállóan megnyitható HTML jelentést állít elő beágyazott vektoros SVG diagramokkal és az előfizetői szerződéshez viszonyított SLA-megfelelőségi táblázattal, amelyet közvetlenül be lehet nyújtani hibajegyként a szolgáltatónak, vagy vita esetén az illetékes hírközlési hatóságnak.

---

## 2. Főbb Képességek és Funkciók

* **Zéró Külső Python Függőség (Zero Pip Dependencies)**: A teljes kód kizárólag a Python 3 szabványos könyvtáraira (`sqlite3`, `http.server`, `urllib`, `socket`, `ctypes`) és natív Linux segédprogramokra épül. Nincs szükség `pip install`-ra, így korlátozott beágyazott rendszereken is azonnal indul.
* **Kettős Működési Mód**:
  * **Automatikus (`mode = auto`, új telepítésnél ez az alapértelmezett)**: ha egy router DHCP-n címet ad a doboznak: **standalone** (több vezetékes portnál a többi port hídba kerül vele, LAN passthrough, majdnem mint egy switch). Ha 90 másodpercig nincs router és internet (a kábel ONT-n vagy modemen, PC-n van, vagy nincs kábel): **router mód**, amíg router nem válaszol újra; mentett belépés és válaszoló PPPoE-szerver esetén PPPoE-vel tárcsáz, egyébként a Wi-Fi hozzáférési ponttal és a LAN portokkal elérhető a beállításhoz. Ha router jelenik meg a WAN porton: azonnal standalone. Rögzített mód, kézi felülbírálás vagy a tulajdonos saját passthrough/aggregációs beállítása mindig erősebb. Szabályok: `nmb/netd/auto_mode.py`. Egységtesztekkel ellenőrizve; élesben még nincs tesztelve.
  * **Mode A (Aktív Router / Gateway)**: Teljes értékű router PPPoE tárcsázással, VLAN tageléssel, NAT masquerade-del, DHCP kiszolgálóval (`dnsmasq`).
  * **Mode B (Transzparens Híd / Inline Bridge)**: Két fizikai interfész közötti Layer 2 híd (`br0`). A doboz DHCP-vel saját címet kér a méréshez, így a szolgáltatói oldalnak ezt biztosítania kell. Ha a doboz leáll, megszakad a kapcsolat.
* **LAN Passthrough és Link Aggregation** (routerhez csatlakoztatott, önálló mérőeszköz; WebGUI: Portok és Illesztőprogramok):
  * **Passthrough**: a kiválasztott portok 2. rétegben az uplinkre hidalódnak, így a doboz mögötti eszközök a router alhálózatán maradnak.
  * **Link aggregation**: két vagy több vezetékes port vagy kártya bejelölhető és `bond0`-ba vonható össze (802.3ad LACP, balance-rr, balance-xor, balance-tlb, balance-alb, active-backup), passthrough-val vagy anélkül.
  * A 802.3ad-hez LACP kell a routeren vagy switchen; a balance-rr és a balance-xor statikus LAG-et igényel. A balance-rr kivételével egy TCP-kapcsolat egy linken marad, így az összesített sebesség többszálú méréssel jelenik meg.
* **Több Hálózati Kártya és Port Kezelése (Multi-NIC Matrix)**:
  * Tetszőleges számú fizikai hálózati kártya (PCIe, USB, alaplapi) kezelése.
  * **Multi-WAN**: Elsődleges WAN és Másodlagos WAN (WAN2) támogatás failover (tartalék) vagy loadbalance (terheléselosztás) módban.
  * **Multi-LAN Híd (`br-lan`)**: Több fizikai LAN port automatikus összefogása egységes Linux hálózati híddá.
  * DMZ-port, Vendég Wi-Fi szonda és interfész-specifikus sebességmérés.
* **Automatikus Driver- és Firmware-Kezelés**:
  * Hardveres vezérlőfelismerés (Realtek, Intel, Broadcom, MediaTek, Qualcomm Atheros, Aquantia, ASIX stb.).
  * Kernel `dmesg` figyelése hiányzó firmware-ek azonnali észleléséhez.
  * Egykattintásos driver/firmware telepítő (Debian `apt`, OpenWrt `opkg`, Alpine `apk`, Arch `pacman`, Fedora `dnf`) élő terminálablakkal a WebGUI-ban.
* **Sebességmérő Motorok és Ellenőrzések**:
  1. **Ookla Speedtest CLI**: Hivatalos Ookla mérőmotor automatikus szerverválasztással vagy testreszabott szerverazonosítóval.
     * **Figyelem**: az Ookla korlátozza, milyen gyakran mérhet egy eszköz: néhány percenkénti mérésnél hamar elutasítja a boxot („Limit reached”), és egy időre letiltja. Ezért az ütemezett Ookla-mérés legfeljebb óránként egyszer fut, akármilyen sűrű az ütemezés; az RTR-NetTest, a Cloudflare és az iPerf3 minden alkalommal fut, a kézi Ookla-mérés pedig kérésre azonnal. Ha az Ookla mégis elutasít, a box szünetelteti az Ooklát (30 perc, duplázódva legfeljebb 4 óráig, újraindítás után is), és nem tesz a helyére más motor eredményét. A webes felület mutatja az óránkénti korlátot és a szünetet.
     * **Miért legfeljebb óránként (`ookla_interval_min`, legalább 60):** az Ookla az ingyenes Speedtest CLI-t csak személyes használatra engedi, és korlátozza, milyen gyakran mérhet egy nyilvános IP-cím. Ha ezt eléri, „Limit reached: Too many requests received” választ ad, és minden további próbálkozás, az elutasított is, fenntartja a tiltást. A tesztvonalon a box eleinte órákon át percenként mért gond nélkül (2026. november 4.); napokig tartó sűrű mérés után az Ookla letiltotta a vonal címét, és a tiltás minden óránkénti próbánál megmaradt. Az új cím ötlete a box tulajdonosától jött: a főrouter (GL.iNet Flint 4) újraindítása után a vonal új nyilvános IP-t kapott, és a legelső Ookla-mérés azonnal sikerült (934/325 Mbps, 2026. november 8.). A tiltás tehát a nyilvános IP-n van, nem a boxon vagy a beállításain, és minden eszközre vonatkozik, amely e cím mögött van. Ezért az ütemezett mérés legfeljebb óránként fut; elutasítás után a box szünetelteti az Ooklát (30 perc, duplázódva legfeljebb 4 óráig, újraindítás után is) ahelyett, hogy újra próbálkozna, és nem tesz a helyére más motor eredményét. Az NMB magától nem cserél IP-címet a tiltás megkerülésére. A kézi mérést a box nem fogja vissza, ezért azzal takarékosan bánj; a szerverlista frissítése is Ookla-kérésnek számít.
  2. **Cloudflare Speed Engine**: Időalapú, 4 szálas le- és feltöltés a Cloudflare felé (gigabites vonalon futásonként kb. 1,2 GB).
  3. **Fast.com (Netflix)**: Beépítve, tisztán Pythonban (nem kell hozzá Node, Go vagy böngésző), a Fast.com saját API-jával, ahogy a `gesquive/fast-cli` és a `sindresorhus/fast-cli` is. Részletek lent, a Fast.com motornál.
  4. **RTR-Netztest (RMBT)**: Az Osztrák Szabályozó Hatóság (RTR) és az európai BEREC szabványos RMBT mérőmotorja.
  5. **iPerf3 Kliens és Szerver**: Helyi és távoli iPerf3 audit TCP/UDP protokollal, állítható szálakkal. Az eredmények, a statisztika és a CSV néven nevezik a szervert (hely és szolgáltató a nyilvános iPerf3-listából; ha csak a címe ismert, a GeoIP szerinti város, ország és ISP), a régi, csak címet tároló soroknál is.
  6. **Portfojtás-Ellenőrző**: TCP-átvitel összehasonlítása gyakori portokon (alapból 80, 443, 8080, 8443, 53, SSH 22, SIP 5060 és BitTorrent 6881) egy 443-as alapértékkel. Különbséget mutathat, de nem bizonyítja, hogy a szolgáltató okozta.
* **Sub-second ICMP Ping Szonda (`nmb-probe`)**: 500 ms-os folyamatos mintavételezés, RFC 3550 jitter számítás, p95/p99 késleltetés, az átjáró és nyilvános célpontok (alapból 1.1.1.1, 8.8.8.8, 9.9.9.9, 185.222.222.222) és kimaradási ablakok naplózása.
* **Alacsony memóriás profilok (512 MB-on nincs tesztelve)**: Dinamikus memóriaprofilok (`low`, `standard`, `performance`), szigorú SQLite live méretkorlátok (48 MB), periodikus és kézi `malloc_trim(0)` memóriafelszabadítás router platformokon.
* **Flash- és SD-Kártya Élettartam Védelem**: Élő adatbázis memóriában futó tmpfs-en, 15 percenkénti és leállításkori atomi pillanatképek SD-re, ext4 `noatime,commit=600`.
* **Hálózatfelderítő (Device Explorer)**: Beépített ARP sweep és MAC OUI vendor felismerés (Apple, Samsung, Intel, Xiaomi stb.) a helyi és a vendéghálózaton.
* **Dedikált Vendég Wi-Fi Kliens Szonda**: Másodlagos vezeték nélküli interfésszel automatikusan felkapcsolódik a router vendég Wi-Fi hálózatára, és ellenőrzi annak sávszélességét, stabilitását és izolációját.
* **Tárhelyőr** (`[storage]`, alapból bekapcsolva): az `nmb-netd` 10 percenként ellenőrzi a lemezt, és a mérete szerinti részt tartja szabadon (2 GB-ig 15%, 16 GB-ig 10%, fölötte 5%; legalább 200 MB, legfeljebb 2 GB; a `min_free_mb` felülírja). Ha ennél kevesebb a szabad hely, a legrégebbivel kezdve töröl: elforgatott naplók, diagnosztikai csomagok és összeomlás-jelentések; a frissítési mentések a legújabb kivételével; régi jelentések; a rendszernapló 32 MB-ig; a nagy aktív NMB-naplók; és csak legvégül mérések, naponként, az utolsó `keep_days` (7) napot megtartva. A törölt mérésekről esemény készül. A `setup.sh` megáll, ha 500 MB-nál kevesebb a szabad hely, és 8 GB alatti lemezen kisebb naplókat használ.
* **Mérés Wi-Fi-n**: A box a saját Wi-Fi-hálózatodra is csatlakozhat, hogy azon mérjen (`[wifi_uplink]`: `ssid`, `password`, `interface`, `hidden`, `enabled`; saját NetworkManager-profil, `nmb-uplink`, a vendégklienstől külön). A `[network] measurement_link` adja meg, hol fut a sebességmérés: `auto` (Etherneten, ha van kábel, különben Wi-Fi-n), `ethernet` vagy `wifi`. Ha a kábel és a Wi-Fi is él, az alapútvonal az Etherneten marad, és egy forrásszabály (150-es tábla) gondoskodik róla, hogy a Wi-Fi-hez kötött mérés tényleg Wi-Fi-n menjen ki. A webes felületen az ütemezés alatt, vagy `nmb-cli run wifi.uplink` paranccsal állítható. NetworkManager kell hozzá. Minden vezeték nélküli interfész szerepe a Portok és driverek alatt választható: 📶 *Vendég Wi-Fi-kliens* vagy 📡 *Fő Wi-Fi-kliens (mérés)*; egy interfész nem lehet egyszerre mindkettő, és `interface = auto` esetén a fő kliens kihagyja a bekapcsolt vendégkliens rádióját.
* **Beállítások USB pendrive-ról**: egy `nmb.conf` fájl a pendrive gyökerében, csak a módosítandó kulcsokkal (például Wi-Fi jelszó, Telegram token, PPPoE belépés); bedugva a doboz egyszer alkalmazza, a régi beállításokról mentést készít, beállított titkot üres értékkel soha nem töröl, és `nmb-import-result.txt` fájlt ír vissza a pendrive-ra (csak nevekkel). Minta: `config/usb-import.example.conf`; kikapcsolás: `[usb_import] enabled = false`. Valódi pendrive-val még nincs tesztelve.
* **USB tethering** (`[usb_uplink]`, alapból kikapcsolva): az USB-re dugott telefont, mobil hotspotot (például Netgear Nighthawk) vagy mobilmodemet a drivere alapján ismeri fel (`rndis_host`, `cdc_ncm`, `cdc_ether`, `ipheth`, `qmi_wwan`, `cdc_mbim`), és soha nem tekinti vezetékes vonalnak. Bekapcsolva saját NetworkManager-profilt kap (`nmb-usb-uplink`), címmel, de soha nem az alapértelmezett útvonallal, így a doboz forgalma és a kiesésmérő a kábelen marad; a `measurement_link = usb` (vagy egy erre az interfészre kért kézi mérés) egy forrásszabályon (152-es tábla) át rajta mér. Teszt állapot egy Netgear Nighthawk M6 Pro (amerikai AT&T-modell, 5G) eszközzel a Raspberry Pi 4-en: a felismerés és az USB-n át végzett mérés működik; a doboz saját átállása USB-re egyszer működött (kábel kihúzva a routerből); **router módban az USB internetet egy kábeles laptopnak és egy, a doboz Wi-Fi-jén lévő kliensnek (2,4 GHz, 802.11n) élő teszten megosztotta 2026-11-08-án**, aznapi két javítás után; a Wi-Fi megosztás a LAN porton USB-n át még nincs igazolva. Részletek: docs/TESTING.hu.md. **Ha ez az egyetlen internet** (nincs vezetékes vagy Wi-Fi alapértelmezett útvonal), a doboz magától ezt használja (900-as metrikájú alapértelmezett útvonal, ami eltűnik, amint visszajön a kábel vagy a Wi-Fi; minden váltás esemény). **Router módban (Mode A)**, ha az Ethernet-porton nem válaszol DHCP-szerver, az USB lesz a WAN, és az egyetlen Ethernet-port meg a Wi-Fi hozzáférési pont osztja tovább a mobilnetet; ha a porton DHCP-szerver jelenik meg, a doboz azonnal leállítja a saját DHCP-jét. A LAN-porti megosztás (`[wifi_share]`) is tudja az USB-t forrásként használni. Az USB-n mért eredmények mobilként (`fwa`) kerülnek be; az USB-s méréseknek saját napi adatkorlátjuk van (`daily_limit_mb`, alapból 1024 MB, 0 = nincs). Webes kártya, `nmb-cli run usb.uplink ...`, mind a 11 nyelven.
* **Wi-Fi megosztása LAN porton** (`[wifi_share]`, alapból kikapcsolva): ha a box Wi-Fi-n van, és egy vezetékes portjának nincs saját internetje, a portra dugott eszközök a boxtól kapnak címet (alapból `address = 192.168.77.1/24`, DHCP .100–.200, a Wi-Fi DNS-szerverei), és a box Wi-Fi-jén érik el az internetet (NAT, saját 151-es útválasztási tábla). A box soha nem oszt címet olyan hálózatban, ahol saját DHCP van: indulás előtt, futás közben percenként és kábel bedugásakor azonnal (előbb a saját DHCP-jét leállítva) DHCP-kérést küld a porton, és leáll, ha bármely más szerver válaszol, vagy a port alapútvonalat kap. A válaszokat csomagszinten olvassa, így a box tűzfala nem rejtheti el őket. A webes felületen az ütemezés alatt, vagy `nmb-cli run wifi.share enabled=true lan_interface=eth0`.
* **Többnyelvű Reszponzív WebGUI**: Sötét módú irányítópult, több fül és alfül, valós idejű SVG diagramok, jelszavas védelem, Logout funkció és azonos kulcskészletű fordítás 11 nyelven (magyar, angol, német, ukrán, francia, román, olasz, spanyol, európai és brazil portugál, egyszerűsített kínai); a Telegram bot is mind a 11 nyelvet beszéli (menük, válaszok, admin-válaszok, riasztások).
* **Telegram Távfelügyelet**: Valós idejű push riasztások szakadás vagy >5% csomagvesztés esetén, távoli parancsok (`/status`, `/ping`, `/test`, `/report`, `/mode`).

---

## 3. Rendszerarchitektúra és Működési Módok

```
                               ┌────────────────────────────────────────────────────────┐
                               │                    ISP Edge (Modem/ONT)                │
                               └───────────────────────────┬────────────────────────────┘
                                                           │
                                                           ▼
┌──────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│ NetworkMeasureBox Céleszköz (SBC, x86 mini PC, beágyazott router)                                                │
│                                                                                                                  │
│  ┌──────────────────────────────────────────────┐          ┌──────────────────────────────────────────────────┐  │
│  │ Kettős Hálózati Démon (nmb-netd)             │          │ Nagyfrekvenciás ICMP Szonda (nmb-probe)          │  │
│  │ • Mode A: Router (PPPoE/NAT/hostapd/dnsmasq) │          │ • 500 ms-os mintavételezés                       │  │
│  │ • Mode B: Passzív Transzparens Híd (br0)     │          │ • RFC 3550 jitter & többcélú veszteségmérés      │  │
│  │ • Multi-WAN failover & Multi-LAN br-lan híd  │          │ • Szakadási és kimaradási ablakok auditálása     │  │
│  └──────────────────────┬───────────────────────┘          └────────────────────────┬─────────────────────────┘  │
│                         │                                                           │                            │
│                         ▼                                                           ▼                            │
│  ┌──────────────────────────────────────────────┐          ┌──────────────────────────────────────────────────┐  │
│  │ Forgalomfüggő Sebességmérő (nmb-speed)       │          │ Elemző és Dosszié-Generátor (nmb-report)         │  │
│  │ • /proc/net/dev üresjárati kapu (küszöbbel) │          │ • Önmagában álló HTML jelentés vektoros SVG-vel  │  │
│  │ • Motorok: Ookla, Cloudflare, Fast.com, RTR,  │          │ • RFC 4180 CSV telemetria exportáló              │  │
│  │ • Net-neutrality portfojtás-ellenőrző        │          │ • Automatikus SMTP hibajegy-továbbítás           │  │
│  └──────────────────────┬───────────────────────┘          └────────────────────────┬─────────────────────────┘  │
│                         │                                                           │                            │
│                         ▼                                                           ▼                            │
│  ┌────────────────────────────────────────────────────────────────────────────────────────────────────────────┐  │
│  │ Memória- és Flash-Optimalizált Tároló Réteg                                                                │  │
│  │ • Forró SQLite WAL adatbázis RAM-ban (tmpfs: /var/lib/nmb/live/nmb.db)                                     │  │
│  │ • Atomi online pillanatképek SD-re (/var/lib/nmb/persist/nmb.db) 15 percenként és leállításkor             │  │
│  │ • 512 MB RAM beágyazott profil: 48MB DB limit, malloc_trim(0) heap felszabadítás, ext4 commit=600         │  │
│  └────────────────────────────────────────────────────────────────────────────────────────────────────────────┘  │
│                                                                                                                  │
│  ┌──────────────────────────────────────────────┐          ┌──────────────────────────────────────────────────┐  │
│  │ Telegram Távfelügyeleti Bot (nmb-telegram)   │          │ Beépített Kezelő WebGUI & REST API (nmb-web)     │  │
│  │ • /status, /ping, /test, /report, /mode      │          │ • Szabványos router port 80 felület (dev 8080)   │  │
│  │ • Azonnali push riasztások kimaradáskor      │          │ • 14+ alrendszer, 11 nyelvű fordítás, Logout    │  │
│  └──────────────────────────────────────────────┘          └──────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
                                                           │
                                                           ▼
                               ┌────────────────────────────────────────────────────────┐
                               │                 Belső Hálózat (LAN / Router)           │
                               └────────────────────────────────────────────────────────┘
```

### Működési Módok Összehasonlítása

| Tulajdonság | Mode A (Aktív Router / Gateway) | Mode B (Passzív Transzparens Híd) |
|---|---|---|
| **Alkalmazási terület** | Önálló főrouterként vagy tartalék routerként | Meglévő router és szolgáltatói modem közé illesztve |
| **IP cím a hálózatban** | Igen (Gateway: `192.168.100.1` vagy egyedi) | Nincs (csak mérési felügyelet a fizikai portokon) |
| **PPPoE tárcsázás & VLAN** | Támogatott (beépített kliens) | Átengedi a csomagokat érintetlenül |
| **DHCP & DNS kiszolgálás** | Igen (`dnsmasq` integráció) | Nincs (a meglévő router oszt IP-t) |
| **Láthatóság a hálózaton** | Routerként látható | Layer 2 híd, de a doboz saját IP-címet kér a méréshez |
| **Üzemszünet-kockázat** | Ha leáll, nincs net | Szoftveres hiba esetén szoftverhíd, bypass hardverrel átenged |

---

## 4. Több Hálózati Kártya, Port Mátrix és Driver Támogatás

A NetworkMeasureBox rugalmas hálózati architektúrával rendelkezik, amely képes kezelni tetszőleges számú fizikai hálózati kártyát (PCI, PCIe, USB Ethernet adapterek, alaplapi portok, Wi-Fi kártyák):

### 1. Interfész Szerepkör Mátrix (Port Role Matrix)
A WebGUI **Beállítások ➔ 🔀 Portok és Illesztőprogramok** menüpontjában egy interaktív mátrix jelenik meg, ahol a felhasználó közvetlenül kioszthatja a portok szerepköreit:
* **🌐 WAN 1 (Elsődleges Internet)**: A fő internetkapcsolat (DHCP, PPPoE vagy Statikus IP).
* **🌐 WAN 2 (Másodlagos Internet)**: Tartalék (Failover) vagy terheléselosztás többutas alapútvonallal, külön DHCP vagy statikus beállítással. Valódi vonalon nincs tesztelve.
* **🏠 LAN (br-lan Híd)**: Bármennyi fizikai Ethernet port kijelölhető belső hálózatként. Az NMB automatikusan létrehozza a Linux hálózati hidat (`br-lan`), hozzáadja a kiválasztott portokat, és a hídra köti a DHCP kiszolgálót (`192.168.100.1/24`) és a NAT masquerade-et.
* **📶 Vendég Wi-Fi Kliens**: Dedikált Wi-Fi interfész a fő router vendéghálózatának ellenőrzésére.
* **🛡️ DMZ**: Mode A-ban a DMZ-port saját alhálózatot (`192.168.200.0/24`) és DHCP-t kap. Az eszközei elérik az internetet, a LAN-t viszont nem, a dobozt pedig csak DHCP-re és DNS-re.
* **⚪ Nincs kiosztva / Inaktív**: Szabadon hagyott portok.

### 2. Hardveres Illesztőprogram- és Firmware-Kezelés
Az [`nmb/netd/drivers.py`](file:///home/ot4/Documents/NetworkMeasureBox/nmb/netd/drivers.py) alrendszer közvetlenül kérdezi le a Linux kernelt és az `ethtool`-t:
* **Támogatott hardverek**: Realtek (RTL8111, RTL8168, RTL8125 2.5G, RTL8126 5G, RTL8152/8153 USB), Intel (e1000e, igb, igc 2.5G, ixgbe 10G, AX200/AX210 Wi-Fi 6/6E), Broadcom, MediaTek (MT7921/MT7922), Qualcomm Atheros, Aquantia / Marvell 10G, ASIX AX88179 USB 3.0 Gigabit adapterek.
* **Kernel Firmware Ellenőrzés**: Vizsgálja a `dmesg` naplót, és azonnal riasztást küld, ha egy hálózati kártya firmware hiánya miatt nem tudott elindulni.
* **Automatikus Telepítés**: Egyetlen kattintással a WebGUI-ból telepíti a hiányzó driver- és firmware-csomagokat (`firmware-realtek`, `firmware-linux-nonfree`, `firmware-iwlwifi`, `firmware-atheros`, `pciutils`, `usbutils`, `ethtool`), majd meghívja az `udevadm trigger`-t a modulok betöltéséhez.

---

## 5. Mérési Motorok és Metrikák

A doboz nem egyetlen mérésre támaszkodik, hanem 5 független rétegben validálja a kapcsolat minőségét:

### 1. Sub-second Folyamatos ICMP Ping Szonda (`nmb-probe`)
* **Gyakoriság**: 500 ms-onként küld ICMP Echo kéréseket 4 független referencia-célpontra:
  1. Szolgáltatói helyi átjáró (ISP Gateway / Next Hop)
  2. Cloudflare DNS (`1.1.1.1`)
  3. Google DNS (`8.8.8.8`)
  4. Quad9 DNS (`9.9.9.9`)
* **Számított értékek**: Átlagos RTT, minimális RTT, maximális RTT, p95 és p99 percentilis késleltetés.
* **RFC 3550 Jitter**: Kiszámítja a csomagok közötti valós idejű késleltetés-ingadozást (jitter), ami a VoIP, videóhívások és online játékok minőségét meghatározza.
* **Szakadás-ablak naplózás**: Rögzíti minden egyes kimaradás pontos kezdetét, végét és időtartamát másodperc pontossággal.

### 2. Ookla Speedtest CLI
* A hivatalos Speedtest CLI bináris integrációja.
* Képes a legközelebbi vagy automatikus szerver használatára, illetve rögzített szerver ID megadására. A szerverlista mindig az Ooklától jön (a boxhoz legközelebbi szerverek, néhány percenként vagy egy kattintással frissül); beépített lista nincs.
* Letöltési, feltöltési sebesség és terhelés alatti késleltetés (bufferbloat) mérése.

### 3. Cloudflare Speed Engine
* A Cloudflare globális CDN hálózatát használó, több szálon futó (multipart) mérőmotor.
* 100 MB-os és 25 MB-os valós adatcsomagok letöltése és feltöltése a legközelebbi Cloudflare edge pontról.

### 4. Fast.com (Netflix) mérőmotor
* A Fast.com saját API-ját használja (`api.fast.com/netflix/speedtest/v2`), a tokent a Fast.com oldalának szkriptjéből olvassa ki (ha nem sikerül, az ismert tokent használja).
* A Fast.com legfeljebb öt, a boxhoz közeli Netflix Open Connect szervert ad; a box mindegyikhez méri a késleltetést (ugyanazt a `range/0-0` kérést, amit a Fast.com is mér, és a TCP-kézfogást).
* Letöltés és feltöltés sima HTTP-n: 16 párhuzamos szál a szerverek között elosztva, irányonként 15 mp; az első 3 mp (TCP-felfutás) kimarad. Azért HTTP, mert Raspberry Pi 4-en a TLS 910 Mbps-nál a CPU 77–88%-át vitte el, és ha közben más szolgáltatás is dolgozott, az eredmény visszaesett; sima HTTP-n 50–56% kell. A tesztvonalon elkülönítve minden változat elérte a vonal sebességét (kb. 910 Mbps), tehát a Fast.com nem fogja vissza a boxot. A kijelzett érték a Fast.com-hoz hasonlóan a „stabil” sebesség: az átlag attól a ponttól, ahol a sebesség beáll.
* Minden sor a `raw_json`-ban megőrzi: a szolgáltatót, ASN-t, várost és országot, ahogy a Fast.com látja; minden szervert városával, országával, késleltetési mintáival és a le- és feltöltésből vett saját részével; a félmásodpercenkénti sebességet; a csúcsot és a sima átlagot; a terhelés alatti késleltetést mindkét irányban és a bufferbloat-osztályzatot.
* A vegyes mérésben minden alkalommal fut, mint a Cloudflare (`fastcom_interval_min = 0`); gigabites vonalon futásonként kb. 2,2 GB.

### 5. RTR-Netztest (RMBT Szabályozói Mérőmotor)
* Az Osztrák Hírközlési Szabályozó Hatóság (RTR) és az Európai Elektronikus Hírközlési Szabályozók Testülete (BEREC) által elfogadott, RFC kompatibilis RMBT nyílt forráskódú mérőmotor.
* Hiteles, független, szolgáltatói befolyástól mentes mérést biztosít.

### 6. iPerf3 Helyi és Távoli Tesztek
* Beépített iPerf3 kliens és felügyelt iPerf3 háttérszerver.
* Lehetővé teszi a belső hálózat (LAN kábel, Wi-Fi AP) maximális throughputjának kimérését, valamint nyilvános iPerf3 szerverek tesztelését TCP és UDP protokollon, tetszőleges párhuzamos szálakkal.

### 7. Net-Neutrality Portfojtás-Ellenőrző (Traffic Shaping Checker)
* Ellenőrzi, hogy a szolgáltató mesterségesen fojtja-e a sávszélességet vagy blokkol-e bizonyos típusú forgalmat.
* TCP-átvitelt hasonlít össze gyakori portokon (alapból 80, 443, 8080, 8443, 53, SSH 22, SIP 5060 és BitTorrent 6881) egy 443-as alapértékkel.

### 8. Traffic Gate (Forgalmi Kapu)
* Az automatikus mérések előtt az NMB megvizsgálja a `/proc/net/dev` számlálóit.
* Ha a doboz a küszöb feletti forgalmat lát (alapértelmezetten a kapacitás 2%-a), a teszt elhalasztásra kerül. Sima `standalone` módban a doboz csak a saját forgalmát látja, ezért a többi eszköz nem számít bele; idegen forgalom csak akkor kerül a számlálóiba, ha áthalad a dobozon.

### 8. Leállás hálózati forgalomra (kísérleti, alapból kikapcsolt)
* Bekapcsolás: `experimental_stop = true` a `[traffic_gate]` szakaszban, vagy a webes kapcsoló.
* Bekapcsolva az ütemezett mérés határa legfeljebb 500 kbps, elhalasztásnál 5 percenként újrapróbálkozik, és ha közben más forgalom jelenik meg, leáll, részeredmény mentése nélkül. A ping tovább fut, a kézi méréseket nem állítja le.
* Egy hanghívás belefér a határba, a videó és a torrent nem.
* A többi eszköz forgalmát a doboz a kliens oldali portokról (híd, gateway vagy saját hozzáférési pont) vagy a router UPnP-számlálóiból olvassa ki. Ha egyik sem érhető el, nincs ütemezett sebességmérés.
* A teljes rálátáshoz a dobozt hídként a szolgáltatói végpont és a router közé kell kötni. Ehhez két Ethernet-port kell, Raspberry Pi 4-en a második egy USB 3-as gigabites adapter lehet. Valódi hídon ezt még nem próbáltuk ki.

### 9. OONI Probe (opcionális, alapból kikapcsolt)
* Heti cenzúra- és hálózatsemlegességi mérés, a webes felületen vagy az `[ooni]` szakasz `enabled = true` beállításával kapcsolható be. A forgalmi kaput nem használja.

### Sebességmérés ütemezése
* Az új telepítések óránként mérnek (`schedule_cron = 0 * * * *`), ez a webes felületen módosítható. Az ütemezés azt adja meg, milyen gyakran néz rá a box; emellett minden motornak saját minimális időköze van (`ookla_interval_min`, legalább 60; `rtr_interval_min` és `cloudflare_interval_min`, 0 = minden futáskor; `fastcom_interval_min`, alapból 0) a `[speedtest]` részben vagy a webes felületen. Így az RTR-NetTest mérhet percenként, az Ookla pedig óránként. Az iPerf3 ugyanezzel az ütemezéssel fut, saját `iperf3_interval_min` időközzel, egy vagy több szerverrel (`target_host` és `extra_servers`; alapból 4 TCP-szál, 10 mp, előbb letöltés, majd feltöltés), önmagában vagy a vegyes mérésben, de csak ha az `[iperf]` részben be van állítva iPerf3-szerver, és az válaszol; különben üres sor nélkül kimarad. A mérési lista csak valódi méréseket mutat; a kihagyott és sikertelen futásokat egy sor számolja. Az ütemezett méréseket az `nmb-web` indítja, ezért annak futnia kell; frissítéskor a beállított ütemezés megmarad.

---

## 6. Alacsony Memóriájú és Beágyazott Architektúra (512 MB RAM Optimalizáció)

Memóriatakarékos profilok korlátozott Linux-rendszerekhez. Ezek eddig csak Raspberry Pi 4-en futottak, routeren nem.

### Memóriaprofilok (`memory_profile`)

A konfigurációban vagy a WebGUI-ban három profil választható:

```ini
[system]
memory_profile = auto   # auto, low, standard, performance
```

1. **`low` profil (< 768 MB RAM, 512 MB-on nincs tesztelve)**:
   * **SQLite memória korlát**: A forró adatbázis mérete RAM-ban szigorúan 48 MB-ra van korlátozva. A legrégebbi ping rekordok automatikusan ritkításra kerülnek.
   * **SQLite cache és mmap**: `cache_size = -2000` (2 MB cache), `mmap_size = 2097152` (2 MB mmap).
   * **TCP socket pufferek**: Csökkentett 8 MB-os pufferhatár a socket memóriaterhelés megelőzésére.
   * **Agresszív glibc heap felszabadítás**: Periodikusan és mérések után automatikusan meghívja a `libc.malloc_trim(0)` natív C függvényt, amely azonnal visszadja a fel nem használt virtuális heap memóriát a Linux kernelnek.
   * **Python GC**: A generációs szemétgyűjtő 3 percenként kényszerített tisztítást végez.
2. **`standard` profil (1 GB - 2 GB RAM, pl. Raspberry Pi 3/4)**:
   * 96 MB live adatbázis limit, 8 MB cache, 16 MB mmap, kiegyensúlyozott pufferek.
3. **`performance` profil (4 GB+ RAM, x86 mini PC-k, szerverek)**:
   * 192 MB live adatbázis limit, 32 MB cache, 64 MB mmap, 64 MB TCP socket pufferek a 10G burst hálózati sebességekhez.

A WebGUI Rendszer fülén közvetlenül ellenőrizhető a szabad RAM mennyisége, az aktív memóriaprofil, és egyetlen gombnyomással elvégezhető a memóriatisztítás (`🧹 Trim & Free RAM Now`).

---

## 7. Hardver- és Flash-Védelem (microSD Longevity)

A legtöbb Raspberry Pi és beágyazott SBC a microSD kártya tönkremenetele miatt hibásodik meg a gyakori írási műveletek következtében. Az NMB speciális védelmi réteggel akadályozza meg a flash cellák elhasználódását:

```
              RAM (tmpfs)                         microSD (ext4, noatime,commit=600)
/var/lib/nmb/live/nmb.db  (+ -wal, -shm)  ──backup──▶  /var/lib/nmb/persist/nmb.db
                                           ◀─restore── (rendszerindításkor)
```

1. **Élő adatbázis a RAM-ban**: A folyamatos ping- és sebességadatok a `/var/lib/nmb/live/` tmpfs RAM partícióra íródnak SQLite WAL (Write-Ahead Logging) módban. Zéró írási terhelés éri az SD kártyát másodpercenként.
2. **Atomi pillanatkép mentés (`nmb-snapshot`)**: Az SQLite Online Backup API segítségével 15 percenként egyetlen konzisztens, szekvenciális írással menti el az állapotot a fizikai SD kártyára (`/var/lib/nmb/persist/nmb.db`), valamint a rendszer szabályos leállításakor (`SIGTERM`).
3. **ext4 fájlrendszer finomhangolás**: `noatime,commit=600` csatolási opciók (a kernel 10 percig késleltetheti a naplóbejegyzéseket).
4. **Naplózás**: A `/var/log`, a `/var/tmp` és a `/tmp` tmpfs-en fut, ezért a naplók újraindításkor elvesznek. A swapot az NMB nem kapcsolja ki.

---

## 8. Beépített Webes Felület (WebGUI) és Többnyelvűség

A beépített webes felület a **szabványos 80-as HTTP router porton** érhető el (fejlesztői futtatás esetén automatikus 8080-as fallback-kel), teljesen reszponzív, modern sötét dizájnnal és 14 dedikált kategóriával rendelkezik:
* **Mobil-optimalizált Érintőkijelzős Ergonómia**: Az almenü-sávok (`.router-subnav`, `.remote-subnav`, `.adblock-subnav`) védett vízszintes görgető-szalagként (`flex: 0 0 auto`, `white-space: nowrap`) viselkednek intelligens `scrollTo` görgetéssel. Ez megakadályozza, hogy okostelefonos kijelzőkön (360px–420px) a gombok betűnként tördelődve függőleges hasábokká torzuljanak.

1. **Irányítópult (Dashboard)**: Legutóbbi mérések összefoglalása, SLA státusz, egykattintásos mérésindítás, interfész-választó és élő végrehajtási terminál.
2. **Ping Telemetria (ICMP Ping)**: Valós idejű vektoros SVG késleltetési grafikon, csomagvesztés, p95/p99 statisztikák, CSV export.
3. **Sebességteszt Eredmények**: Részletes audit napló letöltési/feltöltési sebességgel, bufferbloat pontszámmal és mérőmotor jelöléssel.
4. **iPerf3 Hálózati Sebesség**: Helyi és távoli iPerf3 audit, beépített iPerf szerver indítása/leállítása.
5. **Hálózati Kimaradások**: Minden egyes internetkiesés audit naplója (kezdet, vég, időtartam, kiesett csomagok).
6. **SLA Megfelelőség & Szerződés**: A valós mérések összehasonlítása az előfizetői szerződésben garantált és névleges értékekkel.
7. **Traceroute & Útvonal Elemzés**: Vizuális útvonalkövetés ugrásonkénti késleltetéssel (MTR jellegű analízis).
8. **Portfojtás (Net-Neutrality)**: Forgalomkorlátozás ellenőrzése portonként.
9. **RTR-Netztest (RMBT)**: Nyílt forráskódú sebességmérés.
10. **Hálózatfelderítő (Device Explorer)**: Csatlakoztatott klienseszközök, ARP leltár, MAC gyártóazonosítás.
11. **Fejlesztői Mélykonzol**: Valós idejű rendszernapló (Syslog) és belső modul-napló élő streameléssel.
12. **AI Diagnosztika (LLM Snapshot)**: Egyetlen gombnyomással másolható szanált Markdown diagnosztikai köteg ChatGPT, Claude vagy Gemini mélyelemzéshez.
13. **Beállítások & Router Konfiguráció**:
    * WAN beállítások (DHCP, PPPoE VLAN-nal, Statikus IP, Egyedi WAN MAC cím klónozás).
    * LAN beállítások (Gateway IP, DHCP tartomány, bérleti idő).
    * Wi-Fi 6/6E/7 beállítások (SSID, jelszó, 2.4/5/6 GHz, csatornaszélesség, WPA2/WPA3).
    * **🔀 Portok és Illesztőprogramok**: Multi-NIC szerepkör mátrix, WAN2 failover/loadbalance, LAN bridge (`br-lan`), hardveres driver detektálás és egykattintásos telepítés.
    * Működési mód (Mode A / Mode B / automatikus).
    * Memóriaprofilok (`low`, `standard`, `performance`) és RAM karbantartás.
    * Adminisztrátori hitelesítés és jelszókezelés.
14. **Kijelentkezés (Logout)**: Biztonsági kijelentkezés a böngésző hitelesítési gyorsítótárának törlésével.

### 11 Támogatott Nyelv (néhány szakkifejezés angolul marad)
A felület jobb felső sarkában egyetlen kattintással váltható a nyelv. A webes felület, a terminálos felület, az eredményoldal, a grafikonok és a jelentés minden felirata le van fordítva; a Telegram bot is mind a 11 nyelvet beszéli:
* 🇭🇺 **Magyar (HU)**
* 🇬🇧 **Angol (EN)**
* 🇩🇪 **Német (DE)**
* 🇺🇦 **Ukrán (UK)**
* 🇫🇷 **Francia (FR)**
* 🇷🇴 **Román (RO)**
* 🇮🇹 **Olasz (IT)**
* 🇪🇸 **Spanyol (ES)**
* 🇵🇹 **Portugál, Portugália (PT)**
* 🇧🇷 **Portugál, Brazília (PT-BR)**
* 🇨🇳 **Kínai, egyszerűsített (ZH)**

A hat újabb nyelv nyelvenként egy JSON-fájl az `nmb/web/locales/` és az `nmb/report/locales/` alatt; ha egy szöveg hiányzik, angolul jelenik meg, sosem más nyelven.

---

## 9. Hálózatfelderítő (Device Explorer) & Vendég Wi-Fi Kliens Szonda

### Hálózatfelderítő (Network Device Explorer)
* Folyamatosan pásztázza a helyi alhálózatot ARP kérésekkel.
* Táblázatba rendezi az aktív klienseket: IP cím, MAC cím, gépnév (hostname), első és utolsó észlelés időpontja.
* **MAC OUI Gyártófelismerés**: A hardveres MAC cím első 3 bájtja alapján automatikusan azonosítja az eszköz gyártóját (pl. Apple, Samsung, Intel, Xiaomi, Sony, TP-Link stb.).

### Dedikált Vendég Wi-Fi Kliens Szonda (Guest Wi-Fi Client Probe)
Sok router rendelkezik elkülönített vendéghálózattal (Guest Network), amelynek minőségét nehéz folyamatosan ellenőrizni:
* Az NMB képes egy másodlagos Wi-Fi csatolóval (pl. egy USB Wi-Fi dongle-lal vagy alaplapi rádióval) önálló kliensként felkapcsolódni a fő router vendég Wi-Fi SSID-jére.
* Folyamatosan ellenőrzi a vendéghálózat elérhetőségét, jelerősségét, IP kiosztását és átjáróját.
* Vizsgálja, hogy a vendéghálózat megfelelően izolált-e (nem látja a belső hálózatot), miközben a fő mérési funkciókat teljesen függetlenül működteti.

---

## 10. Univerzális Távoli Elérés, PiVPN Hub és Tailscale Mesh

A távoli elérés elengedhetetlen, ha a mérődoboz telephelyen, nyaralóban vagy szerverszobában üzemel:

### 1. PiVPN Gyors Kliensgenerátor (WireGuard & OpenVPN Hub)
* **Kétprotokollos VPN Szerver**:
  * **WireGuard** (UDP 51820): Korszerű, alacsony késleltetésű, akkumulátorkímélő protokoll modern mobilokhoz és laptopokhoz.
  * **OpenVPN Elliptic Curve** (UDP 1194): Elliptikus görbén alapuló (`prime256v1`) titkosítású biztonsági csatorna.
* **Dual-Stack IPv4 & IPv6 Alagutak**: Teljes IPv4 alhálózatok (`10.8.0.0/24`, `10.9.0.0/24`) és közvetlen IPv6 ULA tartományok (`fd42:42:42::/64`, `fd42:42:43::/64`) kiosztása.
* **1-Kattintásos Kliens Párosítás**: Adja meg a kliens nevét $\to$ az NMB azonnal legenerálja a konfigurációs fájlt és a közvetlenül leolvasható QR kódot a WebGUI-ban és a Telegramon!
* **Kliens Leltár és Menedzsment**: Valós idejű táblázat a csatlakoztatott kliensek IP címével, legutóbbi kézfogásával, adatforgalmával (RX/TX) és azonnali visszavonási kapcsolóval.

### 2. Tailscale Secure Mesh Távoli Hozzáférés
* **Management-Plane Izoláció**: Közvetlen, titkosított hozzáférés a WebGUI felülethez a világ bármely pontjáról anélkül, hogy a tűzfalon nyilvános portot kellene nyitni vagy DynDNS-t kellene konfigurálni.
* Teljesen áthidalja a szolgáltatói CGNAT korlátozásokat és a többszörös router-kaszkádokat.
* Valós idejű MagicDNS azonosító, Tailscale IPv4/IPv6 cím kijelzés, és egykattintásos Csatlakozás / Leválasztás vezérlés.

### 3. DynDNS & Továbbító Proxy
* Integrált DuckDNS dinamikus DNS frissítő kliens.
* Opcionális beépített HTTP CONNECT továbbító proxy, kötelező hitelesítéssel.

---

## 11. Beépített DNS Reklámblokkoló és Adatvédelmi Pajzs (Pi-hole Alternatíva)

* **Nagy Teljesítményű Memóriabeli Sinkhole**:
  * Kiszűri a nyomkövető, reklám-, telemetria- és malware tartományokat még azelőtt, hogy azok elérnék az otthoni eszközöket.
  * Előre konfigurált blokkolólisták (StevenBlack unified hosts, AdAway stb.) automatikus háttérbeli Gravity frissítésekkel.
* **Egyéni Szabályok és Élő Napló**:
  * Rendszerstatisztikák: Mai összes kérés, blokkolt kérések, szűrési arány (%) és aktív Gravity doménszám.
  * Egyéni feketelista, fehérlista és joker Regular Expression (RegEx) szabályok hozzáadása.
  * Valós idejű DNS lekérdezési napló a WebGUI-ban.

---

## 12. Haladó Törvényszéki Diagnosztika és Kiváltó Ok Elemzés

* **Wi-Fi RF & PHY Telemetria (`iw` segítségével)**:
  * Valós idejű jelerősség pontos dBm-ben (pl. `-52 dBm`) és zajszint (Noise floor).
  * RX/TX PHY elméleti bitráták, MCS modulációs index, csatornaszélesség (20/40/80/160 MHz) és hardveres újraküldési hiba-számlálók (`tx_retries`, `tx_failed`).
* **DNS-eltérítés teszt és összehasonlító feloldó mátrix**: olyan címre küld DNS-kérést, ahol nincs szerver; ha válasz jön, valami eltéríti a 53-as portot.
  * Párhuzamosan ellenőriz 4 független DNS szervert: Helyi átjáró/DHCP, Cloudflare (`1.1.1.1`), Google (`8.8.8.8`), Quad9 (`9.9.9.9`).
  * Ellenőrzi a DNSSEC hitelesítést (`ad` Authenticated Data bit) és a gyorsítótárazott vs natív válaszidőket.
  * Detektálja, ha a szolgáltató észrevétlenül átirányítja (hijackeli) az 53-as UDP portot.
* **RFC 5389 STUN Kliens & CGNAT Elemzés**:
    * **NAT-leképezés**: végponttól független (két STUN-szerver felé ugyanaz a nyilvános port) vagy szimmetrikus. A full cone és a restricted típust nem különbözteti meg.
  * Automatikusan kategorizálja a felső hálózati réteget:
    * **Valódi Publikus IP**: A helyi WAN IP megegyezik a külső reflexív STUN IP-vel.
    * **Szolgáltatói CGNAT**: A WAN IP a dedikált RFC 6598 tartományba esik (`100.64.0.0/10`).
    * **Dupla NAT**: A WAN IP RFC 1918 szerinti belső cím (`192.168.x.x` vagy `10.x.x.x`).
* **CPU Megszakítás (IRQ/SoftIRQ) & Hálózati Offload Vizsgálat**:
  * Méri a magonkénti megszakítási és SoftIRQ terhelést a CPU0 szűk keresztmetszetek kiszűrésére (a Gigabit sebesség klasszikus akadálya Raspberry Pi-n és MIPS routereken).
  * RPS/XPS elosztási maszkok (`/sys/class/net/<iface>/queues/rx-*/rps_cpus`) és hálózati kártya gyorsítások (checksum offload, TSO, GRO) auditálása.
* **Mikro-Szakadások & Csomagvesztési Mintázat Korreláció**:
  * Különválasztja a pár ezredmásodperces puffer-torlódási tüskéket a valós link-szakadásoktól ($\ge 5\text{s}$).
  * Automatikusan megállapítja, hogy a hiba a helyi berendezés (CPE/router) vagy a szolgáltatói hálózat (peering) kimaradásából ered-e.
* **Flash Tároló I/O és Rendszer-Egészség**:
  * Folyamatos `%iowait` mérés a memóriakártya vagy flash memória lassulásának felderítésére.
  * Flash-kopás és szabad tárhely ellenőrzés (`statvfs()`), valamint kernel hiba-csapda a `dmesg`/`kmsg` fájlrendszer-hibák azonnali elcsípésére.
* **Szanált Konfiguráció és Adatvédelmi Maszkolás**:
  * Beépített adatvédelmi redaktor: automatikusan kitakarja a bot tokeneket, chat ID-kat, Wi-Fi jelszavakat, előfizetői azonosítókat és áramköri azonosítókat, mielőtt a jelentést külső LLM-nek vagy szolgáltatónak továbbítaná.

---

## 13. Többnyelvű Telegram Bot Érintőmenüvel és QR Kóddal

A beépített felügyeleti bot (`nmb-telegram`) segítségével az eszköz böngésző nélkül, mobilról is teljes körűen irányítható:
* **Interaktív Érintőmenük (Inline Keyboards)**: Gombnyomással elérhető állapotfelmérés, sebességmérés, SLA dosszié és VPN QR lekérés.
* **Többnyelvűség**: Váltható **magyar**, **angol**, **német**, **francia** és **ukrán** nyelv között.
* **Azonnali SLA Dosszié Küldés**: A friss `.html` dosszié közvetlenül megérkezik a Telegram csevegésbe, így azonnal továbbítható a technikusnak.
* **Proaktív Riasztások**: Értesítés szakadásról, és ha a csomagvesztés, a késleltetés vagy a jitter 5 percen át a küszöb felett marad.

---

## 14. SLA Dosszié és Vektoros SVG Motor

* **Semleges Nemzetközi Megnevezés**:
  * A riportok semleges megnevezése: *"Broadband Quality & ISP SLA Performance Dossier"* / *"Szélessávú Hálózati Minőség & Szolgáltatói SLA Vizsgálati Dosszié"*.
  * Nem hivatalos és nem hatósági dokumentum. Az SLA eredmény az NMB saját értékelése rögzített küszöbökkel, nem hatóság vagy szolgáltató döntése.
  * **Megtévesztő `0 Mb/s` Értékek Szűrése**: Ha a szerződéses garantált sebesség nincs beállítva vagy 0 Mb/s, a riport nem jelenít meg félrevezető kártyát, hanem tájékoztató szöveggel segíti a hatósági/szolgáltatói összevetést.
  * **Egyértelmű IP Cím és Szolgáltató Megjelenítés**: Minden egyes mérési sor és telemetria blokk kiemelten megjeleníti az észlelt publikus IPv4/IPv6 címet és a hozzá tartozó ISP szolgáltató nevét.
* **Tiszta Matematikai Vektoros SVG Motor**:
  * Külső diagramkönyvtárak nélkül generál reszponzív, retina-éles `<svg viewBox="0 0 800 380">` grafikonokat Bézier-görbékkel, kettős Y-tengellyel (Mbps és ms) és érintőpontokkal.
  * Generálási idő: **< 1.5 ezredmásodperc**.
  * Közvetlenül letölthető 11 nyelven a `/dossier?lang=...` végponton vagy Telegramon.

---

## 15. Valós Idejű Folyamatkezelő (Beágyazott htop Motor)

* Közvetlenül a Linux kernel `/proc` fájlrendszeréből olvassa az állapotot, megszüntetve a nehézkes `ps` folyamatindításokat.
* Valós idejű lista: PID, Felhasználó, Prioritás, Nice, VIRT, RES, CPU%, MEM%, futásidő és parancssori argumentumok.
* Kategóriaszűrés: Rendszerfolyamatok vs Felhasználói alkalmazások vs NMB komponensek.
* Közvetlen szignálküldés (SIGTERM / SIGKILL) elszabadult folyamatok leállításához a WebGUI-ból.

---

## 16. Önjavító Watchdog és Biztonsági Visszaállás (`nmb-heal`)

* Autonóm háttérbeli audit: ellenőrzi a binárisok épségét, az adatbázist, a jogosultságokat és az internetkapcsolatot.
* **Frissítés a GitHubról pár kattintással**: „Apply Stable Update” a webes felületen, `nmb-cli update --apply --yes` vagy `nmb-heal update --apply`. A szabványos telepítésen (`/opt/nmb`, Git-adat nélkül) a box letölti ennek a tárolónak a legújabb commitját, lefuttatja a tesztjeit (ha elbuknak, semmi sem változik), elmenti a beállításokat és a méréseket, a `setup.sh`-val telepíti (ez megtartja a beállításokat és a méréseket, a programfájlokat lecseréli), és ha a telepítés vagy a webszerver ellenőrzése nem sikerül, visszarakja az előző verziót. A webes felület mutatja a lépéseket; a napló: `/var/log/nmb/update.log`. Git-es példány `git pull`-lal frissül, és az előző commitra áll vissza.

---

## 16/b. Központi Mérésgyűjtő (`nmb-collector`)

Egy internetszolgáltató vagy szakember a saját szerverén futtatja az `nmb-collector`-t, és azok a boxok küldenek neki, amelyeknek a gazdája ehhez hozzájárul. Minden ki van kapcsolva, amíg a box gazdája be nem kapcsolja (webes felület → Rendszer → Központi mérésgyűjtő, vagy `[collector]` az `nmb.conf`-ban), három külön hozzájárulással:

| Beállítás | Mit kap meg a gyűjtő |
|---|---|
| `enabled` | Sebességmérések (a sikertelenek is), óránkénti ping-összesítő célonként, a box egyedi azonosítója, neve, az ügyszám, a szolgáltató, az ügyfélszám és az előfizetett sebességek |
| `share_diagnostics` | Ezen felül a box eseményei és óránként a teljes hálózati diagnosztika: interfészek, útvonalak, MTU, DNS, NAT, Wi-Fi, traceroute, a helyi hálózat eszközei és a beállítások, minden titok kitakarva |
| `allow_remote_control` | A gyűjtő indíthat sebességmérést (motorral és Ookla-szerverrel), kérhet friss diagnosztikát vagy azonnali feltöltést. Mást nem: shell-parancsot nem, beállítást nem módosíthat. A box percenként maga kérdezi meg a gyűjtőt, így a gazda hálózatába kívülről semmi nem csatlakozik |

Minden boxnak állandó, véletlen azonosítója van (pl. `nmb-k7q2-x9mf-3hwd`, a webes felületen látszik), mert a box neve alapból minden boxon `nmb-01`. A gyűjtő jelszóval védett oldalain a box megtalálható ezzel az azonosítóval, a nevével, a mostani vagy egy korábbi ügyszámmal, az ügyfélszámmal vagy a szolgáltató nevével. A box oldala mutatja az átlagokat az előfizetett sebességhez képest, az eredményeket motoronként, a pinget célonként, az eseményeket, a diagnosztikai előzményeket, a távoli parancsokat, és CSV-letöltést ad.

Gyűjtő beüzemelése (csak standard könyvtár, Python 3.10 vagy újabb):
```bash
git clone https://github.com/4r04x4t/NetworkMeasureBox.git /opt/nmb-collector
useradd --system nmb-collector
/opt/nmb-collector/bin/nmb-collector --data /var/lib/nmb-collector set-password
/opt/nmb-collector/bin/nmb-collector --data /var/lib/nmb-collector token-add ugyfelszolgalat   # ezt a tokent kapja meg a box gazdája
chown -R nmb-collector /var/lib/nmb-collector
cp /opt/nmb-collector/os/nmb-collector.service /etc/systemd/system/ && systemctl enable --now nmb-collector
```
A 8600-as porton figyel. Tedd HTTPS-es fordított proxy mögé, vagy indítsd `--cert` és `--key` kapcsolóval, mert a token és az admin jelszó minden kéréssel együtt utazik.

---

## 17. 100%-os De-Pythonizáció és Kereskedelmi Router Portolási Terv

> **Állapot: csak terv.** Az NMB jelenleg Raspberry Pi 4-en készül és fut. Routerre még nincs sem szoftver, sem firmware; az alábbi számok tervezési célok, nem mérések.

A NetworkMeasureBox kereskedelmi routereken való futtatásának terve (akár **4 MB Flash és 32 MB RAM** mellett):
* **Először általános kód**: a natív kód platform- és architektúrafüggetlenül készül, és előbb PC-n (x86-64) és Raspberry Pi 4-en (ARM64) kell lefordulnia, átmennie a teszteken és bizonyítania, csak utána jöhetnek a routerek; a router-célok később ugyanannak a kódnak a háttérmoduljaiként kerülnek be. Lásd a `DEPYTHONIZATION_ROADMAP.md` *Generic First* részét.
* **Minőségi követelmény**: a natív változatnak legalább olyan hibátlanul kell futnia, mint a Pythonosnak, a menet közben talált hibákat ki kell javítani (nem átvinni), és mérhetően jobbnak kell lennie (CPU, memória, indulás, naplózás, biztonságos frissítés); egy komponens csak ennek leírt bizonyítékával válthatja le a Python-megfelelőjét. Lásd a `DEPYTHONIZATION_ROADMAP.md` *Quality Bar* részét.
* **Egységes Statikus Bináris (`nmbd`)**: **Go 1.23+** (Tier 1) és **C11 musl-libc** (Tier 2 & 3) alapon, zéró külső csomagfüggőséggel.
* **Célhardver Portolási Kézikönyvek & WikiDevi Hardver Profilok**:
  * **[ASUS RT-AXE7800](https://wikidevi.wi-cat.ru/ASUS_RT-AXE7800)**:
    * Broadcom BCM6756 4 mag @ 1.7 GHz Cortex-A7, 512 MB DDR4 RAM, 256 MB NAND Flash, 1x 2.5GbE + 1x 1GbE WAN/LAN + 3x 1GbE LAN, Tri-Band Wi-Fi 6E, USB 3.2 Gen 1.
    * Rendszer: Asuswrt / Asuswrt-Merlin (GNUton fork) vagy OpenWrt `bcm4908`.
    * Natív démon: Go 1.23+ egyetlen bináris vagy C11; 2.5 Gbps vonali sebességteszt, többmagos CAKE SQM, Flow Cache bypass, beágyazott `tsnet` Tailscale.
  * **[ASUS RT-N12+](https://wikidevi.wi-cat.ru/ASUS_RT-N12_series)**:
    * MediaTek MT7620N ver:2 eco:6 MIPS24KEc @ 580 MHz (`ramips/mt7620`), 32 MB DDR SDRAM, 8 MB SPI Flash, Fast Ethernet (100 Mbps).
    * Rendszer: OpenWrt `ramips/mt7620`.
    * Natív démon: Monolitikus C11 musl-libc-vel (<850 KB, ~2.8 MB RAM RSS), 100 Mbps mérés <14% CPU terheléssel.
  * **[TP-Link TL-WR740N v4.x / v4.23](https://wikidevi.wi-cat.ru/TP-LINK_TL-WR740N_v4.x)**:
    * Qualcomm Atheros AR9331 MIPS 24Kc @ 400 MHz (`ath79/generic` / `ar71xx`), 32 MB DDR SDRAM, **4 MB SPI Flash**, Fast Ethernet (100 Mbps).
    * Rendszer: Minimal Stripped OpenWrt `ath79/generic` (LuCI nélkül, minimalista kernellel).
    * Natív démon: Micro-C11 `-Os` optimalizálással, stripelve, UPX-LZMA tömörítéssel (**178 KB bináris**), 1.4 MB RAM RSS, 100% memóriabeli körkörös puffer (`tmpfs`) a flash-kopás kizárására.
  * **[TP-Link TL-WR1043ND v1.x](https://wikidevi.wi-cat.ru/TP-LINK_TL-WR1043ND_v1.x)**:
    * Atheros AR9132 @ 400 MHz, 32 MiB RAM, 8 MiB Flash, Realtek RTL8366RB, 1x 1GbE WAN + 4x 1GbE LAN.
  * **[TP-Link Archer C6 v2.x](https://wikidevi.wi-cat.ru/TP-LINK_Archer_C6_v2.x)**:
    * Qualcomm Atheros QCA9563 @ 775 MHz, 128 MiB RAM, 8 MiB Flash, QCA8337N, 1x 1GbE WAN + 4x 1GbE LAN, AC1200.
  * **[ASUS RT-AC57U v1](https://wikidevi.wi-cat.ru/ASUS_RT-AC57U)**:
    * MediaTek MT7621AT, 2 mag @ 880 MHz, 128 MiB RAM, 16 MiB SPI flash, a switch a SoC-ban, 1x 1GbE WAN + 4x 1GbE LAN, 2,4 GHz MT7603EN (b/g/n 2x2) + 5 GHz MT7612EN (a/n/ac 2x2), AC1200, 1x USB 2.0.
    * A v2 Qualcomm-chipes, más hardver; ez a cél csak a v1-re vonatkozik. A WikiDevi a Padavant folyamatban lévőként említi; a valószínű alap az OpenWrt `ramips/mt7621`, ezt még ellenőrizni kell.
* **Tervezett eszközcsaládok**: MikroTik eszközök (a natív `nmbd` konténerként RouterOS v7-en, vagy OpenWrt-n a RouterOS helyett; például hEX, hAP ac², RB5009) és MediaTek SoC-os routerek (MT7620/MT7628, MT7621, MT7622, Filogic MT7981B, MT7986A, MT7988A), chipenként egy port. Az adatokat még ellenőrizni kell; lásd a portolási terv 1.3. részét.
* **Fejlesztői hozzáférés és biztonságos javítás (minden portnál kötelező)**: minden eszközön marad egy, a tulajdonos által bekapcsolható karbantartási mód, teljes root-hozzáféréssel a fejlesztőknek és a fejlesztő LLM-ügynököknek (csak SSH-kulccsal, minden munkamenet auditnaplóban, meghatározott idő után magától kikapcsol); részletes, strukturált naplózás, ami nem koptatja a flasht; újraindítás után is megmaradó összeomlás-nyomok; és a javítás a futó változat mellé kerül, automatikus visszaállással, így egy helyszíni javítás kis eséllyel teszi működésképtelenné (brickeli) az eszközt. Lásd a portolási terv 7D. részét.
* **Az NMB saját Linux-disztribúciója (tervezett)**: minimális rendszerkép Raspberry Pi 4-re, később x86-64-re, a de-Pythonizált `nmbd`-re építve: csak olvasható rendszer, külön adatpartíció, A/B frissítés automatikus visszaállással. Az alapot (Debian, OpenWrt, Alpine vagy más hálózatra szakosodott disztribúció) a portolási terv összehasonlítása alapján választjuk ki. A disztribúció az NMB sajátja, a Linux-kernel nem: az alap gyári kernelét használja változatlanul (Pi 4-en a Raspberry Pi kernelt, x86-64-en az alapdisztribúció LTS kernelét). Egyik eszközön sem fut Python. Lásd a `DEPYTHONIZATION_ROADMAP.md` 6A. részét.
* **Főbb Natív Alrendszerek (Zéró Python)**:
  * **Memória-optimalizált DNS Sinkhole / Reklámblokkoló**: 512 KB Counting Bloom Filter (MurmurHash3, 0.1% FPR) és Trie, amely kevesebb mint 640 KB RAM-ot fogyaszt 32 MB-os routereken.
  * **Külső Függőség Nélküli Sebességmérő Socket Sinks**: Saját folyamaton belüli TCP/TLS kliens, amely közvetlenül csatlakozik Ookla, Cloudflare Edge, Fast.com (Netflix Open Connect) és RTR-NetTest szerverekhez `splice()` és `recv()` zéró-másolásos pufferekkel külső binárisok nélkül.
  * **Autonóm Önjavító Motor (`nmb_heal`)**: Többszintű watchdog (szolgáltatás újraindítás, interfész bounce, driver offload konfigurálás, biztonsági konfigurációs visszagörgetés).
  * **Dinamikus DNS Kliens**: Közvetlen TLS 1.3 Netlink-tudatos frissítő `duckdns` és `dynv6` szolgáltatásokhoz (<60 KB RAM).
* Részletes műszaki tervek:
  * 📄 **[`docs/ROUTER_PORTING_AND_DEPYTHONIZATION_PLAN.md`](docs/ROUTER_PORTING_AND_DEPYTHONIZATION_PLAN.md)**
  * 📄 **[`docs/DEPYTHONIZATION_ROADMAP.md`](docs/DEPYTHONIZATION_ROADMAP.md)**

---

## 18. Parancssori Eszközök (CLI) és Szolgáltatások

A szoftver moduláris felépítésű, az egyes feladatokat különálló, jól tesztelhető démonok látják el:

| Parancs / Bináris | Leírás | Gyakori Használat |
|---|---|---|
| `nmb-netd` | Hálózati üzemmód démon (Mode A / Mode B / Failover) | `nmb-netd --status`<br>`nmb-netd --switch auto\|standalone\|mode_a\|mode_b` |
| `nmb-probe` | Nagyfrekvenciás ICMP ping és jitter szonda | `nmb-probe --verbose` |
| `nmb-speed` | Sebességmérő és forgalomkorlátozás-ellenőrző | `nmb-speed --trigger manual`<br>`nmb-speed --engine ookla\|cloudflare\|fastcom\|rtr\|iperf3\|all`<br>`nmb-speed --interface eth0` |
| `nmb-ooni` | Opcionális OONI Probe kiegészítő | `nmb-ooni status`<br>`nmb-ooni run websites` |
| `nmb-report` | Riport generátor (HTML dosszié, CSV, JSON) | `nmb-report --window 24h --html dossier.html`<br>`nmb-report --json-summary`<br>`nmb-report --send-email` |
| `nmb-adblock` | Beépített DNS reklámblokkoló sinkhole | `nmb-adblock status`<br>`nmb-adblock update`<br>`nmb-adblock -b domain.com` |
| `nmb-heal` | Önjavító watchdog és biztonsági visszaállás | `nmb-heal audit`<br>`nmb-heal status`<br>`nmb-heal fix` |
| `nmb-driver` | Hardveres driver és firmware felderítő | `nmb-driver scan`<br>`nmb-driver missing`<br>`sudo nmb-driver install` |
| `nmb-telegram` | Telegram menedzsment és riasztási bot | `nmb-telegram` |
| `nmb-cli` | A WebGUI menüi terminálban (SSH, egér, gyorsbillentyűk) és JSON-parancsok | `nmb-cli`<br>`nmb-cli menu`<br>`nmb-cli show tab-home`<br>`nmb-cli run speed.run engine=cloudflare`<br>`nmb-cli run speed.run engine=fastcom`<br>`nmb-cli logs dev -n 50 --level warning`<br>`nmb-cli latest` / `nmb-cli latest ookla`<br>`nmb-cli update` / `nmb-cli update --apply --yes`<br>`nmb-cli run collector.send` |
| `nmb-collector` | Központi mérésgyűjtő szolgáltatónak vagy szakembernek (az ő szerverén fut, nem a boxon) | `nmb-collector set-password`<br>`nmb-collector token-add <név>`<br>`nmb-collector serve --port 8600` |
| `nmb-web` | Beépített kezelőfelület és REST API | `nmb-web` (port 80 / dev 8080) |
| `nmb-helper` | Emelt szintű hálózati és driver műveletek segédprogramja | `sudo nmb-helper install-drivers all`<br>`sudo nmb-helper tune` |

### Rendszerszolgáltatások (`systemd`)
Minden komponens saját systemd egységként fut, amelyeket az `nmb.target` fog össze:

```bash
# Teljes rendszer állapotának megtekintése
sudo systemctl status nmb.target

# Szolgáltatások újraindítása
sudo systemctl restart nmb.target

# Valós idejű naplók követése
sudo journalctl -u nmb-probe -f
sudo journalctl -u nmb-web -f
```

---

## 19. Interaktív Telegram Távvezérlő Parancsok

Ha beállította az `nmb-telegram` szolgáltatást, a dobozt közvetlenül a Telegramból is irányíthatja érintőgombokkal:

| Parancs | Leírás |
|---|---|
| `/menu` | Megnyitja a fő interaktív érintőmenüt (Inline billentyűzet) |
| `/status` | Valós idejű rendszerállapot: üzemidő, hálózati mód, IP címek, szolgáltató, CPU/RAM |
| `/ping` | Azonnali ICMP válaszidő és csomagvesztési mátrix a 4 referencia-célpontra |
| `/test [motor]` | Sebességmérés indítása (`ookla`, `cloudflare`, `fastcom`, `rtr`, `iperf`) bufferbloat osztályzattal |
| `/report [ablak]` | Legenerálja és közvetlenül elküldi a hivatalos SLA dossziét (`.html`) a csevegésbe |
| `/ai` | Szanált Markdown diagnosztikai állapotcsomag külső LLM elemzéshez |
| `/mode [auto\|a\|b]`| Megjeleníti vagy átkapcsolja a működési módot (Router vs Transzparens Híd) |
| `/vpn` | PiVPN Hub állapot: aktív WireGuard & OpenVPN alagutak, kliensek száma |
| `/vpn clients` | Csatlakoztatott kliensek listája, legutóbbi kézfogás és RX/TX forgalom |
| `/vpn qr <név>` | Kamera segítségével leolvasható QR kódot küld az azonnali mobil párosításhoz |
| `/vpn conf <név>` | Letölthető `.conf` profilt küld a csevegésbe |
| `/vpn add <név>` | Új VPN kliens profilt hoz létre és visszaküldi a beállításokat |
| `/adblock` | DNS Sinkhole státusz: mai kérések, blokkolt kérések, szűrési arány, doménszám |
| `/adblock on\|off` | Be- vagy kikapcsolja a DNS reklámszűrőt |
| `/lang [hu\|en\|de\|fr\|uk]` | Átkapcsolja a bot nyelvét a támogatott 5 nyelv valamelyikére |

---

## 20. Telepítés és Beüzemelés (Quickstart)

### Hardverkövetelmények
* **Kipróbált**: Raspberry Pi 4 (Debian 13). A kevesebb memóriájú vagy 32 bites hardver nincs tesztelve.
* **Ajánlott (Teljes Router Módhoz)**: Raspberry Pi 4 / 5, vagy x86-64 mini PC (pl. Intel N100) legalább **2 fizikai Ethernet porttal** (1x WAN, 1x LAN) és Wi-Fi csatolóval.

### Automatikus Telepítés
Futtassa a telepítőt. Szimulált környezetben tesztelve ezekkel az operációs rendszerekkel PC-n: Debian 13, Debian 12, Ubuntu 26.04 LTS, Ubuntu 24.04 LTS, Ubuntu 22.04 LTS, Fedora 45, AlmaLinux 10 és Rocky Linux 10 (a RHEL 10 helyett) és Alpine 3.22 / 3.20 (x86-64), valamint Raspberry Pi 4-en Debian 13-mal (lásd: Tesztelési Állapot):

```bash
# Klónozza a tárolót
git clone https://github.com/4r04x4t/NetworkMeasureBox.git
cd NetworkMeasureBox

# Telepítő futtatása root jogosultsággal
sudo ./setup.sh
```

A telepítő szkript automatikusan elvégzi a következőket:
1. Telepíti a szükséges hálózati és diagnosztikai eszközöket (`iproute2`, `iptables`, `nftables`, `ethtool`, `pciutils`, `usbutils`, `dnsmasq`, `hostapd`, `ppp`, `speedtest`).
2. Létrehozza az `/opt/nmb` könyvtárstruktúrát és a `/usr/local/bin/` CLI parancsokat.
3. Beállítja a microSD kímélő tmpfs meghajtókat (`/var/lib/nmb/live/`).
4. Alkalmazza a kernel szintű hálózati és memóriagyorsításokat (BBR torlódásvezérlés, 10G socket pufferek, ICMP jogosultságok).
5. Engedélyezi és elindítja a `systemd` háttérfolyamatokat (`nmb.target`).

### Első Lépések a Telepítés Után
A telepítés befejeztével nyissa meg a böngészőjében a WebGUI-t közvetlenül (port megadása nélkül):
```
http://<az-eszköz-ip-címe>/
```
* **Bejelentkezési adatok**: `admin` / `admin`, kivéve ha `RANDOM_ADMIN_PASSWORD=1` értékkel telepíted (mentve a `/var/lib/nmb/credentials.txt` fájlba; a boot-partíciós másolatról lásd: Biztonsági Modell).
  * Felhasználónév: `admin`
  * Jelszó: `admin` (a Beállítások fülön azonnal megváltoztatható!)
* Állítsa be az előfizetői szerződésében szereplő adatokat (névleges és garantált letöltés/feltöltés), válassza ki a hálózati kártyák szerepköreit, és az eszköz máris megkezdi a folyamatos mérést és adatgyűjtést!

---

## Licenc
A projekt az **MIT Licenc** alatt érhető el — szabadon használható, módosítható és beépíthető mind magáncélú, mind kereskedelmi környezetben.

---

## Tesztelési Állapot

Ami ténylegesen futott, hogy el tudd dönteni, mire támaszkodhatsz. A részletes jegyzőkönyv (hol, mit, hogyan, milyen eredménnyel): [docs/TESTING.hu.md](docs/TESTING.hu.md).

**Tesztvonal:** az NMB-t egyetlen otthoni optikai (FTTH) internetkapcsolaton fejlesztjük és teszteljük: 1000/300 Mbps-os csomag, magyar szolgáltatónál, a box az otthoni router, egy GL.iNet Flint 4 mögött. A README-ben és a tesztelési jegyzőkönyvben szereplő minden sebesség-, CPU- és időadat erről a vonalról és egy Raspberry Pi 4-ről származik. Sokkal lassabb (DSL, mobilnet) és gyorsabb (2,5 vagy 10 Gbps) vonalon nincs tesztelve; kb. 1 Gbps fölött előbb a Pi 4 egyetlen gigabites portja és a CPU-ja lesz a korlát, mint a vonal.

| Terület | Állapot |
|---|---|
| Raspberry Pi 4, Debian 13, `standalone` mód | Napi használatban |
| Tiszta telepítés, x86-64 | Szimulált környezetben tesztelve ezekkel az operációs rendszerekkel PC-n: Debian 13, Debian 12, Ubuntu 26.04 LTS, Ubuntu 24.04 LTS, Ubuntu 22.04 LTS, Fedora 45, AlmaLinux 10 és Rocky Linux 10 (a RHEL 10 helyett) és Alpine 3.22 / 3.20. Telepítés, szolgáltatások, webes felület, valódi sebességmérés, újratelepítés és (Alpine-on) újraindítás |
| `mode_a` router és `mode_b` híd | Virtuális gépeken tesztelve, DHCP-vel, NAT-tal, DMZ-izolációval és kliensforgalommal. Raspberry Pi hardveren nem |
| Wi-Fi hozzáférési pont | WPA2 2,4 és 5 GHz-en, WPA3 2,4 GHz-en, szimulált rádiókkal és valódi klienssel. A Raspberry Pi 4 rádióján: router mód, 2,4 GHz, 802.11n, 20 MHz, egy telefon és egy laptop böngészett (2026-11-08); 5 GHz és Wi-Fi 5/6 még nem. Csak router módban fut; standalone és híd módban a rádió az otthoni Wi-Fi kliense marad |
| Wi-Fi 7, 6 GHz, 160/320 MHz | Nincs igazolva. A Debian 13 hostapd-ja elutasította a Wi-Fi 7 beállításokat, ezért az NMB régebbi szabványra lép vissza |
| PPPoE | Tárcsázás és vonalszakadás utáni újratárcsázás szimulált szolgáltatóval tesztelve. Valódi vonalon nem |
| VLAN, Multi-WAN terheléselosztás, link aggregáció | A kód megvan, valódi vonalon nincs tesztelve |
| Más disztribúciók (például Raspberry Pi OS, Arch), 32 bites rendszerek | Nincs tesztelve; a telepítő Debian-alapú rendszert, Fedorát, RHEL-t és klónjait, valamint Alpine-t támogat |
| 512 MB RAM-os eszközök | 512 MB-os virtuális gépen tesztelve: 25 perc percenkénti méréssel, memóriahiány miatti leállítás és swap-használat nélkül |
| Újratelepítés és frissítés `setup.sh`-val | Ubuntu 26.04-en, Alpine 3.22-n és Rocky Linux 10-en tesztelve: a beállítások és mérések megmaradtak, a törölt fájlok eltűntek, újraindítás után minden szolgáltatás fut |
| Frissítés a GitHubról (Git nélküli telepítés) | Csak egységtesztek (letöltés, biztonságos kicsomagolás, tesztkapu, állapot). A valódi tárolóval még nem futott |
| Központi gyűjtő és távoli irányítás | Valódi gyűjtővel és box-klienssel egy gépen tesztelve: feltöltés, keresés ügyszámra, CSV, diagnosztika csak hozzájárulással, távoli sebességmérés, elutasítás hozzájárulás nélkül, más oldalról érkező kérések elutasítása. Két gép között még nem futott |
| WireGuard és OpenVPN szerver, HTTPS-proxy | Virtuális gépen tesztelve valódi klienssel: alagút, internet és webes felület az alagúton át |
| Vendég Wi-Fi kliens | Virtuális gépen tesztelve szimulált hálózattal. NetworkManager kell hozzá |
| Önfrissítés visszaállítással | Git-checkoutból virtuális gépen tesztelve: a jó frissítés települ, a hibás visszaáll |
| DuckDNS | Csak rossz tokennel tesztelve (elutasítja) |
| Telegram, SMTP, Tailscale, OONI | Valódi fiókkal nincs tesztelve |

Az NMB személyes projekt, nem hitelesített mérőeszköz. Az eredményei alátámaszthatnak egy panaszt, de nem helyettesítik a hatóság vagy a szolgáltató saját mérését.

---

## Biztonsági Modell

* **Webszerver felhasználója**: az `nmb-web` az `nmb` felhasználóként fut, csak a szükséges hálózati képességekkel. A saját szolgáltatásait és az újraindítást polkit engedélyezi, a többi kiemelt feladatot az `nmb-helper` végzi. Emiatt a CLI Terminal és a folyamatkezelő nem tud rootként műveletet végezni. A 0.105-ös polkittal (Ubuntu 22.04) a szabály nem tud szolgáltatásnév szerint szűrni, ezért ott az `nmb` bármely systemd-szolgáltatást kezelheti.
* **Nyilvános címek**: az `nmb-guard` tiltja a 80-as, 53-as és 5201-es portot nyilvános IPv4- és IPv6-címekről. A helyi hálózat, a VPN és a Tailscale továbbra is működik, és a doboz saját kimenő méréseit ez nem érinti. Systemd és `nftables` kell hozzá, ezért Alpine-ra nem települ.
* **Boot-partíció**: a `/boot/firmware/nmb.conf` másolatban a jelszavak és tokenek helyén `__KEEP_CURRENT__` látszik. Ha így hagyod, megmarad az érték, ha átírod, az új érvényes. Az `nmb_credentials.txt` csak addig marad ott, amíg a jelszó az alapértelmezett, vagy telepítéskor generált.
* **Veszélyes műveletek**: a gyári visszaállításhoz parancssorban `--yes`, API-n `RESET` kell. Az adatok és naplók törléséhez `PURGE` kell.
* **Letöltések**: az Ookla-csomag csak egyező SHA-256 esetén települ.
* **Eredmények jelszó nélkül** (választható, alapból ki van kapcsolva): ha a `[web]` részben `public_results = true` (Beállítások → rendszergazdai fiók), a helyi hálózat vagy a VPN eszközei bejelentkezés nélkül megnyithatják a `/results` oldalt, és letölthetik a riportot és a CSV-fájlokat. Például akkor, ha a box másnál van, és ő küldi el az eredményeket egy szakembernek. Csak ezek az olvasható oldalak nyílnak meg; a beállításokhoz, a mérés indításához és a diagnosztikai csomaghoz továbbra is jelszó kell, nyilvános címről pedig mindig.
* **Központi gyűjtő** (választható, alapból kikapcsolt): csak akkor küld, ha a gazda bekapcsolja, és a teljes diagnosztikához és a távoli irányításhoz külön-külön hozzájárulás kell. A távoli irányítás zárt lista (sebességmérés, diagnosztika, feltöltés); a box kérdezi a gyűjtőt, így nem nyílik port. A gyűjtő a tokeneket és az admin jelszót csak hash-ként tárolja, más oldalról érkező admin űrlapot elutasít, a token pedig a boot-partíciós másolatban ki van takarva.
* **Tor**: az OONI csomag felrakja a Tor-t, de a telepítő letiltja a szolgáltatást, mert az NMB nem használja.
* **Nincs titkosítás**: a webes felület alapból HTTP-t használ, ezért csak megbízható hálózaton vagy VPN-en keresztül használd.

---

## Változásnapló

A változások a [CHANGELOG.md](CHANGELOG.md) fájlban találhatók.
