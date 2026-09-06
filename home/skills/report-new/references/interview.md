# Interjú: a hét kör

Körönként egy `AskUserQuestion` hívás. Egy hívásban legfeljebb négy kérdés fér el; ami nem fér bele, azt a válasz után szabad szöveggel kérdezd. Az alapértelmezett érték mindig az első ajánlott opció, és a kérdés szövegében is szerepel. A felhasználó bármikor írhat szabad szöveget; azt rögzítsd változtatás nélkül.

A mértékek forrásbetűje: D = a NAV kivonat fejlécadataiból is számolható, A = Agent-lekérés kell hozzá (fizetés, tétel, áfabontás). A `uv run scripts/report_spec.py --catalogue` kimenete a mérvadó; az alábbi táblák ezt tükrözik.

## 1. kör: hatókör

Kérdések:

1. Mi legyen a riport címe? (szabad szöveg, magyarul; ez lesz a `title_hu`)
2. Jó ez a slug? Ajánlat a címből: kisbetű, ékezet nélkül, szavak aláhúzással, legfeljebb 30 karakter, rövidítve (például "Havi árbevétel és kintlévőség" -> `havi_arbev_kintlev`). Opciók: az ajánlott slug | "Más: ..."
3. Ki a riport gazdája? (név vagy e-mail; `owner`)
4. Mire használod? Opciók: "havi vezetői összefoglaló" | "kintlévőség-követés" | "ÁFA-bevallás előkészítése" | "ügyfélelemzés" | "Más: ..."

Alapértelmezések:

| Mező | Érték |
|---|---|
| slug | a címből képzett javaslat |
| owner | a felhasználó neve, ha ismert |
| cél | havi vezetői összefoglaló |

Ellenőrzés: slug `^[a-z0-9_]+$`, nem létező mappa a `reports/` alatt, nem `_examples`.

Tárold: `title_hu`, `slug`, `owner`, `cél` (a Definíciók lapra és az ügynök promptjába kerül; a specben nincs külön kulcsa).

## 2. kör: időszak és források

Kérdések:

1. Milyen időszakra készül? Opciók: "előző teljes hónap (havi)" | "folyó hónap a mai napig" | "előző teljes negyedév" | "előző teljes hét" | "egyedi tartomány"
2. Melyik dátum számít? Opciók: "kiállítás kelte (kelt)" | "teljesítés dátuma (teljesites)"
3. Mely forrásokra épül? Többes választás: "szamlazz.hu Agent (alapeset, minden mérték)" | "NAV Online Számla kivonat (csak ha van technikai felhasználó)" | "Főkönyvi adatexport CSV egyeztetéshez" | "Áfalista XLSX egyeztetéshez"
4. A készpénzes és bankkártyás számlát tekintsük kiegyenlítettnek a kiállítás napján? Opciók: "igen" | "nem"

Mondd ki a kérdés szövegében: az első napon a szinkron Agent-alapú, ezért minden mérték elérhető. Ha később a NAV kivonat lesz az elsődleges forrás és az Agent kimarad, az A betűs mértékekhez (kintlévőség, DSO, beszedés, áfabontás, tételek) akkor is kell az Agent-lekérés. A validálás elutasítja a specet, ha A betűs mérték mellett `sources.agent.required` hamis.

Alapértelmezések:

| Kulcs | Érték |
|---|---|
| period.grain | month |
| period.basis | kelt |
| period.offset | previous_full_month |
| period.fiscal_year_start_month | 1 |
| period.as_of | period_end |
| period.history_months | 13 (kell az előző évi összehasonlításhoz) |
| period.storno_attribution | issue_month |
| sources.agent | {required: true} |
| sources.nav_digest | {required: false} |
| sources.fokonyvi_csv | {required: false, path: "data/drops/fokonyvi_{period}.csv"} |
| sources.afalista | {required: false, path: "data/drops/afalista_{period}.xlsx"} |
| sources.max_age_days | 3 |
| sources.cash_card_autopaid | true |

Leképezés: havi -> `month` + `previous_full_month`; folyó hónap -> `month` + `current_month_to_date`; negyedév -> `quarter` + `previous_full_quarter`; hét -> `week` + `previous_full_week`; egyedi -> `custom` + `{start, end}` (kérdezd meg a két dátumot).

Tárold: `period.*`, `sources.*`.

## 3. kör: populáció és szűrők

Kérdések:

1. Mely ügyfelek? Opciók: "mindenki" | "csak ezek: ..." (minta, például `Kft*`) | "mindenki, kivéve: ..."
2. Mely számlaszám-előtagok? Opciók a `status` kimenetéből (például `SZLA`, `E-SZLA`, `DB`), plusz "mind". A díjbekérő előtag csak akkor, ha a felhasználó kéri.
3. Mely bizonylattípusok és devizák? Opciók: "számla + helyesbítő + sztornó, minden deviza (alapeset)" | "csak számla" | "csak HUF" | "csak EUR"
4. Legyen alsó nettó összeghatár? Opciók: "nincs" | "igen: ... Ft"

