# Tesztelési jegyzőkönyv

Mit, hol, hogyan és milyen eredménnyel teszteltünk. Ha egy teszt újra lefut vagy új kerül be, ezt a fájlt is frissíteni kell. A README *Tesztelési Állapot* táblázata ennek az összefoglalója. Angol változat: [TESTING.md](TESTING.md).

Utolsó teljes kör: 2026-11-07.

## Hol futottak a tesztek

**Tesztvonal:** az NMB-t egyetlen otthoni optikai (FTTH) internetkapcsolaton fejlesztjük és teszteljük: 1000/300 Mbps-os csomag, magyar szolgáltatónál, a box az otthoni router mögött. A README-ben és a tesztelési jegyzőkönyvben szereplő minden sebesség-, CPU- és időadat erről a vonalról és egy Raspberry Pi 4-ről származik. Sokkal lassabb (DSL, mobilnet) és gyorsabb (2,5 vagy 10 Gbps) vonalon nincs tesztelve; kb. 1 Gbps fölött előbb a Pi 4 egyetlen gigabites portja és a CPU-ja lesz a korlát, mint a vonal.

| Név | Mi ez |
|---|---|
| **Box** | Raspberry Pi 4, Debian 13 (arm64), `standalone` mód, a fejlesztő routerére kötve. Napi használatban, 1000/300 Mbps-os otthoni optikai (FTTH) vonalon. |
| **VM-D13** | QEMU/KVM x86-64 PC-n, Debian 13 felhőkép a teljes `linux-image-amd64` kernellel. Két hálókártya (felhasználói NAT mint WAN, socket-kapcsolat mint LAN). Wi-Fi `mac80211_hwsim`-mel (három szimulált rádió); a kliensek hálózati névterekben. |
| **VM-disztró** | Tiszta Debian 13, Debian 12, Ubuntu 24.04 LTS és Alpine 3.20 (x86-64) virtuális gépek, mindegyik `setup.sh`-val nulláról telepítve. |
| **Unit-tesztek** | `python3 -m unittest discover tests` (223 teszt) a fejlesztői gépen és rootként a VM-D13-on. |

A szimulált azt jelenti: valódi Linux, valódi `hostapd`, `dnsmasq`, `pppd`, WireGuard és OpenVPN, de virtuális kártyák és rádiók. A valódi hardver időzítését, meghajtóit és rádiós viselkedését ez nem fedi le.

## Eredmények

Jelölés: ✅ működik · ⚠️ korláttal működik · ❌ nem működik · — nincs tesztelve

### Operációs rendszerek (VM-disztró)

| Rendszer | Tiszta telepítés | Újratelepítés | Újraindítás | Megjegyzés |
|---|---|---|---|---|
| Debian 13 | ✅ | ✅ | ✅ | A VM-D13 alapja is |
| Debian 12 (Python 3.11) | ✅ | ✅ | — | Valódi sebességmérés sikeres. Polkit-szabály ellenőrizve: az `nmb` újraindíthatja az `nmb-netd`-t, az `ssh`-t nem |
| Ubuntu 24.04 LTS | ✅ | — | — | Kártyanév-felismerés kellett (`ens3` az `eth0` helyett), javítva |
| Ubuntu 26.04 LTS (Python 3.14, polkit 127) | ✅ | ✅ | ✅ | Újratelepítés futó dobozra: a mérések megmaradtak (1 sebességmérés, a pingminták tovább gyűltek), az átírt admin jelszó megmaradt, a beállítás 0640 `nmb:nmb`, a `/opt/nmb` alá tett elavult fájl eltűnt, nincs Traceback. Az RTR-mérés rendben |
| Ubuntu 22.04 LTS (Python 3.10, polkit 0.105) | ✅ | ✅ | ✅ | A régi polkit `.pkla` szabálya kellett, hozzáadva; ott az `nmb` bármely szolgáltatást kezelhet. Az ütemezett Ookla-mérések lefutottak |
| Rocky Linux 10.2 (Python 3.12, polkit 125) | ✅ | ✅ | ✅ | Az EPEL az `ID` alapján bekapcsol; az újratelepítés megtartotta a méréseket és az átírt admin jelszót, a beállítás 0640 `nmb:nmb`, az elavult fájl eltűnt, nincs Traceback. Az RTR-mérés rendben. A 10 GB-os felhőkép legalább 10 GB-os lemezt kér (8 GB-os teszt-overlayjel nem indult el) |
| Alpine 3.22 (OpenRC, Python 3.12) | ✅ | ✅ | ✅ | Újratelepítés futó dobozra: a mérések és az átírt admin jelszó megmaradtak, a beállítás 0640 `nmb:nmb`, az elavult fájl eltűnt, nincs Traceback a `/var/log/nmb` alatt. Az RTR-mérés rendben |
| Alpine 3.20 (OpenRC) | ✅ | ✅ | ✅ | 80-as port jogosultság, RMBT-fordítás és OpenRC-újraindítás javítva |
| Raspberry Pi 4, Debian 13 | ✅ | ✅ | ✅ | A Box |
| Fedora 45 (Python 3.15, SELinux enforcing) | ✅ | — | — | Új `dnf`-ág. Minden szolgáltatás, polkit, minden választható csomag; RTR és Cloudflare mért, az Ookla CLI lefutott (az Ookla sebességkorlátja elutasította, közös IP). SELinux-tiltás nincs. Újraindítás nincs ellenőrizve |
| AlmaLinux 10.2 (a RHEL 10 helyett; Python 3.12, SELinux enforcing) | ✅ | ✅ | ✅ | EPEL kell (a `setup.sh` bekapcsolja). Javítva: a klónok `ID_LIKE` mezője „fedora”-t is tartalmaz, ezért az EPEL kimaradt; a `sudo` ott nem keres a `/usr/local/bin`-ben. A frissítéskeresés a `dnf` frissítéseit számolja. QEMU-ban SCSI-lemez kell a képhez |
| Raspberry Pi OS, Arch, 32 bites | — | — | — | Nincs tesztelve |

