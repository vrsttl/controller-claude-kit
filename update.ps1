<#
.SYNOPSIS
    Frissíti a készletet: git pull, majd install.ps1 -Update.

.DESCRIPTION
    Ugyanazokat a kapcsolókat fogadja, mint az install.ps1, és továbbadja őket.
    A pull csak gyorsítás (fast-forward): ha helyben módosítottad a készletet,
    a parancs hibát ad, és nem ír felül semmit.

.EXAMPLE
    .\update.ps1
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [switch]$NoAdmin,
    [switch]$SkipGmail,
    [switch]$SkipNav,
    [switch]$SkipSchedule,
    [int]$Level = 0,
    [string]$KitPath = $PSScriptRoot
)

$ErrorActionPreference = 'Stop'

. (Join-Path (Join-Path $KitPath 'lib') 'kit-common.ps1')

$dryRun = [bool]$WhatIfPreference

Write-Step 'Készlet frissítése (git pull)'
if (-not (Test-KitCommand -Name 'git')) {
    Write-Warn 'A git nem található, a letöltést kihagyom, csak újratelepítek.'
} elseif (-not (Test-Path -LiteralPath (Join-KitPath -Path $KitPath -ChildPath '.git'))) {
    Write-Warn 'Ez a mappa nem git tároló, a letöltést kihagyom.'
} elseif ($dryRun) {
    Write-Plan "git -C `"$KitPath`" pull --ff-only"
} elseif ($PSCmdlet.ShouldProcess($KitPath, 'git pull --ff-only')) {
    & git -C $KitPath pull --ff-only
    if ($LASTEXITCODE -ne 0) {
        Write-Warn ('A git pull nem sikerült. Ha helyben módosítottad a készletet, ' +
            'először mentsd el a változtatásaidat, majd futtasd újra.')
        exit 1
    }
    Write-Success 'a készlet naprakész'
}

$installScript = Join-KitPath -Path $KitPath -ChildPath 'install.ps1'
if (-not (Test-Path -LiteralPath $installScript -PathType Leaf)) {
    Write-Fail "Nem találom: $installScript"
    exit 1
}

& $installScript -Update -KitPath $KitPath -NoAdmin:$NoAdmin -SkipGmail:$SkipGmail `
    -SkipNav:$SkipNav -SkipSchedule:$SkipSchedule -Level $Level -WhatIf:$dryRun
exit $LASTEXITCODE