Alapértelmezések:

| Kulcs | Érték |
|---|---|
| filters.customers | {include: ["*"], exclude: []} |
| filters.invoice_prefixes | [] (mind) |
| filters.currencies | [] (mind) |
| filters.vat_rates | [] (mind) |
| filters.doc_types | [invoice, modifier, storno] |
| filters.exclude_proforma | true |
| filters.min_net_huf | 0 |
| dimensions | [month, customer, vat_rate] |

Dimenziók: ne kérdezd külön. `product` akkor kerül be, ha a 4. körben termékbontást választ; `currency`, ha devizás mértéket; `payment_method`, ha fizetési mód szerinti megoszlást.

Tárold: `filters.*`, `dimensions`.

## 4. kör: mértékek, küszöbök, kivételek

Első kérdés: "Melyik számok kellenek? Az alapeset a havi árbevétel és kintlévőség riport készlete; vedd ki, amit nem kérsz, és add hozzá, ami hiányzik." Mutasd a csoportokat a forrásbetűvel:

| Csoport | Id | Megnevezés | Forrás | Alapesetben |
|---|---|---|---|---|
| Árbevétel | rev_net | Nettó árbevétel | D | igen |
| Árbevétel | rev_gross | Bruttó árbevétel | D | igen |
| Árbevétel | inv_count | Számlák száma | D | igen |
| Árbevétel | avg_inv | Átlagos számlaérték | D | igen |
| Árbevétel | rev_net_cust | Nettó árbevétel vevőnként | D | igen |
| Árbevétel | rev_net_prod | Nettó árbevétel termékenként | A | nem |
| Árbevétel | rev_net_vat | Nettó árbevétel ÁFA-kulcsonként | A | igen |
| Árbevétel | rev_net_cur | Nettó árbevétel devizánként | D | nem |
| Árbevétel | top_n_share | Top-N vevő részesedés | D | nem |
| Ügyfelek | cust_active | Aktív vevők | D | igen |
| Ügyfelek | cust_new | Új vevők | D | igen |
| Ügyfelek | cust_returning | Visszatérő vevők | D | nem |
| Ügyfelek | cust_churned | Elvesztett vevők | D | nem |
| Kintlévőség | ar_balance | Kintlévőség | A | igen |
| Kintlévőség | ar_aging | Korosított kintlévőség | A | igen |
| Kintlévőség | overdue_amt | Lejárt kintlévőség | A | igen |
| Kintlévőség | overdue_cnt | Lejárt számlák száma | A | nem |
| Kintlévőség | dso | DSO | A | igen |
| Kintlévőség | cash_in | Beérkezett pénz | A | igen |
| Kintlévőség | coll_rate | Beszedési arány | A | igen |
| Kintlévőség | ontime_rate | Határidőre fizetett arány | A | nem |
| Kintlévőség | eur_open | Nyitott EUR követelés | A | nem |
| ÁFA | vat_by_rate | Fizetendő ÁFA kulcsonként | A | igen |
| ÁFA | vat_total | ÁFA összesen | D | nem |
| Minőség | storno_rate | Sztornó arány | D | igen |
| Minőség | modifier_rate | Helyesbítő arány | D | nem |
| Minőség | einv_share | E-számla arány | A | nem |
| Minőség | pm_mix | Fizetési mód megoszlás | D | nem |
| Minőség | eur_share | EUR kitettség | D | nem |
| Minőség | fx_dev | Árfolyam eltérés | A | nem |

Második kérdés: küszöbök. "Hol szóljon a riport? Az alapeset:"

| Mérték | warn | critical | direction | unit |
|---|---|---|---|---|
| overdue_amt | 2 000 000 | 5 000 000 | above | abs |
| dso | 45 | 60 | above | abs |
| storno_rate | 0.03 | 0.05 | above | pct |

Opciók: "maradjon" | "más számok: ..." | "küszöb nélkül". Csak olyan mértékre kérj küszöböt, amelyet kiválasztott.

Harmadik kérdés: kivételek. "Mely tételek kerüljenek a kivétellistára?" Az alapeset:

| id | rule | params | severity | max_rows |
|---|---|---|---|---|
| exc_overdue30 | overdue_gt_days | {days: 30} | warn | 20 |
| exc_overdue_big | overdue_gt_amount | {amount_huf: 1000000} | critical | |
| exc_storno | storno_in_period | | info | |
| exc_taxno | missing_customer_taxno | | warn | |
| exc_fx | fx_deviation | {tolerance: 0.005} | warn | |

További szabályok: `modifier_in_period`, `amount_outlier_zscore`, `duplicate_customer_name`, `unpaid_cash_invoice`. Opciók: "maradjon" | "vedd ki: ..." | "tedd hozzá: ...".

