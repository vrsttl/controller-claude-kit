# Plan: Claude Code starter kit for a finance controller (szamlazz.hu reporting)

> Superseded on 2026-09-06 (v0.2.0): no unattended automation (Task Scheduler
> and `--all` removed); README and HANDOVER rewritten in plain Hungarian with
> technical detail in `docs/HALADO.md`. Per-client parameterisation deferred
> until she asks for it.

## Context

A friend of the user (controller at a small Hungarian IT company, Windows 11 laptop, Claude Code beginner who has already automated some recurring work) needs a packaged, one-script-installable Claude Code setup. The kit must (1) onboard her progressively into Claude Code features, (2) give her a self-serve, repeatable loop for ad-hoc → monthly Excel / Power BI reports fed from szamlazz.hu invoice data, (3) reuse the proven patterns from this workstation (interview skills, dry-run gates, hooks, rules, `/prime`), (4) ship the multi-account Gmail MCP, (5) include a per-project `/prime` bootstrap plus the nudge hook that fires after `/clear`, compaction and `ExitPlanMode`.

The kit is built in `/Users/averes/fanni` and published as a public GitHub repo under `vrsttl`.

## Research conclusions that shape the design (verified 2026-09-06)

| Topic | Finding | Consequence |
|---|---|---|
| szamlazz.hu Számla Agent API | No list/search endpoint. Single-invoice fetch only: `POST https://www.szamlazz.hu/szamla/` multipart field `action-szamla_agent_xml`, root `<xmlszamlaxml>` + `<szamlaagentkulcs>` (42-char key, any plan) + `<szamlaszam>`; response `<szamla>` with header, customer, line items, per-VAT-rate totals, payments, optional PDF. Unknown number → error code 7. Numbering `PREFIX-YYYY-N` is gap-free per prefix per year. | Day-one path = enumeration per prefix/year until 3 consecutive error-7 responses. Query fee assumed zero (fee is per document issued) → confirm with support. |
| NAV Online Számla 3.0 | Company can list its own OUTBOUND invoices by issue-date window (≤35 days, 100/page) via `queryInvoiceDigest`, full XML via `queryInvoiceData`. Needs a technical user (login, SHA-512 password hash, SHA3-512 request signature with the signing key). Digest has no line items and no paid status. `ois-api-client` is unmaintained → write a ~120-line client. | Upgrade path once she has a technical user: NAV digest = authoritative list, Agent = details/payments/PDF. Both paths feed the same cache. |
| Manual exports | Listák → Főkönyvi adatexport CSV (line-item grain, payment status), Áfalista XLSX (per-VAT-rate). No scheduling. | Used as monthly reconciliation control, never as primary source. |
| Excel / Power BI | xlsxwriter (sparklines, data bars, named Excel Tables) writes fresh workbooks; Power BI binds to table names; zero-admin data path = files dropped into an OneDrive-for-work folder, overwritten in place. MCPs: `excel-mcp-server` (haris-musa, uvx), Microsoft `@microsoft/powerbi-modeling-mcp` (official preview), Microsoft Learn MCP (http), `@softeria/ms-365-mcp-server` (optional). | Deterministic Python + xlsxwriter produces the files; MCPs are for interactive inspection only. |
| Windows / Claude Code | Native installer `irm https://claude.ai/install.ps1 \| iex`; config in `%USERPROFILE%\.claude\`, MCP user scope in `%USERPROFILE%\.claude.json`; hooks run under Git Bash when Git for Windows exists, else PowerShell; npx-based stdio MCPs need `cmd /c`; `uv` gives per-user Python + PEP 723 self-contained scripts; `keyring` stores secrets in Windows Credential Manager. | Installer is PowerShell; hook commands written to be valid in both bash and PowerShell. |
| Gmail MCP | Multi-account support is only on the PUBLIC fork `vrsttl/Gmail-MCP-Server`, branch `feature/multi-account-oauth-apps` (not npm). Clone that branch, `npm install && npm run build`, register `node <path>\dist\index.js`; tokens in `~/.gmail-mcp/accounts/<email>/`; add accounts with `auth --keys <oauth-keys.json>`; never set `GMAIL_CREDENTIALS_PATH`. Workstation agent uses prefix `mcp__gmail-local__*` while the user-scope server is `gmail` → kit must use `mcp__gmail__*`. OAuth consent must be "In production" (or Internal for Workspace) or tokens die after 7 days. | Port `gmail-utility` + `draft-email` with the prefix fixed; document the OAuth client creation in Hungarian. |

## Decisions (confirmed with user 2026-09-06)

| Topic | Decision |
|---|---|
| Language | Hungarian for her-facing text (CLAUDE.md, README, rules, interview prompts, Excel labels); English for code, file names, agent/skill names, spec keys, table names |
| Distribution | Public GitHub repo `vrsttl/controller-claude-kit` (no secrets inside) + `install.ps1`; installer clones/pulls to `%USERPROFILE%\claude-kit`, idempotent re-run; `update.ps1` = pull + re-install |
| Her laptop | Admin rights → winget path for Python, Node, Git; keep a `-NoAdmin` fallback (uv-managed Python, portable Git optional) |
| Claude access | Pro/Max subscription; the scheduled monthly run uses the deterministic Python script, Claude is only used for authoring/changes |
| Company mail | Google Workspace → Gmail MCP multi-account at Level 1 (work + personal mailbox) |
| NAV technical user | Unknown → Agent-only enumeration is the day-one data path; NAV hybrid is a documented Level 2 upgrade with `-SkipNav` in the installer |
| Packaging | Hybrid git-repo kit copied into `~/.claude` (plugin format cannot install uv/Node/Git, write user CLAUDE.md, or create scheduled tasks; plain copy is what the mentor already supports) |
| Her project folder | `%USERPROFILE%\Riportok` (scaffolded from `templates/project/`) |
| Hook interpreter | Hook commands are `python "$HOME/.claude/hooks/<name>.py" <arg>`, valid under both Git Bash and PowerShell; `python` comes from winget Python 3.12 (or uv `--default` shim in no-admin mode). No dependency on the unverified `"shell"` hook field |
| Cache strategy | Fetch is incremental (only new invoice numbers); `raw_documents` is append-only; canonical tables are rebuilt from raw on every sync (idempotent, seconds at 50–300 invoices/month) |
| Interview location | Runs in the main thread inside the `/report-new` skill via `AskUserQuestion` (pattern: `~/.claude/skills/supplier-product-ingest/SKILL.md`); agents are used after answers are collected |

## Kit repository layout (`/Users/averes/fanni`)

```
fanni/
├── install.bat                # double-click: powershell -ExecutionPolicy Bypass -File install.ps1
├── install.ps1                # idempotent; flags: -Update -NoAdmin -SkipGmail -SkipNav -SkipSchedule -WhatIf -Level N
├── update.ps1                 # git pull + .\install.ps1 -Update
├── doctor.ps1                 # health check, always exit 0, [OK]/[!]/[X] table + "mit tegyél" lines
├── README.md                  # Hungarian: install, first run, Gmail OAuth client how-to, FAQ
├── CLAUDE.md                  # for the maintainer on this Mac: structure, verify commands
├── CHANGELOG.md
├── manifest.json              # generated by tests/build_manifest.py: managed file → sha256
├── home/                      # copied into %USERPROFILE%\.claude\
│   ├── CLAUDE.md              # her user-level file (~50 lines, HU)
│   ├── rules/                 # kit-level-1.md, kit-level-2.md, kit-level-3.md, reports.md, szamlazz-data.md, email.md
│   ├── agents/                # report-analyst.md, report-engineer.md, report-reviewer.md, gmail-utility.md, web-researcher.md
│   ├── skills/                # report-new/, report-run/, report-edit/, report-list/, level-up/, draft-email/ (each SKILL.md [+ references/])
│   └── hooks/                 # prime_nudge.py, session_tips.py, protect_delivery.py, memory_backup.py, hooks-block.json
├── templates/project/         # scaffold for %USERPROFILE%\Riportok\
│   ├── CLAUDE.md              # project context (non-code style, HU)
│   ├── .claude/commands/prime.md
│   ├── .gitignore             # data/, exports/, *.xlsx, _dryrun/
│   ├── reports/_examples/     # havi_arbev_kintlev/spec.yaml + 3 delta examples (afa_analitika_negyedev, ugyfel_koncentracio_churn, kintlev_behajtas_heti)
│   └── data/drops/.keep, reports/.keep, exports/.keep
├── scripts/                   # copied to %USERPROFILE%\Riportok\scripts\ (all PEP 723 headers, run with `uv run`)
│   ├── szamlazz_sync.py       # CLI: init | pull | pull --agent-only | import-csv | reconcile | status
│   ├── agent_client.py        # Számla Agent xmlszamlaxml (+pdf), error-code mapping, 1 req/s
│   ├── nav_client.py          # queryInvoiceDigest paging/windows + queryInvoiceData, SHA-512/SHA3-512 signing
│   ├── db.py                  # SQLite schema (PRAGMA user_version migrations), raw → canonical rebuild, views
│   ├── get_secret.py          # keyring read with Hungarian error text
│   ├── report_spec.py         # spec.yaml schema + validation + custom-formula whitelist parser
│   ├── report_engine.py       # measure catalogue (pandas over SQLite), comparisons, thresholds, exceptions
│   ├── report_excel.py        # xlsxwriter: executive sheet, data sheets with named tables, Definitions, Run log, CSV export
│   ├── report_validate.py     # checks V01–V16, `_rejected/` handling
│   ├── run_reports.py         # `--all --period previous_month` runner for Task Scheduler
│   └── build_template.py      # template copied to reports/<slug>/build.py by /report-new
├── mcp/
│   ├── register-mcps.ps1      # idempotent `claude mcp add` per level (parses `claude mcp list` first)
│   └── gmail-setup.ps1        # clone fork branch, npm install, build, per-account auth loop
└── tests/
    ├── fixtures/              # agent_szamla_normal.xml, agent_szamla_storno.xml, agent_szamla_modifier.xml, agent_error_7.xml, nav_digest_page1.xml, nav_digest_page2.xml, nav_invoicedata.xml, fokonyvi_sample.csv, afalista_sample.xlsx, fixture.db (built by conftest)
    ├── test_agent_client.py, test_nav_client.py, test_db_rebuild.py, test_sync_incremental.py, test_reconcile.py
    ├── test_report_spec.py, test_report_engine.py, test_report_excel.py, test_report_validate.py, test_hooks.py
    ├── test_settings_merge.ps1 # merge function vs 3 inputs (missing file, {}, pre-existing foreign hooks)
    └── check.sh               # uv run pytest -q && uv run ruff check scripts home/hooks && spec validation of examples && PowerShell parse check
