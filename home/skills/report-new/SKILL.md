---
name: report-new
description: |
  Új riportot készít a szamlazz.hu számlaadatokból. Hét körös interjú (AskUserQuestion), utána a report-analyst ügynök megírja a spec.yaml fájlt, a report-engineer felépíti a build.py-t és lefuttatja a próbafuttatást az utolsó teljes hónapra, a report-reviewer visszaolvassa az xlsx-et, végül a riport aktív lesz. Akkor indítsd, ha új riport kell, például "csinálj egy új riportot", "kellene egy havi árbevétel riport", "készítsünk kintlévőség riportot", "folytassuk a félbehagyott riportot", "riportot szeretnék az ÁFA-ról negyedévente".
---

# /report-new

Új riport az interjútól az aktiválásig. Minden parancs a `~/Riportok` mappából fut. A spec az egyetlen igazságforrás; a build.py és a tesztek belőle készülnek.

## Áttekintés

| Lépés | Eszköz | Eredmény |
|---|---|---|
| 0. Előfeltételek | `Bash` | van szinkronizált adat a próbafuttatás hónapjára |
| 1. körtől az 5. körig: interjú | `AskUserQuestion` | válaszok, alapértelmezésekkel kitöltve |
| 6. kör: előnézet | `Read` (lapvázlat-sablon), `AskUserQuestion` | megerősített terv |
| Spec | `Bash` (`--new`, `--catalogue`, `--validate`), `Agent(report-analyst)` | `reports/<slug>/spec.yaml`, status draft |
| Build és próbafuttatás | `Agent(report-engineer)` | `build.py`, `tests/`, `_dryrun/*.xlsx` |
| 7. kör: ellenőrzés | `Agent(report-reviewer)`, `AskUserQuestion` | ítélet, "Aktiváljuk?" |
| Aktiválás | `Edit`, `Bash` | status active, verzió 1.0.0 |

Az interjú szövege, opciói és alapértelmezései: `references/interview.md`. A vezetői lap vázlatsablonja: `references/executive-mockup.md`. Olvasd be mindkettőt az interjú előtt (`Read`).

## 0. Előfeltételek

1. `Bash`: `uv run scripts/szamlazz_sync.py status`
2. A próbafuttatás hónapja az utolsó teljes hónap (a mai dátum előtti hónap). Nézd meg a `Számlák előtag és év szerint` blokkot és az `Utolsó szinkron forrásonként` sorokat: van-e ebben a hónapban kiállított számla, és volt-e sikeres szinkron (hiba=0) az adott évre.
3. Ha nincs, állj meg, és ajánld fel a kettő közül azt, amelyik a `~/.claude/kit-state.json` `flags.nav` értékéhez illik (`Read`):

| `flags.nav` | Parancs |
|---|---|
| `false` (alapeset) | `uv run scripts/szamlazz_sync.py pull --agent-only --prefix "<ELŐTAG>" --year <ÉÉÉÉ>` (több előtag: ismételd a `--prefix` kapcsolót; az előtagokat a `status` kimenete mutatja) |
| `true` | `uv run scripts/szamlazz_sync.py pull --period <ÉÉÉÉ-HH>` |

Kilépési kód: 0 rendben, 1 adathiba (nézd meg a kiírt sorokat), 2 hiányzó kulcs vagy hibás használat (README, keyring), 3 hálózat (próbáld később). Sikeres szinkron után folytasd az 1. körrel.

4. Ha a felhasználó egy `draft` státuszú riportot folytat (a `/report-list` mutatja), olvasd be a meglévő `reports/<slug>/spec.yaml` fájlt (`Read`), és az interjúban a benne lévő értékeket ajánld fel alapértelmezésként.

## Interjú (1. körtől a 6. körig)

