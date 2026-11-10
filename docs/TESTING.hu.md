# Tesztelési jegyzőkönyv

Mit, hol, hogyan és milyen eredménnyel teszteltünk. Ha egy teszt újra lefut vagy új kerül be, ezt a fájlt is frissíteni kell. A README *Tesztelési Állapot* táblázata ennek az összefoglalója. Angol változat: [TESTING.md](TESTING.md).

Utolsó teljes kör: 2026-11-07. Utolsó frissítés: 2026-11-10 (éjjel: adatkorlát, vegyes kör, ping-telemetria PPPoE-n, kliens az 5 GHz-es hozzáférési ponton; előtte a valódi PPPoE vonal, port-továbbítás, UPnP, IPv6 a LAN-nak).

**A 2026-11-09-i munka környezete:** az aznapi összes javítás, teszt és bővítés a dobozon, **Debian GNU/Linux 13 (trixie)** alatt, a Raspberry Pi 4-en készült és ott lett tesztelve, egy Garuda Linuxot (Arch-alapú) futtató fejlesztői gépről, Tailscale-en keresztül. A fejlesztés Windowsra költözése (WSL2, lásd `DEV_SETUP_WINDOWS.hu.md`) ez után jön.

## Hol futottak a tesztek

**Tesztvonal:** az NMB-t egyetlen otthoni optikai (FTTH) internetkapcsolaton fejlesztjük és teszteljük: 1000/300 Mbps-os csomag, magyar szolgáltatónál, a box az otthoni router, egy GL.iNet Flint 4 mögött. A README-ben és a tesztelési jegyzőkönyvben szereplő minden sebesség-, CPU- és időadat erről a vonalról és egy Raspberry Pi 4-ről származik. Sokkal lassabb (DSL, mobilnet) és gyorsabb (2,5 vagy 10 Gbps) vonalon nincs tesztelve; kb. 1 Gbps fölött előbb a Pi 4 egyetlen gigabites portja és a CPU-ja lesz a korlát, mint a vonal.

| Név | Mi ez |
|---|---|
| **Box** | Raspberry Pi 4, Debian 13 (arm64), `standalone` mód, a fejlesztő főrouterére, egy GL.iNet Flint 4-re kötve. Napi használatban, 1000/300 Mbps-os otthoni optikai (FTTH) vonalon.. 2026-11-09 este közvetlenül a szolgáltató ONT-jára kötve is (PPPoE, DIGI), router módban; a Tailscale-t közben egy USB-s Netgear Nighthawk M6 Pro tartotta fenn. |
| **VM-D13** | QEMU/KVM x86-64 PC-n, Debian 13 felhőkép a teljes `linux-image-amd64` kernellel. Két hálókártya (felhasználói NAT mint WAN, socket-kapcsolat mint LAN). Wi-Fi `mac80211_hwsim`-mel (három szimulált rádió); a kliensek hálózati névterekben. |
| **VM-disztró** | Tiszta Debian 13, Debian 12, Ubuntu 24.04 LTS és Alpine 3.20 (x86-64) virtuális gépek, mindegyik `setup.sh`-val nulláról telepítve. |
| **Unit-tesztek** | `python3 -m unittest discover tests` (303 teszt) a fejlesztői gépen és rootként a VM-D13-on. |

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
| Ookla | Box | ✅ | Óránként működik. Az elutasítás („Limit reached”) a nyilvános IP-hez kötődik: napokig tartó sűrű mérés után a vonal címe minden óránkénti próbánál tiltva maradt, a CLI beállításainak javítása után is; a tulajdonos javaslatára újraindítottuk a főroutert (GL.iNet Flint 4), a vonal új nyilvános IP-t kapott, és az első ütemezett mérés azonnal sikerült: 934,2/325,4 Mbit/s, 6,9 ms, bufferbloat A, #2073-as szerver (2026. nov. 8.). Elutasításkor a box szünetelteti az Ooklát (30 perc, legfeljebb 4 óra), és nem tesz a helyére más motor eredményét |
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
| Valódi hardver, Nighthawk M6 Pro | ✅ | A Pi 4-en USB-n: mérési link, router módú WAN, és a doboz távoli elérése a PPPoE-teszt alatt (lásd fent) |

### Valódi PPPoE vonal és router mód (a doboz az ONT-n, DIGI, 2026-11-09 este)

Csak Tailscale-en keresztül elérve (a fejlesztői gép másik hálózaton, a Nighthawk Wi-Fi-jén volt). Az `nmb-selftest scenario pppoe` vezetésével (140 ellenőrzés sikeres, 5 figyelmeztetés, 6 hiba: az IPv6-ellenőrzések a javításuk előtt, a Wi-Fi-kliens és a webes felület lépése, amit éjjel senki nem végzett el, és a DynDNS késése a javítása előtt), illetve kézzel.

