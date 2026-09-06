# Haladó beállítások és parancsok

Ez a fájl minden olyan részletet összegyűjt, ami a `README.md` fájlból szándékosan kimaradt. Akkor kell, ha a Gmailt vagy a NAV-ot is bekötnéd, ha a telepítőt más kapcsolókkal futtatnád, ha kézzel szinkronizálnál, vagy ha a készletet frissítenéd, illetve leszednéd a gépről.

Rövidítések: a `%USERPROFILE%` a felhasználói mappád (például `C:\Users\Fanni`). A készlet mappája `%USERPROFILE%\claude-kit`, a munkamappa `%USERPROFILE%\Riportok`. A `uv run scripts\...` alakú parancsokat mindig a Riportok mappából add ki, PowerShell ablakban.

## A telepítő kapcsolói

A telepítőt kétféleképpen indíthatod: dupla kattintással az `install.bat` fájlra, vagy PowerShellből, a claude-kit mappából:

```
powershell -ExecutionPolicy Bypass -File .\install.ps1 -WhatIf -SkipGmail -SkipNav
```

Az `install.bat` minden kapcsolót továbbad, tehát PowerShellből így is jó: `.\install.bat -SkipGmail -SkipNav`.

| Kapcsoló | Mit csinál |
|---|---|
| `-WhatIf` | Csak kiírja a tervet, nem változtat semmit. Első alkalommal mindig ezzel kezdd. |
| `-SkipGmail` | Kihagyja a Gmail MCP letöltését és a postafiók bekötését. |
| `-SkipNav` | Nem kéri be a NAV technikai felhasználó négy adatát. |
| `-NoAdmin` | Rendszergazdai jog nélkül fut: a Pythont az uv rakja fel, a Git és a Node telepítését kihagyja (a Gmail MCP ilyenkor nem működik). |
| `-Update` | Újratelepítés a meglévő beállítások megtartásával. A saját riportjaid, az adatbázis és a kulcsok maradnak. |
| `-Level N` | A készlet szintje (1, 2 vagy 3). Alapból a meglévő szint marad, első telepítéskor 1. |

A telepítőt nyugodtan futtathatod többször: a kész lépéseket átugorja, és csak azt csinálja meg, ami hiányzik. Ha megszakad, hárítsd el a hibát, és indítsd újra.

Amit sorban feltelepít, illetve beállít: winget, Claude Code, Git, Python 3.12, Node LTS, uv (Python futtató), keyring (a kulcsok tárolója), a készlet fájljainak másolása a `%USERPROFILE%\.claude` mappába a hookokkal együtt, a Riportok mappa létrehozása, az MCP szerverek bejegyzése, a Gmail MCP (ha nincs kihagyva), a kulcsok bekérése, a `kit-state.json` állapotfájl, végül a `doctor.ps1`.

A telepítés után új PowerShell ablak kell, mert a frissen telepített programok csak új ablakban látszanak.

## Ellenőrzés: doctor.ps1

```
powershell -ExecutionPolicy Bypass -File "$HOME\claude-kit\doctor.ps1"
```

Csak olvas, soha nem javít, és mindig hiba nélkül áll le. Minden sor `[OK]`, `[!]` vagy `[X]` jelöléssel kezdődik, és a nem OK sorok alatt egy "mit tegyél" tanács áll. Amit megnéz: Claude Code, Python, uv, Node és Git megléte és verziója; a szinthez tartozó MCP szerverek; az öt kulcs megvan-e (érték nélkül); a hookok a `settings.json` fájlban; az adatbázis és az utolsó szinkron; a riportok leszállítási mappái írhatók-e; a Gmail fiókok és a jogkivonatuk kora; a készlet szintje.

Ha segítséget kérsz, fájlba is mentheted: tedd a parancs végére, hogy `> "$HOME\Desktop\doctor.txt"`. A `-Json` kapcsolóval gépi feldolgozásra alkalmas kimenetet ad.

## Frissítés: update.ps1

```
powershell -ExecutionPolicy Bypass -File "$HOME\claude-kit\update.ps1"
```

