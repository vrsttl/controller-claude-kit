---
name: level-up
description: |
  Szintlépés a kitben: megmutatja a jelenlegi szintet és azt, amit a következő szint (2 Kontroll, 3 Automatizálás) megnyit, megerősítés után beírja az új szint szabályfájlját a ~/.claude/CLAUDE.md fájlba, frissíti a kit-state.json állományt, regisztrálja az új MCP-ket, és három kipróbálható dolgot ad. Akkor indítsd, ha a felhasználó továbblépne, például "szintlépés", "/level-up", "lépjünk a következő szintre", "mit nyit meg a 2. szint", "kész vagyok a 3. szintre".
---

# /level-up

Három szint van; a 3. a legmagasabb. A skill nem futtat riportot, csak a beállításokat módosítja.

## Szintek

| Szint | Név | Amit megtanulsz | Amit a kit bekapcsol |
|---|---|---|---|
| 1 | Napi használat | `/report-run`, `/report-list`, `/report-new`, engedélykérdések, Esc, `/clear` | gmail és excel MCP; prime_nudge, session_tips, protect_delivery hook; riport-skillek és ügynökök |
| 2 | Kontroll | tervezési mód, `/prime`, a projekt CLAUDE.md, a spec.yaml olvasása és szerkesztése, `/report-edit`, a szinkronnapló olvasása, NAV technikai felhasználó | microsoft-learn MCP; memory_backup hook; `rules/reports.md`, `rules/szamlazz-data.md` |
| 3 | Automatizálás | ügynökök, hookok szerkesztése, Power BI modell MCP, `claude -p` | powerbi-modeling és ms365 MCP; `web-researcher` ügynök; parancssori receptek |

## 1. Jelenlegi szint

1. `Read`: `~/.claude/kit-state.json`. Kulcsok: `level` (1..3), `kit_path`, `project_dir`, `updated_at`, `flags.gmail`, `flags.nav`.
2. Ha a fájl hiányzik vagy nem olvasható: állj meg; a felhasználó futtassa a `doctor.ps1` szkriptet (`powershell -ExecutionPolicy Bypass -File "<kit_path>/doctor.ps1"`; a kit mappája alapból `~/claude-kit`).
3. Ha a `level` 3: írd ki, hogy ez a legmagasabb szint, nincs több lépés, és a `rules/kit-level-3.md` fájl leírja a lehetőségeket. Vége.

## 2. Mit nyit meg a következő szint

Mutasd a következő szint sorát a fenti táblából két oszlopban (megtanulod, bekapcsol), majd a "próbáld ki" listát.

2. szint, Kontroll:

1. `/prime` a `~/Riportok` mappában: eszközök, adatállapot, riportok egy képernyőn.
2. `/report-edit <slug>`: egy küszöb átállítása (patch verzió); utána nézd meg a changelogot a spec végén.
3. `uv run scripts/szamlazz_sync.py status`, majd Shift+Tab a tervezési módhoz, és kérdezd meg, mit jelent a "Nem aktív láncok" blokk.

3. szint, Automatizálás:

1. `claude -p "Melyek az aktív riportok, és mikor futottak utoljára?"` a `~/Riportok` mappából.
2. Power BI Desktop: Adatok lekérése, Excel-munkafüzet, a leszállított fájl; a Navigátorban a `tbl_<slug>_<entity>` táblát válaszd, ne a munkalapot.
3. Kérdezz a `web-researcher` ügynöktől: "Nézz utána a NAV dokumentációban, változott-e a queryInvoiceDigest."

## 3. Megerősítés

`AskUserQuestion`: "Lépjünk a <N>. szintre (<név>)?" Opciók: "Igen" | "Még nem". Nem esetén vége, változtatás nélkül.

## 4. CLAUDE.md

