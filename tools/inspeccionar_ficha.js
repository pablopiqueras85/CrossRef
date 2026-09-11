/*
 * CrossRef - inspector de fichas de catalogo
 * ==========================================
 *
 * Se pega en la consola del navegador, estando en una FICHA DE PRODUCTO, y
 * devuelve un resumen compacto con los selectores CSS candidatos y un ejemplo
 * de cada dato. Con ese resumen se puede escribir la configuracion del conector
 * sin necesidad de mandar el HTML entero.
 *
 * COMO USARLO
 *   1. Abre una ficha de producto en el navegador.
 *   2. F12 (o Ctrl+Mayus+I) -> pestana "Console".
 *   3. Si el navegador pide permiso para pegar, escribe: allow pasting
 *   4. Pega todo este fichero y pulsa Intro.
 *   5. El resultado queda copiado al portapapeles. Pegalo donde toque.
 *
 * NO envia nada a ningun sitio: solo lee la pagina y escribe en la consola.
 */
(() => {
  const LIMITE_TEXTO = 120;
  const MAX_EJEMPLOS = 6;
  const MAX_CANDIDATOS = 6;

  const limpiar = (t) => (t || "").replace(/\s+/g, " ").trim().slice(0, LIMITE_TEXTO);

  /** Selector CSS corto y estable para un elemento. */
  const selector = (el) => {
    if (!el || el === document.documentElement) return "html";
    if (el.id && !/\d{4,}/.test(el.id)) return `#${CSS.escape(el.id)}`;
    const clases = [...el.classList]
      .filter((c) => c.length < 30 && !/\d{4,}|^css-|^sc-|^jsx-/.test(c))
      .slice(0, 2)
      .map((c) => `.${CSS.escape(c)}`)
      .join("");
    const base = el.tagName.toLowerCase() + clases;
    const padre = el.parentElement;
    if (!padre || padre === document.body) return base;
    if (document.querySelectorAll(base).length === 1) return base;
    return `${selector(padre)} > ${base}`;
  };

  /** Tablas de especificaciones: clave/valor por fila. */
  const tablas = [...document.querySelectorAll("table")]
    .map((tabla) => {
      const filas = [...tabla.querySelectorAll("tr")];
      const pares = filas
        .map((fila) => {
          const th = fila.querySelector("th");
          const celdas = [...fila.querySelectorAll("td")];
          if (th && celdas.length) return [limpiar(th.textContent), limpiar(celdas.at(-1).textContent)];
          if (celdas.length >= 2) return [limpiar(celdas[0].textContent), limpiar(celdas[1].textContent)];
          return null;
        })
        .filter((p) => p && p[0] && p[1]);
      return pares.length
        ? {
            tipo: "tabla",
            filas: selector(tabla) + " tr",
            clave: tabla.querySelector("th") ? "th" : "td",
            valor: "td",
            total: pares.length,
            ejemplos: pares.slice(0, MAX_EJEMPLOS),
          }
        : null;
    })
    .filter(Boolean);

  /** Listas de definicion <dl><dt>clave</dt><dd>valor</dd></dl> */
  const listas = [...document.querySelectorAll("dl")]
    .map((dl) => {
      const dt = [...dl.querySelectorAll("dt")];
      const dd = [...dl.querySelectorAll("dd")];
      const pares = dt
        .map((t, i) => [limpiar(t.textContent), limpiar(dd[i]?.textContent)])
        .filter((p) => p[0] && p[1]);
      return pares.length
        ? { tipo: "lista de definicion", selector: selector(dl), total: pares.length,
            ejemplos: pares.slice(0, MAX_EJEMPLOS) }
        : null;
    })
    .filter(Boolean);

  /** Bloques repetidos con dos hijos (etiqueta + valor), tipicos de fichas modernas. */
  const repetidos = (() => {
    const grupos = new Map();
    for (const el of document.querySelectorAll("li, div, p")) {
      const hijos = [...el.children].filter((c) => limpiar(c.textContent));
      if (hijos.length !== 2) continue;
      const clave = limpiar(hijos[0].textContent);
      const valor = limpiar(hijos[1].textContent);
      if (!clave || !valor || clave.length > 60 || clave === valor) continue;
      const firma = `${el.tagName.toLowerCase()}.${[...el.classList].slice(0, 2).join(".")}`;
      if (!grupos.has(firma)) grupos.set(firma, { el, pares: [] });
      grupos.get(firma).pares.push([clave, valor]);
    }
    return [...grupos.values()]
      .filter((g) => g.pares.length >= 3)
      .sort((a, b) => b.pares.length - a.pares.length)
      .slice(0, 3)
      .map((g) => ({
        tipo: "pares repetidos",
        selector: selector(g.el),
        clave: g.el.children[0].tagName.toLowerCase() +
               [...g.el.children[0].classList].slice(0, 1).map((c) => `.${c}`).join(""),
        valor: g.el.children[1].tagName.toLowerCase() +
               [...g.el.children[1].classList].slice(0, 1).map((c) => `.${c}`).join(""),
        total: g.pares.length,
        ejemplos: g.pares.slice(0, MAX_EJEMPLOS),
      }));
  })();

  /** Datos estructurados: lo mas estable si existen. */
  const jsonLd = [...document.querySelectorAll('script[type="application/ld+json"]')]
    .map((s) => { try { return JSON.parse(s.textContent); } catch { return null; } })
    .filter(Boolean);
  const productosLd = [];
  const recorrer = (n) => {
    if (Array.isArray(n)) return n.forEach(recorrer);
    if (n && typeof n === "object") {
      const tipos = [].concat(n["@type"] || []);
      if (tipos.includes("Product")) {
        productosLd.push({
          sku: n.sku, mpn: n.mpn, name: limpiar(n.name), category: n.category,
          brand: typeof n.brand === "object" ? n.brand?.name : n.brand,
          propiedades: (n.additionalProperty || []).slice(0, MAX_EJEMPLOS)
            .map((p) => [p.name, p.value]),
        });
      }
      Object.values(n).forEach(recorrer);
    }
  };
  jsonLd.forEach(recorrer);

  /** Candidatos a referencia, titulo, migas y datasheet. */
  const candidatos = (sel, filtro) =>
    [...document.querySelectorAll(sel)]
      .filter((el) => filtro(limpiar(el.textContent), el))
      .slice(0, MAX_CANDIDATOS)
      .map((el) => ({ selector: selector(el), texto: limpiar(el.textContent) }));

  /* Codigos de pedido: pueden ser alfanumericos (WE-CBF-123) o solo digitos
     (742792022). Se prioriza el que tenga cerca una etiqueta del tipo
     "order code", "referencia" o "part number". */
  const ETIQUETA_REF = /(order\s*code|article|artikel|part\s*(no|number)|sku|referencia|codigo|c[oó]digo)/i;
  const contexto = (el) => limpiar(
    [el.previousElementSibling?.textContent,
     el.parentElement?.querySelector("*:first-child")?.textContent,
     el.parentElement?.previousElementSibling?.textContent,
     el.getAttribute("class"), el.getAttribute("itemprop")].filter(Boolean).join(" ")
  );
  const esCodigo = (t) =>
    /^[A-Za-z0-9][A-Za-z0-9\-\/.]{4,24}$/.test(t) && /\d/.test(t);

  const referencia = [...document.querySelectorAll("h1, h2, span, div, dd, td, p, b, strong")]
    .filter((el) => el.children.length === 0 && esCodigo(limpiar(el.textContent)))
    .map((el) => ({ selector: selector(el), texto: limpiar(el.textContent), pista: contexto(el) }))
    .sort((a, b) => Number(ETIQUETA_REF.test(b.pista)) - Number(ETIQUETA_REF.test(a.pista)))
    .slice(0, MAX_CANDIDATOS);

  const titulos = [...document.querySelectorAll("h1")].slice(0, 3)
    .map((el) => ({ selector: selector(el), texto: limpiar(el.textContent) }));
  const migas = [...document.querySelectorAll("nav a, ol li a, .breadcrumb a, [class*=readcrumb] a")]
    .slice(0, 12).map((el) => ({ selector: selector(el), texto: limpiar(el.textContent) }));
  const pdfs = [...document.querySelectorAll('a[href$=".pdf"], a[href*="pdf"], a[download]')]
    .slice(0, 5).map((el) => ({ selector: selector(el), href: el.getAttribute("href"),
                                texto: limpiar(el.textContent) }));

  const resultado = {
    url: location.href,
    titulo: limpiar(document.title),
    datos_estructurados_jsonld: productosLd,
    bloques_de_especificaciones: [...tablas, ...listas, ...repetidos].slice(0, 5),
    posibles_referencias: referencia,
    titulos,
    migas_de_pan: migas,
    enlaces_pdf: pdfs,
    nota_render: document.querySelector("#__next, #root, [data-reactroot]")
      ? "La pagina se genera con JavaScript: el conector puede necesitar navegador (o buscar la API que alimenta la pagina)."
      : "HTML servido directamente: el conector deberia bastar con descargar la pagina.",
  };

  const texto = JSON.stringify(resultado, null, 2);
  console.log(texto);
  try { copy(texto); console.log("%c✓ Copiado al portapapeles", "color: green; font-weight: bold"); }
  catch { console.log("Selecciona el JSON de arriba y copialo a mano."); }
  return resultado;
})();
