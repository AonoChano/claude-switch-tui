[CmdletBinding()]
param(
    [string]$InstallDir = (Join-Path $env:USERPROFILE ".claude\scripts\ClaudeSwitch"),
    [switch]$NoPath,
    [switch]$SkipPip,
    [switch]$NoLegacyCleanup,
    [switch]$Elevate,
    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Test-IsAdmin {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Invoke-Native {
    param(
        [string]$FilePath,
        [string[]]$Arguments,
        [string]$ErrorMessage
    )

    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$ErrorMessage (exit code $LASTEXITCODE)."
    }
}

function Test-PythonCandidate {
    param(
        [string]$Exe,
        [string[]]$Args
    )

    $previousErrorAction = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $Exe @($Args) -c "import sys, tempfile, venv; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" > $null 2>&1
        return $LASTEXITCODE -eq 0
    }
    catch {
        return $false
    }
    finally {
        $ErrorActionPreference = $previousErrorAction
    }
}

function Invoke-InstallStep {
    param(
        [string]$Message,
        [scriptblock]$Action
    )

    Write-Host "[csw] $Message"
    if (-not $DryRun) {
        & $Action
    }
}

function Resolve-Python {
    $candidates = @()

    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        foreach ($selector in @("-3.12", "-3.11", "-3.10", "-3.13", "-3")) {
            $candidates += @{ Exe = $py.Source; Args = @($selector) }
        }
    }

    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) {
        $candidates += @{ Exe = $python.Source; Args = @() }
    }

    $python3 = Get-Command python3 -ErrorAction SilentlyContinue
    if ($python3) {
        $candidates += @{ Exe = $python3.Source; Args = @() }
    }

    foreach ($candidate in $candidates) {
        if (Test-PythonCandidate -Exe $candidate.Exe -Args $candidate.Args) {
            return $candidate
        }
    }

    throw "A healthy Python 3.10+ was not found. Install or repair Python first, then rerun install.ps1."
}