Letölti a készlet új változatát (`git pull`), majd lefuttatja a telepítőt `-Update` módban. A készlet saját fájljai (a `.claude` mappában és a `Riportok\scripts` mappában) frissülnek; a saját riportjaid (`Riportok\reports`), az adatbázis és a kulcsok maradnak. Ha egy készletfájlt kézzel módosítottál, arról előbb biztonsági másolatot tesz a `%USERPROFILE%\.claude\.kit-backups` mappába, és csak utána írja felül. Ugyanazokat a kapcsolókat fogadja, mint a telepítő.

## Hol vannak a kulcsok és jelszavak

A Windows Hitelesítőadat-kezelőben (Credential Manager), a `keyring` nevű eszközön keresztül. Fájlban, chatben, naplóban nincsenek. Öt tétel van:

| Szolgáltatás | Név | Mi ez |
|---|---|---|
| `szamlazz.hu` | `agent-key` | Számla Agent kulcs |
| `nav.gov.hu` | `tech-login` | NAV technikai felhasználó neve |
| `nav.gov.hu` | `tech-password` | NAV technikai felhasználó jelszava |
| `nav.gov.hu` | `signing-key` | NAV aláírókulcs |
| `nav.gov.hu` | `tax-number` | az adószám első 8 számjegye |

Tárolás és ellenőrzés a Riportok mappából:

```
uv run scripts\get_secret.py set szamlazz.hu agent-key
uv run scripts\get_secret.py check
```

A `set` bekéri az értéket (gépelés közben nem látszik), a `check` kiírja, melyik tétel van meg és melyik hiányzik, érték nélkül. Törölni a Hitelesítőadat-kezelőben lehet kézzel (Vezérlőpult, Hitelesítőadat-kezelő, Windows hitelesítő adatok).

## A szinkron parancsai

A szinkron a szamlazz.hu számláit egy helyi adatbázisba (`Riportok\data\invoices.db`) tölti, és mindig csak az újakat kéri le. Minden parancs a Riportok mappából:

```
uv run scripts\szamlazz_sync.py init
uv run scripts\szamlazz_sync.py pull --agent-only --prefix SZLA --year 2026
uv run scripts\szamlazz_sync.py pull --period 2026-08
uv run scripts\szamlazz_sync.py import-csv "data\drops\fokonyvi_2026-08.csv"
uv run scripts\szamlazz_sync.py import-afalista "data\drops\afalista_2026-08.xlsx"
uv run scripts\szamlazz_sync.py reconcile --period 2026-08
uv run scripts\szamlazz_sync.py status
```

| Parancs | Mit csinál |
|---|---|
| `init` | Létrehozza az adatbázist. A telepítő ezt megcsinálja, kézzel csak akkor kell, ha törölted. |
| `pull --agent-only --prefix P --year YYYY` | Az Agent kulccsal, sorszám szerint végigkéri a `P-YYYY-N` alakú számlákat, az utolsó ismert sorszámtól. Több előtagnál a `--prefix` ismételhető. Ez az alapeset, amíg nincs NAV. |
| `pull --period YYYY-MM` | NAV technikai felhasználóval: előbb a NAV-tól kéri le a hónap számlalistáját, majd az Agenttel a részleteket. Csak akkor működik, ha a NAV adatok meg vannak adva. |
| `import-csv <fájl>` | Betölti a szamlazz.hu Főkönyvi adatexportját (CSV) az egyeztetéshez. |
| `import-afalista <fájl>` | Betölti a szamlazz.hu Áfalistáját (XLSX) az egyeztetéshez. |
| `reconcile --period YYYY-MM` | Összeveti az adatbázist a betöltött exportokkal, és kiírja az eltéréseket. |
| `status` | Utolsó szinkron forrásonként, számlák előtag és év szerint, sztornó- és módosítóláncok, hiányzó sorszámok. |

Hasznos kapcsolók a `pull` parancshoz: `--max 50` a kérések felső korlátja előtagonként (alapból 500; amíg a díjkérdés nincs tisztázva, ezzel próbálj), `--start-seq N` a kezdő sorszám, ha az alapérték (utolsó ismert plusz egy) nem jó. A `reconcile` tűréshatárát a `--tolerance` adja meg forintban, alapból 1.

