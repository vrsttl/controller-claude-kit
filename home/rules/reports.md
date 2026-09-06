# Riportok: a spec.yaml és a kimenet

A `reports/<slug>/spec.yaml` írja le a riportot; a `build.py` csak végrehajtja. Minden módosítás a specben történik, utána validálás, verzióemelés, próbafuttatás. Mintaspec: `reports/_examples/havi_arbev_kintlev/spec.yaml`. Séma és katalógus a parancssorból: `uv run scripts/report_spec.py --validate <spec>` és `--catalogue`.

## `report`

| Kulcs | Jelentés | Tipikus érték |
|---|---|---|
| `id` | a riport állandó azonosítója, soha nem változik | `rpt_3f9a1c2e` (a `--new` adja) |
| `slug` | mappanév és fájlnév-előtag, snake_case | `havi_arbev_kintlev` |
| `title_hu`, `title_en` | cím a munkafüzetben és a listában | `Havi árbevétel és kintlévőség` |
| `owner` | a felelős e-mail címe | `kontroller@ceg.hu` |
| `version` | semver, a `--bump` emeli | `1.0.0` |
| `status` | `draft`, `active`, `retired`; az ütemezett futás csak az `active` riportokat viszi | `active` |
| `changelog[]` | `{version, date, note}` bejegyzések, a `--bump` fűzi hozzá | |
| `locked` | `true` esetén a `protect_delivery.py` hook a specet is védi; ilyenkor csak a `/report-edit` módosíthatja | hiányzik (nem zárolt) |

## `period`

| Kulcs | Jelentés | Értékek |
|---|---|---|
| `grain` | az időszak hossza | `month`, `quarter`, `ytd`, `week`, `custom` |
| `basis` | melyik dátum sorol be egy számlát | `kelt` (kiállítás), `teljesites` (teljesítés) |
| `offset` | melyik időszak a futás napjához képest | `previous_full_month`, `current_month_to_date`, `previous_full_quarter`, `previous_full_week`, `current_week_to_date`, vagy `{start, end}` |
| `fiscal_year_start_month` | az üzleti év kezdő hónapja | `1` |
| `as_of` | a kintlévőség fordulónapja | `period_end`, `run_date` |
| `history_months` | hány hónap előzmény a sparkline-hoz és az összehasonlításhoz | `13` (1 és 60 között; `yoy` vagy `ytd` mellett ne legyen 13 alatt) |
| `storno_attribution` | a storno melyik hónapba kerül | `issue_month` (a storno kiállítási hónapja, alapértelmezés), `original_month` (az eredeti számla hónapja) |

## `sources`

| Kulcs | Jelentés | Tipikus érték |
|---|---|---|
| `agent: {required, path}` | Számla Agent adat (tétel, ÁFA-bontás, fizetés) | `{required: true}` |
| `nav_digest: {required, path}` | NAV Online Számla kivonat | `{required: false}`, amíg nincs technikai felhasználó |
| `fokonyvi_csv: {required, path}` | Főkönyvi adatexport CSV, csak egyeztetéshez | `{required: false, path: "data/drops/fokonyvi_{period}.csv"}` |
| `afalista: {required, path}` | Áfalista XLSX, csak egyeztetéshez | `{required: false, path: "data/drops/afalista_{period}.xlsx"}` |
| `max_age_days` | ennél régebbi kötelező forrásnál a V02 figyelmeztet | `3` |
| `cash_card_autopaid` | készpénzes és kártyás számla fizetettnek számít kiállításkor | `true` |

Az A betűs mértékekhez (lásd a katalógust) `agent.required: true` kell.

## `filters`

| Kulcs | Jelentés | Tipikus érték |
|---|---|---|
| `customers: {include, exclude}` | vevőnév-minták (`*` és `?` helyettesítővel) | `{include: ["*"], exclude: []}` |
| `invoice_prefixes` | csak ezek az előtagok; üres lista = mind | `[]` vagy `[SZLA, E-SZLA]` |
| `currencies` | csak ezek a devizák; üres lista = mind | `[]` |
| `vat_rates` | csak ezek a kulcsok; üres lista = mind | `[]` |
| `doc_types` | bizonylattípusok | `[invoice, modifier, storno]` |
| `exclude_proforma` | díjbekérő kizárása | `true` |
| `min_net_huf` | ennél kisebb nettójú számla kimarad | `0` |

## `dimensions`

