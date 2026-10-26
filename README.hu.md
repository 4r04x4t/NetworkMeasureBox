# NetworkMeasureBox (NMB) — Részletes Rendszerdokumentáció

> **Ipari szintű, autonóm hálózati minőségmérő, SLA-hitelesítő, szolgáltatói hibabizonyító és intelligens router célszoftver.**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Platform: Linux](https://img.shields.io/badge/Platform-Linux%20%28Debian%20%7C%20Alpine%20%7C%20OpenWrt%20%7C%20Arch%29-green.svg)](https://kernel.org)
[![Python: 3.9+](https://img.shields.io/badge/Python-3.9%2B%20%28Zero%20External%20Pip%20Deps%29-yellow.svg)](https://python.org)
[![Hardware: 512MB+ RAM](https://img.shields.io/badge/RAM-512MB%20to%2064GB-purple.svg)](#6-alacsony-memóriájú-és-beágyazott-architektúra-512-mb-ram-optimalizáció)
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
10. [Hivatalos Dosszié (Bizonyító Riport) és Távfelügyelet](#10-hivatalos-dosszié-bizonyító-riport-és-távfelügyelet)
11. [Parancssori Eszközök (CLI) és Szolgáltatások](#11-parancssori-eszközök-cli-és-szolgáltatások)
12. [Telepítés és Beüzemelés (Quickstart)](#12-telepítés-és-beüzemelés-quickstart)

---

## 1. Mi ez az egész? (A projekt célja és küldetése)

A **NetworkMeasureBox (NMB)** egy olyan nyílt forráskódú, professzionális, folyamatosan futó célszoftver és hardver-illesztő réteg, amely véget vet az internetszolgáltatókkal (ISP) folytatott szubjektív vitáknak.

### A probléma
Amikor egy internetkapcsolat akadozik, csomagokat veszít, késleltetési tüskékkel küzd, vagy az esti órákban a szerződésben vállalt garantált sávszélesség töredékére zuhan, a szolgáltatói ügyfélszolgálat reakciója szinte kivétel nélkül:
> *"Nálunk a vonal rendben van, a hiba biztosan az Ön belső hálózatában, a routerében vagy a Wi-Fi-jében keresendő."*

Egyedi, manuálisan futtatott böngészős sebességtesztekkel a felhasználó tehetetlen: nincs folyamatos audit napló, nem látható a mikroszakadások időpontja, és nem bizonyítható a szolgáltató felé a szerződésszegés vagy a forgalomkorlátozás (net-neutrality throttling).

### A megoldás
A NetworkMeasureBox egy olcsó, energiatakarékos céleszközön (pl. Raspberry Pi, x86 mini PC, Odroid vagy egy meglévő, akár 512 MB RAM-os Linux/OpenWrt routeren) a nap 24 órájában, az év 365 napján automatikusan felügyeli és dokumentálja az internetkapcsolatot:
1. **Objektív bizonyítékot gyűjt**: Rögzíti az összes késleltetést, mikroszakadást, jittert és sávszélesség-ingadozást.
2. **Közvetlenül a vonalon mér**: Képes routerként (Mode A) vagy passzív, láthatatlan inline hídként (Mode B) üzemelni a modem és a router között, így kiküszöböli a belső hálózati zavaró tényezőket.
3. **Nem zavarja a felhasználót**: A beépített intelligens forgalmi kapu (Traffic Gate) csak akkor indít nagy sávszélességű tesztet, ha a vonal éppen üres (< 500 kbps), így nem szakítja meg a videóhívást vagy az online játékot.
4. **Hivatalos bizonyító dossziét generál**: Egyetlen gombnyomással jogi/hatósági szintű, önállóan megnyitható HTML jelentést állít elő beágyazott vektoros SVG diagramokkal és az előfizetői szerződéshez viszonyított SLA-megfelelőségi táblázattal, amelyet közvetlenül be lehet nyújtani hibajegyként a szolgáltatónak, vagy vita esetén a Nemzeti Média- és Hírközlési Hatóságnak (NMHH).

---

## 2. Főbb Képességek és Funkciók

* **Zéró Külső Python Függőség (Zero Pip Dependencies)**: A teljes kód kizárólag a Python 3 szabványos könyvtáraira (`sqlite3`, `http.server`, `urllib`, `socket`, `ctypes`) és natív Linux segédprogramokra épül. Nincs szükség `pip install`-ra, így korlátozott beágyazott rendszereken is azonnal indul.
* **Kettős Működési Mód**:
  * **Mode A (Aktív Router / Gateway)**: Teljes értékű router PPPoE tárcsázással, VLAN tageléssel, NAT masquerade-del, DHCP kiszolgálóval (`dnsmasq`), CAKE / fq_codel QoS-szel és Wi-Fi 6/6E/7 hozzáférési ponttal (`hostapd`).
  * **Mode B (Passzív Transzparens Híd / Inline Bridge)**: Két fizikai interfész közötti transzparens híd (`br0`), zéró IP interferenciával, teljesen láthatatlanul a hálózat számára.
* **Több Hálózati Kártya és Port Kezelése (Multi-NIC Matrix)**:
  * Tetszőleges számú fizikai hálózati kártya (PCIe, USB, alaplapi) kezelése.
  * **Multi-WAN**: Elsődleges WAN és Másodlagos WAN (WAN2) támogatás failover (tartalék) vagy loadbalance (terheléselosztás) módban.
  * **Multi-LAN Híd (`br-lan`)**: Több fizikai LAN port automatikus összefogása egységes Linux hálózati híddá.
  * Dedikált DMZ, Vendég Wi-Fi szonda és interfész-specifikus sebességmérés.
* **Automatikus Driver- és Firmware-Kezelés**:
  * Hardveres vezérlőfelismerés (Realtek, Intel, Broadcom, MediaTek, Qualcomm Atheros, Aquantia, ASIX stb.).
  * Kernel `dmesg` figyelése hiányzó firmware-ek azonnali észleléséhez.
  * Egykattintásos driver/firmware telepítő (Debian `apt`, OpenWrt `opkg`, Alpine `apk`, Arch `pacman`, Fedora `dnf`) élő terminálablakkal a WebGUI-ban.
* **5 Párhuzamos Sebességmérő Motor**:
  1. **Ookla Speedtest CLI**: Hivatalos Ookla mérőmotor automatikus szerverválasztással vagy testreszabott szerverazonosítóval.
  2. **Cloudflare Speed Engine**: Hivatalos Cloudflare CDN 100 MB / 25 MB multipart sávszélesség-mérés.
  3. **RTR-Netztest (RMBT)**: Az Osztrák Szabályozó Hatóság (RTR) és az európai BEREC szabványos RMBT mérőmotorja.
  4. **iPerf3 Kliens és Szerver**: Helyi és távoli iPerf3 audit TCP/UDP protokollal, állítható szálakkal.
  5. **Net-Neutrality Portfojtás-Ellenőrző**: Célzott tesztek specifikus portokon (HTTP 80, HTTPS 443, Alt-HTTP 8080, SSH 22, BitTorrent, SIP/VoIP).
* **Sub-second ICMP Ping Szonda (`nmb-probe`)**: 500 ms-os folyamatos mintavételezés, RFC 3550 jitter számítás, p95/p99 késleltetés, több referencia-célpont (ISP átjáró, Cloudflare 1.1.1.1, Google 8.8.8.8, Quad9 9.9.9.9) és kimaradási ablakok naplózása.
* **512 MB RAM Beágyazott Rendszer Optimalizáció**: Dinamikus memóriaprofilok (`embedded`, `standard`, `performance`), szigorú SQLite live méretkorlátok (48 MB), periodikus és kézi `malloc_trim(0)` memóriafelszabadítás router platformokon.
* **Flash- és SD-Kártya Élettartam Védelem**: Élő adatbázis memóriában futó tmpfs-en, 15 percenkénti és leállításkori atomi pillanatképek SD-re, ext4 `noatime,commit=600`, swap tiltás.
* **Hálózatfelderítő (Device Explorer)**: Beépített ARP sweep és MAC OUI vendor felismerés (Apple, Samsung, Intel, Xiaomi stb.) a helyi és a vendéghálózaton.
* **Dedikált Vendég Wi-Fi Kliens Szonda**: Másodlagos vezeték nélküli interfésszel automatikusan felkapcsolódik a router vendég Wi-Fi hálózatára, és ellenőrzi annak sávszélességét, stabilitását és izolációját.
* **Többnyelvű Reszponzív WebGUI**: Sötét módú irányítópult, 14+ kategória, valós idejű SVG diagramok, jelszavas védelem, Logout funkció és 100%-os kulcsparitású fordítás 5 nyelven (magyar, angol, német, ukrán, francia).
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
│  │ • /proc/net/dev üresjárati kapu (<500 kbps)  │          │ • Önmagában álló HTML jelentés vektoros SVG-vel  │  │
│  │ • 5 motor: Ookla, Cloudflare, RTR, iPerf, FW │          │ • RFC 4180 CSV telemetria exportáló              │  │
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
│  │ • /status, /ping, /test, /report, /mode      │          │ • Reszponzív sötét felület a 8080-as porton      │  │
│  │ • Azonnali push riasztások kimaradáskor      │          │ • 14+ alrendszer, 5 nyelvű fordítás, Logout     │  │
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
| **QoS / Bufferbloat védelem** | Igen (CAKE / fq_codel SQM) | Nincs |
| **Láthatóság a hálózaton** | Routerként látható | Teljesen láthatatlan (Layer 2 bridge) |
| **Üzemszünet-kockázat** | Ha leáll, nincs net | Szoftveres hiba esetén szoftverhíd, bypass hardverrel átenged |

---

## 4. Több Hálózati Kártya, Port Mátrix és Driver Támogatás

A NetworkMeasureBox rugalmas hálózati architektúrával rendelkezik, amely képes kezelni tetszőleges számú fizikai hálózati kártyát (PCI, PCIe, USB Ethernet adapterek, alaplapi portok, Wi-Fi kártyák):

### 1. Interfész Szerepkör Mátrix (Port Role Matrix)
A WebGUI **Beállítások ➔ 🔀 Portok és Illesztőprogramok** menüpontjában egy interaktív mátrix jelenik meg, ahol a felhasználó közvetlenül kioszthatja a portok szerepköreit:
* **🌐 WAN 1 (Elsődleges Internet)**: A fő internetkapcsolat (DHCP, PPPoE vagy Statikus IP).
* **🌐 WAN 2 (Másodlagos Internet)**: Tartalék (Failover) vagy Kettős aktív terheléselosztású (Load Balancing) kapcsolat. Külön állítható DHCP vagy statikus IP paraméterekkel.
* **🏠 LAN (br-lan Híd)**: Bármennyi fizikai Ethernet port kijelölhető belső hálózatként. Az NMB automatikusan létrehozza a Linux hálózati hidat (`br-lan`), hozzáadja a kiválasztott portokat, és a hídra köti a DHCP kiszolgálót (`192.168.100.1/24`) és a NAT masquerade-et.
* **📶 Vendég Wi-Fi Kliens**: Dedikált Wi-Fi interfész a fő router vendéghálózatának ellenőrzésére.
* **🛡️ DMZ (Izolált port)**: Külön alhálózat izolált eszközök számára.
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
* Képes a legközelebbi vagy automatikus szerver használatára, illetve rögzített szerver ID megadására (pl. magyarországi Telekom, DIGI, Yettel, Vodafone / One szerverek).
* Letöltési, feltöltési sebesség és terhelés alatti késleltetés (bufferbloat) mérése.

### 3. Cloudflare Speed Engine
* A Cloudflare globális CDN hálózatát használó, több szálon futó (multipart) mérőmotor.
* 100 MB-os és 25 MB-os valós adatcsomagok letöltése és feltöltése a legközelebbi Cloudflare edge pontról.

### 4. RTR-Netztest (RMBT Szabályozói Mérőmotor)
* Az Osztrák Hírközlési Szabályozó Hatóság (RTR) és az Európai Elektronikus Hírközlési Szabályozók Testülete (BEREC) által elfogadott, RFC kompatibilis RMBT nyílt forráskódú mérőmotor.
* Hiteles, független, szolgáltatói befolyástól mentes mérést biztosít.

### 5. iPerf3 Helyi és Távoli Tesztek
* Beépített iPerf3 kliens és felügyelt iPerf3 háttérszerver.
* Lehetővé teszi a belső hálózat (LAN kábel, Wi-Fi AP) maximális throughputjának kimérését, valamint nyilvános iPerf3 szerverek tesztelését TCP és UDP protokollon, tetszőleges párhuzamos szálakkal.

### 6. Net-Neutrality Portfojtás-Ellenőrző (Traffic Shaping Checker)
* Ellenőrzi, hogy a szolgáltató mesterségesen fojtja-e a sávszélességet vagy blokkol-e bizonyos típusú forgalmat.
* Párhuzamosan teszteli a HTTP (80), HTTPS (443), Alt-HTTP (8080), SSH (22), BitTorrent és VoIP portokat.

### 7. Traffic Gate (Forgalmi Kapu)
* Az automatikus mérések előtt az NMB megvizsgálja a `/proc/net/dev` számlálóit.
* Ha a belső hálózaton a felhasználói forgalom meghaladja a beállított küszöbértéket (alapértelmezetten 500 kbps), a teszt elhalasztásra kerül, így a mérés soha nem okoz akadást a felhasználónak.

---

## 6. Alacsony Memóriájú és Beágyazott Architektúra (512 MB RAM Optimalizáció)

A szoftver architektúrája kifejezetten úgy lett felépítve, hogy akár **512 MB RAM-mal rendelkező beágyazott routereken** (pl. ASUS vagy egyéb OpenWrt/Debian router célrendszer) is megbízhatóan, memóriaszivárgás nélkül működjön.

### Memóriaprofilok (`memory_profile`)

A konfigurációban vagy a WebGUI-ban három profil választható:

```ini
[system]
memory_profile = auto   # auto, embedded, standard, performance
```

1. **`embedded` profil (< 768 MB RAM, kifejezetten 512 MB routerekre)**:
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
4. **Naplózás és Swap**: A swap kikapcsolásra kerül; a `systemd-journald` kizárólag illékony memóriába (`Storage=volatile`) naplóz, a `/var/log` és `/tmp` könyvtárak tmpfs-en futnak.

---

## 8. Beépített Webes Felület (WebGUI) és Többnyelvűség

A beépített webes felület a **8080-as porton** érhető el, teljesen reszponzív, modern sötét dizájnnal és 14 dedikált kategóriával rendelkezik:

1. **Irányítópult (Dashboard)**: Legutóbbi mérések összefoglalása, SLA státusz, egykattintásos mérésindítás, interfész-választó és élő végrehajtási terminál.
2. **Ping Telemetria (ICMP Ping)**: Valós idejű vektoros SVG késleltetési grafikon, csomagvesztés, p95/p99 statisztikák, CSV export.
3. **Sebességteszt Eredmények**: Részletes audit napló letöltési/feltöltési sebességgel, bufferbloat pontszámmal és mérőmotor jelöléssel.
4. **iPerf3 Hálózati Sebesség**: Helyi és távoli iPerf3 audit, beépített iPerf szerver indítása/leállítása.
5. **Hálózati Kimaradások**: Minden egyes internetkiesés audit naplója (kezdet, vég, időtartam, kiesett csomagok).
6. **SLA Megfelelőség & Szerződés**: A valós mérések összehasonlítása az előfizetői szerződésben garantált és névleges értékekkel.
7. **Traceroute & Útvonal Elemzés**: Vizuális útvonalkövetés ugrásonkénti késleltetéssel (MTR jellegű analízis).
8. **Portfojtás (Net-Neutrality)**: Forgalomkorlátozás ellenőrzése portonként.
9. **RTR-Netztest (RMBT)**: Európai hatósági szabványú nyílt sebességmérés.
10. **Hálózatfelderítő (Device Explorer)**: Csatlakoztatott klienseszközök, ARP leltár, MAC gyártóazonosítás.
11. **Fejlesztői Mélykonzol**: Valós idejű rendszernapló (Syslog) és belső modul-napló élő streameléssel.
12. **AI Diagnosztika (LLM Snapshot)**: Egyetlen gombnyomással másolható szanált Markdown diagnosztikai köteg ChatGPT, Claude vagy Gemini mélyelemzéshez.
13. **Beállítások & Router Konfiguráció**:
    * WAN beállítások (DHCP, PPPoE VLAN-nal, Statikus IP, Egyedi WAN MAC cím klónozás).
    * LAN beállítások (Gateway IP, DHCP tartomány, bérleti idő).
    * Wi-Fi 6/6E/7 beállítások (SSID, jelszó, 2.4/5/6 GHz, csatornaszélesség, WPA2/WPA3).
    * **🔀 Portok és Illesztőprogramok**: Multi-NIC szerepkör mátrix, WAN2 failover/loadbalance, LAN bridge (`br-lan`), hardveres driver detektálás és egykattintásos telepítés.
    * Működési mód (Mode A / Mode B / Auto-Failover).
    * Memóriaprofilok (`embedded` 512MB, `standard`, `performance`) és RAM karbantartás.
    * CAKE / fq_codel SQM QoS beállítások.
    * Adminisztrátori hitelesítés és jelszókezelés.
14. **Kijelentkezés (Logout)**: Biztonsági kijelentkezés a böngésző hitelesítési gyorsítótárának törlésével.

### 5 Támogatott Nyelv (100%-os Kulcsparitással)
A felület jobb felső sarkában egyetlen kattintással váltható a nyelv. Az összes felirat, magyarázat és mérési státusz teljesen le van fordítva:
* 🇭🇺 **Magyar (HU)**
* 🇬🇧 **Angol (EN)**
* 🇩🇪 **Német (DE)**
* 🇺🇦 **Ukrán (UK)**
* 🇫🇷 **Francia (FR)**

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

## 10. Hivatalos Dosszié (Bizonyító Riport) és Távfelügyelet

### Hivatalos Hibajegy Dosszié (HTML/SVG Dossier)
A WebGUI-ból a `📄 Export Official Report (Dossier)` gombbal vagy parancssorból (`nmb-report --html dossier.html`) bármikor legenerálható egy független, offline működő HTML dokumentum:
* **Önmagában álló**: Nem igényel internetkapcsolatot vagy külső JavaScript könyvtárakat; minden CSS stílus és vektoros SVG diagram közvetlenül be van ágyazva a HTML fájlba.
* **SLA Összehasonlítás**: Táblázatba foglalja a szerződés szerinti maximális és garantált letöltési/feltöltési sebességet, és vörössel kiemeli a szerződésszegő méréseket.
* **Késleltetési & Szakadási Statisztika**: Havi/heti/napi bontásban mutatja a mikroszakadások idejét, a csomagvesztést és a jittert.
* **Közvetlenül csatolható**: E-mailben azonnal továbbítható a szolgáltató ügyfélszolgálatának vagy a hírközlési hatóságnak.

### E-mail (SMTP) Automatikus Értesítés
A konfigurációban megadott SMTP szerveren keresztül az NMB képes automatikusan elküldeni a napi/heti összefoglaló jelentést a felhasználónak, vagy előre megfogalmazott sablon alapján közvetlenül a szolgáltató hibabejelentő e-mail címére.

### Telegram Távfelügyelet (`nmb-telegram`)
A beépített Telegram bot daemon segítségével a felhasználó bárhonnan értesül a hálózat állapotáról:
* **Azonnali riasztások**: Push üzenetet küld, amint a kapcsolat megszakad, vagy ha a csomagvesztés meghaladja az 5%-ot.
* **Távvezérlő parancsok**:
  * `/status`: Jelenlegi hálózati mód, IP címek, utolsó mérés eredménye.
  * `/ping`: Azonnali ICMP válaszidő és csomagvesztés lekérdezése.
  * `/test`: Sebességmérés azonnali indítása távolról.
  * `/report`: Friss SLA megfelelőségi összefoglaló lekérése.
  * `/mode [auto|mode_a|mode_b]`: Működési mód távoli átkapcsolása.

---

## 11. Parancssori Eszközök (CLI) és Szolgáltatások

A szoftver moduláris felépítésű, az egyes feladatokat különálló, jól tesztelhető démonok látják el:

| Parancs / Bináris | Leírás | Gyakori Használat |
|---|---|---|
| `nmb-netd` | Hálózati üzemmód démon (Mode A / Mode B / Failover) | `nmb-netd --status`<br>`nmb-netd --switch mode_a` |
| `nmb-probe` | Nagyfrekvenciás ICMP ping és jitter szonda | `nmb-probe --verbose` |
| `nmb-speed` | Sebességmérő és forgalomkorlátozás-ellenőrző | `nmb-speed --trigger manual`<br>`nmb-speed --interface eth0`<br>`nmb-speed --engine cloudflare` |
| `nmb-report` | Riport generátor (HTML dosszié, CSV, JSON) | `nmb-report --window 24h --html dossier.html`<br>`nmb-report --json-summary` |
| `nmb-telegram` | Telegram menedzsment és riasztási bot | `nmb-telegram` |
| `nmb-web` | Beépített kezelőfelület és REST API | `nmb-web --port 8080` |
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
sudo journalctl -u nmb-speed -f
sudo journalctl -u nmb-web -f
```

---

## 12. Telepítés és Beüzemelés (Quickstart)

### Hardverkövetelmények
* **Minimális**: Bármilyen 64-bites vagy 32-bites Linux hardver legalább **512 MB RAM-mal** és 1 Ethernet interfésszel (Mode B méréshez vagy router mögötti teszthez).
* **Ajánlott (Teljes Router Módhoz)**: Raspberry Pi 4 / 5, vagy x86-64 mini PC (pl. Intel N100) legalább **2 fizikai Ethernet porttal** (1x WAN, 1x LAN) és Wi-Fi csatolóval.

### Automatikus Telepítés
Egy frissen telepített Debian, Ubuntu, Raspberry Pi OS vagy Alpine Linux rendszeren futtassa a felügyelet nélküli telepítőt:

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
A telepítés befejeztével nyissa meg a böngészőjében a WebGUI-t:
```
http://<az-eszköz-ip-címe>:8080
```
* **Alapértelmezett bejelentkezési adatok**:
  * Felhasználónév: `admin`
  * Jelszó: `admin` (a Beállítások fülön azonnal megváltoztatható!)
* Állítsa be az előfizetői szerződésében szereplő adatokat (névleges és garantált letöltés/feltöltés), válassza ki a hálózati kártyák szerepköreit, és az eszköz máris megkezdi a folyamatos mérést és adatgyűjtést!

---

## Licenc
A projekt az **MIT Licenc** alatt érhető el — szabadon használható, módosítható és beépíthető mind magáncélú, mind kereskedelmi környezetben.
