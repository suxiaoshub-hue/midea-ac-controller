# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

block_cipher = None
project_dir = Path(__file__).resolve().parent

a = Analysis(
    [str(project_dir / "backend_entry.py")],
    pathex=[str(project_dir)],
    binaries=[],
    datas=[],
    hiddenimports=[
        "aiohttp",
        "aiofiles",
        "Crypto",
        "Crypto.Cipher",
        "Crypto.Util.Padding",
        "Crypto.Util.strxor",
        "requests",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "homeassistant"],
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="midea_backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
)

