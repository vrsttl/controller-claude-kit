<#
.SYNOPSIS
    Ellenőrzi, hogy a készlet minden eleme a helyén van-e. Soha nem javít.

.DESCRIPTION
    Mindig 0 kilépési kóddal áll le, hogy a telepítő végén is futtatható legyen.
    Minden sor [OK], [!] vagy [X], és minden nem [OK] sorhoz tartozik egy
    "mit tegyél" tanács.

.EXAMPLE
    .\doctor.ps1

.EXAMPLE
    .\doctor.ps1 -Json
    Ugyanaz gépi feldolgozásra, hibakereséshez.
#>
[CmdletBinding()]
param(
    [switch]$Json,
    [string]$KitPath = $PSScriptRoot
)

$ErrorActionPreference = 'Continue'

. (Join-Path (Join-Path $KitPath 'lib') 'kit-common.ps1')

$rows = New-Object System.Collections.ArrayList

function Add-KitRow {
    param(
        [Parameter(Mandatory = $true)][ValidateSet('OK', 'WARN', 'FAIL')][string]$Status,
        [Parameter(Mandatory = $true)][string]$Name,
        [string]$Detail = '',
        [string]$Action = ''
    )
    [void]$rows.Add([pscustomobject]@{
            status = $Status
            name   = $Name
            detail = $Detail
            action = $Action
        })
}

$userProfile = Get-KitUserProfile
$claudeHome = Get-KitClaudeHome
$statePath = Join-KitPath -Path $claudeHome -ChildPath 'kit-state.json'
$settingsPath = Join-KitPath -Path $claudeHome -ChildPath 'settings.json'

$state = Read-KitState -Path $statePath
$level = Resolve-KitLevel -State $state -Requested 0
$projectDir = Get-KitProjectDir
if ((Test-KitProperty -Object $state -Name 'project_dir') -and $state.project_dir) {
    $projectDir = [string]$state.project_dir
}
$scriptsDir = Join-KitPath -Path $projectDir -ChildPath 'scripts'

$flagGmail = $true
$flagNav = $true
$flagSchedule = $true
if (Test-KitProperty -Object $state -Name 'flags') {
    if (Test-KitProperty -Object $state.flags -Name 'gmail') { $flagGmail = [bool]$state.flags.gmail }
    if (Test-KitProperty -Object $state.flags -Name 'nav') { $flagNav = [bool]$state.flags.nav }
    if (Test-KitProperty -Object $state.flags -Name 'schedule') { $flagSchedule = [bool]$state.flags.schedule }
}

# --- 1. Alap eszközök -----------------------------------------------------

if (Test-KitCommand -Name 'claude') {
    Add-KitRow -Status 'OK' -Name 'claude' -Detail (Get-KitToolVersion -Name 'claude')
} else {
    Add-KitRow -Status 'FAIL' -Name 'claude' -Detail 'nincs a PATH-on' `
        -Action 'Futtasd újra a telepítőt, vagy nyiss új terminált: .\install.ps1'
}

$python = Get-KitPythonInfo
if ($python.IsOk) {
    Add-KitRow -Status 'OK' -Name 'python' -Detail ($python.Version + '  ' + $python.Source)
} elseif ($python.IsStoreStub) {
    Add-KitRow -Status 'FAIL' -Name 'python' -Detail 'a Microsoft Store helyettesítője válaszol' `
        -Action ('Beállítások > Alkalmazások > Alkalmazások speciális beállításai > ' +
        'Alkalmazásvégrehajtási aliasok: kapcsold ki a python.exe aliast, majd .\install.ps1')
} elseif (-not $python.Found) {
    Add-KitRow -Status 'FAIL' -Name 'python' -Detail 'nincs a PATH-on' `
        -Action 'Futtasd: .\install.ps1'
} else {
    Add-KitRow -Status 'FAIL' -Name 'python' -Detail ($python.Version + ' (3.12 vagy újabb kell)') `
        -Action 'Futtasd: .\install.ps1'
}