Részhalmaz ebből: `month`, `customer`, `product`, `vat_rate`, `currency`, `payment_method`. Csak az kerüljön be, amit egy mérték vagy egy lap használ; a `product` és a `vat_rate` Agent-adatot igényel.

## `measures[]`

| Kulcs | Jelentés | Értékek |
|---|---|---|
| `id` | katalógusbeli azonosító vagy `custom:<slug>` | `rev_net` |
| `params` | a mérték paraméterei | `{n: 10}` a `top_n_share` mértéknél (alapból 5) |
| `comparisons` | összehasonlítások | részhalmaz ebből: `mom`, `yoy`, `ytd`, `avg3m` |
| `format` | számformátum | `huf_k` (ezer Ft), `huf`, `eur`, `pct`, `days`, `count` |

A `custom:<slug>` képlete csak katalógus-azonosítókból, `prior(id, n)` hívásból és a négy alapműveletből állhat.

### Mértékkatalógus

Forrásbetű: D = a NAV kivonat fejlécadataiból is számolható, A = Agent-lekérés kell hozzá (tétel, ÁFA-bontás, fizetés). Agent-szinkronnal minden mérték elérhető; csak NAV-adatból a D betűsek.

| Csoport | Mérték (forrás) |
|---|---|
| árbevétel | `rev_net` (D), `rev_net_cust` (D), `rev_net_prod` (A), `rev_net_vat` (A), `rev_net_cur` (D), `rev_gross` (D), `inv_count` (D), `avg_inv` (D), `top_n_share` (D) |
| ÁFA | `vat_by_rate` (A), `vat_total` (D) |
| vevők | `cust_active` (D), `cust_new` (D), `cust_returning` (D), `cust_churned` (D) |
| kintlévőség | `ar_balance` (A), `ar_aging` (A), `overdue_amt` (A), `overdue_cnt` (A), `dso` (A), `cash_in` (A), `coll_rate` (A), `ontime_rate` (A) |
| minőség és mix | `storno_rate` (D), `modifier_rate` (D), `einv_share` (A), `pm_mix` (D), `eur_share` (D), `eur_open` (A), `fx_dev` (A) |

A magyar címkék és a képlet szavakkal a `--catalogue` kimenetében és a munkafüzet `Definíciók` lapján vannak.

## `thresholds.<id>`

| Kulcs | Jelentés | Értékek |
|---|---|---|
| `warn` | borostyán szint | szám |
| `critical` | piros szint | szám |
| `direction` | merre baj | `above` (felette: `overdue_amt`, `dso`), `below` (alatta: `coll_rate`) |
| `unit` | a szint mértékegysége | `abs`, `pct`, `pct_of:<másik mérték id>` |

Csak létező `measures[].id` kaphat küszöböt. Szín csak tényleges sértésnél: piros a `critical`, borostyán a `warn`, máshol semmi.

## `exceptions[]`

| Szabály | Mit sorol fel | Paraméter |
|---|---|---|
| `overdue_gt_days` | lejárt nyitott számlák X napon túl | `days` |
| `overdue_gt_amount` | lejárt nyitott számlák X Ft felett | `amount_huf` |
| `storno_in_period` | az időszak stornói | |
| `modifier_in_period` | az időszak helyesbítői | |
| `amount_outlier_zscore` | szokatlan összegű számla | `z` (alapból 3), `window_months` (alapból 12) |
| `missing_customer_taxno` | vevő adószám nélkül | `only_domestic_companies` |
| `fx_deviation` | devizás számla, ahol a NAV HUF érték eltér az összeg és az árfolyam szorzatától | `tolerance` (alapból 0.005) |
| `duplicate_customer_name` | hasonló nevű vevők | |
| `unpaid_cash_invoice` | készpénzes számla rögzített fizetés nélkül | |

Minden bejegyzés: `id`, `rule`, `params`, `severity` (`info`, `warn`, `critical`), `max_rows`. A `Kivételek` lapon minden sor megjelenik, a vezetői lapon összesen legfeljebb 12, súlyosság szerint rendezve.

## `output`