```

## Component specs

### 1. Data layer (`scripts/db.py`, `agent_client.py`, `nav_client.py`, `szamlazz_sync.py`)

SQLite at `%USERPROFILE%\Riportok\data\invoices.db`.

| Table | Grain | Key columns |
|---|---|---|
| `raw_documents` | one fetch | id, source (`agent`/`nav_digest`/`nav_data`/`csv`), doc_key, fetched_at, source_hash, body (gz). Append-only, unique on (source, doc_key, source_hash) |
| `invoice` | one document | invoice_number PK, doc_type (`invoice`/`modifier`/`storno`/`proforma`), nav_operation, chain_root, modification_index, issue_date (kelt), delivery_date (telj), due_date (fizh), payment_method (+raw), is_einvoice, customer_key, currency, fx_rate_invoice (devizaarf), net/vat/gross_amount (signed), net/vat/gross_huf (NAV values when present, else amount × devizaarf), paid_huf, pay_status (`unpaid`/`partial`/`paid`/`void`), order_ref, note, source_flags, period_kelt, period_telj |
| `invoice_line` | one line | invoice_number, line_no, product_name, quantity, unit, unit_price, vat_rate, net, vat, gross, ledger_code |
| `invoice_vat` | invoice × VAT rate | invoice_number, vat_rate, net, vat, gross, net_huf, vat_huf |
| `payment` | one payment | payment_id, invoice_number, pay_date, pay_type, amount, bank_account, note |
| `customer` | one customer | customer_key (vevo.id else sha1(name+taxno)), name, tax_number, country, is_private, first/last_invoice_date |
| `calendar` | one day | date, period_month, quarter, fiscal_year, fiscal_period_no, is_month_end |
| `staging_fokonyvi`, `staging_afalista` | CSV/XLSX rows | reconcile-only, never merged into `invoice` |
| `sync_log` | one run | started, finished, source, window_from, window_to, fetched, inserted, errors, note |
| View `v_chain` | per chain_root | effective_net/vat/gross_huf (signed sum), doc_count, chain_status (`active`/`modified`/`stornoed`), open_huf |

Rules baked in: paid-status derivation order (storno/void → proforma excluded → cash/card auto-paid if spec says so → paid within 1 HUF tolerance → partial → unpaid; overdue = unpaid/partial and due_date < as_of); storno attribution by issue month (default) or original month (spec option); HUF basis = NAV fields when available; FX deviation check between NAV HUF and Agent amount × devizaarf.

`szamlazz_sync.py` commands:

| Command | Behaviour |
|---|---|
| `init` | create schema |
| `pull --period 2026-08` | NAV digest windows ≤35 days, 100/page → new numbers → Agent `xmlszamlaxml` for each → raw → rebuild |
| `pull --agent-only --prefix SZLA [--prefix E-SZLA] --year 2026` | enumerate `seq` from last known + 1, stop after 3 consecutive error-7; 1 req/s token bucket; exponential backoff on 5xx/timeouts, max 5 |
| `import-csv <path>` / `import-afalista <path>` | into staging tables |
| `reconcile --period 2026-08` | cache vs staging per invoice and per VAT rate; exit 1 on mismatch; writes `data/reconcile-<period>.csv` |
| `status` | last sync per source, counts per prefix/year, unresolved chains, gaps |

Secrets via `get_secret.py` → `keyring.get_password("szamlazz.hu", "agent-key")`, `("nav.gov.hu", "tech-login" | "tech-password" | "signing-key" | "tax-number")`. Request logs never include the key.

### 2. Report spec (`report_spec.py`) — the robust requirements interface

`reports/<slug>/spec.yaml` sections (full schema and defaults come from the analyst design; implement exactly these):

| Section | Keys |
|---|---|
| `report` | id (`rpt_<8hex>`, immutable), slug, title_hu, title_en, owner, version (semver), status (draft/active/retired), changelog[] |
| `period` | grain (month/quarter/ytd/week/custom), basis (kelt/teljesites), offset (previous_full_month/current_month_to_date/previous_full_quarter/previous_full_week/{start,end}), fiscal_year_start_month, as_of (period_end/run_date), history_months, storno_attribution |
| `sources` | nav_digest/agent/fokonyvi_csv/afalista {required, path}, max_age_days, cash_card_autopaid |
| `filters` | customers {include, exclude globs}, invoice_prefixes, currencies, vat_rates, doc_types, exclude_proforma, min_net_huf |
| `dimensions` | subset of month, customer, product, vat_rate, currency, payment_method |
| `measures[]` | id (catalogue id or `custom:<slug>` with whitelisted arithmetic formula over catalogue ids and `prior(id, n)`), params, comparisons ⊆ [mom, yoy, ytd, avg3m], format (huf_k/huf/eur/pct/days/count) |
| `thresholds.<id>` | warn, critical, direction (above/below), unit (abs/pct/pct_of:<id>) |
| `exceptions[]` | id, rule (overdue_gt_days, overdue_gt_amount, storno_in_period, modifier_in_period, amount_outlier_zscore, missing_customer_taxno, fx_deviation, duplicate_customer_name, unpaid_cash_invoice), params, severity, max_rows |
| `output` | file_pattern (`{slug}_{period}_v{version}.xlsx`), language (hu/en), number_profile (huf_thousands/huf_full), sheets[] (executive, exceptions, invoice, line, payment, customer, measure, definitions, runlog), executive {blocks[], tiles[≤6], variance_rows[≤9], top_n}, table_prefix (`tbl_<slug>`) |
| `powerbi` | enabled, folder, files ⊆ [fact_invoice, fact_invoice_line, fact_payment, fact_measure, dim_customer, dim_date] |
| `delivery` | folder, overwrite (never/same_version/always), keep_n_versions |
| `validation` | checks[] {id, tolerance, severity, blocks_delivery}, min_rows |

Validation errors are Hungarian, one named error per problem. Table names are append-only after version 1 (edit refuses renames, offers a new table).

### 3. Report engine and Excel (`report_engine.py`, `report_excel.py`, `report_validate.py`)

- Measure catalogue (~30 ids) implemented once in pandas over the canonical tables: rev_net, rev_net_cust, rev_net_prod, rev_net_vat, rev_net_cur, rev_gross, vat_by_rate, vat_total, inv_count, avg_inv, storno_rate, modifier_rate, top_n_share, cust_active, cust_new, cust_returning, cust_churned, ar_balance, ar_aging (buckets not due / 1–30 / 31–60 / 61–90 / 90+), overdue_amt, overdue_cnt, dso, cash_in, coll_rate, ontime_rate, einv_share, pm_mix, eur_share, eur_open, fx_dev. Each carries label_hu, label_en, formula_words, source letter (D = digest-only, A = needs Agent data) so the interview can show which measures require the Agent fetch.
- Executive sheet (the information-dense view): columns A–V, ~38 rows, Calibri 9, fits 1920×1080 at 100% and A4 landscape fit-to-page; freeze at A3; blocks in spec order: title line with period/basis/run timestamp/spec version + validation badge; 6 KPI tiles (value, MoM/YoY deltas, 12-month sparkline); variance table (current, prior, MoM%, prior year, YoY%, YTD, YTD PY, YTD%); AR aging with data bars; VAT summary per rate; top-N customers with share, cumulative share, MoM arrow icon, 6-month sparkline; exceptions block (max 12, sorted by severity, pointer to full sheet); 3-line definitions footnote. Number formats: `#,##0," e Ft"` (thousands profile), `#,##0" Ft"`, `#,##0.00" €"`, `0.0%`, `+0.0%;-0.0%;0.0%`, `0" nap"`, `#,##0" db"`. Red font only on critical breaches, amber on warn, no fills, no charts beyond sparklines, no merged cells except the title.
- Data sheets each with a named Excel Table `tbl_<slug>_<entity>` (English snake_case headers); `Definíciók` sheet (measure id, labels, formula in words, source fields, filters, thresholds); `Futtatási napló` sheet (period, run_ts, spec_version, spec_hash, kit_version, row counts, check results, delivered file).
- Power BI export: CSV UTF-8 with BOM, one file per entity, overwritten in place in `powerbi.folder` (parquet deferred).
- Validation V01–V16 (spec parses; source freshness; NAV count = cache count; line sums = header; per-rate sums = totals; FX deviation; Áfalista tie-out; CSV payment status vs derived; no missing customer; closed-period stability; chain integrity; FX sanity; duplicates; min rows; internal tie-out rev_net = Σ by customer = Σ by VAT rate; output integrity). Blocking failures write `<delivery>/_rejected/<file>_FAILED.xlsx` and exit non-zero; warnings deliver and show in the badge/footnote.
- Build flow per report: `build.py --period <P> --out .staging/` → validate → preview diff vs last delivered (counts, totals) → move into delivery folder (never write there directly; on move failure write `<name>.pending.xlsx` and exit 1).

