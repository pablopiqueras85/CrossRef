/* CrossRef - interfaz web. Sin dependencias: solo fetch y DOM. */

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

const state = {
  families: [],
  familyDetail: {},   // id -> detalle con atributos
  lastQuery: null,    // ultima respuesta de /parse
};

/* ----------------------------------------------------------------- utils */

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!response.ok) {
    let detail = response.statusText;
    try { detail = (await response.json()).detail || detail; } catch (_) {}
    throw new Error(detail);
  }
  return response.json();
}

const escapeHtml = (value) =>
  String(value ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const statusClass = (status) => {
  if (status === "coincide") return "coincide";
  if (status === "aproximado") return "aproximado";
  if (status === "no coincide") return "nocoincide";
  if (status.startsWith("no informado")) return "falta";
  return "na";
};

const verdictClass = (verdict) => verdict.replace(/\s+/g, ".");

function busy(button, isBusy, label) {
  button.disabled = isBusy;
  if (isBusy) { button.dataset.label = button.textContent; button.textContent = label || "Trabajando…"; }
  else if (button.dataset.label) { button.textContent = button.dataset.label; }
}

/* ------------------------------------------------------------ navegacion */

$$(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    $$(".tab").forEach((t) => t.classList.toggle("active", t === tab));
    $$(".view").forEach((v) => v.classList.toggle("active", v.id === `view-${tab.dataset.view}`));
    if (tab.dataset.view === "catalogo") loadCatalog();
  });
});

/* ---------------------------------------------------------------- inicio */

async function init() {
  try {
    const [{ families }, stats] = await Promise.all([
      api("/api/v1/families"),
      api("/api/v1/catalog/stats"),
    ]);
    state.families = families;
    const options = families
      .filter((f) => f.id !== "generic")
      .map((f) => `<option value="${f.id}">${escapeHtml(f.label)}</option>`)
      .join("");
    $("#family-select").insertAdjacentHTML("beforeend", options);
    $("#coverage-family").innerHTML = options;
    $("#catalog-badge").textContent = `${stats.items} referencias indexadas`;
  } catch (error) {
    $("#catalog-badge").textContent = "catálogo no disponible";
  }
}

async function familyDetail(id) {
  if (!state.familyDetail[id]) {
    state.familyDetail[id] = await api(`/api/v1/families/${encodeURIComponent(id)}`);
  }
  return state.familyDetail[id];
}

/* ------------------------------------------------------- paso 1: analizar */

$("#btn-analyze").addEventListener("click", analyze);
$("#query-text").addEventListener("keydown", (event) => {
  if ((event.metaKey || event.ctrlKey) && event.key === "Enter") analyze();
});

async function analyze() {
  const text = $("#query-text").value.trim();
  if (!text) { $("#query-text").focus(); return; }
  const button = $("#btn-analyze");
  busy(button, true, "Analizando…");
  try {
    const parsed = await api("/api/v1/parse", {
      method: "POST",
      body: JSON.stringify({
        text,
        family: $("#family-select").value || null,
        part_number: $("#query-pn").value.trim() || null,
        manufacturer: $("#query-mfr").value.trim() || null,
      }),
    });
    state.lastQuery = parsed;
    if (parsed.part_number && !$("#query-pn").value) $("#query-pn").value = parsed.part_number;
    if (!$("#family-select").value && parsed.family) $("#family-select").value = parsed.family;
    await renderUnderstood(parsed);
    await search();
  } catch (error) {
    $("#query-warnings").innerHTML = `<div>Error: ${escapeHtml(error.message)}</div>`;
  } finally {
    busy(button, false);
  }
}

function placeholderFor(attr) {
  if (attr.type === "range") return attr.unit ? `p. ej. 0 - 18 ${attr.unit}` : "p. ej. de X a Y";
  if (attr.type === "number") return attr.unit ? `p. ej. 10 ${attr.unit}` : "p. ej. 4";
  if (attr.type === "enum" && attr.values?.length) return `p. ej. ${attr.values[0]}`;
  if (attr.type === "bool") return "sí / no";
  return "";
}

async function renderUnderstood(parsed) {
  const detail = await familyDetail(parsed.family || "generic");
  const understood = Object.fromEntries(parsed.understood.map((u) => [u.attribute, u]));

  const inputs = detail.attributes
    .filter((attr) => attr.required || understood[attr.id] || !attr.informative)
    .sort((a, b) => (b.required - a.required) || (b.weight - a.weight))
    .map((attr) => {
      const found = understood[attr.id];
      const assumed = found && /valor por defecto/.test(found.source || "");
      const placeholder = placeholderFor(attr);
      return `
        <label>
          <span>
            ${attr.required ? '<i class="req" title="obligatorio">•</i>' : ""}
            ${escapeHtml(attr.label)}
            ${assumed ? '<i class="assumed" title="no venía en la petición">asumido</i>' : ""}
          </span>
          <input type="text" data-attr="${attr.id}" value="${escapeHtml(found ? found.raw : "")}"
                 placeholder="${escapeHtml(placeholder)}" title="${escapeHtml(attr.rule)}">
        </label>`;
    })
    .join("");

  $("#understood-fields").innerHTML = inputs;
  $("#understood").classList.remove("hidden");
  $("#unparsed").innerHTML = parsed.unparsed.length
    ? `Sin usar: ${parsed.unparsed.map((t) => `<span>${escapeHtml(t)}</span>`).join("")}`
    : "";
  $("#query-warnings").innerHTML = (parsed.warnings || [])
    .map((w) => `<div>${escapeHtml(w)}</div>`).join("");
}

