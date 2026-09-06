# 2. szint: Kontroll

A felhasználó már érti, mit csinál egy riport, és bele akar látni: elolvassa a specet, módosít rajta a `/report-edit` paranccsal, figyeli a szinkron állapotát, és ha van NAV technikai felhasználó, bekapcsolja a NAV-forrást. Az 1. szint szabályai továbbra is érvényesek. Ezen a szinten aktív a `memory_backup.py` hook (a memóriafájlok mentése módosítás előtt, 20 példányig; a bejegyzését a szintlépés utáni `update.ps1` írja a `settings.json` fájlba) és a `microsoft-learn` MCP (hivatalos Microsoft-dokumentáció Excelhez és Power BI-hoz).

## Tervezési mód

`Shift+Tab` kétszer: az engedélymód tervezés lesz (a képernyő alján látszik). Ebben a módban csak olvasol és tervet írsz; fájlt nem módosítasz, parancsot nem futtatsz. Használata:

1. A felhasználó leírja, mit szeretne (például "kerüljön be a DSO a csempék közé").
2. Tervezési módban elolvasod a specet, és felsorolod, mely kulcsok változnának, és mi következik belőle (verzióemelés, új próbafuttatás).
3. Ő jóváhagyja, kilép a tervezési módból (`Shift+Tab`), és jön a végrehajtás, jellemzően a `/report-edit`.

A tervezési módból kilépéskor a `prime_nudge.py` hook kéri a `/prime` futtatását. Futtasd, mert a tervezés közben a kontextus elavulhatott.

## `/prime`

A `~/Riportok/.claude/commands/prime.md` parancs. Hét lépésben betölti: eszközök, adatállapot (`szamlazz_sync.py status`), mappaszerkezet, riporttábla (`run_reports.py --list`), verziók és kit-szint, kulcstények, legutóbbi munka. Nyolc soros összefoglalóval zárul, utána vár a feladatra. Futtasd minden `/clear` után és minden munkamenet elején, ha a `~/Riportok` mappában vagy.

## A projekt CLAUDE.md

A `~/Riportok/CLAUDE.md` a projekt saját szabálykönyve: mappák, a riport életútja öt lépésben, engedélyezett parancsok, tiltólista. A `~/.claude/CLAUDE.md` mindig betöltődik, a projekté csak a `~/Riportok` mappában. Ha a kettő ellentmond, a szigorúbbat kövesd.

## A spec.yaml olvasása és biztonságos módosítása

A spec szerkezetét a `@rules/reports.md` írja le. Olvasni bármikor lehet (`Read`). Módosítani így:

| Eset | Út |
|---|---|
| mérték, csempe, küszöb, kivétel, lap, leszállítási mappa változik | `/report-edit <slug>`: az érintett interjúkörök újra, verzióemelés, changelog, build.py újragenerálás, tesztek, próbafuttatás |
| egyetlen címke vagy elírás | `Edit` a specen, majd `uv run scripts/report_spec.py --validate reports/<slug>/spec.yaml`, majd `uv run scripts/report_spec.py --bump reports/<slug>/spec.yaml patch --note "..."`, majd próbafuttatás |
| `report.id`, `output.table_prefix`, meglévő táblanév | soha; a `--diff` és a `/report-edit` elutasítja 1.0.0 után |
| `report.locked: true` | csak a felhasználó kérésére; utána a specet a hook védi, és a `/report-edit` a hivatalos út |

Kézi szerkesztés után a spec soha ne maradjon validálás és próbafuttatás nélkül. A leszállítás továbbra is csak a `/report-run`.

## `/report-edit <slug>`

1. Betölti és összefoglalja a specet (cím, verzió, időszak, mértékek, leszállítás).
2. Megkérdezi, melyik szakasz változik, és csak az ahhoz tartozó interjúköröket nyitja újra.
3. `--diff` a régi és az új spec között, majd `--bump minor` (új mérték, lap, tábla) vagy `--bump patch` (küszöb, címke, top_n).
4. A report-engineer újragenerálja a `build.py`-t és a teszteket, a report-reviewer átnézi a próbafuttatást.
5. A spec `active` marad; a következő `/report-run` már az új verziót szállítja.

Elutasítja: mérték törlését, amelyre csempe, sor vagy küszöb hivatkozik; táblanév átnevezését vagy eltávolítását 1.0.0 után.

## A szinkron állapota

```
uv run scripts/szamlazz_sync.py status
```

Négy blokk: utolsó szinkron forrásonként, számlák előtag és év szerint a sorszámtartománnyal, nem aktív láncok (storno, módosító), számozási hiányok. Részletek és a havi egyeztetés: `@rules/szamlazz-data.md`. Ha a felhasználó azt kérdezi, friss-e az adat, ezt futtasd, és a forrásonkénti dátumot mondd meg.

## NAV technikai felhasználó bekapcsolása

Akkor érdemes, ha a cégnél van, aki az Online Számla rendszerben technikai felhasználót tud létrehozni. Lépések a felhasználónak:

1. Kérje a cég Online Számla elsődleges felhasználójától (Ügyfélkapu+ belépéssel): új technikai felhasználó "számlák lekérdezése" joggal, és tőle a négy adatot: felhasználónév, jelszó, XML aláírókulcs, a cég adószámának első 8 számjegye.
2. Frissítse a kitet NAV-lépéssel: `cd %USERPROFILE%\claude-kit`, majd `.\install.ps1 -Update` a `-SkipNav` kapcsoló nélkül.
3. Tárolja a négy titkot a `~/Riportok` mappából (mindegyik parancs láthatatlanul kéri be az értéket):

```
uv run scripts/get_secret.py set nav.gov.hu tech-login
uv run scripts/get_secret.py set nav.gov.hu tech-password
uv run scripts/get_secret.py set nav.gov.hu signing-key
uv run scripts/get_secret.py set nav.gov.hu tax-number
```

4. Ellenőrzés: `uv run scripts/get_secret.py check` (öt sor, mind "megvan"), majd `uv run scripts/szamlazz_sync.py pull --period <előző hónap>`.

Ettől kezdve a `pull --period` a NAV kivonatból veszi a számlák listáját, és az Agentből a részleteket. A titkokat soha ne kérd a chatbe, csak a parancsot add meg.

@rules/reports.md
@rules/szamlazz-data.md

## Mikor lépj a 3. szintre

Akkor javasold a `/level-up` parancsot, ha a felhasználó:

- legalább egy riportot módosított már a `/report-edit` paranccsal, és a következő futás rendben leszállt,
- rákérdezett az ütemezett futásra, a Power BI kapcsolatra vagy arra, mit csinál egy ügynök,
- olyan ismétlődő kérdést hoz, amit egy `claude -p` parancs vagy egy hook oldana meg.
