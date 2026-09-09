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

# Moteur d'IA locale : seules les bibliothèques CPU sont reprises. Les variantes
# CUDA pèsent des centaines de mégaoctets pour un GPU que la plupart des postes
# visés n'ont pas, et GPT4All se rabat proprement sur le CPU sans elles.
binaries = []
try:
    import shutil as _shutil

    import gpt4all
    _gpt4all_dest = os.path.join('gpt4all', 'llmodel_DO_NOT_MODIFY', 'build')
    _gpt4all_build = os.path.join(
        os.path.dirname(gpt4all.__file__), 'llmodel_DO_NOT_MODIFY', 'build'
    )
    for _name in os.listdir(_gpt4all_build):
        if _name.endswith('.dll') and 'cuda' not in _name.lower():
            binaries.append((os.path.join(_gpt4all_build, _name), _gpt4all_dest))

    # GPT4All charge d'abord libllmodel.dll et ne se rabat sur llmodel.dll que
    # sur FileNotFoundError. Une fois figé, PyInstaller intercepte ctypes.CDLL et
    # lève à la place une PyInstallerImportError : le repli ne s'exécute jamais
    # et l'application démarre sans moteur. On livre donc la DLL sous les deux
    # noms pour que la première tentative aboutisse.
    _msvc_dll = os.path.join(_gpt4all_build, 'llmodel.dll')
    if os.path.isfile(_msvc_dll):
        _alias_dir = os.path.join(os.path.abspath('build'), 'gpt4all_alias')
        os.makedirs(_alias_dir, exist_ok=True)
        _alias = os.path.join(_alias_dir, 'libllmodel.dll')
        _shutil.copyfile(_msvc_dll, _alias)
        binaries.append((_alias, _gpt4all_dest))
except Exception:
    pass

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=[
        'pypdf',
        'docx',
        'watchdog',
        'watchdog.observers',
        'watchdog.events',
        'PIL',
        'PIL.Image',
        'gpt4all',
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
