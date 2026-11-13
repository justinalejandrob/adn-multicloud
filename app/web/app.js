/* =============================================================================
   ADN Multinube - Dashboard (JavaScript sin dependencias)
   Base común: íconos, utilidades, gráficos, estado y enrutado.
   Las secciones están en secciones.js, evaluacion.js y cluster.js.
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
  network: '<rect x="9" y="2" width="6" height="5" rx="1"/><rect x="2" y="17" width="6" height="5" rx="1"/><rect x="16" y="17" width="6" height="5" rx="1"/><path d="M12 7v5M5 17v-2.5h14V17M12 12v2.5"/>',
  trash: '<path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13"/>',
  stop: '<rect x="6" y="6" width="12" height="12" rx="2" fill="currentColor" stroke="none"/>',
  clipboard: '<rect x="5" y="4" width="14" height="17" rx="2"/><path d="M9 4V2.5h6V4"/><path d="M8.5 10.5l2 2 4-4M8.5 16.5h7"/>',
  shield: '<path d="M12 3l8 3v6c0 4.5-3.4 8.2-8 9-4.6-.8-8-4.5-8-9V6z"/><path d="M8.5 12l2.5 2.5 4.5-4.5"/>',
  globe: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c3 3.2 3 14.8 0 18M12 3c-3 3.2-3 14.8 0 18"/>',
  dollar: '<path d="M12 2v20M17 6.5c-1-1.5-3-2-5-2-3 0-4.5 1.5-4.5 3.5 0 4.5 10 2.5 10 7.5 0 2-2 3.5-5 3.5-2.5 0-4.5-1-5.5-2.5"/>',
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
  ovhcloud: { label: "OVHcloud", model: "IaaS", flag: "Francia" },
  ovh: { label: "OVHcloud", model: "IaaS", flag: "Francia" },
  hetzner: { label: "Hetzner", model: "IaaS", flag: "Alemania" },
  scaleway: { label: "Scaleway", model: "IaaS", flag: "Francia" },
  lightnode: { label: "LightNode", model: "IaaS", flag: "—" },
  donweb: { label: "DonWeb", model: "IaaS", flag: "Argentina" },
  telecu: { label: "Telecu Cloud", model: "IaaS", flag: "Ecuador" },
};
const PROVIDER_ORDER = ["aws", "azure", "ovhcloud", "ovh", "alibaba", "huawei", "donweb", "guaracloud", "magalu", "telecu", "claro", "hetzner", "scaleway", "local"];
const providerLabel = (p) => (PROVIDERS[p] && PROVIDERS[p].label) || p;
const providerModel = (p) => (PROVIDERS[p] && PROVIDERS[p].model) || "IaaS";
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
  const ymax = niceMax(Math.max(...values, opts.ref ? opts.ref.value : 0) * 1.08);
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
      if (showLabels && fmt(v).length * 6.6 <= band / n + gap) root.append(svg("text", { x: x + bw / 2, y: top - 6, "text-anchor": "middle", class: "value-label", text: fmt(v) }));
      root.append(hit);
    });
    const label = cat.length > 18 ? `${cat.slice(0, 17)}…` : cat;
    root.append(svg("text", { x: m.l + band * ci + band / 2, y: H - 12, "text-anchor": "middle", text: label }));
  });
  if (opts.ref) {   // línea de referencia (p. ej. el límite de 15 ms de un SLA)
    const yy = y(opts.ref.value);
    root.append(svg("line", { x1: m.l, x2: W - m.r, y1: yy, y2: yy, "stroke-width": 1.5, "stroke-dasharray": "6 4", style: { stroke: "var(--ink-2)" } }));
    root.append(svg("text", { x: W - m.r, y: yy - 6, "text-anchor": "end", class: "value-label", text: opts.ref.label }));
  }
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

/* ============================================================== ESTADO Y SONDEO */
/*
 * Todas las secciones leen el MISMO estado del clúster (/api/cluster/estado, guardado
 * en etcd) y los resultados de la Evaluación S11 (/api/eval). No hay datos locales:
 * lo que se ve es lo que pasó en las 5 nubes.
 */
const S = { view: "panel", online: true, ev: null, sig: {}, timer: null };
const VIEWS = {
  panel: { title: "Panel principal", sub: "Resumen del clúster de 5 nubes en tiempo real", icon: "grid" },
  adn: { title: "Procesamiento ADN", sub: "Qué encontró el clúster en el genoma y cómo se repartió el trabajo", icon: "dna" },
  rendimiento: { title: "Rendimiento", sub: "Tiempos, speedup, escalabilidad y tamaño de fragmento", icon: "gauge" },
  multicloud: { title: "Multicloud", sub: "Comparación de los 5 proveedores con datos medidos", icon: "cloud" },
  evaluacion: { title: "Evaluación S11", sub: "Las 8 preguntas resueltas con experimentos en nuestras 5 nubes", icon: "clipboard" },
  cluster: { title: "Clúster", sub: "5 nubes · líder elegido con etcd · red privada WireGuard", icon: "network" },
};
const NOMBRE_NUBE = { usa: "USA", europa: "Europa", china: "China", latam: "Latam", ecuador: "Ecuador" };
const nube = (n) => NOMBRE_NUBE[n] || String(n || "").toUpperCase();

