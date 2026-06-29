# -*- mode: python ; coding: utf-8 -*-

a = Analysis(
    ["tray_app.py"],
    pathex=[],
    binaries=[],
    datas=[("config.json", "."), ("assets", "assets")],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "pydoc",
        "unittest",
        "xmlrpc",
        "multiprocessing",
        "PyQt6",
        "PySide6",
    ],
    noarchive=False,
    optimize=2,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="DeltaResolutionSwitcher",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="icon.ico",
)
