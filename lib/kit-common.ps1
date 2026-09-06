# kit-common.ps1
#
# Shared helpers for install.ps1, update.ps1, doctor.ps1, mcp/register-mcps.ps1
# and mcp/gmail-setup.ps1. Dot-source it from the kit root:
#
#   . (Join-Path $PSScriptRoot 'lib\kit-common.ps1')
#
# Two rules keep this file testable on a Mac:
#   1. Every Windows-only call (winget, `irm | iex`, Task Scheduler, keyring)
#      lives in a wrapper that takes -DryRun, so the tests can assert the wrapper
#      exists without ever running it.
#   2. Everything else (settings merge, manifest compare, kit-state, path and
#      spec.yaml helpers) is pure and works on any platform.
#
# Target: Windows PowerShell 5.1 first, PowerShell 7 second. No 7-only syntax:
# no ??, no ternary, no ForEach-Object -Parallel. JSON is always written with
# ConvertTo-Json -Depth 20 and read with ConvertFrom-Json.

# ---------------------------------------------------------------- console ----

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host ">> $Message" -ForegroundColor Cyan
}

function Write-Success {
    param([string]$Message)
    Write-Host "   [OK] $Message" -ForegroundColor Green
}

# Named Write-Warn, not Write-Warning: overriding the built-in cmdlet inside a
# dot-sourced scope would silently change every other caller in the session.
function Write-Warn {
    param([string]$Message)
    Write-Host "   [!] $Message" -ForegroundColor Yellow
}

function Write-Fail {
    param([string]$Message)
    Write-Host "   [X] $Message" -ForegroundColor Red
}

function Write-Detail {
    param([string]$Message)
    Write-Host "   $Message" -ForegroundColor Gray
}

function Write-Plan {
    param([string]$Message)
    Write-Host "   [terv] $Message" -ForegroundColor DarkGray
}

# ------------------------------------------------------------------ paths ----

function Test-KitWindows {
    return ($env:OS -eq 'Windows_NT')
}

function Get-KitUserProfile {
    if ($env:USERPROFILE) { return $env:USERPROFILE }
    return $HOME
}

function Get-KitClaudeHome {
    return (Join-Path (Get-KitUserProfile) '.claude')
}

function Get-KitProjectDir {
    return (Join-Path (Get-KitUserProfile) 'Riportok')
}

function Get-KitGmailServerDir {
    return (Join-Path (Get-KitUserProfile) 'Gmail-MCP-Server')
}

# Absolute filesystem path without requiring the target to exist.
function Convert-KitPath {
    param([Parameter(Mandatory = $true)][string]$Path)
    return $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Path)
}

function Convert-KitRelative {
    param([Parameter(Mandatory = $true)][string]$PosixPath)
    return $PosixPath.Replace('/', [System.IO.Path]::DirectorySeparatorChar)
}

# Join a POSIX style relative path onto a base path using the platform
# separator. Keeps every call site readable and platform neutral.
function Join-KitPath {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$ChildPath
    )
    return (Join-Path $Path (Convert-KitRelative -PosixPath $ChildPath))
}

function New-KitDirectory {
    param([Parameter(Mandatory = $true)][string]$Path, [switch]$DryRun)
    if ($DryRun) { return $false }
    if (Test-Path -LiteralPath $Path) { return $false }
    New-Item -ItemType Directory -Path $Path -Force | Out-Null
    return $true
}

function Get-KitTimestamp {
    return (Get-Date).ToString('yyyyMMdd-HHmmss')
}

function Get-KitIsoTimestamp {
    return (Get-Date).ToString('yyyy-MM-ddTHH:mm:ss')
}

# ------------------------------------------------------------------- json ----

