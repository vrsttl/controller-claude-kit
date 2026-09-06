#!/usr/bin/env bash
# Full verification sweep for the controller kit. Run from anywhere.
# Prints one PASS / FAIL / SKIP line per step and stops at the first failure.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

pass() { echo "[PASS] $1"; }
skip() { echo "[SKIP] $1"; }
fail() { echo "[FAIL] $1"; exit 1; }

echo "== controller-claude-kit checks =="
echo "repo: $REPO_ROOT"
echo

# 1. Python test suite
set +e
uv run pytest -q
PYTEST_RC=$?
set -e
if [ "$PYTEST_RC" -eq 0 ]; then
  pass "pytest"
elif [ "$PYTEST_RC" -eq 5 ]; then
  skip "pytest, no tests collected yet"
else
  fail "pytest (exit $PYTEST_RC)"
fi

# 2. Lint
if uv run ruff check scripts home/hooks tests; then
  pass "ruff check scripts home/hooks tests"
else
  fail "ruff check scripts home/hooks tests"
fi

# 3. Example report spec validation
if [ ! -f scripts/report_spec.py ]; then
  skip "spec validation, scripts/report_spec.py does not exist yet"
else
  shopt -s nullglob
  SPECS=(templates/project/reports/_examples/*/spec.yaml)
  shopt -u nullglob
  if [ "${#SPECS[@]}" -eq 0 ]; then
    skip "spec validation, no example spec.yaml files yet"
  else
    for f in "${SPECS[@]}"; do
      if ! uv run python scripts/report_spec.py --validate "$f"; then
        fail "spec validation: $f"
      fi
    done
    pass "spec validation (${#SPECS[@]} file(s))"
  fi
fi

# 4. PowerShell parse check of every .ps1 in the repo
if ! command -v pwsh >/dev/null 2>&1; then
  skip "pwsh missing, run: brew install powershell"
else
  PS1_FILES="$(find . -name '*.ps1' \
    -not -path './.git/*' \
    -not -path './.venv/*' \
    -not -path './node_modules/*' | sort)"
  if [ -z "$PS1_FILES" ]; then
    skip "PowerShell parse check, no .ps1 files yet"
  else
    export PS1_FILES
    if pwsh -NoProfile -Command '
      $paths = $env:PS1_FILES -split "\r?\n" | Where-Object { $_ -ne "" }
      $bad = 0
      foreach ($p in $paths) {
        $errors = $null
        $full = (Resolve-Path -LiteralPath $p).Path
        [void][System.Management.Automation.Language.Parser]::ParseFile($full, [ref]$null, [ref]$errors)
        if ($errors.Count -gt 0) {
          $bad++
          Write-Host "  parse errors in $p"
          foreach ($e in $errors) {
            Write-Host ("    line {0}: {1}" -f $e.Extent.StartLineNumber, $e.Message)
          }
        }
      }
      if ($bad -gt 0) { exit 1 }
    '; then
      pass "PowerShell parse check ($(echo "$PS1_FILES" | wc -l | tr -d ' ') file(s))"
    else
      fail "PowerShell parse check"
    fi
  fi
fi

# 5. settings.json merge test
if ! command -v pwsh >/dev/null 2>&1; then
  skip "settings merge test, pwsh missing"
elif [ ! -f tests/test_settings_merge.ps1 ]; then
  skip "settings merge test, tests/test_settings_merge.ps1 does not exist yet"
else
  if pwsh -NoProfile -File tests/test_settings_merge.ps1; then
    pass "settings merge test"
  else
    fail "settings merge test"
  fi
fi

# 6. kit-common helper test
if ! command -v pwsh >/dev/null 2>&1; then
  skip "kit-common test, pwsh missing"
elif [ ! -f tests/test_kit_common.ps1 ]; then
  skip "kit-common test, tests/test_kit_common.ps1 does not exist yet"
else
  if pwsh -NoProfile -File tests/test_kit_common.ps1; then
    pass "kit-common test"
  else
    fail "kit-common test"
  fi
fi

# 7. Manifest integrity
if [ ! -f tests/build_manifest.py ]; then
  skip "manifest check, tests/build_manifest.py does not exist yet"
else
  if uv run python tests/build_manifest.py --check; then
    pass "manifest check"
  else
    fail "manifest check"
  fi
fi

echo
echo "All checks completed."
