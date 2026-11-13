/* =============================================================================
   ADN Multinube - Sección «Clúster» (líder elegido con etcd, 5 nubes, WireGuard)
   Solo DEFINE funciones; las ejecuta app.js (que provee h, nf, barChart, ...).
   ============================================================================= */
"use strict";

const CL = { data: null, timer: null, visible: false, tab: "comparacion", advBuilt: false, tabSig: "", busy: false };
const NODE_COLORS = { usa: "var(--s1)", china: "var(--s2)", latam: "var(--s3)", ecuador: "var(--s4)", europa: "var(--s5)" };
const nodeColor = (n) => NODE_COLORS[n] || "var(--neutral-mark)";
const GB = (b) => (isNum(b) ? b / 1e9 : null);
const up = (s) => String(s || "").toUpperCase();

async function clPost(path, body) {
  const res = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json", Accept: "application/json" }, body: JSON.stringify(body || {}) });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || res.statusText);
  return data;
}
async function clAction(path, body, okMsg) {
  try { const r = await clPost(path, body); toast(okMsg || r.mensaje || "Listo"); clPoll(); } catch (e) { toast(`Error: ${e.message}`); }
}

function clusterVisible(on) {
  CL.visible = on;
  clearTimeout(CL.timer);
  if (on) clPoll();
}

async function clPoll() {
  clearTimeout(CL.timer);
  try {
    const prev = CL.data && CL.data.trabajo && CL.data.trabajo.estado;
    CL.data = await api("/api/cluster/estado");
    const job = CL.data.trabajo || {};
    if (prev === "running" && job.estado && job.estado !== "running") toast(job.estado === "done" ? "Análisis terminado" : `Trabajo ${job.estado}`);
    if (CL.visible) renderCluster();
  } catch (e) {
    if (CL.visible) $("#cl-setup").replaceChildren(h("div", { class: "banner bad", style: { marginBottom: "16px" } }, "No se puede leer el clúster: ", e.message));
  }
  if (CL.visible) {
    const running = CL.data && (CL.data.trabajo || {}).estado === "running";
    CL.timer = setTimeout(clPoll, running ? 900 : 2500);
  }
}

/* estado efectivo de un nodo: viva / apagada / caida (sin latido reciente) */
function nodeState(n, now) {
  if (n.estado === "caida") return "caida";
  if (n.apagado_flag || n.estado === "apagada") return "apagada";
  if (isNum(n.visto) && now - n.visto > 7) return "caida";
  return "viva";
}
const STATE_UI = { viva: ["VIVA", "var(--good-ink)"], apagada: ["APAGADA", "var(--warning)"], caida: ["CAÍDA", "var(--critical)"] };

/* ================================================================== render */
function renderCluster() {
  const d = CL.data;
  if (!d) { $("#cl-nodes").replaceChildren(emptyEl("Conectando con el clúster…")); clPoll(); return; }
  if (d.modo !== "etcd") {
    $("#cl-setup").replaceChildren(h("div", { class: "banner bad", style: { marginBottom: "16px" } },
      h("span", { class: "b-icon", style: { color: "var(--critical)" }, html: iconSVG("alert", 22) }),
      h("div", {}, h("div", { style: { fontWeight: 650 } }, "Clúster sin conexión"), h("div", { class: "muted" }, d.mensaje || ""))));
    return;
  }
  $("#cl-setup").replaceChildren();
  renderClBar(d);
  renderClNodes(d);
  renderClFrags(d);
  renderClTab(d);
}

/* ------------------------------------------------------------ barra de mando */
function selectedFiles() {
  const box = $("#cl-files");
  return box ? $$("input:checked", box).map((i) => i.value) : [];
}
function fileCatalog(d) {
  // archivos listos en las nubes vivas (y en cuántas)
  const now = d.ahora, cat = new Map();
  const alive = d.nodos.filter((n) => nodeState(n, now) === "viva");
  for (const n of alive) for (const f of n.archivos || []) {
    const c = cat.get(f.nombre) || { nombre: f.nombre, bytes: f.bytes, listos: 0, total: alive.length, sha: new Set() };
    if (f.listo) { c.listos += 1; c.sha.add(f.seq_sha256); }
    cat.set(f.nombre, c);
  }
  return Array.from(cat.values()).sort((a, b) => a.nombre.localeCompare(b.nombre));
}

function renderClBar(d) {
  const now = d.ahora, job = d.trabajo || {};
  const chip = (k, v, cls) => h("span", { class: "chip" }, h("span", { class: "k" }, k), h("span", { class: cls || "" }, v));
  $("#cl-status").replaceChildren(...[
    chip("Conectado vía", up(d.conectado_via)),
    chip("Líder del clúster", d.lider ? `★ ${up(d.lider)}` : "eligiéndose…", "gold"),
    chip("Líder de etcd (Raft)", up(d.etcd_lider) || "—"),
    chip("Miembros etcd", `${(d.etcd_miembros || []).length}`),
    d.ceder ? chip("Cediendo mando a", up(d.ceder), "gold") : null,
    d.comandos_pendientes ? chip("En cola", nf(d.comandos_pendientes)) : null,
    chip("Nubes vivas", `${d.nodos.filter((n) => nodeState(n, now) === "viva").length}/${d.nodos.length}`),
  ].filter(Boolean));
  if (!CL.advBuilt) buildClAdvanced(d);
  refreshClAdvanced(d);
  const sel = $("#cl-ceder-sel"), cur = sel.value;
  const sig = d.nodos.map((n) => n.nombre).join("|");
  if (sel.dataset.sig !== sig) {
    sel.dataset.sig = sig;
    sel.replaceChildren(h("option", { value: "" }, "(orden normal)"), ...d.nodos.map((n) => h("option", { value: n.nombre, selected: n.nombre === cur }, up(n.nombre))));
  }
  const files = selectedFiles(), cat = fileCatalog(d);
  const total = cat.filter((c) => files.includes(c.nombre)).reduce((a, c) => a + (c.bytes || 0), 0);
  $("#cl-run-label").textContent = total ? `Analizar ${nf(GB(total), 1)} GB` : "Analizar";
  const running = job.estado === "running";
  $("#cl-run").disabled = running;
  $("#cl-cancel").disabled = !running;
}