Összehasonlítások: ne kérdezd; az alapeset mértékenként a példaspec szerint (rev_net, rev_gross: mom, yoy, ytd; inv_count, cash_in: mom, yoy; avg_inv, coll_rate, storno_rate, dso: mom, avg3m; cust_active, cust_new, ar_balance, overdue_amt: mom; a bontások összehasonlítás nélkül). Formátum: huf_k a forintos, pct az arány, days a DSO, count a darabszám.

Tárold: `measures[]` (id, comparisons, format), `thresholds.<id>`, `exceptions[]`.

## 5. kör: kimenet, leszállítás, Power BI

Kérdések:

1. Hová kerüljön a kész fájl? Opciók: "OneDrive mappa: ..." (kérj teljes útvonalat, például `C:/Users/<név>/OneDrive - <Cég>/Riportok`) | "helyben: exports/"
2. Mi legyen, ha ugyanarra a hónapra már van fájl? Opciók: "azonos verziónál felülír (same_version)" | "mindig felülír (always)" | "soha (never)"
3. Kell Power BI export? Opciók: "nem" | "igen, CSV-k ide: exports/powerbi"
4. Mely adatlapok kellenek a vezetői lap mellé? Opciók: "alapeset: kivételek, számlák, vevők, mértékek, definíciók, futtatási napló" | "plusz tételek (line)" | "plusz kifizetések (payment)"

Mondd ki a kérdés szövegében: az Excel-táblák neve `tbl_<slug>_<lap>` lesz, és 1.0.0 után nem nevezhető át, mert a Power BI ezekre hivatkozik. Ha később más név kell, új tábla vagy új riport készül, a régi marad.

Alapértelmezések:

| Kulcs | Érték |
|---|---|
| output.file_pattern | "{slug}_{period}_v{version}.xlsx" |
| output.language | hu |
| output.number_profile | huf_thousands |
| output.sheets | [executive, exceptions, invoice, customer, measure, definitions, runlog] |
| output.executive.blocks | [title, tiles, variance, ar_aging, vat_summary, top_customers, exceptions, footnote] |
| output.executive.tiles | [rev_net, rev_gross, ar_balance, overdue_amt, dso, inv_count] (legfeljebb 6) |
| output.executive.variance_rows | [rev_net, rev_gross, inv_count, avg_inv, cash_in, coll_rate, storno_rate, cust_active, cust_new] (legfeljebb 9) |
| output.executive.top_n | 10 |
| output.table_prefix | tbl_<slug> |
| powerbi | {enabled: false, folder: exports/powerbi, files: [fact_invoice, fact_measure, dim_customer, dim_date]} |
| delivery.folder | a megadott mappa (Windows útvonal előre dőlő perjelekkel is jó) |
| delivery.overwrite | same_version |
| delivery.keep_n_versions | 6 |
| validation.checks | a blokkoló készlet (V01, V04, V05, V11, V15, V16) marad; V07 warn, ha Áfalista is van |

A csempéket és eltéréssorokat csak a kiválasztott mértékekből töltsd; ha egy alapértelmezett mértéket kivett, a helyét ne pótold találomra: kérdezd meg, mi kerüljön oda, vagy hagyd üresen.

Tárold: `output.*`, `powerbi.*`, `delivery.*`.

## 6. kör: előnézet és megerősítés

1. Állítsd össze a spec vázlatát YAML-ként a válaszokból és az alapértelmezésekből (szakaszonként; a `report.id` helyén `<a --new adja>`).
2. Töltsd ki a `references/executive-mockup.md` sablont: cím, a csempék címkéi a katalógusból, eltéréssorok, korosítás, ÁFA, top-N, kivételek, lábjegyzet.
3. `AskUserQuestion`: "Így jó a terv?" Opciók: "Igen, írjuk meg a specet" | "Módosítok az 1. körön" ... "Módosítok az 5. körön" (csak a releváns körök).
4. Módosítás után az előnézetet mutasd meg újra. Ne indítsd el az ügynököt megerősítés nélkül.

Tárold: a megerősített válaszkészletet; ezt kapja a report-analyst.

## 7. kör: próbafuttatás és ellenőrzés

Ez a kör nem kérdez, hanem beszámol. A SKILL.md "Build és próbafuttatás" és "7. kör" lépései:

1. report-engineer: `build.py`, tesztek, `--dry-run` az utolsó teljes hónapra.
2. report-reviewer: az `_dryrun/` xlsx ellenőrzése a spec ellen, táblázat cellahivatkozással.
3. `AskUserQuestion`: "Aktiváljuk?" Opciók: "Igen" | "Még nem, maradjon draft".

Tárold: az ítéletet és a próbafuttatás fájlútvonalát a záró üzenethez.