### 4. Skills (`home/skills/*/SKILL.md`, Hungarian prompts, English names)

| Skill | Mechanics |
|---|---|
| `/report-new` | 7 rounds via `AskUserQuestion` with defaults table (scope; period + sources incl. Agent-dependency warning; population/filters; measures/thresholds/exceptions grouped by revenue/customers/AR/VAT/quality; output/delivery/Power BI; spec preview + text mock-up of the executive sheet + confirm; dry run on last full month + review). Stop-and-fix branch if `sync_log` has no successful sync for the period. Writes `spec.yaml` (status draft) → delegates to `report-engineer` to instantiate `build.py` from `build_template.py` and `tests/` → runs dry run into `_dryrun/` → `report-reviewer` checks → status active |
| `/report-run <slug> [--period P] [--sync-only] [--all]` | sync → build → validate → preview → deliver → open file. `--all` runs every active spec (also the Task Scheduler entry point via `run_reports.py`) |
| `/report-edit <slug>` | shows current spec, asks which section changes, re-opens only the rounds from the re-open matrix (period → 2,4,6,7; filters → 3,6,7; measures → 4,5,6,7; output → 5,6[,7]; title/owner → 6), bumps version (minor/patch), appends changelog, regenerates build.py, re-runs tests + dry run. Refuses to remove a measure still referenced by a tile/row/threshold and refuses table renames after v1 |
| `/report-list` | table from `reports/*/spec.yaml` + last runlog row per report |
| `/level-up` | reads `~/.claude/kit-state.json`, shows what the next level unlocks, confirms, appends `@rules/kit-level-N.md` under the `<!-- KIT-LEVEL-IMPORTS -->` marker in her CLAUDE.md, bumps level, runs `mcp\register-mcps.ps1 -Level N`, prints 3 things to try |
| `/draft-email` | thin delegator to `gmail-utility` (pattern: `~/.claude/skills/draft-email/SKILL.md`): draft only, HTML, no em dashes, account routing by topic, per-account signature, language by recipient TLD |

