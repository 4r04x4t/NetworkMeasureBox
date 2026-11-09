# A NetworkMeasureBox fejlesztése Windowson

Ez az útmutató egy Linuxos PC-ről egy Windows 10 vagy 11 rendszerű PC-re költözteti az NMB fejlesztését. A fejlesztést végezheti ember, vagy a Claude Code, illetve egy másik LLM-ügynök. A mérődobozhoz a hozzáférés megmarad. English: [DEV_SETUP_WINDOWS.md](DEV_SETUP_WINDOWS.md).

**Röviden:** a fejlesztés **WSL2-ben (Ubuntu)** menjen, ne a sima Windowsban. A dobozt **Tailscale-en** érd el. Így bármilyen hálózatról működik, akkor is, ha a doboz router módban van, vagy nem vagy otthon.

## Miért WSL2

A kód, a telepítő és a tesztek Linuxra készültek:

- a `setup.sh`, a segédszkriptek és a telepítés lépései bash-ben vannak, `sed`, `awk`, `tar` és `ssh` hívásokkal;
- a tesztek `fcntl`-t, csomag-socketeket (`AF_PACKET`), hálózati névtereket, valamint POSIX útvonalakat és jogosultságokat használnak;
- a Git for Windows átírja a sorvégeket, és ettől a shell szkriptek elromlanak.

WSL2-ben mindez úgy működik, mint Linuxon. A sima Windowsban (PowerShell vagy Git Bash) a teszteknek csak egy része fut le, a dobozra telepítés pedig megbízhatatlan.

## 1. Telepítés

Rendszergazdaként futtatott PowerShellben:

```powershell
wsl --install -d Ubuntu-24.04
```

Indítsd újra a gépet, nyisd meg a Start menüből az „Ubuntu”-t, és hozd létre a Linuxos felhasználódat. Utána az Ubuntuban:

```bash
sudo apt update
sudo apt install -y git python3 python3-venv openssh-client rsync curl jq sqlite3 build-essential libcurl4-openssl-dev libssl-dev
```

A `build-essential` és a két `-dev` csomag csak ahhoz kell, hogy a natív RTR klienst (`components/open-rmbt`) a PC-n is le lehessen fordítani. A doboz a `setup.sh` futtatásakor magának fordítja le.

**Claude Code** (ha egy ügynök fejleszt): a WSL-be telepítsd, ne a Windowsba, hogy a parancsai a Linuxos shellben fussanak:

```bash
curl -fsSL https://claude.ai/install.sh | bash
```

## 2. Tailscale: így éred el a dobozt

