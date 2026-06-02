[CmdletBinding()]
param(
    [string]$InstallDir = (Join-Path $env:USERPROFILE ".claude\scripts\ClaudeSwitch"),
    [switch]$KeepFiles
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

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
    Write-Host "[csw] Removed from User PATH: $PathToRemove"
}

Remove-UserPath -PathToRemove $InstallDir

if (-not $KeepFiles -and (Test-Path -LiteralPath $InstallDir)) {
    Remove-Item -LiteralPath $InstallDir -Recurse -Force
    Write-Host "[csw] Removed install directory: $InstallDir"
}

Write-Host "[csw] Uninstall complete. Open a new terminal for PATH changes to take effect."
