# Hozzájárulás a NetworkMeasureBoxhoz

Köszönjük a segítséget. Az NMB-vel azt lehet megmutatni a szolgáltatónak, mit tud valójában egy vonal, ezért egy hibás szám rosszabb, mint egy hiányzó funkció. Ezek a szabályok azért vannak, hogy az eredmények megbízhatóak maradjanak. English: [CONTRIBUTING.md](CONTRIBUTING.md).

## Mielőtt elkezded

- Egy kisebb javításnál nagyobb dolog előtt nyiss egy issue-t, és írd le, mit és miért változtatnál.
- Olvasd el a [docs/TESTING.hu.md](docs/TESTING.hu.md)-t: leírja, mi van tesztelve, hol, és hogyan kell tesztelni.
- Az NMB-t egyetlen 1000/300 Mbps-os otthoni optikai vonalon, Raspberry Pi 4-gyel fejlesztjük és teszteljük. Ha máson tesztelsz (más vonal, lap vagy disztribúció), az nagyon hasznos: írd le pontosan, mi volt az.

## Szabályok a kódhoz

- **Python 3.10 vagy újabb, csak a standard könyvtár.** Nincs új pip-csomag; a rendszereszközöket (`ip`, `nft`, `dnsmasq`, `iw`, `nmcli`) teljes hibakezeléssel hívjuk, és a kódnak akkor is működnie kell, ha hiányoznak.
- **Őszinte eredmények.** Soha ne tárolj eredményt egy másik motor neve alatt, ne tölts ki nem mért értéket, ne tarts meg fizikailag lehetetlen eredményt. Ha valami nem sikerült, sikertelenként tárold, az okkal együtt.
- **Ne árts annak a hálózatnak, amelyen a box van.** Ami címet oszt, útvonalat módosít vagy forgalmat küld, annak előbb ellenőriznie kell, hogy ez biztonságos (lásd a Wi-Fi-megosztást: soha nem oszt DHCP-t ott, ahol másik szerver válaszol), és kikapcsoláskor vissza kell állítania mindent.
- **Tiszteld a szolgáltatásokat, amelyek felé mérsz.** Tartsd a korlátaikat (Ookla legfeljebb óránként), és a kliens azonosítsa magát őszintén.
- **Beállítások:** minden új beállításnak olyan alapértéke legyen, ami akkor is biztonságos, ha a felhasználó soha nem nyúl hozzá; a `load_config` olvassa, a `save_config` írja, és dokumentálva van.
- **Webes felület:** minden új szöveg a `t('kulcs', 'English fallback')` hívással megy, a kulcs mind az öt nyelven megvan (`nmb/web/i18n.py`); magyar szöveg nem kerülhet a többi nyelvbe. Minden végpont, amit a webes felület hív, az `nmb-cli`-ben is művelet (`nmb/tui/catalog.py`).
- **Kicsi, olvasható változtatások.** Pull requestenként egy téma. A megjegyzés azt írja le, miért, nem azt, hogy mit.

## Tesztelés (kötelező)

Minden pull request leírja, hogyan lett tesztelve. Tesztleírás nélküli pull requestet nem fogadunk el.

1. **Egységtesztek, mindig:**
   ```sh
   python3 -m unittest discover -s tests
   node --check nmb/web/assets/dashboard.js   # ha változott
   bash -n setup.sh                           # ha változott
   ```
   Az új viselkedés új teszteket kap. A tesztek mockolják a rendszert, és root, hálózat vagy box nélkül futnak.
2. **Valódi eszközön mindennél, ami a hálózathoz, a rendszerhez vagy a méréshez nyúl.** Úgy telepítsd, ahogy a felhasználók kapják (`git archive` és `setup.sh`), futtasd élesben a funkciót, és mérd meg, amit állít (hálózati funkcióknál: az interfész bájtszámlálói előtte és utána). Ne azon a porton tesztelj, amelyiken csatlakozol, hanem veth-párral és hálózati névtérrel. Utána állítsd vissza az eszközt.
3. **VM-ben a telepítő és a disztribúciók változásainál:** tiszta telepítés, újratelepítés rá, újraindítás.
4. **Frissítsd a [docs/TESTING.md](docs/TESTING.md)-t és a [docs/TESTING.hu.md](docs/TESTING.hu.md)-t** egy sorral: hol, milyen eredménnyel, hogyan.

Írd le azt is, amit **nem** teszteltél. A „valódi hardveren nem próbáltam” hasznos mondat; a „működik” anélkül, hogy hol, nem az.

## A pull request

- Töltsd ki a sablont (`.github/pull_request_template.md`); ez kéri a tesztleírást.
- Minden, a felhasználó által észrevehető változtatást írj be a [CHANGELOG.md](CHANGELOG.md) *Unreleased* részébe (Keep a Changelog: Added, Changed, Fixed, Removed).
- Ha a viselkedés vagy a beállítások változnak, frissítsd a README-t (mindkét nyelven).
- Commit-üzenet: `típus(terület): mi változott` (`feat`, `fix`, `docs`, `test`, `refactor`), és a törzsben az ok, ha nem magától értetődő.
- Ha a változtatás egy részét MI-asszisztens írta, írd le; azért továbbra is te felelsz, hogy elolvastad és tesztelted.

## Biztonsági hibák

Biztonsági hibáról ne nyiss nyilvános issue-t. Írj a karbantartónak a GitHub-profilján lévő címre, a hiba előidézésének lépéseivel.

## Licenc

A hozzájárulással elfogadod, hogy a munkád a projekt MIT licence alatt jelenik meg.
