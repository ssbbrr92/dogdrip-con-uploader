$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

python -m pip install -r requirements-build.txt
python -m PyInstaller --noconfirm --clean --onefile --windowed `
  --name "DogDrip.Con-Uploader-v1.1.0" `
  --icon "assets\ic_profile_dd.ico" `
  --add-data "assets\ic_profile_dd.png;." `
  --add-data "assets\dogdrip-con-uploader-logo.png;." `
  "src\app.py"

Write-Host "Built: $root\dist\DogDrip.Con-Uploader-v1.1.0.exe"
