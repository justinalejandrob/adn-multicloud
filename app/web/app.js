/* =============================================================================
   ADN Multinube - Dashboard (JavaScript sin dependencias)
   Secciones: Panel principal · Procesamiento ADN · Rendimiento · Multicloud
   ============================================================================= */
"use strict";

/* ---------------------------------------------------------------- utilidades */
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
const SVGNS = "http://www.w3.org/2000/svg";

const ICONS = {
  grid: '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
  dna: '<path d="M7 3c0 6 10 6 10 12s-10 6-10 6"/><path d="M17 3c0 6-10 6-10 12s10 6 10 6"/><path d="M8.5 7h7M8.5 17h7M10 12h4"/>',
  gauge: '<path d="M12 14l4-4"/><path d="M3.5 18a9 9 0 1 1 17 0"/><circle cx="12" cy="14" r="1.6"/>',
  cloud: '<path d="M7 18a4.5 4.5 0 0 1-.6-8.96A6 6 0 0 1 18 8.5a4.5 4.5 0 0 1-.5 9.5H7z"/>',
  contrast: '<circle cx="12" cy="12" r="9"/><path d="M12 3v18a9 9 0 0 0 0-18z" fill="currentColor"/>',
  download: '<path d="M12 4v11"/><path d="M7 10l5 5 5-5"/><path d="M5 20h14"/>',
  upload: '<path d="M12 20V9"/><path d="M7 13l5-5 5 5"/><path d="M5 4h14"/>',
  play: '<path d="M7 4.5v15l12-7.5z" fill="currentColor" stroke="none"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  percent: '<path d="M19 5L5 19"/><circle cx="7" cy="7" r="2.5"/><circle cx="17" cy="17" r="2.5"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="M20 20l-4-4"/>',
  cpu: '<rect x="6" y="6" width="12" height="12" rx="2"/><path d="M9 2v4M15 2v4M9 18v4M15 18v4M2 9h4M2 15h4M18 9h4M18 15h4"/>',
  zap: '<path d="M13 2L4 14h7l-1 8 9-12h-7z"/>',
  file: '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/>',
  layers: '<path d="M12 3l9 5-9 5-9-5z"/><path d="M3 13l9 5 9-5"/>',
  hash: '<path d="M5 9h14M5 15h14M10 4L8 20M16 4l-2 16"/>',
  ruler: '<path d="M3 17L17 3l4 4L7 21z"/><path d="M7 13l2 2M10 10l2 2M13 7l2 2"/>',
  check: '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
  x: '<path d="M6 6l12 12M18 6L6 18"/>',
  alert: '<path d="M12 3L2 20h20z"/><path d="M12 10v4M12 17v.5"/>',
  pause: '<circle cx="12" cy="12" r="9"/><path d="M10 9v6M14 9v6"/>',
  loader: '<path d="M12 3a9 9 0 1 0 9 9"/>',
  server: '<rect x="3" y="4" width="18" height="7" rx="2"/><rect x="3" y="13" width="18" height="7" rx="2"/><path d="M7 7.5h.01M7 16.5h.01"/>',
  trend: '<path d="M3 17l6-6 4 4 8-8"/><path d="M15 7h6v6"/>',
};
function iconSVG(name, size = 18) {
  return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[name] || ""}</svg>`;
}
function applyIcons(root = document) {
  $$("[data-icon]", root).forEach((n) => { n.innerHTML = iconSVG(n.dataset.icon, n.classList.contains("page-icon") ? 20 : 18); });
}

/** Crea un elemento DOM. Los textos van SIEMPRE por textContent (datos no confiables). */
function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "style" && typeof v === "object") Object.assign(el.style, v);
    else if (k === "html") el.innerHTML = v; // solo para íconos estáticos
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat()) {
    if (c == null || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}
const ico = (name, size) => h("span", { html: iconSVG(name, size), style: { display: "inline-flex" } });
function svg(tag, attrs = {}) {
  const el = document.createElementNS(SVGNS, tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "style") Object.assign(el.style, v);
    else if (k === "text") el.textContent = v;
    else el.setAttribute(k, v);
  }
  return el;
}

const LOCALE = "es-EC";
const isNum = (v) => typeof v === "number" && Number.isFinite(v);
function nf(v, d = 0) {
  return isNum(v) ? v.toLocaleString(LOCALE, { minimumFractionDigits: d, maximumFractionDigits: d }) : "—";
}
function fmtBytes(b) {
  if (!isNum(b)) return "—";
  const u = ["B", "KB", "MB", "GB", "TB"]; let i = 0;
  while (b >= 1024 && i < u.length - 1) { b /= 1024; i++; }
  return `${nf(b, i ? 2 : 0)} ${u[i]}`;
}
function fmtSecs(s) {
  if (!isNum(s)) return "—";
  if (s < 60) return `${nf(s, s < 10 ? 2 : 1)} s`;
  const m = Math.floor(s / 60), r = Math.round(s - m * 60);
  return `${m} min ${r} s`;
}
function fmtDate(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  return isNaN(d) ? iso : d.toLocaleString(LOCALE, { dateStyle: "medium", timeStyle: "short" });
}
/** Acorta nombres de CPU: "Intel(R) Xeon(R) Processor @ 2.80GHz" -> "Intel Xeon @ 2.80GHz" */
const cleanCpu = (c) => (c || "—").replace(/\((R|TM|tm|r)\)/g, "").replace(/\b(CPU|Processor)\b/g, "").replace(/\s+/g, " ").trim();
const shortHash = (s) => (s ? `${s.slice(0, 10)}…${s.slice(-6)}` : "—");
function toast(msg) {
  const t = h("div", { class: "toast", role: "status" }, msg);
  document.body.append(t);
  setTimeout(() => t.remove(), 4200);
}
const store = {
  get(k, def) { try { const v = localStorage.getItem(k); return v ? JSON.parse(v) : def; } catch (e) { return def; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* almacenamiento no disponible */ } },
};

/* ---------------------------------------------------------- proveedores */
const PROVIDERS = {
  azure: { label: "Microsoft Azure", model: "IaaS", flag: "EE. UU." },
  aws: { label: "Amazon Web Services", model: "IaaS", flag: "EE. UU." },
  huawei: { label: "Huawei Cloud", model: "IaaS", flag: "China" },
  alibaba: { label: "Alibaba Cloud", model: "IaaS", flag: "China" },
  guaracloud: { label: "GuaraCloud", model: "PaaS", flag: "Brasil" },
  magalu: { label: "Magalu Cloud", model: "IaaS", flag: "Brasil" },
  claro: { label: "Claro Cloud", model: "IaaS", flag: "Ecuador" },
  local: { label: "Laptop (local)", model: "Local", flag: "Ecuador" },
};
const PROVIDER_ORDER = ["azure", "aws", "huawei", "alibaba", "guaracloud", "magalu", "claro", "local"];
const providerLabel = (p) => (PROVIDERS[p] && PROVIDERS[p].label) || p;
const providerModel = (p) => (PROVIDERS[p] && PROVIDERS[p].model) || "IaaS";
/** El color sigue al proveedor (no a su posición en un gráfico filtrado). */
function providerColor(p) {
  const names = sortProviders(Array.from(new Set(allResults().map((r) => r.environment.cloud_provider))));
  const i = names.indexOf(p);
  return i >= 0 && i < 5 ? `var(--s${i + 1})` : "var(--neutral-mark)";
}
function sortProviders(list) {
  return list.sort((a, b) => {
    const ia = PROVIDER_ORDER.indexOf(a), ib = PROVIDER_ORDER.indexOf(b);
    return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib) || a.localeCompare(b);
  });
}

/* -------------------------------------------------------------- estado */
const S = {
  info: null, state: null, results: [], imported: store.get("adn-imported", []),
  view: "panel", perfKey: null, prevStatus: null, online: true,
};
const VIEWS = {
  panel: { title: "Panel principal", sub: "Estado de la ejecución y proveedor cloud", icon: "grid" },
  adn: { title: "Procesamiento ADN", sub: "Tamaño del archivo, patrón, bloques y resultados", icon: "dna" },
  rendimiento: { title: "Rendimiento", sub: "Comparación secuencial vs. paralelo y tiempos", icon: "gauge" },
  multicloud: { title: "Multicloud", sub: "Comparación de proveedores, CPU, RAM y rendimiento", icon: "cloud" },
};

const resultKey = (r) => `${r.environment.cloud_provider}|${r.environment.timestamp_utc}|${r.input.size_bytes}`;
function validResult(r) {
  return r && r.environment && r.input && r.result && Array.isArray(r.runs);
}
function allResults() {
  const map = new Map();
  for (const r of [...S.results, ...S.imported]) if (validResult(r)) map.set(resultKey(r), r);
  return Array.from(map.values()).sort((a, b) => a.environment.timestamp_utc.localeCompare(b.environment.timestamp_utc));
}
function currentResult() {
  const list = allResults();
  const me = S.info && S.info.environment.cloud_provider;
  const mine = list.filter((r) => r.environment.cloud_provider === me);
  return (mine.length ? mine : list).at(-1) || null;
}
function latestByProvider() {
  const map = new Map();
  for (const r of allResults()) map.set(r.environment.cloud_provider, r);
  return sortProviders(Array.from(map.keys())).map((p) => map.get(p));
}
function seqRun(r) { return r && r.runs.find((x) => x.mode === "sequential"); }
function parRun(r) {
  const p = r ? r.runs.filter((x) => x.mode === "parallel") : [];
  return p.length ? p.reduce((a, b) => (b.workers > a.workers ? b : a)) : null;
}
const mainRun = (r) => parRun(r) || seqRun(r);

/* ------------------------------------------------------------------ API */
async function api(path) {
  const res = await fetch(path, { headers: { Accept: "application/json" }, cache: "no-store" });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) { const e = new Error(body.error || res.statusText); e.status = res.status; throw e; }
  return body;
}
async function loadInfo() { S.info = await api("/api/info"); }
async function loadResults() { S.results = (await api("/api/results")).results || []; }

let pollTimer = null;
async function poll() {
  clearTimeout(pollTimer);
  try {
    S.state = await api("/api/state");
    S.online = true;
    const st = S.state.status;
    if (S.prevStatus === "running" && st !== "running") {
      await Promise.all([loadResults(), loadInfo()]);
      formBuilt = false; // refresca la información del archivo preparado
      toast(st === "done" ? "Análisis completado" : `El análisis falló: ${S.state.error || ""}`);
      renderAll();
    } else {
      renderLive();
    }
    S.prevStatus = st;
  } catch (e) {
    S.online = false;
    renderLive();
  }
  pollTimer = setTimeout(poll, S.state && S.state.status === "running" ? 1000 : 4000);
}

/* ============================================================== GRÁFICOS */
const tip = { el: null };
function showTip(evt, title, rows) {
  const el = tip.el || (tip.el = $("#tooltip"));
  el.replaceChildren(h("div", { class: "tt-title" }, title),
    ...rows.map((r) => h("div", { class: "tt-row" },
      h("span", { class: "tt-key" }, h("i", { style: { background: r.color } }), r.name), h("b", {}, r.value))));
  el.classList.remove("hidden");
  const pad = 14, w = el.offsetWidth, ht = el.offsetHeight;
  let x = evt.clientX + pad, y = evt.clientY + pad;
  if (x + w > innerWidth - 8) x = evt.clientX - w - pad;
  if (y + ht > innerHeight - 8) y = evt.clientY - ht - pad;
  el.style.left = `${Math.max(8, x)}px`; el.style.top = `${Math.max(8, y)}px`;
}
function hideTip() { if (tip.el) tip.el.classList.add("hidden"); }

function niceMax(v) {
  if (!(v > 0)) return 1;
  const exp = Math.pow(10, Math.floor(Math.log10(v)));
  const f = v / exp;
  const nf_ = f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10;
  return nf_ * exp;
}
/** Decimales suficientes para que las 5 marcas del eje sean distintas. */
function axisDecimals(ymax) {
  const step = ymax / 4;
  for (let d = 0; d <= 3; d++) if (Math.abs(step * 10 ** d - Math.round(step * 10 ** d)) < 1e-9) return d;
  return 3;
}
function legendEl(items) {
  return h("div", { class: "legend" }, items.map((it) =>
    h("span", {}, h("i", { class: it.kind || "", style: { background: it.kind === "dash" ? "none" : it.color } }), it.name)));
}
function emptyEl(msg) { return h("div", { class: "empty" }, msg); }
function barPath(x, y, w, hgt, r = 4) {
  r = Math.min(r, hgt, w / 2);
  if (hgt <= 0) return "";
  return `M${x},${y + hgt}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + hgt}Z`;
}

/**
 * Barras verticales agrupadas.
 * opts: categories[], series[{name,color,values[]}], fmt(v), barColors[] (color por
 * categoría cuando hay una sola serie), height
 */
function barChart(container, opts) {
  container.replaceChildren();
  const { categories, series } = opts;
  const fmt = opts.fmt || ((v) => nf(v, 1));
  const values = series.flatMap((s) => s.values).filter(isNum);
  if (!categories.length || !values.length) { container.append(emptyEl(opts.empty || "Sin datos todavía")); return; }
  if (series.length > 1) container.append(legendEl(series.map((s) => ({ name: s.name, color: s.color }))));

  const W = Math.max(280, container.clientWidth || 560), H = opts.height || 250;
  const m = { l: 46, r: 8, t: 22, b: 34 };
  const iw = W - m.l - m.r, ih = H - m.t - m.b;
  const ymax = niceMax(Math.max(...values) * 1.08);
  const y = (v) => m.t + ih - (v / ymax) * ih;
  const root = svg("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": opts.label || "Gráfico de barras" });

  const dec = axisDecimals(ymax);
  for (let i = 0; i <= 4; i++) {
    const v = (ymax / 4) * i, yy = y(v);
    root.append(svg("line", { x1: m.l, x2: W - m.r, y1: yy, y2: yy, class: i ? "gridline" : "baseline" }));
    root.append(svg("text", { x: m.l - 8, y: yy + 4, "text-anchor": "end", text: nf(v, dec) }));
  }
  const band = iw / categories.length;
  const n = series.length, gap = 2;
  const bw = Math.min(56, (band * 0.68 - gap * (n - 1)) / n);
  const groupW = bw * n + gap * (n - 1);
  const showLabels = categories.length * n <= 16 && bw >= 22;

  categories.forEach((cat, ci) => {
    const gx = m.l + band * ci + (band - groupW) / 2;
    series.forEach((s, si) => {
      const v = s.values[ci];
      if (!isNum(v)) return;
      const x = gx + si * (bw + gap), top = y(v), hh = m.t + ih - top;
      const color = (n === 1 && opts.barColors && opts.barColors[ci]) || s.color;
      const p = svg("path", { d: barPath(x, top, bw, Math.max(hh, 1)), class: "bar", style: { fill: color } });
      const hit = svg("rect", { x: x - gap, y: m.t, width: bw + gap * 2, height: ih, fill: "transparent", tabindex: 0 });
      const show = (e) => { p.classList.add("hover"); showTip(e, cat, [{ name: s.name, value: fmt(v), color }]); };
      hit.addEventListener("pointermove", show);
      hit.addEventListener("focus", (e) => { const r = hit.getBoundingClientRect(); show({ clientX: r.right, clientY: r.top }); });
      hit.addEventListener("pointerleave", () => { p.classList.remove("hover"); hideTip(); });
      hit.addEventListener("blur", () => { p.classList.remove("hover"); hideTip(); });
      root.append(p);
      if (showLabels) root.append(svg("text", { x: x + bw / 2, y: top - 6, "text-anchor": "middle", class: "value-label", text: fmt(v) }));
      root.append(hit);
    });
    const label = cat.length > 18 ? `${cat.slice(0, 17)}…` : cat;
    root.append(svg("text", { x: m.l + band * ci + band / 2, y: H - 12, "text-anchor": "middle", text: label }));
  });
  container.append(root);
}

/**
 * Líneas sobre eje X numérico, con cruz que sigue al puntero.
 * opts: xs[], series[{name,color,values[],dashed}], fmt, xFmt, xLabel
 */
function lineChart(container, opts) {
  container.replaceChildren();
  const { xs, series } = opts;
  const fmt = opts.fmt || ((v) => nf(v, 2));
  const xFmt = opts.xFmt || ((v) => nf(v));
  const values = series.flatMap((s) => s.values).filter(isNum);
  if (xs.length < 2 || !values.length) { container.append(emptyEl(opts.empty || "Sin datos suficientes")); return; }
  container.append(legendEl(series.map((s) => ({ name: s.name, color: s.color, kind: s.dashed ? "dash" : "line" }))));

  const W = Math.max(280, container.clientWidth || 560), H = opts.height || 250;
  const m = { l: 42, r: 14, t: 12, b: 40 };
  const iw = W - m.l - m.r, ih = H - m.t - m.b;
  const xmin = Math.min(...xs), xmax = Math.max(...xs);
  const ymax = niceMax(Math.max(...values) * 1.08);
  const x = (v) => m.l + ((v - xmin) / (xmax - xmin || 1)) * iw;
  const y = (v) => m.t + ih - (v / ymax) * ih;
  const root = svg("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": opts.label || "Gráfico de líneas" });

  const dec = axisDecimals(ymax);
  for (let i = 0; i <= 4; i++) {
    const v = (ymax / 4) * i, yy = y(v);
    root.append(svg("line", { x1: m.l, x2: W - m.r, y1: yy, y2: yy, class: i ? "gridline" : "baseline" }));
    root.append(svg("text", { x: m.l - 8, y: yy + 4, "text-anchor": "end", text: nf(v, dec) }));
  }
  xs.forEach((v) => root.append(svg("text", { x: x(v), y: H - 22, "text-anchor": "middle", text: xFmt(v) })));
  if (opts.xLabel) root.append(svg("text", { x: m.l + iw / 2, y: H - 4, "text-anchor": "middle", text: opts.xLabel }));

  series.forEach((s) => {
    const pts = xs.map((xv, i) => [xv, s.values[i]]).filter(([, v]) => isNum(v));
    if (pts.length < 1) return;
    const d = pts.map(([xv, v], i) => `${i ? "L" : "M"}${x(xv)},${y(v)}`).join("");
    root.append(svg("path", { d, fill: "none", "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round",
      "stroke-dasharray": s.dashed ? "5 5" : "none", style: { stroke: s.dashed ? "var(--muted)" : s.color } }));
    if (!s.dashed) pts.forEach(([xv, v]) => root.append(svg("circle", { cx: x(xv), cy: y(v), r: 4, "stroke-width": 2, style: { fill: s.color, stroke: "var(--surface)" } })));
  });

  const cross = svg("line", { y1: m.t, y2: m.t + ih, class: "baseline", style: { display: "none" } });
  root.append(cross);
  const overlay = svg("rect", { x: m.l, y: m.t, width: iw, height: ih, fill: "transparent" });
  overlay.addEventListener("pointermove", (e) => {
    const r = root.getBoundingClientRect();
    const px = ((e.clientX - r.left) / r.width) * W;
    let best = 0;
    xs.forEach((v, i) => { if (Math.abs(x(v) - px) < Math.abs(x(xs[best]) - px)) best = i; });
    cross.setAttribute("x1", x(xs[best])); cross.setAttribute("x2", x(xs[best])); cross.style.display = "";
    showTip(e, `${opts.xName || "x"}: ${xFmt(xs[best])}`, series.map((s) => ({
      name: s.name, value: isNum(s.values[best]) ? fmt(s.values[best]) : "—", color: s.dashed ? "var(--muted)" : s.color })));
  });
  overlay.addEventListener("pointerleave", () => { cross.style.display = "none"; hideTip(); });
  root.append(overlay);
  container.append(root);
}

/* ============================================================== VISTAS */
function kpiTile({ label, iconName, value, unit, foot }) {
  return h("div", { class: "card kpi" },
    h("div", { class: "label" }, h("span", {}, label), h("span", { class: "icon", html: iconSVG(iconName) })),
    h("div", { class: "value num" }, value, unit ? h("small", {}, unit) : null),
    h("div", { class: "foot" }, foot || " "));
}
function kvList(rows) {
  return h("dl", { class: "kv" }, rows.flatMap(([k, v]) => [h("dt", {}, k), h("dd", {}, v ?? "—")]));
}
function statusMeta(st) {
  return {
    idle: { text: "En espera", icon: "pause", color: "var(--muted)" },
    running: { text: "Procesando", icon: "loader", color: "var(--warning)" },
    done: { text: "Completado", icon: "check", color: "var(--good)" },
    error: { text: "Error", icon: "alert", color: "var(--critical)" },
  }[st] || { text: "Sin conexión", icon: "alert", color: "var(--critical)" };
}
const PHASES = {
  prepare: "Preparando datos", download: "Descargando el genoma", generate: "Generando ADN sintético",
  process: "Iniciando procesamiento", sequential: "Procesamiento secuencial", parallel: "Procesamiento paralelo",
};
function overallProgress(state) {
  if (!state || state.status !== "running") return null;
  const steps = state.steps || {};
  const vals = Object.values(steps).filter(isNum);
  const expected = state.params && state.params.mode === "both" ? 3 : state.params && state.params.mode === "benchmark" ? 5 : 2;
  const total = vals.reduce((a, b) => a + b, 0) / (Math.max(expected, vals.length) * 100);
  return Math.min(99, Math.round(total * 100));
}

/* ---------- topbar / sidebar (siempre) ---------- */
function renderChrome() {
  const env = S.info && S.info.environment;
  $("#side-provider").textContent = env ? providerLabel(env.cloud_provider) : "…";
  $("#side-region").textContent = env ? `${env.cloud_origin} · ${env.cloud_region}` : "";
  const st = S.online ? (S.state ? S.state.status : "idle") : "offline";
  const meta = statusMeta(st);
  const pill = $("#status-pill");
  pill.className = `pill ${st}`;
  $("#status-pill-text").textContent = st === "running" && overallProgress(S.state) != null
    ? `${meta.text} · ${overallProgress(S.state)} %` : meta.text;
}

/* ---------- 1. Panel principal ---------- */
function renderKpis(r, target) {
  const seq = seqRun(r), run = mainRun(r);
  const env = r && r.environment;
  const pmb = r && r.result.length ? (r.result.pattern_hits / (r.result.length / 1e6)) : null;
  target.replaceChildren(
    kpiTile({ label: "Tiempo de procesamiento", iconName: "clock", value: run ? nf(run.seconds, run.seconds < 10 ? 2 : 1) : "—", unit: run ? "s" : "",
      foot: !r ? "Ejecute un análisis" : seq && run !== seq ? `Secuencial: ${fmtSecs(seq.seconds)}` : `Modo ${run && run.mode === "sequential" ? "secuencial" : "paralelo"}` }),
    kpiTile({ label: "Contenido GC", iconName: "percent", value: r ? nf(r.summary.gc_content_pct, 2) : "—", unit: r ? "%" : "",
      foot: r ? `A+T: ${nf(100 - r.summary.gc_content_pct, 2)} %` : "Proporción de G y C" }),
    kpiTile({ label: "Coincidencias del patrón", iconName: "search", value: r ? nf(r.result.pattern_hits) : "—",
      foot: r ? `${r.input.pattern} · ${nf(pmb, 1)} por millón de bases` : "Patrón buscado" }),
    kpiTile({ label: "Trabajadores", iconName: "cpu", value: run ? nf(run.workers) : "—",
      foot: env ? `de ${nf(env.cpu_count)} núcleos lógicos disponibles` : "Procesos en paralelo" }),
    kpiTile({ label: "Velocidad de procesamiento", iconName: "zap", value: run ? nf(run.throughput_mb_s, 1) : "—", unit: run ? "MB/s" : "",
      foot: run && run.mode === "parallel" ? `Speedup ${nf(run.speedup, 2)}× · eficiencia ${nf(run.efficiency * 100, 0)} %` : "Lectura + análisis" }),
  );
}

function renderStatusCard() {
  const card = $("#status-card");
  const state = S.state || { status: "idle" };
  const st = S.online ? state.status : "offline";
  const meta = statusMeta(st);
  const pct = overallProgress(state);
  const phase = state.phase ? (PHASES[state.phase] || state.phase) : null;
  let detail;
  if (!S.online) detail = "No se puede contactar al servidor del contenedor.";
  else if (st === "running") detail = `${phase || "Trabajando"} · iniciado ${fmtDate(state.started)}`;
  else if (st === "done") detail = `Terminó ${fmtDate(state.finished)} · duración total ${fmtSecs(state.seconds)}`;
  else if (st === "error") detail = state.error || "Error desconocido";
  else detail = "Listo para procesar. Configure el análisis en «Procesamiento ADN».";

  const bar = h("div", { class: `progress${st === "running" && pct == null ? " indeterminate" : ""}` }, h("span", { style: { width: `${st === "done" ? 100 : pct || 0}%` } }));
  card.replaceChildren(
    h("div", { class: "status-row" },
      h("div", { class: "status-icon", style: { color: meta.color }, html: iconSVG(meta.icon, 22) }),
      h("div", { class: "status-text", style: { flex: 1, minWidth: "200px" } },
        h("strong", {}, `${meta.text}${st === "running" && pct != null ? ` · ${pct} %` : ""}`),
        h("span", { class: "muted" }, detail)),
      h("a", { class: "btn", href: "#adn" }, st === "running" ? "Ver avance" : "Configurar")),
  );
  if (!(st === "idle" && S.online)) card.append(bar);
}

function renderProviderCard() {
  const card = $("#provider-card");
  const env = S.info && S.info.environment;
  if (!env) { card.replaceChildren(emptyEl("Cargando…")); return; }
  card.replaceChildren(
    h("div", { class: "card-head" },
      h("div", {}, h("h2", { class: "card-title" }, "Proveedor cloud"), h("p", { class: "card-sub" }, "Dónde corre este contenedor")),
      h("span", { class: "tag" }, providerModel(env.cloud_provider))),
    kvList([
      ["Proveedor", providerLabel(env.cloud_provider)],
      ["Origen", env.cloud_origin],
      ["Región", env.cloud_region],
      ["Tipo de instancia", env.instance_type],
      ["CPU", h("span", { title: env.cpu_model }, cleanCpu(env.cpu_model))],
      ["Núcleos lógicos", nf(env.cpu_count)],
      ["RAM", isNum(env.ram_gb) ? `${nf(env.ram_gb, 2)} GB` : "—"],
      ["Arquitectura", env.architecture],
      ["En contenedor", env.in_container ? "Sí (Docker)" : "No"],
    ]));
}

function integrityLine(ok, text) {
  return h("div", { style: { display: "flex", alignItems: "center", gap: "8px", marginTop: "12px" } },
    h("span", { style: { color: ok ? "var(--good)" : "var(--critical)", display: "inline-flex" }, html: iconSVG(ok ? "check" : "x") }),
    h("span", {}, text));
}

function renderLastCard() {
  const card = $("#last-card");
  const r = currentResult();
  const head = h("div", { class: "card-head" },
    h("div", {}, h("h2", { class: "card-title" }, "Último análisis"), h("p", { class: "card-sub" }, r ? fmtDate(r.environment.timestamp_utc) : "Todavía no hay resultados")));
  if (!r) { card.replaceChildren(head, emptyEl("Ejecute un análisis para ver el resumen aquí.")); return; }
  card.replaceChildren(head,
    kvList([
      ["Archivo", `${r.input.file} · ${fmtBytes(r.input.size_bytes)}`],
      ["Secuencias", nf(r.result.records)],
      ["Bloques", `${nf(r.input.chunks)} × ${nf(r.input.chunk_mb)} MB`],
      ["Patrón", r.input.pattern],
      ["SHA-256", h("span", { class: "mono", title: r.input.sha256 || "" }, shortHash(r.input.sha256))],
    ]),
    integrityLine(r.sequential_equals_parallel !== false,
      r.sequential_equals_parallel === false ? "Secuencial y paralelo NO coinciden" : "Secuencial y paralelo dan resultados idénticos"));
}

function renderLog() {
  const pre = $("#log");
  const lines = (S.state && S.state.log) || [];
  const atBottom = pre.scrollHeight - pre.scrollTop - pre.clientHeight < 40;
  pre.textContent = lines.length ? lines.join("\n") : "(sin salida todavía)";
  if (atBottom) pre.scrollTop = pre.scrollHeight;
}

function renderPanel() {
  renderKpis(currentResult(), $("#kpis"));
  renderStatusCard(); renderProviderCard(); renderLastCard(); renderLog();
}

/* ---------- 2. Procesamiento ADN ---------- */
let formBuilt = false;
function buildForm() {
  const form = $("#run-form");
  const info = S.info;
  if (!info) return;
  const d = info.defaults, url = info.source === "url", dna = info.dna_file || {};
  const cores = info.environment.cpu_count;
  const field = (id, label, input, hint, wide) =>
    h("div", { class: `field${wide ? " wide" : ""}` }, h("label", { for: id }, label), input, hint ? h("span", { class: "hint", id: `${id}-hint` }, hint) : null);

  const source = h("div", { class: "field wide" },
    h("label", {}, "Fuente del ADN"),
    h("div", { class: "source-box" },
      h("span", { style: { color: "var(--brand)", display: "inline-flex" }, html: iconSVG(url ? "download" : "dna", 22) }),
      h("div", {},
        h("div", { style: { fontWeight: 600 } }, url ? `Genoma real (${info.source_host || "URL configurada"})` : "ADN sintético determinista"),
        h("div", { class: "muted" }, dna.exists
          ? `Archivo preparado: ${fmtBytes(dna.size_bytes)}${dna.sha256 ? ` · SHA-256 ${shortHash(dna.sha256)}` : ""}`
          : url ? "Se descargará en la primera ejecución" : "Se generará en la primera ejecución"))));

  const sizeInput = url
    ? h("input", { id: "f-limit", type: "number", min: 0, step: 50, value: d.limit_mb, inputmode: "numeric" })
    : h("input", { id: "f-size", type: "text", value: d.size, placeholder: "100MB" });
  const mode = h("select", { id: "f-mode" },
    [["both", "Secuencial + paralelo"], ["sequential", "Solo secuencial"], ["parallel", "Solo paralelo"], ["benchmark", "Benchmark (1, 2, 4… procesos)"]]
      .map(([v, t]) => h("option", { value: v, selected: v === d.mode }, t)));
  const workers = h("input", { id: "f-workers", type: "number", min: 0, max: 256, value: d.workers, inputmode: "numeric" });
  const chunk = h("input", { id: "f-chunk", type: "number", min: 1, max: 512, value: d.chunk_mb, inputmode: "numeric" });
  const pattern = h("input", { id: "f-pattern", type: "text", value: d.pattern, maxlength: 64, autocomplete: "off", spellcheck: "false", style: { fontFamily: "var(--mono)", textTransform: "uppercase" } });
  const runBtn = h("button", { class: "btn primary", type: "submit", id: "run-btn", html: `${iconSVG("play")}<span>Ejecutar análisis</span>` });
  const err = h("span", { class: "form-error", id: "form-error", role: "alert" });

  form.replaceChildren(
    source,
    url ? field("f-limit", "Límite (MB)", sizeInput, "0 = genoma completo") : field("f-size", "Tamaño del ADN", sizeInput, "Ej.: 4MB, 100MB, 1GB"),
    field("f-mode", "Modo", mode, "Benchmark genera la curva de speedup"),
    field("f-workers", "Trabajadores", workers, `0 = todos (${nf(cores)} núcleos)`),
    field("f-chunk", "Tamaño de bloque (MB)", chunk, "Menos RAM con bloques pequeños"),
    field("f-pattern", "Patrón genético", pattern, "Solo A, C, G, T, N", true),
    h("div", { class: "form-actions" }, runBtn, err),
  );
  const updateChunks = () => {
    const mb = Number(chunk.value) || 32;
    let total = dna.size_bytes;
    if (url && Number(sizeInput.value) > 0) total = Math.min(total || Infinity, Number(sizeInput.value) * 1048576);
    $("#f-chunk-hint").textContent = isNum(total) ? `≈ ${nf(Math.ceil(total / (mb * 1048576)))} bloques` : "Menos RAM con bloques pequeños";
  };
  chunk.addEventListener("input", updateChunks);
  sizeInput.addEventListener("input", updateChunks);
  updateChunks();
  form.onsubmit = submitRun;
  formBuilt = true;
}

async function submitRun(ev) {
  ev.preventDefault();
  const err = $("#form-error");
  err.textContent = "";
  const q = new URLSearchParams();
  const pat = $("#f-pattern").value.trim().toUpperCase();
  if (!/^[ACGTN]{1,64}$/.test(pat)) { err.textContent = "El patrón solo admite A, C, G, T, N."; return; }
  if ($("#f-limit")) q.set("limit_mb", String(Math.max(0, Math.floor(Number($("#f-limit").value) || 0))));
  if ($("#f-size")) {
    const size = $("#f-size").value.trim().toUpperCase();
    if (!/^\d+(\.\d+)?(B|KB|MB|GB)$/.test(size)) { err.textContent = "Tamaño inválido (ej.: 100MB)."; return; }
    q.set("size", size);
  }
  q.set("mode", $("#f-mode").value);
  q.set("workers", String(Math.max(0, Math.floor(Number($("#f-workers").value) || 0))));
  q.set("chunk_mb", String(Math.min(512, Math.max(1, Math.floor(Number($("#f-chunk").value) || 32)))));
  q.set("pattern", pat);
  $("#run-btn").disabled = true;
  try {
    await api(`/run?${q}`);
    toast("Análisis iniciado");
    S.prevStatus = "running";
    poll();
  } catch (e) {
    err.textContent = e.message;
    $("#run-btn").disabled = false;
  }
}

function stepLabel(key, params) {
  if (key === "prepare") return params && params.source === "url" ? "Descargar genoma" : "Generar ADN";
  const [mode, w] = key.split(":");
  return mode === "sequential" ? "Secuencial (1 proceso)" : `Paralelo (${w} procesos)`;
}
function renderSteps() {
  const box = $("#steps");
  const state = S.state;
  if (!state || !state.started) { box.replaceChildren(emptyEl("Pulse «Ejecutar análisis» para comenzar.")); $("#progress-sub").textContent = "Sin ejecución en curso"; return; }
  const keys = Object.keys(state.steps || {});
  if (!keys.includes("prepare")) keys.unshift("prepare");
  const running = state.status === "running";
  if (running && state.params) {
    const m = state.params.mode;
    if ((m === "both" || m === "sequential" || m === "benchmark") && !keys.some((k) => k.startsWith("sequential"))) keys.push("sequential:1");
    if ((m === "both" || m === "parallel") && !keys.some((k) => k.startsWith("parallel"))) keys.push(`parallel:${state.params.workers === "0" ? (S.info ? S.info.environment.cpu_count : "N") : state.params.workers}`);
  }
  const cur = state.progress && state.progress.label;
  box.replaceChildren(...keys.map((k, i) => {
    const pct = state.steps[k];
    const done = isNum(pct) && pct >= 100;
    const active = running && !done && ((k === "prepare" && ["prepare", "download", "generate"].includes(state.phase)) || (cur && k.startsWith(cur) && state.progress.workers == k.split(":")[1]));
    let extra = "";
    if (k === "prepare" && active && state.progress && state.progress.label === "download") {
      extra = ` · ${nf(state.progress.mb, 0)} MB a ${nf(state.progress.speed, 1)} MB/s`;
    }
    return h("div", { class: `step${done ? " done" : active ? " active" : ""}` },
      h("span", { class: "badge", html: done ? iconSVG("check", 14) : "" }, done ? null : String(i + 1)),
      h("span", { class: "name" }, stepLabel(k, state.params), h("span", { class: "muted", style: { fontWeight: 400 } }, extra)),
      h("span", { class: "pct" }, isNum(pct) ? `${nf(pct, 0)} %` : active ? "…" : "—"),
      h("div", { class: `progress${active && !isNum(pct) ? " indeterminate" : ""}` }, h("span", { style: { width: `${isNum(pct) ? pct : 0}%` } })));
  }));
  $("#progress-sub").textContent = running ? (PHASES[state.phase] || "Trabajando…") :
    state.status === "error" ? `Error: ${state.error || ""}` : `Terminado · ${fmtSecs(state.seconds)}`;
  const btn = $("#run-btn");
  if (btn) btn.disabled = running;
}

const IUPAC = { R: "A o G", Y: "C o T", S: "G o C", W: "A o T", K: "G o T", M: "A o C", B: "C, G o T", D: "A, G o T", H: "A, C o T", V: "A, C o G", U: "Uracilo (ARN)" };
function renderAdnResults() {
  const r = currentResult();
  const stats = $("#adn-stats");
  if (!r) {
    stats.replaceChildren();
    $("#composition").replaceChildren(emptyEl("Sin resultados todavía"));
    $("#gc-card").replaceChildren(emptyEl("Contenido GC"));
    $("#invalid-card").replaceChildren(emptyEl("Caracteres inválidos"));
    return;
  }
  const res = r.result, len = res.length || 1;
  stats.replaceChildren(
    kpiTile({ label: "Tamaño del archivo", iconName: "file", value: fmtBytes(r.input.size_bytes), foot: r.input.file }),
    kpiTile({ label: "Bloques", iconName: "layers", value: nf(r.input.chunks), foot: `de ${nf(r.input.chunk_mb)} MB cada uno` }),
    kpiTile({ label: "Secuencias", iconName: "dna", value: nf(res.records), foot: "registros FASTA (cromosomas, scaffolds…)" }),
    kpiTile({ label: "Longitud", iconName: "ruler", value: nf(len / 1e9, 3), unit: "Gb", foot: `${nf(len)} bases` }),
    kpiTile({ label: "Coincidencias del patrón", iconName: "search", value: nf(res.pattern_hits), foot: `Patrón ${r.input.pattern}` }),
  );

  const rows = [["A", res.A, "var(--s1)"], ["C", res.C, "var(--s2)"], ["G", res.G, "var(--s3)"], ["T", res.T, "var(--s4)"], ["N", res.N, "var(--neutral-mark)"]];
  const maxPct = Math.max(...rows.map(([, v]) => v / len * 100));
  const comp = $("#composition");
  comp.replaceChildren(...rows.map(([b, v, color]) => {
    const pct = v / len * 100;
    const row = h("div", { class: "base-row", tabindex: 0 },
      h("span", { class: "letter", style: { color: b === "N" ? "var(--muted)" : color } }, b),
      h("div", { class: "track" }, h("div", { class: "fill", style: { width: `${(pct / maxPct) * 100}%`, background: color } })),
      h("div", { class: "nums" }, h("b", {}, `${nf(pct, 2)} %`), " ", h("span", { class: "muted" }, nf(v))));
    const name = b === "N" ? "N (indeterminada)" : `Base ${b}`;
    row.addEventListener("pointermove", (e) => showTip(e, name, [{ name: "Cantidad", value: nf(v), color }, { name: "Porcentaje", value: `${nf(pct, 3)} %`, color }]));
    row.addEventListener("pointerleave", hideTip);
    return row;
  }), h("p", { class: "muted", style: { margin: "12px 0 0" } },
    `Minúsculas (regiones repetitivas enmascaradas): ${nf(res.lowercase)} bases · ${nf((res.lowercase || 0) / len * 100, 2)} %`));

  const gc = r.summary.gc_content_pct;
  const at = res.A + res.T, cg = res.C + res.G;
  const chA = at ? Math.abs(res.A - res.T) / at * 100 : 0, chC = cg ? Math.abs(res.C - res.G) / cg * 100 : 0;
  $("#gc-card").replaceChildren(
    h("div", { class: "card-head" }, h("div", {}, h("h2", { class: "card-title" }, "Contenido GC"), h("p", { class: "card-sub" }, "(G + C) / (A + C + G + T)"))),
    h("div", { class: "kpi" }, h("div", { class: "value num" }, nf(gc, 2), h("small", {}, "%"))),
    h("div", { class: "progress", style: { height: "10px", margin: "12px 0" }, title: `GC ${nf(gc, 2)} %` }, h("span", { style: { width: `${gc}%`, background: "var(--s2)" } })),
    h("p", { class: "muted", style: { margin: 0 } }, "El genoma humano tiene alrededor de 41 % de GC."),
    integrityLine(chA < 1 && chC < 1, `Regla de Chargaff: A≈T (dif. ${nf(chA, 2)} %) · C≈G (dif. ${nf(chC, 2)} %)`),
  );

  const det = Object.entries(res.invalid_detail || {}).sort((a, b) => b[1] - a[1]);
  $("#invalid-card").replaceChildren(
    h("div", { class: "card-head" }, h("div", {}, h("h2", { class: "card-title" }, "Caracteres inválidos"),
      h("p", { class: "card-sub" }, `${nf(res.invalid)} en total · todo lo que no es A, C, G, T ni N`))),
    det.length ? h("div", { class: "table-wrap" }, h("table", {},
      h("thead", {}, h("tr", {}, h("th", {}, "Código"), h("th", {}, "Cantidad"), h("th", {}, "Significado IUPAC"))),
      h("tbody", {}, det.slice(0, 12).map(([c, n]) => h("tr", {}, h("td", { class: "mono" }, c), h("td", {}, nf(n)), h("td", {}, IUPAC[c] || "No es código IUPAC")))))) :
      integrityLine(true, "Sin caracteres inválidos"),
  );
}

function renderAdn() {
  if (!formBuilt) buildForm();
  renderSteps();
  renderAdnResults();
}

/* ---------- 3. Rendimiento ---------- */
function resultLabel(r) {
  return `${providerLabel(r.environment.cloud_provider)} · ${fmtDate(r.environment.timestamp_utc)} · ${fmtBytes(r.input.size_bytes)}`;
}
function renderPerf() {
  const list = allResults().slice().reverse();
  const sel = $("#perf-select");
  const cur = currentResult();
  if (!S.perfKey || !list.some((r) => resultKey(r) === S.perfKey)) S.perfKey = cur ? resultKey(cur) : null;
  sel.replaceChildren(...(list.length ? list.map((r) => h("option", { value: resultKey(r), selected: resultKey(r) === S.perfKey }, resultLabel(r))) : [h("option", {}, "Sin resultados")]));
  sel.onchange = () => { S.perfKey = sel.value; renderPerf(); };
  const r = list.find((x) => resultKey(x) === S.perfKey);
  const seq = seqRun(r), par = parRun(r);
  $("#perf-kpis").replaceChildren(
    kpiTile({ label: "Speedup", iconName: "trend", value: par ? nf(par.speedup, 2) : "—", unit: par ? "×" : "", foot: par ? `con ${nf(par.workers)} procesos` : "Requiere modo paralelo" }),
    kpiTile({ label: "Eficiencia", iconName: "gauge", value: par ? nf(par.efficiency * 100, 1) : "—", unit: par ? "%" : "", foot: "Speedup ÷ procesos" }),
    kpiTile({ label: "Tiempo secuencial", iconName: "clock", value: seq ? nf(seq.seconds, 2) : "—", unit: seq ? "s" : "", foot: seq ? `${nf(seq.throughput_mb_s, 1)} MB/s` : "" }),
    kpiTile({ label: "Tiempo paralelo", iconName: "zap", value: par ? nf(par.seconds, 2) : "—", unit: par ? "s" : "", foot: par ? `${nf(par.throughput_mb_s, 1)} MB/s` : "" }),
    kpiTile({ label: "Ahorro de tiempo", iconName: "percent", value: seq && par ? nf((1 - par.seconds / seq.seconds) * 100, 1) : "—", unit: seq && par ? "%" : "",
      foot: seq && par ? `${fmtSecs(seq.seconds - par.seconds)} menos` : "" }),
  );
  if (!r) {
    ["#chart-times", "#chart-speedup", "#chart-throughput", "#amdahl-card", "#runs-table"].forEach((s) => $(s).replaceChildren(emptyEl("Sin resultados todavía")));
    return;
  }
  const runs = r.runs.slice().sort((a, b) => (a.mode === "sequential" ? -1 : b.mode === "sequential" ? 1 : a.workers - b.workers));
  const cats = runs.map((x) => (x.mode === "sequential" ? "Secuencial" : `${x.workers} proc.`));
  barChart($("#chart-times"), {
    categories: cats, label: "Tiempo por modo",
    series: [{ name: "Tiempo", color: "var(--s1)", values: runs.map((x) => x.seconds) }],
    barColors: runs.map((x) => (x.mode === "sequential" ? "var(--s1)" : "var(--s2)")),
    fmt: (v, axis) => (axis ? nf(v, v % 1 ? 1 : 0) : `${nf(v, v < 10 ? 2 : 1)} s`),
  });
  // leyenda explícita: el color codifica el modo
  $("#chart-times").prepend(legendEl([{ name: "Secuencial", color: "var(--s1)" }, { name: "Paralelo", color: "var(--s2)" }]));

  const points = new Map([[1, 1]]);
  runs.forEach((x) => { if (x.mode === "parallel") points.set(x.workers, x.speedup); });
  const xs = Array.from(points.keys()).sort((a, b) => a - b);
  lineChart($("#chart-speedup"), {
    xs, xName: "Procesos", xLabel: "Procesos", label: "Speedup",
    series: [{ name: "Speedup medido", color: "var(--s1)", values: xs.map((x) => points.get(x)) },
      { name: "Ideal (lineal)", dashed: true, values: xs }],
    fmt: (v) => `${nf(v, 2)}×`,
    empty: "Ejecute en modo «Secuencial + paralelo» o «Benchmark»",
  });
  if (xs.length <= 2) $("#chart-speedup").append(h("p", { class: "muted", style: { margin: "8px 0 0" } }, "Use el modo Benchmark para obtener la curva completa (1, 2, 4, 8… procesos)."));

  barChart($("#chart-throughput"), {
    categories: cats, label: "MB/s",
    series: [{ name: "Velocidad", color: "var(--s1)", values: runs.map((x) => x.throughput_mb_s) }],
    fmt: (v, axis) => (axis ? nf(v) : `${nf(v, 1)} MB/s`),
  });

  // Karp-Flatt: fracción serial experimental e = (1/S - 1/p) / (1 - 1/p)
  const card = $("#amdahl-card");
  if (par && par.workers > 1 && par.speedup > 0) {
    const p = par.workers, S_ = par.speedup;
    const e = (1 / S_ - 1 / p) / (1 - 1 / p);
    const maxS = e > 0 ? 1 / e : Infinity;
    card.replaceChildren(
      h("div", { class: "card-head" }, h("div", {}, h("h2", { class: "card-title" }, "Ley de Amdahl"), h("p", { class: "card-sub" }, "Fracción serial estimada (Karp–Flatt)"))),
      h("div", { class: "grid halves" },
        h("div", { class: "kpi" }, h("div", { class: "label" }, "Fracción serial"), h("div", { class: "value num" }, nf(e * 100, 1), h("small", {}, "%"))),
        h("div", { class: "kpi" }, h("div", { class: "label" }, "Speedup máximo teórico"), h("div", { class: "value num" }, isFinite(maxS) ? nf(maxS, 1) : "∞", h("small", {}, "×")))),
      h("p", { class: "note", style: { marginTop: "14px" } },
        `Con ${nf(p)} procesos se logró ${nf(S_, 2)}× en lugar de ${nf(p)}×. Aproximadamente el ${nf(e * 100, 1)} % del trabajo se comporta como serial ` +
        "(lectura del disco, creación de procesos, unión de resultados, núcleos lógicos que comparten un núcleo físico). Por eso, aunque se agreguen más núcleos, " +
        `el speedup no superaría ~${isFinite(maxS) ? nf(maxS, 1) : "∞"}×.`));
  } else {
    card.replaceChildren(h("div", { class: "card-head" }, h("h2", { class: "card-title" }, "Ley de Amdahl")), emptyEl("Necesita una ejecución en paralelo con 2 o más procesos."));
  }

  $("#runs-table").replaceChildren(h("table", {},
    h("thead", {}, h("tr", {}, ["Modo", "Procesos", "Tiempo", "MB/s", "Speedup", "Eficiencia"].map((t) => h("th", {}, t)))),
    h("tbody", {}, runs.map((x) => h("tr", {},
      h("td", {}, h("span", { class: "swatch", style: { background: x.mode === "sequential" ? "var(--s1)" : "var(--s2)" } }), x.mode === "sequential" ? "Secuencial" : "Paralelo"),
      h("td", {}, nf(x.workers)), h("td", {}, fmtSecs(x.seconds)), h("td", {}, nf(x.throughput_mb_s, 1)),
      h("td", {}, `${nf(x.speedup, 2)}×`), h("td", {}, `${nf(x.efficiency * 100, 1)} %`))))));
}

/* ---------- 4. Multicloud ---------- */
const COUNT_KEYS = ["A", "C", "G", "T", "N", "invalid", "pattern_hits", "length", "records"];
function integrityChecks(latest) {
  const out = [];
  const withSha = latest.filter((r) => r.input.sha256);
  if (latest.length < 2) out.push({ state: "info", title: "Se necesitan al menos 2 nubes", text: "Importe los resultados de cada proveedor para comparar." });
  if (withSha.length >= 2) {
    const shas = new Set(withSha.map((r) => r.input.sha256));
    out.push(shas.size === 1
      ? { state: "ok", title: "Mismo archivo en todas las nubes", text: `SHA-256 ${shortHash(withSha[0].input.sha256)} en ${withSha.length} proveedores` }
      : { state: "bad", title: "Los archivos NO son iguales", text: `${shas.size} huellas SHA-256 distintas` });
  }
  const groups = new Map();
  latest.forEach((r) => { const k = r.input.size_bytes; groups.set(k, [...(groups.get(k) || []), r]); });
  for (const [size, rs] of groups) {
    if (rs.length < 2) continue;
    const ref = rs[0].result;
    const diff = rs.filter((r) => COUNT_KEYS.some((k) => r.result[k] !== ref[k]));
    out.push(diff.length
      ? { state: "bad", title: "Resultados diferentes", text: `${diff.map((r) => providerLabel(r.environment.cloud_provider)).join(", ")} no coinciden (${fmtBytes(size)})` }
      : { state: "ok", title: "Resultados idénticos: portabilidad comprobada", text: `${rs.length} nubes contaron exactamente las mismas bases (${fmtBytes(size)})` });
  }
  return out;
}

function mcRows(latest) {
  return latest.map((r) => {
    const env = r.environment, seq = seqRun(r), par = parRun(r);
    return {
      provider: env.cloud_provider, label: providerLabel(env.cloud_provider), model: providerModel(env.cloud_provider),
      origin: env.cloud_origin, region: env.cloud_region, instance: env.instance_type, cpu: env.cpu_model,
      cores: env.cpu_count, ram: env.ram_gb, arch: env.architecture, size: r.input.size_bytes,
      download: r.input.download_seconds, seq: seq && seq.seconds, par: par && par.seconds, workers: par ? par.workers : 1,
      speedup: par && par.speedup, eff: par && par.efficiency, mbs: (par || seq || {}).throughput_mb_s, sha: r.input.sha256,
      gc: r.summary.gc_content_pct, hits: r.result.pattern_hits, date: env.timestamp_utc,
    };
  });
}

function renderMulticloud() {
  const latest = latestByProvider();
  const rows = mcRows(latest);
  $("#import-count").textContent = `${rows.length} proveedor(es) · ${S.imported.length} JSON importado(s)`;
  $("#clear-imports").classList.toggle("hidden", !S.imported.length);

  $("#integrity").replaceChildren(...integrityChecks(latest).map((c) =>
    h("div", { class: `banner ${c.state === "ok" ? "ok" : c.state === "bad" ? "bad" : ""}` },
      h("span", { class: "b-icon", style: { color: c.state === "ok" ? "var(--good)" : c.state === "bad" ? "var(--critical)" : "var(--muted)" }, html: iconSVG(c.state === "ok" ? "check" : c.state === "bad" ? "x" : "cloud", 22) }),
      h("div", {}, h("div", { style: { fontWeight: 650 } }, c.title), h("div", { class: "muted" }, c.text)))));

  $("#provider-cards").replaceChildren(...(rows.length ? rows.map((x) => h("div", { class: "card provider-card" },
    h("div", { class: "head" },
      h("div", { class: "avatar", style: { background: providerColor(x.provider) } }, x.label.slice(0, 1).toUpperCase()),
      h("div", { style: { minWidth: 0 } }, h("div", { class: "name" }, x.label), h("div", { class: "muted", style: { fontSize: "12.5px" } }, `${x.origin} · ${x.region}`)),
      h("span", { class: "tag", style: { marginLeft: "auto" } }, x.model)),
    kvList([
      ["CPU", h("span", { title: x.cpu }, cleanCpu(x.cpu))], ["Núcleos", nf(x.cores)], ["RAM", isNum(x.ram) ? `${nf(x.ram, 1)} GB` : "—"], ["Arquitectura", x.arch],
      ["Tiempo paralelo", fmtSecs(x.par)], ["Velocidad", isNum(x.mbs) ? `${nf(x.mbs, 1)} MB/s` : "—"],
    ]))) : [emptyEl("Aún no hay resultados de nubes. Importe los JSON o ejecute los scripts de despliegue.")]));

  const cats = rows.map((x) => x.label);
  barChart($("#chart-mc-times"), {
    categories: cats, label: "Tiempo por proveedor",
    series: [{ name: "Secuencial", color: "var(--s1)", values: rows.map((x) => x.seq) }, { name: "Paralelo", color: "var(--s2)", values: rows.map((x) => x.par) }],
    fmt: (v, axis) => (axis ? nf(v) : fmtSecs(v)),
  });
  barChart($("#chart-mc-throughput"), {
    categories: cats, label: "MB/s por proveedor",
    series: [{ name: "MB/s", color: "var(--s1)", values: rows.map((x) => x.mbs) }],
    barColors: rows.map((x) => providerColor(x.provider)), fmt: (v, axis) => (axis ? nf(v) : `${nf(v, 1)} MB/s`),
  });
  barChart($("#chart-mc-speedup"), {
    categories: cats, label: "Speedup por proveedor",
    series: [{ name: "Speedup", color: "var(--s1)", values: rows.map((x) => x.speedup) }],
    barColors: rows.map((x) => providerColor(x.provider)), fmt: (v, axis) => (axis ? nf(v, v % 1 ? 1 : 0) : `${nf(v, 2)}×`),
  });
  const dl = rows.filter((x) => isNum(x.download));
  barChart($("#chart-mc-download"), {
    categories: dl.map((x) => x.label), label: "Descarga del genoma",
    series: [{ name: "Descarga", color: "var(--s1)", values: dl.map((x) => x.download) }],
    barColors: dl.map((x) => providerColor(x.provider)), fmt: (v, axis) => (axis ? nf(v) : fmtSecs(v)),
    empty: "Disponible cuando cada nube descarga el genoma con DNA_URL",
  });

  const cols = [
    ["Proveedor", (x) => h("span", {}, h("span", { class: "swatch", style: { background: providerColor(x.provider) } }), x.label)],
    ["Modelo", (x) => x.model], ["Origen", (x) => x.origin], ["Región", (x) => x.region], ["Instancia", (x) => x.instance],
    ["CPU", (x) => cleanCpu(x.cpu)], ["Núcleos", (x) => nf(x.cores)], ["RAM (GB)", (x) => nf(x.ram, 1)], ["Arq.", (x) => x.arch],
    ["Archivo", (x) => fmtBytes(x.size)], ["Descarga", (x) => fmtSecs(x.download)], ["Secuencial", (x) => fmtSecs(x.seq)],
    ["Paralelo", (x) => fmtSecs(x.par)], ["Procesos", (x) => nf(x.workers)], ["Speedup", (x) => (isNum(x.speedup) ? `${nf(x.speedup, 2)}×` : "—")],
    ["Eficiencia", (x) => (isNum(x.eff) ? `${nf(x.eff * 100, 1)} %` : "—")], ["MB/s", (x) => nf(x.mbs, 1)],
    ["GC %", (x) => nf(x.gc, 3)], ["Patrón", (x) => nf(x.hits)], ["SHA-256", (x) => h("span", { class: "mono", title: x.sha || "" }, shortHash(x.sha))],
  ];
  $("#mc-table").replaceChildren(rows.length ? h("table", {},
    h("thead", {}, h("tr", {}, cols.map(([t]) => h("th", {}, t)))),
    h("tbody", {}, rows.map((x) => h("tr", {}, cols.map(([, f]) => h("td", {}, f(x))))))) : emptyEl("Sin datos"));
}

function exportCsv() {
  const rows = mcRows(latestByProvider());
  if (!rows.length) { toast("No hay datos para exportar"); return; }
  const head = ["proveedor", "modelo", "origen", "region", "instancia", "cpu", "nucleos", "ram_gb", "arquitectura", "archivo_bytes",
    "descarga_s", "secuencial_s", "paralelo_s", "procesos", "speedup", "eficiencia", "mb_s", "gc_pct", "patron", "sha256", "fecha_utc"];
  const val = (x) => [x.label, x.model, x.origin, x.region, x.instance, x.cpu, x.cores, x.ram, x.arch, x.size, x.download, x.seq, x.par,
    x.workers, x.speedup, x.eff, x.mbs, x.gc, x.hits, x.sha, x.date];
  const esc = (v) => (v == null ? "" : /[",\n]/.test(String(v)) ? `"${String(v).replace(/"/g, '""')}"` : String(v));
  const csv = [head, ...rows.map(val)].map((r) => r.map(esc).join(",")).join("\n");
  const a = h("a", { href: URL.createObjectURL(new Blob([csv], { type: "text/csv" })), download: "comparacion_nubes.csv" });
  document.body.append(a); a.click(); a.remove();
}

