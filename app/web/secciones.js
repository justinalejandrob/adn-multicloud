/* =============================================================================
   ADN Multinube - Secciones Panel principal · Procesamiento ADN · Rendimiento ·
   Multicloud. Todas se dibujan con los datos REALES del clúster guardados en etcd
   (CL.data = /api/cluster/estado) y con los resultados de la Evaluación S11 (S.ev).
   Solo DEFINE funciones; las ejecuta app.js.
   ============================================================================= */
"use strict";

/* ---------------------------------------------------------------- comunes */
const costHour = (n) => (isNum(n.costo_hora) && n.costo_hora > 0 ? n.costo_hora : (n.costo_mes || 0) / 730);
const evRes = (q) => ((S.ev && S.ev.resultados) || {})[q] || null;
const evData = (q) => (evRes(q) || {}).datos || null;
const jobsContar = () => ((CL.data && CL.data.historial) || []).filter((j) => j.modo !== "comparar" && j.resultado);
const lastJob = () => jobsContar().slice(-1)[0] || null;
const fmtHora = (t) => (isNum(t) ? new Date(t * 1000).toLocaleString(LOCALE, { dateStyle: "medium", timeStyle: "short" }) : "—");
const nodeProcs = (j) => (j.nodos || []).filter((x) => x.fragmentos).reduce((a, x) => a + (x.cpus || 0), 0);
const nubesDe = (j) => (j.nodos || []).filter((x) => x.fragmentos).map((x) => x.nodo);
function bestVerified() {
  const v = jobsContar().filter((j) => isNum(j.speedup));
  return v.length ? v.reduce((a, b) => (b.speedup > a.speedup ? b : a)) : null;
}
const BASE_COLORS = { A: "var(--s1)", C: "var(--s2)", G: "var(--s3)", T: "var(--s4)", N: "var(--neutral-mark)" };
function baseRows(res) {
  const total = ["A", "C", "G", "T", "N"].reduce((a, k) => a + (res[k] || 0), 0) || 1;
  return h("div", {}, ["A", "C", "G", "T", "N"].map((k) => {
    const pct = (res[k] || 0) / total * 100;
    return h("div", { class: "base-row" }, h("span", { class: "letter" }, k),
      h("div", { class: "track" }, h("div", { class: "fill", style: { width: `${pct}%`, background: BASE_COLORS[k] } })),
      h("span", { class: "nums" }, h("b", {}, `${nf(pct, 2)} %`), " ", h("span", { class: "muted" }, nf(res[k] || 0))));
  }));
}
function stateChip(estado) {
  const m = { listo: ["Lista", "var(--good-ink)"], corriendo: ["Ejecutándose…", "var(--warning)"], "en cola": ["En cola", "var(--warning)"], error: ["Error", "var(--critical)"] }[estado]
    || ["Sin ejecutar", "var(--muted)"];
  return h("span", { class: "tag", style: { color: m[1] } }, m[0]);
}
const firstSentence = (t) => (t ? (t.match(/^.*?[.!?](\s|$)/) || [t])[0].trim() : "");

