# Tests for the pure helpers in lib/kit-common.ps1: manifest compare, the copy
# semantics, kit-state preservation and the spec.yaml folder scanner. Nothing
# here touches winget, the network or the Task Scheduler; the last block asserts
# that every wrapper around those keeps its -DryRun escape hatch.
#
#   pwsh -NoProfile -File tests/test_kit_common.ps1

$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot
. (Join-Path $repoRoot (Join-Path 'lib' 'kit-common.ps1'))

$failures = New-Object System.Collections.ArrayList
$tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("kit-common-" + [guid]::NewGuid().ToString('N'))
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

function New-TextFile {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][AllowEmptyString()][string]$Text
    )
    $dir = Split-Path -Parent $Path
    if ($dir -and -not (Test-Path -LiteralPath $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
    }
    [System.IO.File]::WriteAllText($Path, $Text, (New-Object System.Text.UTF8Encoding($false)))
    return $Path
}

function Get-Text {
    param([Parameter(Mandatory = $true)][string]$Path)
    return (Get-Content -LiteralPath $Path -Raw -Encoding UTF8)
}

try {
    # --- 1. Compare-KitFile ------------------------------------------------
    Write-Host "1. Compare-KitFile"
    $probeDir = Join-Path $tempRoot 'probe'
    $newFile = New-TextFile -Path (Join-Path $probeDir 'new.txt') -Text 'v2'
    $oldFile = New-TextFile -Path (Join-Path $probeDir 'old.txt') -Text 'v1'
    $hashV2 = Get-KitFileHash -Path $newFile
    $hashV1 = Get-KitFileHash -Path $oldFile

    Test-Assert ((Compare-KitFile -TargetPath (Join-Path $probeDir 'nope.txt') -ExpectedHash $hashV2) -eq 'missing') 'hianyzo fajl: missing'
    Test-Assert ((Compare-KitFile -TargetPath $newFile -ExpectedHash $hashV2) -eq 'same') 'azonos hash: same'
    Test-Assert ((Compare-KitFile -TargetPath $oldFile -ExpectedHash $hashV2 -PreviousHash $hashV1) -eq 'kit-updated') 'a keszlet frissult: kit-updated'
    Test-Assert ((Compare-KitFile -TargetPath $oldFile -ExpectedHash $hashV2 -PreviousHash 'deadbeef') -eq 'user-modified') 'o szerkesztette: user-modified'
    Test-Assert ((Compare-KitFile -TargetPath $oldFile -ExpectedHash $hashV2) -eq 'user-modified') 'elozo manifest nelkul: user-modified'

    # --- 2. Copy-KitSection ------------------------------------------------
    Write-Host "2. Copy-KitSection (home)"
    $kitPath = Join-Path $tempRoot 'kit'
    $claudeHome = Join-Path $tempRoot 'claude'
    $backupRoot = Join-Path $claudeHome '.kit-backups'
    $stamp = '20260906-101500'

    New-TextFile -Path (Join-Path $kitPath 'home/CLAUDE.md') -Text 'v2 CLAUDE' | Out-Null
    New-TextFile -Path (Join-Path $kitPath 'home/rules/same.md') -Text 'v2 same' | Out-Null
    New-TextFile -Path (Join-Path $kitPath 'home/rules/kit-moved.md') -Text 'v2 kit' | Out-Null
    New-TextFile -Path (Join-Path $kitPath 'home/rules/she-edited.md') -Text 'v2 she' | Out-Null

    $manifestFiles = @{}
    foreach ($key in @('home/CLAUDE.md', 'home/rules/same.md', 'home/rules/kit-moved.md', 'home/rules/she-edited.md')) {
        $manifestFiles[$key] = Get-KitFileHash -Path (Join-Path $kitPath $key)
    }

    # target state: CLAUDE.md missing, same.md up to date, kit-moved.md still on
    # the previous kit version, she-edited.md carries her own text.
    New-TextFile -Path (Join-Path $claudeHome 'rules/same.md') -Text 'v2 same' | Out-Null
    New-TextFile -Path (Join-Path $claudeHome 'rules/kit-moved.md') -Text 'v1 kit' | Out-Null
    New-TextFile -Path (Join-Path $claudeHome 'rules/she-edited.md') -Text 'ezt en irtam' | Out-Null

    $previousFiles = @{
        'home/rules/kit-moved.md'  = (Get-KitFileHash -Path (Join-Path $claudeHome 'rules/kit-moved.md'))
        'home/rules/she-edited.md' = $hashV1
    }

    $result = Copy-KitHome -KitPath $kitPath -ManifestFiles $manifestFiles `
        -PreviousFiles $previousFiles -ClaudeHome $claudeHome -BackupRoot $backupRoot -BackupStamp $stamp

    Test-Assert (@($result.Created) -contains 'CLAUDE.md') 'hianyzo fajl letrejott'
    Test-Assert (@($result.Unchanged) -contains 'rules/same.md') 'azonos fajl valtozatlan'
    Test-Assert (@($result.Updated) -contains 'rules/kit-moved.md') 'keszlet altal frissitett fajl felulirva'
    Test-Assert (@($result.BackedUp) -notcontains 'rules/kit-moved.md') 'keszlet altal frissitett fajlrol nem kell mentes'
    Test-Assert (@($result.BackedUp) -contains 'rules/she-edited.md') 'az o modositasarol keszult mentes'
    Test-Assert (@($result.Updated) -contains 'rules/she-edited.md') 'mentes utan felulirva'

    Test-Assert ((Get-Text -Path (Join-Path $claudeHome 'CLAUDE.md')) -eq 'v2 CLAUDE') 'az uj fajl tartalma helyes'
    Test-Assert ((Get-Text -Path (Join-Path $claudeHome 'rules/kit-moved.md')) -eq 'v2 kit') 'a frissitett fajl tartalma helyes'
    $backupFile = Join-Path $backupRoot (Join-Path $stamp 'home/rules/she-edited.md')
    Test-Assert (Test-Path -LiteralPath $backupFile) "mentes a vart helyen: .kit-backups/$stamp/home/rules/she-edited.md"
    Test-Assert ((Get-Text -Path $backupFile) -eq 'ezt en irtam') 'a mentes az o szovegét tartalmazza'

    Write-Host "2b. masodik futtatas nem valtoztat"
    $again = Copy-KitHome -KitPath $kitPath -ManifestFiles $manifestFiles `
        -PreviousFiles $manifestFiles -ClaudeHome $claudeHome -BackupRoot $backupRoot -BackupStamp '20260906-101600'
    Test-Assert ($again.Unchanged.Count -eq 4) "masodszor minden valtozatlan (kapott: $($again.Unchanged.Count))"
    Test-Assert ($again.Updated.Count -eq 0 -and $again.BackedUp.Count -eq 0) 'masodszor nincs iras es nincs mentes'

    # --- 3. CreateOnly and KeepDrifted -------------------------------------
    Write-Host "3. Riportok masolasi szabalyok"
    $projectDir = Join-Path $tempRoot 'Riportok'
    New-TextFile -Path (Join-Path $kitPath 'templates/project/CLAUDE.md') -Text 'kit projekt szoveg' | Out-Null
    New-TextFile -Path (Join-Path $kitPath 'templates/project/reports/_examples/demo/spec.yaml') -Text 'report: {}' | Out-Null
    New-TextFile -Path (Join-Path $kitPath 'templates/project/reports/.keep') -Text '' | Out-Null

    $templateFiles = @{}
    foreach ($key in @('templates/project/CLAUDE.md', 'templates/project/reports/_examples/demo/spec.yaml', 'templates/project/reports/.keep')) {
        $templateFiles[$key] = Get-KitFileHash -Path (Join-Path $kitPath $key)
    }

    New-TextFile -Path (Join-Path $projectDir 'CLAUDE.md') -Text 'sajat projekt szoveg' | Out-Null
    New-TextFile -Path (Join-Path $projectDir 'reports/_examples/demo/spec.yaml') -Text 'regi pelda' | Out-Null
    New-TextFile -Path (Join-Path $projectDir 'reports/.keep') -Text 'ne nyulj hozza' | Out-Null

    $templateResult = Copy-KitSection -KitPath $kitPath -ManifestFiles $templateFiles `
        -PreviousFiles @{} -Prefix 'templates/project/' -TargetRoot $projectDir `
        -BackupRoot $backupRoot -BackupStamp $stamp `
        -CreateOnly @('reports/') -CreateOnlyExcept @('reports/_examples/') `
        -KeepDrifted @('CLAUDE.md')

    Test-Assert (@($templateResult.Kept) -contains 'CLAUDE.md') 'az o projekt CLAUDE.md-je megmaradt'
    Test-Assert (@($templateResult.BackedUp) -contains 'CLAUDE.md') 'de keszult rola mentes'
    Test-Assert ((Get-Text -Path (Join-Path $projectDir 'CLAUDE.md')) -eq 'sajat projekt szoveg') 'a projekt CLAUDE.md tartalma valtozatlan'
    Test-Assert (@($templateResult.Skipped) -contains 'reports/.keep') 'a reports/ alatti sajat fajl erintetlen'
    Test-Assert ((Get-Text -Path (Join-Path $projectDir 'reports/.keep')) -eq 'ne nyulj hozza') 'a reports/ alatti fajl tartalma valtozatlan'
    Test-Assert (@($templateResult.Updated) -contains 'reports/_examples/demo/spec.yaml') 'a reports/_examples/ a keszlete, frissul'

    # --- 4. kit-state.json -------------------------------------------------
    Write-Host "4. kit-state.json"
    $statePath = Join-Path $tempRoot 'kit-state.json'
    $first = Write-KitState -Path $statePath -KitVersion '0.1.0' -Level 1 -KitPath 'C:\Users\fanni\claude-kit' `
        -ProjectDir 'C:\Users\fanni\Riportok' -Flags @{ gmail = $true; nav = $false; schedule = $true }

    $onDisk = Read-KitJsonFile -Path $statePath
    $keys = @($onDisk.PSObject.Properties.Name)
    $expectedKeys = @('kit_version', 'level', 'installed_at', 'updated_at', 'kit_path', 'project_dir', 'tips_seen', 'flags')
    Test-Assert (($keys -join ',') -eq ($expectedKeys -join ',')) "a kulcsok es a sorrendjuk pontosak (kapott: $($keys -join ','))"
    Test-Assert ($onDisk.level -eq 1) 'level 1'
    Test-Assert ($onDisk.tips_seen -eq 0) 'tips_seen 0 az elso telepiteskor'
    Test-Assert ($onDisk.flags.gmail -eq $true -and $onDisk.flags.nav -eq $false -and $onDisk.flags.schedule -eq $true) 'a flags ertekei helyesek'
    Test-Assert (@($onDisk.flags.PSObject.Properties.Name) -join ',' -eq 'gmail,nav,schedule') 'a flags kulcsai pontosak'

    # she used the kit for a while: tips_seen moved on
    $onDisk.tips_seen = 7
    Write-KitJsonFile -Path $statePath -Value $onDisk
    Start-Sleep -Milliseconds 1100
    $second = Write-KitState -Path $statePath -KitVersion '0.2.0' -Level 2 -KitPath 'C:\Users\fanni\claude-kit' `
        -ProjectDir 'C:\Users\fanni\Riportok' -Flags @{ gmail = $true; nav = $true; schedule = $false }
    $reread = Read-KitJsonFile -Path $statePath

    Test-Assert ($reread.installed_at -eq $first.installed_at) 'az installed_at megmaradt'
    Test-Assert ($reread.tips_seen -eq 7) 'a tips_seen megmaradt'
    Test-Assert ($reread.level -eq 2) 'a level frissult'
    Test-Assert ($reread.kit_version -eq '0.2.0') 'a kit_version frissult'
    Test-Assert ($reread.updated_at -ne $first.updated_at) 'az updated_at frissult'
    Test-Assert ($reread.flags.schedule -eq $false) 'a flags frissult'
    Test-Assert ($second.installed_at -eq $first.installed_at) 'a visszaadott objektum is orzi az installed_at-et'

    Write-Host "4b. -DryRun nem ir"
    $dryPath = Join-Path $tempRoot 'dry-state.json'
    Write-KitState -Path $dryPath -KitVersion '0.1.0' -Level 1 -KitPath 'x' -ProjectDir 'y' -DryRun | Out-Null
    Test-Assert (-not (Test-Path -LiteralPath $dryPath)) 'a -DryRun nem hozott letre fajlt'

    # --- 5. Resolve-KitLevel ----------------------------------------------
    Write-Host "5. Resolve-KitLevel"
    Test-Assert ((Resolve-KitLevel -State $null -Requested 0) -eq 1) 'allapot nelkul 1. szint'
    Test-Assert ((Resolve-KitLevel -State $reread -Requested 0) -eq 2) 'a meglevo szintet orzi'
    Test-Assert ((Resolve-KitLevel -State $reread -Requested 3) -eq 3) 'a -Level felulirja'

    # --- 6. spec.yaml folder scanner --------------------------------------
    Write-Host "6. Get-KitSpecFolders"
    $specDir = Join-Path $tempRoot 'Riportok/reports/havi'
    $deliveryFolder = Join-Path $tempRoot 'kiadas'
    New-Item -ItemType Directory -Path $deliveryFolder -Force | Out-Null
    $specText = @"
report:
  slug: havi
output:
  executive:
    folder: nem_ez
delivery:
  folder: "$($deliveryFolder.Replace('\', '/'))"   # ide kerul a kesz fajl
  overwrite: never
powerbi:
  enabled: true
  folder: exports/powerbi
"@
    New-TextFile -Path (Join-Path $specDir 'spec.yaml') -Text $specText | Out-Null
    $folders = Get-KitSpecFolders -SpecPath (Join-Path $specDir 'spec.yaml') -ProjectDir (Join-Path $tempRoot 'Riportok')
    Test-Assert ($folders.Count -eq 2) "ket mappa (kapott: $($folders.Count))"
    Test-Assert (@($folders | Where-Object { $_ -notlike '*nem_ez*' }).Count -eq 2) 'az output.executive.folder nem kerul bele'
    Test-Assert (@($folders | Where-Object { $_ -like '*powerbi*' }).Count -eq 1) 'a relativ powerbi mappa is bekerult'
    Test-Assert (($folders | Where-Object { $_ -like '*powerbi*' }) -like "*$($tempRoot)*") 'a relativ utat a projekt mappahoz oldottuk fel'
    Test-Assert (Test-KitFolderWritable -Path $deliveryFolder) 'a kiadasi mappa irhato'
    Test-Assert (-not (Test-KitFolderWritable -Path (Join-Path $tempRoot 'nincs-ilyen'))) 'nem letezo mappa nem irhato'

    Write-Host "6b. Get-KitReportSlugs"
    $slugs = Get-KitReportSlugs -ProjectDir (Join-Path $tempRoot 'Riportok')
    Test-Assert ($slugs.Count -eq 1 -and $slugs[0] -eq 'havi') "a _examples kimarad, marad: $($slugs -join ',')"

    # --- 7. Windows-only wrappers stay behind -DryRun ----------------------
    Write-Host "7. Windows-fuggo hivasok burkolo fuggvenyei"
    $wrappers = @(
        'Invoke-KitWinget',
        'Invoke-KitWebInstall',
        'Install-KitUv',
        'New-KitMonthlyTrigger',
        'Register-KitMonthlyTask',
        'Copy-KitSection',
        'Copy-KitHome',
        'Copy-KitFile',
        'Backup-KitFile',
        'Write-KitSettings',
        'Write-KitState',
        'New-KitDirectory'
    )
    foreach ($name in $wrappers) {
        $command = Get-Command -Name $name -ErrorAction SilentlyContinue
        Test-Assert ($null -ne $command) "letezik: $name"
        if ($command) {
            Test-Assert ($command.Parameters.ContainsKey('DryRun')) "$name elfogad -DryRun kapcsolot"
        }
    }

    Write-Host "7b. a burkolok -DryRun mellett nem hivnak rendszerparancsot"
    Test-Assert ((Invoke-KitWinget -PackageId 'Fake.Package' -Name 'proba' -DryRun) -eq $true) 'Invoke-KitWinget -DryRun visszater'
    Test-Assert ((Invoke-KitWebInstall -Url 'https://example.invalid/x.ps1' -Name 'proba' -DryRun) -eq $true) 'Invoke-KitWebInstall -DryRun visszater'
    Test-Assert ($null -eq (New-KitMonthlyTrigger -DryRun)) 'New-KitMonthlyTrigger -DryRun nem epit CIM peldanyt'
    Test-Assert ($null -eq (Register-KitMonthlyTask -Execute 'uv' -WorkingDirectory $tempRoot -DryRun)) 'Register-KitMonthlyTask -DryRun nem regisztral'

    # --- 8. version and path helpers ---------------------------------------
    Write-Host "8. verzio es utvonal segedek"
    $versionKit = Join-Path $tempRoot 'versionkit'
    New-TextFile -Path (Join-Path $versionKit 'CHANGELOG.md') -Text "# Changelog`n`n## [Unreleased]`n`n## [1.2.3] - 2026-09-06`n" | Out-Null
    Test-Assert ((Get-KitVersion -KitPath $versionKit) -eq '1.2.3') 'a CHANGELOG elso verzio fejlecet olvassa'
    Write-KitJsonFile -Path (Join-Path $versionKit 'manifest.json') -Value ([pscustomobject]@{ kit_version = '9.9.9'; files = [pscustomobject]@{} })
    Test-Assert ((Get-KitVersion -KitPath $versionKit) -eq '9.9.9') 'a manifest.json erosebb a CHANGELOG-nal'

    Test-Assert ((Convert-KitRelative -PosixPath 'a/b/c.md') -eq ('a' + [System.IO.Path]::DirectorySeparatorChar + 'b' + [System.IO.Path]::DirectorySeparatorChar + 'c.md')) 'Convert-KitRelative platformfuggo elvalasztot hasznal'
    Test-Assert (Test-KitPathPrefix -Relative 'reports/havi/spec.yaml' -Prefixes @('reports/')) 'Test-KitPathPrefix eltalalja az elotagot'
    Test-Assert (-not (Test-KitPathPrefix -Relative 'reportsxyz/a.md' -Prefixes @('reports/'))) 'Test-KitPathPrefix nem talal hamis egyezest'
} finally {
    Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Host ""
if ($failures.Count -gt 0) {
    Write-Host "FAIL: $($failures.Count) allitas bukott el." -ForegroundColor Red
    foreach ($item in $failures) { Write-Host "  - $item" -ForegroundColor Red }
    exit 1
}
Write-Host "PASS: kit-common" -ForegroundColor Green
exit 0
