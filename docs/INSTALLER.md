# Installer

Maintainer notes for `install.bat`, `install.ps1`, `update.ps1`, `doctor.ps1`,
`lib/kit-common.ps1`, `mcp/register-mcps.ps1`, `mcp/gmail-setup.ps1` and
`tests/build_manifest.py`. Everything she sees on screen is Hungarian; code,
function names and comments are English.

## Files

| File | Role |
|---|---|
| `install.bat` | Double-click entry point. Runs `powershell -NoProfile -ExecutionPolicy Bypass -File install.ps1 %*`, then `pause`. |
| `install.ps1` | The 14 step idempotent installer. |
| `update.ps1` | `git pull --ff-only`, then `install.ps1 -Update` with the same switches. |
| `doctor.ps1` | Read only health check. Always exits 0. `-Json` for support. |
| `lib/kit-common.ps1` | Dot sourced helpers shared by all of the above. |
| `mcp/register-mcps.ps1` | `claude mcp add` per level. `-Remove` for uninstall. |
| `mcp/gmail-setup.ps1` | Clone, build and authenticate the multi account Gmail MCP fork. |
| `tests/build_manifest.py` | Generates and verifies `manifest.json`. |
| `tests/test_settings_merge.ps1` | The `settings.json` merge contract. |
| `tests/test_kit_common.ps1` | Manifest compare, copy semantics, kit state, spec scanner. |

## Running the tests on this Mac

```bash
pwsh -NoProfile -File tests/test_settings_merge.ps1
pwsh -NoProfile -File tests/test_kit_common.ps1
uv run python tests/build_manifest.py --write
uv run python tests/build_manifest.py --check
```

`tests/check.sh` already wires in the parse check, the settings merge test and
the manifest check. It also calls `tests/test_kit_common.ps1` as step 6, so the
sweep covers every test listed above.

A `-WhatIf` smoke run also works on macOS, because every path join goes through
`Join-KitPath` and `Get-KitUserProfile` falls back to `$HOME` when
`%USERPROFILE%` is empty:

```bash
SANDBOX=$(mktemp -d)
pwsh -NoProfile -Command "\$env:USERPROFILE='$SANDBOX'; ./install.ps1 -WhatIf -NoAdmin -SkipGmail"
```

It prints the full plan and writes nothing. This is the closest thing to an
end to end test available without a Windows machine.

## PowerShell compatibility rules

Target is Windows PowerShell 5.1 (what `install.bat` launches) and pwsh 7.

- No 7 only syntax: no `??`, no `?:`, no `ForEach-Object -Parallel`, no
  `ConvertFrom-Json -AsHashtable`, no multi argument `Join-Path`.
- Every `ConvertTo-Json` call passes `-Depth 20`. The 5.1 default of 2 would
  silently truncate `hooks[].hooks[].command`.
- JSON is written with `[System.IO.File]::WriteAllText(..., UTF8Encoding($false))`,
  that is UTF-8 **without** BOM. `Set-Content -Encoding UTF8` writes a BOM in
  5.1 and Node's `JSON.parse` rejects a leading BOM.
- `ConvertFrom-Json` coerces ISO 8601 looking strings into `[datetime]` in both
  5.1 and 7. A naive round trip therefore rewrites `2026-09-06T10:00:00` in the
  current culture format. `ConvertTo-KitIsoString` guards `installed_at`.
- Single element arrays survive as arrays when they are property values (checked
  on pwsh 7.6.5); the merge additionally casts to `[object[]]` before assigning,
  so the shape cannot collapse.
- Every `.ps1` file is saved as **UTF-8 with BOM**. Windows PowerShell 5.1
  assumes the ANSI code page for BOM-less files and would mangle every Hungarian
  accent in the console output. Re-add the BOM after any bulk rewrite:

  ```bash
  python3 -c "
  import pathlib
  BOM=b'\xef\xbb\xbf'
  for p in list(pathlib.Path('.').glob('*.ps1'))+list(pathlib.Path('.').glob('*/*.ps1')):
      d=p.read_bytes()
      if not d.startswith(BOM): p.write_bytes(BOM+d)
  "
  ```

- `Write-Warning` is a built-in cmdlet. The helper is called `Write-Warn` so the
  dot sourced scope does not shadow it.

## `manifest.json` and the copy contract

`tests/build_manifest.py` hashes every file under `home/`, `templates/project/`
and `scripts/` (relative POSIX paths, sorted, sha256) and reads `kit_version`
from the first `## [x.y.z]` heading in `CHANGELOG.md`, falling back to `0.1.0`
while only `[Unreleased]` exists. Caches and OS droppings (`__pycache__`,
`*.pyc`, `.DS_Store`, ...) are excluded, which is why the copy step is manifest
driven rather than a `Copy-Item -Recurse`.

