# Tesztelési jegyzőkönyv

Mit, hol, hogyan és milyen eredménnyel teszteltünk. Ha egy teszt újra lefut vagy új kerül be, ezt a fájlt is frissíteni kell. A README *Tesztelési Állapot* táblázata ennek az összefoglalója. Angol változat: [TESTING.md](TESTING.md).

Utolsó teljes kör: 2026-11-07.

## Hol futottak a tesztek

| Név | Mi ez |
|---|---|
| **Box** | Raspberry Pi 4, Debian 13 (arm64), `standalone` mód, a fejlesztő routerére kötve. Napi használatban, 1000/300 Mbps-os vonalon. |
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
| Alpine 3.20 (OpenRC) | ✅ | ✅ | ✅ | 80-as port jogosultság, RMBT-fordítás és OpenRC-újraindítás javítva |
| Raspberry Pi 4, Debian 13 | ✅ | ✅ | ✅ | A Box |
| Raspberry Pi OS, Fedora, Arch, 32 bites | — | — | — | Nincs tesztelve; a `setup.sh` csak Debian-alapú rendszert és Alpine-t támogat |

### Mérés

| Funkció | Hol | Eredmény | Hogyan |
|---|---|---|---|
| Ookla | Box | ⚠️ | Óránként működik. Percenként az Ookla tiltja a boxot („Limit reached”); ekkor a box szünetelteti az Ooklát (30 perc, legfeljebb 4 óra), és RTR-NetTesttel mér, az RTR saját nevén tárolva |
| RTR-NetTest | Box, VM-disztró | ✅ | ~910/320 Mbps az 1000/300-as vonalon |
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
| Gyári visszaállítás | VM-D13 (korábbi kör), unit-tesztek | ✅ | `--yes` kell hozzá |
| `nmb-cli` TUI | Box, unit-tesztek | ✅ | |
| Biztonság: tűzfal, `nmb`-ként futó webszerver, titkok a boot-partíción | VM-disztró, Box | ✅ | |
| Kernel hálózati finomhangolás | Box, VM-disztró | ✅ | Az `nmb-netd` (root) végzi |
| Telegram bot és riasztások | Unit-tesztek | ⚠️ | Valódi bottal nem |
| SMTP, OONI, meghajtócsere | — | — | |
| 512 MB RAM-os eszközök | — | — | |

## Nyitott

- **A Boxon még a régi polkit-szabály van.** Ott a vendég Wi-Fi a webes felületről „network-control: auth” hibával nem megy, amíg az új `os/90-nmb.rules` nincs telepítve (`setup.sh` újrafuttatása, vagy másolás az `/etc/polkit-1/rules.d/` mappába).
- Nincs tesztelve: Ubuntu újratelepítés és újraindítás, Debian 12 újraindítás, Tailscale, valódi Telegram bot, SMTP, OONI, valódi Wi-Fi és PPPoE hardver.

## Újrafuttatás

- Unit-tesztek: `python3 -m unittest discover tests` (kb. 3 perc).
- Az itt használt VM-szkriptek nincsenek a repóban; minden sor leírja, mi volt beállítva.
