# Tesztelési jegyzőkönyv

Mit, hol, hogyan és milyen eredménnyel teszteltünk. Ha egy teszt újra lefut vagy új kerül be, ezt a fájlt is frissíteni kell. A README *Tesztelési Állapot* táblázata ennek az összefoglalója. Angol változat: [TESTING.md](TESTING.md).

Utolsó teljes kör: 2026-11-07. Utolsó frissítés: 2026-11-08.

## Hol futottak a tesztek

**Tesztvonal:** az NMB-t egyetlen otthoni optikai (FTTH) internetkapcsolaton fejlesztjük és teszteljük: 1000/300 Mbps-os csomag, magyar szolgáltatónál, a box az otthoni router mögött. A README-ben és a tesztelési jegyzőkönyvben szereplő minden sebesség-, CPU- és időadat erről a vonalról és egy Raspberry Pi 4-ről származik. Sokkal lassabb (DSL, mobilnet) és gyorsabb (2,5 vagy 10 Gbps) vonalon nincs tesztelve; kb. 1 Gbps fölött előbb a Pi 4 egyetlen gigabites portja és a CPU-ja lesz a korlát, mint a vonal.

| Név | Mi ez |
|---|---|
| **Box** | Raspberry Pi 4, Debian 13 (arm64), `standalone` mód, a fejlesztő routerére kötve. Napi használatban, 1000/300 Mbps-os otthoni optikai (FTTH) vonalon. |
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
| Tárhelyőr | Box, egységtesztek | ⚠️ | A Boxon (116 GB) 2048 MB-ot tart szabadon, és helyesen nem törölt semmit. Egységtesztek: a cél a lemez méretétől függ, előbb a legrégebbi naplók mennek, a legújabb mentés megmarad, az utolsó 7 nap mérései megmaradnak. Valóban megtelt lemezen még nem futott |
| Beállítások mentése két programból egyszerre | Box, egységtesztek | ✅ | A Boxon derült ki: az induló `nmb-web` és egy közben mentő `nmb-cli` sérült `nmb.conf`-ot hagyott (duplikált szakasz, levágott sor), és utána egyik program sem tudta beolvasni. Javítva (egyszerre egy mentés, saját ideiglenes fájl); egy egységteszt négy szálról 60-szor ment egy rövid és egy hosszú konfigot, és a fájl mindig olvasható |

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
- Fordítások: minden kulcs mind az öt nyelven, magyar szöveg nem kerülhet a többi nyelvbe:
  `python3 -c "from nmb.web.i18n import TRANSLATIONS as T; k=set(T['en']); print({l: len(k ^ set(v)) for l, v in T.items()})"` csak nullákat írhat ki.

### 2. Valódi boxon (minden, ami a hálózathoz, a rendszerhez vagy a méréshez nyúl)

1. Úgy telepítsd a változást, ahogy a felhasználók kapják: `git archive HEAD` a boxra, majd `sudo bash setup.sh` a kicsomagolt mappából. Egyes fájlokat csak gyors próbához másolj, és ezt írd is le.
2. Ellenőrizd: `systemctl is-active nmb-web nmb-netd nmb-probe` és `systemctl list-units 'nmb*' --state=failed`.
3. Futtasd élesben a funkciót, és ott nézd meg az eredményt, ahol a felhasználó látja: webes felület, `nmb-cli latest`, adatbázis (`sqlite3 -readonly /var/lib/nmb/live/nmb.db`), naplók (`journalctl -u nmb-web -u nmb-netd`).
4. Azt mérd, amit a funkció állít. Hálózati funkcióknál ez a bájtszámláló: olvasd ki a `/sys/class/net/<if>/statistics/{rx,tx}_bytes` értékét előtte és utána, így tudod, melyik kapcsolaton ment valójában a forgalom.
5. Állítsd vissza a boxot: beállítások, teszt-interfészek, szabályok. Írd le, mit változtattál, és hogy visszaállítottad.

### 3. A box saját kapcsolatának kockáztatása nélkül

