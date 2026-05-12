@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [Tecno--J.A.R.V.I.S runner] No se encontro .venv.
    echo Ejecuta install.bat primero.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" main.py
if errorlevel 1 (
    echo.
    echo [Tecno--J.A.R.V.I.S runner] La aplicacion se cerro con error.
    pause
    exit /b 1
)
