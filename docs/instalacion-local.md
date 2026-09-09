# Instalar CrossRef en tu PC

Paso a paso, sin dar nada por sabido. Al final tendrás un icono en el
escritorio que abre la herramienta en el navegador.

La herramienta corre entera en tu ordenador: el índice del catálogo es un
fichero local y las búsquedas no salen a internet. Solo hace falta red para
instalarla y para actualizar el catálogo.

---

## Paso 1 — Instalar Python

Solo la primera vez. Necesitas **Python 3.10 o superior**.

1. Entra en <https://www.python.org/downloads/> y pulsa el botón amarillo
   *Download Python*.
2. Ejecuta el instalador que se descarga.
3. **En la primera pantalla, marca la casilla `Add python.exe to PATH`**,
   abajo del todo, antes de pulsar nada más. Es pequeña y es fácil pasarla por
   alto; sin ella, el resto no funciona.
4. Pulsa *Install Now* y espera.

**Comprobar que ha ido bien:** pulsa `Windows + R`, escribe `cmd`, Enter, y en
la ventana negra escribe:

```
python --version
```

Debe responder algo como `Python 3.13.1`. Si dice *"no se reconoce como un
comando interno o externo"*, la casilla del PATH no quedó marcada: vuelve a
pasar el instalador, elige `Modify` y márcala.

---

## Paso 2 — Descargar el proyecto

**No uses el botón `Code` → `Download ZIP` de la portada del repositorio.** Ese
baja la rama por defecto, que de momento solo tiene el README. Usa este enlace:

```
https://github.com/pablopiqueras85/CrossRef/archive/refs/heads/claude/component-cross-reference-system-apv4yn.zip
```

Se descarga un fichero llamado
`CrossRef-claude-component-cross-reference-system-apv4yn.zip`.

**Al descomprimirlo, dentro hay una carpeta con ese mismo nombre largo**, no una
llamada `CrossRef`. Sácala del ZIP, **renómbrala a `CrossRef`** y déjala en la
raíz del disco. El resultado debe ser:

```
C:\CrossRef\
    README.md
    config\
    crossref\
    data\
    docs\
    examples\
    pyproject.toml
    scripts\
    tests\
    tools\
```

**Dos avisos:**

- Si dentro solo ves `README.md`, te has bajado la rama equivocada. Vuelve al
  enlace de arriba.
- **No lo dejes dentro de OneDrive, Dropbox ni ninguna carpeta sincronizada.**
  El índice es un fichero de 100 MB que cambia al usarlo, y la sincronización
  se pelea con él. `C:\CrossRef` o `C:\Users\TU_USUARIO\CrossRef` van bien.

**Si Windows bloquea los scripts:** al venir de un ZIP descargado, Windows
puede marcarlos como "de origen externo". Si al hacer doble clic en el paso 4
no pasa nada o sale un aviso de seguridad, haz clic derecho sobre el fichero →
`Propiedades` → abajo del todo marca `Desbloquear` → `Aceptar`.

---

## Paso 3 — Poner el índice del catálogo

El índice es un único fichero: `catalog.db`. Son 20.290 referencias de
we-online.com ya descargadas y normalizadas.

Si te han pasado el ZIP con el índice:

1. Descomprímelo. Sale un fichero `catalog.db` de unos 100 MB.
2. Cópialo dentro de la carpeta `data` del proyecto. Debe quedar exactamente
   aquí:

```
C:\CrossRef\data\catalog.db
```

La carpeta `data` ya existe y tiene algún fichero dentro; no la borres, solo
añade `catalog.db`.

**Si no te lo han pasado**, doble clic en `scripts\actualizar-catalogo.cmd` y
espera. Descarga el catálogo entero a media petición por segundo para no
cargar el servidor, así que **la primera vez tarda un par de horas**. Déjalo
por la noche. Al terminar te dice cuántas referencias ha indexado.

---

## Paso 4 — Arrancar

Doble clic en:

```
C:\CrossRef\scripts\crossref.cmd
```

**Qué vas a ver:**

1. Se abre una ventana negra. **La primera vez** dice `Primera vez: preparando
   el entorno` y se queda un par de minutos instalando. Es normal, no la
   cierres.
2. Después aparece `CrossRef arrancando en http://127.0.0.1:8000`.
3. A los cinco segundos se abre el navegador solo con la herramienta.