async function importFiles(files) {
  let ok = 0, bad = 0;
  for (const f of files) {
    try {
      const data = JSON.parse(await f.text());
      if (!validResult(data)) throw new Error("formato");
      delete data._file;
      S.imported.push(data); ok++;
    } catch (e) { bad++; }
  }
  const map = new Map(S.imported.map((r) => [resultKey(r), r]));
  S.imported = Array.from(map.values());
  store.set("adn-imported", S.imported);
  toast(`${ok} resultado(s) importado(s)${bad ? ` · ${bad} archivo(s) no válidos` : ""}`);
  renderAll();
}

/* ============================================================ ENRUTADO */
function setView(name) {
  if (!VIEWS[name]) name = "panel";
  S.view = name;
  $$("[data-section]").forEach((s) => s.classList.toggle("hidden", s.dataset.section !== name));
  $$(".nav a").forEach((a) => { a.classList.toggle("active", a.dataset.view === name); a.setAttribute("aria-current", a.dataset.view === name ? "page" : "false"); });
  const v = VIEWS[name];
  $("#page-title").textContent = v.title;
  $("#page-sub").textContent = v.sub;
  $("#page-icon").innerHTML = iconSVG(v.icon, 20);
  $("#top-run").classList.toggle("hidden", name === "adn");
  hideTip();
  renderView();
}
function renderView() {
  ({ panel: renderPanel, adn: renderAdn, rendimiento: renderPerf, multicloud: renderMulticloud })[S.view]();
}
function renderAll() { renderChrome(); renderView(); }
/** Actualización liviana durante el sondeo (sin redibujar gráficos). */
function renderLive() {
  renderChrome();
  if (S.view === "panel") { renderStatusCard(); renderLog(); }
  if (S.view === "adn") renderSteps();
}

