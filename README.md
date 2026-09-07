# CrossRef

Sistema para encontrar la equivalencia de un componente en el catálogo propio a partir
de la información que llega de un cliente, un proveedor o un compañero: la referencia
exacta **1:1** cuando existe, y la alternativa más cercana cuando no, diciendo siempre
qué campos coinciden, cuáles no y por qué.

```
Petición del cliente ──► Identificar familia ──► Normalizar unidades y nombres
                                                          │
                                       Reglas de equivalencia por familia
                                                          │
                          Catálogo indexado ──► Comparación campo a campo
                                                          │
                             equivalente · alternativa · requiere revisión · descartado
```

## Qué resuelve

Un cliente pide *"atenuador 3 dB, 50 ohm, DC-18 GHz, 2 W, SMA macho/hembra"* y hay que
saber si en el catálogo hay algo que valga. La misma pieza puede llegar escrita como
`3dB`, `3,0 dB`, `DC-18000 MHz`, `SMA-M/SMA-F` o `SMA (M) / SMA (F)`. CrossRef lo
normaliza todo a una unidad canónica, aplica las reglas de la familia y devuelve un
veredicto justificado en lugar de una puntuación opaca.

Regla de oro: **con datos incompletos nunca se confirma una equivalencia.** Si falta un
campo obligatorio, el resultado es `requiere revisión`, no un 1:1 optimista.

## Instalación

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

## Puesta en marcha en 3 minutos

```bash
# 1. Cargar el catálogo de ejemplo (51 referencias) en el índice local
crossref sync config/sources/ejemplo_csv.yaml

# 2. Buscar una equivalencia desde la terminal
crossref find "atenuador 3 dB 50 ohm DC-18 GHz 2 W SMA macho/hembra"

# 3. Levantar la interfaz web y la API
crossref serve          # http://127.0.0.1:8000
```

Salida de `find`:

```
Familia: Atenuador fijo (75%)
Entendido: Rango de frecuencia=0 Hz - 18 GHz, Atenuacion=3 dB, Impedancia=50 ohm, ...

[EQUIVALENTE] AT-3SM-2W-18  afinidad 86%
    Atenuador coaxial fijo 3 dB, SMA macho/SMA hembra, DC-18 GHz
    https://catalogo.example/producto/at-3sm-2w-18
    · Equivalencia 1:1: Impedancia, Atenuacion, Rango de frecuencia, Potencia media,
      Conector 1, Conector 2 cumplen la regla estricta.
      = Impedancia            50 ohm          50 ohm          50 ohm coincide con 50 ohm
      = Atenuacion            3 dB            3 dB            3 dB coincide con 3 dB
      = Rango de frecuencia   0 Hz - 18 GHz   0 Hz - 18 GHz   cubre el rango pedido
      = Potencia media        2 W             2 W             cubre el minimo pedido
```

## Conectar vuestro catálogo real

El catálogo es una **dependencia intercambiable**. Hay tres conectores, en este orden
de preferencia:

| Fuente | Cuándo usarla | Plantilla |
| --- | --- | --- |
| **API JSON** | El catálogo web expone API | `config/sources/catalogo_api.yaml.example` |
| **Fichero** | Exportación CSV / XLSX / JSON del ERP o PIM | `config/sources/ejemplo_csv.yaml` |
| **Web** | No hay más remedio que leer las fichas | `config/sources/catalogo_web.yaml.example` |

Para el caso web, el conector se configura con selectores CSS, sin escribir código.
Además aprovecha los datos estructurados JSON-LD (`Product`) si la ficha los publica,
que es lo más estable. Respeta `robots.txt`, limita el ritmo de peticiones y cachea
las descargas.

Para ajustar los selectores contra una ficha real:

```bash
cp config/sources/catalogo_web.yaml.example config/sources/catalogo_web.yaml
# editar selectores...
crossref probe config/sources/catalogo_web.yaml https://vuestro-catalogo/producto/xxx
```

`probe` descarga **una** página y muestra qué ha entendido, a qué familia la asigna,
qué especificaciones ha mapeado y cuáles se quedan fuera. Se itera sobre el YAML hasta
que no queda nada sin mapear. Después:

```bash
crossref sync config/sources/catalogo_web.yaml --limit 20   # prueba
crossref sync config/sources/catalogo_web.yaml --deactivate-missing
```

