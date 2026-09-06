---
name: report-list
description: |
  Kilistázza a riportokat a ~/Riportok/reports mappából: slug, cím, verzió, státusz, időszaktípus, utolsó futás és eredmény, leszállított fájl, és minden riporthoz egy következő lépést javasol. Akkor indítsd, ha a felhasználó áttekintést kér, például "milyen riportjaim vannak", "/report-list", "mikor futott utoljára a havi riport", "melyik riport nincs kész", "mutasd a riportokat".
---

# /report-list

Csak olvas. Minden parancs a `~/Riportok` mappából fut.

## 1. Lista

`Bash`: `uv run scripts/run_reports.py --list`

Oszlopok a kimenetben: slug, cím, verzió, státusz, időszak (grain), utolsó futás, eredmény, kézbesített fájl. Gépi feldolgozáshoz: `uv run scripts/run_reports.py --list --json` (ugyanez JSON listaként, plusz `last_period`, `last_outcome`, `has_build`).

Ha a parancs hibával zárul, tartalék: `Glob` `reports/*/spec.yaml`, minden fájlból `Read` a `report` és a `period` szakasz, és a `reports/<slug>/runlog.jsonl` utolsó sora (`period`, `run_ts`, `outcome`, `delivered_path`). A `reports/_examples/` mappát hagyd ki a listából.

## 2. Táblázat a felhasználónak

| Oszlop | Forrás | Megjelenítés |
|---|---|---|
| Riport | `title_hu` (`slug`) | cím, zárójelben a slug |
| Verzió, státusz | `version`, `status` | `1.2.0 aktív`, `0.1.0 vázlat`, `1.0.0 kivezetett` |
| Időszak | `grain` | havi, negyedéves, heti, év elejétől, egyedi |
| Utolsó futás | `last_run_ts`, `last_period` | `2026-09-05 07:12 (2026-08)` vagy `még nem futott` |
| Eredmény | `last_outcome_hu` | ahogy a script adja (kézbesítve, elutasítva, függőben, próbafuttatás, nem írható felül) |
| Fájl | `delivered_path` | teljes útvonal, vagy üres |
| Következő lépés | a 3. lépés szabályai | egy rövid parancs |

Rendezés: aktív riportok elöl, utána a vázlatok, a végén a kivezetettek; azonos státuszon belül ábécé.

## 3. Következő lépés riportonként

| Állapot | Következő lépés |
|---|---|
| `status: draft`, nincs `build.py` | `/report-new` folytatja (a spec megvan, a build és a próbafuttatás hiányzik) |
| `draft`, `has_build` igaz | `/report-new` a 7. körtől: ellenőrzés és aktiválás |
| `active`, ebben a hónapban még nem futott az előző hónapra | `/report-run <slug>` |
| `active`, utolsó eredmény `delivered` az előző hónapra | rendben; `/report-edit <slug>`, ha változtatna |
| `active`, utolsó eredmény `rejected` | a `_rejected` fájl `Futtatási napló` lapja (lent), majd `/report-run <slug>` a hiba elhárítása után |
| `active`, utolsó eredmény `pending` | zárd be a nyitott xlsx-et, majd `/report-run <slug>` |
| `active`, utolsó eredmény `exists` | a fájl már megvan, és a felülírás tiltott; `/report-edit <slug>`, ha mégis frissíteni kell |
| `active`, utolsó eredmény `dry_run` | még nem volt éles futás: `/report-run <slug>` |
| `retired` | nincs teendő; a régi fájlok a leszállítási mappában maradnak |

"Ebben a hónapban" a mai dátum hónapja; "előző hónap" az azt megelőző `ÉÉÉÉ-HH`. Havi riportnál ezt nézd; negyedéves vagy heti riportnál az utolsó teljes negyedévet vagy hetet.

Az elutasított fájl futtatási naplója (`Bash`, csak olvasás; a fájl a `<delivery.folder>/_rejected/` mappában van):

```
uv run --with openpyxl python -c "import openpyxl,sys; ws=openpyxl.load_workbook(sys.argv[1], read_only=True)['Futtatási napló']; [print(*[c for c in r if c is not None]) for r in ws.iter_rows(values_only=True)]" "<delivery.folder>/_rejected/<név>_FAILED.xlsx"
```

Írd ki belőle a bukott ellenőrzések sorait (id, üzenet). Ne javíts, ne mozgass semmit.

## 4. Sablonok

A `reports/_examples/` mappa négy mintaspecet tartalmaz. Ezek nem futtatható riportok, hanem kiindulópontok a `/report-new` interjúhoz (az alapértelmezések innen jönnek):

| Sablon | Mire |
|---|---|
| `havi_arbev_kintlev` | havi árbevétel, kintlévőség, korosítás, DSO, beszedés, sztornó (a fő minta) |
| `afa_analitika_negyedev` | negyedéves ÁFA-analitika kulcsonként, bevallás előkészítéséhez |
| `ugyfel_koncentracio_churn` | ügyfélkoncentráció, top-N részarány, új és elvesztett vevők |
| `kintlev_behajtas_heti` | heti lejárt tételek behajtáshoz |

A lista alatt egy sor: "Új riporthoz: /report-new; a sablonok a reports/_examples mappában vannak."

## 5. Zárás

Három parancs egy sorban: `/report-run <slug>`, `/report-edit <slug>`, `/report-new`. Ha egyetlen riport sincs a `reports/` alatt, csak ennyi: "Még nincs riport. Kezdd a /report-new paranccsal; a sablonok a reports/_examples mappában vannak."

## Ha elakad

| Helyzet | Teendő |
|---|---|
| "nincs aktív riport itt" | csak vázlatok vannak: a lista a 3. lépés szerint `/report-new` javaslattal |
| A `runlog.jsonl` hiányzik egy riportnál | "még nem futott"; nem hiba |
| A `run_reports.py` nem indul (uv hiba) | `doctor.ps1`; addig a tartalék lista az 1. lépés szerint |
| Egy slug kötőjelet tartalmaz | régi vagy kézzel készült mappa; a validálás elutasítja: a felhasználó nevezze át snake_case alakra (a mappát és a `report.slug` kulcsot együtt) |
| Az `_rejected` fájl nem nyitható | OneDrive még szinkronizálja, vagy nyitva van Excelben; próbáld később, vagy a felhasználó nyissa meg kézzel |

## Szabályok

- Ne építs riportot, és ne szinkronizálj ebben a skillben.
- Ne módosítsd a leszállított és az elutasított fájlokat; útvonalat és tartalmat olvasol, nem írsz.
- A táblázat magyar, az azonosítók (slug, id, kulcsok) angolok.