function buildClAdvanced(d) {
  const adv = $("#cl-adv");
  const field = (label, input, hint) => h("div", { class: "field" }, h("label", {}, label), input, hint ? h("span", { class: "hint" }, hint) : null);
  adv.replaceChildren(
    h("div", { class: "field", style: { gridColumn: "1 / -1" } }, h("label", {}, "Archivos a analizar (deben estar en todas las nubes)"), h("div", { id: "cl-files", style: { display: "flex", flexWrap: "wrap", gap: "6px 18px" } })),
    field("Operación", h("select", { id: "cl-modo" }, h("option", { value: "contar" }, "Contar bases + patrones"), h("option", { value: "comparar" }, "Comparar 2 archivos"))),
    field("Fragmento (MB)", h("input", { id: "cl-chunk", type: "number", min: 1, max: 512, value: 96 }), "La referencia usa ~96 MB"),
    field("Pedidos por nube", h("input", { id: "cl-hilos", type: "number", min: 0, max: 64, value: 0 }), "0 = uno por núcleo"),
    field("Soberanía de datos", h("select", { id: "cl-pais" }, h("option", { value: "" }, "Todas las nubes"), h("option", { value: "Ecuador" }, "Solo nubes en Ecuador"))),
    h("div", { class: "field", style: { gridColumn: "1 / -1" } }, h("label", {}, "Nubes participantes"), h("div", { id: "cl-node-checks", style: { display: "flex", flexWrap: "wrap", gap: "6px 18px" } })),
    h("div", { class: "field", style: { gridColumn: "1 / -1", flexDirection: "row", gap: "20px", flexWrap: "wrap" } },
      h("label", { style: { display: "inline-flex", gap: "8px", alignItems: "center" } }, h("input", { type: "checkbox", id: "cl-verificar" }), "Verificar contra 1 núcleo (en el líder)"),
      h("label", { style: { display: "inline-flex", gap: "8px", alignItems: "center" } }, h("input", { type: "checkbox", id: "cl-solo-reparte" }), "El líder solo reparte (no calcula)")),
  );
  $("#cl-adv-btn").addEventListener("click", () => {
    const hidden = $("#cl-adv").classList.toggle("hidden");
    $("#cl-adv-btn").setAttribute("aria-expanded", String(!hidden));
  });
  $("#cl-form").onsubmit = submitClJob;
  $("#cl-cancel").addEventListener("click", () => clAction("/api/cluster/cancelar"));
  $("#cl-net-btn").addEventListener("click", () => clAction("/api/cluster/red", {}, "Todas las nubes miden la red…"));
  $("#cl-ceder").addEventListener("click", () => clAction("/api/cluster/ceder", { destino: $("#cl-ceder-sel").value }));
  $("#cl-adv").addEventListener("change", () => renderClBar(CL.data));
  $$("#cl-tabs button").forEach((b) => b.addEventListener("click", () => { CL.tab = b.dataset.tab; CL.tabSig = ""; renderClTab(CL.data); }));
  applyIcons($("#cl-bar"));
  CL.advBuilt = true;
}

function refreshClAdvanced(d) {
  const cat = fileCatalog(d), box = $("#cl-files");
  const sig = cat.map((c) => `${c.nombre}:${c.listos}/${c.total}`).join("|");
  if (box.dataset.sig !== sig) {
    const had = box.dataset.sig !== undefined;
    const prev = new Set(selectedFiles());
    box.dataset.sig = sig;
    box.replaceChildren(...(cat.length ? cat.map((c) => {
      const ok = c.listos === c.total && c.sha.size === 1;
      return h("label", { style: { display: "inline-flex", gap: "8px", alignItems: "center" }, title: ok ? "Lista en todas las nubes" : "No está lista (o es distinta) en todas las nubes" },
        h("input", { type: "checkbox", value: c.nombre, checked: had ? prev.has(c.nombre) : ok, disabled: !c.listos }),
        h("span", { class: "mono" }, c.nombre), h("span", { class: "muted" }, `${nf(GB(c.bytes), 2)} GB · ${c.listos}/${c.total} nubes${c.sha.size > 1 ? " · ¡copias distintas!" : ""}`));
    }) : [h("span", { class: "muted" }, "Ninguna nube tiene archivos FASTA. Use la pestaña «Datos en las nubes».")]));
  }
  const nb = $("#cl-node-checks"), nsig = d.nodos.map((n) => n.nombre).join("|");
  if (nb.dataset.sig !== nsig) {
    const off = new Set($$("input", nb).filter((i) => !i.checked).map((i) => i.value));
    nb.dataset.sig = nsig;
    nb.replaceChildren(...d.nodos.map((n) => h("label", { style: { display: "inline-flex", gap: "6px", alignItems: "center" } },
      h("input", { type: "checkbox", value: n.nombre, checked: !off.has(n.nombre) }), h("span", { class: "swatch", style: { background: nodeColor(n.nombre), margin: 0 } }), up(n.nombre))));
  }
}

