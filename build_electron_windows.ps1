$ErrorActionPreference = "Stop"

python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r midea_ac_controller\requirements.txt
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean midea_backend.spec

if (!(Test-Path "midea_ac_controller\electron\backend")) {
  New-Item -ItemType Directory -Path "midea_ac_controller\electron\backend" | Out-Null
}
Copy-Item "dist\midea_backend.exe" "midea_ac_controller\electron\backend\midea_backend.exe" -Force
if (Test-Path "midea_ac_controller\electron\web") {
  Remove-Item "midea_ac_controller\electron\web" -Recurse -Force
}
Copy-Item "midea_ac_controller\web" "midea_ac_controller\electron\web" -Recurse -Force

Push-Location "midea_ac_controller\electron"
npm install
npm run pack
Pop-Location
