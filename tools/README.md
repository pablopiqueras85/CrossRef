# Cómo conectar el catálogo web

Para escribir la configuración del conector hace falta saber **qué selectores CSS**
llevan a cada dato de una ficha de producto. Hay tres formas de averiguarlo, de
menos a más trabajo.

## Opción A — el inspector de fichas (recomendado)

`inspeccionar_ficha.js` se pega en la consola del navegador y devuelve un resumen
compacto: los selectores candidatos y un ejemplo de cada dato. Es lo único que hace
falta compartir; no hay que mandar el HTML entero.

1. Abre **una ficha de producto** (la de una referencia concreta, no un listado).
2. Pulsa `F12` y ve a la pestaña **Console**.
3. Si el navegador avisa de que pegar es peligroso, escribe `allow pasting` y pulsa Intro.
4. Pega el contenido de `inspeccionar_ficha.js` y pulsa Intro.
5. El resumen queda copiado al portapapeles.

El script **sólo lee la página**: no envía nada a ningún sitio ni modifica nada.

Devuelve algo así:

```json
{
  "titulo": "WE-CBF 742792022 | Ferrite Bead",
  "datos_estructurados_jsonld": [{ "sku": "742792022", "brand": "..." }],
  "bloques_de_especificaciones": [
    { "tipo": "tabla", "filas": "table.properties-table tr", "clave": "th", "valor": "td",
      "ejemplos": [["Impedance @ 100 MHz", "600 Ω"], ["Rated Current IR", "500 mA"]] }
  ],
  "posibles_referencias": [{ "selector": "span.value", "texto": "742792022",
                             "pista": "Order Code" }],
  "migas_de_pan": [{ "selector": "nav.breadcrumb > a", "texto": "EMC Components" }],
  "nota_render": "La pagina se genera con JavaScript: ..."
}
```

De ahí sale directamente el YAML del conector:

```yaml
product:
  reference: { selector: "span.value" }
  description: { selector: "h1.product-title" }
  category_path: { selector: "nav.breadcrumb > a", skip: 1 }
  datasheet: { selector: "a.datasheet", attr: href }
  specs:
    table_rows: "table.properties-table tr"
    key_selector: "th"
    value_selector: "td"
```

## Opción B — guardar la página

Si no se puede usar la consola: `Ctrl+S` sobre la ficha → **"Página web, sólo HTML"**.
Se obtiene un `.html` que se puede compartir o abrir con:

```bash
crossref probe config/sources/catalogo_web.yaml file:///ruta/a/ficha.html
```

Ojo: si la ficha se genera con JavaScript, el HTML guardado con esta opción puede no
llevar la tabla de especificaciones. En ese caso, mejor la opción A, o bien
`F12 → Elements → clic derecho en <html> → Copy → Copy outerHTML`, que sí guarda lo
que se ve en pantalla.

## Opción C — buscar la fuente de datos real

Antes de rastrear HTML conviene descartar que exista algo mejor:

- **Sitemap**: abrir `/sitemap.xml` en el navegador. Si lista las fichas, el conector
  las recorre solo (`sitemap:` en el YAML) y no hay que adivinar la paginación.
- **API interna**: `F12 → pestaña Network → filtro Fetch/XHR`, y recargar la ficha. Si
  aparece una petición que devuelve JSON con los datos del producto, esa es la fuente
  buena: se configura con `type: api` en lugar de `type: web`.
- **Exportación**: preguntar internamente por un volcado del PIM/ERP. Es la opción más
  estable de todas y hace innecesario el rastreo.

## Después

```bash
crossref probe config/sources/catalogo_web.yaml <URL de una ficha>   # ajustar
crossref sync config/sources/catalogo_web.yaml --limit 20            # prueba
crossref sync config/sources/catalogo_web.yaml                       # completo
```

`probe` dice qué campos ha entendido y cuáles quedan sin mapear; se itera sobre el
YAML hasta que no queda nada fuera.
