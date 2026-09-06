# Riportok

Ez a mappa (`~/Riportok`) a havi riportok műhelye: itt van az adat, a riportok leírása és a kimenet. Kódot nem itt fejlesztünk; a `scripts/` mappát a kit frissítése (`update.ps1`) felülírja.

## Mappák

| Mappa vagy fájl | Tartalom | Ki írja |
|---|---|---|
| `reports/<slug>/spec.yaml` | a riport leírása, az egyetlen igazságforrás | `/report-new`, `/report-edit` |
| `reports/<slug>/build.py`, `tests/` | a sablonból generált build és a tesztje | report-engineer ügynök |
| `reports/<slug>/runlog.jsonl` | minden futás egy sora | `build.py` |
| `reports/<slug>/.staging/`, `_dryrun/` | építés alatti és próbafuttatott fájlok | `build.py` |
| `reports/_examples/` | mintaspec (`havi_arbev_kintlev`) | a kit |
| `data/invoices.db` | SQLite gyorsítótár a szamlazz.hu számlákról | `szamlazz_sync.py` |
| `data/drops/` | kézi exportok (Főkönyvi CSV, Áfalista XLSX), `pdf/<ÉÉÉÉ-HH>/` | a felhasználó, gmail-utility |
| `exports/` | leszállított riportok (vagy a spec `delivery.folder` mappája) | csak `/report-run` |

## Így születik egy riport

1. `/report-new`: hét interjúkör (hatókör; időszak és források; populáció és szűrők; mértékek, küszöbök, kivételek; kimenet, leszállítás, Power BI; előnézet és megerősítés; próbafuttatás és ellenőrzés).
2. A report-analyst megírja a `spec.yaml`-t (`status: draft`), a főszál validálja: `uv run scripts/report_spec.py --validate reports/<slug>/spec.yaml`.
3. A report-engineer a `scripts/build_template.py` sablonból létrehozza a `build.py`-t és a `tests/` mappát, és próbát futtat: `uv run reports/<slug>/build.py --period <P> --dry-run --json`.
4. A report-reviewer visszaolvassa a `_dryrun/` fájlt, és cellára pontosan összeveti a speckel.
5. Jóváhagyás után a spec `active` és `1.0.0`; ettől kezdve a `/report-run <slug>` szinkronizál, épít, ellenőriz és leszállít.

Módosítás: `/report-edit <slug>`, utána a 3. és a 4. lépés ismétlődik, a verzió emelkedik.

## Engedélyezett parancsok

| Parancs | Mire |
|---|---|
| `/report-new`, `/report-run <slug> [--period P]`, `/report-edit <slug>`, `/report-list` | a riportok teljes életútja |
| `/prime` | állapot betöltése munkamenet elején és `/clear` után |
| `uv run scripts/szamlazz_sync.py status`, `pull --agent-only --prefix <ELŐTAG> --year <ÉÉÉÉ>` | adatállapot, szinkron egy előtagra |
| `uv run scripts/report_spec.py --validate <spec>`, `--catalogue`, `--diff`, `--bump`; `uv run scripts/run_reports.py --list` | spec-eszközök, riporttábla |

## Soha

- Leszállított `.xlsx` fájlt nem szerkesztünk és nem másolunk kézzel; a specet módosítjuk, és újrafuttatjuk.
- Az `exports/`, a `delivery.folder` és a `powerbi.folder` mappába csak a `/report-run` ír; a `build.py` kézből csak `--dry-run` kapcsolóval fut.
- A `data/invoices.db` fájlt nem szerkesztjük és nem töröljük; csak a szinkron és az importok írják.
- A `reports/<slug>/` mappát nem nevezzük át; a `report.id` és a táblanevek 1.0.0 után nem változnak.
- Titok (Agent-kulcs, NAV jelszó) nem kerül a chatbe vagy fájlba; a `uv run scripts/get_secret.py set ...` tárolja.

Első lépés minden munkamenetben: `/prime`.