A kilépési kódok: 0 rendben; 1 adathiba egyes számláknál (a kiírt sorok mondják meg, melyik); 2 hiányzó kulcs vagy rossz használat (nézd meg a `get_secret.py check` kimenetét); 3 hálózati hiba, próbáld később.

## Kézi egyeztetés havonta

Ez nem kötelező, de a lezárt hónapok ellenőrzésére jó:

1. A szamlazz.hu Listák menüjében töltsd le az előző hónap Főkönyvi adatexportját (CSV) és Áfalistáját (XLSX).
2. Tedd a két fájlt a `Riportok\data\drops` mappába.
3. Futtasd le az `import-csv`, az `import-afalista`, majd a `reconcile --period` parancsot a fenti minta szerint.
4. Ha a `reconcile` kilépési kódja 0, minden egyezik. Ha nem, a kiírt sorok mutatják a számlaszámot, a mezőt és az eltérést; a részletes listát egy fájlba is menti, az útvonalát kiírja.

## Gmail bekötése

A Gmail arra kell, hogy a `/draft-email` parancs (és a `/report-run` végén felajánlott kísérőlevél) piszkozatot tudjon írni a postafiókodba. Küldeni sosem küld. Postafiókonként egyszer kell egy Google OAuth ügyfelet készíteni; ez egy JSON fájl, amivel a készlet be tud lépni a postafiókodba.

A Google Cloud Console-ban (`console.cloud.google.com`), az adott postafiókkal belépve:

1. Hozz létre egy projektet, vagy válassz egy meglévőt.
2. API-k és szolgáltatások, Könyvtár: engedélyezd a Gmail API-t.
3. OAuth-hozzájárulási képernyő: céges Workspace postafióknál Belső (Internal) típus; személyes Gmailnél Külső (External), és a képernyőt tedd közzé éles állapotba (Publish app). Ha Tesztelés állapotban marad, a jogkivonat 7 nap után lejár, és újra be kell jelentkezni; a `doctor.ps1` 5 napos kortól figyelmeztet.
4. Hitelesítő adatok, Hitelesítő adatok létrehozása, OAuth-ügyfélazonosító, típus: Asztali alkalmazás (Desktop app).
5. Töltsd le a JSON fájlt (például `oauth-ceges.json`) egy biztonságos helyre.

Ezután jön a Gmail MCP telepítése és a fiók bekötése. A legegyszerűbb, ha újra lefuttatod a telepítőt a `-SkipGmail` nélkül: `.\install.ps1 -Update -SkipNav`. Ez letölti és felépíti a Gmail MCP-t a `%USERPROFILE%\Gmail-MCP-Server` mappába, majd megkérdezi, hozzáadsz-e postafiókot, és kéri a letöltött JSON teljes útvonalát. Ekkor megnyílik a böngésző, belépést és hozzájárulást kér. Később, további fiókhoz, kézzel:

```
node "%USERPROFILE%\Gmail-MCP-Server\dist\index.js" auth --keys "%USERPROFILE%\oauth-ceges.json"
```

A jogkivonat a `%USERPROFILE%\.gmail-mcp\accounts\<email>\credentials.json` fájlba kerül. A `GMAIL_CREDENTIALS_PATH` környezeti változót ne állítsd be, az egy másik (Docker-es) használathoz való, és itt csak zavart okoz. Az MCP neve a Claude Code-ban: `gmail`.

Ha a Gmail MCP lejárt jogkivonatot jelez: a hozzájárulási képernyő Tesztelés állapotban maradt. Tedd közzé éles állapotba (Workspace-nél Belső típus), majd futtasd újra a fenti `auth --keys` parancsot arra a fiókra.

## NAV technikai felhasználó

A NAV Online Számla bekötése a 2. szinthez tartozik. Ezzel a szinkron a NAV-tól kéri le a hónap számlalistáját, és az Agenttel csak a részleteket tölti le; így a számlák egy független forrással is összevethetők.

