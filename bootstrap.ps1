[CmdletBinding()]
param(
    [string]$InstallDir = (Join-Path $env:USERPROFILE ".claude\scripts\claude-switch-tui"),
    [switch]$NoPath,
    [switch]$SkipPip,
    [switch]$NoLegacyCleanup,
    [switch]$ResetVenv,
    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Repo = "AonoChano/claude-switch-tui"
$LatestReleaseApi = "https://api.github.com/repos/$Repo/releases/latest"
$UserAgent = "ClaudeSwitchBootstrap"

function Enable-Tls12 {
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    }
    catch {
    }
}

function Get-LatestRelease {
    Enable-Tls12
    $headers = @{ "User-Agent" = $UserAgent }
    try {
        return Invoke-RestMethod -Uri $LatestReleaseApi -Headers $headers -UseBasicParsing
    }
    catch {
        throw "Failed to query latest ClaudeSwitch release from GitHub: $($_.Exception.Message)"
    }
}

function Invoke-Installer {
    param(
        [string]$InstallScript
    )

    $arguments = @(
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        $InstallScript,
        "-InstallDir",
        $InstallDir
    )
    if ($NoPath) { $arguments += "-NoPath" }
    if ($SkipPip) { $arguments += "-SkipPip" }
    if ($NoLegacyCleanup) { $arguments += "-NoLegacyCleanup" }
    if ($ResetVenv) { $arguments += "-ResetVenv" }
    if ($DryRun) { $arguments += "-DryRun" }

    & powershell.exe @arguments
    if ($LASTEXITCODE -ne 0) {
        throw "ClaudeSwitch installer failed with exit code $LASTEXITCODE."
    }
}

$tempRoot = Join-Path ([IO.Path]::GetTempPath()) ("claude-switch-tui-" + [guid]::NewGuid().ToString("N"))

try {
    $release = Get-LatestRelease
    if (-not $release.zipball_url) {
        throw "Latest release does not expose a source zip URL."
    }

    Write-Host "[csw] Latest release: $($release.tag_name)"
    New-Item -ItemType Directory -Force -Path $tempRoot | Out-Null
    $zipPath = Join-Path $tempRoot "source.zip"

    Enable-Tls12
    Write-Host "[csw] Downloading release source zip..."
    Invoke-WebRequest -Uri $release.zipball_url -OutFile $zipPath -Headers @{ "User-Agent" = $UserAgent } -UseBasicParsing

    Write-Host "[csw] Extracting release source zip..."
    Expand-Archive -LiteralPath $zipPath -DestinationPath $tempRoot -Force
    $sourceDir = Get-ChildItem -LiteralPath $tempRoot -Directory | Select-Object -First 1
    if (-not $sourceDir) {
        throw "Release archive did not contain a source directory."
    }

    $installScript = Join-Path $sourceDir.FullName "install.ps1"
    if (-not (Test-Path -LiteralPath $installScript)) {
        throw "Release archive did not contain install.ps1."
    }

    Invoke-Installer -InstallScript $installScript
}
finally {
    if (Test-Path -LiteralPath $tempRoot) {
        Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}