- **LAN-kliens:** veth-pár, az egyik vége hálózati névtérben (`ip netns add t; ip link add v0 type veth peer name v1; ip link set v1 netns t`). A névtér egy a boxra dugott eszköz. DHCP-t és útválasztást soha ne azon a porton tesztelj, amelyiken keresztül csatlakozol.
- **Második DHCP-szerver:** `dnsmasq --port=0 --interface=v1 --bind-interfaces --dhcp-range=...` a névtérben.
- **Szimulált Wi-Fi:** `mac80211_hwsim` VM-ben (VM-D13). A valódi rádiók másképp viselkednek; az ilyen eredményt jelöld szimuláltnak.
- **Sebességmérő motorok:** egyszerre egy motort futtass; az Ooklát ugyanarról a nyilvános IP-ről legfeljebb óránként, különben órákra letiltja.

### 4. Virtuális gépekben (telepítő, más disztribúciók, hálózati módok)

- Disztribúciónként tiszta felhőkép, nulláról telepítve a `setup.sh`-val; utána újratelepítés rá, majd újraindítás. Ellenőrizd, hogy a beállítások, az admin jelszó és a mérések megmaradnak, és a `/etc/nmb/nmb.conf` `0640 nmb:nmb`.
- Hálózati módok és a hozzáférési pont a VM-D13-ban (két hálókártya, szimulált rádiók, kliensek névterekben).

### Mit kell rögzíteni

Minden sorhoz: hol (Box, VM neve, egységtesztek), az eredmény (✅ ⚠️ ❌), és hogyan: mit állítottál be, mit mértél, számokkal, és mit találtál és javítottál közben. Amit nem próbáltál ki, azt ki nem próbáltként írd, ne működőként.

## Még tesztelendő

### Valódi kábel vagy hardver kell hozzá

| Mit | Hogyan |
|---|---|
| Wi-Fi megosztása LAN porton, élesben | A box Wi-Fi-n, Ethernet-kábel a boxtól egy laptophoz (router nélkül): a laptop 192.168.77.x címet kap, és eléri az internetet. Utána a box kábelét az otthoni routerbe dugva a boxnak másodperceken belül le kell állítania a DHCP-jét, és a routertől kell címet kapnia |
| Wi-Fi uplink a box saját profiljával | `nmb-cli run wifi.uplink ssid=... password=... enabled=true` egy még nem Wi-Fi-s boxon; utána mérés `measurement_link = wifi` beállítással, számlálók a `wlan0`-n |
| Vendég és fő Wi-Fi két rádión | USB Wi-Fi adapter `wlan1`-ként: egyik fő, másik vendég; mindkét sáv az eszközfelderítőben |
| Valódi rádiók hozzáférési pontként | 2,4/5/6 GHz, Wi-Fi 6/7, valódi kliensekkel |
| PPPoE valódi vonalon, Nighthawk M6 Pro, Pi 5 | |
| Tervezett routerek | Routeren még semmi sem fut; lásd a portolási tervet |

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
| Telegram, SMTP | Helyi mock szerverekkel, utána valódi bottal |
| Frissítés GitHubról egy boxon | Amint a mostani kód felkerül a GitHubra |
| Központi gyűjtő két gép között | A gyűjtő egy PC-n, a box egy másik hálózaton |
| Webes felület | Mind az öt nyelv, több felhasználó egyszerre, hibás belépések, Firefox, Chrome és telefon |
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

## Ismert korlátok

- Az Ookla letiltja azt a nyilvános IP-t, amelyről gyakran mérnek, az elutasított próbálkozások után is; a box ilyenkor szünetelteti az Ooklát (30 perc, duplázódva legfeljebb 4 óráig). Kikényszeríteni nem lehet; ritkán futtasd az Ooklát.
- Áramszünetnél legfeljebb 15 perc eredménye veszhet el, szándékosan (az élő adatbázis RAM-ban van).
- A fenti futásokhoz használt VM-szkriptek nincsenek a tárolóban; minden sor leírja, mi volt beállítva.
