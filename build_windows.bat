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
%PYTHON% -c "import PySide6, pypdf, docx, watchdog, pymupdf, PyInstaller" >nul 2>&1
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

echo [3/4] Verification du moteur OCR embarque...
if exist "tesseract\tesseract.exe" (
    echo Dossier tesseract\ trouve : l'OCR sera inclus dans l'executable.
) else (
    echo Dossier tesseract\ absent : l'executable se rabattra sur un Tesseract
    echo installe sur la machine. Pour l'embarquer, copiez tesseract.exe, ses
    echo DLL et le dossier tessdata dans un dossier tesseract\ a la racine.
)

echo [4/4] Construction de Classeur.exe...
%PYTHON% -m PyInstaller classeur.spec --distpath release --workpath build --noconfirm
if errorlevel 1 goto :error

echo.
echo Construction terminee.
echo L'executable se trouve dans release\Classeur\Classeur.exe
echo Partagez tout le dossier release\Classeur, pas seulement le .exe.
if /I "%CI%"=="true" exit /b 0
pause
exit /b 0

:error
echo.
echo La construction a echoue. Lis le message ci-dessus.
pause
exit /b 1