/* -------------------------------------------------------- paso 2: buscar */

$("#btn-search").addEventListener("click", search);
$("#btn-reset").addEventListener("click", () => {
  $("#query-text").value = ""; $("#query-pn").value = ""; $("#query-mfr").value = "";
  $("#family-select").value = ""; $("#understood").classList.add("hidden");
  $("#results").innerHTML = '<p class="empty">Introduce una petición para empezar.</p>';
  $("#counts").innerHTML = ""; $("#query-warnings").innerHTML = "";
});

async function search() {
  const fields = {};
  $$("#understood-fields input[data-attr]").forEach((input) => {
    if (input.value.trim()) fields[input.dataset.attr] = input.value.trim();
  });
  const button = $("#btn-search");
  busy(button, true, "Buscando…");
  try {
    const response = await api("/api/v1/crossref", {
      method: "POST",
      body: JSON.stringify({
        text: $("#query-text").value.trim() || null,
        family: $("#family-select").value || state.lastQuery?.family || null,
        fields,
        part_number: $("#query-pn").value.trim() || null,
        manufacturer: $("#query-mfr").value.trim() || null,
        limit: 10,
        include_rejected: $("#opt-rejected").checked,
        strict: $("#opt-strict").checked,
      }),
    });
    renderResults(response);
  } catch (error) {
    $("#results").innerHTML = `<p class="empty">Error: ${escapeHtml(error.message)}</p>`;
  } finally {
    busy(button, false);
  }
}

function renderResults(response) {
  const counts = response.counts || {};
  $("#counts").innerHTML = [
    `${response.catalog_candidates} evaluadas`,
    `${counts["equivalente"] || 0} equivalentes`,
    `${counts["alternativa"] || 0} alternativas`,
    `${counts["descartado"] || 0} descartadas`,
  ].map((t) => `<span>${escapeHtml(t)}</span>`).join("");

  const blocks = [];
  if (!response.results.length) {
    blocks.push(`<p class="empty">Ninguna referencia del catálogo cumple la petición${
      response.rejected.length ? ". Abajo están las descartadas y el motivo." : ""}.</p>`);
  }
  blocks.push(...response.results.map((r) => card(r, false)));
  if (response.rejected.length) {
    blocks.push('<h2 style="margin:18px 0 8px">Descartadas</h2>');
    blocks.push(...response.rejected.map((r) => card(r, true)));
  }
  $("#results").innerHTML = blocks.join("");
}

function card(result, rejected) {
  const rows = result.comparisons
    .filter((c) => c.status !== "no aplicable" || c.catalog_value)
    .map((c) => `
      <tr>
        <td>${c.required ? '<i class="req">•</i> ' : ""}${escapeHtml(c.label)}</td>
        <td class="value">${escapeHtml(c.query_value || "—")}</td>
        <td class="value">${escapeHtml(c.catalog_value || "—")}</td>
        <td class="st ${statusClass(c.status)}">${escapeHtml(c.status)}</td>
        <td class="rule">${escapeHtml(c.reason)}${
          c.deviation ? ` <b>(${escapeHtml(c.deviation)})</b>` : ""}</td>
      </tr>`)
    .join("");

  const specs = Object.entries(result.specs || {})
    .map(([k, v]) => `<div><b>${escapeHtml(k)}:</b> ${escapeHtml(v)}</div>`).join("");

  return `
  <article class="card ${rejected ? "rejected" : ""}">
    <div class="card-head">
      <div>
        <div class="ref">${escapeHtml(result.reference)}${
          result.exact_reference ? " ★" : ""}</div>
        <div class="desc">${escapeHtml(result.description || "")}</div>
        <div class="meta">
          ${escapeHtml(result.manufacturer || "—")} ·
          fuente <b>${escapeHtml(result.source)}</b> ·
          dato de ${escapeHtml((result.fetched_at || "").slice(0, 10))}
          ${result.url ? ` · <a href="${escapeHtml(result.url)}" target="_blank" rel="noopener">ver ficha</a>` : ""}
          ${result.datasheet_url ? ` · <a href="${escapeHtml(result.datasheet_url)}" target="_blank" rel="noopener">datasheet</a>` : ""}
        </div>
      </div>
      <div class="spacer"></div>
      <div style="text-align:right">
        <div class="verdict ${verdictClass(result.verdict)}">${escapeHtml(result.verdict)}</div>
        <div class="score">afinidad ${(result.score * 100).toFixed(0)}%</div>
      </div>
    </div>
    <ul class="reasons">${result.reasons.map((r) => `<li>${escapeHtml(r)}</li>`).join("")}</ul>
    <table class="cmp">
      <thead><tr><th>Campo</th><th>Petición</th><th>Catálogo</th><th>Estado</th><th>Regla y motivo</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
    ${specs ? `<details class="more"><summary>Ficha original del catálogo</summary><div class="specs">${specs}</div></details>` : ""}
  </article>`;
}