if (Test-KitCommand -Name 'uv') {
    Add-KitRow -Status 'OK' -Name 'uv' -Detail (Get-KitToolVersion -Name 'uv')
} else {
    Add-KitRow -Status 'FAIL' -Name 'uv' -Detail 'nincs a PATH-on' `
        -Action 'Futtasd: .\install.ps1'
}

if ($flagGmail) {
    if (Test-KitCommand -Name 'node') {
        Add-KitRow -Status 'OK' -Name 'node' -Detail (Get-KitToolVersion -Name 'node')
    } else {
        Add-KitRow -Status 'FAIL' -Name 'node' -Detail 'nincs a PATH-on, a Gmail MCP nem indul' `
            -Action 'Futtasd: .\install.ps1'
    }
}

if (Test-KitCommand -Name 'git') {
    Add-KitRow -Status 'OK' -Name 'git' -Detail (Get-KitToolVersion -Name 'git')
} else {
    Add-KitRow -Status 'WARN' -Name 'git' -Detail 'nincs telepítve' `
        -Action 'Nem kötelező. A hookok PowerShell alatt is futnak.'
}

# --- 2. MCP szerverek -----------------------------------------------------

$requiredServers = @('gmail', 'excel')
if ($level -ge 2) { $requiredServers += 'microsoft-learn' }
if ($level -ge 3) { $requiredServers += @('powerbi-modeling', 'ms365') }

$mcpText = $null
if (Test-KitCommand -Name 'claude') {
    try { $mcpText = (& claude mcp list 2>&1 | Out-String) } catch { $mcpText = $null }
}
if (-not $mcpText) {
    Add-KitRow -Status 'WARN' -Name 'MCP szerverek' -Detail 'a claude mcp list nem futtatható' `
        -Action 'Nyiss új terminált, és próbáld: claude mcp list'
} else {
    foreach ($name in $requiredServers) {
        $line = ($mcpText -split "`r?`n" | Where-Object { $_ -match ('^\s*' + [regex]::Escape($name) + '\s*:') } | Select-Object -First 1)
        if (-not $line) {
            Add-KitRow -Status 'FAIL' -Name "MCP: $name" -Detail 'nincs bejegyezve' `
                -Action ".\mcp\register-mcps.ps1 -Level $level"
        } elseif ($line -match 'Failed|Needs authentication|Disabled') {
            Add-KitRow -Status 'WARN' -Name "MCP: $name" -Detail $line.Trim() `
                -Action 'Indítsd el a claude parancsot, és nézd meg a /mcp képernyőt.'
        } else {
            Add-KitRow -Status 'OK' -Name "MCP: $name" -Detail $line.Trim()
        }
    }
}

# --- 3. Titkok ------------------------------------------------------------

$secretScript = Join-KitPath -Path $scriptsDir -ChildPath 'get_secret.py'
if (-not (Test-Path -LiteralPath $secretScript -PathType Leaf)) {
    Add-KitRow -Status 'WARN' -Name 'titkok' -Detail 'a get_secret.py nincs a helyén' `
        -Action 'Futtasd: .\install.ps1'
} elseif (-not (Test-KitCommand -Name 'uv')) {
    Add-KitRow -Status 'WARN' -Name 'titkok' -Detail 'uv nélkül nem tudom lekérdezni' -Action 'Futtasd: .\install.ps1'
} else {
    $secretText = ''
    Push-Location $projectDir
    try { $secretText = (& uv run 'scripts\get_secret.py' check 2>&1 | Out-String) } catch { $secretText = '' }
    Pop-Location
    $seen = 0
    foreach ($line in ($secretText -split "`r?`n")) {
        if ($line -notmatch '^(szamlazz\.hu|nav\.gov\.hu)\s*/\s*([a-z0-9-]+)\s+(\S+)') { continue }
        $seen++
        $service = $Matches[1]
        $name = $Matches[2]
        $stateText = $Matches[3]
        $label = "titok: $service / $name"
        if ($stateText -like 'megvan*') {
            Add-KitRow -Status 'OK' -Name $label -Detail 'megvan'
        } elseif (($service -eq 'nav.gov.hu') -and (-not $flagNav)) {
            Add-KitRow -Status 'WARN' -Name $label -Detail 'nincs megadva (NAV kihagyva)' `
                -Action "Csak a 2. szintű NAV bővítéshez kell: uv run scripts\get_secret.py set $service $name"
        } else {
            Add-KitRow -Status 'FAIL' -Name $label -Detail 'hiányzik' `
                -Action "uv run scripts\get_secret.py set $service $name"
        }
    }
    if ($seen -eq 0) {
        Add-KitRow -Status 'WARN' -Name 'titkok' -Detail 'nem tudtam kiolvasni az állapotot' `
            -Action 'Futtasd kézzel: uv run scripts\get_secret.py check'
    }
}

