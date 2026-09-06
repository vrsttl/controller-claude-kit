# Data layer notes (Phase 1a)

Scope: `scripts/db.py`, `scripts/agent_client.py`, `scripts/nav_client.py`, `scripts/get_secret.py`,
`scripts/szamlazz_sync.py`, `tests/conftest.py`, `tests/fixtures/*`.

This file lists every field name or behaviour that is NOT backed by a document retrieved on
2026-09-06, plus the sources that were verified. Everything marked `# ASSUMPTION` in the code
appears here. Confirm each item against a real response on her szamlazz.hu account (test mode is
enough) and delete the row once confirmed.

## Verified sources (retrieved 2026-09-06)

| Item | Source |
|---|---|
| Agent endpoint, multipart field `action-szamla_agent_xml`, request root `xmlszamlaxml`, namespace `http://www.szamlazz.hu/xmlszamlaxml`, field order `felhasznalo, jelszo, szamlaagentkulcs, szamlaszam, rendelesSzam, pdf, szamlaKulsoAzon` | `https://docs.szamlazz.hu/agent/querying_xml/xml`, `.../querying_xml/request`, `https://www.szamlazz.hu/szamla/docs/xsds/agentxml/xmlszamlaxml.xsd` |
| Response root `szamla`; `alap` children `id, szamlaszam, tipus, eszamla, kelt, telj, fizh, fizmod, fizmodunified, nyelv, devizanem, devizaarf, megjegyzes, penzforg, kata, email, teszt`; `vevo` children `id, nev, cim, email, adoszam, fokonyv`; `tetel` children `nev, mennyiseg, mennyisegiegyseg, nettoegysegar, afakulcs, netto, arresafaalap, afa, brutto, megjegyzes, fokonyv`; `osszegek/afakulcsossz`, `osszegek/totalossz`; `kifizetesek/kifizetes`; `pdf` base64 in the body | `https://docs.szamlazz.hu/agent/querying_xml/response` |
| Failure body `xmlszamlavalasz` with `sikeres`, `hibakod`, `hibauzenet`; error code 7 = unknown invoice number / order number / external id | same page |
| Error code 3 = login failure | `https://docs.szamlazz.hu/agent/basics/error-handling` |
| `kifizetes` children `datum, jogcim, osszeg, bankszamlaszam, banktranzid, devizaarf`; `afakulcsossz` children `afatipus, afakulcs, netto, afa, brutto`; `tipus` codes SZ (invoice), SS (storno), HS (modifier); `alap/hivszamlaszam`; `vevo/privatePersonIndicator`; `tetel/fokonyv` | `https://docs.szamlazz.hu/penzugyi-adatkapcsolat/kimeno-szamlak` (Financial Data Connection document, same `szamla` structure) |
| Főkönyvi adatexport: line-item grain, column meanings, `kifizetett összeg` + `kifizetés dátuma` | `https://tudastar.szamlazz.hu/gyik/fokonyvi-adatexport` |
| Áfalista: per-invoice grain with per-VAT-rate base and VAT columns, summary row, date basis by accounting mode | `https://tudastar.szamlazz.hu/gyik/afa-lista` |
| NAV `QueryInvoiceDigestRequest` / `Response`, `InvoiceDigestType` fields, `QueryInvoiceDataRequest` / `Response`, `TokenExchangeResponse`, `SoftwareType`, `SoftwareIdType` pattern `[0-9A-Z\-]{18}`, enums (`InvoiceDirectionType`, `ManageInvoiceOperationType` CREATE/MODIFY/STORNO, `PaymentMethodType`, `InvoiceAppearanceType`) | `nav-gov-hu/Online-Invoice` `src/schemas/nav/gov/hu/OSA/invoiceApi.xsd`, `invoiceBase.xsd` (via `gh api`) |
| NAV `InvoiceData` tree: `invoiceReference`, `invoiceHead/customerInfo`, `invoiceDetail` (`currencyCode`, `exchangeRate`, `paymentMethod`, `paymentDate`, `invoiceAppearance`), `invoiceLines/line`, `invoiceSummary/summaryNormal/summaryByVatRate`, `summaryGrossData` | `invoiceData.xsd` and `sample/Data sample/Tagorszagi devizas szamla.xml` |
| NAV `common:header` (`requestId, timestamp, requestVersion, headerVersion`) and `common:user` (`login, passwordHash cryptoType="SHA-512", taxNumber, requestSignature cryptoType="SHA3-512"`), namespace `http://schemas.nav.gov.hu/NTCA/1.0/common` | `sample/API sample/tokenExchange.xml`, `invoiceApi.xsd` |
| NAV base URLs (production and test), 35-day window, 100 per page, SHA-512 password hash, SHA3-512 request signature over `requestId + yyyyMMddHHmmss + signingKey`, 1 request/second | claude-mem observations #52143, #52145 |

## Assumptions (marked `# ASSUMPTION` in code)

