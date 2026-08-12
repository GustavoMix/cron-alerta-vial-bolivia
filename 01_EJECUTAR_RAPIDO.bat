@echo off
setlocal EnableExtensions
title SCRAPER TRANSITO BOLIVIA - RAPIDO
color 0A
cd /d "%~dp0"

echo ==================================================
echo   TRANSITO BOLIVIA V3.2 PREMIUM - MODO RAPIDO
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
    echo No encuentro Python.
    echo Ejecuta primero 00_PRIMERA_INSTALACION.bat
    pause
    exit /b 1
)

if not exist ".setup_ok" (
    echo Parece que falta la primera instalacion.
    echo Ejecuta primero:
    echo     00_PRIMERA_INSTALACION.bat
    pause
    exit /b 1
)

echo Facebook: 3 paginas en paralelo
echo Webs:     5 en paralelo
echo Chromium: compartido
echo.
echo Ejecutando...
echo.

%PYEXE% main.py
if errorlevel 1 goto :ERROR

echo.
echo ==================================================
echo TERMINADO
echo ==================================================
echo.
echo Resultado principal:
echo     data\transito_bolivia.json
echo.
echo Diagnostico:
echo     data\estado_fuentes.json
echo.
pause
exit /b 0

:ERROR
echo.
echo Hubo un error. Mandame una captura de lo que aparece arriba.
pause
exit /b 1