| Kulcs | Jelentés | Tipikus érték |
|---|---|---|
| `file_pattern` | fájlnév; tokenek: `{slug}`, `{period}`, `{version}`, `{run_date}` | `{slug}_{period}_v{version}.xlsx` |
| `language` | a címkék nyelve | `hu` |
| `number_profile` | a pénzösszegek formátuma | `huf_thousands` (e Ft), `huf_full` (Ft) |
| `sheets[]` | lapok | részhalmaz ebből: `executive`, `exceptions`, `invoice`, `line`, `payment`, `customer`, `measure`, `definitions`, `runlog` |
| `executive.blocks[]` | a vezetői lap blokkjai sorrendben | `title`, `tiles`, `variance`, `ar_aging`, `vat_summary`, `top_customers`, `exceptions`, `footnote` |
| `executive.tiles[]` | csempék | legfeljebb 6 mérték-id |
| `executive.variance_rows[]` | az eltéréstábla sorai | legfeljebb 9 mérték-id |
| `executive.top_n` | a vevőlista hossza | `5` vagy `10` |
| `table_prefix` | az Excel-táblák előtagja | `tbl_<slug>` |

Lapnevek magyarul: `Vezetői összefoglaló`, `Kivételek`, `Számlák`, `Tételek`, `Kifizetések`, `Ügyfelek`, `Mutatók`, `Definíciók`, `Futtatási napló`. Az `executive` lap kötelező (a validálás elutasítja nélküle); a `definitions` és a `runlog` alapból benne van, és ne kerüljön ki: a reviewer és a hibakeresés ezekre épül.

### A vezetői lap

Egy képernyő (1920x1080, 100 százalék) és egy fekvő A4: A..V oszlopok, nagyjából 38 sor, rögzítés az A3 cellánál, Calibri 9. Tartalma a blokkok sorrendjében:

| Blokk | Tartalom |
|---|---|
| `title` | cím, időszak, alap (kelt vagy teljesítés), a futás ideje, spec-verzió, ellenőrzési jelvény |
| `tiles` | legfeljebb 6 csempe: érték, MoM és YoY változás, 12 havi sparkline |
| `variance` | eltéréstábla, 8 oszlop: aktuális, előző, MoM%, előző év, YoY%, YTD, YTD előző év, YTD% |
| `ar_aging` | korosított kintlévőség: `Nem lejárt`, `1-30 nap`, `31-60 nap`, `61-90 nap`, `90+ nap`, adatsávval |
| `vat_summary` | ÁFA kulcsonként: nettó, ÁFA, bruttó |
| `top_customers` | top N vevő: nettó, részarány, halmozott részarány, MoM nyíl, 6 havi sparkline |
| `exceptions` | legfeljebb 12 kivétel súlyosság szerint, hivatkozás a `Kivételek` lapra |
| `footnote` | 3 sor: definíciók, források, ellenőrzés |

Számformátumok: `#,##0," e Ft"`, `#,##0" Ft"`, `#,##0.00" €"`, `0.0%`, `+0.0%;-0.0%;0.0%`, `0" nap"`, `#,##0" db"`. Nincs kitöltőszín, nincs diagram a sparkline-on kívül, egyesített cella csak a címsorban.

Sűrűségi szabály: minden számnak van viszonyítása (MoM, YoY, YTD vagy küszöb); árva szám nem kerül a lapra. Egy blokk nem ismétli egy másik tartalmát. Ha egy kérés nem fér a korlátokba (hetedik csempe, tizedik sor), a válasz nem a korlát tágítása, hanem választás: mi kerüljön ki.

## `powerbi`

| Kulcs | Jelentés | Tipikus érték |
|---|---|---|
| `enabled` | CSV export be vagy ki | `false` |
| `folder` | célmappa (a hook védi) | `exports/powerbi` |
| `files[]` | entitások | részhalmaz ebből: `fact_invoice`, `fact_invoice_line`, `fact_payment`, `fact_measure`, `dim_customer`, `dim_date` |

## `delivery`

| Kulcs | Jelentés | Értékek |
|---|---|---|
| `folder` | leszállítási mappa (a hook védi) | `exports` vagy egy OneDrive-mappa teljes útvonala |
| `overwrite` | mi történjen, ha a célfájl létezik | `never` (hiba), `same_version` (alapértelmezés: azonos verziójú fájlt felülír; ha a fájlnévben nincs verzió, a verzióval kiegészített néven ment), `always` |
| `keep_n_versions` | ennyi korábbi fájl marad a mappában, a többit a leszállítás törli | `6` |

A leszállítás menete: a build a `.staging/` mappába ír, lefutnak az ellenőrzések, és csak utána kerül a fájl a célmappába. Kimenetek (a `run_reports.py --list` is ezt mutatja):

