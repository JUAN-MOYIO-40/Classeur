# -*- mode: python ; coding: utf-8 -*-
import os

block_cipher = None

# Le moteur OCR est embarqué quand un dossier tesseract/ est présent à la racine
# (tesseract.exe, ses DLL et tessdata). Ce dossier n'est pas versionné : sans
# lui la construction reste possible et l'application se rabat sur un Tesseract
# installé sur la machine, en signalant son absence sur le tableau de bord.
datas = [('assets', 'assets')]
if os.path.isdir('tesseract'):
    datas.append(('tesseract', 'tesseract'))

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=[
        'pypdf',
        'docx',
        'watchdog',
        'watchdog.observers',
        'watchdog.events',
        'PIL',
        'PIL.Image',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'matplotlib',
        'scipy',
        'numpy',
        'llama_cpp',
        'llama_cpp_python',
    ],
    noarchive=False,
    cipher=block_cipher,
)

pyz = PYZ(a.pure, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Classeur',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name='Classeur',
)
