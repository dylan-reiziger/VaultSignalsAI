[CmdletBinding()]
param(
    [string]$Version = "local"
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    $python = "python"
}

$releaseDirectory = Join-Path $projectRoot "release"
$packageDirectory = Join-Path $releaseDirectory "VaultSignalsAI"
$archivePath = Join-Path $releaseDirectory "VaultSignalsAI-windows-x64.zip"

if (Test-Path $archivePath) {
    Remove-Item $archivePath -Force
}

& $python -m PyInstaller --noconfirm --clean --distpath $releaseDirectory VaultSignalsAI.spec
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller did not complete successfully."
}

Copy-Item (Join-Path $projectRoot "LEGAL-NOTICE.txt") (Join-Path $packageDirectory "LEGAL-NOTICE.txt") -Force
Copy-Item (Join-Path $projectRoot "BUSINESS-REVIEW.md") (Join-Path $packageDirectory "BUSINESS-REVIEW.md") -Force
Compress-Archive -Path $packageDirectory -DestinationPath $archivePath -Force

Write-Host "Built VaultSignalsAI $Version"
Write-Host "Download package: $archivePath"
