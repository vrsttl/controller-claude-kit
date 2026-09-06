# Measure catalogue (`scripts/report_engine.py`)

Maintainer reference for `MEASURES`, the dictionary of `MeasureDef` entries the spec's
`measures[].id` values point at. The Hungarian labels and formula sentences below are the
ones `uv run scripts/report_spec.py --catalogue` prints and the `Definíciók` sheet shows;
the table is generated from the code, so a change in `report_engine.py` must be mirrored here
(`tests/test_report_engine.py::test_every_catalogue_measure_returns_a_number` pins the count
at 30 shipped ids).

## How a measure is evaluated

- Every measure is a function `fn(ctx, start, end, params)` over the loaded `Frames`
  (`ctx.frames`), the spec (`ctx.spec`) and the resolved `Period` (`ctx.period`). `ctx.docs()`,
  `ctx.invoices()`, `ctx.ar()`, `ctx.rev_by_customer()` and `ctx.active_customers()` are
  memoised window helpers.
- `kind: flow` measures are evaluated on the window `start..end` (the period, its prior window,
  the prior-year window, YTD windows and the 13-month history for sparklines).
- `kind: snapshot` measures ignore `start` and read the state as of `end` (the AR family, DSO,
  `eur_open`). Their comparisons shift `end` back by whole grain units.
- Measures with a `dim` return a `dict[dim_value, float]`; the engine writes one row per
  dimension value plus a `total` row. `dim: bucket` (AR aging) does not need to be listed in
  `dimensions`; every other `dim` must be (validation error
  `a(z) <id> a(z) <dim> dimenziót igényli, vedd fel a dimensions listába`).
- `source`: `D` = computable from NAV digest header data alone, `A` = needs the Agent fetch
  (lines, VAT split, payments, e-invoice flag). `A` measures require `sources.agent.required:
  true` (validation error `a(z) <id> Agent-adatot igényel, de sources.agent.required hamis`).
- `default_format` maps to an Excel number format (`report_excel.NUMBER_FORMATS`): `huf_k`
  `#,##0," e Ft"`, `huf` `#,##0" Ft"`, `eur` `#,##0.00" €"`, `pct` `0.0%`, `days` `0" nap"`,
  `count` `#,##0" db"`. Under `output.number_profile: huf_full` every `huf_k` becomes `huf`.
- `default_comparisons` is used when the spec's measure omits `comparisons`. Meaning:
  `mom` = value / prior window - 1, `yoy` = value / same window one year earlier - 1,
  `ytd` = fiscal year to date (plus prior-year YTD), `avg3m` = mean of the three calendar
  months before the period start. Division by zero or a missing operand yields an empty cell.
- `params`: only `top_n_share` reads one (`n`, default 5). Any other `params` block is accepted
  and only changes the measure key (`id[k=v,...]`), see `docs/SPEC-SCHEMA.md`.
- Thresholds (`thresholds.<key>`) are applied to the `total` value: `direction: above` marks
  `warn` when value >= warn and `critical` when value >= critical, `below` uses `<=`.
  `unit: pct_of:<other_key>` compares value / other value instead.

## Catalogue