### Mérés

| Funkció | Hol | Eredmény | Hogyan |
|---|---|---|---|
| Ookla | Box | ⚠️ | Óránként működik. Percenként az Ookla tiltja a boxot („Limit reached”); ekkor a box szünetelteti az Ooklát (30 perc, legfeljebb 4 óra), és RTR-NetTesttel mér, az RTR saját nevén tárolva |
| RTR-NetTest | Box, VM-disztró | ✅ | ~910/320 Mbps az 1000/300-as vonalon |
| Wi-Fi megosztása LAN porton | Box (veth + hálózati névtér, az `eth0` érintetlen) | ✅ | A névtérbeli kliens DHCP-vel 192.168.77.116-ot kapott, pingelte az 1.1.1.1-et (11 ms), és 20 MB-ot töltött le HTTPS-en a `wlan0`-n át. Egy második DHCP-szervert indítva a kliens oldalán a box leállította a saját DHCP-jét, címét, NAT-ját és útválasztási szabályát; a szerver eltűnése után 15 mp-en belül újraindult. Közben javítva: a másik szerver válaszait a kernel eldobta, mielőtt egy sima sockethez értek (most csomagszintű socket); a dnsmasq akár 3 mp után ajánl (most 8 mp, három kéréssel); a `--log-facility=-` előtérben tartotta a dnsmasq-ot. Valódi kábellel, Ethernet-uplink nélkül még nincs kipróbálva |
| Mérés Wi-Fi-n (`measurement_link = wifi`) | Box | ✅ | A box az 5 GHz-es Wi-Fi-n (netplan léptette be), bedugott kábellel: egy Fast.com-mérés 149/145 MB-ot vitt a `wlan0`-n, az `eth0`-n semmit, 104/110 Mbit/s. A box saját `nmb-uplink` profiljával való csatlakozás még nincs kipróbálva |
| Fast.com | Box, fejlesztői gép | ✅ | 884/314 Mbit/s az 1000/300-as vonalon, 5 Netflix-szerver, bufferbloat A |
| Cloudflare | Box | ✅ | |
| iPerf3 | Box, VM-D13 | ✅ | |
| Ping-szonda, kiesések | Box | ✅ | Telepítés óta folyamatosan |
| Ütemezés, napi adatkeret | Box, unit-tesztek | ✅ | |
| Portellenőrzés (22, 5060, 6881, …) | Box | ✅ | |
| Forgalom miatti leállítás (kísérleti) | Box, VM-D13 | ✅ | 23–40 Mbps más forgalomra leáll; alapból ki van kapcsolva |
| DNS-eltérítés, NAT-típus | Box | ✅ | Nincs eltérítés; végponttól független NAT |

### Hálózati módok (VM-D13)