/* ============================================================ 1. PANEL PRINCIPAL */
function renderPanel() {
  const d = CL.data, root = $("#panel-root");
  if (!d || d.modo !== "etcd") { offlineBanner(root); return; }
  const ev = (S.ev && S.ev.resultados) || {};
  const live = d.nodos.map((n) => [n.nombre, nodeState(n, d.ahora), Math.round((n.stats || {}).cpu || 0)]);
  if (!changed("panel", [live, d.lider, d.etcd_lider, (d.historial || []).length, (d.eventos || []).slice(-1), d.trabajo && d.trabajo.progreso,
    Object.entries(ev).map(([k, v]) => [k, v && v.estado, v && v.fin]), innerWidth])) return;

  const vivas = d.nodos.filter((n) => nodeState(n, d.ahora) === "viva");
  const j = lastJob(), best = bestVerified();
  const listas = ["p1", "p2", "p3", "p4", "p5", "p6", "p7", "p8"].filter((q) => (ev[q] || {}).estado === "listo").length;
  const usdH = d.nodos.reduce((a, n) => a + costHour(n), 0);
  const kpis = h("div", { class: "grid kpis" },
    kpiTile({ label: "Nubes vivas", iconName: "server", value: `${vivas.length}/${d.nodos.length}`, foot: `${(d.etcd_miembros || []).length} miembros de etcd · WireGuard` }),
    kpiTile({ label: "Líder del clúster", iconName: "network", value: d.lider ? nube(d.lider) : "—", foot: `Líder de etcd (Raft): ${nube(d.etcd_lider) || "—"}` }),
    kpiTile({ label: "Último análisis", iconName: "clock", value: j ? nf(j.segundos, 1) : "—", unit: j ? "s" : "", foot: j ? `${nf(j.bytes / 1e9, 2)} GB · ${nubesDe(j).length} nubes · ${nf(j.gb_s, 2)} GB/s` : "Lance uno en Clúster" }),
    kpiTile({ label: "Speedup verificado", iconName: "trend", value: best ? `${nf(best.speedup, 2)}×` : "—", foot: best ? `vs. 1 núcleo (${fmtSecs(best.seg_1_nucleo)}) · resultado idéntico` : "Analice con «Verificar»" }),
    kpiTile({ label: "Evaluación S11", iconName: "clipboard", value: `${listas}/8`, foot: listas === 8 ? "Las 8 preguntas resueltas" : "Pruebas ejecutadas en las nubes" }),
  );

  const nodesTable = tableEl(["Nube", "Proveedor y ubicación", "CPU", "Uso", "Estado"], d.nodos.map((n) => {
    const st = nodeState(n, d.ahora), ui = STATE_UI[st];
    return [h("span", {}, dot(nodeColor(n.nombre)), h("b", {}, nube(n.nombre)), n.nombre === d.lider ? h("span", { style: { color: "var(--warning)" } }, " ★") : null),
      h("span", { style: { display: "block", textAlign: "left", whiteSpace: "normal" } }, providerLabel(n.provider), h("br"), h("span", { class: "muted" }, `${n.region || "—"} (${n.pais || "—"})`)),
      `${n.cpus || "—"} vCPU`,
      st === "viva" ? `${nf((n.stats || {}).cpu || 0, 0)} %` : "—", h("span", { style: { color: ui[1], fontWeight: 650 } }, ui[0])];
  }));

  let genome = emptyEl("Todavía no hay análisis del genoma.");
  if (j) {
    const r = j.resultado, pats = Object.entries(r.patrones || {});
    genome = h("div", {}, baseRows(r),
      h("div", { class: "muted", style: { marginTop: "10px" } }, `GC ${nf(r.gc_pct, 2)} % · ${nf(j.caracteres)} caracteres · ${fmtHora(j.fin)}`),
      pats.length ? h("div", { style: { marginTop: "6px" } }, pats.map(([p, c]) => h("span", { class: "tag", style: { marginRight: "6px" } }, `${p}: ${nf(c)}`))) : null,
      h("div", { style: { marginTop: "10px" } }, h("a", { href: "#adn" }, "Ver el análisis completo →")));
  }
  const cost = kvList([
    ["Las 5 nubes encendidas", `USD ${nf(usdH, 4)} por hora`],
    ["Al mes (730 h)", `USD ${nf(usdH * 730, 2)}`],
    ["Último análisis", j ? `USD ${nf(j.costo_total, 6)} (USD ${nf(j.costo_por_1000, 3)} por 1.000)` : "—"],
  ]);

  const evts = (d.eventos || []).slice(-8).reverse();
  const evtColors = { lider: "var(--warning)", fallo: "var(--critical)", apagado: "var(--critical)", encendido: "var(--good)", trabajo: "var(--brand)", datos: "var(--s3)" };
  const activity = evts.length ? h("div", {}, evts.map((e) => h("div", { class: "evt" },
    h("span", { class: "muted mono", style: { fontSize: "12px" } }, new Date(e.t * 1000).toLocaleTimeString(LOCALE)),
    h("i", { style: { background: evtColors[e.tipo] || "var(--muted)" } }), h("span", {}, e.msg)))) : emptyEl("Sin eventos.");

  const QS = ["p1", "p2", "p3", "p4", "p5", "p6", "p7", "p8"];
  const evList = h("div", {}, QS.map((q) => {
    const v = ev[q] || {};
    return h("div", { class: "evt", style: { gridTemplateColumns: "34px 92px 1fr" } }, h("b", {}, q.toUpperCase()), stateChip(v.estado),
      h("span", { class: "muted", style: { whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" } }, EV_TITLES[q]));
  }), h("div", { style: { marginTop: "10px" } }, h("a", { href: "#evaluacion" }, "Ir a la Evaluación S11 →")));

  root.replaceChildren(kpis,
    h("div", { class: "grid two", style: { marginTop: "16px" } },
      cardEl(`Las ${d.nodos.length} nubes del clúster`, "Estado en vivo (latido cada 2 s en etcd)", nodesTable),
      h("div", { class: "stack" }, cardEl("Último análisis del genoma", "Composición de bases calculada por el clúster", genome),
        cardEl("Costo del clúster", "Tarifas reales de cada proveedor; las mensuales se prorratean", cost))),
    h("div", { class: "grid halves", style: { marginTop: "16px" } },
      cardEl("Actividad reciente", "Eventos del clúster (líder, caídas, trabajos, datos)", activity),
      cardEl("Evaluación S11", "Cada pregunta, resuelta con un experimento en las nubes", evList)));
}

/* ============================================================ 2. PROCESAMIENTO ADN */
const IUPAC = { R: "A o G", Y: "C o T", S: "G o C", W: "A o T", K: "G o T", M: "A o C", B: "C, G o T", D: "A, G o T", H: "A, C o T", V: "A, C o G", U: "uracilo (ARN)" };
const MOTIVOS = {
  TATAAA: "Caja TATA: señal en los promotores donde empieza la transcripción de un gen",
  GAATTC: "Sitio de corte de la enzima de restricción EcoRI",
  GGATCC: "Sitio de corte de la enzima BamHI",
  AAGCTT: "Sitio de corte de la enzima HindIII",
  TTAGGG: "Repetición de los telómeros (extremos de los cromosomas)",
  CG: "Dinucleótido CpG (se metila; escaso en el genoma humano)",
  ATG: "Codón de inicio de la traducción",
};
let adnSel = null;
function renderAdn() {
  const d = CL.data, root = $("#adn-root");
  if (!d || d.modo !== "etcd") { offlineBanner(root); return; }
  const jobs = jobsContar().slice().reverse();
  if (!jobs.length) { root.replaceChildren(cardEl("Sin análisis", "", emptyEl("Lance un análisis del genoma en la sección Clúster."))); return; }
  if (!adnSel || !jobs.some((x) => x.id === adnSel)) adnSel = jobs[0].id;
  const j = jobs.find((x) => x.id === adnSel);
  const files = j.archivos || [];
  const copies = d.nodos.map((n) => [n.nombre, ((n.archivos || []).find((f) => f.nombre === files[0]) || {}).seq_sha256 || null]);
  if (!changed("adn", [adnSel, jobs.length, copies, innerWidth])) return;

  const r = j.resultado, valid = r.A + r.C + r.G + r.T, total = valid + r.N + (r.otros || 0);
  const sel = h("select", { class: "btn", "aria-label": "Análisis" }, jobs.map((x) => h("option", { value: x.id, selected: x.id === adnSel },
    `${fmtHora(x.fin)} · ${nubesDe(x).map(nube).join(", ")} · ${nf(x.segundos, 1)} s`)));
  sel.addEventListener("change", () => { adnSel = sel.value; renderView(true); });

  const kpis = h("div", { class: "grid kpis" },
    kpiTile({ label: "Caracteres analizados", iconName: "file", value: nf(j.caracteres / 1e9, 3), unit: "G", foot: `${files.join(", ")}` }),
    kpiTile({ label: "Contenido GC", iconName: "percent", value: nf(r.gc_pct, 2), unit: "%", foot: "Genoma humano: ≈ 41 %" }),
    kpiTile({ label: "Regiones sin secuenciar (N)", iconName: "alert", value: nf(r.N / total * 100, 2), unit: "%", foot: `${nf(r.N)} bases N` }),
    kpiTile({ label: "Secuencias en el FASTA", iconName: "layers", value: nf(r.registros), foot: "Cromosomas y contigs" }),
    kpiTile({ label: "Tiempo en el clúster", iconName: "clock", value: nf(j.segundos, 2), unit: "s", foot: `${nubesDe(j).length} nubes · ${nf(j.gb_s, 2)} GB/s${isNum(j.speedup) ? ` · ${nf(j.speedup, 2)}×` : ""}` }),
  );

  const at = r.A / r.T, cg = r.C / r.G;
  const comp = cardEl("Composición de bases", "Porcentaje sobre todas las bases leídas", baseRows(r),
    h("div", { class: "note", style: { marginTop: "12px" } },
      `Segunda regla de Chargaff: en una sola hebra, A ≈ T y C ≈ G. Aquí A/T = ${nf(at, 4)} y C/G = ${nf(cg, 4)}, `,
      Math.abs(at - 1) < 0.02 && Math.abs(cg - 1) < 0.02 ? "lo que confirma que el conteo distribuido es coherente." : "revise el archivo."));

  const freq = { A: r.A / valid, C: r.C / valid, G: r.G / valid, T: r.T / valid };
  const pats = Object.entries(r.patrones || {}).map(([p, c]) => {
    const prob = [...p].reduce((a, b) => a * (freq[b] || 0), 1);
    const exp = prob * valid;
    return [h("span", { style: { display: "block", whiteSpace: "normal", minWidth: "150px" } }, h("b", { class: "mono" }, p), h("br"),
      h("span", { class: "muted", style: { fontSize: "12px" } }, MOTIVOS[p] || "Patrón definido por el usuario")),
      nf(c), nf(c / (valid / 1e6), 1), nf(exp, 0),
      h("b", { style: { color: c / exp > 1 ? "var(--good-ink)" : "var(--warning)" } }, `${nf(c / exp, 2)}×`)];
  });
  const patCard = cardEl("Patrones encontrados", "Observado frente a lo esperado si las bases estuvieran al azar (con estas frecuencias)",
    pats.length ? tableEl(["Patrón y significado", "Veces", "Por millón", "Al azar", "Obs./esp."], pats) : emptyEl("Este análisis no buscó patrones."),
    pats.length ? h("p", { class: "muted", style: { marginBottom: 0 } }, "Una razón mayor que 1× indica que el motivo aparece más de lo que daría el azar: es una señal biológica, no ruido.") : null);

  const otros = Object.entries(r.detalle_otros || {}).sort((a, b) => b[1] - a[1]).slice(0, 12);
  const otherCard = cardEl("Otros caracteres (código IUPAC)", "Bases ambiguas que el FASTA marca con letras especiales",
    otros.length ? tableEl(["Código", "Cantidad", "Significa"], otros.map(([k, v]) => [h("b", { class: "mono" }, k), nf(v), IUPAC[k.toUpperCase()] || "carácter no válido"]))
      : emptyEl("No hay caracteres ambiguos."));

  const rep = cardEl("Cómo se repartió el trabajo", "Fragmentos que calculó cada nube con su propia copia del genoma",
    tableEl(["Nube", "Fragmentos", "% del trabajo", "GB", "Datos"], (j.nodos || []).filter((x) => x.fragmentos).map((x) => [
      h("span", {}, dot(nodeColor(x.nodo)), nube(x.nodo)), nf(x.fragmentos), `${nf(x.pct_trabajo, 1)} %`, nf(x.gb, 2),
      x.bytes_red ? `enviados (${fmtBytes(x.bytes_red)})` : "locales"])));
  const shas = new Set(copies.map(([, s]) => s).filter(Boolean));
  const integ = cardEl("Integridad de las copias", `${files[0] || ""} en cada nube (SHA-256 de la secuencia limpia)`,
    tableEl(["Nube", "SHA-256", ""], copies.map(([n, s]) => [h("span", {}, dot(nodeColor(n)), nube(n)), h("span", { class: "mono" }, s ? shortHash(s) : "—"),
      s ? h("span", { style: { color: shas.size === 1 ? "var(--good-ink)" : "var(--critical)" } }, shas.size === 1 ? "✓ idéntica" : "distinta") : "sin copia"])));

  root.replaceChildren(
    h("div", { class: "card", style: { marginBottom: "16px" } }, h("div", { class: "card-head", style: { margin: 0 } },
      h("div", {}, h("h2", { class: "card-title" }, "Análisis mostrado"), h("p", { class: "card-sub" }, `Trabajo ${j.id} · patrones ${(j.patrones || []).join(", ") || "—"} · líder ${(j.lideres || []).map(nube).join(" → ")}`)),
      h("div", { style: { display: "flex", gap: "8px" } }, sel, h("a", { class: "btn primary", href: "#cluster" }, ico("play"), "Nuevo análisis")))),
    kpis,
    h("div", { class: "grid halves", style: { marginTop: "16px" } }, comp, patCard),
    h("div", { class: "grid thirds", style: { marginTop: "16px" } }, otherCard, rep, integ));
}

/* ============================================================ 3. RENDIMIENTO */
function renderPerf() {
  const d = CL.data, root = $("#perf-root");
  if (!d || d.modo !== "etcd") { offlineBanner(root); return; }
  const jobs = jobsContar(), esc = evRes("escalabilidad");
  if (!changed("rendimiento", [jobs.map((x) => x.id), esc && [esc.estado, esc.fin, (esc.parcial || []).length], innerWidth, document.documentElement.dataset.theme])) return;
  const best = bestVerified();
  const fastest = jobs.length ? jobs.reduce((a, b) => (b.segundos < a.segundos ? b : a)) : null;
  const procs = best ? nodeProcs(best) : 0;
  const kpis = h("div", { class: "grid kpis" },
    kpiTile({ label: "Mejor tiempo", iconName: "clock", value: fastest ? nf(fastest.segundos, 2) : "—", unit: fastest ? "s" : "", foot: fastest ? `${nf(fastest.bytes / 1e9, 2)} GB · fragmentos de ${fastest.chunk_mb} MB` : "" }),
    kpiTile({ label: "Mejor velocidad", iconName: "zap", value: fastest ? nf(Math.max(...jobs.map((x) => x.gb_s)), 2) : "—", unit: "GB/s", foot: "Todo el clúster junto" }),
    kpiTile({ label: "Speedup verificado", iconName: "trend", value: best ? `${nf(best.speedup, 2)}×` : "—", foot: best ? `${fmtSecs(best.seg_1_nucleo)} con 1 núcleo → ${fmtSecs(best.segundos)}` : "Analice con «Verificar»" }),
    kpiTile({ label: "Eficiencia paralela", iconName: "percent", value: best && procs ? nf(best.speedup / procs * 100, 1) : "—", unit: best ? "%" : "", foot: best ? `speedup ÷ ${procs} procesos` : "" }),
    kpiTile({ label: "Análisis registrados", iconName: "layers", value: nf(jobs.length), foot: "Últimos 30 en etcd" }),
  );

  /* escalabilidad (experimento: 1 → 5 nubes) */
  const ed = esc && (esc.datos || (esc.parcial ? { puntos: esc.parcial } : null));
  const corriendo = esc && (esc.estado === "corriendo" || esc.estado === "en cola");
  const btn = h("button", { class: "btn primary", type: "button", disabled: corriendo || jobRunning() || evRunning() }, ico("play"), corriendo ? "Midiendo…" : "Medir escalabilidad (1 a 5 nubes)");
  btn.addEventListener("click", async () => {
    btn.disabled = true;
    try { await apiPost("/api/eval/ejecutar", { pregunta: "escalabilidad" }); toast("Se lanzaron 5 análisis: 1, 2, 3, 4 y 5 nubes"); pollGlobal(); } catch (e) { toast(`Error: ${e.message}`); btn.disabled = false; }
  });
  const chart = h("div", { class: "chart" });
  const escBody = [h("p", { class: "muted", style: { marginTop: 0 } },
    "Analiza el genoma completo 5 veces, agregando una nube cada vez (USA, Europa, China, Latam, Ecuador), y mide cómo baja el tiempo. Tarda unos 4 minutos.")];
  if (ed && ed.puntos && ed.puntos.length) {
    const pts = ed.puntos, base = ed.base_1_nucleo;
    const sp = pts.map((p) => (base ? base / p.segundos : pts[0].segundos / p.segundos));
    const ideal = pts.map((p) => (base ? p.procesos : p.procesos / pts[0].procesos));
    escBody.push(chart);
    escBody.push(tableEl(["Nubes", "Se agrega", "Procesos", "Tiempo", "GB/s", base ? "Speedup vs. 1 núcleo" : "Speedup vs. 1 nube", "Eficiencia", "Karp-Flatt"],
      pts.map((p, i) => [nf(p.nubes), nube(p.seleccion.slice(-1)[0]), nf(p.procesos), fmtSecs(p.segundos), nf(p.gb_s, 3), `${nf(sp[i], 2)}×`,
        isNum(p.eficiencia) ? `${nf(p.eficiencia, 1)} %` : "—", isNum(p.karp_flatt) ? nf(p.karp_flatt, 3) : "—"])));
    if (ed.conclusion) escBody.push(h("div", { class: "note", style: { marginTop: "12px" } }, ed.conclusion));
    escBody.push(h("p", { class: "muted", style: { marginBottom: 0 } }, "Karp-Flatt estima la fracción del trabajo que no se paraleliza (coordinación, nube más lenta). Si sube al agregar nubes, la sobrecarga crece más rápido que la potencia."));
    requestAnimationFrame(() => lineChart(chart, { xs: pts.map((p) => p.nubes), xName: "Nubes", xLabel: "Número de nubes", fmt: (v) => `${nf(v, 2)}×`,
      series: [{ name: base ? "Speedup medido (vs. 1 núcleo)" : "Speedup medido (vs. 1 nube)", color: "var(--s1)", values: sp },
        { name: "Ideal (proporcional a los procesos)", values: ideal, dashed: true }] }));
  } else if (!corriendo) escBody.push(emptyEl("Todavía no se midió la escalabilidad."));
  if (esc && esc.estado === "error") escBody.push(h("div", { class: "banner bad", style: { marginTop: "10px" } }, `Error: ${esc.error}`));
  const escCard = h("div", { class: "card" }, h("div", { class: "card-head" },
    h("div", {}, h("h2", { class: "card-title" }, "Escalabilidad: de 1 a 5 nubes"), h("p", { class: "card-sub" }, "Speedup al agregar nubes al clúster")), btn), ...escBody);

  /* historial */
  const last = jobs.slice(-12);
  const histChart = h("div", { class: "chart" });
  const chunkGroups = {};
  for (const x of jobs.filter((y) => nubesDe(y).length >= Math.min(5, d.nodos.length))) (chunkGroups[x.chunk_mb] = chunkGroups[x.chunk_mb] || []).push(x.segundos);
  const chunks = Object.keys(chunkGroups).map(Number).sort((a, b) => a - b);
  const chunkChart = h("div", { class: "chart" });
  const lj = lastJob();
  const nodeChart = h("div", { class: "chart" });
  requestAnimationFrame(() => {
    barChart(histChart, { categories: last.map((x) => new Date(x.fin * 1000).toLocaleTimeString(LOCALE, { hour: "2-digit", minute: "2-digit", hour12: false })),
      series: [{ name: "Segundos", color: "var(--s1)", values: last.map((x) => x.segundos) }], fmt: (v) => `${nf(v, 1)} s`, label: "Tiempo por análisis" });
    barChart(chunkChart, { categories: chunks.map((c) => `${c} MB`), series: [{ name: "Tiempo medio", color: "var(--s5)", values: chunks.map((c) => chunkGroups[c].reduce((a, b) => a + b, 0) / chunkGroups[c].length) }],
      fmt: (v) => `${nf(v, 1)} s`, empty: "Analice con 5 nubes y distintos tamaños de fragmento", label: "Tiempo por tamaño de fragmento" });
    if (lj) {
      const ns = (lj.nodos || []).filter((x) => x.fragmentos);
      barChart(nodeChart, { categories: ns.map((x) => nube(x.nodo)), series: [{ name: "GB/s por proceso", color: "var(--s1)", values: ns.map((x) => x.gb_s) }],
        barColors: ns.map((x) => nodeColor(x.nodo)), fmt: (v) => nf(v, 3), label: "Velocidad por proceso" });
    }
  });
  const histTable = tableEl(["Fecha", "Nubes", "Fragmento", "Tiempo", "GB/s", "Speedup", "Verificado"], jobs.slice().reverse().slice(0, 10).map((x) => [
    fmtHora(x.fin), nubesDe(x).map(nube).join(", "), `${x.chunk_mb} MB`, fmtSecs(x.segundos), nf(x.gb_s, 3),
    isNum(x.speedup) ? `${nf(x.speedup, 2)}×` : "—", x.identico === true ? h("span", { style: { color: "var(--good-ink)" } }, "✓ idéntico") : x.identico === false ? h("span", { style: { color: "var(--critical)" } }, "✗ distinto") : "—"]));

  root.replaceChildren(kpis, h("div", { style: { marginTop: "16px" } }, escCard),
    h("div", { class: "grid thirds", style: { marginTop: "16px" } },
      cardEl("Tiempo de cada análisis", "Últimos 12, por hora de fin", histChart),
      cardEl("Efecto del tamaño de fragmento", "Con las 5 nubes: fragmentos chicos = más coordinación entre continentes", chunkChart),
      cardEl("Velocidad por proceso", lj ? `Último análisis (${fmtHora(lj.fin)})` : "", nodeChart)),
    h("div", { style: { marginTop: "16px" } }, cardEl("Historial de análisis", "Los más recientes primero", histTable)));
}

/* ============================================================ 4. MULTICLOUD */
function renderMulticloud() {
  const d = CL.data, root = $("#mc-root");
  if (!d || d.modo !== "etcd") { offlineBanner(root); return; }
  const p4 = evData("p4"), p5 = evData("p5"), lj = lastJob();
  if (!changed("multicloud", [d.nodos.map((n) => [n.nombre, n.potencia_gflops, n.costo_hora, n.costo_mes]), p4 && evRes("p4").fin, p5 && evRes("p5").fin, lj && lj.id, d.red, innerWidth, document.documentElement.dataset.theme])) return;

  const bench = Object.fromEntries(((p4 || {}).filas || []).map((f) => [f.nombre, f]));
  const env = Object.fromEntries(((p5 || {}).filas || []).map((f) => [f.nombre, f]));
  const perNode = Object.fromEntries(((lj || {}).nodos || []).map((x) => [x.nodo, x]));
  const rtt = (n) => {
    const vals = Object.entries(d.red || {}).filter(([k]) => k !== n).map(([, v]) => ((v.destinos || {})[n] || {}).rtt_ms).filter(isNum);
    return vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : null;
  };
  const rows = d.nodos.map((n) => {
    const ch = costHour(n), b = bench[n.nombre] || {}, pn = perNode[n.nombre];
    const gflops = b.gflops || n.potencia_gflops;
    const gbH = pn && lj ? pn.gb / lj.segundos * 3600 : null;            // GB que esta nube procesa por hora
    return { n, ch, gflops, muestras: b.muestras_s, gbUsd: gbH && ch ? gbH / ch : null, gflopsUsd: gflops && ch ? gflops / ch : null, rtt: rtt(n.nombre) };
  });
  const stack = (a, b) => h("span", { style: { display: "block", textAlign: "left", whiteSpace: "normal" } }, a, h("br"), h("span", { class: "muted", style: { fontSize: "12px" } }, b));
  const table = tableEl(["Nube", "Proveedor y ubicación", "Máquina", "GFLOPS", "Cobro", "USD/h", "USD/mes", "GB por USD", "RTT medio"], rows.map((r) => [
    h("span", {}, dot(nodeColor(r.n.nombre)), h("b", {}, nube(r.n.nombre))), stack(providerLabel(r.n.provider), `${r.n.region || "—"} (${r.n.pais || "—"})`),
    stack(`${r.n.instancia || "—"} · ${r.n.cpus} vCPU`, cleanCpu(r.n.modelo)), nf(r.gflops, 1), r.n.costo_hora > 0 ? "por hora" : "mensual fijo",
    nf(r.ch, 4), nf(r.ch * 730, 2), isNum(r.gbUsd) ? nf(r.gbUsd, 0) : "—", isNum(r.rtt) ? `${nf(r.rtt, r.rtt < 10 ? 2 : 0)} ms` : "—"]));

  const c1 = h("div", { class: "chart" }), c2 = h("div", { class: "chart" }), c3 = h("div", { class: "chart" });
  requestAnimationFrame(() => {
    const cats = rows.map((r) => nube(r.n.nombre)), colors = rows.map((r) => nodeColor(r.n.nombre));
    barChart(c1, { categories: cats, series: [{ name: "GB del genoma por dólar", color: "var(--s1)", values: rows.map((r) => r.gbUsd) }], barColors: colors, fmt: (v) => nf(v, 0), empty: "Lance un análisis con las 5 nubes", label: "GB por dólar" });
    barChart(c2, { categories: cats, series: [{ name: "GFLOPS por USD/h", color: "var(--s1)", values: rows.map((r) => r.gflopsUsd) }], barColors: colors, fmt: (v) => nf(v, 0), label: "Potencia por dólar" });
    barChart(c3, { categories: cats, series: [{ name: "RTT medio (ms)", color: "var(--s1)", values: rows.map((r) => r.rtt) }], barColors: colors, fmt: (v) => `${nf(v, v < 10 ? 2 : 0)} ms`, empty: "Pulse «Medir red» en Clúster", label: "Latencia media" });
  });
  const envCard = p5 ? cardEl("El mismo contenedor en 5 proveedores", "Medido en cada nube (Evaluación S11, pregunta 5)",
    tableEl(["Nube", "Imagen", "Arquitectura", "Kernel del host", "SO del contenedor", "API de metadatos"], d.nodos.map((n) => {
      const e = env[n.nombre] || {};
      return [h("span", {}, dot(nodeColor(n.nombre)), nube(n.nombre)), h("span", { class: "mono" }, e.imagen || "—"), e.arquitectura || "—", e.kernel || "—", e.so || "—", e.metadatos || "—"];
    })), h("p", { class: "muted", style: { marginBottom: 0 } }, "Misma imagen y mismo sistema dentro del contenedor; lo que cambia es la máquina de cada proveedor y su API propia: ahí está el riesgo de lock-in."))
    : cardEl("El mismo contenedor en 5 proveedores", "", emptyEl("Ejecute la pregunta 5 en Evaluación S11 para medirlo en cada nube."));

  root.replaceChildren(
    cardEl("Comparación de proveedores", "Datos reales: hardware y tarifas de cada nube, potencia medida y rendimiento del último análisis", table,
      h("p", { class: "muted", style: { marginBottom: 0 } }, "GB por USD = genoma que esa nube procesa en una hora ÷ su tarifa por hora. GFLOPS: prueba de la pregunta 4 (o la medición al arrancar).")),
    h("div", { class: "grid thirds", style: { marginTop: "16px" } },
      cardEl("Rendimiento por dólar", "GB del genoma procesados por cada USD", c1),
      cardEl("Potencia por dólar", "GFLOPS por cada USD/h de tarifa", c2),
      cardEl("Latencia hacia las demás nubes", "Promedio medido por WireGuard", c3)),
    h("div", { style: { marginTop: "16px" } }, envCard));
}
