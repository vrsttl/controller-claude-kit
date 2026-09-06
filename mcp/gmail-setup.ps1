<#
.SYNOPSIS
    Letölti és felépíti a többfiókos Gmail MCP szervert, majd bejelentkeztet.

.DESCRIPTION
    A többfiókos támogatás csak a vrsttl/Gmail-MCP-Server tároló
    feature/multi-account-oauth-apps ágán van meg, npm-en nincs fenn. Ezért
    klónozunk, és helyben építünk.

    A jogkivonatok ide kerülnek:
      %USERPROFILE%\.gmail-mcp\accounts.json                     (fióklista)
      %USERPROFILE%\.gmail-mcp\accounts\<email>\credentials.json (jogkivonat)
      %USERPROFILE%\.gmail-mcp\accounts\<email>\oauth-keys.json  (OAuth alkalmazás)

.EXAMPLE
    .\mcp\gmail-setup.ps1

.EXAMPLE
    .\mcp\gmail-setup.ps1 -NoAuth
    Csak letölt és épít, fiókot nem ad hozzá.
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [switch]$NoAuth,
    [string]$KitPath = (Split-Path -Parent $PSScriptRoot)
)

$ErrorActionPreference = 'Stop'

. (Join-Path (Join-Path $KitPath 'lib') 'kit-common.ps1')

$dryRun = [bool]$WhatIfPreference
$repoUrl = 'https://github.com/vrsttl/Gmail-MCP-Server.git'
$branch = 'feature/multi-account-oauth-apps'
$serverDir = Get-KitGmailServerDir
$entryPoint = Join-KitPath -Path $serverDir -ChildPath 'dist/index.js'
$configDir = Join-KitPath -Path (Get-KitUserProfile) -ChildPath '.gmail-mcp'
$accountsDir = Join-KitPath -Path $configDir -ChildPath 'accounts'

function Get-KitGmailAccounts {
    $names = New-Object System.Collections.ArrayList
    $accountsFile = Join-KitPath -Path $configDir -ChildPath 'accounts.json'
    $config = Read-KitJsonFile -Path $accountsFile
    if ((Test-KitProperty -Object $config -Name 'accounts') -and $config.accounts) {
        foreach ($property in $config.accounts.PSObject.Properties) {
            [void]$names.Add($property.Name)
        }
    }
    if (($names.Count -eq 0) -and (Test-Path -LiteralPath $accountsDir -PathType Container)) {
        foreach ($dir in (Get-ChildItem -LiteralPath $accountsDir -Directory -ErrorAction SilentlyContinue)) {
            [void]$names.Add($dir.Name)
        }
    }
    return , ($names.ToArray())
}

Write-Step 'Gmail MCP szerver'

if (-not (Test-KitCommand -Name 'git')) {
    Write-Warn 'A git nem található, a Gmail MCP-t kihagyom.'
    return
}
if (-not (Test-KitCommand -Name 'node')) {
    Write-Warn 'A Node.js nem található, a Gmail MCP-t kihagyom.'
    return
}
if (-not (Test-KitCommand -Name 'npm')) {
    Write-Warn 'Az npm nem található, a Gmail MCP-t kihagyom.'
    return
}

# --- letöltés vagy frissítés ---------------------------------------------
if (Test-Path -LiteralPath (Join-KitPath -Path $serverDir -ChildPath '.git')) {
    if ($PSCmdlet.ShouldProcess($serverDir, 'git pull --ff-only')) {
        if ($dryRun) {
            Write-Plan "git -C `"$serverDir`" pull --ff-only"
        } else {
            & git -C $serverDir fetch origin $branch
            & git -C $serverDir checkout $branch
            & git -C $serverDir pull --ff-only
            Write-Success 'a szerver forráskódja naprakész'
        }
    }
} elseif ($PSCmdlet.ShouldProcess($serverDir, 'git clone')) {
    if ($dryRun) {
        Write-Plan "git clone --branch $branch $repoUrl `"$serverDir`""
    } else {
        & git clone --branch $branch $repoUrl $serverDir
        Write-Success "letöltve: $serverDir"
    }
}

# --- építés ---------------------------------------------------------------
if ($PSCmdlet.ShouldProcess($serverDir, 'npm install és npm run build')) {
    if ($dryRun) {
        Write-Plan 'npm install; npm run build'
    } else {
        Push-Location $serverDir
        try {
            & npm install
            & npm run build
        } finally {
            Pop-Location
        }
    }
}

if ($dryRun) {
    Write-Plan "ellenőrzés: $entryPoint"
    return
}

if (-not (Test-Path -LiteralPath $entryPoint -PathType Leaf)) {
    Write-Fail "Az építés után sem található: $entryPoint"
    Write-Detail "Próbáld kézzel: cd `"$serverDir`" ; npm install ; npm run build"
    return
}
Write-Success "felépítve: $entryPoint"

Write-Detail "A jogkivonatok ide kerülnek: $accountsDir\<email>\credentials.json"
Write-Warn ('Ha a Google OAuth beleegyezési képernyője Testing (Tesztelés) állapotban van, ' +
    'a jogkivonat 7 nap után lejár, és újra be kell jelentkezni. Állítsd In production ' +
    '(Éles) állapotba, vagy Workspace esetén Internal (Belső) típusra.')

$existing = Get-KitGmailAccounts
if ($existing.Count -gt 0) {
    Write-Success ("beállított fiókok: " + ($existing -join ', '))
}

if ($NoAuth) {
    Write-Detail 'Fiók hozzáadása most kihagyva (-NoAuth).'
    return
}

# --- fiókok hozzáadása ----------------------------------------------------
while ($true) {
    $answer = Read-Host 'Hozzáadsz most egy postafiókot? (i/n)'
    if ($answer -notmatch '^(i|I|y|Y)') { break }

    $keysPath = Read-Host 'Add meg a letöltött OAuth kliens JSON teljes elérési útját'
    $keysPath = $keysPath.Trim().Trim('"')
    if (-not (Test-Path -LiteralPath $keysPath -PathType Leaf)) {
        Write-Fail "Nincs ilyen fájl: $keysPath"
        continue
    }
    $keys = Read-KitJsonFile -Path $keysPath
    if (-not ((Test-KitProperty -Object $keys -Name 'installed') -or
            (Test-KitProperty -Object $keys -Name 'web'))) {
        Write-Fail ('Ez nem OAuth kliens fájl: hiányzik belőle az "installed" vagy a "web" ' +
            'kulcs. A Google Cloud Console-ban a Credentials oldalon töltsd le újra.')
        continue
    }

    Write-Detail 'Megnyílik a böngésző, jelentkezz be a postafiókkal, és engedélyezd a hozzáférést.'
    Push-Location $serverDir
    try {
        & node 'dist\index.js' auth --keys $keysPath
    } finally {
        Pop-Location
    }

    $accounts = Get-KitGmailAccounts
    if ($accounts.Count -gt 0) {
        Write-Success ("beállított fiókok: " + ($accounts -join ', '))
    } else {
        Write-Warn 'Még nem látok beállított fiókot. Nézd meg a fenti hibaüzenetet.'
    }
}

Write-Detail 'Fiókot később így adhatsz hozzá:'
Write-Detail "  cd `"$serverDir`" ; node dist\index.js auth --keys `"C:\utvonal\oauth.json`""
