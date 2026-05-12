@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (
    py -3 install.py %*
    goto :done
)

where python >nul 2>nul
if %errorlevel%==0 (
    python install.py %*
    goto :done
)

echo [Tecno--J.A.R.V.I.S installer] Python no esta instalado o no esta en PATH.
echo Instala Python 3.10+ desde https://www.python.org/downloads/ y marca "Add Python to PATH".
pause
exit /b 1

:done
if errorlevel 1 (
    echo.
    echo [Tecno--J.A.R.V.I.S installer] La instalacion fallo. Revisa el error de arriba.
    pause
    exit /b 1
)
echo.
echo [Tecno--J.A.R.V.I.S installer] Listo.
pause