function Read-KitJsonFile {
    param([Parameter(Mandatory = $true)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $null }
    $raw = Get-Content -LiteralPath $Path -Raw -Encoding UTF8 -ErrorAction Stop
    if ($null -eq $raw) { return $null }
    $raw = $raw.TrimStart([char]0xFEFF)
    if (-not $raw.Trim()) { return $null }
    return ($raw | ConvertFrom-Json)
}

function Write-KitJsonFile {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)]$Value
    )
    $full = Convert-KitPath -Path $Path
    $dir = Split-Path -Parent $full
    if ($dir -and -not (Test-Path -LiteralPath $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
    }
    $json = ConvertTo-Json -InputObject $Value -Depth 20
    # UTF-8 without BOM: Node's JSON.parse chokes on a leading BOM.
    [System.IO.File]::WriteAllText($full, $json, (New-Object System.Text.UTF8Encoding($false)))
}

function ConvertTo-KitHashtable {
    param($Object)
    $table = @{}
    if ($null -eq $Object) { return $table }
    foreach ($property in $Object.PSObject.Properties) {
        $table[$property.Name] = [string]$property.Value
    }
    return $table
}

# ConvertFrom-Json turns ISO 8601 looking strings into [datetime] in both 5.1 and
# 7, so a naive round trip would rewrite "2026-09-06T10:00:00" in the current
# culture format. Always format timestamps back to ISO before writing.
function ConvertTo-KitIsoString {
    param($Value)
    if ($null -eq $Value) { return $null }
    if ($Value -is [datetime]) { return $Value.ToString('yyyy-MM-ddTHH:mm:ss') }
    return [string]$Value
}

function Test-KitProperty {
    param($Object, [Parameter(Mandatory = $true)][string]$Name)
    if ($null -eq $Object) { return $false }
    return ($Object.PSObject.Properties.Name -contains $Name)
}

# --------------------------------------------------------------- commands ----

function Test-KitCommand {
    param([Parameter(Mandatory = $true)][string]$Name)
    return [bool](Get-Command -Name $Name -ErrorAction SilentlyContinue)
}

function Get-KitCommandSource {
    param([Parameter(Mandatory = $true)][string]$Name)
    $command = Get-Command -Name $Name -ErrorAction SilentlyContinue
    if (-not $command) { return $null }
    return [string]$command.Source
}

function Get-KitToolVersion {
    param([Parameter(Mandatory = $true)][string]$Name, [string[]]$Arguments = @('--version'))
    if (-not (Test-KitCommand -Name $Name)) { return $null }
    $text = ''
    try {
        $text = (& $Name @Arguments 2>&1 | Out-String)
    } catch {
        return $null
    }
    $text = $text.Trim()
    if (-not $text) { return $null }
    return ($text -split "`r?`n")[0].Trim()
}

# Refresh PATH from the registry plus the two per-user bin folders the Claude
# Code and uv installers write to, so a freshly installed tool is found without
# opening a new terminal.
function Update-KitPath {
    if (Test-KitWindows) {
        $machine = [System.Environment]::GetEnvironmentVariable('Path', 'Machine')
        $user = [System.Environment]::GetEnvironmentVariable('Path', 'User')
        $parts = @()
        if ($machine) { $parts += $machine }
        if ($user) { $parts += $user }
        if ($parts.Count -gt 0) { $env:Path = ($parts -join ';') }
    }
    $profileDir = Get-KitUserProfile
    $extras = @(
        (Join-KitPath -Path $profileDir -ChildPath '.local/bin'),
        (Join-KitPath -Path $profileDir -ChildPath 'AppData/Roaming/npm')
    )
    foreach ($extra in $extras) {
        if ((Test-Path -LiteralPath $extra) -and ($env:Path -notlike "*$extra*")) {
            $env:Path = "$extra;$env:Path"
        }
    }
}

