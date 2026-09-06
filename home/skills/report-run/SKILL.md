---
name: report-run
description: |
  Lefuttat egy aktív riportot egy időszakra: szinkron a szamlazz.hu adatokból, build a spec szerint, ellenőrzés, leszállítás a megadott mappába, majd megnyitja a kész xlsx-et és felajánlja a kísérőlevelet. Akkor indítsd, ha a felhasználó riportot futtatna, például "futtasd a havi riportot", "/report-run havi_arbev_kintlev", "csináld meg az augusztusi riportot", "futtasd le az összes riportot", "csak szinkronizálj".
---

# /report-run

Használat: `/report-run <slug> [--period ÉÉÉÉ-HH] [--sync-only]` vagy `/report-run --all [--period ÉÉÉÉ-HH]`. Minden parancs a `~/Riportok` mappából fut. A skill nem ír a leszállítási mappába közvetlenül: a `build.py` a `.staging/` mappába épít, és onnan mozgat; a `protect_delivery.py` hook minden más utat tilt, ezt ne kerüld meg.

## 1. Paraméterek

1. Slug: a parancs első szava. Ha hiányzik, `Bash`: `uv run scripts/run_reports.py --list`, majd `AskUserQuestion`: "Melyik riportot futtassam?" az aktív slugokkal opcióként. A draft riportot ne ajánld: arra a `/report-new` folytatása való.
2. Időszak `<P>`: a `--period` értéke, különben az utolsó teljes hónap `ÉÉÉÉ-HH` alakban (a mai dátum előtti hónap). Negyedéves vagy heti riportnál a `build.py` érti az `ÉÉÉÉ-Qn` és `ÉÉÉÉ-Whh` alakot is; a szinkronhoz akkor is a benne lévő hónapok kellenek.
3. `Read`: `reports/<slug>/spec.yaml` (`report.title_hu`, `report.status`, `delivery.folder`, `period.grain`). Ha a `status` nem `active`, állj meg: draft -> `/report-new`, retired -> nincs futtatás.
4. `Read`: `~/.claude/kit-state.json` (`flags.nav`).

## 2. Szinkron

1. `Bash`: `uv run scripts/szamlazz_sync.py status` (előtagok, utolsó szinkron).
2. Szinkron a `flags.nav` szerint:

| `flags.nav` | Parancs |
|---|---|
| `false` | `uv run scripts/szamlazz_sync.py pull --agent-only --prefix "<ELŐTAG>" --year <ÉÉÉÉ>` (minden előtagra, amelyet a `status` mutat: ismételt `--prefix`; az év a `<P>` éve) |
| `true` | `uv run scripts/szamlazz_sync.py pull --period <ÉÉÉÉ-HH>` |

3. Kilépési kód:

| Kód | Jelentés | Teendő |
|---|---|---|
| 0 | rendben | tovább |
| 1 | adathiba egyes számláknál | mutasd a kiírt sorokat; `AskUserQuestion`: "Folytassam a riport felépítését a hiányos adattal?" |
| 2 | hiányzó kulcs vagy hibás használat | állj meg; README "Kulcsok", `doctor.ps1` |
| 3 | hálózat | állj meg; próbáld később |

4. `--sync-only`: itt vége. `Bash`: `uv run scripts/szamlazz_sync.py status`, és foglald össze három sorban (előtagonként darab, utolsó szinkron, számozási hiány).

## 3. Build

`Bash`: `uv run "reports/<slug>/build.py" --period <P> --json`

A parancs először magyar előnézeti sorokat ír (cím, sorok száma, nettó árbevétel, kintlévőség, eltérés az előző futtatáshoz képest, ellenőrzések), utána egy JSON objektumot: `slug, period, version, outcome, outcome_hu, delivered_path, staging_path, checks[], row_counts, totals{rev_net, inv_count, ar_balance, overdue_amt}, previous_totals, powerbi_files, exit_code`. A `checks[]` elemei: `id, title_hu, status (ok|warn|fail|skipped), detail_hu, blocking`. A `previous_totals` ugyanennek az időszaknak az előző futtatásából származó `totals` objektum, vagy `null`, ha még nem volt futtatás.

## 4. Előnézet a felhasználónak

Egy táblázat ezekkel a sorokkal:

| Sor | Forrás |
|---|---|
| Riport, időszak, verzió | JSON `slug`, `period`, `version` |
| Eredmény | `outcome_hu` |
| Nettó árbevétel | `totals.rev_net` (Ft; ezer Ft-ban írd ki, magyar számformátummal, például 12 340 e Ft) |
| Kintlévőség | az előnézeti sorok "Kintlévőség" értéke |
| Eltérés az előző futtatáshoz | az előnézeti "Előző futtatás" sor; ha nincs, írd ki, hogy nincs |
| Sorok | `row_counts` (számla, tétel, kifizetés, vevő) |
| Ellenőrzések | csak a `warn` és `fail` státuszú `checks` sorok: id, detail_hu, blokkoló-e |
| Fájl | `delivered_path` |

Az `ok` ellenőrzéseket ne sorold fel; egy sor elég: "a többi ellenőrzés rendben".

## 5. Kilépési kód szerint

| Kód | `outcome` | Mi történt | Teendő |
|---|---|---|---|
| 0 | delivered | a fájl a `delivery.folder` mappában van | 6. lépés |
| 1 | rejected | blokkoló ellenőrzés bukott; a fájl `<delivery.folder>/_rejected/<név>_FAILED.xlsx` | állj meg; írd ki a `fail` sorok `detail_hu` szövegét; a részletek a fájl `Futtatási napló` lapján; adathiba esetén szinkron és `uv run scripts/szamlazz_sync.py reconcile --period <P>`, spec-hiba esetén `/report-edit <slug>` |
| 1 | pending | a célfájl zárolva (nyitva Excelben vagy OneDrive szinkron alatt); a riport `<név>.pending.xlsx` néven ott van | állj meg; zárd be a fájlt, majd `/report-run` újra; a `.pending.xlsx` fájlt ne nevezd át |
| 1 | exists | `delivery.overwrite: never` és a fájl már létezik | állj meg; a felhasználó dönt: a régi fájl marad, vagy `/report-edit` az `overwrite` értékéhez |
| 2 | (nincs) | spec- vagy használati hiba | `Bash`: `uv run scripts/report_spec.py --validate "reports/<slug>/spec.yaml"`, majd `/report-edit <slug>` |

Elutasított vagy függő fájlt ne javíts, ne mozgass, ne nevezz át: a hook tiltja, és a következő futás rendezi.

## 6. Siker után

1. `Bash`: `powershell -Command "Invoke-Item '<delivered_path>'"` (a JSON útvonala, ahogy kapod).
2. `AskUserQuestion`: "Írjak kísérőlevelet a riporthoz?" Opciók: "Igen, /draft-email" | "Nem".
3. Igen esetén indítsd a `/draft-email` skill "havi riport e-mail" receptjét; add át a JSON objektumot, az előnézeti sorokat, a `delivered_path` értéket és a `title_hu` címet.
4. Záró sor: `Leszállítva: <delivered_path> (<P>, v<verzió>)`.

## `--all`

`Bash`: `uv run scripts/run_reports.py --all --period previous_month` (vagy a megadott `--period`). Ugyanez fut a Feladatütemezőből havonta. Előtte a 2. lépés szinkronja egyszer, az összes előtagra. A kimenet riportonként egy sor: slug, időszak, eredmény, kód, fájl, üzenet; a végén "n riport sikeres" vagy "n riport sikertelen". Kilépési kód 1, ha bármelyik nem sikerült: azokra az 5. lépés táblázata érvényes, egyenként.

## Ha elakad

| Helyzet | Teendő |
|---|---|
| "nincs ilyen riport" | `uv run scripts/run_reports.py --list`, slug ellenőrzése (snake_case) |
| A `build.py` hiányzik a riport mappájából | a riport draft állapotban maradt: `/report-new` folytatása |
| V04 vagy V05 bukik (tétel- vagy áfaösszeg nem egyezik a fejléccel) | szinkron újra a hónapra, majd `uv run scripts/szamlazz_sync.py reconcile --period <P>`, ha van Főkönyvi CSV a `data/drops/` alatt |
| V11 bukik (lánc integritás) | feloldatlan sztornó vagy helyesbítő lánc: a `status` "Nem aktív láncok" blokkja; a szinkron dolga, ne javítsd kézzel |
| A hook tiltott egy műveletet | szándékos; a leszállítási mappába csak a `build.py` ír |
| A fájl nem nyílik meg | írd ki az útvonalat; a felhasználó nyissa meg kézzel |
| A riport hónapja után új számla érkezett | futtasd újra ugyanarra a `<P>` időszakra; `same_version` felülírja az azonos verziójú fájlt |

## Szabályok

- Soha ne szerkeszd a leszállított xlsx fájlt, és ne másold kézzel a leszállítási mappába.
- Soha ne futtasd a `build.py`-t `--out` kapcsolóval a leszállítási mappára.
- A kísérőlevél csak piszkozat; küldeni a felhasználó küld.