async function api(path) {
  const res = await fetch(path, { headers: { Accept: "application/json" }, cache: "no-store" });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) { const e = new Error(body.error || res.statusText); e.status = res.status; throw e; }
  return body;
}
async function apiPost(path, body) {
  const res = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json", Accept: "application/json" }, body: JSON.stringify(body || {}) });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || res.statusText);
  return data;
}
const evRunning = () => Object.values((S.ev && S.ev.resultados) || {}).some((v) => v && (v.estado === "corriendo" || v.estado === "en cola"));
const jobRunning = () => !!(CL.data && CL.data.trabajo && CL.data.trabajo.estado === "running");

async function pollGlobal() {
  clearTimeout(S.timer);
  try {
    if (S.view !== "cluster") CL.data = await api("/api/cluster/estado");
    if (S.view !== "cluster" || !S.ev) S.ev = await api("/api/eval");
    S.online = true;
  } catch (e) {
    S.online = false;
  }
  renderChrome();
  if (S.view !== "cluster") renderView(false);
  S.timer = setTimeout(pollGlobal, evRunning() || jobRunning() ? 1500 : 3500);
}

/* ---------- barra superior y lateral ---------- */
function renderChrome() {
  const d = CL.data;
  const via = d && d.nodos ? d.nodos.find((n) => n.nombre === d.conectado_via) : null;
  $("#side-provider").textContent = via ? providerLabel(via.provider) : (d && d.conectado_via ? nube(d.conectado_via) : "…");
  $("#side-region").textContent = via ? `${via.pais} · ${via.region}` : "";
  let st = "idle", text = "En espera";
  if (!S.online || !d || d.modo !== "etcd") { st = "offline"; text = "Sin conexión"; }
  else if (jobRunning()) {
    const j = d.trabajo, p = j.progreso || {};
    st = "running"; text = `Analizando · ${nf(p.hechos || 0)}/${nf(j.fragmentos_total || 0)}`;
  } else if (evRunning()) {
    const q = Object.entries(S.ev.resultados).find(([, v]) => v && v.estado === "corriendo");
    st = "running"; text = q ? `Evaluando ${q[0] === "escalabilidad" ? "escalabilidad" : q[0].toUpperCase()}` : "Evaluación en cola";
  }
  $("#status-pill").className = `pill ${st}`;
  $("#status-pill-text").textContent = text;
}

/* ---------- utilidades compartidas por las secciones ---------- */
function changed(view, data) {
  const sig = JSON.stringify(data);
  if (S.sig[view] === sig) return false;
  S.sig[view] = sig;
  return true;
}
function cardEl(title, sub, ...body) {
  return h("div", { class: "card" },
    h("div", { class: "card-head" }, h("div", {}, h("h2", { class: "card-title" }, title), sub ? h("p", { class: "card-sub" }, sub) : null)),
    ...body);
}
function tableEl(cols, rows) {
  return h("div", { class: "table-wrap" }, h("table", {},
    h("thead", {}, h("tr", {}, cols.map((c) => h("th", {}, c)))),
    h("tbody", {}, rows.map((r) => h("tr", {}, r.map((c) => h("td", {}, c ?? "—")))))));
}
function dot(color) { return h("span", { class: "swatch", style: { background: color } }); }
function offlineBanner(root) {
  root.replaceChildren(h("div", { class: "banner bad" },
    h("span", { class: "b-icon", style: { color: "var(--critical)" }, html: iconSVG("alert", 22) }),
    h("div", {}, h("div", { style: { fontWeight: 650 } }, "Sin conexión con el clúster"),
      h("div", { class: "muted" }, (CL.data && CL.data.mensaje) || "Abra el túnel SSH (conectar.sh) y recargue la página."))));
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
  $("#top-run").classList.toggle("hidden", name === "cluster");
  hideTip();
  clusterVisible(name === "cluster");
  renderView(true);
  pollGlobal();
}
function renderView(force) {
  if (S.view === "cluster") { renderCluster(); return; }
  if (force) S.sig[S.view] = null;
  ({ panel: renderPanel, adn: renderAdn, rendimiento: renderPerf, multicloud: renderMulticloud, evaluacion: renderEvaluacion })[S.view]();
}

/* ============================================================ INICIO */
function init() {
  applyIcons();
  $("#theme-btn").addEventListener("click", () => {
    const next = document.documentElement.dataset.theme === "light" ? "dark" : "light";
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem("adn-theme", next); } catch (e) { /* sin almacenamiento */ }
    renderView(true);
  });
  addEventListener("hashchange", () => setView(location.hash.slice(1)));
  let rt, lastW = 0;
  new ResizeObserver((entries) => {
    const w = Math.round(entries[0].contentRect.width);
    if (Math.abs(w - lastW) < 8) return;
    lastW = w;
    clearTimeout(rt); rt = setTimeout(() => renderView(true), 150);
  }).observe($(".main"));
  setView(location.hash.slice(1) || "panel");
}
init();