1. A cég Online Számla elsődleges felhasználója (Ügyfélkapu+ belépéssel) az `onlineszamla.nav.gov.hu` felületen létrehoz egy technikai felhasználót "számlák lekérdezése" joggal, és aláírókulcsot készít hozzá. Négy adat kell: felhasználónév, jelszó, aláírókulcs, a cég adószámának első 8 számjegye.
2. Futtasd újra a telepítőt a `-SkipNav` nélkül a claude-kit mappából: `.\install.ps1 -Update -SkipGmail`. A hiányzó NAV tételeket sorban bekéri. Ugyanez kézzel, a Riportok mappából:

```
uv run scripts\get_secret.py set nav.gov.hu tech-login
uv run scripts\get_secret.py set nav.gov.hu tech-password
uv run scripts\get_secret.py set nav.gov.hu signing-key
uv run scripts\get_secret.py set nav.gov.hu tax-number
```

3. Ellenőrzés: `uv run scripts\get_secret.py check`, majd egy próbaszinkron az előző hónapra: `uv run scripts\szamlazz_sync.py pull --period 2026-08`.

Ettől kezdve a `/report-run` is a NAV-os módon szinkronizál (ezt a `%USERPROFILE%\.claude\kit-state.json` fájl `flags.nav` értéke mondja meg neki).

## A riport-parancsok részletei

| Parancs | Mire |
|---|---|
| `/report-new` | Új riport: interjú, leírás (spec), próbafuttatás az előző hónapra, aktiválás. Félbehagyott riportot is folytat. |
| `/report-run <slug>` | Elkészíti a riportot az előző hónapra. Más hónap: `/report-run <slug> --period 2026-07`. Csak szinkron, riport nélkül: `--sync-only`. |
| `/report-edit <slug>` | Meglévő riport módosítása. Csak az érintett kérdéseket teszi fel újra, verziót emel, és próbafuttatással ellenőriz. |
| `/report-list` | A riportok listája: név, verzió, állapot, utolsó futás, kész fájl. |
| `/prime` | Betölti a projekt állapotát a Riportok mappában (adatállapot, riportok, utolsó futások). Új beszélgetés elején hasznos. |
| `/draft-email` | Levélpiszkozat a Gmailben, küldés nélkül. |
| `/level-up` | A következő szint bekapcsolása. |

A `<slug>` a riport rövid neve (kisbetű, ékezet nélkül, aláhúzással, például `havi_arbev_kintlev`); a `/report-list` mutatja.

Minden riport egy mappa a `Riportok\reports` alatt: `spec.yaml` (a riport leírása; minden ebből készül), `build.py` (a leírásból készült program), `tests` és `runlog.jsonl` (a futások naplója). A kész `.xlsx` fájlt sosem szerkesztjük kézzel: a leírást módosítjuk a `/report-edit` paranccsal, és újrafuttatjuk.

Szintek: az 1. szint (Napi használat) a telepítéstől jár. A 2. szint (Kontroll) a tervezési módot, a `/prime` parancsot, a spec olvasását és szerkesztését, a NAV-forrást és a `microsoft-learn` MCP-t hozza. A 3. szint (Automatizálás) az ügynököket, a hookokat, a Power BI és az ms365 MCP-t, valamint a parancssori használatot (`claude -p`). A `/level-up` mindig egyet lép, és a Claude Code újraindítását kéri.

## Mi történik leszállításkor

A riport előbb egy átmeneti mappába épül, tizenhat ellenőrzésen megy át, és csak utána kerül a végleges helyére.

- Ha egy blokkoló ellenőrzés hibázik (V01 a spec olvashatósága, V04 tételösszeg, V05 ÁFA-bontás, V11 számlalánc, V15 belső egyeztetés, V16 a fájl épsége), a készlet nem szállítja le a riportot, hanem a leszállítási mappa `_rejected` almappájába teszi, `_FAILED` végződéssel. A fájl "Futtatási napló" lapja mutatja az okot. A szinkron vagy a leírás javítása után futtasd újra.
- Ha a célfájl nyitva van az Excelben (vagy a OneDrive épp szinkronizálja), a riport `<név>.pending.xlsx` néven kerül a mappába. Zárd be az Excelt, és futtasd újra a riportot, vagy nevezd át a fájlt a végleges névre.
- Ha ugyanarra a hónapra már van fájl, a leírás `delivery.overwrite` kulcsa dönt: `same_version` (azonos verziónál felülír, új verziónál verziószámot fűz a névhez), `always` (mindig felülír), `never` (nem ír felül, a futás hibával áll le).

