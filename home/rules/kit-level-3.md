# 3. szint: Automatizálás

A felhasználó a kit belső részeit is használja: olvassa az ügynökök leírását, óvatosan szerkeszt hookot, kezeli az ütemezett futást, Power BI-t köt a riportokra, és parancssorból is kérdez. Ezen a szinten elérhető a `powerbi-modeling` és az `ms365` MCP, valamint a `web-researcher` ügynök. Az 1. és a 2. szint szabályai érvényben maradnak: leszállítani továbbra is csak a `/report-run` tud, a leszállítási mappába kézzel senki nem ír.

## Ügynökök

Az ügynök egy külön Claude-példány saját utasításfájllal, eszközlistával és modellel. A skillek hívják; a felhasználó ritkán közvetlenül. A fájlok: `~/.claude/agents/<név>.md`.

| Ügynök | Modell | Mit csinál | Mit soha |
|---|---|---|---|
| `report-analyst` | opus | interjúválaszokból spec.yaml, vezetői blokk tervezése, reconcile eltérés magyarázata | Python, build.py, leszállított fájl |
| `report-engineer` | opus | build.py és tests/ a sablonból, próbafuttatás, buildhiba javítása, mértékkatalógus bővítése | spec.yaml módosítása, leszállítás |
| `report-reviewer` | sonnet | kész xlsx visszaolvasása, cellára pontos hibalista a spec ellen, reconcile | javítás, build futtatása |
| `gmail-utility` | sonnet | piszkozat, keresés, melléklet letöltése két fiókkal | küldés a szó szerinti "küldd el" nélkül |
| `web-researcher` | sonnet | hivatalos NAV, szamlazz.hu, Power BI és xlsxwriter dokumentáció URL-lel és idézettel | fájlírás, forrás nélküli állítás |

Egy agentfájl olvasása: a fejléc (`name`, `description` a FOR és a NEM ERRE listával, `model`, `tools`), aztán a `## Soha` blokk, a munkamenet és a `## Visszaadási protokoll`. Ha a felhasználó azt kérdezi, melyik ügynök csinált valamit, a leírás FOR listája válaszol. Ügynökfájlt módosítani lehet, de az `update.ps1` a kit változatát visszaírja (a módosított fájl másolata a `~/.claude/.kit-backups/<időbélyeg>/` alá kerül); tartós módosítás a kit repóba való.

Közvetlen hívás, ha kell: "Használd a report-reviewer ügynököt a reports/<slug>/_dryrun/ fájlra."

## Hook szerkesztése

A hookok a `~/.claude/hooks/*.py` fájlok. Csak a Python szabványkönyvtárat használják, és hibatűrők (fail-open): ha bennük bármi váratlan történik, átengedik a műveletet, és egy sort írnak a `~/.claude/hooks/.hook-errors.log` fájlba. Szerkesztés szabályai:

1. Először olvasd el a kit repóban a `~/claude-kit/docs/HOOKS.md` fájlt: esemény, bemenet, kilépési kód, mintabemenetek.
2. Módosítás előtt másolat: `Copy-Item ~/.claude/hooks/protect_delivery.py ~/.claude/hooks/protect_delivery.py.bak`.
3. Ne vegyél be külső csomagot, ne írj a stdout-ra JSON-on kívül semmit, és 2-es kóddal csak akkor lépj ki, ha blokkolni akarsz (annak csak PreToolUse eseménynél van hatása).
4. Próba: adj be egy mintabemenetet a `HOOKS.md` szerint, és nézd meg a kilépési kódot és a kimenetet.
5. Ha elromlott: a `.bak` visszamásolása, vagy `update.ps1`, amely a kit változatát visszaírja. A `.hook-errors.log` mondja meg, mi történt.

A `settings.json` hook-bejegyzéseit ne kézzel írd: az `install.ps1 -Update` (az `update.ps1` hívja) fésüli össze a szint szerint, és csak a kit saját bejegyzéseit cseréli; ezért kér a `/level-up` a végén `update.ps1` futtatást.

## Feladatütemező

A telepítő létrehozta a `\Controller\HaviRiport` feladatot: minden hónap 5-én 07:00-kor lefut

```
uv run "%USERPROFILE%\Riportok\scripts\run_reports.py" --all --period previous_month
```