async function submitClJob(ev) {
  ev.preventDefault();
  const files = selectedFiles();
  const pats = $("#cl-patrones").value.split(/[,;\s]+/).map((x) => x.trim().toUpperCase()).filter(Boolean);
  if (!files.length) { toast("Elija los archivos en «Opciones»"); $("#cl-adv").classList.remove("hidden"); return; }
  if (pats.some((p) => !/^[ACGTN]{1,64}$/.test(p))) { toast("Los patrones solo admiten A, C, G, T, N"); return; }
  const modo = $("#cl-modo").value;
  if (modo === "comparar" && files.length !== 2) { toast("Para comparar elija exactamente 2 archivos"); return; }
  await clAction("/api/cluster/ejecutar", {
    archivos: files, patrones: pats, modo, chunk_mb: Number($("#cl-chunk").value) || 96, max_hilos: Number($("#cl-hilos").value) || 0,
    solo_pais: $("#cl-pais").value || null, verificar: $("#cl-verificar").checked, lider_solo_reparte: $("#cl-solo-reparte").checked,
    nodos: $$("#cl-node-checks input").filter((i) => i.checked).map((i) => i.value),
  });
}

/* ------------------------------------------------------------ tarjetas */
function coreStrip(stats, color) {
  const cores = stats.nucleos || [];
  const busy = new Set((stats.procesos || []).filter((p) => p.cpu >= 20).map((p) => p.nucleo));
  return h("div", { style: { display: "flex", gap: "2px", alignItems: "flex-end", height: "22px", margin: "4px 0" }, "aria-label": "CPU por núcleo" },
    cores.map((v, i) => h("div", { title: `Núcleo ${i}: ${nf(v, 0)} %${busy.has(i) ? " · calculando ADN" : ""}`,
      style: { flex: 1, maxWidth: "18px", height: "100%", background: "var(--surface-2)", borderRadius: "2px", display: "flex", alignItems: "flex-end" } },
    h("div", { style: { width: "100%", height: `${Math.max(3, v)}%`, background: busy.has(i) ? color : "var(--neutral-mark)", borderRadius: "2px" } }))));
}

function renderClNodes(d) {
  const now = d.ahora;
  $("#cl-nodes").replaceChildren(...d.nodos.map((n) => {
    const st = nodeState(n, now), [stText, stColor] = STATE_UI[st];
    const color = nodeColor(n.nombre), s = n.stats || {};
    const ram = s.mem_total ? s.mem_usada / s.mem_total * 100 : null;
    const price = n.costo_hora > 0 ? `USD ${nf(n.costo_hora, 4)}/h` : n.costo_mes > 0 ? `USD ${nf(n.costo_mes, 2)}/mes` : "precio —";
    const filesOk = (n.archivos || []).filter((f) => f.listo).length;
    return h("div", { class: `card cl-node${st !== "viva" ? " down" : ""}`, style: { borderColor: color } },
      h("div", { class: "top" }, h("span", { class: "nm", style: { color } }, up(n.nombre)), h("span", { class: "st", style: { color: stColor } }, `● ${stText}`)),
      n.es_lider ? h("div", { class: "lead" }, "★ LÍDER DEL CLÚSTER") : h("div", { class: "muted", style: { minHeight: "18px" } }, d.etcd_lider === n.nombre ? "líder de etcd (Raft)" : ""),
      h("div", { class: "muted" }, `${providerLabel(n.provider)} · ${n.region || "—"} (${n.pais || "—"})`),
      h("div", { class: "muted" }, `${n.instancia || "—"} · ${price}${n.cobro ? ` (${n.cobro})` : ""}`),
      h("div", { style: { marginTop: "6px" } }, cleanCpu(n.modelo)),
      h("div", {}, `${nf(n.cpus)} vCPU · ${fmtBytes(s.mem_total)} RAM · ${nf(n.procesos)} procesos`),
      h("div", {}, `Potencia ≈ ${isNum(n.potencia_gflops) ? nf(n.potencia_gflops, 0) : "…"} GFLOPS · GPU: ${n.gpu || "—"}`),
      h("div", { class: "mono", style: { marginTop: "4px" } }, `carga ${s.carga ? nf(s.carga[0], 2) : "—"} · RAM ${isNum(ram) ? nf(ram, 0) : "—"} % · CPU ${nf(s.cpu, 0)} %`),
      st === "viva" ? coreStrip(s, color) : null,
      h("div", { class: "mono", style: { color } }, `IP pública ${n.ip_publica || "—"}`),
      h("div", { class: "mono", style: { color } }, `IP privada ${n.ip_privada || "—"} (WireGuard)`),
      h("div", { class: "muted" }, `datos listos: ${filesOk}/${(n.archivos || []).length} · fragmentos ${nf(s.pedazos)}`),
      h("div", { class: "acts" },
        h("button", { class: "btn", type: "button", disabled: st === "apagada", onclick: () => clAction("/api/cluster/apagar", { nodo: n.nombre }, `Apagando ${up(n.nombre)} (simulado)…`) }, "Apagar nube"),
        h("button", { class: "btn", type: "button", disabled: st !== "apagada", onclick: () => clAction("/api/cluster/encender", { nodo: n.nombre }, `Encendiendo ${up(n.nombre)}…`) }, "Encender")));
  }));
}

