# Riportok: állapot betöltése

A `~/Riportok` mappában dolgozol. Mielőtt bármihez nyúlnál, töltsd be a kontextust az alábbi hét lépéssel. Csak olvasó parancsokat futtass; ami hibát ad, azt jegyezd fel, ne javítsd itt.

## 1. Eszközök

- Python mindig `uv run scripts/<szkript>.py ...` formában, a `~/Riportok` mappából.
- MCP: `excel` (kész `.xlsx` beleolvasása, ha egy cellára kíváncsi a felhasználó), `gmail` (piszkozat, keresés, melléklet; a gmail-utility ügynök használja). 2. szinttől `microsoft-learn`, 3. szinttől `powerbi-modeling` és `ms365`.
- Skillek: `/report-new`, `/report-run`, `/report-edit`, `/report-list`, `/draft-email`, `/level-up`.
- Ügynökök: report-analyst, report-engineer, report-reviewer, gmail-utility; 3. szinten web-researcher.

## 2. Adatállapot

```
uv run scripts/szamlazz_sync.py status
```

Jegyezd fel: az utolsó Agent (és ha van, NAV) szinkron ideje, a számlák előtag és év szerint a sorszámtartománnyal, a nem aktív láncok száma, a számozási hiányok. Ha az első blokk `(még nem volt szinkron)`, az összefoglalóba írd be, hogy első szinkron kell (`pull --agent-only --prefix <ELŐTAG> --year <ÉÉÉÉ>`).

## 3. Mappaszerkezet

| Mappa | Tartalom |
|---|---|
| `reports/<slug>/` | `spec.yaml`, `build.py`, `tests/`, `runlog.jsonl`, `.staging/`, `_dryrun/` |
| `reports/_examples/` | mintaspec |
| `data/invoices.db`, `data/drops/` | gyorsítótár, kézi exportok, PDF-archívum |
| `exports/` | leszállított riportok, ha a spec nem ad más `delivery.folder` mappát |
| `scripts/` | a kit szkriptjei, az `update.ps1` felülírja |

Ellenőrizd, léteznek-e (`reports/`, `data/invoices.db`, `exports/`); a hiányzót jelezd.

## 4. Riportok

```
uv run scripts/run_reports.py --list
```

Oszlopok: slug, cím, verzió, státusz, időszak, utolsó futás, eredmény, leszállított fájl. Ha a parancs nem fut, olvasd be a `reports/*/spec.yaml` fájlok `report` szakaszát (`slug`, `title_hu`, `version`, `status`) és a `runlog.jsonl` utolsó sorát.

## 5. Verziók és szint

```
uv --version
python --version
```

Olvasd be a `~/.claude/kit-state.json` fájlt: `level`, `kit_version`, `kit_path`, `project_dir`, `flags.gmail`, `flags.nav`, `flags.schedule`. A szint dönti el, mely szabályfájlok és MCP-k aktívak.

## 6. Kulcstények

- HUF-ban nincs tizedes: sehol nincs osztás 100-zal, nincs kerekítés; ezer forintos profil `#,##0," e Ft"`.
- ÁFA-kulcsok: `27`, `5`, `0`, `AAM`, `TAM`, `EU`, `EUK`.
- Storno alapból a saját kiállítási hónapjában (`period.storno_attribution: issue_month`); storno és helyesbítő előjeles, és lánchoz tartozik.
- Fizetettség sorrendje: storno, díjbekérő kizárva, készpénz és kártya (ha `cash_card_autopaid`), 1 Ft tűrés, részleges, fizetetlen; lejárt = nyitott és határidőn túl.
- Leszállítás: a `.staging/` mappából, csak a `/report-run` útján; a `delivery.folder` és a `powerbi.folder` védett; zárolt célfájl `.pending.xlsx`, bukott blokkoló ellenőrzés `_rejected/`.
- Leszállított `.xlsx` sosem szerkeszthető kézzel: spec módosítása, újrafuttatás.
- Blokkoló ellenőrzések: V01, V04, V05, V11, V15, V16. Táblanevek (`tbl_<slug>_<entity>`) 1.0.0 után véglegesek.
- Számla Agent: számlánkénti lekérés, hézagmentes sorszámozás, 3 ismeretlen szám után megáll; a lekérdezési díj megerősítése az első teljes felsorolás előtt kötelező.

## 7. Legutóbbi munka

- A `status` első blokkja (utolsó szinkron forrásonként) és minden `reports/<slug>/runlog.jsonl` utolsó sora: időszak, eredmény, bukott ellenőrzések.
- Ha a `~/Riportok` git-repó (van `.git` mappa): `git -C ~/Riportok log --oneline -5 -- reports/`. Ha nincs, hagyd ki, és ne inicializálj repót.

## Zárás

Foglald össze az állapotot legfeljebb 8 sorban: szint, adatállapot (utolsó szinkron, számlaszám), riportok száma és az utolsó futások eredménye, hiányzó titok vagy mappa, verziók, legutóbbi változás. Utána várj a felhasználó feladatára; ne kezdj semmit magadtól.