1. Körönként egy `AskUserQuestion` hívás a `references/interview.md` szerint (kérdés, opciók, alapértelmezés). Az alapértelmezés mindig az első, ajánlott opció legyen.
2. Minden kör után jegyezd fel a tárolandó értékeket a fájl "Tárold" sora szerint. Ne kérdezz rá arra, amit a felhasználó már megmondott.
3. A slug ellenőrzése az 1. körben: `^[a-z0-9_]+$`, nincs kötőjel, nincs ékezet, és a `reports/<slug>/` mappa még nem létezik (`Bash`: `ls "reports/"`). Ütközésnél új javaslat.
4. A 2. körben mondd ki: az első napon minden mérték elérhető, mert a szinkron Agent-alapú; ha később a NAV kivonat lesz az elsődleges forrás, az A betűs mértékekhez akkor is kell az Agent-lekérés.
5. A 6. körben állítsd össze a válaszokból a spec vázlatát YAML-ként (szakaszok sorrendje: report, period, sources, filters, dimensions, measures, thresholds, exceptions, output, powerbi, delivery, validation), töltsd ki a lapvázlatot, és kérj megerősítést (`AskUserQuestion`: "Így jó" | "Módosítok: <kör száma>"). Módosításnál csak a megnevezett kört nyisd újra, majd mutasd az előnézetet még egyszer.

## Spec megírása

1. `Bash`: `uv run scripts/report_spec.py --new <slug> --title-hu "<title_hu>"` (váz: friss `report.id`, status `draft`, verzió 0.1.0). Ha a fájl már létezik (draft folytatása), hagyd ki.
2. `Bash`: `uv run scripts/report_spec.py --catalogue` (a mértékek táblája: id, megnevezés, forrás D vagy A, formátum). A kimenetet add át az ügynöknek.
3. `Agent(subagent_type="report-analyst", prompt=...)` ezzel a szöveggel:

```
Írd meg a reports/<slug>/spec.yaml fájlt az interjú válaszaiból. A váz már létezik, csak töltsd ki.
Interjúválaszok (kör, kulcs, érték, alapértelmezés-e):
<a 6. körben megerősített válaszok táblázata>
Mértékkatalógus (a --catalogue kimenete):
<kimenet>
Példa: reports/_examples/havi_arbev_kintlev/spec.yaml.
Kötelező: report.status draft, report.version 0.1.0, output.table_prefix tbl_<slug>, delivery.folder az interjúból.
Minden csempe, eltéréssor és küszöb létező measures[].id-re mutasson. Ne futtass semmit; a parancsokat add vissza a protokollod szerint.
```

4. `Bash`: `uv run scripts/report_spec.py --validate "reports/<slug>/spec.yaml"`. Kilépési kód 0: tovább. Kód 1: a kiírt sorok alakja `útvonal: szakasz.kulcs: üzenet`. Add vissza szó szerint az ügynöknek egy második `Agent(report-analyst)` hívásban ("Javítsd ezeket a hibákat, mást ne változtass"), majd validálj újra. Egy javítási kör; ha még mindig hibás, állj meg, és mutasd meg a hibasort a felhasználónak.
5. Mutasd meg az ügynök döntéseit (csempék, eltéréssorok, küszöbök indoklása) három vagy négy sorban.

## Build és próbafuttatás

`Agent(subagent_type="report-engineer", prompt=...)`:

```
Új riport: reports/<slug>/spec.yaml (validálva, verzió 0.1.0, status draft).
1. Hozd létre a reports/<slug>/build.py fájlt a scripts/build_template.py sablonból, és a reports/<slug>/tests/test_build.py tesztet.
2. Próbafuttatás: uv run reports/<slug>/build.py --period <ÉÉÉÉ-HH> --dry-run --json (az utolsó teljes hónap; a kimenet a reports/<slug>/_dryrun/ mappába kerül, leszállítás nincs).
3. Tesztek: uv run pytest reports/<slug>/tests -q
4. Legfeljebb három javítási kör. A spec.yaml fájlhoz ne nyúlj; ha a specen kell változtatni, írd le a kulcsot és az értéket.
Jelents a protokollod szerint, az _dryrun/ xlsx útvonalával.
```