| id | label_hu | label_en | source | kind | dim | format | default comparisons | source_fields |
|---|---|---|---|---|---|---|---|---|
| `rev_net` | Nettó árbevétel | Net revenue | D | flow |  | `huf_k` | mom, yoy, ytd | `invoice.net_huf` |
| `rev_net_cust` | Nettó árbevétel vevőnként | Net revenue by customer | D | flow | customer | `huf_k` | mom, yoy | `invoice.net_huf, customer.name` |
| `rev_net_prod` | Nettó árbevétel termékenként | Net revenue by product | A | flow | product | `huf_k` | mom, yoy | `invoice_line.net, invoice.fx_rate_invoice` |
| `rev_net_vat` | Nettó árbevétel ÁFA-kulcsonként | Net revenue by VAT rate | A | flow | vat_rate | `huf_k` | mom, yoy | `invoice_vat.net_huf` |
| `rev_net_cur` | Nettó árbevétel devizánként | Net revenue by currency | D | flow | currency | `huf_k` | mom, yoy | `invoice.net_huf, invoice.currency` |
| `rev_gross` | Bruttó árbevétel | Gross revenue | D | flow |  | `huf_k` | mom, yoy, ytd | `invoice.gross_huf` |
| `vat_by_rate` | Fizetendő ÁFA kulcsonként | VAT payable by rate | A | flow | vat_rate | `huf_k` | mom, yoy | `invoice_vat.vat_huf` |
| `vat_total` | ÁFA összesen | Total VAT | D | flow |  | `huf_k` | mom, yoy | `invoice.vat_huf` |
| `inv_count` | Számlák száma | Invoice count | D | flow |  | `count` | mom, yoy, avg3m | `invoice.doc_type` |
| `avg_inv` | Átlagos számlaérték | Average invoice value | D | flow |  | `huf_k` | mom, avg3m | `invoice.net_huf` |
| `storno_rate` | Sztornó arány | Storno rate | D | flow |  | `pct` | mom, avg3m | `invoice.doc_type` |
| `modifier_rate` | Helyesbítő arány | Modifier rate | D | flow |  | `pct` | mom, avg3m | `invoice.doc_type` |
| `top_n_share` | Top-N vevő részesedés | Top-N customer share | D | flow |  | `pct` | mom, yoy | `invoice.net_huf, customer.name` |
| `cust_active` | Aktív vevők | Active customers | D | flow |  | `count` | mom, yoy | `invoice.customer_key` |
| `cust_new` | Új vevők | New customers | D | flow |  | `count` | mom, yoy | `customer.first_invoice_date` |
| `cust_returning` | Visszatérő vevők | Returning customers | D | flow |  | `count` | mom, yoy | `invoice.customer_key, customer.first_invoice_date` |
| `cust_churned` | Elvesztett vevők | Churned customers | D | flow |  | `count` | mom | `invoice.customer_key` |
| `ar_balance` | Kintlévőség | AR balance | A | snapshot |  | `huf_k` | mom | `invoice.gross_huf, payment.amount, invoice.paid_huf` |
| `ar_aging` | Korosított kintlévőség | AR aging | A | snapshot | bucket | `huf_k` | mom | `invoice.due_date, payment.pay_date` |
| `overdue_amt` | Lejárt kintlévőség | Overdue amount | A | snapshot |  | `huf_k` | mom | `invoice.due_date, payment.pay_date` |
| `overdue_cnt` | Lejárt számlák száma | Overdue count | A | snapshot |  | `count` | mom | `invoice.due_date` |
| `dso` | DSO (vevőállomány forgási ideje) | Days sales outstanding | A | snapshot |  | `days` | mom, avg3m | `invoice.gross_huf, payment.amount, invoice.net_huf` |
| `cash_in` | Beérkezett pénz | Cash collected | A | flow |  | `huf_k` | mom, yoy, ytd | `payment.amount, payment.pay_date, invoice.fx_rate_invoice` |
| `coll_rate` | Beszedési arány | Collection rate | A | flow |  | `pct` | mom, avg3m | `payment.amount, invoice.gross_huf` |
| `ontime_rate` | Határidőre fizetett arány | Paid-on-time share | A | flow |  | `pct` | mom, avg3m | `invoice.due_date, payment.pay_date` |
| `einv_share` | E-számla arány | E-invoice share | A | flow |  | `pct` | mom | `invoice.is_einvoice` |
| `pm_mix` | Fizetési mód megoszlás | Payment method mix | D | flow | payment_method | `pct` | mom | `invoice.payment_method, invoice.net_huf` |
| `eur_share` | EUR kitettség | FX exposure share | D | flow |  | `pct` | mom, yoy | `invoice.currency, invoice.net_huf` |
| `eur_open` | Nyitott EUR követelés | Open EUR receivables | A | snapshot |  | `huf_k` | mom | `invoice.currency, invoice.gross_huf, payment.amount` |
| `fx_dev` | Árfolyam eltérés | FX rate deviation | A | flow |  | `pct` | (none) | `invoice.net_huf, invoice.net_amount, invoice.fx_rate_invoice` |

`ar_aging` buckets (`AGING_BUCKETS`): `not_due`, `1_30`, `31_60`, `61_90`, `90_plus`, labelled
`Nem lejárt`, `1-30 nap`, `31-60 nap`, `61-90 nap`, `90+ nap` (English: `Not due`, `1-30 days`,
`31-60 days`, `61-90 days`, `90+ days`). Aging uses the chain root's due date; open amount per
chain = signed gross HUF of the chain's documents issued up to `as_of` minus payments booked up
to `as_of` (documents without payment rows fall back to their stored `paid_huf`).