/* ------------------------------------------------------------------ lote */

$("#btn-batch").addEventListener("click", async () => {
  const lines = $("#batch-text").value.split("\n").map((l) => l.trim()).filter(Boolean);
  if (!lines.length) return;
  const button = $("#btn-batch");
  busy(button, true, "Procesando…");
  try {
    const response = await api("/api/v1/crossref/batch", {
      method: "POST",
      body: JSON.stringify({ rows: lines.map((text) => ({ text })), limit: 3 }),
    });
    $("#batch-results").innerHTML = `
      <table>
        <thead><tr><th>#</th><th>Petición</th><th>Familia</th><th>Estado</th>
        <th>Referencia</th><th>Alternativas</th><th>Motivo</th></tr></thead>
        <tbody>${response.results.map((r) => `
          <tr>
            <td>${r.row}</td>
            <td>${escapeHtml(r.input)}</td>
            <td>${escapeHtml(r.family)}</td>
            <td><span class="verdict ${verdictClass(r.status)}">${escapeHtml(r.status)}</span></td>
            <td class="value">${r.catalog_url
              ? `<a href="${escapeHtml(r.catalog_url)}" target="_blank" rel="noopener">${escapeHtml(r.catalog_reference || "")}</a>`
              : escapeHtml(r.catalog_reference || "—")}</td>
            <td class="value">${escapeHtml((r.alternatives || []).join(", ") || "—")}</td>
            <td>${escapeHtml(r.reason)}</td>
          </tr>`).join("")}</tbody>
      </table>`;
  } catch (error) {
    $("#batch-results").innerHTML = `<p class="empty">Error: ${escapeHtml(error.message)}</p>`;
  } finally {
    busy(button, false);
  }
});

$("#btn-batch-csv").addEventListener("click", async () => {
  const lines = $("#batch-text").value.split("\n").map((l) => l.trim()).filter(Boolean);
  if (!lines.length) return;
  const csv = "peticion\n" + lines.map((l) => `"${l.replace(/"/g, '""')}"`).join("\n");
  const form = new FormData();
  form.append("file", new Blob([csv], { type: "text/csv" }), "peticiones.csv");
  const response = await fetch("/api/v1/crossref/batch/csv?column=peticion", { method: "POST", body: form });
  const blob = await response.blob();
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = "crossref_resultados.csv";
  link.click();
  URL.revokeObjectURL(link.href);
});

/* -------------------------------------------------------------- catalogo */

async function loadCatalog() {
  try {
    const stats = await api("/api/v1/catalog/stats");
    const families = Object.entries(stats.by_family)
      .map(([name, n]) => `<div class="stat"><b>${n}</b><span>${escapeHtml(name)}</span></div>`).join("");
    const sources = Object.entries(stats.by_source)
      .map(([name, info]) => `<div class="stat"><b>${info.items}</b><span>fuente ${escapeHtml(name)}<br>${
        escapeHtml((info.last_fetch || "").slice(0, 16).replace("T", " "))}</span></div>`).join("");
    $("#catalog-stats").innerHTML =
      `<div class="stat"><b>${stats.items}</b><span>referencias activas</span></div>` + families + sources;
    await loadCoverage();
  } catch (error) {
    $("#catalog-stats").innerHTML = `<p class="empty">Error: ${escapeHtml(error.message)}</p>`;
  }
}

$("#coverage-family").addEventListener("change", loadCoverage);

async function loadCoverage() {
  const family = $("#coverage-family").value;
  if (!family) return;
  const data = await api(`/api/v1/catalog/coverage/${encodeURIComponent(family)}`);
  $("#coverage").innerHTML = Object.entries(data).map(([id, info]) => `
    <div class="cov-row">
      <div class="lbl">
        <span>${info.required ? '<i class="req">•</i> ' : ""}${escapeHtml(info.label)}</span>
        <span>${(info.coverage * 100).toFixed(0)}% (${info.items_with_value})</span>
      </div>
      <div class="bar"><i style="width:${(info.coverage * 100).toFixed(0)}%"></i></div>
    </div>`).join("");
}

$("#btn-sync").addEventListener("click", async () => {
  const button = $("#btn-sync");
  busy(button, true, "Sincronizando…");
  $("#sync-output").textContent = "";
  try {
    const report = await api("/api/v1/catalog/sync", {
      method: "POST",
      body: JSON.stringify({ source: $("#sync-source").value.trim() }),
    });
    $("#sync-output").textContent = JSON.stringify(report, null, 2);
    await loadCatalog();
    const stats = await api("/api/v1/catalog/stats");
    $("#catalog-badge").textContent = `${stats.items} referencias indexadas`;
  } catch (error) {
    $("#sync-output").textContent = `Error: ${error.message}`;
  } finally {
    busy(button, false);
  }
});

init();