/* ============================================================ INICIO */
async function init() {
  applyIcons();
  $("#theme-btn").addEventListener("click", () => {
    const next = document.documentElement.dataset.theme === "light" ? "dark" : "light";
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem("adn-theme", next); } catch (e) { /* sin almacenamiento */ }
  });
  const dz = $("#dropzone"), fi = $("#file-input");
  fi.addEventListener("change", () => { importFiles(Array.from(fi.files)); fi.value = ""; });
  ["dragenter", "dragover"].forEach((t) => dz.addEventListener(t, (e) => { e.preventDefault(); dz.classList.add("drag"); }));
  ["dragleave", "drop"].forEach((t) => dz.addEventListener(t, (e) => { e.preventDefault(); dz.classList.remove("drag"); }));
  dz.addEventListener("drop", (e) => importFiles(Array.from(e.dataTransfer.files)));
  $("#clear-imports").addEventListener("click", () => { S.imported = []; store.set("adn-imported", []); renderAll(); });
  $("#export-csv").addEventListener("click", exportCsv);
  addEventListener("hashchange", () => setView(location.hash.slice(1)));
  let rt;
  new ResizeObserver(() => { clearTimeout(rt); rt = setTimeout(() => { if (["rendimiento", "multicloud", "adn"].includes(S.view)) renderView(); }, 150); }).observe($(".main"));

  try { await Promise.all([loadInfo(), loadResults()]); } catch (e) { S.online = false; }
  setView(location.hash.slice(1) || "panel");
  poll();
}
init();
