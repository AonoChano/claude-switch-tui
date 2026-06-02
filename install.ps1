[CmdletBinding()]
param(
    [string]$InstallDir = (Join-Path $env:USERPROFILE ".claude\scripts\claude-switch-tui"),
    [switch]$NoPath,
    [switch]$SkipPip,
    [switch]$NoLegacyCleanup,
    [switch]$Elevate,
    [switch]$ResetVenv,
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

function Get-PythonDisplayName {
    param([hashtable]$Candidate)

    $argsText = ""
    if ($Candidate.Args -and $Candidate.Args.Count -gt 0) {
        $argsText = " " + ($Candidate.Args -join " ")
    }
    return "$($Candidate.Exe)$argsText"
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

function Get-PythonCandidates {
    $candidates = @()

    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        foreach ($selector in @("-3.13", "-3.12", "-3.11", "-3.10", "-3")) {
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

    return $candidates
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

function Remove-InstallLaunchers {
    param([string]$InstallRoot)

    $names = @(
        "csw.cmd",
        "csw.bat",
        "csw.ps1",
        "claude-sw.cmd",
        "claude-sw.bat",
        "claude_sw.bat"
    )
    $installFull = [IO.Path]::GetFullPath($InstallRoot).TrimEnd("\") + "\"
    foreach ($name in $names) {
        $path = Join-Path $InstallRoot $name
        if (-not (Test-Path -LiteralPath $path)) {
            continue
        }
        $full = [IO.Path]::GetFullPath($path)
        if (-not $full.StartsWith($installFull, [StringComparison]::OrdinalIgnoreCase)) {
            throw "Refusing to remove launcher outside install directory: $full"
        }
        Remove-Item -LiteralPath $path -Force
    }
}

function New-LocalVenv {
    param(
        [string]$VenvPath,
        [string]$VenvPython,
        [string]$InstallRoot
    )

    $allCandidates = @(Get-PythonCandidates)
    $usableCandidates = @()
    foreach ($candidate in $allCandidates) {
        if (Test-PythonCandidate -Exe $candidate.Exe -Args $candidate.Args) {
            $usableCandidates += $candidate
        }
    }

    if (-not $usableCandidates -or $usableCandidates.Count -eq 0) {
        $detected = if ($allCandidates -and $allCandidates.Count -gt 0) {
            ($allCandidates | ForEach-Object { Get-PythonDisplayName -Candidate $_ }) -join ", "
        }
        else {
            "none"
        }
        $message = @(
            "Python 3.10+ with venv support was not found.",
            "Detected Python commands: $detected",
            "Install Python 3.10+ from https://www.python.org/downloads/windows/ and enable 'Add python.exe to PATH'.",
            "Then open a new PowerShell and rerun the installer."
        ) -join [Environment]::NewLine
        throw $message
    }

    $attempts = @()
    foreach ($candidate in $usableCandidates) {
        $label = Get-PythonDisplayName -Candidate $candidate
        Write-Host "[csw] Trying Python: $label"
        Remove-LocalVenv -VenvPath $VenvPath -InstallRoot $InstallRoot

        $previousErrorAction = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        $output = @()
        $exitCode = 1
        try {
            $output = & $candidate.Exe @($candidate.Args) -m venv $VenvPath 2>&1
            $exitCode = $LASTEXITCODE
        }
        catch {
            $output = @($_.Exception.Message)
            $exitCode = 1
        }
        finally {
            $ErrorActionPreference = $previousErrorAction
        }

        if ($exitCode -eq 0 -and (Test-Path -LiteralPath $VenvPython)) {
            return
        }

        $summary = ($output | Select-Object -First 3) -join " "
        if ($summary) {
            $attempts += "$label -> exit $exitCode; $summary"
        }
        else {
            $attempts += "$label -> exit $exitCode"
        }
    }

    Remove-LocalVenv -VenvPath $VenvPath -InstallRoot $InstallRoot
    $message = @(
        "Could not create ClaudeSwitch local virtual environment.",
        "Tried: $($attempts -join ' | ')",
        "Install or repair Python 3.10+, then rerun the installer."
    ) -join [Environment]::NewLine
    throw $message
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

    $newPath = if ($current) { "$PathToAdd;$current" } else { $PathToAdd }
    [Environment]::SetEnvironmentVariable("Path", $newPath, "User")
    if (($env:Path -split ";") -notcontains $PathToAdd) {
        $env:Path = "$PathToAdd;$env:Path"
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
        [string[]]$LegacyPaths = @()
    )

    $current = [Environment]::GetEnvironmentVariable("Path", "User")
    $parts = @()
    if ($current) {
        $parts = $current -split ";" | Where-Object { $_ -and $_.Trim() }
    }

    $normalizedTarget = $PathToAdd.TrimEnd("\")
    $normalizedLegacyPaths = @()
    foreach ($legacyPath in $LegacyPaths) {
        if ($legacyPath) {
            $normalizedLegacyPaths += $legacyPath.TrimEnd("\")
        }
    }
    $filtered = @()
    foreach ($part in $parts) {
        $trimmed = $part.TrimEnd("\")
        if ([string]::Equals($trimmed, $normalizedTarget, [StringComparison]::OrdinalIgnoreCase)) {
            continue
        }
        $isLegacy = $false
        foreach ($legacyPath in $normalizedLegacyPaths) {
            if ([string]::Equals($trimmed, $legacyPath, [StringComparison]::OrdinalIgnoreCase)) {
                Write-Host "[csw] Removing legacy User PATH entry: $part"
                $isLegacy = $true
                break
            }
        }
        if ($isLegacy) {
            continue
        }
        $filtered += $part
    }

    $newParts = @($PathToAdd) + $filtered
    [Environment]::SetEnvironmentVariable("Path", ($newParts -join ";"), "User")

    $envParts = @()
    foreach ($envPart in ($env:Path -split ";")) {
        if (-not $envPart) {
            continue
        }
        $trimmed = $envPart.TrimEnd("\")
        if ([string]::Equals($trimmed, $normalizedTarget, [StringComparison]::OrdinalIgnoreCase)) {
            continue
        }
        $isLegacy = $false
        foreach ($legacyPath in $normalizedLegacyPaths) {
            if ([string]::Equals($trimmed, $legacyPath, [StringComparison]::OrdinalIgnoreCase)) {
                $isLegacy = $true
                break
            }
        }
        if (-not $isLegacy) {
            $envParts += $envPart
        }
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

function Remove-LegacyInstallDirectory {
    param(
        [string]$LegacyInstallDir,
        [string]$InstallRoot,
        [string]$SourceRoot
    )

    if (-not (Test-Path -LiteralPath $LegacyInstallDir)) {
        return
    }

    $legacyFull = [IO.Path]::GetFullPath($LegacyInstallDir).TrimEnd("\") + "\"
    $installFull = [IO.Path]::GetFullPath($InstallRoot).TrimEnd("\") + "\"
    $sourceFull = [IO.Path]::GetFullPath($SourceRoot).TrimEnd("\") + "\"
    $scriptsFull = [IO.Path]::GetFullPath((Join-Path $env:USERPROFILE ".claude\scripts")).TrimEnd("\") + "\"
    $runningDir = [Environment]::GetEnvironmentVariable("CLAUDE_SWITCH_RUNNING_DIR", "Process")
    $runningFull = ""
    if ($runningDir) {
        $runningFull = [IO.Path]::GetFullPath($runningDir).TrimEnd("\") + "\"
    }

    if ($legacyFull -eq $installFull -or $legacyFull -eq $sourceFull -or ($runningFull -and $legacyFull -eq $runningFull)) {
        return
    }
    if (-not $legacyFull.StartsWith($scriptsFull, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to clean legacy install directory outside .claude scripts: $legacyFull"
    }

    $legacyItems = @(
        "claude_switch.py",
        "requirements.txt",
        "VERSION",
        "install.ps1",
        "uninstall.ps1",
        "bootstrap.ps1",
        "install.sh",
        "uninstall.sh",
        "bootstrap.sh",
        "csw.cmd",
        "csw.bat",
        "csw.ps1",
        "claude-sw.cmd",
        "claude-sw.bat",
        "claude_sw.bat",
        "locales",
        ".venv"
    )

    foreach ($name in $legacyItems) {
        $path = Join-Path $LegacyInstallDir $name
        if (-not (Test-Path -LiteralPath $path)) {
            continue
        }
        $full = [IO.Path]::GetFullPath($path)
        if (-not $full.StartsWith($legacyFull, [StringComparison]::OrdinalIgnoreCase)) {
            throw "Refusing to remove legacy item outside legacy install directory: $full"
        }
        Remove-Item -LiteralPath $path -Recurse -Force
        Write-Host "[csw] Removed legacy install item: $path"
    }

    $remaining = Get-ChildItem -LiteralPath $LegacyInstallDir -Force -ErrorAction SilentlyContinue
    if (-not $remaining) {
        Remove-Item -LiteralPath $LegacyInstallDir -Force
        Write-Host "[csw] Removed empty legacy install directory: $LegacyInstallDir"
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
    if ($ResetVenv) { $arguments += " -ResetVenv" }
    if ($DryRun) { $arguments += " -DryRun" }
    Start-Process -FilePath "powershell.exe" -ArgumentList $arguments -Verb RunAs
    exit 0
}

$sourceRoot = $PSScriptRoot
$legacyScriptsDir = Join-Path $env:USERPROFILE ".claude\scripts"
$legacyInstallDirs = @(
    (Join-Path $legacyScriptsDir "ClaudeSwitch")
) | Select-Object -Unique
$legacyPathEntries = @($legacyScriptsDir) + $legacyInstallDirs
$sourceScript = Join-Path $sourceRoot "claude_switch.py"
$sourceRequirements = Join-Path $sourceRoot "requirements.txt"
$sourceVersion = Join-Path $sourceRoot "VERSION"
$sourceLocales = Join-Path $sourceRoot "locales"
$sourceInstall = Join-Path $sourceRoot "install.ps1"
$sourceUninstall = Join-Path $sourceRoot "uninstall.ps1"
$sourceBootstrap = Join-Path $sourceRoot "bootstrap.ps1"
$sourceInstallSh = Join-Path $sourceRoot "install.sh"
$sourceUninstallSh = Join-Path $sourceRoot "uninstall.sh"
$sourceBootstrapSh = Join-Path $sourceRoot "bootstrap.sh"
$venvDir = Join-Path $InstallDir ".venv"
$venvPython = Join-Path $venvDir "Scripts\python.exe"

if (-not (Test-Path -LiteralPath $sourceScript)) {
    throw "Cannot find source script: $sourceScript"
}
if (-not (Test-Path -LiteralPath $sourceRequirements)) {
    throw "Cannot find requirements.txt: $sourceRequirements"
}

$version = if (Test-Path -LiteralPath $sourceVersion) { (Get-Content -LiteralPath $sourceVersion -Raw).Trim() } else { "0.2.0" }

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
    foreach ($script in @($sourceInstall, $sourceUninstall, $sourceBootstrap, $sourceInstallSh, $sourceUninstallSh, $sourceBootstrapSh)) {
        if (Test-Path -LiteralPath $script) {
            Copy-IfDifferent -Source $script -Destination (Join-Path $InstallDir (Split-Path -Leaf $script))
        }
    }
    Copy-DirectoryIfDifferent -Source $sourceLocales -Destination (Join-Path $InstallDir "locales")
}

if (-not $SkipPip) {
    Invoke-InstallStep "Preparing local virtual environment" {
        if ($ResetVenv) {
            Remove-LocalVenv -VenvPath $venvDir -InstallRoot $InstallDir
        }
        if (-not (Test-Path -LiteralPath $venvPython)) {
            Remove-InstallLaunchers -InstallRoot $InstallDir
            New-LocalVenv -VenvPath $venvDir -VenvPython $venvPython -InstallRoot $InstallDir
        }
        else {
            Write-Host "[csw] Reusing existing virtual environment: $venvDir"
        }
    }
    Invoke-InstallStep "Installing Python dependencies into local venv" {
        Invoke-Native -FilePath $venvPython -Arguments @("-m", "pip", "install", "--upgrade", "pip") -ErrorMessage "Failed to upgrade pip in local venv"
        Invoke-Native -FilePath $venvPython -Arguments @("-m", "pip", "install", "-r", (Join-Path $InstallDir "requirements.txt")) -ErrorMessage "Failed to install Python dependencies into local venv"
    }
}
else {
    Write-Host "[csw] Skipped pip dependency installation."
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

if (-not $NoLegacyCleanup) {
    Invoke-InstallStep "Migrating legacy files and shell environment" {
        Remove-LegacyFiles -LegacyDir $legacyScriptsDir -InstallRoot $InstallDir
        foreach ($legacyInstallDir in $legacyInstallDirs) {
            Remove-LegacyInstallDirectory -LegacyInstallDir $legacyInstallDir -InstallRoot $InstallDir -SourceRoot $sourceRoot
        }
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
            Register-ClaudeSwitchPath -PathToAdd $InstallDir -LegacyPaths $legacyPathEntries
        }
    }
}
else {
    Write-Host "[csw] Skipped PATH registration."
}

Write-Host "[csw] Done. Open a new terminal and run: csw"
