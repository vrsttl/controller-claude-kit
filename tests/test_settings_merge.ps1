# Tests for Merge-KitHooks, the settings.json merge contract in docs/HOOKS.md.
# Runs on macOS under pwsh 7 and on Windows PowerShell 5.1: pure JSON handling,
# no Windows-only calls.
#
#   pwsh -NoProfile -File tests/test_settings_merge.ps1

$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot
. (Join-Path $repoRoot (Join-Path 'lib' 'kit-common.ps1'))

$hooksBlockPath = Join-Path $repoRoot (Join-Path 'home' (Join-Path 'hooks' 'hooks-block.json'))
$failures = New-Object System.Collections.ArrayList
$tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("kit-merge-" + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $tempRoot -Force | Out-Null

function Test-Assert {
    param([bool]$Condition, [Parameter(Mandatory = $true)][string]$Message)
    if ($Condition) {
        Write-Host "  ok   $Message" -ForegroundColor DarkGray
    } else {
        [void]$failures.Add($Message)
        Write-Host "  FAIL $Message" -ForegroundColor Red
    }
}

function New-SettingsFile {
    param([string]$Name, [string]$Content)
    $path = Join-Path $tempRoot $Name
    if ($null -ne $Content) {
        [System.IO.File]::WriteAllText($path, $Content, (New-Object System.Text.UTF8Encoding($false)))
    }
    return $path
}

function Get-EventCommands {
    param($Merged, [Parameter(Mandatory = $true)][string]$EventName)
    $commands = New-Object System.Collections.ArrayList
    if (-not (Test-KitProperty -Object $Merged.hooks -Name $EventName)) { return , @() }
    foreach ($entry in @($Merged.hooks.$EventName)) {
        foreach ($hook in @($entry.hooks)) { [void]$commands.Add([string]$hook.command) }
    }
    return , ($commands.ToArray())
}

function Get-AllCommands {
    param($Merged)
    $commands = New-Object System.Collections.ArrayList
    foreach ($event in $Merged.hooks.PSObject.Properties) {
        foreach ($entry in @($event.Value)) {
            foreach ($hook in @($entry.hooks)) { [void]$commands.Add([string]$hook.command) }
        }
    }
    return , ($commands.ToArray())
}

function Measure-Match {
    param([string[]]$Values, [Parameter(Mandatory = $true)][string]$Needle)
    return @($Values | Where-Object { $_ -like "*$Needle*" }).Count
}

try {
    # --- 1. missing settings file ----------------------------------------
    Write-Host "1. hianyzo settings.json"
    $path1 = Join-Path $tempRoot 'missing.json'
    $merged1 = Merge-KitHooks -SettingsPath $path1 -HooksBlockPath $hooksBlockPath -Level 1
    $json1 = ConvertTo-Json -InputObject $merged1 -Depth 20
    $all1 = Get-AllCommands -Merged $merged1

    Test-Assert (-not (Test-Path -LiteralPath $path1)) 'a merge nem hoz letre fajlt'
    Test-Assert ($all1.Count -eq 4) "pontosan 4 kit hook parancs (kapott: $($all1.Count))"
    Test-Assert ((Measure-Match -Values $all1 -Needle 'prime_nudge.py') -eq 2) 'ket prime_nudge bejegyzes'
    Test-Assert ((Measure-Match -Values $all1 -Needle 'session_tips.py') -eq 1) 'egy session_tips bejegyzes'
    Test-Assert ((Measure-Match -Values $all1 -Needle 'protect_delivery.py') -eq 1) 'egy protect_delivery bejegyzes'
    Test-Assert ((Measure-Match -Values $all1 -Needle 'memory_backup.py') -eq 0) '1. szinten nincs memory_backup'
    Test-Assert ($json1 -notlike '*kit_min_level*') 'a kit_min_level kulcs le van vagva'
    Test-Assert ($json1 -notlike '*"kit"*') 'a kit azonosito nem kerul a settings.json-be'

    # --- 2. empty object --------------------------------------------------
    Write-Host "2. ures settings.json"
    $path2 = New-SettingsFile -Name 'empty.json' -Content '{}'
    $merged2 = Merge-KitHooks -SettingsPath $path2 -HooksBlockPath $hooksBlockPath -Level 1
    $json2 = ConvertTo-Json -InputObject $merged2 -Depth 20
    Test-Assert ($json2 -eq $json1) 'a {} eredmenye azonos a hianyzo fajleval'

    # --- 3. foreign hooks plus a stale kit entry ---------------------------
    Write-Host "3. idegen hookok es elavult kit bejegyzes"
    $existing = @'
{
  "permissions": {
    "allow": ["Bash(ls:*)"],
    "deny": []
  },
  "model": "opus",
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [{ "type": "command", "command": "echo foo" }]
      }
    ],
    "Stop": [
      {
        "matcher": "*",
        "hooks": [{ "type": "command", "command": "echo stop" }]
      }
    ],
    "SessionStart": [
      {
        "matcher": "clear",
        "hooks": [{ "type": "command", "command": "python3 ~/.claude/hooks/prime_nudge.py SessionStart" }]
      }
    ]
  }
}
'@
    $path3 = New-SettingsFile -Name 'existing.json' -Content $existing
    $merged3 = Merge-KitHooks -SettingsPath $path3 -HooksBlockPath $hooksBlockPath -Level 1

    Test-Assert (Test-KitProperty -Object $merged3 -Name 'permissions') 'a permissions kulcs megmaradt'
    Test-Assert (@($merged3.permissions.allow).Count -eq 1) 'a permissions tartalma valtozatlan'
    Test-Assert ($merged3.model -eq 'opus') 'az egyeb kulcsok valtozatlanok'

    $stop3 = Get-EventCommands -Merged $merged3 -EventName 'Stop'
    Test-Assert ($stop3.Count -eq 1 -and $stop3[0] -eq 'echo stop') 'a Stop hook erintetlen'

    $pre3 = Get-EventCommands -Merged $merged3 -EventName 'PreToolUse'
    Test-Assert ($pre3.Count -eq 2) "PreToolUse: 1 idegen + 1 kit (kapott: $($pre3.Count))"
    Test-Assert ($pre3[0] -eq 'echo foo') 'az idegen PreToolUse hook maradt elol'
    Test-Assert ($pre3[1] -like '*protect_delivery.py*') 'a kit hook a vegere kerult'

    $start3 = Get-EventCommands -Merged $merged3 -EventName 'SessionStart'
    Test-Assert ((Measure-Match -Values $start3 -Needle 'prime_nudge.py') -eq 1) 'az elavult prime_nudge bejegyzest lecsereltuk, nincs duplikatum'
    Test-Assert ((Measure-Match -Values $start3 -Needle 'python3 ~/.claude') -eq 0) 'a regi parancs string eltunt'
    Test-Assert ($start3.Count -eq 2) "SessionStart: 2 kit bejegyzes (kapott: $($start3.Count))"

    # --- 4. level gate ----------------------------------------------------
    Write-Host "4. szintfuggo bejegyzesek"
    $mergedL1 = Merge-KitHooks -SettingsPath (Join-Path $tempRoot 'lvl.json') -HooksBlockPath $hooksBlockPath -Level 1
    $mergedL2 = Merge-KitHooks -SettingsPath (Join-Path $tempRoot 'lvl.json') -HooksBlockPath $hooksBlockPath -Level 2
    $allL1 = Get-AllCommands -Merged $mergedL1
    $allL2 = Get-AllCommands -Merged $mergedL2
    Test-Assert ((Measure-Match -Values $allL1 -Needle 'memory_backup.py') -eq 0) '1. szint: nincs memory_backup'
    Test-Assert ((Measure-Match -Values $allL2 -Needle 'memory_backup.py') -eq 1) '2. szint: van memory_backup'
    Test-Assert ($allL2.Count -eq ($allL1.Count + 1)) '2. szinten pontosan eggyel tobb bejegyzes'

    # --- 5. idempotence ---------------------------------------------------
    Write-Host "5. ismetelt futtatas"
    $path5 = New-SettingsFile -Name 'idem.json' -Content $existing
    $first = Merge-KitHooks -SettingsPath $path5 -HooksBlockPath $hooksBlockPath -Level 2
    Write-KitSettings -SettingsPath $path5 -Settings $first | Out-Null
    $firstJson = Get-Content -LiteralPath $path5 -Raw -Encoding UTF8

    $second = Merge-KitHooks -SettingsPath $path5 -HooksBlockPath $hooksBlockPath -Level 2
    Write-KitSettings -SettingsPath $path5 -Settings $second | Out-Null
    $secondJson = Get-Content -LiteralPath $path5 -Raw -Encoding UTF8

    Test-Assert ($firstJson -eq $secondJson) 'a masodik merge ugyanazt a JSON-t adja'
    Test-Assert (Test-Path -LiteralPath "$path5.bak") 'keszult settings.json.bak mentes'

    $thirdJson = Get-Content -LiteralPath $path5 -Raw -Encoding UTF8
    Test-Assert ($thirdJson -notlike '*kit_min_level*') 'a kiirt fajlban sincs kit_min_level'
} finally {
    Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Host ""
if ($failures.Count -gt 0) {
    Write-Host "FAIL: $($failures.Count) allitas bukott el." -ForegroundColor Red
    foreach ($item in $failures) { Write-Host "  - $item" -ForegroundColor Red }
    exit 1
}
Write-Host "PASS: settings merge" -ForegroundColor Green
exit 0
