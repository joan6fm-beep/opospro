@echo off
chcp 65001 >nul
title OposPro - Acceso desde el movil
cd /d "%~dp0"

set "PORT=8502"

rem --- Reutiliza el entorno creado por run.bat ---
set "VPY=%LOCALAPPDATA%\OposPro\venv\Scripts\python.exe"
if not exist "%VPY%" (
    echo Ejecuta primero run.bat una vez para instalar la aplicacion.
    pause
    exit /b 1
)

rem --- IP local: la de la red activa con puerta de enlace (Wi-Fi o cable) ---
set "IP="
for /f "usebackq delims=" %%i in (`powershell -NoProfile -Command "Get-NetIPConfiguration | Where-Object { $_.IPv4DefaultGateway -and $_.NetAdapter.Status -eq 'Up' } | ForEach-Object { $_.IPv4Address.IPAddress } | Select-Object -First 1"`) do set "IP=%%i"
if not defined IP (
    echo No se ha podido detectar la IP local. Comprueba que el PC esta conectado a la red.
    pause
    exit /b 1
)

echo.
echo  ============================================================
echo.
echo     IP local de este ordenador:   %IP%
echo.
echo     Enlace para el movil:         http://%IP%:%PORT%
echo.
echo  ============================================================
echo.
echo  - El movil debe estar conectado a la MISMA red (Wi-Fi de casa).
echo  - Escribe el enlace tal cual en el navegador del movil.
echo  - En este ordenador tambien funciona: http://localhost:%PORT%
echo.

rem --- Si run.bat ya tiene la app abierta, no se arranca otra copia ---
netstat -ano | findstr /r /c:":%PORT% .*LISTENING" >nul
if not errorlevel 1 (
    echo  La aplicacion ya esta en marcha. Deja abierta su ventana mientras la uses.
    echo.
    pause
    goto :eof
)

echo  Para cerrar la aplicacion, cierra esta ventana.
echo.
"%VPY%" -m streamlit run app.py --server.port %PORT% --server.address 0.0.0.0 --server.headless true
goto :eof
