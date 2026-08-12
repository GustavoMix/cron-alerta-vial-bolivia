@echo off
setlocal EnableExtensions
title SCRAPER TRANSITO BOLIVIA V2
color 0A
cd /d "%~dp0"

echo ==================================================
echo   SCRAPER HIBRIDO TRANSITO BOLIVIA V3
echo   30 FACEBOOK + WEB + HISTORIAL + FOTOS + VIDEOS + RUTAS
echo ==================================================
echo.

set "PYEXE="

REM 1) Intentar Python normal.
python --version >nul 2>nul
if not errorlevel 1 set "PYEXE=python"

REM 2) Intentar launcher py.
if not defined PYEXE (
    py -3 --version >nul 2>nul
    if not errorlevel 1 set "PYEXE=py -3"
)

REM 3) Rutas comunes de Python 3.12.
if not defined PYEXE (
    if exist "%LocalAppData%\Programs\Python\Python312\python.exe" set "PYEXE=%LocalAppData%\Programs\Python\Python312\python.exe"
)
if not defined PYEXE (
    if exist "C:\Program Files\Python312\python.exe" set "PYEXE=C:\Program Files\Python312\python.exe"
)

REM 4) Si no existe, instalar con winget.
if not defined PYEXE (
    echo Python no esta instalado.
    echo Intentando instalar Python 3.12 automaticamente...
    echo.
    where winget >nul 2>nul
    if errorlevel 1 goto :NO_WINGET

    winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements

    if exist "%LocalAppData%\Programs\Python\Python312\python.exe" (
        set "PYEXE=%LocalAppData%\Programs\Python\Python312\python.exe"
    ) else (
        echo.
        echo Python fue instalado pero Windows necesita refrescar el PATH.
        echo Cierra esta ventana y vuelve a ejecutar este mismo BAT.
        echo.
        pause
        exit /b 0
    )
)

echo Python:
%PYEXE% --version
echo.

if not exist "requirements.txt" (
    echo ERROR: Pon este BAT dentro de la carpeta scraper_transito_bolivia.
    echo Debe estar junto a main.py y requirements.txt.
    pause
    exit /b 1
)

echo [1/4] Actualizando PIP...
%PYEXE% -m pip install --upgrade pip
if errorlevel 1 goto :ERROR

echo.
echo [2/4] Instalando librerias...
%PYEXE% -m pip install -r requirements.txt
if errorlevel 1 goto :ERROR

echo.
echo [3/4] Instalando Chromium para Facebook...
%PYEXE% -m playwright install chromium
if errorlevel 1 goto :ERROR

echo.
echo [4/4] Ejecutando las 37 fuentes con filtro premium...
echo.
%PYEXE% main.py
if errorlevel 1 goto :ERROR

echo.
echo ==================================================
echo   PRUEBA FINALIZADA
echo ==================================================
echo.
echo Mira estos archivos:
echo.
echo   data\estado_fuentes.json
echo       = cuales fuentes funcionaron/fallaron
echo.
echo   data\alertas_viales.json
echo       = alertas finales fusionadas
echo.
echo   data\alertas_individuales.json
echo       = todo lo encontrado antes de fusionar
echo.
echo   data\incidentes_historial.json
echo       = historial de estados entre ejecuciones
echo.
echo   data\alertas_viales.csv
echo       = version facil de abrir en Excel
echo.
pause
exit /b 0

:NO_WINGET
echo.
echo No encontre winget.
echo Instala Python 3.12 desde python.org y marca:
echo     Add python.exe to PATH
echo Luego vuelve a ejecutar este BAT.
echo.
pause
exit /b 1

:ERROR
echo.
echo ==================================================
echo HUBO UN ERROR
echo ==================================================
echo Mandame una captura de TODO lo que aparece arriba.
echo.
pause
exit /b 1
