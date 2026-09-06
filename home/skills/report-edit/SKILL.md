---
name: report-edit
description: |
  Meglévő riport specjét módosítja biztonságosan: megmutatja a spec összefoglalóját, csak az érintett interjúköröket nyitja újra, a report-analyst átírja a spec.yaml fájlt, a diff és a validálás eldönti, engedélyezett-e a változás, verzióemelés changelog-bejegyzéssel, a report-engineer újragenerálja a build.py-t és a teszteket, próbafuttatás, majd a report-reviewer ellenőrzi. Akkor indítsd, ha a felhasználó egy riporton változtatna, például "módosítsd a kintlévőség riportot", "/report-edit havi_arbev_kintlev", "tegyél bele egy új mértéket", "állítsd át a küszöböt 3 millióra", "ezentúl teljesítés alapján számoljon".
---

# /report-edit

Használat: `/report-edit <slug>`. Minden parancs a `~/Riportok` mappából fut. A spec az igazságforrás: a build.py-t nem kézzel foltozzuk, hanem a spec után újrageneráljuk.

## 1. A spec bemutatása

1. Slug nélkül: `Bash`: `uv run scripts/run_reports.py --list`, majd `AskUserQuestion`: "Melyik riportot módosítsam?"
2. `Read`: `reports/<slug>/spec.yaml`. Ha `report.status` draft, állj meg: a `/report-new` folytatja. Ha `report.locked: true`, állj meg: a hook tiltja a szerkesztést; a felhasználó oldja fel a `locked` kulcsot kézzel, ha tényleg módosítani akar.
3. Összefoglaló táblázat: cím, verzió, státusz, időszak (grain, basis, offset), források, szűrők egy sorban, mértékek id-listája, küszöbök, kivételek id-listája, lapok, leszállítási mappa, Power BI igen vagy nem.
4. Írd ki a legutóbbi changelog-bejegyzést.

## 2. Mi változik

`AskUserQuestion`: "Melyik részt módosítjuk?" Opciók:

| Opció | Spec-szakasz | Újranyitott körök |
|---|---|---|
| időszak és források | period, sources | 2, 4, 6, 7 |
| szűrők | filters, dimensions | 3, 6, 7 |
| mértékek, küszöbök, kivételek | measures, thresholds, exceptions | 4, 5, 6, 7 |
| kimenet, leszállítás, Power BI | output, powerbi, delivery | 5, 6 és 7 csak akkor, ha lap vagy tábla változott |
| cím, gazda | report.title_hu, report.owner | 6 |
| egyéb | a felhasználó mondja meg | a fenti táblából a legközelebbi sor |

A körök szövege: `../report-new/references/interview.md` (`Read`). Minden újranyitott körben a jelenlegi spec-érték az alapértelmezett opció. A 6. kör itt a módosított szakaszok YAML-részletét mutatja, és a vezetői lap vázlatát (`../report-new/references/executive-mockup.md`) csak akkor, ha a csempék vagy az eltéréssorok változtak.

## 3. Mentés a módosítás előtt

`Bash`: `cp "reports/<slug>/spec.yaml" "reports/<slug>/spec.prev.yaml"`

## 4. Az új spec

1. `Bash`: `uv run scripts/report_spec.py --catalogue`, ha a mértékek köre változik.
2. `Agent(subagent_type="report-analyst", prompt=...)`:

```
Módosítsd a reports/<slug>/spec.yaml fájlt. Csak ezeket a szakaszokat írd át: <szakaszok>. A többi maradjon változatlan; a report.id és az output.table_prefix nem változhat.
Új válaszok (kör, kulcs, régi érték, új érték):
<táblázat>
Mértékkatalógus: <a --catalogue kimenete, ha kell>
A verziót és a changelogot ne írd: a --bump parancsot a főszál futtatja. Ha egy törlendő mértékre csempe, eltéréssor vagy küszöb hivatkozik, ne töröld, hanem sorold fel a hivatkozásokat.
```

3. `Bash`: `uv run scripts/report_spec.py --diff "reports/<slug>/spec.prev.yaml" "reports/<slug>/spec.yaml"`

Kilépési kód 1 esetén állj meg, és írd ki a magyar indokot változtatás nélkül. A tiltott esetek és a kiút:

| Elutasítás | Kiút |
|---|---|
| a riport azonosítója nem változtatható | a `report.id` marad; új riport kell, ha új azonosító a cél |
| 1.0.0 után a táblák előtagja nem nevezhető át | az előtag marad; új tábla vagy új riport (`/report-new`), a régi fájlok érintetlenek |
| a(z) X mérték hiányzik, de csempe, eltéréssor vagy küszöb hivatkozik rá | ne töröld a mértéket; vedd ki a csempék és sorok közül (a vezetői lap nem mutatja, az adatlapon marad) |
| a(z) tbl_<slug>_<lap> tábla 1.0.0 után nem távolítható el | a lap marad; ha zavar, a Power BI oldalán rejtsd el |