## Definir las familias y sus reglas

Las familias viven en `config/families/*.yaml`. **Añadir una familia nueva no requiere
tocar el código.** Un atributo declara su tipo, su unidad canónica, si es obligatorio,
con qué regla se compara y qué alias puede tener en el catálogo o en la petición:

```yaml
- id: attenuation
  label: Atenuacion
  type: number
  dimension: decibel
  unit: dB
  required: true
  weight: 3
  aliases: [atenuacion, attenuation, att, valor de atenuacion]
  rule: {kind: numeric_equal, abs_tol: 0.0, alt_abs_tol: 0.5}
```

`abs_tol`/`rel_tol` definen el **1:1**; `alt_abs_tol`/`alt_rel_tol` definen hasta dónde
se acepta una **alternativa**. En el ejemplo: 3 dB exacto es equivalente, 3,3 dB es
alternativa, 6 dB se descarta.

Reglas disponibles:

| Regla | Significado |
| --- | --- |
| `numeric_equal` | Igual tras convertir a la unidad base |
| `at_least` | El catálogo debe igualar o superar lo pedido (potencia, tensión) |
| `at_most` | El catálogo no puede empeorar lo pedido (VSWR, pérdidas, tolerancia) |
| `range_covers` | El rango del catálogo cubre todo el rango pedido |
| `range_within` / `range_overlaps` | Variantes para rangos |
| `enum_equal` / `enum_in` | Valores de lista con sinónimos (conectores, encapsulados) |
| `text_equal` | Texto igual tras normalizar |
| `list_contains` / `list_equal` | Conjuntos de valores |
| `bool_equal` | Sí/no |
| `informative` | Se muestra, pero nunca decide |

Un atributo puede declarar `assume:` con el valor que se da por supuesto cuando la
petición no lo indica (por ejemplo `50 ohm` en RF). Nunca es silencioso: el valor sale
marcado como *asumido* y se avisa para que se confirme con el cliente.

Los atributos comunes a varias familias se definen una vez en
`config/families/_common.yaml` y se reutilizan con `- use: impedance`.

Tras editar los YAML:

```bash
crossref check                     # valida la configuración
curl -X POST localhost:8000/api/v1/families/reload
```

## Familias incluidas de serie

RF/microondas: atenuadores, cargas, divisores/combinadores, acopladores, filtros,
adaptadores, latiguillos y conectores. Pasivos: resistencias, condensadores y bobinas.
Más una familia `generic` de reserva que solo compara lo que coincide por nombre y
nunca confirma un 1:1 por sí sola.

Son un punto de partida: lo normal es ajustarlas a las familias reales del catálogo,
usando el informe de `sync` como guía.

## Interfaz web

`crossref serve` publica en `http://127.0.0.1:8000`:

- **Buscar** — se pega la petición tal cual llega; el sistema muestra *lo que ha
  entendido* en campos editables (por si hay que corregir algo) y devuelve los
  candidatos con la comparación campo a campo, el enlace a la ficha, la fuente del dato
  y su fecha.
- **Lote / RFQ** — una petición por línea, resultado en tabla y descarga en CSV.
- **Catálogo** — referencias indexadas, cobertura de datos por atributo (si un campo
  obligatorio tiene poca cobertura, esa familia no podrá resolverse 1:1) y
  sincronización.

## API

| Método | Ruta | Para qué |
| --- | --- | --- |
| `POST` | `/api/v1/crossref` | Buscar equivalencia |
| `POST` | `/api/v1/parse` | Ver cómo se interpreta una petición, sin buscar |
| `POST` | `/api/v1/crossref/batch` | Lista de peticiones (JSON) |
| `POST` | `/api/v1/crossref/batch/csv` | Lista de peticiones (CSV) → CSV |
| `GET` | `/api/v1/families` · `/api/v1/families/{id}` | Esquema y reglas vigentes |
| `GET` | `/api/v1/catalog/stats` | Estado del índice |
| `GET` | `/api/v1/catalog/coverage/{familia}` | Cobertura de datos por atributo |
| `POST` | `/api/v1/catalog/sync` | Sincronizar desde una fuente |

Documentación interactiva en `/docs`. Ejemplo:

```bash
curl -s localhost:8000/api/v1/crossref -H 'Content-Type: application/json' -d '{
  "text": "atenuador 3 dB 50 ohm DC-18 GHz 2 W SMA macho/hembra",
  "limit": 3, "include_rejected": true
}' | jq '.results[0] | {reference, verdict, score, reasons}'
```

Respuesta (recortada):

```json
{
  "reference": "AT-3SM-2W-18",
  "verdict": "equivalente",
  "score": 0.8613,
  "reasons": ["Equivalencia 1:1: Impedancia, Atenuacion, Rango de frecuencia, ..."]
}
```

Cada resultado incluye además `comparisons[]` con, para cada campo: valor pedido, valor
del catálogo, estado (`coincide`, `aproximado`, `no coincide`, `no informado`), regla
aplicada y motivo en lenguaje llano.

Las operaciones que modifican el catálogo (`sync`, `reload`) se pueden proteger
poniendo la variable de entorno `CROSSREF_ADMIN_TOKEN`; entonces exigen la cabecera
`X-Admin-Token`.

## Los cuatro veredictos

| Veredicto | Cuándo | Qué hacer |
| --- | --- | --- |
| `equivalente` | Todos los campos obligatorios cumplen la regla estricta | Se puede ofrecer como 1:1 |
| `alternativa` | Cumple, pero algún campo entró por tolerancia | Ofrecer indicando la desviación |
| `requiere revisión` | Falta un dato obligatorio en la petición o en la ficha | Pedir el dato que falta |
| `descartado` | Incumple un campo obligatorio | Se muestra el motivo, no se oculta |

## Línea de comandos

```bash
crossref find "TEXTO" [--family X] [--strict] [--rejected] [--json]
crossref batch peticiones.csv --column peticion --out resultados.csv
crossref sync FUENTE.yaml [--limit N] [--deactivate-missing]
crossref probe FUENTE.yaml URL          # ajustar el conector web
crossref families [ID]                  # esquema y reglas vigentes
crossref coverage FAMILIA               # cobertura de datos del catálogo
crossref stats · crossref check · crossref serve
```

## Cómo está construido

```
crossref/
  units.py       Magnitudes y rangos -> unidad canónica (1,5 GHz = 1500 MHz)
  normalize.py   Texto, sinónimos y part numbers comparables
  schema.py      Familias y atributos cargados desde YAML
  rules.py       Motor de reglas: una comparación explicada por campo
  extract.py     De texto libre o formulario a valores normalizados
  matching.py    Veredicto y ordenación de candidatos
  store.py       Índice SQLite con FTS, procedencia y fecha
  ingest.py      Normalización de fichas + informe de calidad
  sources/       Conectores: web, ficheros y API
  service.py     Capa común a API, web y CLI
  api.py         FastAPI + interfaz web
  cli.py         Línea de comandos
config/families/ Familias y reglas (lo que se toca a menudo)
config/sources/  Configuración de las fuentes de catálogo
```

El motor es **determinista**: mismas entradas, mismo resultado, sin modelos
estadísticos de por medio. Todo lo que el sistema no entiende se devuelve en
`unparsed` y en los avisos, en lugar de adivinarse en silencio.

## Calidad de los datos

`crossref sync` no solo carga: informa. Al terminar dice cuántas fichas hay por familia,
cuáles no ha sabido clasificar, qué campos del catálogo no encajan en ningún atributo
(con ejemplos, para añadirlos como `aliases`) y qué fichas no traen todos los campos
obligatorios de su familia. Ese informe es la lista de tareas para ir afinando la
configuración.

## Tests

```bash
pytest -q     # 109 tests
```

Cubren la conversión de unidades y formatos, las reglas de equivalencia y sus
tolerancias, la interpretación de peticiones reales, los veredictos, el índice y sus
conectores, y el contrato de la API.

## Estado y siguientes pasos

Funciona de punta a punta con un catálogo de ejemplo. Para ponerlo en producción:

1. Conectar el catálogo real (API o exportación si es posible; si no, el conector web).
2. Revisar el informe de `sync` y ajustar familias, alias y categorías.
3. Confirmar con negocio las tolerancias de `alternativa` de cada familia.
4. Programar la sincronización periódica (`crossref sync --deactivate-missing`).
5. Decidir si hace falta autenticación y trazabilidad por usuario.

Fuera del alcance actual: sustituciones aproximadas sin tolerancia aprobada, compra
automática y aprendizaje a partir del histórico de decisiones.