`--check` compares `kit_version` and the `files` map only; `generated_at` is
ignored and is preserved across `--write` when nothing else moved, so the file
does not churn in git.

The installer keeps its previous manifest at `~\.claude\.kit-manifest.json`.
`Compare-KitFile` returns one of four states and `Copy-KitSection` acts on them:

| State | Meaning | Action |
|---|---|---|
| `missing` | not on her laptop yet | copy |
| `same` | hash equals the manifest | nothing |
| `kit-updated` | differs from the manifest but equals the previous manifest | overwrite silently |
| `user-modified` | differs from both | back up, then overwrite, and list it in the summary |

Backups go to `~\.claude\.kit-backups\<yyyyMMdd-HHmmss>\<manifest relative path>`,
so `home/rules/reports.md` lands at
`.kit-backups\20260906-101500\home\rules\reports.md`. Keeping the `home/`,
`templates/project/` and `scripts/` prefixes means backups from different
sections never collide. One timestamp folder per installer run.

Section specific rules:

| Section | Target | Exceptions |
|---|---|---|
| `home/` | `~\.claude\` | none |
| `templates/project/` | `~\Riportok\` | `reports/` is create only (never overwritten, never backed up) except `reports/_examples/`, which is kit owned; `CLAUDE.md` is backed up but hers is kept when it drifted |
| `scripts/` | `~\Riportok\scripts\` | none, kit owned, always refreshed |

### `.gitattributes`

I added a `.gitattributes` at the repo root with `* -text`. Without it a Windows
checkout with `core.autocrlf=true` rewrites every LF to CRLF, every sha256 stops
matching, and the installer reports the entire kit as "she edited it" and backs
up 50 files on the first run. It is committed at the repo root by design with
`* -text`, so Windows checkouts keep LF and the manifest hashes match.

## `settings.json` merge

`Merge-KitHooks -SettingsPath -HooksBlockPath -Level` implements `docs/HOOKS.md`
exactly and returns the merged object without touching the disk;
`Write-KitSettings` writes it and takes the `settings.json.bak` backup. Splitting
them is what makes the merge testable.

Kit entries are identified by substring: an entry counts as a kit entry when any
of its `hooks[].command` strings contains one of the `hook_files` names. That
matches `python3 ~/.claude/hooks/prime_nudge.py` and any older command spelling,
so re-running never duplicates. `kit_min_level` is stripped before the entry is
appended, and the informational `kit` key never reaches `settings.json`.

`/level-up` must call the same two functions with the new level.

## `kit-state.json`

Written by `Write-KitState`. Key order is fixed:
`kit_version, level, installed_at, updated_at, kit_path, project_dir, tips_seen,
flags{gmail, nav}`. On a re-run `installed_at` and `tips_seen` are read
back from the existing file and preserved; `level` comes from the caller, which
resolves it with `Resolve-KitLevel` (explicit `-Level N` wins, else the existing
level, else 1).

Kit 0.1.0 also wrote a `flags.schedule` key. `Write-KitState` rebuilds the
`flags` object from scratch on every run, so that key disappears from the file
the first time 0.2.0 rewrites it. Nothing reads it any more.

## Verified against live documentation (2026-09-06)

### uv: the `python` shim

`https://docs.astral.sh/uv/concepts/python-versions/` says, verbatim: "To install
`python` and `python3` executables, include the experimental `--default` option:
`uv python install 3.12 --default`". It calls the option experimental but does
not require `--preview`. Confirmed against the installed uv 0.9.9: `uv python
install --help` lists `--default` as a plain flag and has no `--preview` option
of its own (`--preview` is still accepted as a hidden global flag, but passing it
buys nothing). The installer therefore runs, in `-NoAdmin` mode only:

```
uv python install 3.12 --default
```

Older uv releases (roughly before 0.5) did gate `--default` behind `--preview`;
if she somehow ends up on one, the command fails loudly and `doctor.ps1` reports
`python` as missing.

### `claude mcp add`

Verified against `https://code.claude.com/docs/en/mcp`:

- Shape is `claude mcp add [options] <name> [url-or-command]`.
- The `--` separator is **required** for stdio servers and comes after every
  option, before the command: `claude mcp add [options] <name> -- <command> [args...]`.
- `--scope user` may sit before or after the name. The docs show
  `claude mcp add --transport http hubspot --scope user https://mcp.hubspot.com/anthropic`.
- HTTP servers use `--transport http <name> <url>`.
- Environment variables use `-e KEY=value` / `--env KEY=value`. The kit needs
  none, so no `-e` flag is emitted.
- `claude mcp list` prints a health marker per server: `✔ Connected`,
  `! Needs authentication`, `✘ Failed to connect`, `⏸ Pending approval`,
  `⊘ Disabled for this project`.