function Get-KitPythonInfo {
    $info = [pscustomobject]@{
        Found       = $false
        Source      = $null
        Version     = $null
        Major       = 0
        Minor       = 0
        IsStoreStub = $false
        IsOk        = $false
    }
    $command = Get-Command -Name 'python' -ErrorAction SilentlyContinue
    if (-not $command) { return $info }

    $info.Found = $true
    $info.Source = [string]$command.Source
    if ($info.Source -and ($info.Source -like '*\WindowsApps\*')) { $info.IsStoreStub = $true }

    $text = ''
    try {
        $text = (& python --version 2>&1 | Out-String).Trim()
    } catch {
        $text = ''
    }
    # The Microsoft Store alias stub prints nothing and opens the Store instead.
    if (-not $text) {
        $info.IsStoreStub = $true
        return $info
    }
    $info.Version = ($text -split "`r?`n")[0].Trim()
    if ($info.Version -match 'Python\s+(\d+)\.(\d+)') {
        $info.Major = [int]$Matches[1]
        $info.Minor = [int]$Matches[2]
    }
    $info.IsOk = ((-not $info.IsStoreStub) -and ($info.Major -eq 3) -and ($info.Minor -ge 12))
    return $info
}

function Test-KitUvTool {
    param([Parameter(Mandatory = $true)][string]$Name)
    if (-not (Test-KitCommand -Name 'uv')) { return $false }
    $text = ''
    try {
        $text = (& uv tool list 2>&1 | Out-String)
    } catch {
        return $false
    }
    return ($text -match ('(?m)^\s*' + [regex]::Escape($Name) + '(\s|$)'))
}

# ---------------------------------------------- Windows-only call wrappers ----
# Nothing below runs during the macOS tests: every function short-circuits on
# -DryRun before it touches winget, the network or the Task Scheduler.

function Invoke-KitWinget {
    param(
        [Parameter(Mandatory = $true)][string]$PackageId,
        [Parameter(Mandatory = $true)][string]$Name,
        [switch]$DryRun
    )
    if ($DryRun) {
        Write-Plan "winget install --id $PackageId  ($Name)"
        return $true
    }
    if (-not (Test-KitCommand -Name 'winget')) { return $false }
    Write-Detail "winget install --id $PackageId"
    & winget install --id $PackageId --exact --accept-source-agreements --accept-package-agreements
    Update-KitPath
    return $true
}

function Invoke-KitWebInstall {
    param(
        [Parameter(Mandatory = $true)][string]$Url,
        [Parameter(Mandatory = $true)][string]$Name,
        [switch]$DryRun
    )
    if ($DryRun) {
        Write-Plan "irm $Url | iex  ($Name)"
        return $true
    }
    Write-Detail "irm $Url | iex"
    $installer = Invoke-RestMethod -Uri $Url
    Invoke-Expression $installer
    Update-KitPath
    return $true
}

function Install-KitUv {
    param([switch]$DryRun)
    if (Test-KitCommand -Name 'uv') { return $true }
    Invoke-KitWebInstall -Url 'https://astral.sh/uv/install.ps1' -Name 'uv' -DryRun:$DryRun | Out-Null
    if ($DryRun) { return $true }
    Update-KitPath
    return (Test-KitCommand -Name 'uv')
}

