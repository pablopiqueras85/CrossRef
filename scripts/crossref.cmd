@echo off
REM Arranque de CrossRef en Windows: doble clic y se abre en el navegador.
REM
REM La primera vez crea el entorno e instala las dependencias (un par de
REM minutos). A partir de ahi arranca en segundos.
setlocal
cd /d "%~dp0.."
title CrossRef - no cierres esta ventana

REM Este script tiene que vivir dentro de la carpeta scripts\ del proyecto:
REM se orienta por su propia ubicacion. Suelto en Descargas se pone a buscar
REM el proyecto en la carpeta de usuario y falla con un error de pip que no
REM dice nada de esto.
if not exist "pyproject.toml" goto :fuera_de_sitio

REM Que interprete usar, en orden:
REM   1. el que digas en python.txt (una linea con la ruta completa)
REM   2. el lanzador oficial de Windows, 'py'
REM   3. 'python' del PATH
REM El fichero existe porque hay maquinas donde Python viene dentro de otro
REM programa (KiCad, Altium, Anaconda) y no esta en el PATH.
set "PY="
if exist "python.txt" (
    for /f "usebackq delims=" %%p in ("python.txt") do if not defined PY set "PY=%%p"
)
if not defined PY (
    where py >nul 2>&1 && set "PY=py -3"
)
if not defined PY (
    where python >nul 2>&1 && set "PY=python"
)
if not defined PY goto :sin_python

REM Se mira crossref.exe y no python.exe: si la instalacion se corto a
REM medias, el entorno existe pero esta vacio, y dandolo por bueno el arranque
REM fallaba luego sin explicar por que.
if not exist ".venv\Scripts\crossref.exe" (
    REM Se comprueba antes de crear nada: un Python viejo o sin el modulo venv
    REM falla mas adelante con un error que no dice nada.
    %PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" 2>nul || goto :version_vieja
    %PY% -c "import venv" 2>nul || goto :sin_venv

    echo.
    echo   Primera vez: preparando el entorno.
    for /f "delims=" %%v in ('%PY% -c "import sys; print(sys.version.split()[0], sys.executable)"') do echo   Usando Python %%v

    if not exist ".venv\Scripts\python.exe" (
        %PY% -m venv .venv || goto :error_venv
    )

    REM Con una carpeta wheelhouse al lado, la instalacion no toca internet.
    REM Es la salida cuando el proxy de la empresa bloquea pypi.org.
    if exist "wheelhouse\*.whl" (
        echo   Instalando desde wheelhouse, sin conexion.
        echo.
        ".venv\Scripts\python.exe" -m pip install --no-index --find-links wheelhouse -e . --quiet || goto :error_deps
    ) else (
        echo   Descargando dependencias. Esto tarda un par de minutos.
        echo.
        REM --retries 1: si no hay salida a pypi, que se sepa en 20 segundos y
        REM no despues de cuatro reintentos de 15 segundos cada uno.
        ".venv\Scripts\python.exe" -m pip install -e . --quiet --retries 1 --timeout 20 || goto :error_deps
    )
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

:fuera_de_sitio
echo.
echo   Este lanzador no esta en su sitio.
echo.
echo   Tiene que estar dentro de la carpeta scripts\ del proyecto, porque se
echo   orienta por donde esta el. Ahora mismo esta buscando el proyecto aqui:
echo.
echo       %CD%
echo.
echo   y ahi no hay ningun pyproject.toml. Mueve este fichero a:
echo.
echo       ...\CrossRef\scripts\crossref.cmd
echo.
echo   y haz doble clic sobre el desde ahi.
echo.
pause
exit /b 1

:sin_python
echo.
echo   No se encuentra Python en este equipo.
echo.
echo   Si sabes que esta instalado pero no aparece (pasa cuando viene dentro
echo   de otro programa), crea un fichero llamado python.txt en la carpeta
echo   del proyecto con la ruta completa del ejecutable en una sola linea:
echo.
echo       C:\Ruta\A\python.exe
echo.
echo   Si no lo esta, instalalo desde https://www.python.org/downloads/
echo   marcando "Add python.exe to PATH".
echo.
pause
exit /b 1

:version_vieja
echo.
echo   El Python que hay en este equipo es demasiado antiguo. Hace falta 3.10
echo   o superior. Esta es la version encontrada:
echo.
for /f "delims=" %%v in ('%PY% -c "import sys; print(sys.version.split()[0], sys.executable)"') do echo       %%v
echo.
echo   Si hay otra instalacion mas nueva en la maquina, apuntala en un fichero
echo   python.txt en la carpeta del proyecto, con la ruta completa del
echo   ejecutable en una sola linea.
echo.
pause
exit /b 1

:sin_venv
echo.
echo   Este Python no trae el modulo 'venv', asi que no puede crear el entorno
echo   aislado. Suele pasar con los Python recortados que vienen dentro de
echo   otros programas.
echo.
echo   Busca otra instalacion en la maquina y apuntala en python.txt.
echo.
pause
exit /b 1

:error_venv
echo.
echo   No se ha podido crear el entorno. El motivo esta arriba.
echo.
pause
exit /b 1

:error_deps
echo.
echo   Ha fallado la instalacion de dependencias. El motivo esta arriba.
echo.
echo   Si pone "Connection to pypi.org timed out", el proxy de la empresa
echo   bloquea la descarga de librerias. Solucion sin internet:
echo.
echo     1. Consigue el paquete de librerias de tu version de Python.
echo     2. Descomprimelo aqui, de forma que quede C:\CrossRef\wheelhouse\
echo     3. Borra la carpeta .venv y vuelve a hacer doble clic aqui.
echo.
echo   El lanzador detecta esa carpeta y se instala sin tocar internet.
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
