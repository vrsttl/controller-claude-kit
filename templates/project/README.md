# Riportok

Havi és negyedéves riportok szamlazz.hu számlaadatból, Claude Code és a controller-claude-kit segítségével. A mappa helye rögzített: `%USERPROFILE%\Riportok`. Ne helyezd át: a kit és az ütemezett feladat ide mutat.

| Mappa | Tartalom |
|---|---|
| `reports/<slug>/` | egy riport: `spec.yaml` (a leírás), `build.py`, `tests/`, `runlog.jsonl` |
| `reports/_examples/` | mintaspec, innen érdemes indulni |
| `data/` | `invoices.db` gyorsítótár és `drops/` a kézi exportoknak |
| `exports/` | leszállított riportok (ha a spec nem OneDrive-mappát ad meg) |
| `scripts/` | a kit szkriptjei; a `%USERPROFILE%\claude-kit\update.ps1` frissíti |

Munka Claude Code-ban, ebből a mappából: `claude`, majd `/prime`.

| Parancs | Mire |
|---|---|
| `/report-new` | új riport interjúval |
| `/report-run <slug>` | havi futtatás és leszállítás |
| `/report-edit <slug>` | meglévő riport módosítása |
| `/report-list` | riportok és utolsó futásuk |
| `uv run scripts/szamlazz_sync.py status` | adatállapot a parancssorból |

A részletes szabályok a `CLAUDE.md` fájlban, a kit leírása a `%USERPROFILE%\claude-kit\README.md` fájlban.