`register-mcps.ps1` parses `claude mcp list` once with `(?m)^\s*<name>\s*:` and
only adds what is missing. `doctor.ps1` reuses the same parse and downgrades a
row to `[!]` when the line contains `Failed`, `Needs authentication` or
`Disabled`. The exact glyphs are not matched, because a 5.1 console with a legacy
code page will not render them.

### Gmail MCP token layout

Verified against the fork itself (cloned `vrsttl/Gmail-MCP-Server`, branch
`feature/multi-account-oauth-apps`, `src/account-manager.ts` lines 13 to 16 and
69, `src/index.ts` around line 100):

```
~/.gmail-mcp/gcp-oauth.keys.json              global fallback OAuth app
~/.gmail-mcp/accounts.json                    {version, activeAccount, defaultAccount, accounts{email: {...}}}
~/.gmail-mcp/accounts/<email>/credentials.json   the OAuth tokens
~/.gmail-mcp/accounts/<email>/oauth-keys.json    per account OAuth app (optional)
~/.gmail-mcp/credentials.json                 legacy single account layout
```

So the token file whose age matters is
`accounts/<email>/credentials.json`, not `token.json`. `doctor.ps1` still probes
`token.json` as a second candidate in case an older single account install is
migrated in, and says so here rather than guessing silently.

The auth command is `node dist/index.js auth --keys "<path>"`
(`parseAuthArgs()` in `src/index.ts`; the optional positional argument is the
callback URL, default `http://localhost:3000/oauth2callback`). The keys file must
contain an `installed` or a `web` object, which `gmail-setup.ps1` validates
before shelling out. `GMAIL_CREDENTIALS_PATH` is a Docker only variable and is
never set.

Testing mode consent screens expire refresh tokens after 7 days, so `doctor.ps1`
warns at 5 days.

## Removed in 0.2.0: the monthly scheduled task

0.1.0 registered a Task Scheduler entry, `\Controller\HaviRiport`, that ran the
reports unattended on the 5th of every month. There is no unattended automation
in the kit any more: a monthly run is something she starts by hand, so the
`-SkipSchedule` switch, the registration step and the `doctor.ps1` row are all
gone.

Machines that already took 0.1.0 still have the task, and it would keep firing
against a runner that no longer accepts its arguments. `install.ps1` therefore
calls `Remove-KitLegacyScheduledTask` on every run. The helper is idempotent and
silent: it returns `$false` without printing anything when `Get-ScheduledTask` or
`Unregister-ScheduledTask` is unavailable (so it is a no-op on macOS and Linux)
or when the task is not there. Only when it actually removes something does it
print one Hungarian line saying the automatic monthly run is gone and reports are
started by hand. The unregister sits behind `SupportsShouldProcess`, so
`install.ps1 -WhatIf` never touches it.

## Python on PATH and the Microsoft Store stub

`Get-KitPythonInfo` returns `IsStoreStub = $true` when either
`(Get-Command python).Source` contains `\WindowsApps\` or `python --version`
prints nothing. Both are the Store alias stub, which opens the Store instead of
running Python and would break every hook. The installer warns and points at
Settings > Apps > Advanced app settings > App execution aliases; `doctor.ps1`
repeats it as a `[X]` row.

## Testability boundaries

Everything Windows only sits behind a wrapper with a `-DryRun` switch, and
`tests/test_kit_common.ps1` asserts both that the wrapper exists and that
`-DryRun` returns without calling anything:

`Invoke-KitWinget`, `Invoke-KitWebInstall`, `Install-KitUv`, plus the mutating
helpers `Copy-KitSection`, `Copy-KitHome`, `Copy-KitFile`, `Backup-KitFile`,
`New-KitDirectory`, `Write-KitSettings` and `Write-KitState`.

`install.ps1` itself uses `[CmdletBinding(SupportsShouldProcess)]` and wraps every
mutating step in `$PSCmdlet.ShouldProcess`, captured as `$script:Cmdlet` so the
`Confirm-KitAction` helper can reach it. `$script:DryRun = [bool]$WhatIfPreference`
drives the `-DryRun` switches and the `[terv]` plan lines.

## Cannot be verified without a Windows machine

- `winget install` for `Git.Git`, `Python.Python.3.12`, `OpenJS.NodeJS.LTS`.
- `irm https://claude.ai/install.ps1 | iex` and the uv installer.
- `keyring` writing into Windows Credential Manager, and the interactive
  `getpass` prompt inside `uv run` under a PowerShell host.
- Whether `%USERPROFILE%\.local\bin` is where the Claude Code and uv installers
  actually land on Windows 11, and whether `Update-KitPath` therefore finds them
  without a new terminal.
- Console rendering of Hungarian accents and of the `claude mcp list` glyphs in a
  legacy code page console.
- Whether `python` resolves to the winget Python before the Store alias after a
  fresh install without a reboot.

Run `install.ps1 -WhatIf` first on her laptop, then the live run, then
`doctor.ps1`.
