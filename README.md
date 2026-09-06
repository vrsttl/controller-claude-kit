# controller-claude-kit

Claude Code alapú riportkészítő környezet kontrollereknek: szamlazz.hu számlaadatból havi Excel és Power BI riportok, Windows 11 laptopon, egy telepítővel.

## Mit ad a kit

- Szinkron, amely a szamlazz.hu Számla Agent (és opcionálisan a NAV Online Számla) adatait helyi SQLite gyorsítótárba tölti, mindig csak az új számlákat kérve.
- Riportok leírás alapján (`spec.yaml`): interjúkérdésekkel, nem kódolással; determinisztikus Python építi az Excel fájlt egy képernyős vezetői összefoglalóval, névvel ellátott táblákkal és Power BI CSV-kkel.
- Tizenhat ellenőrzés minden futásnál (tételösszeg, ÁFA-bontás, számlalánc, belső egyeztetés); ami blokkolót bukik, azt a kit nem szállítja le.
- Ütemezett havi futás a Windows Feladatütemezőből, Claude nélkül, a hónap 5-én.
- Három tanulási szint (Napi használat, Kontroll, Automatizálás), Gmail-piszkozatok két fiókkal, védőhookok a leszállított fájlok körül.

## Előfeltételek

| Mi | Miért |
|---|---|
| Windows 11, rendszergazdai jog (vagy a `-NoAdmin` kapcsoló) | a telepítő winget-tel rakja fel a Pythont, a Node-ot és a Gitet |
| Claude Pro vagy Max előfizetés | a Claude Code bejelentkezéshez |
| szamlazz.hu fiók és Számla Agent kulcs | Beállítások, Számla Agent; a kulcs 42 karakter, minden csomagban elérhető |
| Google Workspace vagy Gmail postafiók, fiókonként egy Google Cloud OAuth-ügyfél | a Gmail MCP-hez (lásd lent) |
| OneDrive vagy helyi mappa a kész riportoknak | ide szállít a `/report-run` |
| opcionális: NAV Online Számla technikai felhasználó | 2. szint, a NAV-forráshoz |

## Telepítés

1. Klónozás vagy a zip kicsomagolása ide: `%USERPROFILE%\claude-kit`

```
git clone https://github.com/vrsttl/controller-claude-kit.git %USERPROFILE%\claude-kit
```

2. Próba előbb, változtatás nélkül (PowerShell a mappában):

```
cd %USERPROFILE%\claude-kit
powershell -ExecutionPolicy Bypass -File .\install.ps1 -WhatIf
```

