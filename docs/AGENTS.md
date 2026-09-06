# Agents

Maintainer note for the five sub-agents under `home/agents/` (copied to `%USERPROFILE%\.claude\agents\` by `install.ps1`). Frontmatter descriptions and bodies are Hungarian; agent names, tool names, CLI flags, spec keys and file names stay English. No `skills:` key: the kit's skills invoke the agents, never the reverse.

| Agent | Model | Tools | Invoked by | Never |
|---|---|---|---|---|
| `report-analyst` | opus | Read, Write, Edit, Glob, Grep | `/report-new`, `/report-edit` (spec authoring); main thread for reconcile CSV explanations | writes Python, edits build.py, touches delivered files, runs commands (no Bash: returns the `report_spec.py --validate` / `--bump` command) |
| `report-engineer` | opus | Read, Write, Edit, Bash, Glob | `/report-new`, `/report-edit` after a validated spec; main thread on build failures | edits spec.yaml, writes into delivery.folder, runs build.py without `--dry-run`/`--no-deliver`, runs `pull` without an explicit period, edits `scripts/report_engine.py` or any other kit-owned script (new measures go to `scripts/measures_local.py`) |
| `report-reviewer` | sonnet | Read, Bash, Grep | `/report-new` round 7, `/report-run` after a dry run, main thread on demand | fixes or edits anything, runs build.py or pull |
| `gmail-utility` | sonnet | Read, Write, `mcp__gmail__*` (24 tools) | `/draft-email`, `/report-run` (monthly e-mail draft), main thread for mailbox tasks | calls `send_email` without the literal "küldd el", deletes or labels unasked, drops thread history, changes the default account unasked |
| `web-researcher` | sonnet | WebFetch, WebSearch, Read | Level 3 only (`rules/kit-level-3.md`), main thread on documentation questions | writes to disk, fabricates endpoints or field names, answers without a URL |

## Shared structure

Every file: YAML frontmatter (`name`, `description` with `FOR:` / `NEM ERRE:` / trigger phrases, `model`, `tools`), a one-paragraph role line, a `## Soha` block (hard rules), domain sections, `## Visszaadási protokoll` (the terse Hungarian report the main thread reads), and a closing `<avoid_overengineering>` block in Hungarian.

## Checks

```bash
grep -rnP '\x{2014}|\x{2013}' home/agents docs/AGENTS.md   # em/en dash by code point, must return nothing
grep -rln 'gmail-loc[a]l\|claude_ai_Gma[i]l' home/agents    # workstation tool prefixes, must return nothing
wc -l home/agents/*.md                                       # 80 to 200 lines each
```

## report-engineer conventions

- Local measures: `scripts/report_engine.py` imports the optional sibling `~/Riportok/scripts/measures_local.py` and merges its `MEASURES: dict[str, MeasureDef]` into the catalogue (new ids only; an id that collides with a catalogue id raises a Hungarian error). `measures_local.py` is not in `manifest.json`, so `install.ps1` / `update.ps1` never overwrite it. The agent creates or extends that file (`MeasureDef` fields: `id`, `label_hu`, `label_en`, `formula_words`, `source` D/A, `default_format`, `fn(ctx, start, end, params)`; file skeleton in `docs/MEASURES.md`, "Helyi bővítés"), confirms the id with `uv run scripts/report_spec.py --catalogue`, and adds `reports/<slug>/tests/test_measures_local.py`. It never edits `scripts/report_engine.py`.
- Build tests: `build.py` accepts `--db PATH`, so `reports/<slug>/tests/test_build.py` runs a dry run against an explicit database. Default is `~/Riportok/data/invoices.db` for the last full month; when that period has no `invoice` rows the test calls `pytest.skip` with a Hungarian reason. A fixture DB (for example the kit's `tests/fixtures/fixture.db`) is substituted by changing the `--db` value; no separate fixture mechanism.
- Return protocol: the agent quotes the `build.py --json` keys (`slug`, `period`, `version`, `outcome`, `outcome_hu`, `delivered_path`, `staging_path`, `checks[]` with `id`, `title_hu`, `status`, `detail_hu`, `blocking`, `row_counts`, `totals` with `rev_net`, `inv_count`, `ar_balance`, `overdue_amt`, `previous_totals`, `powerbi_files`, `exit_code`); outcomes `delivered`, `rejected`, `pending`, `exists`, `dry_run`, `not_delivered`; exit codes 0/1/2.

## Known gaps

- `gmail-utility` cannot attach files; the monthly e-mail names the path for manual attachment.
