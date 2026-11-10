# NMHH Szélessáv.net mérődoboz és NetworkMeasureBox – összehasonlítás

Ez a leírás az NMHH Szélessáv Programjának (SZÉP) hatósági mérődobozát veti össze a NetworkMeasureBoxszal (NMB). Célja, hogy aki a saját internetkapcsolatát szeretné mérni, lássa, mit kap az egyikkel és mit a másikkal.

**Források és jelölések.** Minden állításnál jelöljük, honnan származik:

- **[Szerződés]** – az NMHH közigazgatási szerződésmintája a Szélessáv Programban való részvételről (2018, 1. számú melléklettel), amelyet a szelessav.net igénylési oldala tesz közzé;
- **[Igénylési oldal]** – <https://szelessav.net/merodoboz-igenylese> (letöltve: 2026. november 10.);
- **[Tapasztalat]** – a projekt tulajdonosának saját tapasztalata a mérődobozzal; ezt hivatalos forrás nem erősíti meg;
- **[NMB]** – a NetworkMeasureBox saját dokumentációja és tesztjei (`README.hu.md`, `docs/TESTING.hu.md`).

Ez a leírás nem jogi tanácsadás és nem hatósági álláspont. A pontos feltételeket mindig az NMHH aktuális szerződése és honlapja adja meg. Az NMHH mérőrendszere hatósági célú: a hatósági eljárásokhoz és a hazai statisztikához ad adatot, és ezt a szerepet az NMB nem váltja ki.

---

## 1. Mi a gond a jelenlegi NMHH Szélessáv.net mérődobozzal?

### Csak Magyarországon használható

- Az NMHH mérőrendszere „a Magyarországon jelenlévő internetszolgáltatók ellenőrzésére került kiépítésre”, és „a méréseket külföldről nem lehet kezdeményezni”. **[Szerződés, 1. sz. melléklet, 5. pont]**
- Közreműködő csak „magyarországi lakóhellyel rendelkező természetes személy” lehet. **[Szerződés, „A szerződés megkötésének feltételei”]**

### Nem kaphatja meg akárki

- Feltételek: 18 év feletti életkor, magyarországi lakóhely, és saját szélessávú előfizetés vagy az előfizető hozzájárulása. Ha az ingatlan tulajdonosa más, az ő hozzájárulása is kell. **[Szerződés]**
- Az igénylést az NMHH fogadja el vagy utasítja el, „az igénylők száma, a meglevő mérési pontok földrajzi és szolgáltatók valamint szolgáltatás csomagok szerinti eloszlása szerint”. **[Szerződés, 1. sz. melléklet, 3. pont]** A reprezentatív minta érdekében az NMHH el is utasíthat igényt. **[Igénylési oldal]**
- Az igénylőlap csak akkor jelenik meg, ha a felhasználó már legalább öt mérést végzett az NMHH szoftveres eszközeivel. **[Igénylési oldal]**
- 1000 Mb/s feletti előfizetéssel egyelőre ne igényeljen dobozt: jelenleg az 1000 Mb/s alatti csomagok mérésére fókuszálnak. **[Igénylési oldal]**

### Ingyenes, de ára van: üzemeltetni kell, és vissza kell adni

- A mérőeszköz **a Magyar Állam tulajdona**, a tulajdonosi jogokat az NMHH gyakorolja. A közreműködő csak ingyenes használati jogot kap, **határozatlan időre**. **[Szerződés]**
- A közreműködő vállalja, hogy a dobozt **3 napon belül üzembe helyezi**, és rendeltetésszerűen működteti. **Díjazást és a működtetés költségeinek (például az áramnak) megtérítését nem kérheti**, és a működtetést **saját felelősségére** végzi. **[Szerződés]**
- **Anyagi felelősséggel tartozik** a rendeltetés- vagy szerződésellenes használatból eredő kárért. A hibát 3 munkanapon belül, az adatai, a szolgáltatója, a csomagja vagy a lakhelye változását pedig **8 napon belül** jelentenie kell. **[Szerződés]**
- A szerződés megszűnésekor a dobozt **működőképes állapotban vissza kell szolgáltatni**, különben az ellenértékét vagy az okozott kárt meg kell téríteni. **[Szerződés]**
- A szerződést bármelyik fél felmondhatja 15 napos felmondási idővel. **Az NMHH akkor is felmondhatja, ha a szolgáltatás megfelelő és stabil**: ha három hónap mérései szerint a le- és feltöltési sebesség eléri a garantált sávszélesség 90%-át, és a rendelkezésre állás is legalább 90%. **[Szerződés]** Ha tehát a kapcsolatod jó, a dobozt visszakérhetik.