function New-KitMonthlyTrigger {
    param(
        [int]$DayOfMonth = 5,
        [string]$At = '07:00',
        [switch]$DryRun
    )
    if ($DryRun) { return $null }
    # New-ScheduledTaskTrigger has no monthly option, so the trigger is built as
    # a CIM instance of MSFT_TaskMonthlyTrigger. DaysOfMonth is a bitmask.
    $class = Get-CimClass -ClassName MSFT_TaskMonthlyTrigger `
        -Namespace Root/Microsoft/Windows/TaskScheduler
    $trigger = New-CimInstance -CimClass $class -ClientOnly
    $trigger.DaysOfMonth = [uint32](1 -shl ($DayOfMonth - 1))
    $trigger.MonthsOfYear = 4095
    $parts = $At.Split(':')
    $start = (Get-Date -Hour ([int]$parts[0]) -Minute ([int]$parts[1]) -Second 0)
    $trigger.StartBoundary = $start.ToString('yyyy-MM-ddTHH:mm:ss')
    $trigger.Enabled = $true
    return $trigger
}

function Get-KitScheduledTaskInfo {
    param(
        [string]$TaskPath = '\Controller\',
        [string]$TaskName = 'HaviRiport'
    )
    if (-not (Test-KitCommand -Name 'Get-ScheduledTask')) { return $null }
    $task = Get-ScheduledTask -TaskPath $TaskPath -TaskName $TaskName -ErrorAction SilentlyContinue
    if (-not $task) { return $null }
    $next = $null
    try {
        $next = (Get-ScheduledTaskInfo -InputObject $task -ErrorAction SilentlyContinue).NextRunTime
    } catch {
        $next = $null
    }
    return [pscustomobject]@{
        Name        = $TaskName
        Path        = $TaskPath
        State       = [string]$task.State
        NextRunTime = $next
    }
}

function Register-KitMonthlyTask {
    param(
        [string]$TaskPath = '\Controller\',
        [string]$TaskName = 'HaviRiport',
        [Parameter(Mandatory = $true)][string]$Execute,
        [string]$Argument = '',
        [Parameter(Mandatory = $true)][string]$WorkingDirectory,
        [int]$DayOfMonth = 5,
        [string]$At = '07:00',
        [switch]$DryRun
    )
    if ($DryRun) {
        Write-Plan "Register-ScheduledTask $TaskPath$TaskName ($DayOfMonth. nap, $At)"
        return $null
    }
    if (-not (Test-KitCommand -Name 'Register-ScheduledTask')) {
        throw 'A ScheduledTasks modul nem érhető el ezen a gépen.'
    }
    $action = New-ScheduledTaskAction -Execute $Execute -Argument $Argument `
        -WorkingDirectory $WorkingDirectory
    $trigger = New-KitMonthlyTrigger -DayOfMonth $DayOfMonth -At $At
    $userId = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
    # Interactive logon type: runs only when she is logged on, so Windows never
    # asks for the account password during registration.
    $principal = New-ScheduledTaskPrincipal -UserId $userId -LogonType Interactive -RunLevel Limited
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable
    return (Register-ScheduledTask -TaskPath $TaskPath -TaskName $TaskName -Action $action `
            -Trigger $trigger -Principal $principal -Settings $settings -Force)
}

# --------------------------------------------------------- manifest / copy ----

function Get-KitFileHash {
    param([Parameter(Mandatory = $true)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $null }
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Get-KitManifest {
    param([Parameter(Mandatory = $true)][string]$KitPath)
    $manifest = Read-KitJsonFile -Path (Join-Path $KitPath 'manifest.json')
    if (-not $manifest) { return $null }
    return $manifest
}

function Get-KitManifestFiles {
    param($Manifest)
    if (-not (Test-KitProperty -Object $Manifest -Name 'files')) { return @{} }
    return (ConvertTo-KitHashtable -Object $Manifest.files)
}

function Get-KitVersion {
    param([Parameter(Mandatory = $true)][string]$KitPath)
    $manifest = Get-KitManifest -KitPath $KitPath
    if ((Test-KitProperty -Object $manifest -Name 'kit_version') -and $manifest.kit_version) {
        return [string]$manifest.kit_version
    }
    $changelog = Join-Path $KitPath 'CHANGELOG.md'
    if (Test-Path -LiteralPath $changelog -PathType Leaf) {
        foreach ($line in (Get-Content -LiteralPath $changelog -Encoding UTF8)) {
            if ($line -match '^##\s+\[(\d+\.\d+\.\d+)\]') { return $Matches[1] }
        }
    }
    return '0.1.0'
}

# One of: missing, same, kit-updated, user-modified.
function Compare-KitFile {
    param(
        [Parameter(Mandatory = $true)][string]$TargetPath,
        [Parameter(Mandatory = $true)][AllowEmptyString()][string]$ExpectedHash,
        [AllowNull()][string]$PreviousHash
    )
    if (-not (Test-Path -LiteralPath $TargetPath -PathType Leaf)) { return 'missing' }
    $actual = Get-KitFileHash -Path $TargetPath
    if ($actual -eq $ExpectedHash) { return 'same' }
    if ($PreviousHash -and ($actual -eq $PreviousHash)) { return 'kit-updated' }
    return 'user-modified'
}

function Copy-KitFile {
    param(
        [Parameter(Mandatory = $true)][string]$Source,
        [Parameter(Mandatory = $true)][string]$Target,
        [switch]$DryRun
    )
    if ($DryRun) { return }
    $dir = Split-Path -Parent $Target
    if ($dir -and -not (Test-Path -LiteralPath $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
    }
    Copy-Item -LiteralPath $Source -Destination $Target -Force
}

function Backup-KitFile {
    param(
        [Parameter(Mandatory = $true)][string]$SourceFile,
        [Parameter(Mandatory = $true)][string]$BackupRoot,
        [Parameter(Mandatory = $true)][string]$Stamp,
        [Parameter(Mandatory = $true)][string]$RelativeKey,
        [switch]$DryRun
    )
    $target = Join-Path (Join-Path $BackupRoot $Stamp) (Convert-KitRelative -PosixPath $RelativeKey)
    if (-not $DryRun) {
        Copy-KitFile -Source $SourceFile -Target $target
    }
    return $target
}

function New-KitCopyResult {
    return [pscustomobject]@{
        Created   = (New-Object System.Collections.ArrayList)
        Unchanged = (New-Object System.Collections.ArrayList)
        Updated   = (New-Object System.Collections.ArrayList)
        BackedUp  = (New-Object System.Collections.ArrayList)
        Skipped   = (New-Object System.Collections.ArrayList)
        Kept      = (New-Object System.Collections.ArrayList)
        Missing   = (New-Object System.Collections.ArrayList)
    }
}

function Test-KitPathPrefix {
    param([Parameter(Mandatory = $true)][string]$Relative, [string[]]$Prefixes = @())
    foreach ($prefix in $Prefixes) {
        if (-not $prefix) { continue }
        if ($Relative -eq $prefix) { return $true }
        if ($Relative.StartsWith($prefix)) { return $true }
    }
    return $false
}

<#
Copy one manifest section onto the laptop.

  missing target                     -> copy                        (Created)
  target hash = manifest hash        -> nothing                     (Unchanged)
  target hash = previous manifest    -> kit changed it, overwrite    (Updated)
  target differs from both           -> she edited it: back up, then
                                        overwrite, or keep hers when
                                        the path is in -KeepDrifted  (BackedUp)

-CreateOnly marks paths that are hers forever (reports\): only created when
missing, never overwritten, never backed up. -CreateOnlyExcept carves kit-owned
subtrees back out of that rule (reports\_examples\).
#>
function Copy-KitSection {
    param(
        [Parameter(Mandatory = $true)][string]$KitPath,
        [Parameter(Mandatory = $true)][hashtable]$ManifestFiles,
        [hashtable]$PreviousFiles = @{},
        [Parameter(Mandatory = $true)][string]$Prefix,
        [Parameter(Mandatory = $true)][string]$TargetRoot,
        [string]$BackupRoot,
        [string]$BackupStamp,
        [string[]]$CreateOnly = @(),
        [string[]]$CreateOnlyExcept = @(),
        [string[]]$KeepDrifted = @(),
        [switch]$DryRun
    )
    $result = New-KitCopyResult
    if (-not $BackupStamp) { $BackupStamp = Get-KitTimestamp }

    foreach ($key in ($ManifestFiles.Keys | Sort-Object)) {
        if (-not $key.StartsWith($Prefix)) { continue }
        $relative = $key.Substring($Prefix.Length)
        if (-not $relative) { continue }

        $source = Join-Path $KitPath (Convert-KitRelative -PosixPath $key)
        if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
            [void]$result.Missing.Add($key)
            continue
        }
        $target = Join-Path $TargetRoot (Convert-KitRelative -PosixPath $relative)
        $expected = [string]$ManifestFiles[$key]
        $previous = $null
        if ($PreviousFiles -and $PreviousFiles.ContainsKey($key)) {
            $previous = [string]$PreviousFiles[$key]
        }

        $state = Compare-KitFile -TargetPath $target -ExpectedHash $expected -PreviousHash $previous
        if ($state -eq 'missing') {
            Copy-KitFile -Source $source -Target $target -DryRun:$DryRun
            [void]$result.Created.Add($relative)
            continue
        }
        if ($state -eq 'same') {
            [void]$result.Unchanged.Add($relative)
            continue
        }

        $isHers = ((Test-KitPathPrefix -Relative $relative -Prefixes $CreateOnly) -and
            -not (Test-KitPathPrefix -Relative $relative -Prefixes $CreateOnlyExcept))
        if ($isHers) {
            [void]$result.Skipped.Add($relative)
            continue
        }

        if ($state -eq 'user-modified' -and $BackupRoot) {
            [void]$result.BackedUp.Add($relative)
            Backup-KitFile -SourceFile $target -BackupRoot $BackupRoot -Stamp $BackupStamp `
                -RelativeKey $key -DryRun:$DryRun | Out-Null
        }
        if ($state -eq 'user-modified' -and
            (Test-KitPathPrefix -Relative $relative -Prefixes $KeepDrifted)) {
            [void]$result.Kept.Add($relative)
            continue
        }

        Copy-KitFile -Source $source -Target $target -DryRun:$DryRun
        [void]$result.Updated.Add($relative)
    }
    return $result
}