1. Telepítsd a Tailscale-t **Windowsra** (https://tailscale.com/download), és jelentkezz be **ugyanazzal a fiókkal, mint a dobozon**. A Windows és a WSL2 közös hálózatot használ, így a WSL is ezen át éri el a dobozt.
2. A doboz Tailscale-címét a Tailscale admin felületén vagy a `tailscale status` paranccsal találod meg. Ez egy `100.x.y.z` alakú cím. **Ne írd be a repóba**: a tulajdonos privát hálózatához tartozik.
3. Próbáld ki a WSL-ből:

```bash
ping -c 2 <doboz-tailscale-ip>
```

A dobozzal kapcsolatos minden munkához a Tailscale-címet használd, ne a LAN-címet. A LAN-cím a DHCP miatt változhat, és router módban vagy egy másik hálózatról nem érhető el.

## 3. SSH a dobozra

A jelszavas belépés is működik, de egy ügynöknek jobb a kulcs, mert így a jelszó nem kerül parancsokba:

```bash
ssh-keygen -t ed25519 -C "nmb-dev-windows"
ssh-copy-id user@<doboz-tailscale-ip>
ssh user@<doboz-tailscale-ip> 'hostname; systemctl is-active nmb-netd nmb-web'
```

Ha szeretnéd, írd be ezt a `~/.ssh/config` fájlba:

```
Host nmb-box
    HostName <doboz-tailscale-ip>
    User user
    ServerAliveInterval 20
```

Ezután elég az `ssh nmb-box`. A `ServerAliveInterval` életben tartja a kapcsolatot, amikor a doboz útvonalai változnak.

**sudo a dobozon:** a jelszót soha ne írd parancssorba, szkriptbe vagy naplóba. Egy privát fájlból add át a szabványos bemeneten, és utána töröld a fájlt:

```bash
umask 077; printf '%s\n' '<sudo-jelszó>' > ~/.nmb-pw
ssh nmb-box 'sudo -S -p "" nmb-selftest' < ~/.nmb-pw
rm -f ~/.nmb-pw
```

## 4. A repó és a GitHub

A repót a WSL saját fájlrendszerében tartsd (például a `~/src` alatt), ne a `/mnt/c/...` alatt. Így többszörösen gyorsabb, és a jogosultságok meg a sorvégek is rendben maradnak.

```bash
mkdir -p ~/src && cd ~/src
git clone git@github.com:4r04x4t/NetworkMeasureBox.git
cd NetworkMeasureBox
git config core.autocrlf false
```

A feltöltéshez kétféle hozzáférést használhatsz:
- egy SSH-kulcsot a GitHubon (`cat ~/.ssh/id_ed25519.pub`, majd GitHub → Settings → SSH keys);
- vagy a GitHub CLI-t:

```bash
sudo apt install -y gh
gh auth login            # a tokent a bekéréskor illeszd be, ne argumentumként
```

A tokennek csak `repo` és `workflow` jogosultságot adj. Tokent soha ne írj távoli címbe (`https://user:token@...`) vagy a `.git/config`-ba.

## 5. Egységtesztek

```bash
python3 -m unittest discover -s tests
```

Minden commit előtt mindnek át kell mennie. Nem kell hozzájuk hálózat és root jog sem. Az élő ellenőrzések (`nmb-selftest`) a dobozon futnak, nem a PC-n.

## 6. Egy változtatás telepítése a dobozra

Mindig úgy telepíts, ahogy a felhasználók is kapják: a `setup.sh`-val. Egyes fájlokat soha ne másolj át. Kivétel egy gyors próba, de akkor ezt mondd is meg.

```bash
sha=$(git rev-parse --short HEAD)
git archive HEAD -o /tmp/nmb.tar
scp /tmp/nmb.tar nmb-box:/tmp/nmbd.tar
ssh nmb-box "rm -rf /tmp/nmbd && mkdir /tmp/nmbd && tar xf /tmp/nmbd.tar -C /tmp/nmbd && cd /tmp/nmbd && \
  sudo -S -p '' sh -c 'env NMB_SOURCE_COMMIT=$sha bash setup.sh > /tmp/setupd.log 2>&1; echo rc=\$?; cd /; rm -rf /tmp/nmbd /tmp/nmbd.tar'" < ~/.nmb-pw
```

Utána takaríts el. A doboz `/tmp`-je egy 256 MB-os tmpfs, és az otthagyott másolatok egyszer már megtöltötték. Ezután ellenőrizd a dobozt:

```bash
ssh nmb-box 'sudo -S -p "" nmb-selftest' < ~/.nmb-pw
```

## 7. Tesztek, amelyek elvágják a doboz saját kapcsolatát

A router mód, az USB tethering és a kábelek áthelyezése megváltoztatja a doboz útvonalait. Ezeket csak a vezetett forgatókönyvekkel futtasd. A forgatókönyv:
- szolgáltatásként fut a dobozon;
- előbb elmenti a beállításokat, hogy vissza tudja állítani őket;
- ha a Tailscale 2 percig nem kapcsolódik, leáll, és mindent visszaállít;
- 45 perc után mindenképp visszaállít.

```bash
ssh nmb-box "sudo -S -p '' systemd-run --unit=nmb-scenario -p StandardOutput=file:/var/log/nmb/scenario-router.log nmb-selftest scenario router" < ~/.nmb-pw
ssh nmb-box 'tail -f /var/log/nmb/scenario-router.log'
```

Kézzel: `sudo nmb-selftest restore`. Részletek: [TESTING.hu.md](TESTING.hu.md), 2a. és 7. pont.

## 8. Az ügynök memóriája

A Claude Code a projekttel kapcsolatos jegyzeteit gépenként tárolja, a `~/.claude/projects/<a-repó-útvonala>/memory/` mappában. Ezekben van a munka állása, a doboz elérése és a tulajdonos szabályai. Egy új gépen ezek hiányoznak. Két megoldás van:

- másold át a mappát a régi PC-ről a WSL-be, az új repó útvonaláról elnevezett mappába (ez a mappa akkor jön létre, amikor a Claude Code-ot egyszer elindítod a repóban);
- vagy az első üzenetben írd meg az ügynöknek, hol tart a munka, és kérd meg, hogy mentse el.

Ezekben a jegyzetekben benne lehet, hogyan érhető el a doboz. Ne tedd be őket a repóba.

## 9. Szabályok, amelyek maradnak

- Titok nem kerülhet a repóba, a commitokba vagy a naplókba: token, jelszó, kulcs, Wi-Fi jelszó.
- A tulajdonos nyilvános címei (otthoni vonal, mobil) és a Tailscale-cím nem kerülhetnek a repóba.
- Ookla legfeljebb óránként egyszer; a rate limit megkerülésére nem írunk kódot.
- Minden, a felhasználó által látható változás bekerül a `CHANGELOG.md`-be; a dokumentáció angolul és magyarul is készül.
- Őszinte eredmények: ami élesben nem ment át, azt nem írjuk le működőnek ([TESTING.hu.md](TESTING.hu.md)).

## Ellenőrzőlista

| Lépés | Akkor kész, ha |
|---|---|
| WSL2 Ubuntu | a `wsl -l -v` a 2-es verziót mutatja |
| Tailscale | a `ping <doboz-tailscale-ip>` válaszol a WSL-ből |
| SSH | az `ssh nmb-box hostname` jelszó nélkül működik |
| Repó | a `~/src` alá klónozva, `core.autocrlf false` |
| GitHub | a `git push --dry-run` működik |
| Egységtesztek | a `python3 -m unittest discover -s tests` átmegy |
| Doboz | az `nmb-selftest` a dobozon nem jelez bukást |
| Ügynök memóriája | átmásolva, vagy az állapot megadva az első üzenetben |
