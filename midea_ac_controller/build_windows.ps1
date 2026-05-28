$ErrorActionPreference = "Stop"

python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r midea_ac_controller\requirements.txt
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean midea_ac_controller.spec

