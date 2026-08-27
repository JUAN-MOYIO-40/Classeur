@echo off
setlocal
cd /d "%~dp0"

echo [1/4] Verification de l'environnement Python...
if not exist ".venv\Scripts\python.exe" (
    py -3 -m venv .venv
    if errorlevel 1 goto :error
)

set "PYTHON=.venv\Scripts\python.exe"

echo [2/4] Verification des dependances locales...
%PYTHON% -c "import PySide6, pypdf, docx, watchdog, PyInstaller" >nul 2>&1
if errorlevel 1 (
    echo Dependances absentes : installation initiale requise.
    echo Une connexion Internet est necessaire uniquement pour cette etape.
    %PYTHON% -m pip install --disable-pip-version-check -r requirements.txt pyinstaller
    if errorlevel 1 goto :error
) else (
    echo Dependances deja presentes : construction hors connexion possible.
)

%PYTHON% -m pip check >nul 2>&1
if errorlevel 1 (
    echo Les dependances sont incoherentes. Relance de l'installation...
    %PYTHON% -m pip install --disable-pip-version-check -r requirements.txt pyinstaller
    if errorlevel 1 goto :error
)

echo [3/4] Verification OCR optionnel...
set "OCR_OK=1"
where tesseract.exe >nul 2>&1
if errorlevel 1 (
    echo OCR PDF scanne desactive : tesseract.exe absent du PATH.
    set "OCR_OK=0"
)
where pdftoppm.exe >nul 2>&1
if errorlevel 1 (
    echo OCR PDF scanne desactive : pdftoppm.exe absent du PATH.
    set "OCR_OK=0"
)
if "%OCR_OK%"=="1" echo Les outils OCR sont disponibles.

echo Construction de MDJR_Classeur.exe...
%PYTHON% -m PyInstaller --noconfirm --clean --windowed --name MDJR_Classeur --add-data "assets;assets" --hidden-import pypdf --hidden-import docx --hidden-import watchdog main.py
if errorlevel 1 goto :error

echo [4/4] Construction terminee.
echo L'executable se trouve dans dist\MDJR_Classeur\MDJR_Classeur.exe
 echo Tu peux compresser le dossier dist\MDJR_Classeur pour le partager.
 if /I "%CI%"=="true" exit /b 0
 pause
 exit /b 0

:error
echo.
echo La construction a echoue. Lis le message ci-dessus.
pause
exit /b 1