### A mérések csak az NMHH-hoz kerülnek, és csak az NMHH szervereivel mérhetsz

- A mérés „egy külföldön is elfogadott és alkalmazott ú.n. Ookla mérő rendszerrel egyenértékű, hazai fejlesztésű mérőrendszerrel” történik. A mérőszerver a BIX-ben (Budapest Internet Exchange) van. **[Szerződés, 1. sz. melléklet, 2. pont]** Más mérőmotor (például Ookla Speedtest, RTR-NetTest, Cloudflare, iPerf3) és más szerver a dobozon nem választható. **[Szerződés; Tapasztalat]**
- A mérési eredmények a szelessav.net portálon érhetők el. Az egyedi eredményeket **90 napig** tárolják, utána csak átlagolva, összesített statisztikaként maradnak meg. A közreműködő saját, a dobozon indított méréseinek eredménye **csak a doboz webes felületén** látható, a rendszer ezeket nem tárolja. **[Szerződés, 1. sz. melléklet, 4. pont]**
- A közreműködő saját mérése a szerződés szerint pontatlanabb: egyetlen átlagos méretű adatcsomaggal fut, szemben a központi, több adatcsomagos méréssel. **[Szerződés, 1. sz. melléklet, 5. pont]**

### A szoftverhez nem lehet hozzányúlni, a forráskód és az API nem ismert

- A közreműködő vállalja, hogy az eszközt **nem nyitja fel, a szoftverét nem módosítja, és a működését nem befolyásolja**. A szoftver módosítása vagy már annak kísérlete is **azonnali felmondási ok**. **[Szerződés]**
- A doboz szoftverének forráskódja és programozói felülete (API) nyilvánosan nem ismert. **[Tapasztalat]**

### Egyéb korlátok

- **Szolgáltatónév eltérése:** ha az NMHH nyilvántartásában más szolgáltató szerepel, mint aki valójában nyújtja a szolgáltatást, abból is lehet figyelmeztetés. Ez különösen igaz, ha az előfizetés egy másik cég hálózatán fut. Példa: a nyilvántartásban „Digi Hungary” áll, miközben a szolgáltatást a One nyújtja a 2Connect hálózatán. **[Tapasztalat]** A szerződés szerint a szolgáltató- vagy csomagváltást 8 napon belül be kell jelenteni. **[Szerződés]**
- **Fapados webes kezelőfelület** a dobozon. **[Tapasztalat]**
- **Legfeljebb kb. 1 Gbit/s**, és nincs linkaggregáció (LAN aggregation). **[Tapasztalat]** Az igénylési oldal is 1000 Mb/s alatti előfizetésekre fókuszál. **[Igénylési oldal]**

## 2. Az NMHH mérődoboz előnyei

- **Hardver:** egy újraprogramozható Linksys WRT3200ACM router, egyedi, saját fejlesztésű firmware-rel. A firmware-hez nem szabad hozzányúlni, mert az szerződésszegés. **[Tapasztalat; a módosítás tilalma: Szerződés]**
- **Stabil szoftver.** **[Tapasztalat]**
- **Hatósági mérés:** az eredmények az NMHH eljárásainak alapjául is szolgálhatnak. **[Szerződés]** Az NMB ezt nem nyújtja: az NMB SLA-eredménye a saját értékelése, nem hatósági döntés. **[NMB]**
- **Áttekinthető online felület:** a szelessav.net saját felületén grafikonok vannak, és az eredmények CSV-fájlba menthetők. **[Tapasztalat]** A szerződés szerint az eredmények nyomtatható formában is elérhetők. **[Szerződés]**
- **A felhasználó gépétől független mérés:** mérés előtt ellenőrzi a forgalmat, és akkor mér, amikor éppen nem használod az internetet. **[Szerződés; Igénylési oldal]**
- **LAN passthrough:** a doboz a kiépítési végpont és a felhasználói eszközök közé kerül. **[Igénylési oldal]** A forgalmat átengedi. **[Tapasztalat]**
- **A BME-n fejlesztett mérőmotor.** **[Tapasztalat]** A szerződés „hazai fejlesztésű mérőrendszert” említ. **[Szerződés]**