## A leszállítási mappa módosítása

A legegyszerűbb: `/report-edit <slug>`, és a "kimenet, leszállítás, Power BI" részt válaszd. Kézzel: a `reports\<slug>\spec.yaml` fájlban a `delivery.folder` kulcs (OneDrive mappánál a teljes útvonalat add meg, például `C:/Users/Fanni/OneDrive - Cég/Riportok`), utána emelj verziót, és futtass próbát a Riportok mappából:

```
uv run scripts\report_spec.py --bump "reports\<slug>\spec.yaml" patch --note "új leszállítási mappa"
uv run "reports\<slug>\build.py" --period 2026-08 --dry-run
```

## Díjbekérők

Alapból a riportokba nem kerülnek be a díjbekérők (a leírásban `filters.exclude_proforma: true`, és a `doc_types` listában nincs `proforma`). Ha kellenek: az előtagjukat a szinkronnak is add meg (a `--prefix` kapcsoló ismétlésével), a leírásban `exclude_proforma: false` és `proforma` a `doc_types` listában. Egyszer ellenőrizni kell, hogy az Agent-lekérdezés egyáltalán visszaadja-e őket; ezt még nem próbáltuk ki.

## A készlet eltávolítása

1. MCP szerverek: a claude-kit mappából `powershell -ExecutionPolicy Bypass -File .\mcp\register-mcps.ps1 -Remove` (vagy egyenként: `claude mcp remove gmail`, `claude mcp remove excel`, és a magasabb szintűek).
2. A `%USERPROFILE%\.claude` mappából a készlet fájljai törölhetők; a listájuk a `%USERPROFILE%\.claude\.kit-manifest.json` fájlban van. A `settings.json` fájlból a készlet hook bejegyzései kézzel vehetők ki (a `.kit-backups` mappában van róla korábbi másolat).
3. A `%USERPROFILE%\claude-kit`, a `%USERPROFILE%\Gmail-MCP-Server` és a `%USERPROFILE%\.gmail-mcp` mappa törölhető.
4. A `%USERPROFILE%\Riportok` mappa a tiéd (riportok, adatbázis, kész fájlok): tartsd meg.
5. A kulcsokat a Hitelesítőadat-kezelőből kézzel lehet törölni.

## A szamlazz.hu díjkérdés

A készlet feltevése: az Agent-lekérdezés (`xmlszamlaxml` művelet) ingyenes, és díj csak a kiállított bizonylat után jár. Ezt írásban erősíttesd meg a szamlazz.hu ügyfélszolgálatával, mielőtt egy teljes évet letöltesz. Küldhető szöveg, a céges fiókból:

> Tárgy: Számla Agent lekérdezés díja
>
> Tisztelt Ügyfélszolgálat!
>
> A Számla Agent felületet kizárólag számlák lekérdezésére szeretnénk használni: xmlszamlaxml művelet, számlaszám alapján, havonta a saját kimenő számláink letöltése, számla kiállítása nélkül. Kérem, erősítsék meg, hogy a lekérdező hívásoknak nincs külön díja, és nem számítanak bele a csomag bizonylatkeretébe. Ha van díj vagy korlát, kérem, írják meg a mértékét.
>
> Fiók: <cégnév, szamlazz.hu felhasználónév>
>
> Köszönettel,
> <név, beosztás>

Amíg a válasz nincs meg, csak korlátozott próbaszinkron: `pull --agent-only --prefix SZLA --year 2026 --max 50`. Ha kiderül, hogy díjköteles: a havi szinkron kérésszáma a hónapban kiállított számlák száma plusz nagyjából három, ezzel kell számolni.