# --- 4. settings.json és hookok -------------------------------------------

$settings = $null
$settingsOk = $false
if (-not (Test-Path -LiteralPath $settingsPath -PathType Leaf)) {
    Add-KitRow -Status 'FAIL' -Name 'settings.json' -Detail 'nincs meg' -Action 'Futtasd: .\install.ps1'
} else {
    try {
        $settings = Read-KitJsonFile -Path $settingsPath
        $settingsOk = $true
        Add-KitRow -Status 'OK' -Name 'settings.json' -Detail 'beolvasható'
    } catch {
        Add-KitRow -Status 'FAIL' -Name 'settings.json' -Detail 'hibás JSON' `
            -Action "Állítsd vissza a mentésből: $settingsPath.bak"
    }
}

$expectedHooks = @('prime_nudge.py', 'session_tips.py', 'protect_delivery.py')
if ($level -ge 2) { $expectedHooks += 'memory_backup.py' }

$settingsText = ''
if ($settingsOk) { $settingsText = (ConvertTo-Json -InputObject $settings -Depth 20) }
foreach ($hookFile in $expectedHooks) {
    $hookPath = Join-KitPath -Path $claudeHome -ChildPath ('hooks/' + $hookFile)
    if (-not $settingsOk) {
        Add-KitRow -Status 'FAIL' -Name "hook: $hookFile" -Detail 'settings.json nem olvasható' `
            -Action 'Futtasd: .\install.ps1'
    } elseif ($settingsText -notlike "*$hookFile*") {
        Add-KitRow -Status 'FAIL' -Name "hook: $hookFile" -Detail 'nincs a settings.json-ben' `
            -Action 'Futtasd: .\install.ps1'
    } elseif (-not (Test-Path -LiteralPath $hookPath -PathType Leaf)) {
        Add-KitRow -Status 'FAIL' -Name "hook: $hookFile" -Detail 'a fájl hiányzik' `
            -Action 'Futtasd: .\install.ps1'
    } else {
        Add-KitRow -Status 'OK' -Name "hook: $hookFile" -Detail 'bejegyezve és megvan'
    }
}
if ($level -lt 2) {
    Add-KitRow -Status 'OK' -Name 'hook: memory_backup.py' -Detail 'a 2. szinttől kapcsol be'
}

# --- 5. Adatbázis ---------------------------------------------------------

$dbPath = Join-KitPath -Path $projectDir -ChildPath 'data/invoices.db'
$syncScript = Join-KitPath -Path $scriptsDir -ChildPath 'szamlazz_sync.py'
if (-not (Test-Path -LiteralPath $dbPath -PathType Leaf)) {
    Add-KitRow -Status 'WARN' -Name 'invoices.db' -Detail 'még nincs adatbázis' `
        -Action 'Hozd létre: cd Riportok ; uv run scripts\szamlazz_sync.py init'
} elseif ((Test-Path -LiteralPath $syncScript -PathType Leaf) -and (Test-KitCommand -Name 'uv')) {
    $statusText = ''
    Push-Location $projectDir
    try { $statusText = (& uv run 'scripts\szamlazz_sync.py' status 2>&1 | Out-String) } catch { $statusText = '' }
    Pop-Location
    $head = (($statusText -split "`r?`n" | Where-Object { $_.Trim() }) | Select-Object -First 4) -join ' | '
    if ($head) {
        Add-KitRow -Status 'OK' -Name 'invoices.db' -Detail $head
    } else {
        Add-KitRow -Status 'WARN' -Name 'invoices.db' -Detail 'megvan, de a status nem adott kimenetet' `
            -Action 'Futtasd kézzel: cd Riportok ; uv run scripts\szamlazz_sync.py status'
    }
} else {
    Add-KitRow -Status 'OK' -Name 'invoices.db' -Detail 'megvan'
}

