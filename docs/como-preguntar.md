# Cómo preguntar

CrossRef compara **parámetros**, no nombres. Todo lo que sigue sale de esa idea.

## La regla de oro

> Una referencia de fabricante, por sí sola, no dice nada.
> Hay que describir **qué es** y **con qué valores**.

Comprobado con una petición real:

```
$ crossref find "MSTBA 2,5/ 2-G-5,08"
Familia: Generico (sin familia identificada) (0%)
Entendido: (nada)                                     <- no hay nada que comparar

$ crossref find "bornero enchufable base de placa paso 5,08 mm 2 contactos"
Familia: Bornero / regleta (75%)
Entendido: Paso=5.08 mm, Numero de contactos=2, Lado del conector=placa
[EQUIVALENTE] 691305530002  afinidad 83%
```

`MSTBA 2,5/ 2-G-5,08` contiene el paso, los contactos y la sección, pero
codificados en la nomenclatura de Phoenix Contact. La herramienta no la conoce
(ver [Si solo tienes la referencia](#si-solo-tienes-la-referencia-del-fabricante)).

## Cómo se escribe una petición

**1. El tipo de componente, al principio.** La familia se detecta sobre todo por
las primeras palabras: `ferrita 600 ohm…` funciona mejor que `600 ohm de una
ferrita…`.

**2. Los valores con su unidad.** El formato da igual:
`5,08 mm` = `5.08mm`, `100 nF` = `0,1 uF`, `DC-18 GHz` = `0 a 18000 MHz`.

**3. Nombra el parámetro cuando pueda confundirse.** Si hay dos valores de la
misma magnitud, di cuál es cuál:

```
✗ bornero 5,08 mm 2,5 mm 2 contactos          <- ¿cuál es el paso?
✓ bornero paso 5,08 mm, seccion 2,5 mm2, 2 contactos
```

**4. Pide solo lo que de verdad importe.** Cada parámetro que añadas es una
condición más. Si pides algo que el catálogo no publica, el resultado baja a
*requiere revisión* — es correcto, pero no lo provoques sin necesidad.

**5. Lee "lo que he entendido".** Es la comprobación clave: si un valor ha
caído en el campo equivocado, se ve ahí. En la interfaz web esos campos son
editables: se corrige y se vuelve a buscar.

## Qué pedir en cada familia

Los **obligatorios** son los que la familia necesita para poder confirmar un 1:1.
Los **útiles** afinan el resultado; añádelos solo si el cliente los ha exigido.

| Familia | id | Obligatorios | Útiles |
| --- | --- | --- | --- |
| Ferrita supresora / EMI | `ferrite_bead` | impedancia, corriente nominal | frecuencia de medida, impedancia maxima, resistencia dc (dcr), encapsulado |
| Ferrita para cable | `cable_ferrite` | impedancia, diametro interior | frecuencia de medida, inductancia, corriente nominal, resistencia dc (dcr) |
| Choque de modo comun | `common_mode_choke` | impedancia, corriente nominal, numero de lineas | frecuencia de medida, inductancia, tension nominal, tension de aislamiento |
| Filtro de red | `line_filter` | corriente nominal, tension nominal, numero de etapas | corriente de fuga, atenuacion, tipo de conexion, frecuencia de medida |
| Inductancia de potencia SMD | `power_inductor` | inductancia, corriente nominal, resistencia dc (dcr) | tolerancia, corriente de saturacion, tamano / footprint, altura maxima |
| Inductancia de chip / RF | `rf_chip_inductor` | inductancia | tolerancia, encapsulado, corriente nominal, resistencia dc (dcr) |
| Transformador | `transformer` | relacion de transformacion, tension de aislamiento | inductancia del primario, corriente nominal, resistencia dc (dcr), encapsulado |
| Bobina de carga inalambrica | `wireless_power_coil` | inductancia, corriente nominal, dimensiones | tolerancia, resistencia dc (dcr), estandar, frecuencia de medida |
| Condensador ceramico MLCC | `mlcc` | capacidad, tension nominal, tolerancia, dielectrico | encapsulado, cualificacion aec-q, frecuencia de medida, longitud |
| Condensador electrolitico de aluminio | `aluminum_capacitor` | capacidad, tension nominal, formato (d x l), montaje | tolerancia, esr, corriente de rizado, cualificacion aec-q |
| Condensador de pelicula | `film_capacitor` | capacidad, tension nominal, tolerancia | clase de seguridad, paso (pitch), frecuencia de medida, cualificacion aec-q |
| Supercondensador | `supercapacitor` | capacidad, tension nominal, formato | esr, tolerancia, frecuencia de medida, cualificacion aec-q |
| Resistencia de placa metalica (shunt) | `metal_plate_resistor` | valor, tolerancia, potencia | encapsulado, coeficiente de temperatura (tcr), cualificacion aec-q, frecuencia de medida |
| Resistencia de capa gruesa | `thick_film_resistor` | valor, tolerancia, potencia | encapsulado, tension nominal, coeficiente de temperatura (tcr), cualificacion aec-q |
| Bornero / regleta | `terminal_block` | paso (pitch), numero de contactos, tipo de conexion, corriente nominal, tension nominal, lado del conector | orientacion, seccion de cable, frecuencia de medida, cualificacion aec-q |
| Tira de pines / zocalo | `pin_header` | paso (pitch), numero de contactos, numero de filas, genero, orientacion, montaje | corriente nominal, tension nominal, altura maxima, frecuencia de medida |
| Conector FFC/FPC (ZIF/LIF) | `ffc_fpc_connector` | paso (pitch), numero de contactos | contacto, accionamiento, orientacion, corriente nominal |
| Conector circular (M12 / M8) | `circular_connector` | rosca, numero de contactos, codificacion, genero | corriente nominal, tension nominal, grado de proteccion, orientacion |
| Cable plano (FFC / cinta) | `flat_cable` | paso (pitch), numero de conductores, longitud | terminacion, corriente nominal, tension nominal, frecuencia de medida |
| Terminal de potencia / press-fit | `press_fit_terminal` | corriente nominal, rosca, tipo de montaje | resistencia de contacto, longitud, altura maxima, frecuencia de medida |
| Conector de entrada/salida (USB, RJ45, jack) | `io_connector` | interfaz, genero, orientacion, montaje | corriente nominal, tension nominal, frecuencia de medida, cualificacion aec-q |
| Diodo TVS / supresor ESD | `esd_tvs` | tension de trabajo (vrwm), numero de lineas | tension de ruptura (vbr), tension de clampado (vc), corriente de pico (ipp), capacidad de union |
| Varistor | `varistor` | tension de varistor | tension maxima ac, corriente de choque, energia admisible, encapsulado |
| LED | `led` | color | longitud de onda, intensidad luminosa, tension directa, corriente directa |
| Cristal / oscilador | `crystal_oscillator` | frecuencia, tolerancia de frecuencia | estabilidad, capacidad de carga, esr, encapsulado |
| Antena | `antenna` | rango de frecuencia, impedancia | ganancia, tipo de antena, conector 1 (entrada), dimensiones |
| Material de interfaz termica | `thermal_interface` | conductividad termica, espesor | dimensiones, tension de aislamiento, frecuencia de medida, cualificacion aec-q |
| Modulo de alimentacion | `power_module` | tension de entrada, tension de salida, corriente de salida | encapsulado, frecuencia de medida, cualificacion aec-q, longitud |
| Balun | `balun` | rango de frecuencia, relacion de impedancias | encapsulado, frecuencia de medida, cualificacion aec-q, longitud |
| Apantallamiento EMC | `emc_shielding` | tipo, dimensiones | eficacia de apantallamiento, material, espesor, frecuencia de medida |

Para ver el detalle de una familia, con sus reglas y valores admitidos:

```bash
crossref families terminal_block
```

## Si solo tienes la referencia del fabricante

Hoy no funciona sola, y no es un fallo que se arregle con mejor texto: un código
de artículo no contiene los parámetros, solo los codifica en la nomenclatura de
cada fabricante. Tres salidas, de mejor a peor:

**1. La tabla de equivalencias.** Si esa sustitución ya se decidió alguna vez,
está resuelta y es autoridad, no deducción:

```bash
crossref crossrefs equivalencias.csv --source "lista comercial 2024"
crossref find "..." --limit 5        # ahora la referencia ajena se reconoce
```

**2. Decodificar la referencia** y preguntar por valores. Las nomenclaturas son
sistemáticas:

```
MSTBA  2,5 /  2  -G-  5,08     (Phoenix Contact)
  │     │     │   │     └── paso 5,08 mm
  │     │     │   └──────── pines rectos, soldar
  │     │     └──────────── 2 contactos
  │     └────────────────── conductor hasta 2,5 mm²
  └──────────────────────── base macho para PCB
```

**3. Pedir la hoja de datos** al cliente o al proveedor y usar sus valores.

## Los cuatro veredictos

| Veredicto | Qué significa | Qué hacer |
| --- | --- | --- |
| `equivalente` | Todos los obligatorios cumplen la regla estricta | Se puede ofrecer como 1:1 |
| `alternativa` | Cumple, pero algo entró por tolerancia | Ofrecer indicando la desviación |
| `requiere revisión` | Falta un dato: en la petición o en la ficha | Conseguir ese dato |
| `descartado` | Incumple un obligatorio | Se muestra el motivo, con `--rejected` |

**`requiere revisión` no es un fallo de la herramienta.** Suele significar que la
ficha del catálogo web no publica ese parámetro y está solo en la hoja de datos.
Es preferible a dar por buena una equivalencia sobre un dato que nadie ha visto.

## Ejemplos que funcionan

```bash
crossref find "ferrita 600 ohm a 100 MHz, 500 mA, DCR maximo 0,4 ohm"
crossref find "inductancia de potencia 10 uH 3 A DCR maximo 40 mOhm apantallada"
crossref find "condensador ceramico 100 nF 50 V X7R 0805 tolerancia 10%"
crossref find "bornero paso 5,08 mm 2 contactos base de placa"
crossref find "diodo TVS 5 V 1 linea SOT-23"
crossref find "cristal 16 MHz 10 ppm 12 pF"

crossref find "..." --family terminal_block   # si la detección falla
crossref find "..." --rejected                # por qué se descartó cada una
crossref find "..." --strict                  # solo equivalencias 1:1
crossref batch peticiones.csv --out salida.csv    # una RFQ entera
```