/* ------------------------------------------------------------ fragmentos */
function jobSummary(d) {
  const job = d.trabajo || {};
  return job.estado === "done" ? job.resultado : (d.historial || []).slice(-1)[0] || null;
}
function renderClFrags(d) {
  const job = d.trabajo || {}, total = job.fragmentos_total || 0;
  const done = new Map(d.fragmentos.map((f) => [f[0], f]));
  const inflight = (job.progreso || {}).en_curso || {};
  const mb = total && job.bytes_total ? job.bytes_total / total / 1048576 : null;
  $("#cl-frag-title").textContent = total ? `Fragmentos (${nf(total)} × ~${nf(mb, 0)} MB)` : "Fragmentos";
  const fase = (job.progreso || {}).fase;
  $("#cl-frag-sub").textContent = !job.estado ? "sin trabajo" : job.estado === "running" ? `${fase || "trabajando"} · ${nf(done.size)}/${nf(total)} hechos · líder ${up(d.lider)}` :
    job.estado === "done" ? `terminado ${fmtDate(new Date(job.fin * 1000).toISOString())}` : `${job.estado}${job.error ? `: ${job.error}` : ""}`;
  const names = d.nodos.map((n) => n.nombre);
  $("#cl-legend").replaceChildren(...names.map((n) => h("span", {}, h("i", { style: { background: nodeColor(n) } }), n)));
  const box = $("#cl-frags");
  if (!total) { const e = emptyEl("Pulse «Analizar» para repartir el ADN entre las nubes"); e.style.gridColumn = "1 / -1"; box.replaceChildren(e); renderClSummary(d); return; }
  const t0 = Math.min(...d.fragmentos.map((f) => f[2]), Infinity);
  box.replaceChildren(...Array.from({ length: total }, (_, i) => {
    const f = done.get(i), run = inflight[i];
    const node = f ? f[1] : run;
    const cell = h("div", { class: `cl-frag${f ? "" : run ? " run" : " pend"}`, style: f ? { background: nodeColor(node) } : run ? { color: nodeColor(node) } : {} }, String(i));
    cell.addEventListener("pointermove", (e) => showTip(e, `Fragmento ${i}`, f ? [
      { name: "Nube", value: up(f[1]), color: nodeColor(f[1]) }, { name: "Duración", value: fmtSecs(f[3] - f[2]), color: nodeColor(f[1]) },
      { name: "Inicio", value: `+${nf(f[2] - t0, 2)} s`, color: nodeColor(f[1]) }, { name: "Modo", value: f[4] === "referencia" ? "datos locales" : "datos enviados", color: nodeColor(f[1]) }]
      : [{ name: "Estado", value: run ? `calculando en ${up(run)}` : "pendiente", color: run ? nodeColor(run) : "var(--neutral-mark)" }]));
    cell.addEventListener("pointerleave", hideTip);
    return cell;
  }));
  renderClSummary(d);
}

function renderClSummary(d) {
  const s = jobSummary(d), box = $("#cl-summary");
  if (!s) { box.replaceChildren(); return; }
  const r = s.resultado || {};
  const lines = [h("div", {}, h("b", {}, `Trabajo ${s.id}`), `: ${nf(s.segundos, 2)} s · ${nf(GB(s.bytes), 2)} GB · ${nf(s.gb_s, 2)} GB/s · ${nf(s.caracteres)} caracteres · líder ${(s.lideres || []).map(up).join(" → ")}`)];
  if (s.modo === "comparar") lines.push(h("div", {}, `Comparadas ${nf(r.comparadas)} · iguales ${nf(r.iguales)} · diferentes ${nf(r.diferentes)} · similitud ${nf(r.similitud_pct, 4)} %`));
  else lines.push(h("div", {}, `Bases: A=${nf(r.A)}  C=${nf(r.C)}  G=${nf(r.G)}  T=${nf(r.T)}  N=${nf(r.N)} · GC ${nf(r.gc_pct, 2)} % · inválidos ${nf(r.otros)} · patrones: `,
    ...Object.entries(r.patrones || {}).map(([p, v], i) => h("span", {}, i ? " · " : "", h("b", {}, `${p}=${nf(v)}`)))));
  if (typeof s.identico === "boolean") lines.push(h("div", { style: { color: s.identico ? "var(--good-ink)" : "var(--critical)", fontWeight: 600 } },
    s.identico ? `✓ Idéntico al cálculo con 1 núcleo (${fmtSecs(s.seg_1_nucleo)}) · speedup ${nf(s.speedup, 2)}×` : "✗ No coincide con el cálculo de 1 núcleo"));
  box.replaceChildren(...lines);
}