| # | Where | Assumption | How to confirm |
|---|---|---|---|
| A1 | `agent_client.py` `HEADER_ERROR_CODE`, `HEADER_ERROR_MESSAGE` | Agent error headers are named `szlahu_error_code` and `szlahu_error`. Observation #52141 says errors arrive in headers and names the data headers (`szlahu_szamlaszam` ...) but not the error header names. The body `xmlszamlavalasz` is checked as well, so a wrong header name only loses the header path. | Fetch an unknown number and print `response.headers`. |
| A2 | `agent_client.parse_invoice_xml` `reference` | `alap/hivszamlaszam` carries the referenced original invoice number on storno and modifier documents (named on the Financial Data Connection page; the Agent response page's `alap` list did not show it). | Fetch a storno via the Agent and look for the element. |
| A3 | `agent_client.parse_invoice_xml` `order_ref` | `alap/rendelesszam` holds the order number. | Same fetch. |
| A4 | `agent_client.parse_invoice_xml` customer | `vevo/adoszameu`, `vevo/cim/orszag`, `vevo/cim/irsz`, `vevo/cim/telepules`, `vevo/cim/cim`, `vevo/privatePersonIndicator`. The address block naming mirrors `szallito/cim`. | Same fetch. |
| A5 | `agent_client.parse_invoice_xml` `ledger_code` | `tetel/fokonyv/arbevetel` is the revenue ledger code of a line. | Same fetch with ledger numbers configured. |
| A6 | `db.DOC_TYPE_BY_TIPUS` | `tipus` codes: `SZ` invoice, `SS` storno, `HS` modifier are documented; `DB` / `D` for pro forma (díjbekérő) is a guess. Unknown codes fall back to `modifier` when `hivszamlaszam` is present, else `invoice`. Whether a pro forma is reachable through `xmlszamlaxml` at all is unverified (PLAN risk table). | Fetch a díjbekérő number; check `tipus`. |
| A7 | `db.normalize_payment_method` | `fizmodunified` values contain `transfer` / `cash` / `card` keywords; the raw `fizmod` label is matched on `átutal`, `készpénz`, `kártya`. `Utánvét`, `Csekk`, `PayPal` map to `other`. | Print distinct `fizmodunified` values after the first sync. |
| A8 | `db._fx`, `agent_client` | HUF invoices carry `devizaarf` `0` or `1` or empty; any of these becomes `fx_rate_invoice = 1.0`. For foreign currency an empty or zero rate also becomes 1.0 (no silent multiplication by 0). | Check an EUR invoice's `devizaarf`. |
| A9 | `db._finalize` `paid_huf` | `kifizetes/osszeg` is in the invoice currency; converted with `kifizetes/devizaarf` when present, else the invoice rate. | Check a paid EUR invoice. |
| A10 | `db.rebuild` `payment_id` | The Agent XML has no payment id; `payment_id = "<invoice_number>#<n>"` by document order. Re-fetching an invoice whose payments were re-entered in a different order renumbers them (harmless for reports, matters only for joins on `payment_id`). | None needed; documented behaviour. |
| A11 | `db.rebuild` signed amounts | szamlazz.hu emits negative line and total amounts on storno documents and delta amounts on modifiers, so values are stored as received (no sign flipping). The fixtures follow this. | Fetch a real storno; totals must be negative. If they are positive, negate in `_merge_agent` for `doc_type == "storno"`. |
| A12 | `nav_client.nav_vat_key` | NAV `vatDomesticReverseCharge = true` maps to the szamlazz.hu code `F.AFA`; NAV exemption / out-of-scope `case` codes (`AAM`, `TAM`, `KBAET`, `KBAUK`, `EAM`, `NAM`, `ATK`, `EUFAD37`, `EUFADE`, `EUE`, `HO`) are used verbatim as `vat_rate` keys. szamlazz.hu uses `EU` where NAV uses `KBAET`, so NAV per-rate HUF values only override Agent rows when the key text matches; otherwise Agent amount x rate is used (see precedence below). | Compare `invoice_vat` keys of one EU invoice from both sources. |
| A13 | `nav_client.new_request_id` | `requestId` pattern `[+a-zA-Z0-9_]{1,30}` (30-char upper alnum ids starting with `RID`, like the NAV sample). The NTCA 1.0 `common.xsd` is not in the public repo tree (only NTCA 2.0 is), so the pattern was not re-read this session. | First live `tokenExchange`; an `INVALID_REQUEST` would show up immediately. |
| A14 | `nav_client.NavClient.build_request` | `softwareDevCountryCode` and `softwareDevTaxNumber` are omitted (both `minOccurs=0`). `softwareId` default `CONTROLLERKIT00001`. | None needed. |
| A15 | `szamlazz_sync.HEADER_MAP_FOKONYVI` | Főkönyvi adatexport header strings. The tudástár page lists column *meanings* (számlaszám, számla kiállítás dátuma, teljesítés időpontja, fizetési határidő, vevő neve, vevő adószáma, termék neve, áfakulcs, tétel nettó érték, tétel áfaérték, tétel bruttó érték, devizanem, kifizetett összeg, kifizetés dátuma), not the literal headers. Matching is exact after accent folding and casefolding; unmatched canonical fields are printed as a warning and stay NULL. The line revenue ledger column (`árbevétel főkönyvi szám`) is a guess. | Open a real export, compare the first row with the candidates and extend the tuples. |
| A16 | `szamlazz_sync.HEADER_MAP_AFALISTA`, `AFALISTA_RATE_COLUMN_RE` | Áfalista headers (`Számlaszám`, `Számla kiállításának dátuma`, `Vevő neve`, `Nettó ár`, `Áfa`, `Bruttó ár`) and per-rate column pairs named `<kulcs> alap` / `<kulcs> áfa` (e.g. `27% alap`, `AAM áfa`). The fixture `tests/fixtures/afalista_sample.xlsx` is generated with these same guesses by `tests/fixtures/make_afalista.py`, so the import test is self-consistent, not externally validated. | Open a real Áfalista XLSX and adjust the map and regex. |
| A17 | `szamlazz_sync` CSV parsing | Encoding tried in order utf-8-sig, cp1250, iso-8859-2; delimiter sniffed from the header line among `;`, tab, `,`; dates `2026.08.05.`, `2026-08-05`, `05.08.2026`; numbers with space thousands and decimal comma. | Import a real export. |
| A18 | `agent_error_7.xml` fixture | Namespace `http://www.szamlazz.hu/xmlszamlavalasz` on the failure body is a guess; the parser ignores namespaces. | Compare with a real error body. |

## Precedence rules as implemented (`db.rebuild`)

- Header amounts in document currency: `nav_data` > `agent` > `nav_digest`.
- HUF amounts (`net_huf`, `vat_huf`, `gross_huf`, `invoice_vat.net_huf/vat_huf`): `nav_data` HUF > `nav_digest` HUF > `amount x fx_rate_invoice`. This is the reconciliation of the two sentences in the contract ("nav_data > agent > nav_digest" and "NAV HUF values win"): for EUR invoices the NAV HUF value beats the Agent product; for HUF invoices the three agree.
- `fx_rate_invoice`: `nav_data` `exchangeRate` when present, else Agent `devizaarf`. In the fixture the two differ on purpose (399.5 vs 400) to prove the precedence; the report engine's FX deviation check is where that difference is meant to surface.
- Lines, payments, `payment_method`, `due_date`, `order_ref`, `note`: Agent only, as required. A digest-only invoice therefore has `payment_method = 'other'` and `due_date = NULL` even though the NAV digest carries `paymentMethod` and `paymentDate`. If overdue reporting on digest-only invoices turns out to matter, the fallback is one line in `_merge_digest`.
- `is_einvoice`: Agent `eszamla`, else NAV `invoiceAppearance == 'ELECTRONIC'`.
- `doc_type`: Agent `tipus` when the Agent document exists, else NAV `invoiceOperation` (CREATE/MODIFY/STORNO), else `modifier` / `invoice` by the presence of `originalInvoiceNumber`.
- `modification_index`: NAV value when present; otherwise chain members without an index are numbered sequentially by (`issue_date`, `invoice_number`) after the highest known index; originals get 0.
- `pay_status`: every document of a chain that contains a storno is `void` (original, modifiers and the storno itself). The contract says "originals whose chain contains a storno"; modifiers of a stornoed original are treated the same way because their amounts are cancelled with the chain.
- `customer`: one row per `customer_key`; name, tax number, country and `is_private` come from the customer's latest invoice, `first_invoice_date` / `last_invoice_date` span all documents including proformas.
- `calendar`: from the first day of the month 13 months before the earliest `issue_date` to the last day of the month after the latest. `quarter` is the calendar quarter (`YYYY-Qn`); `fiscal_year` and `fiscal_period_no` honour `fiscal_year_start_month`.
- `raw_documents.body` is gzip-compressed (`mtime=0`), `source_hash` is the SHA-256 of the uncompressed body. `import-csv` and `import-afalista` also store the file under `source = 'csv'` with the file name as `doc_key`.
- Staging imports replace previously imported rows for the same invoice numbers instead of appending, so re-running an import cannot double the reconcile sums.

## reconcile output

`data/reconcile-<period>.csv` (next to the database), `;`-separated, UTF-8 with BOM, columns
`invoice_number, vat_rate, field, cache_value, staging_value, delta`. `field` is
`<source>.<net|vat|gross>` (source `fokonyvi` or `afalista`), `<source>.missing_in_cache` for an
export invoice absent from the cache, and `vat_rate` is empty for invoice-level rows. Only nonzero
deltas are written. Exit 1 when any `|delta| > tolerance` (default 1 HUF) or when nothing is staged
for the period. Invoices present in the cache but absent from the export are not reported (the
export is treated as a control sample, not as the complete population).

## Known gaps

- No live call was made in this session (no key, no NAV technical user). Every network path is
  covered by fakes only.
- The NAV `requestSignature` test computes its expected value inline with `hashlib`; the public NAV
  sample publishes a signature but not the signing key, so there is no external known-answer test.
- `get_secret.check` on this Mac talks to the macOS Keychain through `keyring`; on Windows it uses
  Credential Manager. Only the `SecretMissing` path is unit-tested.