function Copy-KitHome {
    param(
        [Parameter(Mandatory = $true)][string]$KitPath,
        [Parameter(Mandatory = $true)][hashtable]$ManifestFiles,
        [hashtable]$PreviousFiles = @{},
        [Parameter(Mandatory = $true)][string]$ClaudeHome,
        [string]$BackupRoot,
        [string]$BackupStamp,
        [switch]$DryRun
    )
    return (Copy-KitSection -KitPath $KitPath -ManifestFiles $ManifestFiles `
            -PreviousFiles $PreviousFiles -Prefix 'home/' -TargetRoot $ClaudeHome `
            -BackupRoot $BackupRoot -BackupStamp $BackupStamp -DryRun:$DryRun)
}

function Write-KitCopySummary {
    param([Parameter(Mandatory = $true)]$Result, [Parameter(Mandatory = $true)][string]$Label)
    $counts = "új: $($Result.Created.Count), változatlan: $($Result.Unchanged.Count), " +
    "frissítve: $($Result.Updated.Count)"
    Write-Detail "$Label - $counts"
    foreach ($item in $Result.BackedUp) {
        Write-Warn "Módosítottad, ezért mentettem róla másolatot: $item"
    }
    foreach ($item in $Result.Kept) {
        Write-Warn "A te változatod maradt érvényben: $item"
    }
    foreach ($item in $Result.Missing) {
        Write-Warn "Hiányzik a készletből: $item"
    }
}