# --- 6. Kiadási mappák ----------------------------------------------------

$slugs = Get-KitReportSlugs -ProjectDir $projectDir
if ($slugs.Count -eq 0) {
    Add-KitRow -Status 'OK' -Name 'riportok' -Detail 'még nincs riport definíció' `
        -Action ''
} else {
    foreach ($slug in $slugs) {
        $specPath = Join-KitPath -Path $projectDir -ChildPath "reports/$slug/spec.yaml"
        $folders = Get-KitSpecFolders -SpecPath $specPath -ProjectDir $projectDir
        if ($folders.Count -eq 0) {
            Add-KitRow -Status 'WARN' -Name "riport: $slug" -Detail 'nincs delivery.folder a specben' `
                -Action "Nyisd meg: $specPath"
            continue
        }
        foreach ($folder in $folders) {
            if (-not (Test-Path -LiteralPath $folder -PathType Container)) {
                Add-KitRow -Status 'FAIL' -Name "mappa: $slug" -Detail "nincs meg: $folder" `
                    -Action "Hozd létre a mappát, vagy javítsd a spec.yaml delivery.folder értékét."
            } elseif (Test-KitFolderWritable -Path $folder) {
                Add-KitRow -Status 'OK' -Name "mappa: $slug" -Detail $folder
            } else {
                Add-KitRow -Status 'FAIL' -Name "mappa: $slug" -Detail "nem írható: $folder" `
                    -Action 'Zárd be a mappában nyitva lévő Excel fájlokat, és ellenőrizd a jogosultságot.'
            }
        }
    }
}

# --- 7. Ütemezett feladat -------------------------------------------------

