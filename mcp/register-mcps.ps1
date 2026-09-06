<#
.SYNOPSIS
    Bejegyzi a szinthez tartozó MCP szervereket a Claude Code-ba.

.DESCRIPTION
    Egyszer beolvassa a `claude mcp list` kimenetét, és csak azokat a szervereket
    adja hozzá, amelyek még nincsenek benne. Idempotens.

    A bejegyzések felhasználói hatókörbe (--scope user) kerülnek, vagyis a
    %USERPROFILE%\.claude.json fájlba. Azt a fájlt soha nem szerkesztjük kézzel.

.EXAMPLE
    .\mcp\register-mcps.ps1 -Level 2

.EXAMPLE
    .\mcp\register-mcps.ps1 -Remove
    Eltávolítja a készlet összes MCP szerverét.
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [int]$Level = 1,
    [switch]$Remove,
    [string]$KitPath = (Split-Path -Parent $PSScriptRoot)
)

$ErrorActionPreference = 'Stop'

. (Join-Path (Join-Path $KitPath 'lib') 'kit-common.ps1')

$dryRun = [bool]$WhatIfPreference
$gmailEntry = Join-KitPath -Path (Get-KitGmailServerDir) -ChildPath 'dist/index.js'

# Command syntax verified against the Claude Code MCP docs on 2026-09-06:
#   stdio:  claude mcp add <name> --scope user -- <command> [args...]
#   http:   claude mcp add --transport http <name> <url> --scope user
# The -- separator is required for stdio servers and comes after every option.
$servers = @(
    [pscustomobject]@{
        Name = 'gmail'; Level = 1; Kind = 'stdio'
        Command = @('node', $gmailEntry)
        RequiresFile = $gmailEntry
        Why = 'A Gmail MCP nincs felépítve. Futtasd: .\mcp\gmail-setup.ps1'
    },
    [pscustomobject]@{
        Name = 'excel'; Level = 1; Kind = 'stdio'
        Command = @('uvx', 'excel-mcp-server', 'stdio')
        RequiresFile = $null; Why = $null
    },
    [pscustomobject]@{
        Name = 'microsoft-learn'; Level = 2; Kind = 'http'
        Url = 'https://learn.microsoft.com/api/mcp'
        RequiresFile = $null; Why = $null
    },
    [pscustomobject]@{
        Name = 'powerbi-modeling'; Level = 3; Kind = 'stdio'
        Command = @('cmd', '/c', 'npx', '-y', '@microsoft/powerbi-modeling-mcp@latest', '--start')
        RequiresFile = $null; Why = $null
    },
    [pscustomobject]@{
        Name = 'ms365'; Level = 3; Kind = 'stdio'
        Command = @('cmd', '/c', 'npx', '-y', '@softeria/ms-365-mcp-server')
        RequiresFile = $null; Why = $null
    }
)

function Get-KitMcpList {
    if (-not (Test-KitCommand -Name 'claude')) { return $null }
    try {
        return (& claude mcp list 2>&1 | Out-String)
    } catch {
        return ''
    }
}

function Test-KitMcpRegistered {
    param([Parameter(Mandatory = $true)][string]$Name, [AllowNull()][string]$ListText)
    if (-not $ListText) { return $false }
    $pattern = '(?m)^\s*' + [regex]::Escape($Name) + '\s*:'
    return ($ListText -match $pattern)
}

Write-Step "MCP szerverek bejegyzése (szint $Level)"

if (-not (Test-KitCommand -Name 'claude')) {
    Write-Warn 'A claude parancs nem található, az MCP bejegyzést kihagyom.'
    return
}

$listText = Get-KitMcpList

if ($Remove) {
    foreach ($server in $servers) {
        if (-not (Test-KitMcpRegistered -Name $server.Name -ListText $listText)) {
            Write-Success "$($server.Name): nincs bejegyezve"
            continue
        }
        if ($PSCmdlet.ShouldProcess($server.Name, 'claude mcp remove')) {
            if ($dryRun) {
                Write-Plan "claude mcp remove $($server.Name) --scope user"
            } else {
                & claude mcp remove $server.Name --scope user
                Write-Success "$($server.Name): eltávolítva"
            }
        }
    }
    return
}

foreach ($server in $servers) {
    if ($server.Level -gt $Level) { continue }

    if (Test-KitMcpRegistered -Name $server.Name -ListText $listText) {
        Write-Success "$($server.Name): már bejegyezve"
        continue
    }
    if ($server.RequiresFile -and -not (Test-Path -LiteralPath $server.RequiresFile -PathType Leaf)) {
        Write-Warn "$($server.Name): kihagyva. $($server.Why)"
        continue
    }

    if ($server.Kind -eq 'http') {
        $arguments = @('mcp', 'add', '--transport', 'http', $server.Name, $server.Url,
            '--scope', 'user')
    } else {
        $arguments = @('mcp', 'add', $server.Name, '--scope', 'user', '--') + $server.Command
    }

    if ($PSCmdlet.ShouldProcess($server.Name, 'claude mcp add')) {
        if ($dryRun) {
            Write-Plan ('claude ' + ($arguments -join ' '))
        } else {
            & claude @arguments
            if ($LASTEXITCODE -eq 0) {
                Write-Success "$($server.Name): bejegyezve"
            } else {
                Write-Warn "$($server.Name): a bejegyzés nem sikerült (kilépési kód $LASTEXITCODE)"
            }
        }
    }
}

Write-Detail 'Ellenőrzés: claude mcp list'