# ---------------------------------------------------------- settings merge ----

function Test-KitHookEntry {
    param($Entry, [string[]]$HookFiles = @())
    if ($null -eq $Entry) { return $false }
    if (-not (Test-KitProperty -Object $Entry -Name 'hooks')) { return $false }
    foreach ($hook in @($Entry.hooks)) {
        if (-not (Test-KitProperty -Object $hook -Name 'command')) { continue }
        $command = [string]$hook.command
        if (-not $command) { continue }
        foreach ($file in $HookFiles) {
            if ($file -and ($command -like "*$file*")) { return $true }
        }
    }
    return $false
}

function ConvertTo-KitHookEntry {
    param($Entry)
    $clean = [ordered]@{}
    foreach ($property in $Entry.PSObject.Properties) {
        if ($property.Name -eq 'kit_min_level') { continue }
        $clean[$property.Name] = $property.Value
    }
    return [pscustomobject]$clean
}

<#
Merge the kit hook block into her settings.json and return the merged object.

Contract (docs/HOOKS.md): drop existing entries whose command mentions a kit
hook file, keep every foreign entry in place, append the kit entries whose
kit_min_level is at most -Level with kit_min_level stripped, touch no other
event and no other settings key. Idempotent.
#>
function Merge-KitHooks {
    param(
        [Parameter(Mandatory = $true)][string]$SettingsPath,
        [Parameter(Mandatory = $true)][string]$HooksBlockPath,
        [int]$Level = 1
    )
    $settings = Read-KitJsonFile -Path $SettingsPath
    if ($null -eq $settings) { $settings = [pscustomobject]@{} }

    $block = Read-KitJsonFile -Path $HooksBlockPath
    if ($null -eq $block) { throw "A hooks-block.json nem olvasható: $HooksBlockPath" }
    $hookFiles = @()
    if (Test-KitProperty -Object $block -Name 'hook_files') { $hookFiles = @($block.hook_files) }

    $merged = [ordered]@{}
    if (Test-KitProperty -Object $settings -Name 'hooks') {
        foreach ($property in $settings.hooks.PSObject.Properties) {
            $merged[$property.Name] = [object[]]@($property.Value)
        }
    }

    foreach ($event in $block.hooks.PSObject.Properties) {
        $name = $event.Name
        $kept = New-Object System.Collections.ArrayList
        if ($merged.Contains($name)) {
            foreach ($entry in @($merged[$name])) {
                if (Test-KitHookEntry -Entry $entry -HookFiles $hookFiles) { continue }
                [void]$kept.Add($entry)
            }
        }
        foreach ($entry in @($event.Value)) {
            $minLevel = 1
            if (Test-KitProperty -Object $entry -Name 'kit_min_level') {
                $minLevel = [int]$entry.kit_min_level
            }
            if ($minLevel -le $Level) {
                [void]$kept.Add((ConvertTo-KitHookEntry -Entry $entry))
            }
        }
        $merged[$name] = [object[]]$kept.ToArray()
    }

    $hooksObject = [pscustomobject]$merged
    if (Test-KitProperty -Object $settings -Name 'hooks') {
        $settings.hooks = $hooksObject
    } else {
        $settings | Add-Member -NotePropertyName 'hooks' -NotePropertyValue $hooksObject -Force
    }
    return $settings
}

