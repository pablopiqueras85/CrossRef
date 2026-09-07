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
# Con el catálogo de ejemplo que trae el repositorio (51 referencias ficticias).
# El flag --families añade las familias de demo a las del catálogo real.
DEMO='--families config/families,examples/families'

crossref $DEMO sync examples/fuente_demo.yaml
crossref $DEMO find "atenuador 3 dB 50 ohm DC-18 GHz 2 W SMA macho/hembra"
crossref serve                                   # http://127.0.0.1:8000
```

Con el catálogo real, `--families` sobra: `config/families` es el valor por defecto.

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

## Conectar el catálogo (we-online.com)

El catálogo es una **dependencia intercambiable**. Hay tres conectores, en este orden
de preferencia:

| Fuente | Cuándo usarla | Plantilla |
| --- | --- | --- |
| **API JSON** | El catálogo web expone API | `config/sources/catalogo_api.yaml.example` |
| **Fichero** | Exportación CSV / XLSX / JSON del ERP o PIM | `examples/fuente_demo.yaml` |
| **Web** | No hay más remedio que leer las fichas | `config/sources/catalogo_web.yaml.example` |

Al ser el catálogo de vuestra propia empresa, lo más probable es que exista una vía
mejor que leer la web: una exportación del PIM/ERP o el mismo feed que alimenta la
web. Merece la pena preguntarlo antes de montar un rastreador, porque el HTML se
rompe con cada rediseño y una exportación no.

Para el caso web, el conector se configura con selectores CSS, sin escribir código.
Además aprovecha los datos estructurados JSON-LD (`Product`) si la ficha los publica,
que es lo más estable. Respeta `robots.txt`, limita el ritmo de peticiones y cachea
las descargas.

Para ajustar los selectores contra una ficha real:

```bash
cp config/sources/catalogo_web.yaml.example config/sources/catalogo_web.yaml
# editar base_url, sitemap y selectores...
crossref probe config/sources/catalogo_web.yaml https://www.we-online.com/en/components/products/<ficha>
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

## Familias incluidas

`config/families/` contiene 26 familias que siguen la taxonomía real del catálogo, más una
familia `generic` de reserva que solo compara lo que coincide por nombre y nunca
confirma un 1:1 por sí sola:

| Fichero | Familias |
| --- | --- |
| `we_magnetics.yaml` | Inductancias de potencia (*Power Magnetics*), inductancias de chip/RF, choques de modo común, ferritas para PCB, transformadores de señal, bobinas de carga inalámbrica |
| `we_emc.yaml` | Filtros de red (*WE-CLFS*), ferritas para cable (*snap*, toroides, nanocristalinos), baluns (*WE-BAL*), apantallamiento EMC |
| `we_capacitors.yaml` | MLCC, electrolíticos de aluminio/polímero/híbridos, película y supresión de interferencias (X/Y), supercondensadores |
| `we_resistors.yaml` | Resistencias de placa metálica (shunt) y de capa gruesa |
| `we_connectors.yaml` | Tiras de pines y zócalos, borneros, conectores de E/S (USB, RJ45, jack) |
| `we_protection_opto.yaml` | ESD/TVS, protección contra sobretensiones (varistores), LEDs, cristales y osciladores, antenas *WE-MCA*, interfaz térmica, módulos de alimentación |

Los nombres de parámetro son los que usa el propio catálogo en sus filtros, así que
las columnas se mapean solas: `Z @ 100 MHz`, `I_R`, `R_DC max`, `Size`, `Mount` y
`AEC-Q Product` se reconocen sin configurar nada.

**AEC-Q**: si la petición exige cualificación de automoción, una referencia sin
cualificar **no** es equivalente. Si no la exige, que la referencia la tenga no penaliza.

Cada familia lleva los parámetros que de verdad deciden una sustitución. Por ejemplo,
en una inductancia de potencia el DCR se compara como **máximo** (más resistencia
empeora), la corriente nominal como **mínimo** y el paso de un conector con **igualdad
exacta** (2,50 mm y 2,54 mm no son intercambiables por mucho que se parezcan).

Están dimensionadas a partir de los parámetros habituales de cada tipo de componente,
no de una lectura de vuestras fichas. En cuanto se sincronice el catálogo real, el
informe de `sync` dirá qué campos publican de verdad las fichas y qué hay que ajustar.

