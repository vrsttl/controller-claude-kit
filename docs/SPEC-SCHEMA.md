# Report spec schema (`reports/<slug>/spec.yaml`)

Maintainer reference for `scripts/report_spec.py`. Every key, default, allowed value and
Hungarian error text below is taken from the code; when the code changes, change this file in
the same commit (`report_spec.py` docstring: "Every default is documented in
docs/SPEC-SCHEMA.md; keep the two in sync"). The four example specs under
`templates/project/reports/_examples/` are the reference instances and must pass
`uv run scripts/report_spec.py --validate` (part of `tests/check.sh`).

Conventions: keys and values that a machine reads are English snake_case; every string she
reads (titles, error texts, sheet labels) is Hungarian. Validation returns one `SpecError(path,
message_hu)` per problem, never raises; `load_spec` raises `SpecLoadError` only when the file
cannot be read at all. A spec file starts with a short Hungarian comment block (what the report
is for, what its notable options mean); `--new` writes the three-line `SKELETON_HEADER`.

## File and loading

| Item | Behaviour |
|---|---|
| Location | `reports/<slug>/spec.yaml`; the folder name must equal `report.slug` |
| Loading | `load_spec(path) -> Spec`; `spec_from_dict(raw, path=None)` for in-memory specs |
| Load errors (`SpecLoadError.message_hu`) | `a spec fájl nem található: <path>`; `a spec.yaml nem értelmezhető YAML: <parser message>`; `a spec.yaml gyökere kulcs-érték párokból álló blokk kell legyen` |
| Section shape errors (collected, not raised) | `<section>: kulcs-érték párokat vár` for a non-mapping section; `filters.customers: {include, exclude} listákat vár`; `measures: a mérőszámokat listaként kell megadni`; `measures[i]: hiányzik az id mező`; `thresholds.<k>: {warn, critical, direction, unit} blokkot vár`; `exceptions: a kivételszabályokat listaként kell megadni`; `exceptions[i]: hiányzik a rule mező`; `output.executive: {blocks, tiles, variance_rows, top_n} blokkot vár`; `validation.checks: az ellenőrzéseket listaként kell megadni`; `validation.checks[i]: hiányzik az id mező` |
| Paths | `Spec.project_root` = parent of the nearest `reports/` folder above the spec (else the spec folder); `Spec.resolve_path(value)` keeps absolute paths and joins relative ones to the project root |
| Hash | `spec_hash(path)` = sha256 of the file bytes, written to the run log and the `Futtatási napló` sheet |

## Sections

### `report`

| Key | Type | Default | Rule / error text |
|---|---|---|---|
| `id` | str | `""` | `rpt_` + 8 hex chars, immutable. `rpt_ előtag és 8 hexa karakter kell (pl. rpt_3f9a1c2e)` |
| `slug` | str | `""` | `^[a-z0-9_]+$`. `csak kisbetű, számjegy és aláhúzás engedélyezett`; when loaded from a `spec.yaml`, `a slug (<slug>) nem egyezik a mappa nevével (<dir>)` |
| `title_hu` | str | `""` | required. `a magyar cím kötelező` |
| `title_en` | str | `""` | free text |
| `owner` | str | `""` | free text (e-mail in the examples) |
| `version` | str | `0.1.0` | semver `\d+.\d+.\d+`. `semver formátum kell (pl. 1.0.0)` |
| `status` | str | `draft` | `draft`, `active`, `retired`. `megengedett értékek: draft, active, retired` |
| `changelog[]` | list of `{version, date, note}` | `[]` | `{version, date, note} mezők kellenek` |

`run_reports.py --all` runs only `status: active` specs; `/report-run` refuses `draft` and `retired`.

### `period`

| Key | Type | Default | Allowed / error text |
|---|---|---|---|
| `grain` | str | `month` | `month`, `quarter`, `ytd`, `week`, `custom`. `megengedett értékek: month, quarter, ytd, week, custom` |
| `basis` | str | `kelt` | `kelt` (issue date), `teljesites` (delivery date, falls back to issue date when empty). `megengedett értékek: kelt, teljesites` |
| `offset` | str or `{start, end}` | `previous_full_month` | `previous_full_month`, `current_month_to_date`, `previous_full_quarter`, `previous_full_week`, `current_week_to_date`, or `{start: ISO, end: ISO}` (custom grain only). Errors: `egyedi időszakhoz {start, end} ISO dátumok kellenek`; `{start, end} csak custom grain mellett adható meg`; `megengedett értékek: <list> vagy {start, end}`; `custom grain mellett {start, end} kötelező` |
| `fiscal_year_start_month` | int | `1` | 1..12. `1 és 12 közötti egész szám kell` |
| `as_of` | str | `period_end` | `period_end`, `run_date` (receivables cut-off). `megengedett értékek: period_end, run_date` |
| `history_months` | int | `13` | 1..60, sparkline history. `1 és 60 közötti egész szám kell` |
| `storno_attribution` | str | `issue_month` | `issue_month`, `original_month` (storno counted in the original invoice's month). `megengedett értékek: issue_month, original_month` |

Period resolution (`report_engine.resolve_period(spec, run_date, override)`): without an
override the window comes from `grain` + `offset` relative to `run_date`; `--period` overrides
with `previous_month`, `current_month`, `previous_quarter`, `previous_week`, `ytd`, `ÉÉÉÉ-HH`,
`ÉÉÉÉ-Qn`, `ÉÉÉÉ-Whh` or `ÉÉÉÉ-HH-NN..ÉÉÉÉ-HH-NN`. Errors (`PeriodError.message_hu`, exit code
2 in `build.py` as `IDŐSZAK HIBA: ...`): `az időszak vége a kezdete előtt van`, `érvénytelen dátum
az időszakban: <token> (<detail>)`, `ismeretlen időszak: <token> (elfogadott: ...)`, `custom
időszakhoz {start, end} kell`. Labels (`Period.label`, used in file names and the run log):
month `YYYY-MM`, quarter `<fiscal year>-Qn`, week ISO `YYYY-Wnn`, ytd
`<fiscal year>-YTD<MM>`, custom `YYYY-MM-DD_YYYY-MM-DD`. Comparison windows: prior = one grain unit back, prior year = 12 months
back (52 weeks for week grain), YTD = fiscal year start to period end, avg3m = the three calendar
months before the period start.

### `sources`

| Key | Type | Default | Meaning / error text |
|---|---|---|---|
| `agent` | `{required, path}` | `{required: true}` | Agent fetch (lines, VAT split, payments). `A` measures need it |
| `nav_digest` | `{required, path}` | `{required: false}` | NAV digest; enables V03 and V06 |
| `fokonyvi_csv` | `{required, path}` | `{required: false, path: "data/drops/fokonyvi_{period}.csv"}` | Főkönyvi export in staging; V08 fails when required and absent |
| `afalista` | `{required, path}` | `{required: false, path: "data/drops/afalista_{period}.xlsx"}` | Áfalista in staging; V07 fails when required and absent |
| `max_age_days` | int | `3` | V02: last successful sync may be this many days older than `run_date`. `nemnegatív egész szám kell` |
| `cash_card_autopaid` | bool | `true` | cash and card invoices count as paid (`paid_huf = gross_huf`). `igaz/hamis érték kell` |

Each source block: `required` must be bool (`sources.<name>.required: igaz/hamis érték kell`);
a non-mapping block reports `sources.<name>: {required, path} blokkot vár`.

### `filters`

| Key | Type | Default | Meaning / error text |
|---|---|---|---|
| `customers.include` | list of globs | `["*"]` | case-insensitive `fnmatch` on customer name or key. `filters.customers_include: szöveges elemek listáját várja` |
| `customers.exclude` | list of globs | `[]` | same matching; exclusion wins |
| `invoice_prefixes` | list | `[]` | invoice number prefixes (`startswith`) |
| `currencies` | list | `[]` | ISO codes |
| `vat_rates` | list | `[]` | VAT keys (`27`, `5`, `AAM`, ...); filters lines and VAT split, and switches V15 to customer-only tie-out |
| `doc_types` | list | `[invoice, modifier, storno]` | subset of `invoice, modifier, storno, proforma`, non-empty. `megengedett értékek: invoice, modifier, storno, proforma` |
| `exclude_proforma` | bool | `true` | `igaz/hamis érték kell` |
| `min_net_huf` | number | `0` | keeps rows with `abs(net_huf) >= value`. `nemnegatív szám kell` |

The applied filters are listed in Hungarian on the `Definíciók` sheet (`Frames.filters_hu`).

### `dimensions`

List, default `[month, customer, vat_rate]`, allowed `month, customer, product, vat_rate,
currency, payment_method`. Error `ismeretlen dimenzió: <values>`. A dimensional measure whose
`dim` is missing here is refused (see `measures`).

### `measures[]`

Each item is a mapping (a bare string `id` is accepted and expanded to `{id}`).

| Key | Type | Default | Rule / error text |
|---|---|---|---|
| `id` | str | required | catalogue id (`docs/MEASURES.md`) or `custom:<slug>`. `ismeretlen mérőszám: <id>`; `custom:<slug> alakban, csak kisbetű, számjegy, aláhúzás`; `a(z) <slug> név foglalt a katalógusban`; `a(z) <id> Agent-adatot igényel, de sources.agent.required hamis`; `a(z) <id> a(z) <dim> dimenziót igényli, vedd fel a dimensions listába` |
| `params` | mapping | `{}` | `kulcs-érték párokat vár`. Only `top_n_share` reads `n` |
| `comparisons` | list or absent | catalogue default | subset of `mom, yoy, ytd, avg3m`. `megengedett értékek: mom, yoy, ytd, avg3m` |
| `format` | str or absent | catalogue default | `huf_k, huf, eur, pct, days, count`. `megengedett értékek: ...` |
| `formula` | str | none | required for `custom:` (`egyedi mérőszámhoz formula kötelező`), forbidden otherwise (`katalógusbeli mérőszámnál nem adható meg formula`); grammar errors are reported under `measures[i].formula` (list in `docs/MEASURES.md`) |

At least one measure is required (`legalább egy mérőszám kell`). Measure key: `id` when
`params` is empty, else `id[k=v,...]` with sorted params (`top_n_share[n=5]`). Keys must be
unique (`ismétlődő mérőszám: <key>`). References from `thresholds`, `output.executive.tiles`
and `variance_rows` may use the bracket key, or the bare id when that id occurs once
(`Spec.measure_keys()`).

### `thresholds.<measure key>`

| Key | Type | Default | Rule / error text |
|---|---|---|---|
| `warn` | number | none | at least one of `warn`/`critical` (`legalább warn vagy critical érték kell`); `szám kell` |
| `critical` | number | none | same |
| `direction` | str | `above` | `above` (`>=` triggers), `below` (`<=`). `megengedett értékek: above, below` |
| `unit` | str | `abs` | `abs`, `pct`, `pct_of:<measure key>`. `megengedett értékek: abs, pct, pct_of:<id>`; `pct_of hivatkozás ismeretlen mérőszámra: <ref>` |

Unknown key: `a küszöb olyan mérőszámra hivatkozik, ami nincs a measures listában`. Levels
colour the tile and variance cells (amber `warn`, red `critical`) and feed `fact_measure.status`.

### `exceptions[]`

| Key | Type | Default | Rule / error text |
|---|---|---|---|
| `id` | str | `exc_<rule>` | `^[a-z0-9_]+$`, unique. `csak kisbetű, számjegy és aláhúzás engedélyezett`; `ismétlődő kivétel-azonosító: <id>` |
| `rule` | str | required | see table below. `ismeretlen szabály: <rule>` |
| `params` | mapping | `{}` | rule specific |
| `severity` | str | `warn` | `info`, `warn`, `critical`. `megengedett értékek: info, warn, critical` |
| `max_rows` | int | `50` | rows kept per rule on the `Kivételek` sheet. `pozitív egész szám kell` |

| Rule | Params (default) | Row |
|---|---|---|
| `overdue_gt_days` | `days` (required: `napok száma kell`) | open chains with `days_overdue > days` as of `as_of` |
| `overdue_gt_amount` | `amount_huf` (required: `HUF összeg kell`) | open overdue chains with `open_huf > amount_huf` |
| `storno_in_period` | none | storno documents in the period, note `eredeti: <chain_root>` |
| `modifier_in_period` | none | modifier documents in the period |
| `amount_outlier_zscore` | `z` (3.0), `window_months` (12) | invoices whose net z-score over the trailing window exceeds `z` |
| `missing_customer_taxno` | `only_domestic_companies` (false) | invoices of non-private customers without a tax number |
| `fx_deviation` | `tolerance` (0.005) | non-HUF documents where `net_huf / (net_amount * fx_rate_invoice)` deviates more than `tolerance` from 1 |
| `duplicate_customer_name` | none | customer keys sharing a normalised name (legal-form suffixes stripped) |
| `unpaid_cash_invoice` | none | cash invoices whose derived status is `unpaid`/`partial` before auto-pay |

Rows are sorted by severity (`critical`, `warn`, `info`) then absolute amount; the executive
block shows at most 12 (`report_excel.MAX_EXEC_EXCEPTIONS`) with a pointer to the full sheet.

### `output`

| Key | Type | Default | Rule / error text |
|---|---|---|---|
| `file_pattern` | str | `{slug}_{period}_v{version}.xlsx` | must end in `.xlsx` and contain a `{slug}`, `{period}`, `{version}` or `{run_date}` token. `xlsx végződés és legalább egy {slug}/{period}/{version}/{run_date} token kell` |
| `language` | str | `hu` | `hu`, `en` (sheet names and labels). `megengedett értékek: hu, en` |
| `number_profile` | str | `huf_thousands` | `huf_thousands` (`#,##0," e Ft"`), `huf_full` (`#,##0" Ft"`). `megengedett értékek: huf_thousands, huf_full` |
| `sheets` | list | `[executive, exceptions, invoice, customer, measure, definitions, runlog]` | subset of `executive, exceptions, invoice, line, payment, customer, measure, definitions, runlog`, no repeats, `executive` mandatory. `ismeretlen lap: ...`; `ismétlődő lap`; `a vezetői összefoglaló (executive) lap kötelező` |
| `executive.blocks` | list | all eight in order | subset of `title, tiles, variance, ar_aging, vat_summary, top_customers, exceptions, footnote`; order matters. `ismeretlen blokk: ...` |
| `executive.tiles` | list of measure keys | `[]` | at most 6. `legfeljebb 6 csempe engedélyezett`; `ismeretlen mérőszám-hivatkozás: <ref>` |
| `executive.variance_rows` | list of measure keys | `[]` | at most 9. `legfeljebb 9 sor engedélyezett`; `ismeretlen mérőszám-hivatkozás: <ref>` |
| `executive.top_n` | int | `10` | `pozitív egész szám kell` |
| `table_prefix` | str | `tbl_<slug>` | `^tbl_[a-z0-9_]+$`. `tbl_ előtag, csak kisbetű, számjegy, aláhúzás` |

Sheet names (`report_excel.SHEET_NAMES`): hu `Vezetői összefoglaló`, `Kivételek`, `Számlák`,
`Tételek`, `Kifizetések`, `Ügyfelek`, `Mutatók`, `Definíciók`, `Futtatási napló`; en
`Executive`, `Exceptions`, `Invoices`, `Lines`, `Payments`, `Customers`, `Measures`,
`Definitions`, `Run log`. A hidden `_series` sheet carries sparkline data. Excel Table names are
`<table_prefix>_<entity>` for `exceptions, invoice, line, payment, customer, measure`.

### `powerbi`

| Key | Type | Default | Rule / error text |
|---|---|---|---|
| `enabled` | bool | `false` | `igaz/hamis érték kell` |
| `folder` | str | `exports/powerbi` | relative to the project root or absolute; required when enabled (`Power BI export mappát kell megadni`) |
| `files` | list | `[fact_invoice, fact_measure, dim_customer, dim_date]` | subset of `fact_invoice, fact_invoice_line, fact_payment, fact_measure, dim_customer, dim_date`. `ismeretlen fájl: ...` |

CSV export is UTF-8 with BOM, comma separated, `%.2f` floats, one file per entity, overwritten
in place. `build.py --powerbi/--no-powerbi` overrides `enabled`; `--dry-run` writes under
`_dryrun/powerbi/`.

### `delivery`

| Key | Type | Default | Rule / error text |
|---|---|---|---|
| `folder` | str | `exports` | relative to the project root or absolute. `kézbesítési mappa kötelező` |
| `overwrite` | str | `same_version` | `never` (existing target gives outcome `exists`), `same_version` (overwrites a file of the same version; an existing file without this version in its name is kept and the new one gets a `_v<version>` suffix), `always`. `megengedett értékek: never, same_version, always` |
| `keep_n_versions` | int | `6` | older files matching `file_pattern` are pruned after delivery. `pozitív egész szám kell` |

### `validation`

| Key | Type | Default | Rule / error text |
|---|---|---|---|
| `checks[]` | list of `{id, tolerance, severity, blocks_delivery}` | all sixteen defaults | listed items override the default for that id; unlisted ids keep their defaults. `V01 és V16 közötti azonosító kell`; `nemnegatív szám kell`; `megengedett értékek: fail, warn`; `igaz/hamis érték kell` |
| `min_rows` | int (or `{invoice: n}`) | `1` | V14 minimum document count. `nemnegatív egész szám kell` |

Tolerance semantics: a delta passes when `abs(delta) < tolerance`, so `tolerance: 1` rejects a
1 HUF difference and `0` means exact.

| Id | title_hu | Compares | Default tolerance | Default severity | Blocks by default | Skipped when |
|---|---|---|---|---|---|---|
| V01 | Spec értelmezhető | `validate(spec)` is empty | 0 | fail | yes | never |
| V02 | Forrás frissesség | last successful `sync_log` row per required source covers the period and is at most `max_age_days` old | 0 | fail | no | no required sync source |
| V03 | NAV digest darabszám = gyorsítótár | NAV digest count vs cached invoices | 0 | fail | no | `nav_digest` not required |
| V04 | Tételsorok összege = fejléc | line net/VAT sums vs header per document | 1 | fail | yes | no lines |
| V05 | ÁFA-bontás összege = fejléc | VAT-split net/VAT sums vs header per document | 1 | fail | yes | no VAT split |
| V06 | NAV HUF vs összeg × árfolyam | stored HUF net vs amount × rate on non-HUF documents | 0.005 | warn | no | `nav_digest` not required |
| V07 | Áfalista egyeztetés | staged Áfalista rows vs VAT split per invoice and rate | 1 | warn | no | no staged rows (fails instead when `afalista.required`) |
| V08 | Főkönyvi CSV fizetettség egyeztetés | staged CSV payment status vs derived status | 0 | warn | no | no staged rows (fails when `fokonyvi_csv.required`) |
| V09 | Nincs vevő nélküli számla | every invoice has a named customer | 0 | fail | no | never |
| V10 | Lezárt időszak stabilitása | `rev_net` and `inv_count` vs the last run log entry for the same period | 1 (fixed) | warn | no | first run for the period |
| V11 | Számlalánc integritás | every modifier/storno has its chain root | 0 | fail | yes | never |
| V12 | Árfolyam ésszerűség | each non-HUF rate within `median / factor .. median * factor` | 2 (factor) | warn | no | no non-HUF documents |
| V13 | Duplikált számlák | same customer, gross and issue date | 0 | warn | no | never |
| V14 | Minimális sorszám | document count >= `min_rows` | 0 | fail | no | never |
| V15 | Belső egyeztetés (vevő = ÁFA-kulcs = összesen) | total net = sum by customer = sum by VAT rate | 1 | fail | yes | never |
| V16 | Kimeneti fájl épsége | workbook opens, expected sheets and tables exist, at most 6 tiles, no merged cells outside the title row, at most 12 executive exceptions | 0 | fail | yes | workbook not written yet |

`run_checks()` always returns the sixteen results in order; `status` is `ok`, `warn`, `fail` or
`skipped`, `blocking` is `blocks_delivery` from the spec. A failed blocking check moves the
staging file to `<delivery.folder>/_rejected/<name>_FAILED.xlsx` and exits 1.

## Editing rules (`diff_specs(old, new)`, `/report-edit`)

| Refusal | Text |
|---|---|
| id changed | `report.id: a riport azonosítója nem változtatható` |
| table prefix renamed at version >= 1.0.0 | `output.table_prefix: 1.0.0 után a táblák előtagja nem nevezhető át (Power BI hivatkozik rá), új riportot hozz létre` |
| a referenced measure removed | `measures: a(z) <ref> mérőszám hiányzik, de csempe, eltéréstábla-sor vagy küszöb hivatkozik rá` |
| a table sheet removed at version >= 1.0.0 | `output.sheets: a(z) <prefix>_<entity> tábla 1.0.0 után nem távolítható el` |

`bump_spec(path, "minor"|"patch", note)` rewrites `report.version` and appends
`{version, date, note}` to `changelog`; from `0.1.0`, `minor` gives `0.2.0` and `patch` gives
`0.1.1`. Errors: `a verzióemelés csak minor vagy patch lehet`, `a jelenlegi verzió nem semver:
<v>`.

## CLI (`uv run scripts/report_spec.py ...`)

| Command | Output | Exit |
|---|---|---|
| `--validate PATH...` | `OK: <path>` or one `<path>: <key path>: <message>` line per error | 0 all valid, 1 otherwise |
| `--catalogue` | table `id  megnevezés  forrás  formátum` from `report_engine.MEASURES` (including `measures_local.py` entries) | 0 |
| `--diff OLD NEW` | refusal lines or `OK: a módosítás engedélyezett` | 0 allowed, 1 refused |
| `--bump PATH minor\|patch --note TEXT` | `<path>: verzió <new>`; `a --note szöveg kötelező a verzióemeléshez` without a note | 0 / 1 |
| `--new SLUG --title-hu TEXT [--out PATH]` | writes the skeleton (default `reports/<slug>/spec.yaml`), `létrehozva: <path>`; errors `a --title-hu cím kötelező`, `a slug csak kisbetűt, számjegyet és aláhúzást tartalmazhat`, `már létezik: <path>` | 0 / 1 |

Skeleton defaults (`skeleton(slug, title_hu)`): fresh `rpt_<8hex>` id, version `0.1.0`, status
`draft`, changelog note `vázlat`, all section defaults above, measures `rev_net` (mom, yoy, ytd,
huf_k) and `inv_count` (mom, yoy, count), tiles and variance rows `[rev_net, inv_count]`, the
sixteen checks written out explicitly.

## Build contract (`reports/<slug>/build.py`, copied from `scripts/build_template.py`)

Flags: `--period` (override token, see `period`), `--out DIR` (default `.staging/` next to the
spec, `_dryrun/` with `--dry-run`), `--db PATH` (default `RIPORTOK_DIR/data/invoices.db`),
`--dry-run`, `--no-deliver`, `--powerbi/--no-powerbi`, `--run-date YYYY-MM-DD`, `--json`.

Exit codes: 0 `delivered`, `dry_run`, `not_delivered`; 1 `rejected`, `pending`, `exists`; 2 spec
or usage error (`SPEC HIBA: ...`, `IDŐSZAK HIBA: ...`, `ADATBÁZIS HIBA: nem található: ...`).

`--json` prints, after the Hungarian preview lines, one object with keys `slug, period,
version, outcome, outcome_hu, delivered_path, staging_path, checks[], row_counts, totals,
previous_totals, powerbi_files, exit_code`. `totals` = `{rev_net, inv_count, ar_balance,
overdue_amt}` (HUF, receivables as of `as_of`); `previous_totals` = the `totals` of the last
`runlog.jsonl` entry for the same period, or `null`. `checks[]` items carry `id, title_hu,
status, detail_hu, blocking`. `outcome_hu` values: `kézbesítve`, `elutasítva`, `függőben (a
célfájl zárolva)`, `nem írható felül (a célfájl létezik)`, `próbafuttatás`, `nem kézbesítve
(--no-deliver)`.

Run log: `reports/<slug>/runlog.jsonl`, one JSON line per delivery attempt (not for dry runs)
with `period, run_ts, spec_version, spec_hash, kit_version, row_counts, totals, checks, outcome,
delivered_path`. `run_reports.py --list` shows the last line per report.