| Funkció | Eredmény | Hogyan |
|---|---|---|
| Mode A router: DHCP, NAT, internet a LAN-klienseknek | ✅ | A névtérben lévő kliens címet kapott, pingelte az internetet, HTTPS-t töltött |
| Mode B híd | ✅ | A box saját címet kap a hídon |
| DMZ-elkülönítés | ✅ | A DMZ eléri az internetet, a LAN-t és a webes felületet nem |
| PPPoE tárcsázás és újratárcsázás | ⚠️ | `pppoe-server` ellen; a box saját forgalma a `ppp0`-n ment. A LAN-kliens teljes oda-vissza útját a szimuláció saját NAT-ja miatt nem lehetett ellenőrizni |
| DHCP a box újraindítása után | ✅ | Javítva: `dhcp-authoritative`, így a régi bérletét megújító kliens azonnal választ kap |
| Valódi hardver, Nighthawk M6 Pro | — | A fejlesztő tervezi |

### Wi-Fi hozzáférési pont (VM-D13, szimulált rádiók)

| Eset | Eredmény | Hogyan |
|---|---|---|
| WPA2, 2,4 GHz | ✅ | A kliens csatlakozott, DHCP-t kapott, elérte az internetet, a HTTPS-t és a webes felületet |
| WPA2, 5 GHz (36. csatorna) | ✅ | Ugyanazok az ellenőrzések. `wireless-regdb` kell hozzá (a `setup.sh` most telepíti) |
| 5 GHz `wireless-regdb` nélkül | ✅ | A box 2,4 GHz-re vált ahelyett, hogy egyáltalán nem lenne Wi-Fi |
| WPA3 (SAE), 2,4 GHz | ✅ | Ugyanazok az ellenőrzések, mint WPA2-nél |
| Rossz jelszó | ✅ | Nincs cím, nincs forgalom |
| Wi-Fi 7 / 6 GHz / 160–320 MHz | ⚠️ | A Debian 13 `hostapd`-ja elutasítja a Wi-Fi 7 beállításokat; a box Wi-Fi 6-ra lép vissza |
| Valódi Wi-Fi hardver | — | |

### Vendég Wi-Fi kliens (a box egy másik Wi-Fi-hálózathoz csatlakozik; VM-D13)

| Eset | Eredmény | Hogyan |
|---|---|---|
| Keresés, csatlakozás, DHCP, ping | ✅ | Névtérben futó `hostapd`-hálózat ellen, a webes felület API-ján át |
| Rossz jelszó | ✅ | A hiba a NetworkManager valódi üzenetét mutatja |
| Újracsatlakozás, bontás, mentett profil | ✅ | Javítva: régi profil már nem akadályozza az újracsatlakozást; a „disconnected” állapot már nem számít csatlakozottnak |
| Jogosultság `nmb` felhasználóként | ✅ | A polkit-szabályban javítva. A Boxon még a régi szabály van, lásd *Nyitott* |
| NetworkManager nélkül | ❌ szándékosan | A funkcióhoz NetworkManager (`nmcli`) kell; a `setup.sh` nem telepíti |

### VPN és távoli elérés (VM-D13)

| Funkció | Eredmény | Hogyan |
|---|---|---|
| WireGuard szerver | ✅ | Peer a webes felületen hozzáadva, a konfigurációját névtérbeli kliens használta: alagút, internet, HTTPS és webes felület az alagúton át; peer törlése és leállítás |
| OpenVPN szerver | ✅ | Javítva: a szervertanúsítványból hiányzott a TLS-szerver felhasználás, ezért minden klienst elutasított. A régi tanúsítványt a program ugyanazzal a CA-val újra kiállítja. Kliensprofil végig tesztelve |
| HTTPS/CONNECT proxy | ✅ | Javítva: 20 s késés hibás IPv6-os hálózaton (most 0,4 s), leállítás után foglalva maradt a port, és a proxy elérte a box saját loopback-szolgáltatásait (most elutasítja) |
| DuckDNS | ⚠️ | A rossz tokent elutasítja és kijelzi. Valódi fiókkal nem próbáltuk |
| Tailscale | — | Fiók kell hozzá |

### Egyéb funkciók