`examples/families/` contiene familias de demostración (RF coaxial y pasivos
genéricos) que solo usa el catálogo de ejemplo y los tests. No se cargan en producción.

## Rangos de serie

El catálogo publica en sus listados el **rango de cada serie** (`WE-CBF: Z @ 100 MHz
10 a 2700 Ω, I_R 450 a 12000 mA`), no el valor de cada referencia. CrossRef lo detecta
y lo trata con honestidad: que el valor pedido caiga dentro del rango de una serie
**nunca** se da por equivalencia 1:1, porque no demuestra que exista una referencia
con ese valor exacto.

```
$ crossref find "ferrita 500 ohm a 100 MHz 8,7 A"

[ALTERNATIVA] WE-SUKW  afinidad 74%
    ~ Impedancia   500 ohm   416 ohm - 580 ohm   cae dentro del rango publicado,
      pero el catálogo no detalla el valor de cada referencia: hay que confirmar
      la referencia concreta
```

Entre varias series que contengan el valor, gana la que lo ciñe más: WE-SUKW
(416–580 Ω) por delante de WE-CBF (10–2700 Ω).

Esto permite usar la herramienta **antes** de tener el catálogo sincronizado a nivel
de referencia: `config/sources/series_ferritas_pcb.yaml` carga un índice de series de
ejemplo. Cuando esté el catálogo real, esa fuente sobra.

## Equivalencias ya declaradas

Lo normal en un fabricante es que ya existan listas de "esta referencia de la
competencia se sustituye por esta nuestra". Esas decisiones valen más que cualquier
comparación de parámetros, así que se cargan aparte y se consultan primero:

```bash
crossref crossrefs equivalencias_2024.csv --source "lista comercial 2024"
```

El CSV necesita una columna con la referencia ajena y otra con la propia; los nombres
de columna se reconocen solos (`Referencia competencia`, `Competitor PN`, `MPN`,
`Referencia propia`, `Our reference`…), y admite además fabricante y una nota.

Cuando la petición trae esa referencia, el resultado la cita con su procedencia:

> *Equivalencia ya declarada para 'XYZ-3DB-SMA' de OtroFabricante (según lista
> comercial 2024): validado en 2024.*

Así queda claro que la equivalencia viene de una decisión previa y no de una
comparación automática, y se puede auditar quién la aprobó y cuándo.

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
crossref crossrefs TABLA.csv [--source NOMBRE]   # equivalencias ya declaradas
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
  crossrefs.py   Tabla de equivalencias declaradas de la competencia
  sources/       Conectores: web, ficheros y API
  service.py     Capa común a API, web y CLI
  api.py         FastAPI + interfaz web
  cli.py         Línea de comandos
config/families/ Familias y reglas del catálogo propio (lo que se toca a menudo)
config/sources/  Configuración de las fuentes de catálogo
examples/        Catálogo y familias de demostración (borrables)
```

`--families` admite varios directorios separados por comas, por si conviene separar
las familias por línea de producto o por unidad de negocio.

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
pytest -q     # 150 tests
```

Cubren la conversión de unidades y formatos, las reglas de equivalencia y sus
tolerancias, la interpretación de peticiones reales, los veredictos, el índice y sus
conectores, la tabla de equivalencias, el contrato de la API y la detección e
interpretación de las 26 familias del catálogo y el tratamiento de los rangos de serie.

## Estado y siguientes pasos

Funciona de punta a punta con un catálogo de ejemplo. Para ponerlo en producción:

1. Conectar el catálogo real (API o exportación si es posible; si no, el conector web,
   ajustando los selectores con `crossref probe`).
2. Revisar el informe de `sync` y ajustar familias, alias y categorías a lo que
   publiquen de verdad las fichas.
3. Cargar las listas históricas de equivalencias con `crossref crossrefs`.
4. Confirmar con negocio las tolerancias de `alternativa` de cada familia.
5. Programar la sincronización periódica (`crossref sync --deactivate-missing`).
6. Decidir si hace falta autenticación y trazabilidad por usuario.

Fuera del alcance actual: sustituciones aproximadas sin tolerancia aprobada, compra
automática y aprendizaje a partir del histórico de decisiones.
