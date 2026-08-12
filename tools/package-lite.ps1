$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$source = Join-Path $repoRoot "lite-extension"
$outputDir = Join-Path $repoRoot "dist"
$packageName = "DogDrip.Con-Uploader-Lite-v1.0.1"
$folderOutput = Join-Path $outputDir $packageName
$zipOutput = Join-Path $outputDir "$packageName.zip"

if (-not (Test-Path $outputDir)) {
    New-Item -ItemType Directory -Path $outputDir | Out-Null
}

# Keep one stable unpacked-extension path so Chrome only needs this folder
# registered once. Rebuilding replaces its contents in place.
if (-not (Test-Path $folderOutput)) {
    New-Item -ItemType Directory -Path $folderOutput | Out-Null
}
Get-ChildItem -LiteralPath $folderOutput -Force | Remove-Item -Recurse -Force
Copy-Item -Path (Join-Path $source "*") -Destination $folderOutput -Recurse -Force

if (Test-Path $zipOutput) {
    try {
        Remove-Item -LiteralPath $zipOutput -Force
        Compress-Archive -Path (Join-Path $folderOutput "*") -DestinationPath $zipOutput -CompressionLevel Optimal
    }
    catch [System.IO.IOException] {
        Write-Warning "ZIP 파일이 사용 중이라 갱신하지 못했습니다: $zipOutput"
    }
}
else {
    Compress-Archive -Path (Join-Path $folderOutput "*") -DestinationPath $zipOutput -CompressionLevel Optimal
}

Write-Host "Updated folder: $folderOutput"
Write-Host "Updated ZIP:    $zipOutput"