### 5. Agents (`home/agents/*.md`, template: `~/.claude/agents/documentation-writer.md` with FOR/NOT FOR, `<avoid_overengineering>`, Workflow, Return Protocol)

| Agent | Model | Tools | Role |
|---|---|---|---|
| `report-analyst` | opus | Read, Write, Edit, Glob, Grep | Turns interview answers into a valid `spec.yaml`, designs executive block choices, explains reconcile mismatches. Never writes Python |
| `report-engineer` | opus | Read, Write, Edit, Bash, Glob | Instantiates/updates `build.py` + `tests/` from a validated spec, fixes failing builds, extends `report_engine` catalogue when a spec needs a new measure. Never edits spec.yaml |
| `report-reviewer` | sonnet | Read, Bash, Grep | Reads the produced xlsx back (openpyxl), checks every measure/format/table name against the spec, runs `reconcile`, judges executive-sheet density (one screen, every number has a comparison), reports with cell references. Never fixes |
| `gmail-utility` | sonnet | `mcp__gmail__*` (all 24 tools) + Read, Write | Ported from `~/.claude/agents/gmail-utility.md`: multi-account rules (`list_accounts`/`switch_account`/`set_default_account`), draft-never-send, preserve thread history, HTML, no em dashes; szamlazz.hu számlaértesítő harvesting (`from:@szamlazz.hu`, `download_attachment`) as PDF archive; monthly report e-mail draft in Hungarian |
| `web-researcher` | sonnet | WebFetch, WebSearch, Read | Level 3: NAV/szamlazz.hu doc changes, Power BI connector questions |

