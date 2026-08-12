@echo off
setlocal EnableExtensions
title INSTALAR SCRAPER TRANSITO BOLIVIA FAST
color 0A
cd /d "%~dp0"

echo ==================================================
echo   PRIMERA INSTALACION - V3.2 PREMIUM FAST
echo ==================================================
echo.

set "PYEXE="
python --version >nul 2>nul
if not errorlevel 1 set "PYEXE=python"

if not defined PYEXE (
    py -3 --version >nul 2>nul
    if not errorlevel 1 set "PYEXE=py -3"
)

if not defined PYEXE (
    if exist "%LocalAppData%\Programs\Python\Python312\python.exe" set "PYEXE=%LocalAppData%\Programs\Python\Python312\python.exe"
)

if not defined PYEXE (
    echo Python no encontrado. Intentando instalar Python 3.12...
    where winget >nul 2>nul
    if errorlevel 1 goto :NO_PYTHON
    winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements

    if exist "%LocalAppData%\Programs\Python\Python312\python.exe" (
        set "PYEXE=%LocalAppData%\Programs\Python\Python312\python.exe"
    ) else (
        echo.
        echo Cierra esta ventana y vuelve a ejecutar este BAT.
        pause
        exit /b 0
    )
)

echo Python:
%PYEXE% --version
echo.

echo [1/2] Instalando librerias...
%PYEXE% -m pip install -r requirements.txt
if errorlevel 1 goto :ERROR

echo.
echo [2/2] Instalando Chromium...
%PYEXE% -m playwright install chromium
if errorlevel 1 goto :ERROR

echo OK>"%~dp0.setup_ok"

echo.
echo ==================================================
echo INSTALACION TERMINADA
echo ==================================================
echo A partir de ahora usa:
echo.
echo     01_EJECUTAR_RAPIDO.bat
echo.
pause
exit /b 0

:NO_PYTHON
echo Instala Python 3.12 y marca "Add Python to PATH".
pause
exit /b 1

:ERROR
echo Hubo un error. Mandame una captura.
pause
exit /b 1