## Formula in words (`formula_words`, shown on the `Definíciók` sheet)

- `rev_net`: A szűrt bizonylatok (számla, helyesbítő, sztornó) előjeles nettó HUF összege az időszak alapdátuma szerint.
- `rev_net_cust`: Nettó árbevétel vevőnév szerint csoportosítva.
- `rev_net_prod`: Tételsorok nettó értéke a számla árfolyamával forintosítva, terméknév szerint.
- `rev_net_vat`: Az ÁFA-bontás nettó HUF összege kulcsonként.
- `rev_net_cur`: Nettó árbevétel HUF-ban, a számla devizaneme szerint csoportosítva.
- `rev_gross`: A szűrt bizonylatok előjeles bruttó HUF összege.
- `vat_by_rate`: Az ÁFA-bontás ÁFA HUF összege kulcsonként, az időszak alapdátuma (kelt vagy teljesítés) szerint.
- `vat_total`: A szűrt bizonylatok előjeles ÁFA HUF összege.
- `inv_count`: A számla típusú bizonylatok darabszáma (helyesbítő és sztornó nélkül).
- `avg_inv`: Nettó árbevétel osztva a számlák számával.
- `storno_rate`: Sztornó bizonylatok száma osztva a számlák számával az időszakban.
- `modifier_rate`: Helyesbítő bizonylatok száma osztva a számlák számával az időszakban.
- `top_n_share`: A legnagyobb N (params.n, alapból 5) vevő nettó árbevétele osztva a teljes nettó árbevétellel.
- `cust_active`: Azon vevők száma, akiknek az időszakban pozitív a nettó árbevétele.
- `cust_new`: Azon vevők száma, akiknek az első számlája az időszakba esik (customer.first_invoice_date, hiányában a legkorábbi számla kelte).
- `cust_returning`: Aktív vevők száma az új vevők nélkül.
- `cust_churned`: Azon vevők száma, akiknek az időszak végét megelőző 12 hónapban (a záró 3 hónap előtt) volt árbevétele, de a záró 3 hónapban nem.
- `ar_balance`: Nyitott követelés a fordulónapon: a számlaláncok bruttó HUF összege mínusz a fordulónapig könyvelt kifizetések (kifizetés-sor nélküli bizonylatnál a tárolt fizetett összeg).
- `ar_aging`: Nyitott követelés a lánc eredeti számlájának fizetési határideje szerinti sávokban: nem lejárt, 1-30, 31-60, 61-90, 90+ nap.
- `overdue_amt`: Nyitott követelés, ahol a fizetési határidő a fordulónap előtt van.
- `overdue_cnt`: Lejárt, nyitott számlaláncok darabszáma a fordulónapon.
- `dso`: Kintlévőség osztva a fordulónapot záró 3 naptári hónap napi átlagos nettó árbevételével (3 havi nettó árbevétel / a 3 hónap napjainak száma).
- `cash_in`: Az időszakban könyvelt kifizetések összege a számla árfolyamával forintosítva.
- `coll_rate`: Beérkezett pénz osztva az időszakban kiállított bruttó árbevétellel.
- `ontime_rate`: Az időszakban esedékes, kifizetett számlák közül azok aránya, amelyek utolsó kifizetése legkésőbb a fizetési határidőn történt (kifizetés-sor nélküli, fizetettnek jelölt számla határidőben fizetettnek számít).
- `einv_share`: E-számlaként kiállított számlák száma osztva a számlák számával.
- `pm_mix`: Nettó árbevétel részesedése fizetési módonként.
- `eur_share`: Nem HUF devizanemű bizonylatok nettó HUF árbevétele osztva a teljes nettó árbevétellel.
- `eur_open`: EUR devizanemű számlaláncok nyitott követelése HUF-ban a fordulónapon.
- `fx_dev`: A nem HUF bizonylatoknál a tárolt HUF nettó és a nettó × számlaárfolyam hányadosának legnagyobb abszolút eltérése 1-től az időszakban.

## Custom measures (`custom:<slug>`)