**La ventana negra tiene que quedarse abierta mientras uses la herramienta**:
es el servidor. Si la cierras, la página deja de responder.

**Para cerrar:** cierra la ventana negra, o pulsa `Ctrl+C` dentro de ella.

**Arranques siguientes:** ya no instala nada, tarda unos segundos.

---

## Paso 5 — El acceso directo en el escritorio

1. Clic derecho sobre `C:\CrossRef\scripts\crossref.cmd`.
2. `Mostrar más opciones` → `Enviar a` → `Escritorio (crear acceso directo)`.
3. En el escritorio, renombra el acceso directo a `CrossRef`.

Opcional, para que la ventana negra no moleste: clic derecho sobre el acceso
directo → `Propiedades` → `Ejecutar: Minimizada`.

---

## Cómo se usa la interfaz

La pantalla tiene tres columnas y el flujo son **dos clics**, no uno:

**1. Petición del cliente.** Pega el texto tal y como te llega. Puedes forzar
la familia si la detección falla, y rellenar la referencia y el fabricante que
te han dado (por ahora son informativos).

**2. Lo que he entendido.** Al pulsar `Analizar petición` aparece esta columna
con cada valor en su campo. **Míralo siempre**: si algo cayó en el campo
equivocado, se ve aquí, y los campos son editables. Corriges y sigues.

**3. Resultados.** Al pulsar `Buscar equivalencia` sale la lista, cada
referencia con su veredicto y una tabla campo a campo: qué pediste, qué
publica el catálogo, si coincide y por qué. Cada resultado enlaza a su ficha
en we-online.com.

Las otras dos pestañas de arriba: **Lote / RFQ** procesa una lista entera de
peticiones de golpe, y **Catálogo** enseña qué hay indexado y con cuánto
detalle por familia.

Cómo redactar la petición para que acierte: [como-preguntar.md](como-preguntar.md).

---

## Usarla desde la línea de comandos

La ventana negra sirve la interfaz web. Para consultas sueltas sin navegador,
abre otro `cmd`, ve a la carpeta y usa:

```
cd C:\CrossRef
.venv\Scripts\crossref find "bornero paso 5,08 mm 2 contactos base de placa"
.venv\Scripts\crossref find "LED verde 0805" --rejected
.venv\Scripts\crossref batch peticiones.csv --out resultados.csv
.venv\Scripts\crossref stats
```

---

## Compartirla con el equipo

Por defecto solo escucha en tu máquina. Para que entren otros desde su
navegador:

```
.venv\Scripts\crossref serve --host 0.0.0.0
```

y que abran `http://TU-IP:8000`. Antes, dos avisos: **no lleva ningún control
de acceso**, y en una red corporativa esto suele necesitar el visto bueno de
IT. Para uso compartido de verdad lo razonable es desplegarla en un servidor
interno, no en tu portátil.

---

## Si algo falla

| Lo que ves | Qué pasa |
| --- | --- |
| `No se encuentra Python` | La casilla `Add python.exe to PATH` no quedó marcada. Reinstala Python marcándola. |
| `Falta el catalogo indexado` | `catalog.db` no está en `C:\CrossRef\data\`. Repasa el paso 3. |
| `Ha fallado la instalacion de dependencias` | Sin salida a internet, o el proxy de la empresa bloquea `pypi.org`. Habla con IT. |
| La ventana negra se abre y se cierra de golpe | Windows está bloqueando el script. Clic derecho → `Propiedades` → `Desbloquear`. |
| El navegador dice "no se puede conectar" | Llegaste antes que el servidor. Espera cinco segundos y recarga. |
| `crossref stats` dice 0 referencias | El fichero `catalog.db` no está donde toca o se copió a medias. |
| El antivirus bloquea el `.cmd` | Es un script que arranca Python. Si no puedes desbloquearlo, abre un `cmd` en la carpeta y ejecuta a mano las líneas de dentro del fichero. |
| La descarga del catálogo se corta a mitad | Vuelve a lanzarla: lo ya descargado queda en caché y no se vuelve a pedir. |

---

## Actualizar más adelante

**El catálogo:** doble clic en `scripts\actualizar-catalogo.cmd`. Reaprovecha
lo descargado, así que tarda mucho menos que la primera vez.

**La herramienta:** bájate el ZIP otra vez y sustituye todo **menos la carpeta
`data`**, que es donde vive tu índice. Luego arranca normal; si hay
dependencias nuevas, las instala solo.
