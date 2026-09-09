@echo off
REM Arranque de CrossRef en Windows: doble clic y se abre en el navegador.
REM
REM La primera vez crea el entorno e instala las dependencias (tarda un par de
REM minutos). A partir de ahi arranca en segundos.
setlocal
cd /d "%~dp0.."

where py >nul 2>&1 && (set PY=py -3) || (set PY=python)

if not exist ".venv\Scripts\python.exe" (
    echo Preparando el entorno por primera vez...
    %PY% -m venv .venv || goto :sin_python
    ".venv\Scripts\python.exe" -m pip install --upgrade pip --quiet
    ".venv\Scripts\python.exe" -m pip install -e . --quiet || goto :error
)

if not exist "data\catalog.db" (
    echo.
    echo   No hay catalogo indexado todavia.
    echo   Ejecuta scripts\actualizar-catalogo.cmd y vuelve a abrir esto.
    echo.
    pause
    exit /b 1
)

echo Abriendo CrossRef en http://127.0.0.1:8000 ...
start "" http://127.0.0.1:8000
".venv\Scripts\crossref.exe" serve
exit /b 0

:sin_python
echo.
echo   No se encuentra Python. Instalalo desde https://www.python.org/downloads/
echo   marcando la casilla "Add python.exe to PATH".
echo.
pause
exit /b 1

:error
echo.
echo   Ha fallado la instalacion de dependencias. Revisa el mensaje de arriba.
echo.
pause
exit /b 1