### Nincs kipróbálva, nem biztos, hogy létezik

- PPPoE-kapcsolat és router funkció a mérődobozon. **[Tapasztalat: nincs kipróbálva]**

## 3. A NetworkMeasureBox előnyei

| Szempont | NetworkMeasureBox | Állapot |
|---|---|---|
| Tulajdon | 100%-ban a saját eszközöd. Nincs szerződés, üzembe helyezési határidő vagy visszaszolgáltatás | **[NMB]** |
| Mérőmotorok | Több egy helyen: Ookla Speedtest, Cloudflare, Fast.com (Netflix), RTR-NetTest (Open-RMBT), iPerf3. Az ütemezett vegyes futásnál választható, melyik fusson | élesben tesztelve **[NMB, TESTING]** |
| Szerverek | Hazai és nemzetközi szerverek, tartalomszolgáltatók és -továbbítók (Cloudflare, Fast.com/Netflix) szerverei; az Ookla és az iPerf3 bővebb szerverválasztékot ad | **[NMB]** |
| Gyakoriság | Állítható ütemezés, motoronként külön időköz. Az Ookla legfeljebb óránként fut, és csak a feltételei elfogadása után | **[NMB]** |
| Hol látszanak az eredmények | Helyben (webes felület, Telegram, CLI, SLA-dosszié, CSV). Az Ookla- és az RTR-mérések a saját rendszerükbe is bekerülnek, így nemzetközi összevetésben is látszanak | **[NMB]** |
| Ország | Nincs Magyarországhoz kötve. A natív változat tervében a doboz csak a saját országára vonatkozó részeket mutatja | **[NMB; tervezett: DEPYTHONIZATION_ROADMAP 9. pont]** |
| Üzemmódok | Standalone, router mód (DHCP, NAT, PPPoE, IPv6, porttovábbítás) és átlátszó (LAN passthrough, híd) mód, valamint automatikus mód | router mód PPPoE-vel és standalone élesben tesztelve; a passthrough és az automatikus mód részben **[NMB, TESTING]** |
| Mobilinternet | Mérhető, és USB-tetheringgel (telefon, mobil hotspot, modem) használható is | élesben tesztelve **[NMB, TESTING]** |
| Wi-Fi | Vevő (Wi-Fi-kliens) és adó (hozzáférési pont) is | 2,4 GHz-es és 5 GHz-es AP és kliens élesben tesztelve **[NMB, TESTING]** |
| Sebesség | Raspberry Pi 4-en egy gigabites port. A támogatott eszköztől és a fejlesztési fázistól függően akár 1 Gbit/s fölött is. A linkaggregáció a szoftverben megvan | 1 Gbit/s fölött **tervezett**, nincs élesben mérve **[NMB]** |
| Kezelés | Webes felület, Telegram-értesítések és -parancsok, CLI (`nmb-cli`), nem csak webes felület | **[NMB]** |
| Forráskód | Nyílt forráskódú (MIT), szabadon módosítható | **[NMB]** |
| Kezelés MI-vel | Nyílt kód és szöveges beállítások, így egy nyelvi modellel (például Claude Code) könnyebb kezelni, hibát keresni és bővíteni | **[NMB]** |

## 4. Mikor melyiket?

- **Az NMHH mérődoboza** akkor jó választás, ha hatósági mérési eredményt szeretnél, és elfogadod a feltételeket: magyarországi lakóhely, az NMHH döntése, folyamatos üzemeltetés, bejelentési kötelezettség, visszaszolgáltatás, és a szoftverhez nem nyúlhatsz.
- **A NetworkMeasureBox** akkor jó választás, ha saját, szabadon kezelhető eszközt szeretnél több mérőmotorral és szerverrel, állítható ütemezéssel, router- és mobilinternet-képességgel, országtól függetlenül.
- **A kettő együtt is használható.** Az NMB nem helyettesíti a hatósági mérést, de a saját mérései kiegészítik.

---

*Készült: 2026. november 10. A források állapota a letöltés napján. A szerződésminta 2018-as keltezésű; ha az NMHH azóta módosította, mindig az aktuális szöveg az irányadó.*
