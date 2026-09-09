@echo off
REM Descarga el catalogo de we-online.com y reconstruye el indice local.
REM
REM Tarda un par de horas la primera vez: va a media peticion por segundo para
REM no cargar el servidor. Dejalo corriendo y vete a otra cosa. Las siguientes
REM veces reaprovecha lo ya descargado y tarda mucho menos.
setlocal
cd /d "%~dp0.."

if not exist ".venv\Scripts\python.exe" (
    echo Falta el entorno. Ejecuta primero scripts\crossref.cmd
    pause
    exit /b 1
)

echo Descargando el catalogo. Esto tarda; no cierres la ventana.
echo.
".venv\Scripts\crossref.exe" sync config\sources\we_online.yaml --deactivate-missing
echo.
pause
