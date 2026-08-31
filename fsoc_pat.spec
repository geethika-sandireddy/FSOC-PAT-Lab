# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for AI-FSOC PAT Mission Console
# Build: pyinstaller fsoc_pat.spec

import sys
from pathlib import Path

block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        'pygame',
        'cv2',
        'numpy',
        'core',
        'core.scene',
        'core.sensor',
        'core.disturbances',
        'core.detection',
        'core.tracking',
        'core.gimbal',
        'core.control',
        'core.geometry',
        'core.orbital',
        'core.simulator',
        'ai',
        'ai.classifier',
        'metrics',
        'metrics.performance',
        'metrics.stress_test',
        'ui',
        'ui.theme',
        'ui.widgets',
        'ui.view3d',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'scipy', 'pandas'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='FSOC_PAT_Mission_Console',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # windowed mode
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,  # add icon='assets/icon.ico' if available
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='FSOC_PAT_Mission_Console',
)
