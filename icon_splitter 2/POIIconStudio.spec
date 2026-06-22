# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_data_files


datas = collect_data_files("easyocr")
hiddenimports = [
    "cv2",
    "easyocr",
    "numpy",
    "openpyxl",
    "scipy",
    "scipy.ndimage",
]

a = Analysis(
    ["web_app.py"],
    pathex=["."],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="POI Icon Studio",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="POI Icon Studio",
)

app = BUNDLE(
    coll,
    name="POI Icon Studio.app",
    icon=None,
    bundle_identifier="com.chongyu.poi-icon-studio",
    version="1.1.0",
    info_plist={
        "NSHighResolutionCapable": True,
        "LSMinimumSystemVersion": "11.0",
        "CFBundleDisplayName": "POI Icon Studio",
    },
)