Ha az ügynök `Specen kellene változtatni` sort ad vissza, vidd a report-analyst elé egy javítási körben, validálj, és indítsd újra a report-engineer ügynököt. Ha a próbafuttatás három kör után is 1-es kóddal zárul, állj meg (lásd "Ha elakad").

## 7. kör: ellenőrzés és aktiválás

1. `Agent(subagent_type="report-reviewer", prompt=...)`:

```
Ellenőrizd a reports/<slug>/_dryrun/<fájl>.xlsx fájlt a reports/<slug>/spec.yaml ellen, időszak <ÉÉÉÉ-HH>.
Próbafuttatás, nem leszállított fájl. reconcile csak akkor, ha a status szerint van staging adat.
Jelents a protokollod szerint: táblázat cellahivatkozással, ítélet, sűrűség.
```

2. Mutasd meg a reviewer táblázatát változtatás nélkül, alatta az ítéletet.
3. Ha van `critical` sor: egy javítási kör a report-engineer ügynökkel (a critical sorokat add át szó szerint), majd új reviewer futás. Ha marad critical, állj meg; a riport draft marad.
4. `AskUserQuestion`: "Aktiváljuk a riportot? (1.0.0 verzió; ezután a táblanevek véglegesek)" Opciók: "Igen" | "Még nem, maradjon draft".
5. Igen esetén:
   - `Edit` a `reports/<slug>/spec.yaml` fájlon: `status: draft` helyett `status: active`, `version: 0.1.0` helyett `version: 1.0.0`, és a `changelog` listába új sor: `- {version: 1.0.0, date: <ma, ÉÉÉÉ-HH-NN>, note: első aktív verzió}`. (A `--bump` csak minor vagy patch lépést tud, 0.1.0-ból nem ad 1.0.0-t.)
   - `Bash`: `uv run scripts/report_spec.py --validate "reports/<slug>/spec.yaml"` (0 kell).
6. Zárás, két sor: `Riport aktív: <title_hu> (<slug>), verzió 1.0.0, próbafuttatás: reports/<slug>/_dryrun/<fájl>.xlsx` és `Következő lépés: /report-run <slug>`.

Nem esetén a spec draft marad; írd ki, hogy a `/report-list` mutatja, és a `/report-new` folytatja.

## Ha elakad

| Helyzet | Teendő |
|---|---|
| Nincs szinkron a hónapra | 0. lépés: `pull --agent-only --prefix "<ELŐTAG>" --year <ÉÉÉÉ>` vagy `pull --period <ÉÉÉÉ-HH>`, utána `status` újra |
| Szinkron kilépési kód 2 | hiányzó kulcs a Windows Credential Managerben: README "Kulcsok" szakasz, `doctor.ps1` |
| Validálási hiba a javítási kör után is | mutasd a hibasort; a felhasználó dönt: új válasz az érintett körre, vagy `/report-edit` később |
| Próbafuttatás kilépési kód 1 | blokkoló ellenőrzés bukott (V01, V04, V05, V11, V15, V16); olvasd fel a `--json` `checks` listájából a `fail` sorok `detail_hu` szövegét; adathiba esetén `status` és szinkron, motorhiba esetén report-engineer |
| Próbafuttatás kilépési kód 2 | spec- vagy használati hiba: `--validate`, majd report-analyst |
| Reviewer critical a javítás után is | a riport draft marad; a critical sorokat írd ki, és javasold a `/report-edit <slug>` parancsot a spec oldali javításhoz |
| A hook tilt egy írást | szándékos: leszállítási mappába és zárolt specbe a skill nem ír; ne kerüld meg |

## Szabályok

- Ne írj közvetlenül a `delivery.folder` alá, és ne futtasd a `build.py`-t `--dry-run` nélkül ebben a skillben.
- Ne találj ki mértéket: csak a `--catalogue` id-k vagy `custom:<slug>` képlet.
- A slug és a `table_prefix` 1.0.0 után végleges; ezt az 5. körben mondd ki.
- Magyarul, tömören; a felhasználó válaszait ne fogalmazd át, csak rögzítsd.