| Funkció | Hol | Eredmény | Hogyan |
|---|---|---|---|
| DNS-reklámszűrő terhelés alatt | VM-D13 | ✅ | 3000 lekérdezés 50 szálon: mind megválaszolva, 6900/s, p99 72 ms, 24 MB RAM |
| Önfrissítés visszaállítással | VM-D13 | ✅ | `/opt/nmb` Git-checkoutként, helyi originnel. A jó commit települt; a bukó tesztet tartalmazó commit után visszaállt. Javítva: három teszt a géptől függött, ezért valódi boxon minden frissítés visszaállt volna; a `--json` kimenet nem volt tiszta JSON |
| Webes felület, beállítások mentése és újratöltése | Box, VM-disztró | ✅ | |
| Eredmények jelszó nélkül (`public_results`) | Box, helyi példány, unit-tesztek | ✅ | A Boxon ki van kapcsolva: a `/results` 401-et ad. Bekapcsolva a `/results`, a riport és a CSV-fájlok bejelentkezés nélkül megnyílnak a LAN-ról; a `/`, az `/api/config`, az `/api/status` és minden POST továbbra is 401; a kikapcsolás a webes felületről mentődik |
| Ookla ütemezési figyelmeztetés | Box, unit-tesztek | ✅ | A Box (minden motor percenként) `ookla_rate_limit_risk`-et jelez; óránkénti vagy csak RTR-es ütemezésnél nincs figyelmeztetés |
| Gyári visszaállítás | VM-D13 (korábbi kör), unit-tesztek | ✅ | `--yes` kell hozzá |
| `nmb-cli` TUI | Box, unit-tesztek | ✅ | |
| Biztonság: tűzfal, `nmb`-ként futó webszerver, titkok a boot-partíción | VM-disztró, Box | ✅ | |
| Kernel hálózati finomhangolás | Box, VM-disztró | ✅ | Az `nmb-netd` (root) végzi |
| Telegram bot és riasztások | Unit-tesztek | ⚠️ | Valódi bottal nem |
| SMTP, OONI, meghajtócsere | — | — | |
| 512 MB RAM | VM-D13 (463 MB használható) | ✅ | 25 perc, minden szolgáltatás, percenkénti mérés: 26-ból 26 mérés sikeres, 182–222 MB szabad, nincs swap, nincs OOM, nincs újraindulás; webszerver 40 MB, szonda 31 MB, egyik sem nő |
| Mentés és visszaállítás | VM-D13 | ✅ | Létrehozás, letöltés, listázás, visszaállítás a listából és feltöltött fájlból; a beállítás és minden mérés visszajön; a csonka feltöltést elutasítja, és nem változtat semmit. Javítva: a visszaállított adatbázist a régi `-wal` napló eltüntethette, a régebbi boot-partíciós másolat felülírta a visszaállított beállítást, az `nmb` nem tudta olvasni a visszaállított beállítást, és a feltöltött mentést bárki olvashatta |
| Áramszünet | VM-D13 | ✅ | A QEMU leállítva futó mérés közben és rögtön egy mentés indítása után: mindkét adatbázis átmegy az `integrity_check`-en, a beállítás ép, minden szolgáltatás fut; a félbeszakadt mérés egyszerűen hiányzik. A mentés atomikus (ideiglenes fájl, fsync, átnevezés). Legfeljebb 15 perc eredménye veszhet el, ez a tmpfs miatt szándékos |
| Ookla a dobozon: választott szerver, szünet, nincs helyettesítés | Box, egységtesztek | ✅ | A dobozon derült ki: a beépített Yettel-azonosító (10390) rossz volt („No servers defined”), a szünetelő Ooklát RTR-eredmény helyettesítette, a szünet újraindításkor elveszett, és az `/api/status` hibát adott egy sikertelen mérés után. Mind javítva; a szünet újraindítás után is megmarad, és szünet alatt nem kerül be sor |
| Motoronkénti időköz | Egységtesztek | ✅ | 30 perces RTR 30 percen belül kimarad, utána fut; 0 esetén minden alkalommal fut; az Ookla 60 perc alá nem állítható |
| Frissítés a GitHubról (Git nélküli telepítés) | Egységtesztek | ⚠️ | Biztonságos kicsomagolás (útvonal-kiszökés elutasítva), ellenőrzés a GitHub ellen (szimulálva), állapotfájl, root- és commit-ellenőrzés. A valódi tárolóval dobozon még nem futott |
| Újratelepítés `setup.sh`-val | VM-distro (Ubuntu 26.04, Alpine 3.22, Rocky 10) | ✅ | A beállítások, az admin jelszó és a mérések megmaradtak; a `/opt/nmb` alá tett elavult fájl eltűnt; a beállítás 0640 `nmb:nmb` |
| Központi gyűjtő és távoli irányítás | Helyi gyűjtő és box-kliens, egységtesztek | ✅ | Feltöltés (ismétlés nem duplikál), keresés ügyszámra, korábbi ügyszámra és ügyfélszámra, CSV, diagnosztika és események csak hozzájárulással, távoli sebességmérés lefut és visszajelez, parancs elutasítva hozzájárulás nélkül vagy más oldalról, ismeretlen parancs mindkét oldalon elutasítva, titkok hash-ként (0600). Két gép között még nem futott |

## Jelöltek

### Operációs rendszerek