`Edit` a `~/.claude/CLAUDE.md` fájlon: a `<!-- KIT-LEVEL-IMPORTS -->` sor elé új sorként `@rules/kit-level-<N>.md`. Előtte `Read`: ha a sor már szerepel, ne írd be még egyszer. Ha a jelölő hiányzik, állj meg, és írd ki, hogy a fájl `Aktív szint` szakaszába kell a jelölő (a kit `home/CLAUDE.md` mintája szerint).

Eredmény a 2. szint után:

```
@rules/kit-level-1.md
@rules/kit-level-2.md

<!-- KIT-LEVEL-IMPORTS -->
```

## 5. kit-state.json

`Edit` a `~/.claude/kit-state.json` fájlon: `"level": <régi>` helyett `"level": <N>`, és az `"updated_at"` értéke a mostani időpont `ÉÉÉÉ-HH-NNTÓÓ:PP:MM` alakban. Más kulcshoz ne nyúlj (a `tips_seen` értéket a hook kezeli).

## 6. MCP-k

`Bash`: `powershell -ExecutionPolicy Bypass -File "<kit_path>/mcp/register-mcps.ps1" -Level <N>` (a `kit_path` a kit-state fájlból, előre dőlő perjelekkel). Mutasd meg a kimenetét változtatás nélkül. A szkript idempotens: a már meglévő szervereket kihagyja.

| Szint | Új MCP |
|---|---|
| 2 | microsoft-learn (http) |
| 3 | powerbi-modeling, ms365 (npx, `cmd /c`) |

## 7. Csak a 2. szintnél: update.ps1

A `memory_backup.py` hook a 2. szinttől él: minden `Write` és `Edit` előtt másolatot tesz a memóriafájlokról, húszat őriz. A hook bejegyzését a `settings.json` fájlba a telepítő (`install.ps1`) írja be a szint alapján, ezért a szintlépés után a felhasználó futtassa:

`powershell -ExecutionPolicy Bypass -File "<kit_path>/update.ps1"`

Ez `git pull` és `install.ps1 -Update`: a hookok bejegyzése a szinthez igazodik, a `settings.json` többi tartalma megmarad (`settings.json.bak` készül). Enélkül a hook fájl ott van, de nem fut.

## 8. Újraindítás

Írd ki: az MCP-k és a hookok a Claude Code újraindítása után élnek. A felhasználó zárja be az összes Claude Code ablakot, indítsa újra, majd a `~/Riportok` mappában `/prime`. A következő indításkor a session_tips hook már az új szint tippjeit adja.

Záró sor: `Szint: <régi> -> <N> (<név>). Új szabályfájl: rules/kit-level-<N>.md. Újraindítás után: /prime.`

## Ha elakad

| Helyzet | Teendő |
|---|---|
| kit-state.json hiányzik | `doctor.ps1`, majd újra `/level-up` |
| a jelölő hiányzik a CLAUDE.md fájlból | a felhasználó illessze be az `Aktív szint` szakasz végére: `<!-- KIT-LEVEL-IMPORTS -->`, majd újra |
| register-mcps.ps1 hibát ad | a kimenet szerint: hiányzó Node (3. szint) -> `install.ps1` újra; végrehajtási házirend -> a parancs `-ExecutionPolicy Bypass` kapcsolóval fut, ahogy fent |
| `claude mcp list` nem mutatja az új szervert újraindítás után | `powershell -ExecutionPolicy Bypass -File "<kit_path>/mcp/register-mcps.ps1" -Level <N>` újra, majd `claude mcp list` |
| a felhasználó visszalépne | `Edit`: a `@rules/kit-level-<N>.md` sor törlése és a `level` visszaírása; az MCP-k maradhatnak |

## Szabályok

- Egyszerre egy szintet lépj; 1-ről 3-ra nincs ugrás.
- Ne írd át a `rules/kit-level-*.md` fájlokat; azok a kit részei.
- A `settings.json` fájlt ne szerkeszd kézzel: az `update.ps1` dolga.
