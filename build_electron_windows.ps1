$ErrorActionPreference = "Stop"

$PackageJson = Get-Content "midea_ac_controller\electron\package.json" -Raw | ConvertFrom-Json
$AppVersion = $PackageJson.version
$GitCommit = (git rev-parse --short HEAD).Trim()
$BuiltAt = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
$VersionInfo = [ordered]@{
  version = $AppVersion
  commit = $GitCommit
  built_at = $BuiltAt
}
$VersionInfo | ConvertTo-Json | Set-Content "midea_ac_controller\web\version.json" -Encoding UTF8

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
$DistDir = Join-Path (Get-Location) "dist"
$PortableExe = Get-ChildItem $DistDir -Filter "*.exe" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if ($PortableExe) {
  $TargetName = "midea-ac-controller-v$AppVersion-$GitCommit.exe"
  Copy-Item $PortableExe.FullName (Join-Path $DistDir $TargetName) -Force
}
Pop-Location