Abból gyűjtve, mit ismer fel a `setup.sh`, és mire van szüksége a kódnak (futáskor Python 3.10 vagy újabb, csak a standard könyvtár, systemd nftables-szel, vagy Alpine OpenRC-vel).

| Rendszer | Várható | Miért | Hogyan tesztelhető |
|---|---|---|---|
| Raspberry Pi OS (arm64), Lite | Működnie kell | Debian 13 alapú, mint a Box | Pi-n, vagy Debian arm64 QEMU alatt |
| Raspberry Pi OS (armhf, 32 bites) | Nem tudni | Az Ooklát és az RMBT-t csak arm64-en és x86-64-en futtattuk | Pi 2/3/Zero 2-n |
| Armbian, DietPi | Működnie kell | Debian-alapú képek más egykártyás gépekre | A lapkán, vagy x86-os képükkel |
| Linux Mint 22, Pop!_OS | Működnie kell | Ubuntu 24.04 alapú; az asztali NetworkManager lefoglalhatja a portokat | VM |
| Devuan | Elutasítva | Nincs systemd; a `setup.sh` most érthető üzenettel leáll | — |
| Arch, Manjaro, openSUSE, Void, NixOS | Nem támogatott | Más csomagkezelő vagy init-rendszer | Portolás kell |
| OpenWrt | Nem támogatott | A natív újraírásban tervezett, lásd `ROUTER_PORTING_AND_DEPYTHONIZATION_PLAN.md` | — |

### Még nem tesztelt funkciók és helyzetek

Virtuális gépen elvégezhető:

- **Kevés memória, hosszabban:** az 512 MB 25 percen át átment; a 24 órás futás még hátravan.
- **Hosszú futás:** 24–72 óra percenkénti mérésekkel; memórianövekedés, adatbázisméret, naplóforgatás.
- **Régebbi kiadás mentése:** 2.4.0-s mentés visszaállítása.
- **Frissítés régebbi kiadásról:** 2.4.0 telepítése, majd frissítés a mostanira a konfiguráció megtartásával.
- **WAN-átállás és multi-WAN terheléselosztás:** két WAN-kártya, az egyik kihúzása.
- **VLAN, link aggregáció, átengedés:** szimulált switch-csel (VLAN-szűrős Linux-híd, bondolt ellenoldal).
- **Ellenséges hálózatok:** csak IPv6-os WAN, CGNAT, hibás DNS, captive portal, ugráló kapcsolat, óraugrás (a Pi-nek nincs órája elemmel).
- **Telegram és SMTP** helyi álszerverek ellen.
- **Traceroute, csomagfigyelő, OONI, jelentéskészítés, meghajtótelepítő.**
- **Webes felület:** az öt nyelv teljessége, több egyidejű felhasználó, ismételt rossz bejelentkezés, valamint Firefox, Chrome és telefonos böngésző.

Hardver vagy fiók kell hozzá:

- Valódi Wi-Fi rádiók (2,4/5/6 GHz, Wi-Fi 6/7), valódi PPPoE-vonal, a Nighthawk M6 Pro, USB-s Ethernet-adapter, Pi 5.
- Tailscale, valódi DuckDNS-domain, valódi Telegram-bot.

## Nyitott

- **A Boxon még a régi polkit-szabály van.** Ott a vendég Wi-Fi a webes felületről „network-control: auth” hibával nem megy, amíg az új `os/90-nmb.rules` nincs telepítve (`setup.sh` újrafuttatása, vagy másolás az `/etc/polkit-1/rules.d/` mappába).
- Nincs tesztelve: a portok megnyitása firewalldben (a Fedora és az AlmaLinux felhőképén nem futott).
- Nincs tesztelve: Debian 12 és Fedora újraindítás, Tailscale, valódi Telegram bot, SMTP, OONI, valódi Wi-Fi és PPPoE hardver.
- Élesben még nem futott: a GitHubos frissítés dobozon (megvárja, amíg a mostani kód felkerül a GitHubra, különben a doboz régebbi verzióra lépne vissza), és a központi gyűjtő két gép között.
- Wi-Fi-s mérés: kábel nélkül a box már most Wi-Fi-n mér (az alapértelmezett útvonalra esik vissza); a Wi-Fi-s mérés bedugott kábel mellett, a kettő egyszerre, és a box mint Wi-Fi–Ethernet átalakító még tervezésre vár.

## Újrafuttatás

- Unit-tesztek: `python3 -m unittest discover tests` (kb. 3 perc).
- Az itt használt VM-szkriptek nincsenek a repóban; minden sor leírja, mi volt beállítva.
