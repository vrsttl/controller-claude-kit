# szamlazz.hu adatok: források, szinkron, egyeztetés

## Tények, amelyekre minden épül

| Tény | Következmény |
|---|---|
| A Számla Agent API csak egy számlát ad vissza számlaszám alapján; lista- vagy keresővégpont nincs | a szinkron sorszámonként kérdez le, egy előtagra és egy évre |
| A számlaszám `ELŐTAG-ÉÉÉÉ-N`, előtagonként és évenként hézagmentes | a felsorolás az utolsó ismert sorszám + 1-től indul, és 3 egymást követő "nincs ilyen számla" válasz (7-es hibakód) után megáll |
| A lekérdezés díja feltehetően nulla (a díj a kiállított bizonylat után jár) | az első teljes évi felsorolás előtt meg kell erősíttetni a szamlazz.hu ügyfélszolgálatával, lásd lent |
| A szinkron inkrementális: csak az új sorszámokat kéri le; a nyers válasz a `raw_documents` táblába kerül, a többi tábla ebből épül újra | bármikor újrafuttatható; a havi kérésszám a havi számlaszám plusz 3 |
| NAV Online Számla 3.0: a cég a saját kimenő számláit listázhatja legfeljebb 35 napos ablakonként (`queryInvoiceDigest`), tétel és fizetettség nélkül; a teljes XML a `queryInvoiceData` hívással jön | technikai felhasználó kell hozzá (2. szint); a NAV a lista, az Agent a részlet |
| A kézi exportok (Listák: Főkönyvi adatexport CSV, Áfalista XLSX) csak kézzel indíthatók | csak havi egyeztetési kontroll, soha nem elsődleges forrás |
| Storno és helyesbítő bizonylat előjeles összeggel érkezik, és egy lánchoz tartozik (`v_chain` nézet, `chain_root`) | a riport a lánc eredő értékét mutatja; hiányzó eredeti számla V11 bukás |
| HUF-ban nincs tizedes | sehol nincs osztás 100-zal, nincs kerekítés; formátum `#,##0" Ft"` vagy `#,##0," e Ft"` |
| ÁFA-kulcsok: `27`, `5`, `0`, `AAM`, `TAM`, `EU`, `EUK` | az `invoice_vat` tábla kulcsonként bontja; a spec `filters.vat_rates` szűrhet |
| Az Agent PDF-et is tudna adni, de a szinkron nem kéri | a `data/drops/pdf/<ÉÉÉÉ-HH>/` PDF-archívumot a gmail-utility tölti fel a számlaértesítőkből; nem riportforrás |

### Fizetettség

A `pay_status` levezetése ebben a sorrendben; az első találat dönt:

1. storno vagy stornózott bizonylat: `void`, nyitott összeg 0
2. díjbekérő (proforma): kimarad
3. készpénz vagy kártya, ha `sources.cash_card_autopaid: true`: `paid`
4. a rögzített fizetések összege 1 Ft-on belül eléri a bruttót: `paid`
5. van fizetés, de kevesebb: `partial`
6. különben: `unpaid`

Lejárt = `unpaid` vagy `partial`, és a fizetési határidő a fordulónap (`period.as_of`) előtt van.

### A storno hovatartozása

Alapból a storno a saját kiállítási hónapjába kerül (`period.storno_attribution: issue_month`). Az `original_month` érték az eredeti számla hónapjába teszi. Ez spec-döntés, nem adathiba: ha a felhasználó eltűnt vagy kétszer szereplő stornót lát, ezt a kulcsot nézd meg először.

## Szinkronparancsok

Mind a `~/Riportok` mappából, `uv run` alatt. Kilépési kód: 0 rendben, 1 adathiba vagy eltérés, 2 használati hiba vagy hiányzó titok, 3 hálózati hiba (később újra).

| Parancs | Mikor |
|---|---|
| `uv run scripts/szamlazz_sync.py init` | egyszer, telepítés után (a telepítő lefuttatja); sémát hoz létre, meglévő adatot nem bánt |
| `uv run scripts/szamlazz_sync.py pull --agent-only --prefix SZLA --year 2026` | az alapút: egy előtag egy évének felsorolása az Agentből, az utolsó ismert sorszámtól; több előtag: `--prefix` ismételve; első alkalommal egy előtaggal |
| `uv run scripts/szamlazz_sync.py pull --period 2026-08` | NAV technikai felhasználóval: a hónap számlalistája a NAV-tól, a részletek az Agentből |
| `uv run scripts/szamlazz_sync.py import-csv data/drops/fokonyvi_2026-08.csv` | a Főkönyvi adatexport betöltése a `staging_fokonyvi` táblába (egyeztetéshez) |
| `uv run scripts/szamlazz_sync.py import-afalista data/drops/afalista_2026-08.xlsx` | az Áfalista betöltése a `staging_afalista` táblába (egyeztetéshez) |
| `uv run scripts/szamlazz_sync.py reconcile --period 2026-08` | a gyorsítótár és a betöltött exportok összevetése számlánként és ÁFA-kulcsonként; eltérésnél kilépési kód 1 és `data/reconcile-2026-08.csv` |
| `uv run scripts/szamlazz_sync.py status` | állapot, bármikor, csak olvas |