| Kimenet | Mit jelent | Teendő |
|---|---|---|
| `kézbesítve` | a fájl a célmappában van | nincs |
| `elutasítva` | blokkoló ellenőrzés bukott; a fájl a `<delivery.folder>/_rejected/<név>_FAILED.xlsx` helyre került | a `Futtatási napló` lapon a bukott ellenőrzés; adat vagy spec javítása, újrafuttatás |
| `függőben` | a célfájl zárolt (nyitva Excelben vagy OneDrive-szinkron alatt); a fájl `<név>.pending.xlsx` néven került a célmappába | az Excel bezárása, majd `/report-run` újra; vagy a felhasználó kézzel átnevezi a `.pending.xlsx` fájlt (te nem: a hook tiltja) |
| `nem írható felül` | `overwrite: never`, és a célfájl létezik | spec-döntés, vagy a régi fájl elmozdítása |
| `próbafuttatás` | `--dry-run`: a fájl a `_dryrun/` mappában maradt | nincs |

## `validation`

`checks[]`: `{id, tolerance, severity, blocks_delivery}`; `min_rows`: ennyi bizonylat alatt a V14 jelez. Amit a spec nem sorol fel, az az alapértelmezéssel fut.

| Id | Cím (így írja a napló) | Mit néz | Blokkol alapból |
|---|---|---|---|
| V01 | Spec értelmezhető | a spec betölthető és érvényes | igen |
| V02 | Forrás frissesség | kötelező forrás sikeres szinkronja az időszakra, `max_age_days` napon belül | nem |
| V03 | NAV digest darabszám = gyorsítótár | a NAV kivonat és a gyorsítótár számlaszáma egyezik (csak NAV-forrással) | nem |
| V04 | Tételsorok összege = fejléc | tűrés 1 Ft | igen |
| V05 | ÁFA-bontás összege = fejléc | tűrés 1 Ft | igen |
| V06 | NAV HUF vs összeg × árfolyam | a NAV HUF érték és az összeg szorozva árfolyam eltérése (tűrés 0.5 százalék) | nem |
| V07 | Áfalista egyeztetés | a betöltött Áfalista és a gyorsítótár kulcsonként | nem |
| V08 | Főkönyvi CSV fizetettség egyeztetés | a CSV fizetettsége és a levezetett `pay_status` | nem |
| V09 | Nincs vevő nélküli számla | | nem |
| V10 | Lezárt időszak stabilitása | ugyanaz az eredmény, mint az előző futásnál erre az időszakra | nem |
| V11 | Számlalánc integritás | minden storno és helyesbítő eredetije megvan | igen |
| V12 | Árfolyam ésszerűség | | nem |
| V13 | Duplikált számlák | | nem |
| V14 | Minimális sorszám | legalább `min_rows` bizonylat | nem |
| V15 | Belső egyeztetés (vevő = ÁFA-kulcs = összesen) | vevőnkénti összeg = kulcsonkénti összeg = `rev_net` | igen |
| V16 | Kimeneti fájl épsége | megnyitható, lapok, táblák, csempe- és kivételkorlát | igen |

Blokkoló bukás: nincs leszállítás, `_rejected/`, kilépési kód 1. Nem blokkoló bukás: a leszállítás megtörténik, a jelvény és a lábjegyzet jelzi. A `blocks_delivery` kulccsal egy ellenőrzés blokkolóvá tehető; a hat alapból blokkolót ne kapcsold ki.

## Táblanevek

Minden adatlapon egy névvel ellátott Excel-tábla: `tbl_<slug>_<entity>` (például `tbl_havi_arbev_kintlev_invoice`), angol snake_case fejlécekkel. A Power BI és minden képlet ezekre a nevekre hivatkozik, ezért 1.0.0 után a `table_prefix` és a meglévő táblanevek véglegesek: a `--diff` és a `/report-edit` elutasítja az átnevezést és a tábla eltávolítását. Új entitás új táblát kaphat, a régi marad.

## Verzió és changelog

| Változás | `--bump` |
|---|---|
| új vagy törölt mérték, lap, tábla, dimenzió, forrás, kivételszabály, időszaktípus, alap (kelt vagy teljesítés) | `minor` |
| küszöb, kivételparaméter, címke, cím, gazda, `top_n`, `max_rows`, leszállítási mappa, felülírási szabály, Power BI ki vagy be | `patch` |

```
uv run scripts/report_spec.py --bump reports/<slug>/spec.yaml minor --note "DSO csempe"
uv run scripts/report_spec.py --diff <régi spec> <új spec>
```

A verziót és a changelogot soha ne írd kézzel.
