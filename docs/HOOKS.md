# Kit hooks

Maintainer and installer reference for `home/hooks/`. End-user text (the nudge, the tips, the block reasons) is Hungarian; everything here is English.

Verified against the Claude Code hooks reference (`https://code.claude.com/docs/en/hooks`, fetched 2026-09-06). Where the docs and `docs/PLAN.md` differ, the docs win; the differences are listed at the end.

## Files

| File | Event / matcher | Level | Purpose |
|---|---|---|---|
| `prime_nudge.py <Event>` | `SessionStart` (`clear\|compact`), `PostToolUse` (`ExitPlanMode`) | 1 | Asks Claude to run `/prime` after a context reset or after leaving plan mode. Self-gating wording, no-op where `/prime` does not exist. |
| `session_tips.py` | `SessionStart` (`*`) | 1 | One rotating Hungarian tip for the current level. |
| `protect_delivery.py` | `PreToolUse` (`Write\|Edit\|MultiEdit\|Bash`) | 1 | Blocks writes, edits and destructive shell commands against delivered-report folders and locked specs. |
| `memory_backup.py` | `PreToolUse` (`Write\|Edit\|MultiEdit`) | 2 | Snapshots auto-memory files under `~/.claude/projects/<slug>/memory/` before they are overwritten, keeps 20. |
| `hooks-block.json` | n/a | n/a | Kit-format hook block consumed by the installer's merge step. Never copied verbatim into `settings.json`. |
| `session_tips.json` | n/a | n/a | The Hungarian tip pool, `{"1": [...], "2": [...], "3": [...]}`. Authored separately from this document. |
| `session_tips.example.json` | n/a | n/a | Two tips per level. Fallback when `session_tips.json` is missing; also the test fixture. |

Runtime artefacts (not shipped, created on her machine): `~/.claude/hooks/.hook-errors.log`, `~/.claude/projects/<slug>/memory/backups/`.

## Runtime contract (all hooks)