if (-not $flagSchedule) {
    Add-KitRow -Status 'WARN' -Name 'ütemezett futtatás' -Detail 'ki van kapcsolva (-SkipSchedule)' `
        -Action 'Bekapcsolás: .\install.ps1'
} else {
    $task = Get-KitScheduledTaskInfo -TaskPath '\Controller\' -TaskName 'HaviRiport'
    if (-not $task) {
        Add-KitRow -Status 'FAIL' -Name 'ütemezett futtatás' -Detail 'a \Controller\HaviRiport feladat nincs meg' `
            -Action 'Futtasd: .\install.ps1'
    } elseif ($task.State -eq 'Disabled') {
        Add-KitRow -Status 'FAIL' -Name 'ütemezett futtatás' -Detail 'a feladat le van tiltva' `
            -Action 'Feladatütemező > Controller > HaviRiport > Engedélyezés'
    } else {
        $detail = "állapot: $($task.State)"
        if ($task.NextRunTime) { $detail += ", következő futás: $($task.NextRunTime)" }
        Add-KitRow -Status 'OK' -Name 'ütemezett futtatás' -Detail $detail
    }
}

# --- 8. Gmail fiókok ------------------------------------------------------

if (-not $flagGmail) {
    Add-KitRow -Status 'WARN' -Name 'Gmail' -Detail 'ki van kapcsolva (-SkipGmail)' -Action ''
} else {
    $configDir = Join-KitPath -Path $userProfile -ChildPath '.gmail-mcp'
    $accountsFile = Join-KitPath -Path $configDir -ChildPath 'accounts.json'
    $accountsDir = Join-KitPath -Path $configDir -ChildPath 'accounts'
    $accounts = New-Object System.Collections.ArrayList
    $config = Read-KitJsonFile -Path $accountsFile
    if ((Test-KitProperty -Object $config -Name 'accounts') -and $config.accounts) {
        foreach ($property in $config.accounts.PSObject.Properties) { [void]$accounts.Add($property.Name) }
    }
    if (($accounts.Count -eq 0) -and (Test-Path -LiteralPath $accountsDir -PathType Container)) {
        foreach ($dir in (Get-ChildItem -LiteralPath $accountsDir -Directory -ErrorAction SilentlyContinue)) {
            [void]$accounts.Add($dir.Name)
        }
    }

    if ($accounts.Count -eq 0) {
        Add-KitRow -Status 'FAIL' -Name 'Gmail fiókok' -Detail 'nincs beállított fiók' `
            -Action 'Futtasd: .\mcp\gmail-setup.ps1'
    } else {
        Add-KitRow -Status 'OK' -Name 'Gmail fiókok' -Detail ($accounts -join ', ')
        foreach ($account in $accounts) {
            $accountDir = Join-KitPath -Path $accountsDir -ChildPath $account
            # A fork mindig credentials.json-be írja a jogkivonatot; a token.json
            # a régi, egyfiókos elrendezés neve, biztonságból azt is megnézzük.
            $tokenFile = $null
            foreach ($candidate in @('credentials.json', 'token.json')) {
                $path = Join-KitPath -Path $accountDir -ChildPath $candidate
                if (Test-Path -LiteralPath $path -PathType Leaf) { $tokenFile = $path; break }
            }
            if (-not $tokenFile) {
                Add-KitRow -Status 'FAIL' -Name "Gmail: $account" -Detail 'nincs jogkivonat fájl' `
                    -Action "Jelentkezz be újra: cd `"$(Get-KitGmailServerDir)`" ; node dist\index.js auth --keys `"...`""
                continue
            }
            $ageDays = [int]((Get-Date) - (Get-Item -LiteralPath $tokenFile).LastWriteTime).TotalDays
            if ($ageDays -gt 5) {
                Add-KitRow -Status 'WARN' -Name "Gmail: $account" -Detail "a jogkivonat $ageDays napos" `
                    -Action ('Testing állapotú OAuth képernyőnél a jogkivonat 7 nap után lejár. ' +
                    'Állítsd In production állapotba, vagy jelentkezz be újra.')
            } else {
                Add-KitRow -Status 'OK' -Name "Gmail: $account" -Detail "a jogkivonat $ageDays napos"
            }
        }
    }
}

# --- 9. Szint és verzió ---------------------------------------------------

$kitVersion = Get-KitVersion -KitPath $KitPath
if (-not $state) {
    Add-KitRow -Status 'FAIL' -Name 'kit-state.json' -Detail 'nincs meg' -Action 'Futtasd: .\install.ps1'
} else {
    $stateVersion = ''
    if (Test-KitProperty -Object $state -Name 'kit_version') { $stateVersion = [string]$state.kit_version }
    if ($stateVersion -eq $kitVersion) {
        Add-KitRow -Status 'OK' -Name 'készlet' -Detail "verzió $kitVersion, szint $level"
    } else {
        Add-KitRow -Status 'WARN' -Name 'készlet' -Detail "telepítve: $stateVersion, elérhető: $kitVersion" `
            -Action 'Futtasd: .\update.ps1'
    }
}

# --- Kiírás ---------------------------------------------------------------

if ($Json) {
    $payload = [pscustomobject]@{
        kit_version = $kitVersion
        level       = $level
        project_dir = $projectDir
        checked_at  = (Get-KitIsoTimestamp)
        rows        = [object[]]$rows.ToArray()
    }
    Write-Output (ConvertTo-Json -InputObject $payload -Depth 20)
    exit 0
}

$symbols = @{ 'OK' = '[OK]'; 'WARN' = '[!] '; 'FAIL' = '[X] ' }
$colors = @{ 'OK' = 'Green'; 'WARN' = 'Yellow'; 'FAIL' = 'Red' }
$width = 2
foreach ($row in $rows) { if ($row.name.Length -gt $width) { $width = $row.name.Length } }

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Állapot: verzió $kitVersion, szint $level" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

foreach ($row in $rows) {
    $line = "{0} {1}  {2}" -f $symbols[$row.status], $row.name.PadRight($width), $row.detail
    Write-Host $line -ForegroundColor $colors[$row.status]
    if (($row.status -ne 'OK') -and $row.action) {
        Write-Host ("     mit tegyél: " + $row.action) -ForegroundColor Gray
    }
}

$failCount = @($rows | Where-Object { $_.status -eq 'FAIL' }).Count
$warnCount = @($rows | Where-Object { $_.status -eq 'WARN' }).Count
Write-Host ""
if ($failCount -eq 0 -and $warnCount -eq 0) {
    Write-Host "Minden rendben." -ForegroundColor Green
} else {
    Write-Host "Hiba: $failCount, figyelmeztetés: $warnCount" -ForegroundColor Yellow
}
Write-Host ""

exit 0