### 6. Hooks (`home/hooks/`, Python stdlib only, fail-open, log to `~/.claude/hooks/.hook-errors.log`)

| Hook | Event / matcher | Behaviour |
|---|---|---|
| `prime_nudge.py <Event>` | SessionStart `clear\|compact`; PostToolUse `ExitPlanMode` | Port of `~/.claude/hooks/prime-nudge.sh` without jq (`json.dumps`), same self-gating wording ("ha ebben a projektben elérhető a /prime, futtasd most; különben hagyd figyelmen kívül") |
| `session_tips.py` | SessionStart `*` | One rotating Hungarian tip for the current level from `kit-state.json` (`additionalContext`) |
| `protect_delivery.py` | PreToolUse `Write\|Edit\|MultiEdit\|Bash` | Exit 2 + Hungarian message when the target is under any `delivery.folder` from `Riportok\reports\*\spec.yaml`, or a locked spec, or a Bash/PowerShell delete against those paths; names `/report-run` as the sanctioned path |
| `memory_backup.py` | PreToolUse `Write\|Edit\|MultiEdit` (Level 2+) | Port of `~/.claude/hooks/memory_backup.py`: snapshot files under `.claude\projects\<slug>\memory\` before overwrite, keep 20 |

`hooks-block.json` entries carry `"kit": "controller"` so the installer's merge replaces only kit hooks; commands are `python "$HOME/.claude/hooks/<name>.py" [arg]` (valid in Git Bash and PowerShell). `settings.json` is merged, never overwritten (backup to `settings.json.bak`).

### 7. Progressive onboarding (`home/CLAUDE.md`, `home/rules/kit-level-*.md`, `kit-state.json`)

Her CLAUDE.md (~50 lines, HU): Kommunikációs stílus (terse, tables, no em dashes, "magyarul válaszolj"), Anti-sycophancy, Munkamódszer (she may use Read/Edit/Bash directly; agents are invoked by the report skills for her), Riportok (where things live, spec.yaml is the source of truth, never hand-edit a delivered xlsx), Parancsok table (`/report-*`, `/prime`, `/level-up`, `/clear`, `/memory`), Aktív szint with `@rules/kit-level-1.md` + `<!-- KIT-LEVEL-IMPORTS -->` marker.

| Level | She learns | Kit enables |
|---|---|---|
| 1 Napi használat | `/report-run`, `/report-list`, `/report-new`, permission prompts, Esc, `/clear` | gmail + excel MCPs; prime_nudge, session_tips, protect_delivery hooks; report skills + agents |
| 2 Kontroll | plan mode, `/prime`, project CLAUDE.md, editing spec.yaml, `/report-edit`, reading sync_log, NAV technical user upgrade | microsoft-learn MCP; memory_backup hook; `rules/reports.md`, `rules/szamlazz-data.md` |
| 3 Automatizálás | agents, editing hooks, Task Scheduler, Power BI model MCP, `claude -p` | powerbi-modeling + ms365 MCPs; `web-researcher` agent; headless recipes |

### 8. `/prime` for her project (`templates/project/.claude/commands/prime.md`)

Port of `/Users/averes/webshop/.claude/commands/prime.md` structure, seven sections: tools (excel/gmail MCPs, prefer `uv run scripts/...`); state (`uv run scripts/szamlazz_sync.py status` output); structure of `Riportok`; report table generated from `reports/*/spec.yaml`; versions (Python, uv, deps, kit version, level); key details (HUF zero-decimal, VAT rates in play, storno rule, delivery folder, never hand-edit delivered xlsx); recent work (last 5 sync_log rows + git log of `reports/`). The global nudge hook fires it after `/clear`, compaction and `ExitPlanMode`.

### 9. Installer (`install.ps1`, pattern: `/Users/averes/excel-parsing/windows-package/install.ps1` helpers `Write-Step/Success/Warning`, `Test-Admin`, `Install-WingetPackage`; drop the `--dangerously-skip-permissions` aliases)

Steps, each guarded by a `Test-` check: winget present → Claude Code (`irm https://claude.ai/install.ps1 | iex`) → Git for Windows (winget) → Python 3.12 (winget; `-NoAdmin`: uv + `uv python install 3.12 --default`) → Node LTS (winget, skip with `-SkipGmail`) → uv (`irm https://astral.sh/uv/install.ps1 | iex`) → `uv tool install keyring` → copy `home\*` into `~\.claude\` with `manifest.json` hash compare and `.kit-backups\<ts>\` for drifted files → merge hooks into `settings.json` → scaffold `~\Riportok` (never overwrite existing `reports\`) → `mcp\register-mcps.ps1 -Level 1` → `mcp\gmail-setup.ps1` (clone branch `feature/multi-account-oauth-apps`, `npm install`, `npm run build`, per-account `auth --keys`) → keyring bootstrap (prompt only for missing entries; `-SkipNav` skips the four NAV entries) → Task Scheduler `Controller\HaviRiport` monthly day 5 07:00 running `uv run "$env:USERPROFILE\Riportok\scripts\run_reports.py" --all --period previous_month` (`-SkipSchedule` to opt out) → write `kit-state.json` → `doctor.ps1`.

`doctor.ps1` checks: claude, python, uv, node, git versions; `claude mcp list` connected servers for the level; 5 keyring entries; settings.json parses and contains kit hooks; `invoices.db` exists + counts + last sync; delivery folders writable; scheduled task present; Gmail `accounts.json` lists ≥1 account and token age < 5 days warning; level.

### 10. MCP registration by level (`mcp/register-mcps.ps1`)

```
L1  claude mcp add gmail --scope user -- node "$env:USERPROFILE\Gmail-MCP-Server\dist\index.js"
    claude mcp add excel --scope user -- uvx excel-mcp-server stdio
L2  claude mcp add --transport http --scope user microsoft-learn https://learn.microsoft.com/api/mcp
L3  claude mcp add powerbi-modeling --scope user -- cmd /c npx -y @microsoft/powerbi-modeling-mcp@latest --start
    claude mcp add ms365 --scope user -- cmd /c npx -y @softeria/ms-365-mcp-server
```

## Verification

1. `tests/check.sh` on this Mac: `uv run pytest -q` (all fixtures, no network), `uv run ruff check scripts home/hooks`, `uv run python scripts/report_spec.py --validate templates/project/reports/_examples/*/spec.yaml`, PowerShell parse check of every `.ps1` via `pwsh -NoProfile` (`[System.Management.Automation.Language.Parser]::ParseFile`), `pwsh tests/test_settings_merge.ps1`.
2. End-to-end on fixtures: build `havi_arbev_kintlev` for a fixture month into `.staging/`, assert sheet list, table names, number formats, tile count ≤ 6, exceptions ≤ 12, CSV golden hashes, validation report has no blocking failure; inject a 1 HUF VAT delta and assert `_rejected/` path + exit 1.
3. Hook contract tests: feed SessionStart/PostToolUse/PreToolUse JSON on stdin, assert `additionalContext` JSON or exit 2 with Hungarian stderr; assert fail-open on malformed input.
4. Manual on her laptop (stated gap, cannot be verified here): `install.ps1 -WhatIf` first, then live run, then `doctor.ps1`; first real sync in `--agent-only` mode for one prefix and one month; `reconcile` against a Főkönyvi CSV export of the same month before the first delivered report.
5. Live API checks she must do once (documented in README): Agent key works (`status` after a 1-invoice fetch), proforma reachability via `xmlszamlaxml`, Agent query fee confirmation with szamlazz.hu support, NAV technical user creation (Level 2).

## Risks and open items

| Item | Handling |
|---|---|
| Agent query fee assumed zero | README instructs to confirm with support before the first full enumeration; incremental sync keeps request counts low |
| Proforma reachability via `xmlszamlaxml` unverified | Proforma prefixes are opt-in in `filters.invoice_prefixes`; Definitions sheet states coverage |
| NAV technical user may need company Ügyfélkapu rights | `-SkipNav`; Agent-only path is first-class; NAV documented as Level 2 upgrade |
| Hook `"shell"` field and AskUserQuestion-on-Windows unverified | Hook commands are shell-agnostic; interview runs in the main thread like `supplier-product-ingest` |
| OneDrive file open in Excel during scheduled run | Build to `.staging/`, move; on failure `.pending.xlsx` + exit 1 |
| Excel Table renamed after Power BI binds | `/report-edit` refuses renames after v1 |
| Google OAuth consent in Testing mode | README warning; `doctor.ps1` token-age check |
| No Windows VM on this Mac | Installer parse-checked + `-WhatIf`; winget/schtasks/Credential Manager steps verified on first install, covered by `doctor.ps1` |