A `--period` és az `--agent-only` nem adható meg együtt. Az `--agent-only` módhoz `--prefix` és `--year` is kell. Ritkán kellő kapcsolók: `--start-seq N` (kezdő sorszám), `--max N` (kéréskorlát előtagonként, alapból 500), `--with-nav-data` (a `--period` mellett a NAV teljes számla-XML-jét is letölti), `--tolerance` (a reconcile tűrése Ft-ban, alapból 1).

A szinkront a `/report-run` is elindítja a spec forrásai szerint. Kézzel akkor futtasd, ha a felhasználó a riport előtt látni akarja az adatállapotot, vagy új előtag jelent meg.

## Havi egyeztetés

Minden hónapzárás előtt, a lezárt hónapra (a példában 2026-08):

1. A felhasználó a szamlazz.hu felületén: Listák, Főkönyvi adatexport, a hónap, CSV letöltése; majd Listák, Áfalista, a hónap, XLSX letöltése.
2. A két fájlt a `~/Riportok/data/drops/` mappába teszi. A név szabad; a spec `sources.*.path` mintája szerint érdemes: `fokonyvi_2026-08.csv`, `afalista_2026-08.xlsx`.
3. `uv run scripts/szamlazz_sync.py import-csv data/drops/fokonyvi_2026-08.csv`
4. `uv run scripts/szamlazz_sync.py import-afalista data/drops/afalista_2026-08.xlsx`
5. `uv run scripts/szamlazz_sync.py reconcile --period 2026-08`
6. Kilépési kód 0: mehet a `/report-run`. Kilépési kód 1: a `data/reconcile-2026-08.csv` soronként mutatja a számlát, a mezőt, a gyorsítótár és az export értékét; a magyarázatot a report-analyst ügynök adja, a javítás vagy az újraszinkron utána.

Ha az export fejlécét a szkript nem ismeri fel, a hibaüzenet a `HEADER_MAP_FOKONYVI` vagy a `HEADER_MAP_AFALISTA` listára mutat a `szamlazz_sync.py` elején. Ezt a mentor bővíti; ne találgass oszlopnevet.

## Mit mutat a `status`

| Blokk | Tartalom | Mire figyelj |
|---|---|---|
| Utolsó szinkron forrásonként | `agent`, `nav_digest`, `nav_data`, `csv`, `afalista` (és az `init`, `reconcile` futások): a befejezés ideje, letöltve, új, hiba; `(még nem volt szinkron)`, ha üres | a lezárt hónap után van-e friss `agent` sor |
| Számlák előtag és év szerint | `SZLA-2026: 143 db (1..143)` | a tartomány vége egyezik-e a szamlazz.hu-n látott utolsó számlaszámmal |
| Nem aktív láncok | storno vagy módosítás alatt álló láncok, bizonylatszámmal | a hiányzó eredeti számla V11 bukást okoz |
| Számozási hiányok | előtagonként a hiányzó sorszámok listája | lásd lent |

## Mit jelent egy számozási hiány

A szamlazz.hu számozása hézagmentes, ezért egy hiányzó sorszám mindig jelent valamit:

| Ok | Teendő |
|---|---|
| a felsorolás megszakadt (hálózat, `--max` korlát, Esc) | `pull --agent-only` újra ugyanarra az előtagra és évre; az utolsó ismert sorszámtól folytatja |
| a szám egy másik számlatömbhöz tartozik, vagy díjbekérő, amit a `filters` kizár | nem hiba: a `status` a nyers készletet mutatja, a szűrés a riportban történik |
| a szamlazz.hu-n tényleg nincs ilyen szám | ügyfélszolgálati kérdés; a szinkron nem áll meg miatta |

A hiány piros zászló, nem leállító hiba: a riport lefut. NAV-forrással a V03 (kivonat darabszám) jelzi az eltérést; Agent-only módban a `status` az egyetlen jelzés.

## Titkok

| Titok | Parancs |
|---|---|
| Számla Agent kulcs | `uv run scripts/get_secret.py set szamlazz.hu agent-key` |
| NAV technikai felhasználó (2. szint) | `uv run scripts/get_secret.py set nav.gov.hu tech-login`, majd ugyanígy `tech-password`, `signing-key`, `tax-number` (az adószám első 8 számjegye) |
| állapot, értékek nélkül | `uv run scripts/get_secret.py check` |

A `set` láthatatlanul kéri be az értéket, és a Windows hitelesítőtárban (Credential Manager) tárolja. A kulcs soha nem kerül a chatbe, a specbe, a naplóba vagy egy fájlba. Ha a felhasználó beillesztené, állítsd meg, és add meg a `set` parancsot. Hiányzó titoknál a szkript magyar hibaüzenete a pontos parancsot írja ki.

## Teendő: a lekérdezési díj megerősítése

Az Agent-lekérdezés (`xmlszamlaxml`) díja a kit feltevése szerint nulla. Amíg a szamlazz.hu ügyfélszolgálata ezt írásban meg nem erősítette, ne futtass teljes évi felsorolást, csak korlátozott próbát (`--max 50`). Ha a felhasználó teljes évet kér, kérdezd meg, megjött-e a válasz; ha nem, a levél szövege a kit `README.md` és `docs/HANDOVER.md` fájljában van.