function Write-KitSettings {
    param(
        [Parameter(Mandatory = $true)][string]$SettingsPath,
        [Parameter(Mandatory = $true)]$Settings,
        [switch]$NoBackup,
        [switch]$DryRun
    )
    if ($DryRun) { return $false }
    if (-not $NoBackup -and (Test-Path -LiteralPath $SettingsPath -PathType Leaf)) {
        Copy-Item -LiteralPath $SettingsPath -Destination "$SettingsPath.bak" -Force
    }
    Write-KitJsonFile -Path $SettingsPath -Value $Settings
    return $true
}

# -------------------------------------------------------------- kit-state ----

function Read-KitState {
    param([Parameter(Mandatory = $true)][string]$Path)
    return (Read-KitJsonFile -Path $Path)
}

function Resolve-KitLevel {
    param($State, [int]$Requested = 0)
    if ($Requested -gt 0) { return $Requested }
    if ((Test-KitProperty -Object $State -Name 'level') -and $State.level) { return [int]$State.level }
    return 1
}

function Write-KitState {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$KitVersion,
        [Parameter(Mandatory = $true)][int]$Level,
        [Parameter(Mandatory = $true)][string]$KitPath,
        [Parameter(Mandatory = $true)][string]$ProjectDir,
        [hashtable]$Flags = @{},
        [switch]$DryRun
    )
    $existing = Read-KitState -Path $Path
    $now = Get-KitIsoTimestamp
    $installedAt = $now
    $tipsSeen = 0
    if ($existing) {
        if ((Test-KitProperty -Object $existing -Name 'installed_at') -and $existing.installed_at) {
            $installedAt = ConvertTo-KitIsoString -Value $existing.installed_at
        }
        if ((Test-KitProperty -Object $existing -Name 'tips_seen') -and
            ($null -ne $existing.tips_seen)) {
            $tipsSeen = [int]$existing.tips_seen
        }
    }
    $state = [pscustomobject]([ordered]@{
            kit_version  = $KitVersion
            level        = $Level
            installed_at = $installedAt
            updated_at   = $now
            kit_path     = $KitPath
            project_dir  = $ProjectDir
            tips_seen    = $tipsSeen
            flags        = [pscustomobject]([ordered]@{
                    gmail    = [bool]$Flags['gmail']
                    nav      = [bool]$Flags['nav']
                    schedule = [bool]$Flags['schedule']
                })
        })
    if (-not $DryRun) { Write-KitJsonFile -Path $Path -Value $state }
    return $state
}

