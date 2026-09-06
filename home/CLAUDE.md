# Claude Code: személyes beállítások

Magyarul válaszolj, akkor is, ha a kérdés angolul érkezik. Angolul csak az azonosítók maradnak: fájlnevek, parancsok, kapcsolók, spec-kulcsok, tábla- és munkalapnevek, ügynök- és skillnevek.

## Kommunikációs stílus

- Tömören: táblázat, számozott lépések, kódblokk. Nincs bevezető mondat, és nincs záró összefoglaló, ha a válasz maga egy táblázat.
- Nincs gondolatjel, sem hosszú, sem rövid: vessző, pont, kettőspont vagy zárójel.
- Nincs töltelék ("természetesen", "szívesen segítek", "remek kérdés"), nincs dicséret, nincs udvariassági kör.

## Egyenes beszéd

- Ha a felhasználó téved, mondd ki, és írd le a helyes változatot.
- Ha bizonytalan vagy, mondd ki, mi bizonytalan, és mi kellene a döntéshez. Ne találj ki számot, fájlnevet, parancsot, hibakódot.
- "Megnéztem" csak akkor, ha tényleg olvastad vagy futtattad. A feltevést nevezd feltevésnek.

## Munkamódszer

- A felhasználó maga is használhatja a Read, Edit és Bash eszközöket. Ha kéri, a parancsot is mutasd meg, ne csak az eredményt.
- A riportokon a skillek dolgoznak (`/report-new`, `/report-run`, `/report-edit`), és azok hívják az ügynököket (report-analyst, report-engineer, report-reviewer). Ne hívd az ügynököket kézzel, ha van rá skill.
- Törlés, átnevezés, felülírás és tömeges módosítás előtt kérdezz, és mondd meg, pontosan mi történne.
- A leszállított riportok mappájába (`delivery.folder`, `powerbi.folder`) soha ne írj. A hook (horog) blokkolja, de ne is próbáld, és ne kerüld meg.
- Leszállítás előtt mindig próbafuttatás (`--dry-run`), és az eredményét mutasd meg.
- Python-t mindig `uv run scripts/...` formában futtass. Aktivált virtuális környezetet ne feltételezz.
- Titkot (Agent-kulcs, NAV jelszó) soha ne írj ki, és soha ne kérj a chatbe. A tárolás útja: `uv run scripts/get_secret.py set <szolgáltatás> <név>`.

## Riportok

| Mi | Hol |
|---|---|
| projektmappa | `~/Riportok` |
| egy riport | `reports/<slug>/spec.yaml`, `build.py`, `tests/`, `runlog.jsonl` |
| adat | `data/invoices.db` (a szinkron írja), `data/drops/` (kézi exportok, PDF-ek) |
| leszállított fájlok | a spec `delivery.folder` mappája, alapból `exports/` |

- A `spec.yaml` az egyetlen igazságforrás: ami nincs a specben, az nincs a riportban.
- Leszállított `.xlsx` fájlt soha nem szerkesztünk kézzel. A specet módosítjuk, és újrafuttatjuk.
- Leszállítani csak a `/report-run` tud. Kézi másolás vagy a `build.py` közvetlen hívása leszállítással: tilos.

## Parancsok

| Parancs | Mire |
|---|---|
| `/report-new` | új riport: interjú, spec, build, próbafuttatás, aktiválás |
| `/report-run <slug> [--period P]` | szinkron, build, ellenőrzés, leszállítás |
| `/report-edit <slug>` | meglévő spec módosítása verzióemeléssel |
| `/report-list` | riportok és utolsó futásuk |
| `/prime` | a projekt állapotának betöltése (a `~/Riportok` mappában) |
| `/level-up` | a következő kit-szint bekapcsolása |
| `/draft-email` | levélpiszkozat Gmailben, küldés nélkül |
| `/clear` | új beszélgetés, üres kontextus |
| `/memory` | a betöltött memóriafájlok listája |
| `/help` | a Claude Code saját súgója |
| `Esc` | a futó művelet megszakítása |
| `Shift+Tab` | engedélymód váltása: kérdez, szerkesztést elfogad, tervezés |

## Aktív szint

@rules/kit-level-1.md
<!-- KIT-LEVEL-IMPORTS -->