3. Dupla kattintás az `install.bat` fájlra. A telepítő sorban: winget, Claude Code, Git, Python 3.12, Node LTS, uv, keyring; a `home\` mappa másolása a `%USERPROFILE%\.claude\` alá; a `%USERPROFILE%\Riportok` mappa létrehozása; MCP-k regisztrálása; a Gmail MCP építése; titkok bekérése; ütemezett feladat; végül `doctor.ps1`.

4. Amit kérdez: a Számla Agent kulcs (láthatatlanul), a Gmail-fiókok OAuth-fájlja (fiókonként egy böngészős belépés), a NAV négy adata (csak ha nincs `-SkipNav`), és jóváhagyás az ütemezett feladathoz (kihagyás: `-SkipSchedule`).

Kapcsolók: `-Update` (újratelepítés a meglévő beállítások megtartásával), `-NoAdmin`, `-SkipGmail`, `-SkipNav`, `-SkipSchedule`, `-WhatIf`, `-Level N`.

## Első futtatás

1. Új PowerShell ablak (a PATH csak új ablakban frissül), majd `claude`, és bejelentkezés a böngészőben az előfizetéses fiókkal.
2. `cd %USERPROFILE%\Riportok`, majd `claude`, majd `/prime`: a projekt állapotát mutatja.
3. Első szinkron egyetlen előtagra, a saját számlaszám-előtaggal (`SZLA` helyett a tiéd):

```
uv run scripts/szamlazz_sync.py pull --agent-only --prefix SZLA --year 2026
```

4. `uv run scripts/szamlazz_sync.py status`: számlák előtag és év szerint, hiányok.
5. `/report-new`: az első riport interjúja, próbafuttatással.

Teljes évi felsorolás előtt olvasd el a GYIK díjra vonatkozó pontját.

## Gmail OAuth-ügyfél

Fiókonként egyszer, a Google Cloud Console-ban (`console.cloud.google.com`), az adott fiókkal belépve:

1. Projekt létrehozása (vagy meglévő kiválasztása).
2. API-k és szolgáltatások, Könyvtár: a Gmail API engedélyezése.
3. OAuth-hozzájárulási képernyő: Workspace postafióknál Belső (Internal) típus; személyes Gmailnél Külső (External), és a képernyő KÖZZÉTÉTELE éles állapotba (Publish app). Ha Tesztelés állapotban marad, a token 7 nap után lejár.
4. Hitelesítő adatok, Hitelesítő adatok létrehozása, OAuth-ügyfélazonosító, típus: Asztali alkalmazás (Desktop app).
5. A JSON letöltése (például `oauth-ceges.json`) biztonságos helyre.
6. A fiók hozzáadása a Gmail MCP-hez (a telepítő is ezt futtatja, később kézzel is mehet):

```
node "%USERPROFILE%\Gmail-MCP-Server\dist\index.js" auth --keys "%USERPROFILE%\oauth-ceges.json"
```

A böngésző belépést és hozzájárulást kér; a token a `%USERPROFILE%\.gmail-mcp\accounts\<email>\` mappába kerül. A `GMAIL_CREDENTIALS_PATH` környezeti változót ne állítsd be. Az MCP neve a Claude Code-ban: `gmail`.

## NAV technikai felhasználó (2. szint, opcionális)

1. A cég Online Számla elsődleges felhasználója (Ügyfélkapu+ belépéssel) az `onlineszamla.nav.gov.hu` felületen technikai felhasználót hoz létre "számlák lekérdezése" joggal, és aláírókulcsot generál. Kell: felhasználónév, jelszó, aláírókulcs, a cég adószámának első 8 számjegye.
2. `cd %USERPROFILE%\claude-kit`, majd `powershell -ExecutionPolicy Bypass -File .\install.ps1 -Update` (a `-SkipNav` nélkül).
3. A négy titok tárolása a `%USERPROFILE%\Riportok` mappából:

```
uv run scripts/get_secret.py set nav.gov.hu tech-login
uv run scripts/get_secret.py set nav.gov.hu tech-password
uv run scripts/get_secret.py set nav.gov.hu signing-key
uv run scripts/get_secret.py set nav.gov.hu tax-number
```

4. `uv run scripts/get_secret.py check`, majd `uv run scripts/szamlazz_sync.py pull --period 2026-08` (az előző hónapra).

## Havi rutin

1. A hónap 5-én 07:00-kor a `\Controller\HaviRiport` feladat lefuttatja az aktív riportokat az előző hónapra. Kézzel: `/report-run --all`.
2. szamlazz.hu, Listák: Főkönyvi adatexport (CSV) és Áfalista (XLSX) az előző hónapra; a fájlok a `%USERPROFILE%\Riportok\data\drops\` mappába.
3. Claude Code-ban vagy a parancssorból: `import-csv`, `import-afalista`, majd `uv run scripts/szamlazz_sync.py reconcile --period 2026-08`. Kilépési kód 0: rendben.
4. A kész fájl megnyitása a leszállítási mappából; ha valami hiányzik vagy változtatni kell: `/report-edit <slug>`, majd `/report-run <slug>`.
5. `/draft-email`: a kísérőlevél piszkozata a címzetteknek; a küldés kézzel.

## Frissítés

```
cd %USERPROFILE%\claude-kit
powershell -ExecutionPolicy Bypass -File .\update.ps1
```

`git pull`, majd `install.ps1 -Update`: a `home\` és a `scripts\` fájlok frissülnek; a saját riportok (`reports\`), az adat és a titkok maradnak. Kézzel módosított kit-fájlról biztonsági másolat készül a `%USERPROFILE%\.claude\.kit-backups\` alá.

## Ellenőrzés

```
cd %USERPROFILE%\claude-kit
powershell -ExecutionPolicy Bypass -File .\doctor.ps1
```

Táblázat `[OK]`, `[!]`, `[X]` jelöléssel: Claude Code, Python, uv, Node, Git verziók; MCP-k a szinthez; az öt titok; hookok a `settings.json`-ban; adatbázis és utolsó szinkron; leszállítási mappák írhatók-e; ütemezett feladat; Gmail-fiókok és a token kora; szint. Minden hibás sor alatt egy "mit tegyél" sor.

## GYIK

| Kérdés | Válasz |
|---|---|
| Mit jelent az engedélykérés? | Claude Code megkérdezi, futtathat-e egy parancsot vagy írhat-e egy fájlt. A kérdés mutatja, pontosan mit. A kit saját szkriptjei (`uv run scripts/...`) rendben vannak; ha nem érted, mondj nemet, nem romlik el semmi. |
| Nyitva volt az Excel, és `.pending.xlsx` lett a fájl | A célfájl zárolt volt, ezért a riport `<név>.pending.xlsx` néven került a mappába. Zárd be az Excelt, és futtasd újra a `/report-run` parancsot, vagy nevezd át a fájlt a végleges névre. |
| Megjelent egy `_rejected` mappa | Egy blokkoló ellenőrzés bukott (V01, V04, V05, V11, V15, V16), a riport nem lett leszállítva. A bukott fájl `Futtatási napló` lapja mutatja az okot; a szinkron vagy a spec javítása után újrafuttatás. |
| A Gmail MCP lejárt tokent jelez | Az OAuth-képernyő Tesztelés állapotban maradt: tedd közzé éles állapotba (Workspace-nél Belső típus), majd futtasd újra az `auth --keys` parancsot arra a fiókra. |
| Telepítés után az `uv` nem található | A PATH csak új ablakban frissül. Zárd be a PowerShellt vagy a terminált, és nyisd meg újra. |
| Fizetni kell az Agent-lekérdezésekért? | A kit feltevése: nem, a díj a kiállított bizonylat után jár. Ezt írásban erősíttesd meg a szamlazz.hu ügyfélszolgálatával, mielőtt egy teljes évet felsorolsz (a levélszöveg a `docs\HANDOVER.md` fájlban). Az inkrementális szinkron havonta csak az új számlákat kéri le. |
| Bekerülnek a díjbekérők? | Alapból nem (`filters.exclude_proforma: true`, a `doc_types` listában nincs `proforma`). Ha kellenek: az előtagjukat a szinkron is sorolja fel (`--prefix` ismételve), a specben `exclude_proforma: false` és `proforma` a `doc_types` listában, és egyszer ellenőrizni kell, hogy az Agent-lekérdezés visszaadja-e őket. |
| Hol vannak a jelszavak és kulcsok? | A Windows hitelesítőtárban (Credential Manager), a `keyring` csomagon keresztül. Listázás értékek nélkül: `uv run scripts/get_secret.py check`. Fájlban, chatben, naplóban nincsenek. |
| Hogyan változtatom meg a leszállítási mappát? | `/report-edit <slug>`, a kimenet és leszállítás kör; vagy a spec `delivery.folder` kulcsa, utána `--bump patch` és próbafuttatás. OneDrive-mappánál a teljes útvonalat add meg. |
| Hogyan távolítom el a kitet? | Ütemezett feladat: `schtasks /Delete /TN "\Controller\HaviRiport" /F`. MCP-k: `powershell -ExecutionPolicy Bypass -File .\mcp\register-mcps.ps1 -Remove` a kit mappájából (vagy egyenként `claude mcp remove gmail`, `excel` és a magasabb szintűek). A `%USERPROFILE%\.claude\` alól a kit fájljai (a `manifest.json` sorolja), a `%USERPROFILE%\claude-kit` és a `%USERPROFILE%\Gmail-MCP-Server` mappa törölhető. A `%USERPROFILE%\Riportok` mappa a tiéd, tartsd meg. A titkokat a hitelesítőtárból kézzel lehet törölni. |

## Mit NEM csinál a kit

- Nem küld e-mailt magától: csak piszkozatot készít, a küldés a tiéd.
- Nem ír a szamlazz.hu-ba: csak olvas (számla lekérdezése, PDF).
- Nem tölt fel sehová: a kimenet a helyi `exports\` mappa vagy az általad választott OneDrive-mappa.
- Nem szerkeszt kész riportot: minden változás a specen keresztül, újrafuttatással.
- Az ütemezett futás nem használ Claude-ot, és nem kérdez: ha bármi hiányzik, a riport nem szállít, és a napló mondja meg, miért.
