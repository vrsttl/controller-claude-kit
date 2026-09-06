# 1. szint: Napi használat

A felhasználó riportokat futtat és készít, a belső működést nem szerkeszti. Ezen a szinten csak az itt felsorolt parancsokat, eszközöket és fogalmakat használd és ajánld. Ami a 2. vagy a 3. szinthez tartozik (spec kézi szerkesztése, hookok, Feladatütemező, `claude -p`), azt ne hozd szóba; ha ő kérdez rá, irányítsd a `/level-up` parancshoz.

## Mit csinál a felhasználó ezen a szinten

| Feladat | Parancs |
|---|---|
| havi riport futtatása | `/report-run <slug>` (alapból az előző teljes hónap) |
| másik időszak | `/report-run <slug> --period 2026-08` |
| minden aktív riport egyszerre | `/report-run --all` |
| új riport | `/report-new`, majd válaszol a hét interjúkörre |
| áttekintés | `/report-list` |
| kísérőlevél a riporthoz | `/draft-email` |

## Engedélykérések

Claude Code minden fájlírás és minden parancs előtt engedélyt kér, amíg a felhasználó mást nem állít be. A kérdés azt mutatja, pontosan mi történne: melyik fájl, melyik parancs.

| Kérés | Teendő |
|---|---|
| `uv run scripts/...` vagy `uv run reports/<slug>/build.py ...` | elfogadható: a kit saját szkriptjei |
| írás a `reports/<slug>/` alá (spec.yaml, build.py, tests) | elfogadható skill futása közben |
| írás a `data/` vagy a leszállítási mappa alá | utasítsd el, és jelezd: ide csak a szinkron és a `/report-run` írhat |
| `rm`, `del`, `Remove-Item`, `move`, átnevezés | utasítsd el, ha nem ő kérte kimondva |
| bármi, amit nem ért | utasítsd el; az elutasítás nem ront el semmit, a kérdés újra feltehető |

Ha a felhasználó megkérdezi, mit jelent egy kérés, egy mondatban mondd meg, mi történne, és mi történik, ha nemet mond.

## Esc és /clear

- `Esc` bármikor megszakítja a futó műveletet. Ami félbeszakadt, újra kérhető; leszállított fájl nem sérül, mert a build először a `.staging/` mappába ír.
- Minden lezárt feladat után `/clear`. A régi beszélgetés nem segít, csak zavar: a következő riportnak tiszta kontextus kell. `/clear` után a `~/Riportok` mappában a `/prime` tölti vissza, amit tudni kell.

## A három riport-skill

| Skill | Mit csinál | Mikor |
|---|---|---|
| `/report-new` | interjú (7 kör), spec.yaml, build.py, próbafuttatás, ellenőrzés, aktiválás | új riport |
| `/report-run` | szinkron, build, ellenőrzés (V01..V16), leszállítás, a fájl megnyitása | minden hónapban |
| `/report-list` | táblázat a `reports/*/spec.yaml` fájlokból és az utolsó `runlog.jsonl` sorból | bármikor |

A `/report-edit` a 2. szinten kerül elő. Ha 1. szinten módosítást kér, mondd meg, hogy ez a `/report-edit` dolga, és ajánld a `/level-up` parancsot.

## A két MCP

| MCP | Mire | Mire nem |
|---|---|---|
| `gmail` | piszkozat, keresés, olvasás, melléklet letöltése (a `/draft-email` és a gmail-utility ügynök használja) | küldés kérés nélkül; a szó szerinti "küldd el" utasítás kell |
| `excel` | egy kész `.xlsx` megnyitása és beleolvasás, ha a felhasználó egy cellára kíváncsi | riport írása vagy módosítása; a riportot a `build.py` készíti, nem az MCP |

## A három hook (horog)

A hook olyan kis program, amely magától fut a háttérben; a felhasználónak nincs vele dolga.

- `session_tips.py`: minden indításkor egy tippet ír a szinthez, a hónap 5. és 7. napja között pedig emlékeztet, hogy az ütemezett havi riportnak el kellett készülnie.
- `prime_nudge.py`: `/clear`, kontextustömörítés és a tervezési módból kilépés után kéri a `/prime` futtatását, ha a projektben létezik.
- `protect_delivery.py`: blokkolja az írást, a szerkesztést és a törlő parancsokat a leszállítási mappákban (`delivery.folder`, `powerbi.folder`) és a zárolt specekben; az üzenete a `/report-run` parancshoz irányít.

Ha egy hook blokkol, ne kerüld meg (más útvonal, más parancs): mondd el a felhasználónak, mit védett, és mi a helyes út.

@rules/email.md

## Mikor lépj a 2. szintre

Akkor javasold a `/level-up` parancsot, ha mindhárom igaz:

- legalább három hónapzárás lefutott a `/report-run` paranccsal gond nélkül,
- a felhasználó rákérdezett már a spec.yaml tartalmára vagy a szinkron állapotára,
- módosítást kért egy meglévő riporton (mérték, küszöb, leszállítási mappa).