/* ------------------------------------------------------------ pestañas */
function renderClTab(d) {
  $$("#cl-tabs button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.tab === CL.tab)));
  const s = jobSummary(d);
  const sig = `${CL.tab}|${s ? s.id + s.segundos : ""}|${CL.tab === "eventos" ? (d.eventos.slice(-1)[0] || {}).t : ""}|${CL.tab === "red" ? JSON.stringify(d.red) : ""}|${CL.tab === "datos" ? JSON.stringify(d.nodos.map((n) => n.archivos)) + JSON.stringify(d.descargas) : ""}|${CL.tab === "tiempo" ? d.fragmentos.length : ""}|${CL.tab === "historial" ? d.historial.length : ""}|${innerWidth}`;
  if (sig === CL.tabSig) return;
  CL.tabSig = sig;
  const body = $("#cl-tab-body");
  const fn = { comparacion: tabComparacion, costo: tabCosto, tiempo: tabTiempo, red: tabRed, datos: tabDatos, historial: tabHistorial, eventos: tabEventos }[CL.tab];
  body.replaceChildren();
  fn(d, body, s);
}
const noJob = (body) => body.append(emptyEl("Todavía no hay un análisis terminado."));
const swatchCell = (n) => h("td", {}, h("span", { class: "swatch", style: { background: nodeColor(n) } }), up(n));

function tabComparacion(d, body, s) {
  if (!s) return noJob(body);
  const ns = s.nodos || [];
  body.append(h("div", { class: "table-wrap" }, h("table", {},
    h("thead", {}, h("tr", {}, ["Nube", "Proveedor", "País", "Fragmentos", "% del trabajo", "GB", "Cálculo", "GB/s", "Datos", "Bytes por red", "Errores"].map((t) => h("th", {}, t)))),
    h("tbody", {}, ns.map((n) => h("tr", {}, swatchCell(n.nodo), h("td", {}, providerLabel(n.provider)), h("td", {}, n.pais || "—"),
      h("td", {}, nf(n.fragmentos)), h("td", {}, `${nf(n.pct_trabajo, 1)} %`), h("td", {}, nf(n.gb, 2)), h("td", {}, fmtSecs(n.seg_calculo)),
      h("td", {}, nf(n.gb_s, 3)), h("td", {}, n.modo === "referencia" ? "locales" : n.modo === "envio" ? "enviados" : "—"),
      h("td", {}, fmtBytes(n.bytes_red)), h("td", {}, n.fallo ? "falló" : nf(n.errores))))))));
  const a = h("div", { class: "chart" }), b = h("div", { class: "chart" });
  body.append(h("div", { class: "grid halves", style: { marginTop: "16px" } },
    h("div", {}, h("h3", { class: "card-title" }, "Fragmentos por nube"), a), h("div", {}, h("h3", { class: "card-title" }, "Velocidad por nube (GB/s)"), b)));
  const cats = ns.map((n) => up(n.nodo));
  barChart(a, { categories: cats, series: [{ name: "Fragmentos", color: "var(--s1)", values: ns.map((n) => n.fragmentos) }], barColors: ns.map((n) => nodeColor(n.nodo)), fmt: (v) => nf(v), height: 230 });
  barChart(b, { categories: cats, series: [{ name: "GB/s", color: "var(--s1)", values: ns.map((n) => n.gb_s) }], barColors: ns.map((n) => nodeColor(n.nodo)), fmt: (v, ax) => (ax ? nf(v, 2) : `${nf(v, 3)} GB/s`), height: 230 });
  body.append(h("p", { class: "note", style: { marginTop: "12px" } }, "«Datos locales»: la nube lee el fragmento de su propia copia del genoma (verificada por SHA-256); por internet solo viaja la orden {archivo, offset, longitud} y el resultado. «Datos enviados»: el líder le manda los bytes del fragmento."));
}

function tabCosto(d, body, s) {
  if (!s) return noJob(body);
  const ns = (s.nodos || []).slice().sort((a, b) => b.costo_analisis - a.costo_analisis);
  body.append(h("p", { class: "muted", style: { marginTop: 0 } }, `Transacción = 1 análisis completo de ${nf(GB(s.bytes), 2)} GB. Cada nube cobra su tarifa por hora durante los ${nf(s.segundos, 2)} s que dura el análisis (las de cuota mensual se pasan a costo por hora: mes ÷ 730 h).`));
  const tot = { h: 0, m: 0, c: 0, gb: 0 };
  ns.forEach((n) => { tot.h += n.costo_hora; tot.m += n.costo_mes; tot.c += n.costo_analisis; tot.gb += n.gb; });
  const row = (n) => h("tr", {}, swatchCell(n.nodo), h("td", {}, nf(n.costo_hora, 4)), h("td", {}, nf(n.costo_mes, 2)), h("td", {}, nf(s.segundos, 2)),
    h("td", {}, nf(n.costo_analisis, 6)), h("td", {}, nf(n.costo_analisis * 1000, 3)), h("td", {}, nf(n.gb, 2)), h("td", {}, isNum(n.usd_por_gb) ? nf(n.usd_por_gb, 6) : "—"), h("td", {}, `${nf(n.pct_costo, 1)} %`));
  body.append(h("div", { class: "table-wrap" }, h("table", {},
    h("thead", {}, h("tr", {}, ["Nube", "USD/hora", "USD/mes", "Duración (s)", "Costo del análisis (USD)", "Por 1.000 análisis (USD)", "GB procesados", "USD por GB", "% del costo"].map((t) => h("th", {}, t)))),
    h("tbody", {}, ns.map(row), h("tr", { style: { fontWeight: 700 } }, h("td", {}, "TOTAL"), h("td", {}, nf(tot.h, 4)), h("td", {}, nf(tot.m, 2)), h("td", {}, nf(s.segundos, 2)),
      h("td", {}, nf(tot.c, 6)), h("td", {}, nf(tot.c * 1000, 3)), h("td", {}, nf(tot.gb, 2)), h("td", {}, tot.gb ? nf(tot.c / tot.gb, 6) : "—"), h("td", {}, "100 %"))))));
  const credit = ns.filter((n) => /cr[eé]dito/i.test(n.cobro || "")).map((n) => up(n.nodo));
  const est = ns.filter((n) => /estimad/i.test(n.cobro || "")).map((n) => up(n.nodo));
  body.append(h("p", { style: { fontWeight: 650, margin: "14px 0" } }, `Un análisis de ${nf(GB(s.bytes), 2)} GB en ${nf(s.segundos, 2)} s cuesta ≈ USD ${nf(tot.c, 5)} en las ${ns.length} nubes (USD ${nf(tot.c * 1000, 2)} por cada 1.000 análisis; ≈ USD ${nf(tot.m, 2)} al mes si todas quedan encendidas).`,
    credit.length ? ` ${credit.join(" y ")} se pagan con crédito.` : "", est.length ? ` ${est.join(", ")}: valor estimado.` : ""));
  const [a, b, c] = [0, 1, 2].map(() => h("div", { class: "chart" }));
  body.append(h("div", { class: "grid thirds" }, h("div", {}, h("h3", { class: "card-title" }, "Costo de este análisis (milésimas de USD)"), a),
    h("div", {}, h("h3", { class: "card-title" }, "Costo por GB procesado (milésimas de USD)"), b), h("div", {}, h("h3", { class: "card-title" }, "Tarifa por hora (USD)"), c)));
  const cats = ns.map((n) => up(n.nodo)), cols = ns.map((n) => nodeColor(n.nodo));
  barChart(a, { categories: cats, series: [{ name: "mUSD", color: "var(--s1)", values: ns.map((n) => n.costo_analisis * 1000) }], barColors: cols, fmt: (v, ax) => (ax ? nf(v, 2) : `${nf(v, 3)} mUSD`), height: 220 });
  barChart(b, { categories: cats, series: [{ name: "mUSD/GB", color: "var(--s1)", values: ns.map((n) => (isNum(n.usd_por_gb) ? n.usd_por_gb * 1000 : null)) }], barColors: cols, fmt: (v, ax) => (ax ? nf(v, 2) : `${nf(v, 3)} mUSD/GB`), height: 220 });
  barChart(c, { categories: cats, series: [{ name: "USD/h", color: "var(--s1)", values: ns.map((n) => n.costo_hora) }], barColors: cols, fmt: (v, ax) => (ax ? nf(v, 3) : `${nf(v, 4)} USD/h`), height: 220 });
}

function tabTiempo(d, body) {
  const fr = d.fragmentos;
  if (!fr.length) return noJob(body);
  const t0 = Math.min(...fr.map((f) => f[2])), t1 = Math.max(...fr.map((f) => f[3]));
  const lanes = d.nodos.map((n) => n.nombre).filter((n) => fr.some((f) => f[1] === n));
  // cada pedido simultáneo de una nube va en su propio sub-carril
  const rowOf = new Map(), rowsPer = {};
  for (const n of lanes) {
    const ends = [];
    fr.filter((f) => f[1] === n).sort((a, b) => a[2] - b[2]).forEach((f) => {
      let r = ends.findIndex((e) => e <= f[2] + 1e-6);
      if (r < 0) { r = ends.length; ends.push(0); }
      ends[r] = f[3]; rowOf.set(f[0], r);
    });
    rowsPer[n] = Math.max(1, ends.length);
  }
  const rowH = 9, gapL = 10, laneY = {}; let yAcc = 10;
  lanes.forEach((n) => { laneY[n] = yAcc; yAcc += rowsPer[n] * rowH + gapL; });
  const W = Math.max(320, body.clientWidth || 900), m = { l: 80, r: 12, t: 10, b: 34 };
  const H = yAcc + m.b, iw = W - m.l - m.r, span = Math.max(t1 - t0, 1e-3);
  const x = (t) => m.l + (t - t0) / span * iw;
  const root = svg("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "Línea de tiempo de los fragmentos por nube" });
  for (let k = 0; k <= 5; k++) {
    const t = t0 + span * k / 5, xx = x(t);
    root.append(svg("line", { x1: xx, x2: xx, y1: m.t, y2: H - m.b, class: "gridline" }));
    root.append(svg("text", { x: xx, y: H - 14, "text-anchor": "middle", text: `${nf(t - t0, span < 10 ? 1 : 0)} s` }));
    void k;
  }
  lanes.forEach((n) => root.append(svg("text", { x: m.l - 8, y: laneY[n] + rowsPer[n] * rowH / 2 + 4, "text-anchor": "end", text: up(n) })));
  fr.forEach((f) => {
    if (!(f[1] in laneY)) return;
    const r = svg("rect", { x: x(f[2]), y: laneY[f[1]] + rowOf.get(f[0]) * rowH, width: Math.max(2, x(f[3]) - x(f[2]) - 1), height: rowH - 2, rx: 2, style: { fill: nodeColor(f[1]) } });
    r.addEventListener("pointermove", (e) => showTip(e, `Fragmento ${f[0]} · ${up(f[1])}`, [{ name: "Inicio", value: `+${nf(f[2] - t0, 2)} s`, color: nodeColor(f[1]) }, { name: "Duración", value: fmtSecs(f[3] - f[2]), color: nodeColor(f[1]) }]));
    r.addEventListener("pointerleave", hideTip);
    root.append(r);
  });
  // cambios de líder durante el trabajo
  d.eventos.filter((e) => e.tipo === "lider" && /nuevo líder|retoma/.test(e.msg) && e.t >= t0 - 1 && e.t <= t1 + 1).forEach((e) => {
    const xx = x(Math.min(Math.max(e.t, t0), t1));
    root.append(svg("line", { x1: xx, x2: xx, y1: m.t, y2: H - m.b, "stroke-width": 2, "stroke-dasharray": "5 4", style: { stroke: "var(--warning)" } }));
    root.append(svg("text", { x: xx + 4, y: m.t + 10, class: "value-label", text: `★ ${up(e.nodo)}` }));
  });
  body.append(h("div", { class: "chart" }, root), h("p", { class: "muted" }, "Cada barra es un fragmento. Las líneas punteadas marcan cambios de líder durante el trabajo (por ejemplo, cuando la nube líder se cae y otra retoma el trabajo)."));
}

function tabRed(d, body) {
  const names = d.nodos.map((n) => n.nombre), red = d.red || {};
  const cell = (from, to, key) => { const v = ((red[from] || {}).destinos || {})[to]; return v && isNum(v[key]) ? v[key] : null; };
  const all = names.flatMap((a) => names.map((b) => cell(a, b, "rtt_ms"))).filter(isNum);
  if (!all.length) { body.append(emptyEl("Pulse «Medir red»: cada nube mide su latencia (RTT) y transferencia hacia las demás por WireGuard.")); return; }
  const max = Math.max(...all);
  const heat = (v) => (isNum(v) ? `color-mix(in srgb, var(--s1) ${Math.round(15 + 70 * v / max)}%, var(--surface))` : "transparent");
  const matrix = (key, fmt, title, colored) => h("div", {}, h("h3", { class: "card-title", style: { marginBottom: "8px" } }, title), h("div", { class: "table-wrap" }, h("table", { class: "heat" },
    h("thead", {}, h("tr", {}, h("th", {}, "desde \\ hacia"), names.map((n) => h("th", {}, up(n))))),
    h("tbody", {}, names.map((a) => h("tr", {}, h("td", { style: { textAlign: "left" } }, h("span", { class: "swatch", style: { background: nodeColor(a) } }), up(a)),
      names.map((b) => { const v = a === b ? null : cell(a, b, key); return h("td", { style: { background: colored ? heat(v) : "transparent" } }, a === b ? "·" : isNum(v) ? `${fmt(v)}${key === "rtt_ms" && v < 15 ? " ✓" : ""}` : "—"); })))))));
  body.append(h("div", { class: "grid halves" }, matrix("rtt_ms", (v) => `${nf(v, v < 10 ? 1 : 0)} ms`, "Latencia RTT entre nubes (ms)", true), matrix("mb_s", (v) => nf(v, 1), "Transferencia entre nubes (MB/s)", false)));
  body.append(h("p", { class: "note", style: { marginTop: "12px" } }, "✓ = menos de 15 ms (el umbral de la pregunta 1 de la evaluación). La latencia (ms) depende sobre todo de la distancia: ≈1 ms de ida y vuelta por cada 100 km de fibra. La transferencia (MB/s) depende del ancho de banda de cada VM. Son cosas distintas: un enlace puede tener poca latencia y poco ancho de banda, o al revés."));
}

function fileCell(f) {
  if (!f) return ["—", "var(--muted)"];
  if (f.listo) return [`✓ ${nf(GB(f.bytes), 2)} GB`, "var(--good-ink)"];
  if (f.estado === "error") return ["error", "var(--critical)", f.error];
  if ((f.estado === "descargando" || f.estado === "subiendo") && f.recibido) {
    const pct = f.total ? ` ${nf(f.recibido / f.total * 100, 0)} %` : ` ${nf(f.recibido / 1048576, 0)} MB`;
    return [`${f.estado === "subiendo" ? "subiendo" : "bajando"}${pct}${f.mb_s ? ` · ${nf(f.mb_s, 1)} MB/s` : ""}`, "var(--warning)"];
  }
  return [f.estado || "sin preparar", "var(--warning)"];
}

function tabDatos(d, body) {
  const now = d.ahora, cat = new Set();
  d.nodos.forEach((n) => (n.archivos || []).forEach((f) => cat.add(f.nombre)));
  Object.keys(d.descargas || {}).forEach((f) => cat.add(f));
  const files = Array.from(cat).sort();
  const errors = [];
  body.append(files.length ? h("div", { class: "table-wrap" }, h("table", {},
    h("thead", {}, h("tr", {}, h("th", {}, "Archivo"), d.nodos.map((n) => h("th", {}, up(n.nombre))), h("th", {}, "¿Idéntico?"))),
    h("tbody", {}, files.map((name) => {
      const shas = new Set(d.nodos.map((n) => ((n.archivos || []).find((x) => x.nombre === name && x.listo) || {}).seq_sha256).filter(Boolean));
      return h("tr", {}, h("td", { class: "mono" }, name), d.nodos.map((n) => {
        const f = (n.archivos || []).find((x) => x.nombre === name);
        const [t, c, err] = nodeState(n, now) === "caida" ? ["(caída)", "var(--muted)"] : fileCell(f);
        if (err) errors.push([up(n.nombre), err]);
        return h("td", { style: { color: c, fontWeight: 600 }, title: err || "" }, t);
      }), h("td", {}, shas.size === 1 ? "✓ mismo SHA-256" : shas.size > 1 ? "✗ distintos" : "—"));
    })))) : emptyEl("Ninguna nube tiene archivos todavía. Use una de las tres opciones de abajo."));
  if (errors.length) {
    const by = new Map();  // el mismo error en varias nubes se muestra una vez
    errors.forEach(([n, e]) => by.set(e, [...(by.get(e) || []), n]));
    body.append(h("div", { class: "note", style: { color: "var(--critical)", marginTop: "8px" } }, Array.from(by, ([e, ns]) => h("div", {}, h("b", {}, ns.join(", ")), `: ${e}`))));
  }
  body.append(datosForms(d));
}

/* Los formularios se crean UNA vez y se vuelven a insertar: así lo escrito y la
   barra de la subida no se borran cuando la tabla se actualiza cada segundo. */
function datosForms(d) {
  const F = CL.datosForms || (CL.datosForms = buildDatosForms());
  F.update(d);
  return F.el;
}

function buildDatosForms() {
  const card = (title, help, ...kids) => h("div", { class: "card", style: { marginTop: "16px", background: "var(--surface-2)" } },
    h("h3", { class: "card-title", style: { marginBottom: "6px" } }, title), h("p", { class: "muted", style: { marginTop: 0 } }, help),
    h("div", { class: "cl-inline", style: { width: "100%", flexWrap: "wrap" } }, ...kids));
  const nameInput = () => h("input", { type: "text", class: "plain", placeholder: "GCA_000001405.29_GRCh38.p14_genomic.fna", style: { flex: 2, minWidth: "180px", fontFamily: "var(--mono)" } });
  const fixName = (v) => v.trim().replace(/\s+/g, "_").replace(/[^A-Za-z0-9._-]/g, "");

  // 1) desde un enlace (OneDrive / SharePoint / Dropbox / NCBI)
  const url = h("input", { type: "url", class: "plain", placeholder: "https://puceeduec-my.sharepoint.com/:u:/g/personal/... o https://1drv.ms/u/...", style: { flex: 3, minWidth: "220px" } });
  const nm1 = nameInput();
  const c1 = card("① Descargar desde un enlace en todas las nubes",
    "Cada nube baja el archivo directamente de OneDrive / SharePoint / Dropbox con su propia conexión (la más rápida). Funciona si el enlace es del ARCHIVO (no de la carpeta) y es público («Cualquier persona con el vínculo»). Si OneDrive pide iniciar sesión, use la opción ②.",
    url, nm1, h("button", { class: "btn primary", type: "button", onclick: () => clAction("/api/cluster/descargar", { url: url.value.trim(), archivo: fixName(nm1.value) }) }, "Descargar en todas"));

  // 2) subir desde la PC a la nube conectada
  const file = h("input", { type: "file", class: "plain", accept: ".fna,.fa,.fasta,.fas,.txt", style: { flex: 3, minWidth: "220px" } });
  const bar = h("progress", { max: 100, value: 0, style: { flex: "1 1 100%", height: "10px", display: "none" } });
  const msg = h("div", { class: "muted", style: { flex: "1 1 100%", fontVariantNumeric: "tabular-nums" } });
  const target = h("b", {}, "—");
  let xhr = null;
  const send = h("button", { class: "btn primary", type: "button", onclick: () => {
    if (xhr) { xhr.abort(); return; }
    const f = file.files[0];
    if (!f) { toast("Elija primero el archivo .fna"); return; }
    const name = fixName(f.name);
    xhr = new XMLHttpRequest();
    xhr.open("POST", `/api/subir?archivo=${encodeURIComponent(name)}`);
    const t0 = performance.now();
    bar.style.display = "block"; send.textContent = "Cancelar subida";
    xhr.upload.onprogress = (e) => {
      if (!e.lengthComputable) return;
      const secs = (performance.now() - t0) / 1000, mbs = e.loaded / 1048576 / Math.max(secs, 0.001);
      bar.value = e.loaded / e.total * 100;
      msg.textContent = `${nf(e.loaded / 1048576, 0)} de ${nf(e.total / 1048576, 0)} MB · ${nf(mbs, 1)} MB/s · faltan ≈ ${fmtSecs((e.total - e.loaded) / 1048576 / Math.max(mbs, 0.01))}`;
    };
    const done = (text) => { xhr = null; send.textContent = "Subir"; msg.textContent = text; clPoll(); };
    xhr.onload = () => { let r = {}; try { r = JSON.parse(xhr.responseText); } catch (_) { /* vacío */ }
      done(xhr.status < 300 ? `✓ ${r.mensaje}. Ahora use ③ para copiarlo a las demás nubes.` : `Error: ${r.error || xhr.status}`); };
    xhr.onerror = () => done("Error de red: se cortó el túnel SSH o la conexión. Vuelva a intentarlo.");
    xhr.onabort = () => done("Subida cancelada.");
    xhr.send(f);
  } }, "Subir");
  const c2 = card("② Subir desde tu PC a la nube conectada",
    h("span", {}, "Primero descargue el archivo de OneDrive en su PC. Se sube por el túnel SSH a ", target, ", solo una vez; luego ③ lo replica a las demás por WireGuard. Con 3 GB la subida tarda según el internet de su casa (a 5 MB/s, unos 10 min). Para archivos grandes, el script ", h("code", {}, "subir_genoma.sh"), " (rsync) puede reanudar si se corta."),
    file, send, bar, msg);

  // 3) replicar desde una nube a las demás
  const src = h("select", { style: { flex: 1, minWidth: "140px" } });
  const fsel = h("select", { style: { flex: 2, minWidth: "200px", fontFamily: "var(--mono)" } });
  const c3 = card("③ Copiar desde una nube a todas las demás (WireGuard)",
    "Las nubes que no tienen el archivo lo copian desde la nube elegida por la red privada 10.99.0.x (cifrada). Al terminar, la tabla debe mostrar «✓ mismo SHA-256» en todas.",
    src, fsel, h("button", { class: "btn primary", type: "button", onclick: () => clAction("/api/cluster/descargar", { origen: src.value, archivo: fsel.value }) }, "Replicar"));

  const fill = (sel, opts) => {
    const cur = sel.value, sig = JSON.stringify(opts);
    if (sel.dataset.sig === sig) return;
    sel.dataset.sig = sig;
    sel.replaceChildren(...opts.map(([v, t]) => h("option", { value: v }, t)));
    if (opts.some(([v]) => v === cur)) sel.value = cur;
  };
  const api_ = {
    el: h("div", {}, c1, c2, c3),
    update(d) {
      target.textContent = up(d.conectado_via || "la nube conectada");
      const ready = d.nodos.filter((n) => nodeState(n, d.ahora) !== "caida" && (n.archivos || []).some((f) => f.listo));
      fill(src, ready.map((n) => [n.nombre, up(n.nombre)]));
      const node = d.nodos.find((n) => n.nombre === src.value);
      fill(fsel, ((node && node.archivos) || []).filter((f) => f.listo).map((f) => [f.nombre, `${f.nombre} (${nf(GB(f.bytes), 2)} GB)`]));
    },
  };
  src.addEventListener("change", () => CL.data && api_.update(CL.data));
  return api_;
}

function tabHistorial(d, body) {
  const rows = (d.historial || []).slice().reverse();
  if (!rows.length) return noJob(body);
  body.append(h("div", { class: "table-wrap" }, h("table", {},
    h("thead", {}, h("tr", {}, ["Trabajo", "Archivos", "GB", "Fragmentos", "Duración", "GB/s", "Líderes", "Costo (USD)", "Verificación"].map((t) => h("th", {}, t)))),
    h("tbody", {}, rows.map((s) => h("tr", {}, h("td", { class: "mono" }, s.id), h("td", {}, (s.archivos || []).join(", ")), h("td", {}, nf(GB(s.bytes), 2)),
      h("td", {}, nf(s.fragmentos)), h("td", {}, fmtSecs(s.segundos)), h("td", {}, nf(s.gb_s, 3)), h("td", {}, (s.lideres || []).map(up).join(" → ")),
      h("td", {}, nf(s.costo_total, 6)), h("td", {}, s.identico === true ? "✓ idéntico" : s.identico === false ? "✗" : "—")))))));
}

const EVT_COLOR = { lider: "var(--warning)", fallo: "var(--critical)", error: "var(--critical)", apagado: "var(--critical)", encendido: "var(--good)", trabajo: "var(--brand)" };
function tabEventos(d, body) {
  const ev = (d.eventos || []).slice().reverse();
  if (!ev.length) { body.append(emptyEl("Sin eventos")); return; }
  body.append(h("div", {}, ev.map((e) => h("div", { class: "evt" },
    h("span", { class: "mono muted" }, new Date(e.t * 1000).toLocaleTimeString(LOCALE)), h("i", { style: { background: EVT_COLOR[e.tipo] || nodeColor(e.nodo) } }),
    h("span", {}, h("b", { style: { color: nodeColor(e.nodo) } }, up(e.nodo)), " · ", e.msg)))));
}