function Remove-LocalVenv {
    param(
        [string]$VenvPath,
        [string]$InstallRoot
    )

    if (-not (Test-Path -LiteralPath $VenvPath)) {
        return
    }

    $venvFull = [IO.Path]::GetFullPath($VenvPath)
    $installFull = [IO.Path]::GetFullPath($InstallRoot).TrimEnd("\") + "\"
    if (-not $venvFull.StartsWith($installFull, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to remove venv outside install directory: $venvFull"
    }

    Remove-Item -LiteralPath $VenvPath -Recurse -Force
}

function Add-UserPath {
    param([string]$PathToAdd)

    $current = [Environment]::GetEnvironmentVariable("Path", "User")
    $parts = @()
    if ($current) {
        $parts = $current -split ";" | Where-Object { $_ -and $_.Trim() }
    }

    $normalizedTarget = $PathToAdd.TrimEnd("\")
    foreach ($part in $parts) {
        if ([string]::Equals($part.TrimEnd("\"), $normalizedTarget, [StringComparison]::OrdinalIgnoreCase)) {
            Write-Host "[csw] User PATH already contains $PathToAdd"
            return
        }
    }

    $newPath = if ($current) { "$current;$PathToAdd" } else { $PathToAdd }
    [Environment]::SetEnvironmentVariable("Path", $newPath, "User")
    if (($env:Path -split ";") -notcontains $PathToAdd) {
        $env:Path = "$env:Path;$PathToAdd"
    }
    Write-Host "[csw] Added to User PATH: $PathToAdd"
}

function Remove-UserPath {
    param([string]$PathToRemove)

    $current = [Environment]::GetEnvironmentVariable("Path", "User")
    if (-not $current) {
        return
    }

    $normalizedTarget = $PathToRemove.TrimEnd("\")
    $parts = $current -split ";" | Where-Object {
        $_ -and -not [string]::Equals($_.TrimEnd("\"), $normalizedTarget, [StringComparison]::OrdinalIgnoreCase)
    }

    [Environment]::SetEnvironmentVariable("Path", ($parts -join ";"), "User")
    $envParts = $env:Path -split ";" | Where-Object {
        $_ -and -not [string]::Equals($_.TrimEnd("\"), $normalizedTarget, [StringComparison]::OrdinalIgnoreCase)
    }
    $env:Path = $envParts -join ";"
    Write-Host "[csw] Removed from User PATH: $PathToRemove"
}

function Register-ClaudeSwitchPath {
    param(
        [string]$PathToAdd,
        [string]$LegacyPath
    )

    $current = [Environment]::GetEnvironmentVariable("Path", "User")
    $parts = @()
    if ($current) {
        $parts = $current -split ";" | Where-Object { $_ -and $_.Trim() }
    }

    $normalizedTarget = $PathToAdd.TrimEnd("\")
    $normalizedLegacy = $LegacyPath.TrimEnd("\")
    $filtered = @()
    foreach ($part in $parts) {
        $trimmed = $part.TrimEnd("\")
        if ([string]::Equals($trimmed, $normalizedTarget, [StringComparison]::OrdinalIgnoreCase)) {
            continue
        }
        if ([string]::Equals($trimmed, $normalizedLegacy, [StringComparison]::OrdinalIgnoreCase)) {
            Write-Host "[csw] Removing legacy User PATH entry: $LegacyPath"
            continue
        }
        $filtered += $part
    }

    $newParts = @($PathToAdd) + $filtered
    [Environment]::SetEnvironmentVariable("Path", ($newParts -join ";"), "User")

    $envParts = $env:Path -split ";" | Where-Object {
        $_ -and
        -not [string]::Equals($_.TrimEnd("\"), $normalizedTarget, [StringComparison]::OrdinalIgnoreCase) -and
        -not [string]::Equals($_.TrimEnd("\"), $normalizedLegacy, [StringComparison]::OrdinalIgnoreCase)
    }
    $env:Path = (@($PathToAdd) + $envParts) -join ";"
    Write-Host "[csw] Registered User PATH: $PathToAdd"
}

function Remove-LegacyFiles {
    param(
        [string]$LegacyDir,
        [string]$InstallRoot
    )

    if (-not (Test-Path -LiteralPath $LegacyDir)) {
        return
    }

    $legacyFull = [IO.Path]::GetFullPath($LegacyDir).TrimEnd("\") + "\"
    $installFull = [IO.Path]::GetFullPath($InstallRoot).TrimEnd("\") + "\"
    $legacyNames = @(
        "claude_switch.py",
        "csw.bat",
        "csw.cmd",
        "csw.ps1",
        "claude-sw.bat",
        "claude-sw.cmd",
        "claude-sw.ps1",
        "claude_sw.bat",
        "claude_sw.cmd",
        "claude_sw.ps1"
    )

    foreach ($name in $legacyNames) {
        $path = Join-Path $LegacyDir $name
        if (-not (Test-Path -LiteralPath $path)) {
            continue
        }
        $full = [IO.Path]::GetFullPath($path)
        if ($full.StartsWith($installFull, [StringComparison]::OrdinalIgnoreCase)) {
            continue
        }
        if (-not $full.StartsWith($legacyFull, [StringComparison]::OrdinalIgnoreCase)) {
            throw "Refusing to remove legacy file outside scripts directory: $full"
        }
        Remove-Item -LiteralPath $path -Force
        Write-Host "[csw] Removed legacy file: $path"
    }

    $legacyVenv = Join-Path $LegacyDir ".venv"
    if (Test-Path -LiteralPath $legacyVenv) {
        $venvFull = [IO.Path]::GetFullPath($legacyVenv)
        if ($venvFull.StartsWith($installFull, [StringComparison]::OrdinalIgnoreCase)) {
            return
        }
        if (-not $venvFull.StartsWith($legacyFull, [StringComparison]::OrdinalIgnoreCase)) {
            throw "Refusing to remove legacy venv outside scripts directory: $venvFull"
        }
        Remove-Item -LiteralPath $legacyVenv -Recurse -Force
        Write-Host "[csw] Removed legacy venv: $legacyVenv"
    }
}

function Repair-PowerShellProfiles {
    param(
        [string]$LegacyDir,
        [string]$InstallRoot
    )

    $profilePaths = @(
        $PROFILE.CurrentUserAllHosts,
        $PROFILE.CurrentUserCurrentHost
    ) | Where-Object { $_ } | Select-Object -Unique

    $legacyPattern = [regex]::Escape($LegacyDir.TrimEnd("\"))
    $scriptPattern = "(?i)$legacyPattern\\(claude_switch\.py|csw\.bat|csw\.cmd|csw\.ps1|claude[-_]sw\.(bat|cmd|ps1))"
    $aliasPattern = "(?i)\b(Set-Alias|function)\s+(csw|claude[-_]sw)\b"
    $managedStart = "# >>> ClaudeSwitch managed block >>>"
    $managedEnd = "# <<< ClaudeSwitch managed block <<<"
    $escapedInstallRoot = $InstallRoot.Replace("'", "''")
    $managedBlock = @"
$managedStart
Remove-Item Alias:csw -ErrorAction SilentlyContinue
Remove-Item Alias:claude-sw -ErrorAction SilentlyContinue
Remove-Item Alias:claude_sw -ErrorAction SilentlyContinue
function csw { & '$escapedInstallRoot\csw.ps1' @args }
function claude-sw { & '$escapedInstallRoot\csw.ps1' @args }
$managedEnd
"@

        foreach ($profilePath in $profilePaths) {
        $content = ""
        if (Test-Path -LiteralPath $profilePath) {
            $content = Get-Content -LiteralPath $profilePath -Raw
            $backup = "$profilePath.csw-bak"
            Copy-Item -LiteralPath $profilePath -Destination $backup -Force
            Write-Host "[csw] Profile backup: $backup"
        }

        $content = [regex]::Replace(
            $content,
            "(?s)\r?\n?# >>> ClaudeSwitch managed block >>>.*?# <<< ClaudeSwitch managed block <<<\r?\n?",
            "`r`n"
        )
        $lines = if ($content) { $content -split "\r?\n" } else { @() }
        $changed = $false
        $newLines = foreach ($line in $lines) {
            if ($line -match "^\s*# \[csw installer disabled legacy line" ) {
                $line
            }
            elseif (($line -match $scriptPattern) -or (($line -match $aliasPattern) -and ($line -match "(?i)\.claude\\scripts"))) {
                $changed = $true
                "# [csw installer disabled legacy line] $line"
            }
            else {
                $line
            }
        }

        $profileDir = Split-Path -Parent $profilePath
        if (-not (Test-Path -LiteralPath $profileDir)) {
            New-Item -ItemType Directory -Force -Path $profileDir | Out-Null
        }
        $newContent = (($newLines | Where-Object { $_ -ne $null }) -join "`r`n").TrimEnd()
        if ($newContent) {
            $newContent += "`r`n`r`n"
        }
        $newContent += $managedBlock + "`r`n"
        Set-Content -LiteralPath $profilePath -Value $newContent -Encoding UTF8
        Write-Host "[csw] Repaired PowerShell profile: $profilePath"
        if ($changed) {
            Write-Host "[csw] Disabled legacy profile lines that pointed to old scripts."
        }
    }
}

function Warn-UserClaudeEnvironment {
    $names = @(
        "ANTHROPIC_BASE_URL",
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
        "ANTHROPIC_MODEL",
        "ANTHROPIC_DEFAULT_OPUS_MODEL",
        "ANTHROPIC_DEFAULT_SONNET_MODEL",
        "ANTHROPIC_DEFAULT_HAIKU_MODEL"
    )
    foreach ($name in $names) {
        $value = [Environment]::GetEnvironmentVariable($name, "User")
        if ($value) {
            Write-Host "[csw] Notice: User environment variable $name is set. csw-launched Claude overrides managed values, but direct 'claude' may still use your User env."
        }
    }
}

function Copy-IfDifferent {
    param(
        [string]$Source,
        [string]$Destination
    )

    $sourceFull = [IO.Path]::GetFullPath($Source)
    $destinationFull = [IO.Path]::GetFullPath($Destination)
    if ([string]::Equals($sourceFull, $destinationFull, [StringComparison]::OrdinalIgnoreCase)) {
        return
    }
    Copy-Item -LiteralPath $Source -Destination $Destination -Force
}

function Copy-DirectoryIfDifferent {
    param(
        [string]$Source,
        [string]$Destination
    )

    if (-not (Test-Path -LiteralPath $Source)) {
        return
    }
    $sourceFull = [IO.Path]::GetFullPath($Source)
    $destinationFull = [IO.Path]::GetFullPath($Destination)
    if ([string]::Equals($sourceFull, $destinationFull, [StringComparison]::OrdinalIgnoreCase)) {
        return
    }
    New-Item -ItemType Directory -Force -Path $Destination | Out-Null
    Copy-Item -Path (Join-Path $Source "*") -Destination $Destination -Recurse -Force
}

if ($Elevate -and -not (Test-IsAdmin)) {
    $arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -InstallDir `"$InstallDir`""
    if ($NoPath) { $arguments += " -NoPath" }
    if ($SkipPip) { $arguments += " -SkipPip" }
    if ($NoLegacyCleanup) { $arguments += " -NoLegacyCleanup" }
    if ($DryRun) { $arguments += " -DryRun" }
    Start-Process -FilePath "powershell.exe" -ArgumentList $arguments -Verb RunAs
    exit 0
}

$sourceRoot = $PSScriptRoot
$legacyScriptsDir = Join-Path $env:USERPROFILE ".claude\scripts"
$sourceScript = Join-Path $sourceRoot "claude_switch.py"
$sourceRequirements = Join-Path $sourceRoot "requirements.txt"
$sourceVersion = Join-Path $sourceRoot "VERSION"
$sourceLocales = Join-Path $sourceRoot "locales"
$venvDir = Join-Path $InstallDir ".venv"
$venvPython = Join-Path $venvDir "Scripts\python.exe"

if (-not (Test-Path -LiteralPath $sourceScript)) {
    throw "Cannot find source script: $sourceScript"
}
if (-not (Test-Path -LiteralPath $sourceRequirements)) {
    throw "Cannot find requirements.txt: $sourceRequirements"
}

$version = if (Test-Path -LiteralPath $sourceVersion) { (Get-Content -LiteralPath $sourceVersion -Raw).Trim() } else { "0.1.0" }

Write-Host "[csw] Installing Claude Switch $version"
Write-Host "[csw] InstallDir: $InstallDir"
Write-Host "[csw] Admin: $(if (Test-IsAdmin) { 'yes' } else { 'no' })"

Invoke-InstallStep "Creating install directory" {
    New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
}

Invoke-InstallStep "Copying application files" {
    Copy-IfDifferent -Source $sourceScript -Destination (Join-Path $InstallDir "claude_switch.py")
    Copy-IfDifferent -Source $sourceRequirements -Destination (Join-Path $InstallDir "requirements.txt")
    if (Test-Path -LiteralPath $sourceVersion) {
        Copy-IfDifferent -Source $sourceVersion -Destination (Join-Path $InstallDir "VERSION")
    }
    Copy-DirectoryIfDifferent -Source $sourceLocales -Destination (Join-Path $InstallDir "locales")
}

Invoke-InstallStep "Writing launchers" {
    $cmdLauncher = @'
@echo off
setlocal
set "CSW_HOME=%~dp0"
"%CSW_HOME%.venv\Scripts\python.exe" "%CSW_HOME%claude_switch.py" %*
exit /b %ERRORLEVEL%
'@
    Set-Content -LiteralPath (Join-Path $InstallDir "csw.cmd") -Value $cmdLauncher -Encoding ASCII
    Set-Content -LiteralPath (Join-Path $InstallDir "csw.bat") -Value $cmdLauncher -Encoding ASCII
    Set-Content -LiteralPath (Join-Path $InstallDir "claude-sw.cmd") -Value $cmdLauncher -Encoding ASCII
    Set-Content -LiteralPath (Join-Path $InstallDir "claude-sw.bat") -Value $cmdLauncher -Encoding ASCII
    Set-Content -LiteralPath (Join-Path $InstallDir "claude_sw.bat") -Value $cmdLauncher -Encoding ASCII

    $psLauncher = @'
$CswHome = Split-Path -Parent $MyInvocation.MyCommand.Path
& (Join-Path $CswHome ".venv\Scripts\python.exe") (Join-Path $CswHome "claude_switch.py") @args
exit $LASTEXITCODE
'@
    Set-Content -LiteralPath (Join-Path $InstallDir "csw.ps1") -Value $psLauncher -Encoding UTF8
}

if (-not $SkipPip) {
    $python = Resolve-Python
    Invoke-InstallStep "Creating local virtual environment" {
        Remove-LocalVenv -VenvPath $venvDir -InstallRoot $InstallDir
        Invoke-Native -FilePath $python.Exe -Arguments (@($python.Args) + @("-m", "venv", $venvDir)) -ErrorMessage "Failed to create local virtual environment"
    }
    Invoke-InstallStep "Installing Python dependencies into local venv" {
        Invoke-Native -FilePath $venvPython -Arguments @("-m", "pip", "install", "--upgrade", "pip") -ErrorMessage "Failed to upgrade pip in local venv"
        Invoke-Native -FilePath $venvPython -Arguments @("-m", "pip", "install", "-r", (Join-Path $InstallDir "requirements.txt")) -ErrorMessage "Failed to install Python dependencies into local venv"
    }
}
else {
    Write-Host "[csw] Skipped pip dependency installation."
}

if (-not $NoLegacyCleanup) {
    Invoke-InstallStep "Migrating legacy files and shell environment" {
        Remove-LegacyFiles -LegacyDir $legacyScriptsDir -InstallRoot $InstallDir
        Repair-PowerShellProfiles -LegacyDir $legacyScriptsDir -InstallRoot $InstallDir
        Warn-UserClaudeEnvironment
    }
}
else {
    Write-Host "[csw] Skipped legacy cleanup and environment repair."
}

if (-not $NoPath) {
    Invoke-InstallStep "Registering install directory in User PATH" {
        if ($NoLegacyCleanup) {
            Add-UserPath -PathToAdd $InstallDir
        }
        else {
            Register-ClaudeSwitchPath -PathToAdd $InstallDir -LegacyPath $legacyScriptsDir
        }
    }
}
else {
    Write-Host "[csw] Skipped PATH registration."
}

Write-Host "[csw] Done. Open a new terminal and run: csw"