Kiútnál: `Bash`: `cp "reports/<slug>/spec.prev.yaml" "reports/<slug>/spec.yaml"` (visszaállítás), majd `AskUserQuestion` a választott kiúttal, és a 4. lépés újra.

4. `Bash`: `uv run scripts/report_spec.py --validate "reports/<slug>/spec.yaml"`. Kód 1: a hibasorokat add vissza az ügynöknek egy javítási körben (`Agent(report-analyst)`: "Javítsd ezeket, mást ne változtass"), majd `--diff` és `--validate` újra. Két sikertelen kör után visszaállítás és megállás.

## 5. Verzióemelés

1. Döntsd el a lépés méretét:

| Változás | Lépés |
|---|---|
| új vagy törölt mérték, lap, tábla, dimenzió, forrás, időszaktípus, alap (kelt vagy teljesítés) | minor |
| küszöb, kivételparaméter, címke, cím, gazda, top_n, leszállítási mappa, felülírási szabály, Power BI ki vagy be | patch |

2. `AskUserQuestion`: "Verzió <régi> -> <új> (<minor|patch>). Changelog-szöveg: '<javaslat egy mondatban>'. Jó így?" Opciók: "Igen" | "Más szöveg: ...".
3. `Bash`: `uv run scripts/report_spec.py --bump "reports/<slug>/spec.yaml" <minor|patch> --note "<megerősített szöveg>"`

## 6. Build, próbafuttatás, ellenőrzés

1. `Agent(subagent_type="report-engineer", prompt=...)`:

```
Módosított riport: reports/<slug>/spec.yaml (verzió <új>, validálva, a diff engedélyezte).
1. Generáld újra a reports/<slug>/build.py fájlt a scripts/build_template.py sablonból, ne foltozd.
2. Igazítsd a reports/<slug>/tests/test_build.py tesztet az új mértékekhez és lapokhoz.
3. Próbafuttatás: uv run reports/<slug>/build.py --period <ÉÉÉÉ-HH> --dry-run --json (utolsó teljes hónap).
4. Tesztek: uv run pytest reports/<slug>/tests -q
A spec.yaml fájlhoz ne nyúlj. Jelents a protokollod szerint, az _dryrun/ xlsx útvonalával.
```

2. Csak akkor, ha a 7. kör a mátrix szerint nyitva van (minden eset, kivéve: cím és gazda; kimenet, ha nem változott lap vagy tábla): `Agent(subagent_type="report-reviewer", prompt=...)`:

```
Ellenőrizd a reports/<slug>/_dryrun/<fájl>.xlsx fájlt a reports/<slug>/spec.yaml (verzió <új>) ellen, időszak <ÉÉÉÉ-HH>.
Kiemelten: <a módosított szakaszok>. Jelents a protokollod szerint.
```

3. Mutasd a reviewer táblázatát. `critical` esetén egy javítási kör a report-engineer ügynökkel, majd új ellenőrzés. Ha marad critical: visszaállítás (`cp` a `spec.prev.yaml` fájlból), és a felhasználó dönt.

## 7. Lezárás

1. `Bash`: `rm "reports/<slug>/spec.prev.yaml"`
2. Záró sorok: `Spec: reports/<slug>/spec.yaml, verzió <régi> -> <új>, changelog: <szöveg>` és `Következő lépés: /report-run <slug>` (a leszállított fájlt csak a `/report-run` frissíti).

## Ha elakad

| Helyzet | Teendő |
|---|---|
| A diff elutasítja a változást | a 4. lépés táblázata; visszaállítás a `spec.prev.yaml` fájlból |
| Validálási hiba két kör után | visszaállítás, a hibasorokat mutasd meg, a felhasználó dönt |
| A `--bump` "a --note szöveg kötelező" hibát ad | a changelog-szöveg hiányzott: kérd meg újra, és futtasd `--note` értékkel |
| Próbafuttatás kilépési kód 1 vagy 2 | a report-engineer jelentése szerint: adathiba -> szinkron, spec-hiba -> report-analyst; három kör után visszaállítás |
| A hook tilt egy írást | zárolt spec vagy leszállítási mappa: szándékos, ne kerüld meg |
| A felhasználó a leszállított xlsx-et szerkesztené | nem: a spec módosul, és a `/report-run` új fájlt készít |

## Szabályok

- A `report.id` és a `table_prefix` sosem változik ebben a skillben.
- A verziót és a changelogot csak a `--bump` írja; kézzel nem.
- Ne futtasd a `build.py`-t `--dry-run` nélkül; a leszállítás a `/report-run` dolga.
