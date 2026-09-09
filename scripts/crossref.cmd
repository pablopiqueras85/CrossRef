@echo off
REM Arranque de CrossRef en Windows: doble clic y se abre en el navegador.
REM
REM La primera vez crea el entorno e instala las dependencias (un par de
REM minutos). A partir de ahi arranca en segundos.
setlocal
cd /d "%~dp0.."
title CrossRef - no cierres esta ventana

REM 'py' es el lanzador oficial de Windows; 'python' es el respaldo.
where py >nul 2>&1 && (set PY=py -3) || (set PY=python)

if not exist ".venv\Scripts\python.exe" (
    echo.
    echo   Primera vez: preparando el entorno. Esto tarda un par de minutos.
    echo.
    %PY% -m venv .venv || goto :sin_python
    ".venv\Scripts\python.exe" -m pip install --upgrade pip --quiet
    ".venv\Scripts\python.exe" -m pip install -e . --quiet || goto :error_deps
    echo   Entorno listo.
    echo.
)

if not exist "data\catalog.db" goto :sin_catalogo

REM El navegador se abre con retardo: si se abre a la vez que el servidor,
REM llega antes de que este escuchando y muestra un error de conexion.
start "" /b powershell -NoProfile -WindowStyle Hidden -Command ^
    "Start-Sleep -Seconds 5; Start-Process 'http://127.0.0.1:8000'" 2>nul

echo   CrossRef arrancando en http://127.0.0.1:8000
echo   El navegador se abre solo en unos segundos.
echo.
echo   Para cerrar la herramienta: cierra esta ventana, o pulsa Ctrl+C.
echo.
".venv\Scripts\crossref.exe" serve
exit /b 0

:sin_python
echo.
echo   No se encuentra Python.
echo.
echo   Instalalo desde https://www.python.org/downloads/ y marca la casilla
echo   "Add python.exe to PATH" en la primera pantalla del instalador.
echo   Despues cierra esta ventana y vuelve a hacer doble clic aqui.
echo.
pause
exit /b 1

:error_deps
echo.
echo   Ha fallado la instalacion de dependencias. El motivo esta arriba.
echo   Lo mas habitual es no tener salida a internet o que el proxy de la
echo   empresa bloquee pypi.org.
echo.
pause
exit /b 1

:sin_catalogo
echo.
echo   Falta el catalogo indexado: no existe data\catalog.db
echo.
echo   Tienes dos opciones:
echo     a) Si te han pasado el fichero catalog.db, deja una copia en la
echo        carpeta data\ de este proyecto.
echo     b) Si no, ejecuta scripts\actualizar-catalogo.cmd y espera a que
echo        termine (un par de horas la primera vez).
echo.
pause
exit /b 1
