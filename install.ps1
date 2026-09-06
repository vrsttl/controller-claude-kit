<#
.SYNOPSIS
    Telepíti a controller Claude Code készletet Windows 11 alatt.

.DESCRIPTION
    Idempotens: másodszor futtatva nem változtat semmit, csak [OK] sorokat ír ki.
    Minden lépés előtt ellenőrzi, hogy kell-e csinálni bármit is.

.EXAMPLE
    .\install.ps1 -WhatIf
    Kiírja, mit csinálna, de semmit nem módosít.

.EXAMPLE
    .\install.ps1 -NoAdmin -SkipNav
    Rendszergazdai jogok nélkül, NAV titkok bekérése nélkül.
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [switch]$Update,
    [switch]$NoAdmin,
    [switch]$SkipGmail,
    [switch]$SkipNav,
    [int]$Level = 0,
    [string]$KitPath = $PSScriptRoot
)

$ErrorActionPreference = 'Stop'

. (Join-Path (Join-Path $KitPath 'lib') 'kit-common.ps1')

$script:Cmdlet = $PSCmdlet
$script:DryRun = [bool]$WhatIfPreference
$script:Step = 'indulás'

function Confirm-KitAction {
    param([Parameter(Mandatory = $true)][string]$Target, [Parameter(Mandatory = $true)][string]$Action)
    return $script:Cmdlet.ShouldProcess($Target, $Action)
}

function Set-KitStep {
    param([Parameter(Mandatory = $true)][string]$Name)
    $script:Step = $Name
    Write-Step $Name
}