A spec may define `{id: custom:<slug>, formula: "..."}`. The formula is parsed with
`report_spec.parse_formula` and may only contain catalogue ids (bare names, never bracket
keys), numeric constants, `+ - * /`, unary sign, parentheses and `prior(<id>, n)` (the same
catalogue measure `n` grain units earlier). Dimensional measures inside a formula evaluate
to empty. Error texts: `a formula üres`, `a formula nem értelmezhető: ...`,
`csak + - * / műveletek engedélyezettek`, `csak előjel (+/-) engedélyezett egyoperandusú
műveletként`, `csak számkonstansok engedélyezettek`, `ismeretlen mérőszám a formulában: <név>`,
`csak a prior(id, n) függvény hívható`, `prior(id, n) pontosan két argumentumot vár`,
`prior() első argumentuma katalógusbeli mérőszám kell legyen`, `prior() második argumentuma
pozitív egész szám kell legyen`, `nem engedélyezett elem a formulában: <típus>`. A custom slug
that collides with a catalogue id is refused (`a(z) <slug> név foglalt a katalógusban`).

## `MeasureDef` fields

| Field | Type | Meaning |
|---|---|---|
| `id` | str | catalogue id, equal to the dictionary key |
| `label_hu`, `label_en` | str | labels for tiles, tables and the definitions sheet |
| `formula_words` | str | one Hungarian sentence ending with a period |
| `source` | `D` or `A` | digest-only or Agent-dependent |
| `default_format` | one of `FORMATS` | number format when the spec omits `format` |
| `fn` | callable | `fn(ctx, start, end, params) -> float | None | dict[str, float]` |
| `kind` | `flow` (default) or `snapshot` | window vs as-of evaluation |
| `dim` | str or None | dimension name for dict-valued measures |
| `default_comparisons` | tuple | used when the spec omits `comparisons` |
| `source_fields` | str | table.column list for the definitions sheet |

## Helyi bővítés (`measures_local.py`)

The installer refreshes `Riportok/scripts/` from the manifest on every update, so a measure
added directly to `MEASURES` would be lost. Local measures live in a separate file that the kit
does not ship and the manifest does not list, therefore `install.ps1 -Update` never touches it:

- Path: `%USERPROFILE%\Riportok\scripts\measures_local.py` (next to `report_engine.py`; any
  `sys.path` entry works, the instantiated `build.py` puts `Riportok/scripts` first).
- Contract: the module exposes `MEASURES: dict[str, MeasureDef]`. After the catalogue is built,
  `report_engine.merge_local_measures(MEASURES)` imports the module (if present) and merges it
  in place. Local ids may add to the catalogue but never override a shipped id.
- Errors (`report_engine.LocalMeasureError`, raised at import time so `build.py` stops before
  writing anything): `a helyi mérőszám ütközik a katalógussal: <id> (measures_local.py), válassz
  másik azonosítót` on an id collision; `a helyi mérőszám nem MeasureDef, vagy az id nem egyezik
  a kulccsal: <id> (measures_local.py)` when a value is not a `MeasureDef` or its `id` differs
  from its key. A module without a `MEASURES` dict is ignored.
- Verify: `uv run scripts/report_spec.py --catalogue` lists the local id with its Hungarian
  label; `--validate` accepts a spec that references it; the `Definíciók` sheet shows it like
  any shipped measure. The `report-engineer` agent is the intended author.

Example (`measures_local.py`, a flow measure over the period window):

```python
from report_engine import MeasureDef


def m_gross_per_invoice(ctx, start, end, params):
    docs = ctx.invoices(start, end)  # invoices with basis date in start..end
    return float(docs["gross_huf"].sum() / len(docs)) if len(docs) else None


MEASURES = {
    "local_gross_per_invoice": MeasureDef(
        id="local_gross_per_invoice",
        label_hu="Bruttó érték számlánként (helyi)",
        label_en="Gross value per invoice (local)",
        formula_words="Bruttó árbevétel osztva a számlák számával.",
        source="D",
        default_format="huf_k",
        fn=m_gross_per_invoice,
    )
}
```

The function receives the same `ctx` as the shipped measures: `ctx.frames` (invoice, line,
vat, payment, customer DataFrames), `ctx.period` (the resolved `Period`, including `as_of`) and
`ctx.spec`. For a snapshot-style measure use `ctx.ar(end)` and pass `kind="snapshot"`.
`tests/test_report_engine.py` covers the merge, the collision error and the `--catalogue`
output with a temporary `measures_local.py`.
