# Instalar CrossRef en tu PC

La herramienta corre entera en tu ordenador: el índice del catálogo es un
fichero local y las búsquedas no salen a internet. Solo hace falta red para
actualizar el catálogo.

## Windows

**1. Instalar Python** (una vez). Descárgalo de
[python.org/downloads](https://www.python.org/downloads/) y **marca la casilla
"Add python.exe to PATH"** en la primera pantalla del instalador. Sin esa
casilla no funciona nada de lo demás.

**2. Descargar el proyecto.** En GitHub, botón verde `Code` → `Download ZIP`, y
lo descomprimes donde quieras tenerlo (por ejemplo `C:\CrossRef`). No lo dejes
dentro de una carpeta sincronizada con OneDrive: la base de datos cambia
constantemente y la sincronización se pelea con ella.

**3. Construir el índice** (una vez, y luego cuando quieras refrescarlo).
Doble clic en:

```
scripts\actualizar-catalogo.cmd
```

Va a media petición por segundo para no cargar el servidor, así que la primera
vez tarda **un par de horas**. Déjalo por la noche. Al terminar imprime cuántas
referencias ha indexado y qué le ha chirriado.

**4. Abrir la herramienta.** Doble clic en:

```
scripts\crossref.cmd
```

La primera vez prepara el entorno (un par de minutos). Después abre el
navegador en `http://127.0.0.1:8000` y ya está. Para cerrarla, cierra la
ventana negra.

**Acceso directo en el escritorio:** botón derecho sobre `crossref.cmd` →
`Enviar a` → `Escritorio (crear acceso directo)`. Si quieres que no aparezca la
ventana negra, en las propiedades del acceso directo pon `Ejecutar: Minimizada`.

## macOS y Linux

```bash
git clone https://github.com/pablopiqueras85/CrossRef.git
cd CrossRef
./scripts/crossref.sh --sync     # construir el índice (un par de horas)
./scripts/crossref.sh            # abrir la herramienta
```

## Si alguien te pasa el índice ya hecho

El índice es un único fichero, `data/catalog.db`. Copiarlo ahí dentro te ahorra
las dos horas de descarga. Comprueba que ha entrado bien:

```
.venv\Scripts\crossref stats
```

Debe decir unas 20.000 referencias activas. Si dice 0, el fichero no está donde
toca.

## Usarla desde la línea de comandos

La ventana negra que abre `crossref.cmd` sirve la interfaz web. Para lanzar
consultas sueltas sin abrir el navegador, abre un `cmd` en la carpeta del
proyecto:

```
.venv\Scripts\crossref find "bornero paso 5,08 mm 2 contactos base de placa"
.venv\Scripts\crossref batch peticiones.csv --out resultados.csv
.venv\Scripts\crossref stats
```

Cómo redactar la consulta está en [como-preguntar.md](como-preguntar.md).

## Compartirla con el equipo

`crossref serve` escucha solo en tu máquina. Para que la abran otros desde su
navegador, arráncala con:

```
.venv\Scripts\crossref serve --host 0.0.0.0
```

y diles que entren a `http://TU-IP:8000`. Antes de hacerlo, dos avisos: no lleva
ningún control de acceso, y en una red corporativa esto suele necesitar el visto
bueno de IT. Para uso compartido de verdad, lo razonable es desplegarla en un
servidor interno, no en tu portátil.

## Problemas frecuentes

**"No se encuentra Python"** — no marcaste "Add python.exe to PATH". Vuelve a
pasar el instalador y elige `Modify`, o reinstala marcando la casilla.

**El antivirus corporativo bloquea el script** — es un `.cmd` que arranca
Python. Si no puedes desbloquearlo, abre un `cmd` en la carpeta y ejecuta a mano
las tres líneas que hay dentro del fichero.

**La descarga del catálogo falla a mitad** — se puede repetir sin perder nada:
lo ya descargado queda en caché y no se vuelve a pedir.

**"No hay catalogo indexado todavia"** — falta el paso 3, o el fichero
`data/catalog.db` no está donde debe.
