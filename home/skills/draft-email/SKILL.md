---
name: draft-email
description: |
  E-mail piszkozatot készít a gmail-utility ügynökkel a gmail MCP-n keresztül: HTML, fiókválasztás téma szerint (céges vagy személyes), aláírás fiókonként, nyelv a címzett domainje szerint, a szál előzménye megmarad. Csak piszkozat; küldés kizárólag a szó szerinti "küldd el" utasításra. Akkor indítsd, ha a felhasználó levelet írna vagy levelekkel dolgozna, például "írj egy e-mailt a könyvelőnek", "válaszolj erre a levélre", "készítsd el a havi riport kísérőlevelét", "gyűjtsd be a számlaértesítő PDF-eket", "/draft-email".
---

# /draft-email

Ez a skill csak továbbít: a munkát a `gmail-utility` ügynök végzi (`Agent(subagent_type="gmail-utility", prompt=...)`). A skill csak összegyűjti, ami a prompthoz kell, és továbbadja.

## Alapszabályok

| Szabály | Részlet |
|---|---|
| Csak piszkozat | az ügynök a `draft_email` eszközt hívja; `send_email` csak akkor, ha a felhasználó az adott levélre szó szerint azt írta: "küldd el". A "mehet", "oké", "jó lesz" nem küldés |
| HTML | `mimeType: "text/html"`, `<b>`, `<br>`, `<ul><li>`; markdown nincs |
| Nincs gondolatjel | vessző, pont, kettőspont, zárójel; sem hosszú, sem rövid gondolatjel |
| Fiók téma szerint | lásd lent; bizonytalan esetben `AskUserQuestion` |
| Aláírás | `~/.claude/email-signatures.json`, kulcs a fiók e-mail címe; ha nincs, csak név, és ezt az ügynök jelzi |
| Nyelv | a címzett domainje: `.hu` magyar, minden más angol; a felhasználó felülírja ("írd németül") |
| Szál | válasznál az előzmény megmarad, az ügynök nem vágja le |
| Melléklet | az MCP nem tud fájlt csatolni; az útvonal a válaszban szerepel, a felhasználó csatolja kézzel, vagy OneDrive-linket illeszt be |

## Fiókválasztás

| Téma | Fiók |
|---|---|
| szamlazz.hu, NAV, számlaértesítő, ügyfél, kolléga, vezető, könyvelő, havi riport | céges (Workspace) |
| magánügy, saját vásárlás, hírlevél, család | személyes |
| a felhasználó megnevezi | az, amit mondott |
| nem dönthető el | `AskUserQuestion`: "Melyik fiókból?" Opciók: "céges" | "személyes" |

A fiókok azonosítását az ügynök végzi (`list_accounts`); a skill csak a "céges" vagy "személyes" szót adja át.

## Menet

1. Gyűjtsd össze: fiók (téma szerint), címzett, tárgy (vagy "válasz erre: <tárgy>"), tartalom pontokban, nyelv, küldés engedélyezve-e (csak a szó szerinti "küldd el" esetén).
2. Ha a címzett vagy a tartalom hiányzik, egy `AskUserQuestion` hívás; ne találj ki címet.
3. `Agent(subagent_type="gmail-utility", prompt=...)` az általános prompttal (lent).
4. Add vissza az ügynök jelentését változtatás nélkül: fiók, tárgy, címzett, piszkozat-azonosító, csatolandó fájl, "Nem küldtem el semmit".
5. Módosítás kérésére új `Agent` hívás ugyanazzal a prompttal és a kért változtatással; az ügynök a meglévő piszkozatot írja át, nem csinál újat.

## Általános prompt

```
Készíts PISZKOZATOT (ne küldd el).
Fiók: <céges | személyes>
Címzett: <e-mail cím>  Másolat: <ha van>
Tárgy: <tárgy>  (válasznál: az eredeti szál tárgya, válasz a <dátum> levélre)
Nyelv: <hu | en | más, ha a felhasználó kérte>
Tartalom:
- <pont 1>
- <pont 2>
Követelmények: HTML (mimeType text/html), nincs gondolatjel, nincs markdown; a fiók aláírása a ~/.claude/email-signatures.json fájlból; válasznál a szál előzménye megmarad.
Küldés: <"nem engedélyezett" | 'a felhasználó szó szerint ezt írta: "küldd el"'>
Jelents a protokollod szerint.
```

## Recept: havi riport e-mail

Mikor: a `/report-run` sikeres vége ("Írjak kísérőlevelet?" igen), vagy a felhasználó kéri ("készítsd el a havi riport levelét"). Bemenet: a `build.py --json` objektuma (`slug`, `period`, `version`, `outcome_hu`, `totals.rev_net`, `row_counts`, `checks`), az előnézeti sorok (kintlévőség, eltérés az előző futtatáshoz) és a `delivered_path`. Ha nincs friss futás, `Read`: `reports/<slug>/runlog.jsonl` utolsó sora, és kérdezd meg a címzettet.

