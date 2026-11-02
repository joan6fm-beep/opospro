@echo off
chcp 65001 >nul
title OposPro - Auxiliar Administrativo
cd /d "%~dp0"

rem --- Localizar Python (lanzador py o python) ---
set "PY="
where py >nul 2>nul && set "PY=py"
if not defined PY (
    where python >nul 2>nul && set "PY=python"
)
if not defined PY (
    echo No se ha encontrado Python. Instalalo desde https://www.python.org/downloads/ y marca "Add to PATH".
    pause
    exit /b 1
)

rem --- Entorno virtual propio de la app, fuera de OneDrive para no sincronizarlo ---
set "VENV=%LOCALAPPDATA%\OposPro\venv"
set "VPY=%VENV%\Scripts\python.exe"
if not exist "%VPY%" (
    echo Creando entorno de Python por primera vez...
    %PY% -m venv "%VENV%" || goto :error
)

rem --- Instalar dependencias solo cuando requirements.txt cambia ---
set "STAMP=%VENV%\requirements.stamp"
fc /b requirements.txt "%STAMP%" >nul 2>nul
if errorlevel 1 (
    echo Instalando dependencias, puede tardar unos minutos la primera vez...
    "%VPY%" -m pip install --upgrade pip >nul
    "%VPY%" -m pip install -r requirements.txt || goto :error
    copy /y requirements.txt "%STAMP%" >nul
)

echo.
echo  Abriendo OposPro en el navegador: http://localhost:8502
echo  Para cerrar la aplicacion, cierra esta ventana.
echo.
rem headless evita la pregunta de email del primer arranque; el navegador se abre aparte
start "" /b cmd /c "timeout /t 5 /nobreak >nul & start http://localhost:8502"
"%VPY%" -m streamlit run app.py --server.port 8502 --server.address 0.0.0.0 --server.headless true
goto :eof

:error
echo.
echo Se ha producido un error. Revisa los mensajes anteriores.
pause
exit /b 1