try {
    $userProfile = Get-KitUserProfile
    $claudeHome = Get-KitClaudeHome
    $projectDir = Get-KitProjectDir
    $scriptsDir = Join-KitPath -Path $projectDir -ChildPath 'scripts'
    $statePath = Join-KitPath -Path $claudeHome -ChildPath 'kit-state.json'
    $settingsPath = Join-KitPath -Path $claudeHome -ChildPath 'settings.json'
    $hooksBlockPath = Join-KitPath -Path $KitPath -ChildPath 'home/hooks/hooks-block.json'
    $backupRoot = Join-KitPath -Path $claudeHome -ChildPath '.kit-backups'
    $localManifestPath = Join-KitPath -Path $claudeHome -ChildPath '.kit-manifest.json'
    $backupStamp = Get-KitTimestamp

    $state = Read-KitState -Path $statePath
    $effectiveLevel = Resolve-KitLevel -State $state -Requested $Level
    $kitVersion = Get-KitVersion -KitPath $KitPath

    Write-Host ""
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host "  Controller Claude Code készlet" -ForegroundColor Cyan
    Write-Host "  verzió: $kitVersion   szint: $effectiveLevel" -ForegroundColor Cyan
    Write-Host "========================================" -ForegroundColor Cyan
    if ($script:DryRun) {
        Write-Host "  PRÓBA MÓD (-WhatIf): semmit nem írok ki a lemezre." -ForegroundColor Yellow
    }
    Write-Detail "készlet: $KitPath"
    Write-Detail "Claude mappa: $claudeHome"
    Write-Detail "projekt: $projectDir"

    # --- 1. winget --------------------------------------------------------
    Set-KitStep '1/14 winget (Windows csomagkezelő)'
    $hasWinget = Test-KitCommand -Name 'winget'
    if ($hasWinget) {
        Write-Success 'már telepítve'
    } elseif ($NoAdmin) {
        Write-Warn 'winget nincs, de -NoAdmin módban vagyunk, a uv oldja meg a Pythont.'
    } else {
        throw ("A winget nem található. Telepítsd az App Installer csomagot a Microsoft Store-ból " +
            "(https://apps.microsoft.com/store/detail/9NBLGGH4NNS1), majd indítsd újra a telepítőt. " +
            "Ha nincs jogod hozzá, futtasd így: .\install.ps1 -NoAdmin")
    }

    # --- 2. Claude Code ---------------------------------------------------
    Set-KitStep '2/14 Claude Code'
    if (Test-KitCommand -Name 'claude') {
        Write-Success ('már telepítve: ' + (Get-KitToolVersion -Name 'claude'))
    } elseif (Confirm-KitAction -Target 'Claude Code' -Action 'telepítés (irm claude.ai/install.ps1)') {
        Invoke-KitWebInstall -Url 'https://claude.ai/install.ps1' -Name 'Claude Code' | Out-Null
        Update-KitPath
        if (Test-KitCommand -Name 'claude') {
            Write-Success 'telepítve'
        } else {
            Write-Warn 'A claude parancs még nem található. Nyiss új terminált, és futtasd újra a telepítőt.'
        }
    }

    # --- 3. Git for Windows -----------------------------------------------
    Set-KitStep '3/14 Git for Windows'
    if (Test-KitCommand -Name 'git') {
        Write-Success ('már telepítve: ' + (Get-KitToolVersion -Name 'git'))
    } elseif ($NoAdmin) {
        Write-Warn ('Git nincs telepítve, -NoAdmin módban kihagyom. A hookok ilyenkor ' +
            'PowerShell alatt futnak, ami ugyanúgy jó.')
    } elseif (Confirm-KitAction -Target 'Git.Git' -Action 'telepítés wingettel') {
        Invoke-KitWinget -PackageId 'Git.Git' -Name 'Git for Windows' | Out-Null
        if (Test-KitCommand -Name 'git') { Write-Success 'telepítve' } else { Write-Warn 'A git még nem található, nyiss új terminált.' }
    }

    # --- 4. Python 3.12 ---------------------------------------------------
    Set-KitStep '4/14 Python 3.12'
    $python = Get-KitPythonInfo
    if ($python.IsOk) {
        Write-Success ('már telepítve: ' + $python.Version + '  (' + $python.Source + ')')
    } else {
        if ($python.IsStoreStub) {
            Write-Warn ('A python parancsra a Microsoft Store helyettesítője válaszol ' +
                '(' + $python.Source + '). Ez nem igazi Python.')
            Write-Detail 'Gépeld be: Beállítások > Alkalmazások > Alkalmazások speciális beállításai > Alkalmazásvégrehajtási aliasok, és kapcsold ki a python.exe aliast.'
        }
        if ($NoAdmin) {
            if (Confirm-KitAction -Target 'Python 3.12 (uv)' -Action 'telepítés uv-vel') {
                Install-KitUv -DryRun:$script:DryRun | Out-Null
                if (-not $script:DryRun) {
                    # A --default kapcsoló hozza létre a python parancsot (uv docs:
                    # concepts/python-versions, "experimental --default option").
                    & uv python install 3.12 --default
                    Update-KitPath
                } else {
                    Write-Plan 'uv python install 3.12 --default'
                }
            }
        } elseif (Confirm-KitAction -Target 'Python.Python.3.12' -Action 'telepítés wingettel') {
            Invoke-KitWinget -PackageId 'Python.Python.3.12' -Name 'Python 3.12' -DryRun:$script:DryRun | Out-Null
        }
        if (-not $script:DryRun) {
            $python = Get-KitPythonInfo
            if ($python.IsOk) {
                Write-Success ('telepítve: ' + $python.Version)
            } else {
                Write-Warn 'A python 3.12 még nem érhető el a PATH-on. Nyiss új terminált, és futtasd újra a telepítőt.'
            }
        }
    }

    # --- 5. Node LTS ------------------------------------------------------
    Set-KitStep '5/14 Node.js LTS'
    if ($SkipGmail) {
        Write-Warn '-SkipGmail miatt kihagyva (a Gmail MCP-hez kellene).'
    } elseif (Test-KitCommand -Name 'node') {
        Write-Success ('már telepítve: ' + (Get-KitToolVersion -Name 'node'))
    } elseif ($NoAdmin) {
        Write-Warn 'Node nincs, -NoAdmin módban kihagyom. A Gmail MCP nem fog működni, amíg nincs Node.'
    } elseif (Confirm-KitAction -Target 'OpenJS.NodeJS.LTS' -Action 'telepítés wingettel') {
        Invoke-KitWinget -PackageId 'OpenJS.NodeJS.LTS' -Name 'Node.js LTS' -DryRun:$script:DryRun | Out-Null
        if (Test-KitCommand -Name 'node') { Write-Success 'telepítve' }
    }

    # --- 6. uv ------------------------------------------------------------
    Set-KitStep '6/14 uv (Python futtató)'
    if (Test-KitCommand -Name 'uv') {
        Write-Success ('már telepítve: ' + (Get-KitToolVersion -Name 'uv'))
    } elseif (Confirm-KitAction -Target 'uv' -Action 'telepítés (irm astral.sh/uv/install.ps1)') {
        if (Install-KitUv -DryRun:$script:DryRun) { Write-Success 'telepítve' }
    }

    # --- 7. keyring -------------------------------------------------------
    Set-KitStep '7/14 keyring eszköz'
    if (Test-KitUvTool -Name 'keyring') {
        Write-Success 'már telepítve'
    } elseif (Confirm-KitAction -Target 'uv tool install keyring' -Action 'telepítés') {
        if ($script:DryRun) {
            Write-Plan 'uv tool install keyring'
        } else {
            & uv tool install keyring
            Write-Success 'telepítve'
        }
    }

    # --- 8. home mappa és hookok -------------------------------------------
    Set-KitStep '8/14 Claude mappa feltöltése és hookok'
    $manifest = Get-KitManifest -KitPath $KitPath
    if (-not $manifest) {
        throw ("Hiányzik a manifest.json a készlet gyökerében ($KitPath). " +
            "Fejlesztői gépen futtasd: uv run python tests/build_manifest.py --write")
    }
    $manifestFiles = Get-KitManifestFiles -Manifest $manifest
    $previousFiles = Get-KitManifestFiles -Manifest (Read-KitJsonFile -Path $localManifestPath)

    if (Confirm-KitAction -Target $claudeHome -Action 'home mappa másolása') {
        New-KitDirectory -Path $claudeHome -DryRun:$script:DryRun | Out-Null
        $homeResult = Copy-KitHome -KitPath $KitPath -ManifestFiles $manifestFiles `
            -PreviousFiles $previousFiles -ClaudeHome $claudeHome -BackupRoot $backupRoot `
            -BackupStamp $backupStamp -DryRun:$script:DryRun
        Write-KitCopySummary -Result $homeResult -Label 'home'
    }

    if (Confirm-KitAction -Target $settingsPath -Action "hookok beolvasztása (szint $effectiveLevel)") {
        $merged = Merge-KitHooks -SettingsPath $settingsPath -HooksBlockPath $hooksBlockPath `
            -Level $effectiveLevel
        Write-KitSettings -SettingsPath $settingsPath -Settings $merged -DryRun:$script:DryRun | Out-Null
        Write-Success "settings.json rendben (mentés: settings.json.bak)"
    }

    # --- 9. Riportok mappa -------------------------------------------------
    Set-KitStep '9/14 Riportok mappa'
    if (Confirm-KitAction -Target $projectDir -Action 'projekt mappa létrehozása') {
        foreach ($sub in @('', 'data', 'data/drops', 'exports', 'reports', 'scripts')) {
            $target = if ($sub) { Join-KitPath -Path $projectDir -ChildPath $sub } else { $projectDir }
            if (New-KitDirectory -Path $target -DryRun:$script:DryRun) {
                Write-Detail "létrehozva: $target"
            }
        }
        $templateResult = Copy-KitSection -KitPath $KitPath -ManifestFiles $manifestFiles `
            -PreviousFiles $previousFiles -Prefix 'templates/project/' -TargetRoot $projectDir `
            -BackupRoot $backupRoot -BackupStamp $backupStamp `
            -CreateOnly @('reports/') -CreateOnlyExcept @('reports/_examples/') `
            -KeepDrifted @('CLAUDE.md') -DryRun:$script:DryRun
        Write-KitCopySummary -Result $templateResult -Label 'Riportok'

        $scriptsResult = Copy-KitSection -KitPath $KitPath -ManifestFiles $manifestFiles `
            -PreviousFiles $previousFiles -Prefix 'scripts/' -TargetRoot $scriptsDir `
            -BackupRoot $backupRoot -BackupStamp $backupStamp -DryRun:$script:DryRun
        Write-KitCopySummary -Result $scriptsResult -Label 'scripts'
    }

    if ((Test-KitCommand -Name 'git') -and -not (Test-Path -LiteralPath (Join-KitPath -Path $projectDir -ChildPath '.git'))) {
        if (Confirm-KitAction -Target $projectDir -Action 'git init') {
            if ($script:DryRun) {
                Write-Plan "git -C `"$projectDir`" init"
            } else {
                & git -C $projectDir init | Out-Null
                Write-Success 'git tároló létrehozva (a riport specek így verziózva lesznek)'
            }
        }
    } elseif (Test-Path -LiteralPath (Join-KitPath -Path $projectDir -ChildPath '.git')) {
        Write-Success 'git tároló már létezik'
    }

    $syncScript = Join-KitPath -Path $scriptsDir -ChildPath 'szamlazz_sync.py'
    if (-not (Test-Path -LiteralPath $syncScript -PathType Leaf)) {
        Write-Warn 'A szamlazz_sync.py még nincs a készletben, az adatbázis létrehozását kihagyom.'
    } elseif (Test-Path -LiteralPath (Join-KitPath -Path $projectDir -ChildPath 'data/invoices.db')) {
        Write-Success 'az invoices.db már létezik'
    } elseif (Confirm-KitAction -Target 'data\invoices.db' -Action 'adatbázis létrehozása') {
        if ($script:DryRun) {
            Write-Plan 'uv run scripts\szamlazz_sync.py init'
        } else {
            Push-Location $projectDir
            try {
                & uv run 'scripts\szamlazz_sync.py' init
                Write-Success 'adatbázis létrehozva'
            } finally {
                Pop-Location
            }
        }
    }

    # --- 10. MCP szerverek -------------------------------------------------
    Set-KitStep '10/14 MCP szerverek'
    $registerScript = Join-KitPath -Path $KitPath -ChildPath 'mcp/register-mcps.ps1'
    if (-not (Test-Path -LiteralPath $registerScript -PathType Leaf)) {
        Write-Warn "Nem találom: $registerScript"
    } else {
        & $registerScript -Level $effectiveLevel -KitPath $KitPath -WhatIf:$script:DryRun
    }

    # --- 11. Gmail MCP -----------------------------------------------------
    Set-KitStep '11/14 Gmail MCP'
    if ($SkipGmail) {
        Write-Warn '-SkipGmail miatt kihagyva.'
    } else {
        $gmailScript = Join-KitPath -Path $KitPath -ChildPath 'mcp/gmail-setup.ps1'
        if (-not (Test-Path -LiteralPath $gmailScript -PathType Leaf)) {
            Write-Warn "Nem találom: $gmailScript"
        } else {
            $accountsFile = Join-KitPath -Path $userProfile -ChildPath '.gmail-mcp/accounts.json'
            $hasAccounts = Test-Path -LiteralPath $accountsFile -PathType Leaf
            $noAuth = ($script:DryRun -or ($Update -and $hasAccounts))
            & $gmailScript -KitPath $KitPath -NoAuth:$noAuth -WhatIf:$script:DryRun
        }
    }

    # --- 12. Titkok --------------------------------------------------------
    Set-KitStep '12/14 Titkok a Windows hitelesítőtárban'
    $secretScript = Join-KitPath -Path $scriptsDir -ChildPath 'get_secret.py'
    if (-not (Test-Path -LiteralPath $secretScript -PathType Leaf)) {
        Write-Warn 'A get_secret.py még nincs a helyén, a titkok bekérését kihagyom.'
    } elseif ($script:DryRun) {
        Write-Plan 'uv run scripts\get_secret.py check, majd a hiányzó tételek bekérése'
    } else {
        $checkText = ''
        Push-Location $projectDir
        try {
            $checkText = (& uv run 'scripts\get_secret.py' check 2>&1 | Out-String)
        } finally {
            Pop-Location
        }
        $missing = New-Object System.Collections.ArrayList
        foreach ($line in ($checkText -split "`r?`n")) {
            if ($line -match '^(szamlazz\.hu|nav\.gov\.hu)\s*/\s*([a-z0-9-]+)\s+(\S+)') {
                $service = $Matches[1]
                $name = $Matches[2]
                $stateText = $Matches[3]
                if ($stateText -like 'megvan*') { continue }
                if ($SkipNav -and ($service -eq 'nav.gov.hu')) { continue }
                [void]$missing.Add(@($service, $name))
            }
        }
        if ($missing.Count -eq 0) {
            Write-Success 'minden szükséges titok megvan'
        } else {
            Write-Detail "Hiányzó titkok: $($missing.Count) darab. Az értékek beírása nem látszik a képernyőn."
            foreach ($pair in $missing) {
                $service = $pair[0]
                $name = $pair[1]
                $answer = Read-Host "Megadod most a(z) $service / $name értékét? (i/n)"
                if ($answer -notmatch '^(i|I|y|Y)') {
                    Write-Warn "kihagyva, később: uv run scripts\get_secret.py set $service $name"
                    continue
                }
                Push-Location $projectDir
                try {
                    & uv run 'scripts\get_secret.py' set $service $name
                } finally {
                    Pop-Location
                }
            }
        }
    }

    # --- Takarítás: a 0.1.0 havi ütemezett feladata -------------------------
    # Kit 0.1.0 registered a monthly task. The kit no longer schedules anything,
    # so a leftover task is unregistered here. Silent no-op when there is nothing
    # to remove, and on any machine without the ScheduledTasks module.
    Remove-KitLegacyScheduledTask | Out-Null

    # --- 13. kit-state.json ------------------------------------------------
    Set-KitStep '13/14 kit-state.json'
    $flags = @{
        gmail = (-not $SkipGmail)
        nav   = (-not $SkipNav)
    }
    if (Confirm-KitAction -Target $statePath -Action 'állapot írása') {
        Write-KitState -Path $statePath -KitVersion $kitVersion -Level $effectiveLevel `
            -KitPath $KitPath -ProjectDir $projectDir -Flags $flags -DryRun:$script:DryRun | Out-Null
        Write-Success "szint $effectiveLevel, verzió $kitVersion"
    }
    if (Confirm-KitAction -Target $localManifestPath -Action 'manifest mentése') {
        if (-not $script:DryRun) {
            Copy-Item -LiteralPath (Join-KitPath -Path $KitPath -ChildPath 'manifest.json') `
                -Destination $localManifestPath -Force
        }
    }

    # --- 14. Ellenőrzés ----------------------------------------------------
    Set-KitStep '14/14 Ellenőrzés'
    $doctorScript = Join-KitPath -Path $KitPath -ChildPath 'doctor.ps1'
    if (Test-Path -LiteralPath $doctorScript -PathType Leaf) {
        & $doctorScript -KitPath $KitPath
    }

    Write-Host ""
    Write-Host "========================================" -ForegroundColor Green
    Write-Host "  Kész" -ForegroundColor Green
    Write-Host "========================================" -ForegroundColor Green
    Write-Host ""
    Write-Host "Következő lépés:" -ForegroundColor Cyan
    Write-Host "  1. Nyiss egy új terminált (hogy a PATH frissüljön)." -ForegroundColor White
    Write-Host "  2. Jelentkezz be: claude   (majd kövesd a képernyőn megjelenő lépéseket)" -ForegroundColor White
    Write-Host "  3. cd `"$projectDir`"" -ForegroundColor White
    Write-Host "  4. claude" -ForegroundColor White
    Write-Host "  5. Írd be: /prime" -ForegroundColor White
    Write-Host ""
} catch {
    Write-Host ""
    Write-Host "[X] A telepítés megszakadt itt: $script:Step" -ForegroundColor Red
    Write-Host "    $($_.Exception.Message)" -ForegroundColor Red
    Write-Host ""
    Write-Host "    A telepítő idempotens: a hibát elhárítva nyugodtan futtathatod újra," -ForegroundColor Yellow
    Write-Host "    a már kész lépéseket átugorja." -ForegroundColor Yellow
    exit 1
}
