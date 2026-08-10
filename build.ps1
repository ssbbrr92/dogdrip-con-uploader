$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

python -m pip install -r requirements-build.txt
python -m PyInstaller --noconfirm --clean --onefile --windowed `
  --name "DogDrip.Con-Uploader-v1.1.1" `
  --icon "assets\ic_profile_dd.ico" `
  --exclude-module "numpy" `
  --add-data "assets\ic_profile_dd.png;." `
  --add-data "assets\dogdrip-con-uploader-logo.png;." `
  --add-data "assets\lucide;lucide" `
  --add-data "docs\THIRD_PARTY_NOTICES.md;." `
  "src\app.py"

Write-Host "Built: $root\dist\DogDrip.Con-Uploader-v1.1.1.exe"
