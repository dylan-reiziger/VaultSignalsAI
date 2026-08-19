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
$checksumPath = "$archivePath.sha256"
$versionAssetPath = Join-Path $projectRoot "assets\VaultSignalsAI-version.txt"

if (Test-Path $archivePath) {
    Remove-Item $archivePath -Force
}
if (Test-Path $checksumPath) {
    Remove-Item $checksumPath -Force
}
Set-Content -Path $versionAssetPath -Value $Version -NoNewline -Encoding ascii

& $python -m PyInstaller --noconfirm --clean --distpath $releaseDirectory VaultSignalsAI.spec
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller did not complete successfully."
}

Copy-Item (Join-Path $projectRoot "LEGAL-NOTICE.txt") (Join-Path $packageDirectory "LEGAL-NOTICE.txt") -Force
Copy-Item (Join-Path $projectRoot "BUSINESS-REVIEW.md") (Join-Path $packageDirectory "BUSINESS-REVIEW.md") -Force
Compress-Archive -Path $packageDirectory -DestinationPath $archivePath -Force
$archiveHash = (Get-FileHash -Path $archivePath -Algorithm SHA256).Hash.ToLowerInvariant()
"$archiveHash  $(Split-Path -Leaf $archivePath)" | Set-Content -Path $checksumPath -Encoding ascii

Write-Host "Built VaultSignalsAI $Version"
Write-Host "Download package: $archivePath"
Write-Host "SHA-256 checksum: $checksumPath"