# ------------------------------------------------------------- spec.yaml ----
# Same naive line scanner the protect_delivery.py hook uses: track the top-level
# key at column 0, then pick folder: at any indent below delivery: or powerbi:.

function Resolve-KitSpecFolder {
    param([Parameter(Mandatory = $true)][string]$Value, [string]$ProjectDir)
    $path = [System.Environment]::ExpandEnvironmentVariables($Value)
    if ($path.StartsWith('~')) { $path = (Get-KitUserProfile) + $path.Substring(1) }
    if ((-not [System.IO.Path]::IsPathRooted($path)) -and $ProjectDir) {
        $path = Join-Path $ProjectDir $path
    }
    return $path
}

function Get-KitSpecFolders {
    param(
        [Parameter(Mandatory = $true)][string]$SpecPath,
        [string]$ProjectDir
    )
    $folders = New-Object System.Collections.ArrayList
    if (-not (Test-Path -LiteralPath $SpecPath -PathType Leaf)) { return , @() }
    $section = ''
    foreach ($line in (Get-Content -LiteralPath $SpecPath -Encoding UTF8)) {
        if ($line -match '^([A-Za-z_][A-Za-z0-9_]*)\s*:') {
            $section = $Matches[1]
            continue
        }
        if (($section -ne 'delivery') -and ($section -ne 'powerbi')) { continue }
        if ($line -match '^\s+folder\s*:\s*(.+?)\s*$') {
            $value = ($Matches[1] -replace '\s+#.*$', '').Trim()
            $value = $value.Trim('"').Trim("'")
            if ($value) {
                [void]$folders.Add((Resolve-KitSpecFolder -Value $value -ProjectDir $ProjectDir))
            }
        }
    }
    return , ($folders.ToArray())
}

function Get-KitReportSlugs {
    param([Parameter(Mandatory = $true)][string]$ProjectDir)
    $reports = Join-Path $ProjectDir 'reports'
    if (-not (Test-Path -LiteralPath $reports)) { return , @() }
    $slugs = New-Object System.Collections.ArrayList
    foreach ($dir in (Get-ChildItem -LiteralPath $reports -Directory -ErrorAction SilentlyContinue)) {
        if ($dir.Name -eq '_examples') { continue }
        if (Test-Path -LiteralPath (Join-Path $dir.FullName 'spec.yaml') -PathType Leaf) {
            [void]$slugs.Add($dir.Name)
        }
    }
    return , ($slugs.ToArray())
}

function Test-KitFolderWritable {
    param([Parameter(Mandatory = $true)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Container)) { return $false }
    $probe = Join-Path $Path (".kit-write-test-" + [guid]::NewGuid().ToString('N') + ".tmp")
    try {
        Set-Content -LiteralPath $probe -Value 'x' -ErrorAction Stop
        Remove-Item -LiteralPath $probe -Force -ErrorAction SilentlyContinue
        return $true
    } catch {
        return $false
    }
}