| Funkció | Eredmény | Hogyan |
|---|---|---|
| PPPoE felderítés, belépés, kernelbeli PPPoE a szolgáltatásnévvel | ✅ | `nmb-selftest pppoe --pppoe-real`: koncentrátor DIGI, szolgáltatás `Diginet`, `pppoe.so`; az első próbát elutasította („Invalid username or password”): a mentett felhasználónévben `_` volt, a szolgáltatóéban `-`; a régi routerből vett névvel csatlakozott |
| Internet, HTTPS, MTU PPPoE-n | ✅ | Az első ping-válasz 6 s-mal a kapcsolat felépülése után (a szolgáltató eldobja az első csomagokat), MTU 1492, HTTPS 200 |
| Az automatikus mód router módot választ PPPoE-vel | ✅ | 15 s-mal a `mode = auto` után, a kábel az ONT-n |
| NAT, MSS-csökkentés, a doboz internete és DNS-e a ppp0-n, hozzáférési pont és DHCP, szimulált LAN-kliens | ✅ | A forgatókönyv `pppoe-up` lépése és a router csoport |
| Sebesség PPPoE-n (1000/300-as csomag) | ✅ | Cloudflare 899/308, Fast.com 870/324, RTR 749/321, iPerf3 904/322 Mbit/s, a ppp0-hoz kötve |
| Újratárcsázás | ✅ | A pppd-t bontásra utasítva 12 s alatt vissza; leállított pppd: az nmb-netd 41 s után újraindította |
| Valódi Wi-Fi-kliens a router módon át, PPPoE-n | ✅ | A tulajdonos telefonja a doboz Wi-Fi-jén (2,4 GHz, 802.11n): „tökéletesen működik”. A forgatókönyv saját kliens- és webes lépése nem készült el (éjszaka) |
| A WAN zárva az internet felé | ✅ | Másik hálózatról: SSH, DNS (TCP és UDP), webes felület és iperf3 zárva IPv4-en és IPv6-on, a ping válaszol |
| A doboz saját IPv6-ja PPPoE-n | ✅ | A javítás után: cím és alapértelmezett útvonal a szolgáltató router-hirdetéséből, HTTPS IPv6-on |
| IPv6 a LAN-nak (előtag-delegálás, router-hirdetés) | ✅ | A dhcpcd egy /64-et kapott a DIGI-től, a dnsmasq hirdette; egy szimulált LAN-kliens SLAAC-címet kapott és IPv6-on elérte az internetet; egy LAN-eszköz nyitott portja az internetről nem volt elérhető. Valódi telefonnal: nem ellenőrizve |
| Port-továbbítás | ✅ | Egy LAN-eszköz (névtér webszerverrel) másik hálózatról elérve a vonal címén; hairpin egy második LAN-eszközről; `nmb-selftest portfwd` 9/9 |
| UPnP / NAT-PMP / PCP | ✅ | NAT-PMP-leképezés és IGD AddPortMapping egy LAN-eszközről, másik hálózatról elérve; a 22-es port és egy másik eszköznek kért leképezés elutasítva; az UPnP kikapcsolásakor törölve. Valódi alkalmazással (játékkonzol, torrentkliens): nem ellenőrizve |
| A DynDNS követi az új címet | ✅ két javítás után | Először 246 s után (a következő ütemezett frissítéskor). Utána az útvonalváltáskor azonnal frissített (20:51, „the box's way to the internet changed”), de a dobozon lévő IPv6 miatt az IPv6-címet küldte IPv4-ként; a csak-IPv4 javítás után a név a vonalra mutatott (21:00) |
| Wi-Fi alapbeállítással (auto) | ✅ | A javítás után: 802.11ac, 80 MHz, 36-os csatorna elsőre; a gépről 5180 MHz-en látszott; utána vissza a tulajdonos 2,4 GHz-es 802.11n-es beállítására. 5 GHz-es kliens: lásd lent, 2026-11-10 |
| A sebességmérések router módban a router WAN-jához kötődnek | ✅ | A javítások után; előttük az eth0-hoz (csak link-local cím), a WAN kiesésekor vagy az nmb-netd újraindításakor pedig a USB-s hotspothoz kötődtek (mobiladat). A 21:10-es frissítéskor a védelem kihagyott egy mérést („no test over the USB hotspot”), 21:00 óta 0 mérés USB-n |
| nmb-netd újraindítása élő PPPoE mellett | ✅ javítás után | Először (20:31) a leállítási időkorlát a PADT előtt kilőtte a pppd-t; a DIGI megtartotta a régi munkamenetet, a következő belépést elutasította („Too many sessions”), a PADI-ra nem válaszolt, és kb. 6 perc után engedte el. Javítva (a pppd bont elsőként, 45 s-os leállítási idő); újratesztelve 20:40:09-kor és 20:40:39-kor: „Sent PADT” egy másodpercen belül, a következő belépés azonnal elfogadva |

### Adatkorlát, vegyes kör és ping-telemetria (a doboz PPPoE-n, 2026-11-10 éjjel)

| Funkció | Eredmény | Hogyan |
|---|---|---|
| A tulajdonos ütemezésének adatforgalma | — (adat, nem teszt) | A ppp0-n kb. 4 óra alatt (21:10-01:06) 556 GB le és 244 GB fel ment, minden motorral 2-5 percenként; négy szerveres iPerf3-mal kb. 25 GB 10 perc alatt |
| Adatkorlát | ✅ | `nmb-selftest datacap` 5/5: a felhasználás linkenként az időszak kezdete óta számolva, a felhasznált mennyiségre állított korlát elértnek látszott, egy ütemezett kör motor futtatása nélkül kimaradt, a tulajdonos korlátai visszaálltak |
| Vegyes kör iPerf3 és Ookla nélkül | ✅ | A dobozon Cloudflare, Fast.com és RTR beállítva; a következő ütemezett körök csak ezeket futtatták |
| Ping-telemetria PPPoE-n | ✅ javítás után | Előtte: 100% veszteség minden célpontra 19:31 és 01:21 között (a szonda az eth0-hoz volt kötve, cím nélkül) és 8 nyitva maradt kiesés. Utána: a szonda 30 s-on belül a ppp0-ra költözött, veszteség nincs, 1.1.1.1 kb. 8 ms; a Local Gateway (PPPoE-n nincs átjáró) és az ISP First Hop (a PPP peer 10.0.0.1, amely pingre nem válaszol) kikapcsolva |
| NetworkManager a PPPoE-porton | ✅ | Router módban az eth0 nem kezelt: egy próbálkozás az újraindításkor (01:38), szemben az előtte lévő 42 perc 21 próbálkozásával („Activation: failed for connection 'netplan-eth0'” 45 s-onként) |
| Kliens az 5 GHz-es hozzáférési ponton | ✅ | 2026-11-10 02:23-02:31, a doboz saját alapbeállításával (802.11ac, 80 MHz, 36-os csatorna): egy linuxos laptop -61 dBm-mel, 433 Mbit/s-os kapcsolati sebességgel csatlakozott (VHT MCS 9, egy adatfolyam: a Pi 4 rádiójának maximuma), IPv4-et és a delegált prefixből IPv6-címet kapott, a DNS és a HTTPS IPv4-en és IPv6-on is működött, ping nem veszett el. Átvitel: csak a Wi-Fi (SSH-adatfolyam a dobozról a laptopra) 84 Mbit/s, visszafelé 81 Mbit/s; internet 64-81 Mbit/s le (egy adatfolyam), 94 Mbit/s (négy adatfolyam), 87-91 Mbit/s fel; a tulajdonos telefonja ugyanekkor 86,9/98,7 Mbit/s, 10 ms ping. A kb. 85-95 Mbit/s tehát a Pi 4 beépített Wi-Fi-jének plafonja hozzáférési pontként 5 GHz-en, nem a vonalé (kábelen 900/320). Késleltetés a dobozig: üresjáratban 1-134 ms (átlag 30 ms), letöltés alatt átlag 120 ms |
| A hozzáférési pont sávjának váltása | ✅ javítás után | Előtte: a sávváltás az egész routert újraépítette, a pppd újratárcsázott, a LAN kb. 40 s-ig internet nélkül maradt. Utána: vissza 2,4 GHz-re, 802.11n-re egy reloaddal: ugyanaz a pppd-folyamat, egy ping sem veszett el (40/40 az 1.1.1.1-re), a hostapd kb. 3 s alatt újra fut |
| A netd újraindítása automatikus módban | ✅ javítás után | Előtte: két tárcsázás 20 s különbséggel („auto mode: PPPoE on; rebuilding router mode”), abban a percben 464 pingből 312 elveszett. Utána: egy tárcsázás, a router mód egyszer épül fel |
| Módbeállítás váltása azonos módra | ✅ javítás után | Routerről automatikusra és vissza a PPPoE vonalon: ugyanaz a pppd-folyamat, mindkétszer 32-ből 0 ping veszett el („the box stays in mode_a”) |
| IPv6 valódi telefonon a doboz Wi-Fi-jén | ✅ | 2026-11-10 02:56, a tulajdonos telefonja: ipv6test.google.com „using IPv6 already”, test-ipv6.run 10/10 IPv6-ra és IPv4-re, mindkét cím a DIGI-től |
| A dobozt módosító Telegram-parancsok | ✅ javítások után | 2026-11-10, a bot saját parancskezelőjén át a dobozon (a válaszok összegyűjtve, a műveletek valódiak): `/mode mode_a` és `/mode auto` (ugyanaz a pppd, nincs újratárcsázás); `/vpn stop`/`start` WireGuardra és OpenVPN-re (nem volt csatlakozott kliens); `/heal`, `/heal fix` (ép, nincs teendő); `/heal updates` (a javítás előtt régebbi kódot kínált „2.5.0 -> 2.5.0” formában, utána „a legújabb fut (commit)”); `/wifi connect` (most elutasítja, amíg a rádió a hozzáférési pont); `/dyndns off`/`on`/`update` (a webszerver frissítője 35 s-on belül leáll és visszajön; a javítás előtt tovább futott); `/adblock off`/`on`; `/backup create` (37,5 MB 32 s alatt) és `/backup list`; `/purge` megerősítéssel az adatok másolatain a doboz RAM-lemezén (a mérések törlése a javítás előtt „database or disk is full” hibával elbukott, most szeletekben megy; események, riportok, mentések); `/reboot now` (77 s múlva újra elérhető Tailscale-en router módban PPPoE-vel, egy tárcsázás, IPv4 és IPv6, Wi-Fi fut, az adatbázis az utolsó percig megmaradt) |
| Megtelt /var/log | ✅ javítás után | A kör közben derült ki: a 48 MB-os RAM-lemez 100%-on volt (fejlesztői napló 10 MB x 5), minden szolgáltatásban elakadt a naplózás, és egy telepítés félúton leállt. Az elforgatott példányok a gépre mentve; a forgatás most a fájlrendszerhez igazodik: újraindítás után 1% foglalt |
| `/kill` | ✅ javítás után | Két `sleep` folyamaton: a bot sajátja TERM-re leállt, a rootét elutasította (a botnak nincs sudo-joga a killhez), a PID 1-et elutasította, nem létező PID-et jelzett; a 19-es jelet most elutasítja (előtte TERM-et küldött, miközben 19-et írt) |
| `/purge logs confirm` | ✅ javítás után | Elkülönített mount-névtérben (a naplókönyvtárak ott eldobható RAM-lemezek, a `journalctl` és a `dmesg` helyén egy rögzítő): az NMB-naplók kiürültek, az elforgatott példányok törlődtek, más fájl megmaradt, a segéd meghívta a `journalctl --rotate`, `--vacuum-time=1s` és `dmesg -c` parancsot; az SD-kártyán őrzött naplókat is törli már (előtte megmaradtak). A doboz valódi journalja, kernel-puffere és naplói változatlanok |
| Tárhelyőr a /var/log RAM-lemezen | ✅ javítás után | Egy 45 MB-os próbafájl után 48 MB-ból 3 MB maradt szabadon: az őr törölte (a legrégebbi elforgatott naplót elsőként), és 47 MB szabadnál megállt; a valódi fejlesztői napló érintetlen. Előtte csak az adatlemezt figyelte |
| Bot-indulás újraindítás után router módban | ✅ javítás után | Előtte: 2 perccel a többi szolgáltatás után (a NetworkManager-wait-online-ra várt, ami az ONT-n elbukik). Utána (04:02-es újraindítás): együtt a netd-vel, a webbel és a szondával; a PPPoE előtt egy sikertelen lekérdezés, utána működik |
| `setup.sh` majdnem tele /var/log-gal | ✅ | /var/log 91%-on: a telepítő előbb törölte a régi elforgatott naplót, végigfutott, és a régi alap fejlesztői naplót (6 x 10 MB) 3 x 5 MB-ra állította; a gyári Web UI-belépésre figyelmeztetett |
| Az ONT-ról az otthoni routerre (automatikus mód) | ✅ javítások után | 2026-11-10 04:09: a tulajdonos átdugta a kábelt; 04:11:32-kor önálló mód („a router címet ad az eth0-n”), 04:12:12-re internet (kiesés 04:09:31-04:12:12 = az átdugás), a dnsmasq, a pppd és a hostapd leállt, nincs `proto boot` útvonal, a Local Gateway célpont visszakapcsolt, az ISP First Hop kikapcsolva marad, a DynDNS azonnal frissült (04:12:36). A kábeles 50-es metrika a NetworkManager-profilban csak javítás után (100 maradt); egy bennragadt DNS-tartalékjelző is javítva. A `/wifi connect` a mentett otthoni profillal önálló módban működik |
| A WAN-kábel 3 s-ra kihúzva | ✅ | 02:28, véletlenül: a PPPoE-munkamenet megmaradt (nem tárcsázott újra, nem lett kiesés, ping sem veszett el) |
| A 2026-11-09-i hamis kiesés-sorok törölve | ✅ | A tulajdonos döntése: előbb mentés az adatbázisról (dobozon és a gépen), utána a 18-25-ös kiesések törölve, a 17-es (18:56, a kábel átdugása) lezárva 19:00:49-kor, amikor a doboz USB-n át újra online volt, a 19:00:49 és 01:20:58 közötti elveszett minták és teljesen elveszett percek törölve, két határperc javítva. Rendelkezésre állás az utolsó 24 órában: 99,55% (előtte 73,22%) |

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
| Telegram bot és riasztások | Box, egységtesztek | ✅ | 2026-11-08, Pi 4, a valódi parancskezelőn át, helyettesítő klienssel: minden parancs, menügomb és inline gomb mind a 11 nyelven (338 futás, 0 hiba); a `/mode`, `/heal`, `/backup`, `/drivers` jó és hibás bemenettel mind a 11 nyelven (66 futás, 0 hiba, magyar szöveg csak magyarul). Visszafordítható parancsok élesben, utána visszaállítva: `/kill` egy saját `sleep`-re, `/backup create` + `send` (39 MB) + törlés, `/vpn add`/`qr`/`conf`/`del` tesztklienssel, `/heal fix`. Vegyes sebességmérés a valódi botról (Cloudflare 860/293, Fast.com 814/320, RTR 607/310, iPerf3 503/315). Egy tesztként jelölt valódi riasztás megérkezett a chatbe. Talált és javított hibák: kilenc parancs olyan függvényt hívott, aminek közben megváltoztak a paraméterei (a régi mockok kitalált értékeket adtak vissza, ezért voltak zöldek a tesztek); a bot napokkal régebbi kódot futtatott, mert a telepítő sosem indította újra. Nem futott: újraindítás, purge, frissítés, módváltás, Wi-Fi-csatlakozás, VPN indítás/leállítás |
| SMTP, OONI, meghajtócsere | — | — | |
| 512 MB RAM | VM-D13 (463 MB használható) | ✅ | 25 perc, minden szolgáltatás, percenkénti mérés: 26-ból 26 mérés sikeres, 182–222 MB szabad, nincs swap, nincs OOM, nincs újraindulás; webszerver 40 MB, szonda 31 MB, egyik sem nő |
| Mentés és visszaállítás | VM-D13 | ✅ | Létrehozás, letöltés, listázás, visszaállítás a listából és feltöltött fájlból; a beállítás és minden mérés visszajön; a csonka feltöltést elutasítja, és nem változtat semmit. Javítva: a visszaállított adatbázist a régi `-wal` napló eltüntethette, a régebbi boot-partíciós másolat felülírta a visszaállított beállítást, az `nmb` nem tudta olvasni a visszaállított beállítást, és a feltöltött mentést bárki olvashatta |
| Áramszünet | VM-D13 | ✅ | A QEMU leállítva futó mérés közben és rögtön egy mentés indítása után: mindkét adatbázis átmegy az `integrity_check`-en, a beállítás ép, minden szolgáltatás fut; a félbeszakadt mérés egyszerűen hiányzik. A mentés atomikus (ideiglenes fájl, fsync, átnevezés). Legfeljebb 15 perc eredménye veszhet el, ez a tmpfs miatt szándékos |
| Ookla a dobozon: választott szerver, szünet, nincs helyettesítés | Box, egységtesztek | ✅ | A dobozon derült ki: a beépített Yettel-azonosító (10390) rossz volt („No servers defined”), a szünetelő Ooklát RTR-eredmény helyettesítette, a szünet újraindításkor elveszett, és az `/api/status` hibát adott egy sikertelen mérés után. Mind javítva; a szünet újraindítás után is megmarad, és szünet alatt nem kerül be sor |
| Motoronkénti időköz | Egységtesztek | ✅ | 30 perces RTR 30 percen belül kimarad, utána fut; 0 esetén minden alkalommal fut; az Ookla 60 perc alá nem állítható |
| Frissítés a GitHubról (Git nélküli telepítés) | Egységtesztek | ⚠️ | Biztonságos kicsomagolás (útvonal-kiszökés elutasítva), ellenőrzés a GitHub ellen (szimulálva), állapotfájl, root- és commit-ellenőrzés. A valódi tárolóval dobozon még nem futott |
| Újratelepítés `setup.sh`-val | VM-distro (Ubuntu 26.04, Alpine 3.22, Rocky 10) | ✅ | A beállítások, az admin jelszó és a mérések megmaradtak; a `/opt/nmb` alá tett elavult fájl eltűnt; a beállítás 0640 `nmb:nmb` |
| Központi gyűjtő és távoli irányítás | Helyi gyűjtő és box-kliens, egységtesztek | ✅ | Feltöltés (ismétlés nem duplikál), keresés ügyszámra, korábbi ügyszámra és ügyfélszámra, CSV, diagnosztika és események csak hozzájárulással, távoli sebességmérés lefut és visszajelez, parancs elutasítva hozzájárulás nélkül vagy más oldalról, ismeretlen parancs mindkét oldalon elutasítva, titkok hash-ként (0600). Két gép között még nem futott |
| Tárhelyőr | Box, egységtesztek | ⚠️ | A Boxon (116 GB) 2048 MB-ot tart szabadon, és helyesen nem törölt semmit. Az `nmb-cli` `storage.save` (a hibás számot elutasítja), `storage.cleanup` és az `/api/storage/status` a Boxon lefutott. Egységtesztek: a cél a lemez méretétől függ, előbb a legrégebbi naplók mennek, a legújabb mentés megmarad, az utolsó 7 nap mérései megmaradnak. Valóban megtelt lemezen még nem futott; a webes *Tárhely* kártyát böngészőben még nem nyitottuk meg |
| Beállítások mentése két programból egyszerre | Box, egységtesztek | ✅ | A Boxon derült ki: az induló `nmb-web` és egy közben mentő `nmb-cli` sérült `nmb.conf`-ot hagyott (duplikált szakasz, levágott sor), és utána egyik program sem tudta beolvasni. Javítva (egyszerre egy mentés, saját ideiglenes fájl); egy egységteszt négy szálról 60-szor ment egy rövid és egy hosszú konfigot, és a fájl mindig olvasható. Később derült ki: eltűnt a Telegram-token, mert minden program a beállítások teljes, régi másolatát írta vissza. Háromutas összefésüléssel javítva (egy mentés csak azt írja, amit az adott program változtatott); a `tests/test_config_merge.py` az egyik másolatból tokent, egy régebbiből más beállítást ment, és mindkettő megmarad. A Boxon azóta a token négy telepítést és több mentést túlélt |
| USB tethering, 5G (Netgear Nighthawk M6 Pro, amerikai AT&T-modell; USB-terméknév MR6X00) | Box, egységtesztek | ⚠️ | 2026-11-08. Bedugva `eth1` néven jelent meg (`rndis_host`, 0846:68e1); a javítás előtt vezetékes Ethernetnek számított volna, most tetheringként ismeri fel, és a doboz továbbra is az `eth0`-n mért. `nmb-cli run usb.uplink enabled=true`: magáncímet kapott a hotspot DHCP-jétől, az alapértelmezett útvonal maradt az `eth0`-n, a 152-es forrásszabály a helyén. Vegyes mérés `interface=eth1`-gyel: Ookla 105,3/17,7 Mbps, Cloudflare 69,2/18,6, Fast.com 63,6/17,9, RTR 196,7/44,0, mind `fwa`-ként az `eth1`-en, a mobilszolgáltató nyilvános IP-jével (nem az otthoni vonaléval); 506 MB az `eth1` számlálóin. Ellenőrizendő: az RTR 5G-n jóval gyorsabb a többinél, és a sorában nincs kliens-IP; a kábel kiesésekor USB-re váltó tartalék nincs megírva (a kiesésmérő ilyenkor a mobilkapcsolatot mérné) **Frissítés 2026-11-08 este:** az USB-re kért mérés (`nmb-speed -i eth1`) az `eth0`-n futott (a kapcsolót figyelmen kívül hagyta); javítva, utána mind a négy motor az `eth1`-en mért (a bájtokat ott számoltuk). **2026-11-09:** RTR `--bind`-dal az `eth1`-en: 81 MB az `eth1`-en, 130 Mbit/s letöltés, a sorban a mobilszolgáltató nyilvános IP-je (ugyanaz, mint a Cloudflare-é USB-n, nem az otthoni vonalé), ping minimum 29,9 ms a 31,0 ms-os mediánnal szemben, jitter 0,26 ms. |
| USB tethering mint egyetlen internet (Nighthawk M6 Pro, 5G) | Box | ⚠️ | 2026-11-08, élesben. Kábel kihúzva: az alapértelmezett útvonal a Wi-Fire került (600-as metrika), az USB-t nem használta, az `auto` a `wlan0`-n mért. Utána a Wi-Fi lecsatlakoztatva (előtte visszakapcsoló időzítő élesítve): kb. 12 mp alatt a doboz felvette a `default via <hotspot> dev eth1 metric 900` útvonalat, a Tailscale-en át az 5G-n is elérhető maradt, az `auto` az `eth1`-en mért (Cloudflare 76,2/25,3 Mbps, `fwa`-ként). Kábel és Wi-Fi vissza: az USB-útvonal 10 mp-en belül eltűnt, és bekerült az `uplink_usb_fallback_end` esemény. Közben talált és javított hiba: a váltások eseménye `warning` súlyossággal íródott, amit a séma nem enged, ezért nem tárolódtak (most egy teszt a valódi sémába szúr be). Még nem futott: router mód USB-WAN-nal (PC az Ethernet-porton, Wi-Fi-kliens) **Elbukott 2026-11-08 20:02-kor** (vezetett forgatókönyv): amikor a kábel a routerből a laptopba került, az `eth0`-n maradt egy statikus alapútvonal (50-es metrika, a doboz saját maga tette fel), ami megelőzte a Wi-Fit és az USB-t; a doboz elvesztette az internetet és a Tailscale-t, nem állt át USB-re, és a laptopnak sem osztott meg semmit. Javítva (a halott útvonalakat törli, `ignore_routes_with_linkdown`); újra még nincs tesztelve. |
| Router mód USB tetheringgel mint WAN (Nighthawk M6 Pro, 5G) | Box | ⚠️ | 2026-11-08, élesben, két körben, egy laptoppal az Ethernet-porton és a doboz Wi-Fijén; a naplók mentve és elemezve. Működött: híd `eth0` + `wlan0`, NAT az `eth1` felé, DHCP a laptopnak kábelen és Wi-Fin (miután javult az AP indítása, és az, hogy a NetworkManager kivette a portot a hídból). Két hiba kiderült, reprodukálva és javítva: (1) router módban a doboz elveszítette a saját internetjét, mert a rádió hozzáférési ponttá válás után is megtartotta az otthoni Wi-Fi bérelt címét és alapértelmezett útvonalát (600-as metrika); a Tailscale saját naplója `defaultRoute=wlan0`-t mutatott; (2) a DHCP-őr nem látta az otthoni routert a hídtag porton: a DISCOVER egy másik interfész címével ment ki forrásként (a dnsmasq ezt figyelmen kívül hagyja), és a csak IPv4-es packet socket nem kapta meg a hídtag port kereteit; nyers, 0.0.0.0-ról küldött kerettel és `ETH_P_ALL`-lal a próba egy névtérbeli tesztszervert sima és hídtag porton is megtalált (a régi kód egyiken sem), és az otthoni routert is. Az USB-eszköz kihúzásakor a helyreállítás működött (a mód `eth0`-val mint WAN-nal épült újra). Újra futtatandó a javításokkal: internet a kábeles és a Wi-Fi-kliensnek, utána az otthoni router a porton **Egészében még nem működik:** egyik élő körben sem kapott egyetlen kliens (kábelen vagy Wi-Fin) igazoltan internetet a dobozon át; a tulajdonos a kábelen nem tudott böngészni. A DHCP-őr és a WAN-váltás működik. Újratesztelés: `nmb-selftest scenario usb`, ami a kliensek továbbított csomagjait számolja. **2026-11-08 21:00, élesben, sikeres:** a halott útvonal javításával router módban az USB-s 5G internetet megosztotta egy Windowsos laptopnak a kábelen és egy kliensnek a doboz Wi-Fi-jén (2,4 GHz, csak 802.11n); a tulajdonos mindkettőn böngészett, a webes felület helyben elérhető volt, a Tailscale nem szakadt meg; a laptopról 75 mp alatt 462 csomag ment ki az `eth1`-en. A laptop előbb megtartotta a Wi-Fi megosztásból kapott 192.168.77.x címet, és addig nem volt internete, amíg a port linkje le nem esett; javítva (router módban a beállítás után a vezetékes LAN portok linkje 4 mp-re leesik). Az otthoni router visszadugva: a DHCP-őr 50 mp után leállt, és az `eth0` lett a WAN. Még nyitva: 5 GHz és Wi-Fi 5/6 a hozzáférési ponton; a kábel laptopra dugása az új linkeséssel |
| Wi-Fi hozzáférési pont jelszava | Box, egységtesztek | ✅ | A közös gyári jelszót a hozzáférési pont és a webes mentés is elutasítja; az üreset és a 8–63 karakteren kívülit is; az `/api/config` csak a `wifi_psk_set` jelzőt adja vissza, a jelszót soha; a telepítési naplóban nincs jelszósor. A Boxon: a jelszó egyedi és érvényes (kiolvasás nélkül ellenőrizve); a hozzáférési pont ki van kapcsolva |
| Az `nmb-cli` lefedi a webes felületet | Box, egységtesztek | ✅ | A `tests/test_tui.py` elbukik, ha egy webes végpontnak nincs CLI-művelete; a webes felület által ténylegesen hívott végpontokat kézzel is összevetettük a katalógussal (az aliasokat és előtagokat leszámítva): a két diagnosztikai letöltés, a fő Wi-Fi szerep és a tárhelybeállítások hiányoztak, ezeket felvettük |
| A telepítő minden szolgáltatást újraindít | Box | ✅ | A `setup.sh` után az `nmb-web`, `nmb-netd` és `nmb-telegram` `ActiveEnterTimestamp` értéke későbbi a telepítés kezdeténél; a javítás előtt a bot két nappal korábbi kódot futtatott |
| Nincs titok a kimenetekben | Box, átnézés | ✅ | A telepítési napló, az `/api/config`, a bot válaszai és a diagnosztikai csomag átnézve tokenekre és jelszavakra: csak meglétet jelző mezők. A dobozon futó tesztek a titkoknál csak azt nézik, üres-e, illetve a gyári érték-e, kiírni soha nem írják ki |

## Hogyan kell tesztelni

Minden változtatást azon a szinten kell tesztelni, ahol elromolhat. Írd le, mit futtattál, hol, és mit láttál; a rögzített teszt nélküli változtatás nincs kész (lásd [CONTRIBUTING.hu.md](../CONTRIBUTING.hu.md)).

### 1. Egységtesztek (minden változtatásnál)

```sh
python3 -m unittest discover -s tests          # kb. 1 perc; OK-val kell végződnie
node --check nmb/web/assets/dashboard.js       # ha a webes felület szkriptje változott
bash -n setup.sh                               # ha a setup.sh változott
```

- Az új viselkedés tesztet kap a `tests/` alatt. A rendszert mockold (`subprocess`, `/sys`, socketek); a teszteknek sima PC-n, root, hálózat és box nélkül is át kell menniük.
- A `tests/test_tui.py` elbukik, ha a webes felület olyan végpontot hív, amit az `nmb-cli` nem ismer: vedd fel a műveletet az `nmb/tui/catalog.py`-ba.
- Fordítások: minden kulcs minden nyelven (a `tests/test_i18n_locales.py` ellenőrzi a JSON-nyelveket: minden kulcs, ugyanazok a helyőrzők és HTML, mint az angolban), magyar szöveg nem kerülhet a többi nyelvbe:
  `python3 -c "from nmb.web.i18n import TRANSLATIONS as T; k=set(T['en']); print({l: len(k ^ set(v)) for l, v in T.items()})"` csak nullákat írhat ki.

### 2. Valódi boxon (minden, ami a hálózathoz, a rendszerhez vagy a méréshez nyúl)

1. Úgy telepítsd a változást, ahogy a felhasználók kapják: `git archive HEAD` a boxra, majd `sudo bash setup.sh` a kicsomagolt mappából. Egyes fájlokat csak gyors próbához másolj, és ezt írd is le.
2. Ellenőrizd: `systemctl is-active nmb-web nmb-netd nmb-probe` és `systemctl list-units 'nmb*' --state=failed`.
3. Futtasd élesben a funkciót, és ott nézd meg az eredményt, ahol a felhasználó látja: webes felület, `nmb-cli latest`, adatbázis (`sqlite3 -readonly /var/lib/nmb/live/nmb.db`), naplók (`journalctl -u nmb-web -u nmb-netd`).
4. Azt mérd, amit a funkció állít. Hálózati funkcióknál ez a bájtszámláló: olvasd ki a `/sys/class/net/<if>/statistics/{rx,tx}_bytes` értékét előtte és utána, így tudod, melyik kapcsolaton ment valójában a forgalom.
5. Állítsd vissza a boxot: beállítások, teszt-interfészek, szabályok. Írd le, mit változtattál, és hogy visszaállítottad.

### 2a. Élő önteszt a boxon (`nmb-selftest`)

A `sudo nmb-selftest` kb. egy perc alatt ellenőrzi a futó boxot; a `--full` a Telegram botot is végigviszi minden parancson és gombon mind a 11 nyelven (néhány perc). Csak egy csoport: `sudo nmb-selftest router usb`. A jelentés a `/var/log/nmb/selftest-<idő>.json` fájlba kerül; a kilépési kód 1, ha valami elbukott.

| Csoport | Mit ellenőriz |
|---|---|
| services | nmb szolgáltatások futnak, nincs traceback az utolsó órában, netd állapotfájl |
| internet | alapértelmezett útvonal, ping, DNS, HTTPS |
| config | a Wi-Fi jelszó nem gyenge és nem gyári, a Telegram token be van állítva (sosem írja ki), az `nmb.conf` nem olvasható mindenkinek, az események súlyossága a sémának megfelel |
| web | mind a 11 nyelv teljes és nincs bennük magyar szöveg (a magyaron kívül); status, USB, tárhely és config végpontok; a `/api/config` nem ad vissza titkot |
| cli | `nmb-cli menu`, minden képernyő, `latest` minden motorra |
| usb | eszköztípus, cím, a profil sosem alapértelmezett útvonal, forrásszabály a 152-es táblába, USB alapútvonal csak más internet nélkül, ping és HTTPS az USB-n |
| router | csak router módban: hídtagok, DHCP-szerver, NAT a WAN-on, a box saját útvonala; majd egy szimulált LAN kliens (hálózati névtér egy `br-lan`-ba kötött veth-en) címet kap, és eléri az internetet, a DNS-t és a HTTPS-t |
| dhcp-probe | a DHCP-őr egy eldobható dnsmasq ellen: megtalálja sima porton és hídtag porton, és nem jelez, ha nincs szerver |
| speed | utolsó 48 óra motoronként: hibák a leggyakoribb üzenetekkel, rate limit szünetek, kliens IP nélküli sorok, egyetlen ping minta, a medián letöltés az Ookla/Cloudflare-hez képest ugyanazon a vonalon |
| wifi-ap | a rádió sávjai (HT40/VHT sávonként) a futó `hostapd.conf`-hoz képest, visszautasított hostapd indítások |
| collector | az adatbázis egy másolata feltöltve egy helyi gyűjtőre (vagy `--collector-url`, token a `NMB_SELFTEST_COLLECTOR_TOKEN` változóból): minden mérés egyszer érkezik meg, az újraküldés nem ad hozzá semmit. A box saját feltöltési pozíciója érintetlen marad |
| telegram | csak `--full` vagy név szerint |

Az ellenőrzések csak eldobható objektumokat hoznak létre (névterek, veth párok, tesztbridge, adatbázis-másolat), és utána eltávolítják őket; sosem váltanak módot, nem változtatnak beállítást vagy uplinket, és sosem írnak ki titkot vagy nyilvános címet.

**Vezetett USB tethering forgatókönyv** (kell hozzá valaki, aki a kábeleket átdugja): `sudo systemd-run --unit=nmb-scenario -p StandardOutput=file:/var/log/nmb/scenario-usb.log nmb-selftest scenario usb`. Szolgáltatásként fut, mert a box kapcsolata futás közben változik; az aktuális teendő a `/run/nmb/scenario.json` fájlban és a naplóban van. Lépések: USB-re kötött sebességmérések (minden motor, a bájtok számolása az USB interfészen, USB adatszámláló), Wi-Fi megosztás a LAN porton egy laptopnak, USB tartalék, amikor a box lecsatlakozik a Wi-Firől (a laptop ekkor az USB-n internetezik, egy automatikus mérés az USB-n), router mód USB WAN-nal (szimulált kliens, laptop a kábelen, egy eszköz a box Wi-Fi-jén, továbbított csomagok számolása egy eldobható nftables táblában), a DHCP-őr, amikor a kábel visszakerül az otthoni routerbe (határ 90 mp), visszaállítás, és opcionálisan az USB eszköz kihúzása. A beállításokat előbb elmenti, és a végén, összeomlás után, vagy egy külön visszaállító szolgáltatással 45 perc múlva visszaállítja (`sudo nmb-selftest restore` kézzel). A `--plan` kiírja a lépéseket, a `--steps router,guard,restore` csak ezeket futtatja.

**Vezetett router mód forgatókönyv** (az Ethernet-port a WAN, egy telefon vagy PC a box Wi-Fi-jén; USB nem kell): `sudo systemd-run --unit=nmb-scenario -p StandardOutput=file:/var/log/nmb/scenario-router.log nmb-selftest scenario router`. Lépések: a router mód elindul (WAN-cím, NAT, hozzáférési pont címmel és DHCP-vel, szimulált LAN kliens internettel, DNS-sel, HTTPS-sel), egy valódi eszköz a box Wi-Fi-jén (friss cím, a csomagjait a WAN-on kifelé számolja), a webes felület arról az eszközről (a 80-as portra érkező csomagokat számolja), a kábel egy percre kihúzva az otthoni routerből (a hozzáférési pont és a DHCP fut tovább, nincs halott útvonal, bekapcsolt USB esetén az USB veszi át) és vissza (újra van WAN-cím, az eszköz újra online, a netd nem omlik össze), visszaállítás (standalone, a rádió újra az otthoni Wi-Fin, nincs hozzáférési pont). A `systemctl stop nmb-scenario` mostantól szintén visszaállít.

**Vezetett automatikus mód forgatókönyv** (a Tailscale miatt USB tethering kell hozzá, vagy `NMB_SCENARIO_ALLOW_OFFLINE=1`): `sudo systemd-run --unit=nmb-scenario -p StandardOutput=file:/var/log/nmb/scenario-auto.log nmb-selftest scenario auto`. Lépések: `mode = auto` a routerben lévő kábellel (egy percig standalone-nak kell maradnia), kábel ki (router mód nem a 90 mp-es türelmi idő előtt, hozzáférési pont és DHCP, internet USB-n, Tailscale él), kábel vissza (kb. egy percen belül standalone, cím a routertől, nincs hozzáférési pont, a rádió újra az otthoni Wi-Fin), mentett PPPoE belépésnél a kábel az ONT-n (router mód PPPoE-vel tárcsáz, internet a `ppp0`-n) és vissza, visszaállítás (a mód az eredeti).

Az `nmb-selftest` `mode` csoportja a futó módot a beállításhoz méri: az automatikus döntést és okát, hogy router módon kívül nincs hozzáférési pont, standalone-ban van cím a routertől, router módban fut a DHCP, és automatikus router módban nem válaszol router a WAN porton. Minden futás végén „To look at” lista mutatja a hibákat és figyelmeztetéseket; a `--md jelentes.md` Markdown-táblát is ír, issue-ba vagy chatbe másoláshoz.

### 3. A box saját kapcsolatának kockáztatása nélkül

- **LAN-kliens:** veth-pár, az egyik vége hálózati névtérben (`ip netns add t; ip link add v0 type veth peer name v1; ip link set v1 netns t`). A névtér egy a boxra dugott eszköz. DHCP-t és útválasztást soha ne azon a porton tesztelj, amelyiken keresztül csatlakozol.
- **Második DHCP-szerver:** `dnsmasq --port=0 --interface=v1 --bind-interfaces --dhcp-range=...` a névtérben.
- **Szimulált Wi-Fi:** `mac80211_hwsim` VM-ben (VM-D13). A valódi rádiók másképp viselkednek; az ilyen eredményt jelöld szimuláltnak.
- **Sebességmérő motorok:** egyszerre egy motort futtass; az Ooklát ugyanarról a nyilvános IP-ről legfeljebb óránként, különben órákra letiltja.

### 4. Virtuális gépekben (telepítő, más disztribúciók, hálózati módok)

- Disztribúciónként tiszta felhőkép, nulláról telepítve a `setup.sh`-val; utána újratelepítés rá, majd újraindítás. Ellenőrizd, hogy a beállítások, az admin jelszó és a mérések megmaradnak, és a `/etc/nmb/nmb.conf` `0640 nmb:nmb`.
- Hálózati módok és a hozzáférési pont a VM-D13-ban (két hálókártya, szimulált rádiók, kliensek névterekben).

### 5. A mockoknak egyezniük kell a valódi kóddal

Ha egy mock kitalált értéket ad vissza, a teszt zöld marad, miközben a valódi hívás elbukik. Használd az `autospec=True`-t (`@patch("nmb.x.y", autospec=True)`), így egy átnevezett paraméter elbuktatja a tesztet, és a mock azt a formát adja vissza, amit a valódi függvény (a tuple maradjon tuple). Ha nem vagy biztos benne, egyszer írasd ki a valódi eredményt a dobozon, és annak a formáját vedd át a tesztbe.

### 6. Minden folyamatnak az új kódot kell futtatnia

A feltelepített fájl hatástalan, amíg egy régi folyamat a memóriájában tartja a régit. Telepítés után vesd össze minden szolgáltatás indulási idejét a telepítés idejével (`systemctl show -p ActiveEnterTimestamp nmb-web nmb-netd nmb-probe nmb-telegram`); mindegyiknek későbbinek kell lennie. Ugyanígy az olyan beállításváltozás után, amit egy szolgáltatás csak induláskor olvas be.

### 7. Hosszú ellenőrzések futtatása a dobozon

- Átmeneti egységként futtasd, ne az SSH-munkamenetben: `sudo systemd-run --unit=nmb-check --uid=nmb -p StandardOutput=file:/tmp/nmb-check.out python3 -u /tmp/check.py`. A kimeneti fájlt ne hozd létre előre (a systemd nem tudja megnyitni a `/tmp`-ben egy másik felhasználó által létrehozott fájlt).
- Minden lépésnek legyen saját időkorlátja, és lépésenként írjon ki egy sort, így egy elakadásnál látszik, hol tart.
- Soha ne `pkill -f`-elj olyan mintára, ami a saját SSH-parancsodra is illeszkedik.
- Mielőtt elvágsz egy kapcsolatot, amin át a dobozt éred, élesíts egy tőled független visszautat, és ez egy alvó szolgáltatás legyen, ne időzítő: `systemd-run --unit=nmb-restore sh -c 'sleep 360; nmcli device connect wlan0'`. Egy átmeneti időzítő (`--on-active`) egyszer 3,5 percet késett, mert egy telepítés közben újratöltötte a systemd-t. Tarts nyitva egy második utat is (Tailscale a másik kapcsolaton).
- Hagyd ki, ami a vonalat vagy a dobozt változtatja (menügombról indított sebességmérés, újraindítás, purge, frissítés), hacsak éppen nem az a teszt; a döntés előtt a gombfeliratot fordítsd le parancsra.
- Olyan teszt-chatazonosítókat használj, amelyek nem valódi chatek, és írd le, milyen valódi üzenetek mentek ki.

### 8. Titkok

Tesztelés közben soha ne olvass ki, ne írj ki és ne másolj tokent, jelszót vagy kulcsot, naplóba sem. Csak azt ellenőrizd, ami számít: üres-e, egyezik-e egy ismert gyári értékkel, jó-e a hossza. Ha egy titok elveszett, kérd meg a tulajdonost, hogy írja be újra.

### Mit kell rögzíteni

Minden sorhoz: hol (Box, VM neve, egységtesztek), az eredmény (✅ ⚠️ ❌), és hogyan: mit állítottál be, mit mértél, számokkal, és mit találtál és javítottál közben. Amit nem próbáltál ki, azt ki nem próbáltként írd, ne működőként.

## Kiadás előtti ellenőrzőlista

Minden kiadás előtt a Boxon (a telepítő változásainál egy VM-en is). Minden sor leírja, mit kell csinálni, és mikor számít sikeresnek. Az eredményt írd be a fenti táblázatokba.

| # | Terület | Mit kell csinálni | Akkor sikeres, ha |
|---|---|---|---|
| 1 | Egységtesztek | `python3 -m unittest discover -s tests`, `node --check nmb/web/assets/dashboard.js`, `bash -n setup.sh` | Minden OK |
| 2 | Frissítő telepítés | `git archive HEAD` a boxra, `sudo bash setup.sh` | Kilépési kód 0; az `nmb-web`, `nmb-netd`, `nmb-probe` (és ha használt, az `nmb-telegram`) aktív, és a telepítés után indult; nincs hibás `nmb*` egység; az `/opt/nmb/.source-commit` az új commit; a beállítások, az admin jelszó, a Telegram-token és a mérések megmaradtak; a `nmb.conf` olvasható és `0640 nmb:nmb`; a `/root/nmb-setup.log`-ban nincs jelszó vagy token |
| 3 | Tiszta telepítés | Támogatott családonként egy VM nulláról (Debian/Ubuntu, Fedora/RHEL, Alpine) | Mint a 2., és a műszerfal válaszol, és lefut egy első RTR-mérés |
| 4 | Ookla | Egy ütemezett futás, legfeljebb óránként | Van sor letöltéssel, feltöltéssel, pinggel és a választott szerverrel; elutasításkor: egy hibasor, szünet, és nem kerül a helyére más motor eredménye |
| 5 | RTR-NetTest, Cloudflare, Fast.com | Mindegyikből egy kézi futás (`nmb-cli run speed.run engine=...`) | A sor a saját motorneve alatt van; a sebesség hihető a vonalhoz (a tesztvonalon 850–940 le, 300–330 fel); a Fast.com sor `raw_json`-jában ott vannak a szerverek, a minták és a terhelés alatti késleltetés |
| 6 | iPerf3 | Egy futás a beállított szerver felé | A sor a szerver nevét viseli (hely és szolgáltató), nem csak a címét |
| 7 | Vegyes futás | Ütemezés `all` motorral, egy ciklus kivárása | Motoronként egy sor, mindegyik a saját nevén; Ookla csak akkor, ha letelt az órája |
| 8 | Mérési kapcsolat | `wifi` beállítás, egy mérés, a `wlan0`/`eth0` bájtszámlálók előtte és utána; vissza `auto`-ra | A forgalom a választott kapcsolaton ment; `auto` esetén bedugott kábellel Ethernet |
| 9 | Wi-Fi megosztása LAN porton | veth-pár + névtér a *Hogyan kell tesztelni* szerint; utána egy második DHCP-szerver a névtérben | A kliens címet kap és a Wi-Fi-n át eléri az internetet; a második szerverrel a box kb. 2 percen belül leállítja a DHCP-jét, címét, NAT-ját és szabályát; kikapcsoláskor minden eltűnik |
| 10 | Vezeték nélküli szerepek | Portok és driverek: `wlan0` legyen fő, mentés; utána vendég | Az eszközfelderítő a megfelelő sávot mutatja; a vendégállapot nem állítja a fő hálózatot vendégnek |
| 11 | Tárhelyőr | Rootként `storage_guard.run(cfg, force=True)` a Boxon; VM-en megtöltött lemezzel | Box: semmi sem törlődik, a cél látszik; VM: előbb a régi naplók mennek, az utolsó 7 nap mérései megmaradnak, esemény íródik |
| 12 | Beállítások | Mentés a webes felületről és az `nmb-cli`-ből egyszerre, néhányszor; egy beállítás módosítása a webes felületen, utána egy másiké az `nmb-cli`-vel | A `nmb.conf` olvasható marad; nincs duplikált szakasz; mindkét változás megvan, a Telegram-token és a többi titok változatlan (a bot továbbra is elindul) |
| 13 | Nyelvek | Mind a 11 nyelv végigváltása a műszerfalon, a beállításokban, a kijelentkezési oldalon és a `/results` oldalon; a jelentés megnyitása `?lang=` paraméterrel mindegyiken; a botban `/lang` mindegyikre | Nincs nyers kulcs vagy `{helyőrző}`, nincs szétesett elrendezés, nincs magyar szöveg a magyaron kívül, sem a webes felületen, sem a botban |
| 14 | Webes felület | Minden fül megnyitása nyitott böngészőkonzollal | Nincs JavaScript-hiba; minden fül betölti az adatait |
| 15 | Jelentések, exportok | A jelentés, a sebesség-CSV, a részletes CSV és a ping-CSV letöltése | A fájlok megnyílnak; az új motorok és az iPerf3-nevek megjelennek |
| 16 | Telegram (ha be van állítva) | Minden menügomb, valamint a `/status`, `/ping`, `/report`, `/tailscale`, `/vpn`, `/wifi`, `/wifi scan`, `/tasks`, `/heal`, `/backup`, `/drivers`, `/mode` parancs; egy `/test`; `/kill` egy saját `sleep`-re; `/backup create`, utána törlés; `/vpn add` és `/vpn del` tesztnévvel; egy tesztriasztás | Minden válasz a chat nyelvén, valódi adatokkal (nincs `0.0 B`, nincs „nincs vezérlő”, a Tailscale-állapot egyezik a `tailscale status`-szal); nincs „Hiba (...)” szöveg; megjön a sebességmérés; minden létrehozott dolog törölve. A helyettesítő klienses szkripttel: minden parancs és gomb mind a 11 nyelven, 0 hiba |
| 17 | Újraindítás | `sudo reboot`, 3 perc várakozás | Minden szolgáltatás fut; a beállítások, az utolsó pillanatkép és az Ookla-szünet állapota megmarad |
| 18 | Wi-Fi hozzáférési pont | Próbáld elmenteni a gyári jelszót és egy 6 karakteresat; nézd meg az `/api/config`-ot | Mindkettőt elutasítja; az `/api/config`-ban `wifi_psk_set` van, jelszó nincs; érvényes jelszó nélkül a hozzáférési pont nem indul |
| 19 | `nmb-cli` | `nmb-cli menu`; `nmb-cli run storage.save keep_days=7`, `storage.cleanup`, `dev.bundle`; egy hibás érték | Az új műveletek szerepelnek a listában és működnek; a hibás értéket üzenettel elutasítja |
| 20 | Tárhely kártya | Megnyitás a webes felületen, mentés, „Ellenőrzés és takarítás most” | Az értékek betöltődnek, mentődnek, és újratöltés után is megmaradnak; a szabad hely sora frissül |
| 21 | Újraindult szolgáltatások | `systemctl show -p ActiveEnterTimestamp` minden `nmb*` szolgáltatásra | Mind későbbi a telepítésnél |
| 22 | Titkok | `grep -iE 'token\|password\|psk' /root/nmb-setup.log`; `nmb-cli api GET /api/config` | Csak jelzők, például `wifi_psk_set`, értékek nincsenek |
| 23 | Naplók a futás után | `journalctl -p err -u 'nmb*' --since <kezdés>` | Nincs új hiba, csak amit a teszt szándékosan okozott |
| 24 | Visszaállítás | A tesztbeállítások, teszt-interfészek, szabályok, tesztkliensek és a teszt-chatek nyelvének visszaállítása | A box olyan, mint az ellenőrzőlista előtt |

## Még tesztelendő

### Valódi kábel vagy hardver kell hozzá

| Mit | Hogyan |
|---|---|
| Wi-Fi megosztása LAN porton, élesben | A box Wi-Fi-n, Ethernet-kábel a boxtól egy laptophoz (router nélkül): a laptop 192.168.77.x címet kap, és eléri az internetet. Utána a box kábelét az otthoni routerbe dugva a boxnak másodperceken belül le kell állítania a DHCP-jét, és a routertől kell címet kapnia |
| Wi-Fi uplink a box saját profiljával | `nmb-cli run wifi.uplink ssid=... password=... enabled=true` egy még nem Wi-Fi-s boxon; utána mérés `measurement_link = wifi` beállítással, számlálók a `wlan0`-n |
| Vendég és fő Wi-Fi két rádión | USB Wi-Fi adapter `wlan1`-ként: egyik fő, másik vendég; mindkét sáv az eszközfelderítőben |
| Valódi rádiók hozzáférési pontként | 2,4 GHz, 802.11n valódi telefonnal működik (2026-11-09); 5 GHz, 802.11ac, 80 MHz laptoppal és telefonnal működik (2026-11-10, kb. 85-95 Mbit/s, a rádió korlátja); Wi-Fi 6/7 és 6 GHz más hardvert igényel |
| Második rádió valódi kétsávos működéshez | A Pi 4-nek egy rádiója van: egyszerre egy sáv. Mindkét sávhoz egyszerre egy USB-s Wi-Fi adapter kell második hozzáférési pontként (nincs megírva) |
| Pi 5 | |
| Tervezett routerek | Routeren még semmi sem fut; lásd a portolási tervet |

### A box és USB tethering kell hozzá (`nmb-selftest scenario usb`)

| Mit | Hogyan |
|---|---|
| A 2026-11-09-i naplóátnézés javításai | Telegram kiesés közben (kábel ki a routerből): a bot naplójában egyre hosszabb szünetek, nem másodpercenként több kérés. (`/dyndns off` és `/dyndns on`: elkészült 2026-11-10-én, lásd Eredmények.) Csak a DNS letiltása (pl. az 53-as port a routeren): a tartalék elindul, miközben az IP működik, és a tiltás vége után 15 percen belül visszajön a rendes DNS. Router mód a Pi-n: a `journalctl -u nmb-netd` nem mutat „hostapd did not start” sort. A `/var/lib/nmb/.rmbt_client_uuid` változatlan marad az RTR mérések között. Egy kábelhúzás után nincsenek ismétlődő „dead default route” sorok |
| Automatikus mód (`mode = auto`) | A box `auto`-ban, a kábel az otthoni routerben: standalone, nincs váltás. A kábel 90 mp-re kihúzva a routerből: router mód hozzáférési ponttal (a Tailscale-nek USB-n vagy Wi-Fin meg kell maradnia). A kábel az ONT-n, mentett PPPoE-vel: router mód PPPoE-vel. A kábel vissza a routerbe: kb. 30 mp-en belül standalone. Router újraindítás (90 mp alatt): marad standalone. Több vezetékes portos boxon: a többi port hídban a WAN porttal, a mögötte lévő PC a router címét kapja |
| IPv6 a vonalon | `sudo nmb-selftest ipv6`: a LAN router hirdetése (élettartam, előtagok), a box nyilvános IPv6-címe és útvonala, HTTPS IPv6-on. 2026-11-09, Pi 4: az otthoni router (GL.iNet Flint 4) 0 élettartamot és előtag nélküli hirdetést küldött, ezért a LAN nem kapott IPv6-ot, pedig a szolgáltató adja; újratesztelendő, miután a router LAN-oldalán bekapcsolták az IPv6-ot. Utána a DynDNS-nek be kell állítania az AAAA-rekordot |
| IPv6 router módban DHCP-s WAN-on vagy USB-n | Csak PPPoE-s WAN-ra készült el (2026-11-09); másik router mögött vagy hotspoton a LAN továbbra is csak IPv4-et kap |
| Valódi PPPoE vonal, ami hátravan | 2026-11-09-én elkészült (lásd Eredmények). Hátravan: egy elutasított belépés után 10 percet kell várnia (`journalctl -u nmb-netd`: „dialing again in 600 s”); egy hosszabb vonalkiesés (nem csak újraindítás) USB-s mérés nélkül; egy továbbított port valódi telefonon vagy gépen (az IPv6 telefonon működik, 2026-11-10); UPnP valódi alkalmazásból |
| Beállítások USB pendrive-ról | A `config/usb-import.example.conf` `nmb.conf` néven egy FAT32 pendrive-on, új Telegram tokennel: bedugva a token megváltozik, az `nmb-import-result.txt` felsorolja a `telegram.token`-t, mentés a `/var/lib/nmb/config-backups/`-ban, újra bedugva semmi nem változik |
| Router mód Ethernet WAN-nal (`nmb-selftest scenario router`) | Egy telefon vagy PC a box Wi-Fi-jén: internet, webes felület és SSH a Wi-Firől, WAN kábel kihúzása és visszadugása; ha a távoli elérés 2 percre megszakad, a Tailscale-őrnek le kell állítania és vissza kell állítania mindent |
| Wi-Fi megosztás a LAN porton, USB-ről jövő internettel | A box Wi-Fin, a kábel a routerből a laptopba, majd a box lecsatlakozik a Wi-Firől: a laptopnak tovább kell böngésznie az USB-n át (`wifi-share`, `usb-fallback` lépések; a kliens `eth1`-en kimenő csomagjait számolja) |
| Router módban a LAN portok linkje beállítás után leesik | Laptop a kábelen egy korábbi címmel (pl. 192.168.77.x): újradugás nélkül egy percen belül 192.168.100.x címet kell kapnia és böngésznie kell |
| A halott alapútvonalak eltűnnek | Kábel a routerből a laptopba: egy netd körön belül nem maradhat alapútvonal az `eth0`-n; a box forgalma Wi-Fin vagy USB-n megy, a Tailscale nem szakad meg (`nmb-selftest internet`: „no dead default route”) |
| Vezetékes útvonal-prioritás NetworkManagerrel | Az otthoni router mögött: 2026-11-10-én elkészült (lásd Eredmények). Hátravan: laptopra áttett kábel után az eth0-n nem maradhat alapútvonal |
| USB eszköz kihúzása router módban és standalone-ban | A forgatókönyv `unplug` lépése: nem marad USB útvonal vagy szabály, a mód `eth0`-val épül újra |
| Titkok visszaállítása | A Telegram token kézi törlése az `nmb.conf`-ból: az `nmb-selftest config` a nevével bukjon el, a `sudo nmb-selftest secrets-restore` hozza vissza, és a bot válaszoljon |
| iPerf3 szerver pihentetése | Az ötször egymás után elbukó szervert 6 órára ki kell hagyni (naplósor: „left out for up to 6 h”), utána újra próbálni |
| Ookla szünet | Ookla rate limit alatt az ütemező kihagyott sorokat tároljon, ne hibákat (`nmb-selftest speed`: nincs „rate-limit pauses” figyelmeztetés) |
| Gyűjtő az interneten át, HTTPS-sel | Eddig box → PC Tailscale-en, HTTP-vel; gyűjtő valódi tanúsítvánnyal, másik hálózaton |

### Most is elvégezhető (VM vagy box)

| Mit | Hogyan |
|---|---|
| Tárhelyőr megtelt lemezen | VM kis lemezzel (2–4 GB); töltsd meg (`fallocate -l ... /var/tmp/fill`), várj legfeljebb 10 percet, vagy rootként `storage_guard.run(cfg, force=True)`: előbb a régi naplók mennek, az utolsó 7 nap mérései maradnak, esemény íródik |
| Telepítő kicsi vagy teli lemezen | 500 MB-nál kevesebb szabad helynél a `setup.sh`-nak érthető üzenettel meg kell állnia; 8 GB alatti lemezen az új konfig 2 × 2 MB-os naplókat kap |
| Beállítások mentése több programból egyszerre | A webes felület és az `nmb-cli` pár percig ciklusban ment; a `nmb.conf`-nak olvashatónak kell maradnia (az egységteszt egy folyamat szálait fedi le) |
| Fast.com nem 1000/300-as vonalon | Összevetés az RTR-NetTesttel ugyanazon a vonalon |
| Hosszú futás | 24–72 óra percenkénti méréssel: memória, adatbázisméret, naplóforgatás, tárhelyőr |
| Kevés memória, hosszabban | 512 MB 25 percig rendben volt; 24 óra még hátravan |
| Frissítés és mentés régebbi kiadásról | 2.4.0 telepítése, frissítés a mostanira a konfig megtartásával; 2.4.0-s mentés visszaállítása |
| WAN-tartalék, terheléselosztás, VLAN, link aggregáció | Két WAN-kártya, az egyiket kihúzni; Linux-híd VLAN-szűréssel |
| Ellenséges hálózatok | Csak IPv6-os WAN, CGNAT, hibás DNS, captive portal, ki-be kapcsoló link, órabeállítás-ugrás |
| A dobozt módosító Telegram-parancsok, ami hátravan | 2026-11-10-én elkészült (lásd Eredmények). Hátravan: `/heal apply` valódi GitHub-frissítéssel (csak a „nincs újabb” ág futott), `/purge` a valódi adaton (másolatokon és névtérben futott), `/wifi connect` új hálózathoz jelszóval (a mentett profillal 2026-11-10-én működött) |
| 50 MB-nál nagyobb mentés Telegramon | A Telegram elutasítja a nagyobb fájlt; a botnak ezt jeleznie kell, nem csendben elbuknia |
| Elveszett beállítások valódi folyamatok között | A webes felület, az `nmb-cli`, a bot és az `nmb-netd` egy órán át felváltva ment; minden beállított érték megmarad (az egységteszt egy folyamaton belül két másolatot fed le) |
| SMTP | Helyi mock szerverrel, utána valódi postafiókkal |
| Frissítés GitHubról egy boxon | Amint a mostani kód felkerül a GitHubra |
| Webes felület | Mind a 11 nyelv (a hat újabb gépi segítséggel készült fordítás: anyanyelvi lektor nézze át), több felhasználó egyszerre, hibás belépések, Firefox, Chrome és telefon |
| firewalld-portok, Debian 12 és Fedora újraindítás, Tailscale, OONI, valódi DuckDNS-domain | |

### Még nem tesztelt operációs rendszerek

Abból, hogy a `setup.sh` mit ismer fel, és mi kell a kódnak (Python 3.10 vagy újabb, csak a standard könyvtár, systemd nftables-szel, vagy Alpine OpenRC-vel).

| Rendszer | Várható | Miért | Hogyan tesztelhető |
|---|---|---|---|
| Raspberry Pi OS (arm64), Lite | Működnie kell | Debian 13 alapú, mint a Box | Pi-n, vagy Debian arm64 QEMU alatt |
| Raspberry Pi OS (armhf, 32 bites) | Ismeretlen | Az Ookla és RMBT build csak arm64-en és x86-64-en futott | Pi 2/3/Zero 2-n |
| Armbian, DietPi | Működnie kell | Debian alapú képek más egykártyás gépekre | A lapon, vagy az x86-os képeiken |
| Linux Mint 22, Pop!_OS | Működnie kell | Ubuntu 24.04 alapú; az asztali NetworkManager elviheti a portokat | VM |
| Devuan | Elutasítva | Nincs systemd; a `setup.sh` érthető üzenettel megáll | — |
| Arch, Manjaro, openSUSE, Void, NixOS | Nem támogatott | Más csomagkezelő vagy init-rendszer | Portolás kell |
| OpenWrt | Nem támogatott | A natív átírásban tervezett, lásd `ROUTER_PORTING_AND_DEPYTHONIZATION_PLAN.md` | — |
| Az NMB saját disztribúciója | Tervezett | Lásd a portolási tervet | — |

## Javítandó

A kódban vagy a box naplóiban talált, még nem javított hibák (a 2026-11-09-i naplóátnézés összefoglalója a CHANGELOG-ban):

| Mi | Részlet |
|---|---|
| Ookla rate limit óránkénti ütemezésnél | Az Ookla néhány óránként még elutasította a boxot (2026-11-08 17:20, 20:22-22:24, 11-09 01:27, 06:37, 07:41). Egy ok javítva (a bot minden alkalommal új kliensként futtatta az Ooklát); figyelni kell, megszűnik-e, és a kézi és Telegramos futásokat is bele kell számolni az órába |
| SD-kártya írások | A fejlesztői napló kb. 10 MB-ot nő naponta (2026-11-10 óta a forgatása a /var/log 40%-ába fér) (a diagnosztikai pillanatkép boot partíciós másolata már óránként legfeljebb egyszer készül) |
| A tulajdonos ütemezése által használt adat | A doboz 2-5 percenként minden motort futtat (a tulajdonos beállítása): egy 1000 Mbit/s-os vonalon ez óránként sok GB. A USB-nek nincs napi korlátja (0); 2026-11-09 óta a router mód nem vált USB-re méréshez, de USB-korlát beállítása így is ajánlott |
| `nmcli device reapply` | Az IPv4 DNS előresorolása egyszer újraalkalmazza a profilt; ez egyszer megszakította a bot egy nyitott kapcsolatát (újracsatlakozott) |
| pppd figyelmeztetés minden tárcsázáskor | „can't open options file /root/.ppprc: Permission denied” (a netd korlátozott jogokkal fut); ártalmatlan |

## Ismert korlátok

- A Raspberry Pi 4-nek egy Wi-Fi rádiója van: a hozzáférési pontja egyszerre egy sávot használ (2,4 vagy 5 GHz, az „auto” az 5 GHz-et választja). Mindkét sávhoz egyszerre második rádió kell.
- A Pi 4 beépített Wi-Fi-je hozzáférési pontként 5 GHz-en kb. 85-95 Mbit/s-ot visz át (802.11ac, 80 MHz, egy adatfolyam; mérve 2026-11-10-én laptoppal és telefonnal), messze a gigabites vonal alatt. A Wi-Fi-s eredmények a rádiót mutatják, nem a vonalat; a vonalat kábelen kell mérni.
- A DIGI PPPoE-je belépésenként egy munkamenetet enged: az otthoni router és a doboz nem lehet egyszerre online ugyanazzal a belépéssel, és egy nem bontott munkamenet (PADT nélkül) percekre blokkolja a következő belépést.
- Az Ookla letiltja azt a nyilvános IP-címet, amelyről túl gyakran mérnek, és az elutasított próbálkozások fenntartják a tiltást; ez 2026. nov. 8-án igazolódott, amikor egy új nyilvános IP-vel (a főrouter újraindítása után) a mérés azonnal sikerült. A box ilyenkor szünetelteti az Ooklát (30 perc, duplázódva legfeljebb 4 óráig). Az NMB nem cserél IP-t a megkerüléshez; az Ooklát legfeljebb óránként futtasd.
- Áramszünetnél legfeljebb 15 perc eredménye veszhet el, szándékosan (az élő adatbázis RAM-ban van).
- A fenti futásokhoz használt VM-szkriptek és bot-ellenőrző szkriptek nincsenek a tárolóban; minden sor leírja, mi volt beállítva.
- A bot mentést csak a Telegram botokra vonatkozó 50 MB-os korlátjáig tud elküldeni.
- Az a doboz, amelyen a régi gyári Wi-Fi-jelszó volt, és nem kapott újat, addig nem indít hozzáférési pontot, amíg nem állítanak be jelszót.