- Python 3.12 standard library only, one file per hook, no shared module. Invoked as `python "$HOME/.claude/hooks/<name>.py" [arg]`. `$HOME` is expanded by the hook's shell: Git Bash exports `HOME`, PowerShell has the `$HOME` automatic variable. Claude Code does not set `HOME` itself, it inherits the parent environment, so this only works because both shells define it.
- Event JSON is read from stdin, JSON (if any) is written to stdout, the decision is carried by the exit code. Stdout JSON is ASCII-escaped (`json.dumps` default) so console code pages never matter; stderr is reconfigured to UTF-8 before a Hungarian reason is written.
- Fail-open. Any internal error appends one line `<iso-utc> <hook>: <repr>` to `<claude home>/hooks/.hook-errors.log` and the hook exits 0 with no output. Empty stdin exits 0 silently; malformed non-empty stdin exits 0 and logs one line (`prime_nudge` and `session_tips` ignore stdin content entirely, so they never log for it).
- Claude home is `Path(os.environ.get("CLAUDE_KIT_HOME") or Path.home()) / ".claude"`. `CLAUDE_KIT_HOME` exists for tests only; it is never set on her machine.
- Paths are compared after normalisation to a lowercase forward-slash form: `\` and `/` accepted, `~`, `$VAR`, `${VAR}`, `%VAR%` expanded, Git Bash `/c/Users/...` rewritten to `c:/users/...`, `.` and `..` collapsed, relative paths resolved against the event `cwd` (or `project_dir`). `C:\Users\Fanni\Riportok\exports`, `/c/Users/Fanni/Riportok/exports/` and `c:/users/fanni/riportok/exports` are the same path.

## `kit-state.json`

`<claude home>/kit-state.json`, written by the installer and `/level-up`. Hooks treat it as read-only except `session_tips.py`, which bumps `tips_seen`.

```json
{
  "kit_version": "0.2.0",
  "level": 1,
  "installed_at": "2026-09-06T10:00:00",
  "updated_at": "2026-09-06T10:00:00",
  "kit_path": "C:\\Users\\fanni\\claude-kit",
  "project_dir": "C:\\Users\\fanni\\Riportok",
  "tips_seen": 0,
  "flags": {"gmail": true, "nav": false}
}
```

The hooks read only `level`, `tips_seen` and `project_dir`. The `flags` block is not read by any hook; in particular `flags.schedule` is no longer read, the kit has no unattended run, every report is started by hand. Missing or unreadable file: level 1, `tips_seen` 0, `project_dir` = `<home>/Riportok`. The hooks never create the file. `session_tips.py` rewrites it only when it was readable, via a temp file plus `os.replace`, preserving every other key.

## Hook details

### `prime_nudge.py <HookEventName>`

Argument defaults to `SessionStart`. Consumes stdin, ignores it. Output:

```json
{"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": "A kontextus most újraindult ... hagyd figyelmen kívül ezt az üzenetet."}}
```

Registered twice: `SessionStart` with matcher `clear|compact` (matched against the `source` field) and `PostToolUse` with matcher `ExitPlanMode` (matched against `tool_name`). The `startup` and `resume` sources are deliberately excluded, `/prime` on every start would be noise.

### `session_tips.py`

1. Load `kit-state.json` (level, `tips_seen`).
2. Load tips: first `session_tips.json`, then `session_tips.example.json`, each looked up in `<claude home>/hooks/` and then in the hook's own directory (identical on her machine, different under test). If nothing loads, one built-in tip.
3. Pool = tips for levels 1..N concatenated in order, so level 2 keeps rotating the level 1 tips.
4. Tip = `pool[tips_seen % len(pool)]`, then `tips_seen += 1` (best effort).

Output:

```json
{"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": "Tipp (1. szint): <tip>"}}
```

### `protect_delivery.py`

Protected set, rebuilt on every call from `<project_dir>/reports/*/spec.yaml` (the directory named `_examples` is skipped):

- every top-level `delivery:` block's `folder:` and every top-level `powerbi:` block's `folder:` (quotes stripped, trailing `# comment` stripped, `~` and env vars expanded, relative paths resolved against `project_dir`), kind `folder`;
- the spec file itself when its top-level `report:` block contains `locked: true` (also `yes`, `on`, `1`), kind `locked`.

The spec reader is a ~20-line line-based scanner, not a YAML parser: it tracks the current top-level key (column 0) and picks `folder:` / `locked:` at any indent below it. Nested `folder:` keys under other sections (for example `output.executive.folder`) are ignored.

Decision:

| Tool | Blocked when |
|---|---|
| `Write`, `Edit`, `MultiEdit` | `tool_input.file_path` (resolved against `cwd`) is inside a protected folder, or equals a locked spec |
| `Bash` | `tool_input.command` mentions a protected path (absolute in either slash style, `~`/`$HOME`/`%USERPROFILE%`/`$env:USERPROFILE` prefixed, Git Bash drive form, or relative to `cwd` as a whole token) **and** contains a destructive verb (`rm`, `rmdir`, `rd`, `del`, `erase`, `mv`, `move`, `Remove-Item`, `ri`, `Move-Item`, `mi`, `Clear-Content`, `Out-File`, `Set-Content`) **or** a `>` / `>>` redirect whose target is the protected path **or** `Copy-Item` together with `-Force` |
| anything else (`Read`, `Grep`, `Glob`, ...) | never; the hook is not even registered for them |

Block = Hungarian reason on stderr, exit 2. The reason names the offending path and the slug, says the folder is a delivered-report folder (or a locked spec), and points to `/report-run <slug>` (or `/report-edit <slug>`). Allow = exit 0, no output. A `cat <delivery>/x.xlsx > /tmp/out` is allowed (the redirect target is not protected); `rm -rf <delivery>_other` is allowed (whole-token match). Known gap, by design: `cp`, `copy`, `tee` and `dd` are not in the verb list.

### `memory_backup.py`

Applies only to `tool_input.file_path` under `<claude home>/projects/<slug>/memory/`. Match is `^(.*[\\/]\.claude[\\/]projects[\\/][^\\/]+[\\/]memory)(?:[\\/]|$)` case-insensitive on the absolute path, then the matched memory dir must sit inside `<claude home>/projects/` (compared after normalisation), so a foreign `.claude/projects` tree is ignored. Before the tool runs it copies `MEMORY.md` to `backups/MEMORY.<utc stamp>.md` and, when the target is another file, its pre-image to `backups/<name>.<utc stamp>.bak`, then prunes each group to the newest `KEEP = 20` by mtime. Never blocks, never exits non-zero.

## Sample stdin payloads

Field names per the hooks reference: common `session_id`, `transcript_path`, `cwd`, `permission_mode`, `hook_event_name`; `SessionStart` adds `source` (and sometimes `model`); tool events add `tool_name`, `tool_input`, `tool_use_id`; `PostToolUse` also carries `tool_response`.

SessionStart (after `/clear`):

```json
{"session_id": "abc123", "transcript_path": "C:\\Users\\fanni\\.claude\\projects\\C--Users-fanni-Riportok\\abc123.jsonl", "cwd": "C:\\Users\\fanni\\Riportok", "permission_mode": "default", "hook_event_name": "SessionStart", "source": "clear"}
```

PostToolUse (ExitPlanMode):

```json
{"session_id": "abc123", "transcript_path": "...", "cwd": "C:\\Users\\fanni\\Riportok", "permission_mode": "default", "hook_event_name": "PostToolUse", "tool_name": "ExitPlanMode", "tool_input": {"plan": "..."}, "tool_response": {}, "tool_use_id": "toolu_01"}
```

PreToolUse (Write):

```json
{"session_id": "abc123", "transcript_path": "...", "cwd": "C:\\Users\\fanni\\Riportok", "permission_mode": "default", "hook_event_name": "PreToolUse", "tool_name": "Write", "tool_input": {"file_path": "C:\\Users\\fanni\\Riportok\\exports\\havi_2026-08_v1.0.0.xlsx", "content": "..."}, "tool_use_id": "toolu_01"}
```

PreToolUse (Edit): `tool_input` = `{"file_path": "...", "old_string": "...", "new_string": "..."}`. MultiEdit: `{"file_path": "...", "edits": [{"old_string": "...", "new_string": "..."}]}`. Bash: `{"command": "rm -rf exports", "description": "..."}`.

## Output and exit-code contract

| Hook | stdout | exit |
|---|---|---|
| `prime_nudge.py`, `session_tips.py` | `{"hookSpecificOutput": {"hookEventName": "<event>", "additionalContext": "<text>"}}` | 0 |
| `protect_delivery.py` | nothing | 0 allow, 2 block (stderr = reason shown to Claude) |
| `memory_backup.py` | nothing | 0 |

Per the docs: exit 2 on `PreToolUse` blocks the tool call and feeds stderr to Claude; exit 2 on `PostToolUse` or `SessionStart` does not block anything, which is why only `protect_delivery.py` ever uses it. Exit codes other than 0 and 2 are non-blocking errors; the hooks never use them. The JSON `permissionDecision: "deny"` form would be an equivalent way to block; the kit uses exit 2 because it needs no stdout and matches the workstation hooks.

## `hooks-block.json` and the installer merge contract

Shape:

```json
{
  "kit": "controller",
  "hook_files": ["prime_nudge.py", "session_tips.py", "protect_delivery.py", "memory_backup.py"],
  "hooks": {
    "<EventName>": [
      {"matcher": "<matcher>", "hooks": [{"type": "command", "command": "python \"$HOME/.claude/hooks/<file>\" [arg]", "timeout": 10}], "kit_min_level": <1|2|3>}
    ]
  }
}
```

The installer (and `/level-up`, which must re-run the same merge with the new level) must:

1. Read `<claude home>/settings.json`; a missing file or `{}` counts as `{"hooks": {}}`. Write `settings.json.bak` before touching it.
2. For each `<EventName>` in `hooks-block.json`:
   - drop from the existing `settings.hooks[<EventName>]` every entry that is a kit entry: an entry is a kit entry when any of its `hooks[].command` strings contains one of the `hook_files` names (substring test, so `python3 ~/.claude/hooks/prime_nudge.py`, a different `$HOME` spelling or an older kit version all match);
   - keep every other entry untouched and in its original order (foreign hooks, hand-written hooks);
   - append the kit entries whose `kit_min_level` is less than or equal to her level, with the `kit_min_level` key removed (Claude Code rejects unknown keys in the strict settings schema, do not ship it).
3. Leave events that are not in `hooks-block.json` alone.
4. Leave every non-`hooks` key of `settings.json` alone.
5. The `kit` string is informational; do not write it into `settings.json`.
6. Copy all of `home/hooks/*` into `<claude home>/hooks/` (the `.py` files, both tips JSON files, and `hooks-block.json` itself so `/level-up` can re-merge without the repo).

Re-running the merge is idempotent: the second run removes exactly the entries it added on the first run and adds them back.

Matchers, as the docs define them: a matcher made only of letters, digits, `_`, `-`, spaces, `,` and `|` is an exact string or a `|`/`,`-separated list of exact strings; anything else is an unanchored JavaScript regex. `Write|Edit|MultiEdit|Bash` and `clear|compact` are therefore exact lists, which has the same effect as the regex alternation the plan assumed. `SessionStart` matchers are tested against `source`; tool-event matchers against `tool_name`.

## Differences from `docs/PLAN.md` forced by the docs

| Plan | Docs | Effect |
|---|---|---|
| SessionStart sources `startup\|resume\|clear\|compact` | Also `fork` | `session_tips.py` runs on `*`, so it fires on fork too. `prime_nudge.py` stays on `clear\|compact`; a forked session inherits context and needs no `/prime`. |
| Tool matchers described as regex | Pipe-only matchers are exact lists; regex only when other characters appear | No change to the values; `Edit.*` style patterns would also match `NotebookEdit`, so the kit sticks to exact names. |
| Hook `"shell"` field "unverified" | Documented: `"bash"` or `"powershell"`, default bash, or PowerShell on Windows when Git Bash is absent | Kit still does not set it; the `python "$HOME/..."` form works under both defaults. |
| No timeout stated | Default command timeout is 600 s | Kit sets `timeout: 10` explicitly on every entry. |
| `$HOME` assumed available | Claude Code inherits the parent environment and does not export `HOME` itself | Works under Git Bash and PowerShell (both define it). Would not work under `cmd.exe`, which Claude Code does not use for hooks. |
| Exit 2 = block | True for `PreToolUse` only; `PostToolUse` and `SessionStart` cannot block | Only `protect_delivery.py` exits 2. |

## Tests

`tests/test_hooks.py` runs every hook as a subprocess with `CLAUDE_KIT_HOME=<tmp>`; `protect_delivery.normalize_path`, `protect_delivery._parse_spec` and `session_tips._tip_pool` are also imported directly (`pyproject.toml` puts `home/hooks` on `pythonpath`).

```bash
uv run ruff check home/hooks tests/test_hooks.py
uv run pytest -q tests/test_hooks.py
```
