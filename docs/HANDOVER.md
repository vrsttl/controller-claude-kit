# Átadási jegyzet

A mentortól a kontrollernek, a telepítés előtt. Öt dolog kell előre; a többit a telepítő intézi.

## 1. Amit előre készíts elő

| # | Mi | Honnan | Mire |
|---|---|---|---|
| 1 | Számla Agent kulcs | szamlazz.hu, Beállítások, Számla Agent (42 karakter) | a szinkron ezzel kérdezi le a számlákat; a telepítő láthatatlanul kéri be, és a Windows hitelesítőtárban marad |
| 2 | NAV technikai felhasználó (opcionális) | a cég Online Számla elsődleges felhasználója (Ügyfélkapu+) hozza létre: név, jelszó, aláírókulcs, az adószám első 8 számjegye | a 2. szinten kapcsolható be; nélküle `-SkipNav` a telepítéskor, később pótolható |
| 3 | Google OAuth-ügyfél JSON postafiókonként | Google Cloud Console (lépések a `README.md` Gmail szakaszában); Workspace-fióknál Belső típus, személyesnél Külső és közzétett | a Gmail MCP fiókonként egy böngészős belépést kér a telepítés alatt |
| 4 | A leszállítási mappa útvonala | egy OneDrive for Business mappa, például `%USERPROFILE%\OneDrive - Cég\Riportok` | az első riport interjúja ezt kéri; ide kerülnek a kész fájlok, a Power BI innen frissül |
| 5 | Beleegyezés az ütemezett feladatba | döntés | a telepítő létrehozza a `\Controller\HaviRiport` feladatot (a hónap 5-én 07:00); ha nem kell, `-SkipSchedule` |

## 2. A telepítés sorrendje

1. Klónozás vagy zip a `%USERPROFILE%\claude-kit` mappába.
2. `install.ps1 -WhatIf` (csak listáz), majd `install.bat` dupla kattintással.
3. A telepítő kérdéseire: Agent-kulcs, OAuth JSON fiókonként, NAV adatok (vagy `-SkipNav`), ütemezés.
4. Új PowerShell ablak, `claude`, bejelentkezés az előfizetéses fiókkal.
5. `doctor.ps1`: minden sor `[OK]`, vagy javítás a "mit tegyél" sor szerint.

## 3. Első napi ellenőrzőlista

- [ ] `doctor.ps1` hibátlan (a NAV titkok kivételével, ha kihagytad)
- [ ] `uv run scripts/get_secret.py check`: `szamlazz.hu / agent-key` megvan
- [ ] `cd %USERPROFILE%\Riportok`, `claude`, `/prime` lefut, és 8 soros összefoglalót ad
- [ ] `uv run scripts/szamlazz_sync.py pull --agent-only --prefix <ELŐTAG> --year 2026 --max 50` egy előtagra, korlátozott kéréssel (a díj megerősítéséig)
- [ ] `uv run scripts/szamlazz_sync.py status`: a számlák darabszáma és tartománya egyezik a szamlazz.hu-n látottal, nincs hiány
- [ ] egy lezárt hónap Főkönyvi CSV és Áfalista XLSX a `data\drops\` mappában; `import-csv`, `import-afalista`, `reconcile --period` kilépési kód 0
- [ ] `/report-new` végigmegy egy próbariporton, a `_dryrun\` fájl megnyílik Excelben
- [ ] `/draft-email` piszkozatot készít a céges fiókban, és nem küld
- [ ] `schtasks /Query /TN "\Controller\HaviRiport"` mutatja a feladatot (ha kérted)

## 4. Kérdés a szamlazz.hu ügyfélszolgálatának

A kit azt feltételezi, hogy az Agent-lekérdezés (`xmlszamlaxml`) ingyenes, és díj csak a kiállított bizonylat után jár. Teljes évi felsorolás előtt ezt írásban meg kell erősíttetni. Küldhető szöveg (a céges fiókból, a szamlazz.hu ügyfélszolgálati címére):

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

Amíg a válasz nincs meg: csak `--max 50` korlátos próbaszinkron. Ha díjköteles: a havi inkrementális szinkron kérésszáma a havi számlaszám plusz 3, ezzel kell számolni.

## 5. Hibabejelentés

1. `cd %USERPROFILE%\claude-kit`, majd `powershell -ExecutionPolicy Bypass -File .\doctor.ps1 > "%USERPROFILE%\Desktop\doctor.txt"`.
2. E-mail a mentornak: a `doctor.txt` csatolva, mit csináltál, mi történt (a hibaüzenet szó szerint), és ha riportról van szó, a `reports\<slug>\runlog.jsonl` utolsó sora.
3. Titkot (kulcs, jelszó) soha ne másolj a levélbe; a doctor kimenete csak azt mutatja, megvan-e.

## 6. Szintek

| Szint | Mikor | Mit hoz |
|---|---|---|
| 1 Napi használat | a telepítéstől | `/report-new`, `/report-run`, `/report-list`, `/draft-email`, engedélykérések, Esc, `/clear` |
| 2 Kontroll | három sikeres hónapzárás után | tervezési mód, `/prime`, spec olvasása és `/report-edit`, `status`, NAV-forrás, `microsoft-learn` MCP |
| 3 Automatizálás | ha ütemezés, Power BI vagy `claude -p` kérdés jön | ügynökök, hookok, Feladatütemező, `powerbi-modeling` és `ms365` MCP, `web-researcher` |

A szintlépés a `/level-up` paranccsal történik, mindig egyet lép, és Claude Code újraindítást kér.