| Cél | Parancs |
|---|---|
| állapot és következő futás | `schtasks /Query /TN "\Controller\HaviRiport" /V /FO LIST` |
| futtatás most (próbához) | `schtasks /Run /TN "\Controller\HaviRiport"` |
| a futás eredménye | `uv run scripts/run_reports.py --list`, vagy a `reports/<slug>/runlog.jsonl` utolsó sora |
| kikapcsolás és visszakapcsolás | `schtasks /Change /TN "\Controller\HaviRiport" /DISABLE`, majd `/ENABLE` |

A futás nem használ Claude-ot: tiszta Python a specek szerint, a `previous_month` időszakra. Ha a laptop 5-én reggel ki volt kapcsolva, a futás elmaradhatott: a `session_tips.py` 5. és 7. között emlékeztet, a `/report-run --all` pótolja.

## Power BI Desktop

Két kötési mód, mindkettő a riport kimenetére épül, nem az adatbázisra:

| Forrás | Hogyan | Mikor |
|---|---|---|
| a munkafüzet névvel ellátott táblái (`tbl_<slug>_<entity>`) | Power BI Desktop: Adatok lekérése, Excel-munkafüzet, a leszállított fájl; a Navigátorban a táblákat válaszd, ne a munkalapokat | egy riport, kevés tábla |
| CSV mappa (`powerbi.folder`, alapból `exports/powerbi/`) | Adatok lekérése, Mappa; fájlonként `fact_invoice`, `fact_invoice_line`, `fact_payment`, `fact_measure`, `dim_customer`, `dim_date` | több riport, csillagséma |

A CSV export a specben kapcsolható: `powerbi.enabled: true`, a `files` listában a kért entitások. A fájlok UTF-8 BOM kódolásúak, minden futás helyben felülírja őket, így a Power BI frissítés mindig az utolsó futást látja. A táblanevek 1.0.0 után nem változnak, ezért a modell nem törik el egy spec-módosítástól. OneDrive-mappából a Power BI szolgáltatás is tud frissíteni.

A `powerbi-modeling` MCP a megnyitott Power BI Desktop modellhez kapcsolódik: mértékek, kapcsolatok, DAX olvasása és írása. Módosítás előtt a `.pbix` mentése, és a felhasználóval egyeztetett lista arról, mi változik. Dokumentációs kérdésre a `microsoft-learn` MCP vagy a `web-researcher`.

## `claude -p` receptek

A `claude -p "..."` egy kérdés, egy válasz, párbeszéd nélkül, a terminálban. A `~/Riportok` mappából futtatva a projekt CLAUDE.md is betöltődik. Három bevált recept:

```
claude -p "Futtasd: uv run scripts/run_reports.py --list, és add vissza a táblázatot változatlanul."
claude -p "Futtasd: uv run scripts/report_spec.py --validate reports/havi_arbev_kintlev/spec.yaml, és mondd meg egy sorban, érvényes-e; ha nem, mi a hiba."
claude -p "Olvasd be a reports/havi_arbev_kintlev/runlog.jsonl utolsó sorát, és foglald össze három sorban: időszak, eredmény, bukott ellenőrzések."
```

Csak olvasó feladatra. Ami írna, szinkronizálna vagy leszállítana, azt ne `-p` alatt kérd: ott nincs mód közben kérdezni, és az engedély nélküli eszközhívás elakad.

## `web-researcher`

Hivatalos forrásból válaszol: `onlineszamla.nav.gov.hu`, `docs.szamlazz.hu`, `tudastar.szamlazz.hu`, `learn.microsoft.com`, `xlsxwriter.readthedocs.io`. Minden állításhoz URL, szó szerinti idézet és dátum; ha nem találta, az első sor: "Nem találtam." Hívás: "Nézz utána a web-researcher ügynökkel, változott-e a queryInvoiceDigest lapozása." Fájlt nem ír; ami a válaszból a specbe vagy a kódba kerül, azt a report-analyst vagy a report-engineer viszi át.

## Nincs 4. szint

Ami ezen túl kell (új mérték a katalógusban, új skill, új hook), az a kit fejlesztése: a `~/claude-kit` repóban történik, és az `update.ps1` hozza át. Ilyen kérésnél írd le pontosan, mi hiányzik, hogy a mentor be tudja építeni.