```
Készíts PISZKOZATOT (ne küldd el): a havi riport kísérőlevele.
Fiók: céges
Címzett: <e-mail cím>  Másolat: <ha van>
Tárgy: Havi riport <ÉÉÉÉ-HH>: <title_hu>
Nyelv: hu
Riport: <slug>, verzió <version>, időszak <ÉÉÉÉ-HH>, eredmény <outcome_hu>
Adatok a build.py kimenetéből (csak ezeket használd, mást ne találj ki):
- nettó árbevétel: <totals.rev_net> Ft
- kintlévőség a fordulónapon: <az előnézeti sor értéke>
- eltérés az előző futtatáshoz: <az előnézeti sor, vagy "nincs előző futtatás">
- sorok: <row_counts.invoice> számla, <row_counts.customer> vevő
- figyelmeztetések: <a warn státuszú checks id és detail_hu, vagy "nincs">
Törzs: egy bevezető mondat (időszak, riport neve), majd 3 és 5 közötti <li> pont a fenti adatokból (érték, változás, küszöbsértés vagy kivétel, ha van), zárásként "A riportot csatolom." és alatta a fájl útvonala: <delivered_path>. Ha OneDrive-link is van: <link>.
Számok magyar formában (1 234 e Ft; 12,5 %). HTML, nincs gondolatjel, a céges aláírás.
Az MCP nem csatol fájlt: a jelentésben add meg a csatolandó útvonalat.
```

A válaszban emeld ki a felhasználónak: a fájlt kézzel kell csatolnia, vagy OneDrive-linket kell beillesztenie a piszkozatba.

## Recept: számlaértesítő PDF-ek begyűjtése

Mikor: "gyűjtsd be a számlaértesítőket", "töltsd le a szamlazz.hu PDF-eket", vagy hónap eleji archiválás. Ez PDF-archívum; a riportok forrása a szinkron, nem ezek a fájlok.

```
Számlaértesítő PDF-ek begyűjtése (letöltés, nem levélírás).
Fiók: céges
Keresés: from:@szamlazz.hu has:attachment newer_than:35d   (adott hónapra: after:<ÉÉÉÉ/HH/01> before:<a következő hónap első napja>)
Minden találatnál: read_email, majd a PDF mellékletekre download_attachment ide: ~/Riportok/data/drops/pdf/<ÉÉÉÉ-HH>/ (a hónap a levél dátumából; fájlnév az eredeti melléklet neve, ütközésnél a levél dátuma elé írva: 2026-08-14_).
Ne törölj, ne címkézz, ne jelölj olvasottnak semmit; csak akkor, ha a felhasználó kifejezetten kérte: <nincs ilyen kérés | a kérés szövege>.
Jelents: hány levél, hány PDF, hová, mit hagytál ki és miért.
```

Az útvonalat a `project_dir` szerint add meg, ha a `~/.claude/kit-state.json` fájlban más a projektmappa (`Read`).

## Ha elakad

| Helyzet | Teendő |
|---|---|
| Az ügynök csak egy fiókot lát | a másik nincs bejelentkezve: `powershell -ExecutionPolicy Bypass -File "<kit_path>/mcp/gmail-setup.ps1"` (a `kit_path` a kit-state fájlból), utána újra |
| A gmail MCP nem elérhető | `claude mcp list`; ha hiányzik, `powershell -ExecutionPolicy Bypass -File "<kit_path>/mcp/register-mcps.ps1" -Level 1`; MCP nélkül ne írj levelet, és ne tégy úgy, mintha megírtad volna |
| Az aláírás hiányzik | a felhasználó hozza létre a `~/.claude/email-signatures.json` fájlt (kulcs: e-mail cím, érték: HTML részlet); addig csak név |
| A keresés üres | az ügynök kiírja a pontos lekérdezést; tágabb: `from:@szamlazz.hu` dátum nélkül |
| Lejárt OAuth token (7 nap) | a Google Cloud OAuth képernyő "Testing" módban van: README, "In production" vagy "Internal"; utána `gmail-setup.ps1` újra |
| A felhasználó "küldd el"-t ír | új `Agent` hívás, a promptban szó szerint: a felhasználó ezt írta: "küldd el"; az ügynök küld, és jelenti |

## Szabályok

- Nem küld, nem töröl, nem címkéz, nem hoz létre szűrőt kérés nélkül.
- Nem tesz a levélbe olyan számot, amely nincs a build.py kimenetében vagy a szálban.
- Fiókváltás csak a feladat elején; az alapértelmezett fiókot nem állítja át.
