/* =============================================================================
   ADN Multinube - Sección «Evaluación S11»
   Cada pregunta de la evaluación es un EXPERIMENTO que corre en las 5 nubes
   (app/evaluacion.py). Aquí se lanzan y se muestran sus resultados.
   Solo DEFINE funciones; las ejecuta app.js.
   ============================================================================= */
"use strict";

const EV_TITLES = {
  p1: "Latencia y rendimiento transaccional",
  p2: "Soberanía de datos y cumplimiento normativo",
  p3: "Costos, egreso de datos y modelo financiero",
  p4: "Cómputo especializado para IA y Big Data",
  p5: "Multinube y mitigación del vendor lock-in",
  p6: "Almacenamiento masivo y redundancia geográfica",
  p7: "Borde (edge), 5G e IoT",
  p8: "SLA, disponibilidad y red internacional",
};
const EV_INFO = {
  p1: { q: "¿Un DC local TIER III o una región de un hiperescalar de EE. UU. garantiza un RTT menor a 15 ms para autorizar pagos?",
    eq: [["DC local TIER III (Telconet)", "Telecu, Guayaquil"], ["Hiperescalar de EE. UU. (AWS/Azure)", "AWS, Ohio"]],
    how: "Desde Ecuador (el banco) se envían 60 autorizaciones reales a un microservicio en cada nube y se mide el tiempo de ida y vuelta." },
  p2: { q: "¿Qué implica guardar registros ciudadanos en la nube estatal, en un soberano europeo o en un hiperescalar de EE. UU.?",
    eq: [["a) Nube estatal (CNT EP)", "Telecu, Ecuador"], ["b) Soberano europeo (OVHcloud)", "OVHcloud, Alemania"], ["c) Hiperescalar de EE. UU.", "AWS, EE. UU."]],
    how: "Cada nube consulta su IP pública real (ipinfo) para verificar dónde está físicamente, y se procesa el genoma solo con servidores en Ecuador." },
  p3: { q: "Para una startup con mucho video saliente: ¿pago por uso de EE. UU., nube asiática barata o VPS local de tarifa fija? ¿Dónde está el sobrecosto oculto?",
    eq: [["AWS/Azure (pago por uso)", "AWS"], ["Alibaba/Tencent (bajo costo)", "Huawei Cloud"], ["Telconet/Netlife (tarifa fija)", "Telecu y DonWeb"]],
    how: "Se mide la capacidad real de salida de cada nube hacia Ecuador (descargando 32 MB) y se calcula el costo con 1, 10 y 50 TB al mes." },
  p4: { q: "Para entrenar deep learning: ¿proveedores de EE. UU. o asiáticos? Aceleradores, flexibilidad y madurez.",
    eq: [["Vertex AI / SageMaker (EE. UU.)", "AWS"], ["ModelArts / ApsaraDB (Asia)", "Huawei Cloud"]],
    how: "Cada nube mide sus GFLOPS y entrena la misma red neuronal (60.000 muestras, misma semilla); se busca si tiene GPU o NPU." },
  p5: { q: "¿Qué complejidad tiene orquestar varias nubes (APIs, gobernanza, costos duplicados)?",
    eq: [["Multinacionales (Azure, IBM)", "AWS, OVHcloud, Huawei"], ["Integradores regionales (Sonda, Movistar)", "DonWeb y Telecu"]],
    how: "Se verifica que las 5 nubes ejecutan la misma imagen, se detecta la API propia de cada una y el mando del clúster se pasa por los 5 proveedores." },
  p6: { q: "Durabilidad de 11 nueves: ¿STaaS global con varias zonas o almacenamiento privado local? ¿Cuál es el trade-off?",
    eq: [["STaaS global (S3/GCS)", "Réplicas en 4 continentes"], ["Almacenamiento local (Internexa/Telconet)", "Copia en Telecu"]],
    how: "Desde Ecuador se recupera el mismo bloque de 64 MB del genoma de la copia local y de cada réplica remota, y se comprueba que sean idénticos." },
  p7: { q: "Sensores que exigen respuesta inmediata: ¿borde asiático o infraestructura regional?",
    eq: [["KT Cloud / Huawei (Asia)", "Huawei, Hong Kong"], ["Internexa / Claro (regional)", "DonWeb y Telecu"]],
    how: "200 sensores simulados en Ecuador envían 40 lotes; se compara decidir en el borde local con mandar cada lote a una nube lejana." },
  p8: { q: "Si se corta el cable submarino, ¿qué pasa con una solución 100 % en nubes globales? ¿Cómo ayuda la nube híbrida local?",
    eq: [["Nube híbrida local (Telconet/Sonda)", "Telecu, Ecuador"], ["Nubes públicas globales", "AWS, OVHcloud, Huawei, DonWeb"]],
    how: "Se simula el corte: las 4 nubes extranjeras quedan aisladas. Se mide quién toma el mando y si el servicio local sigue respondiendo; luego se restablece." },
};
const QS = ["p1", "p2", "p3", "p4", "p5", "p6", "p7", "p8"];

async function evRun(pregunta, btn) {
  if (btn) btn.disabled = true;
  try {
    await apiPost("/api/eval/ejecutar", { pregunta });
    toast(pregunta === "todas" ? "Ejecutando las 8 pruebas en las nubes (unos 5 minutos)" : `Ejecutando ${pregunta.toUpperCase()} en las nubes`);
    pollGlobal();
  } catch (e) { toast(`Error: ${e.message}`); if (btn) btn.disabled = false; }
}

function renderEvaluacion() {
  const root = $("#ev-root"), d = CL.data;
  if (!d || d.modo !== "etcd") { offlineBanner(root); return; }
  const ev = (S.ev && S.ev.resultados) || {};
  if (!changed("evaluacion", [QS.map((q) => [ev[q] && ev[q].estado, ev[q] && ev[q].fin]), jobRunning(), innerWidth, document.documentElement.dataset.theme])) return;

  const busy = evRunning() || jobRunning();
  const listas = QS.filter((q) => (ev[q] || {}).estado === "listo").length;
  const all = h("button", { class: "btn primary", type: "button", disabled: busy }, ico("play"), "Ejecutar las 8 pruebas");
  all.addEventListener("click", () => evRun("todas", all));
  const cur = QS.find((q) => (ev[q] || {}).estado === "corriendo");
  const head = h("div", { class: "card" },
    h("div", { class: "card-head" },
      h("div", {}, h("h2", { class: "card-title" }, "Las 8 preguntas, resueltas con nuestro clúster"),
        h("p", { class: "card-sub" }, `${listas} de 8 ejecutadas${cur ? ` · ahora: ${cur.toUpperCase()} (${EV_TITLES[cur]})` : ""}${jobRunning() ? " · hay un análisis de ADN en curso" : ""}`)),
      all),
    h("div", { class: "progress", style: { marginBottom: "14px" } }, h("span", { style: { width: `${listas / 8 * 100}%` } })),
    h("p", { style: { marginTop: 0 } }, "Cada pregunta nombra proveedores que no tenemos; se reemplazan por su equivalente real en el clúster y se ",
      h("b", {}, "mide"), " lo que la pregunta plantea. El cliente de cada prueba (el banco, la institución, la startup, los sensores) está en Ecuador."),
    tableEl(["En la pregunta", "En nuestro clúster", "Por qué"], [
      ["CNT EP · Telconet · DC local TIER III", h("span", {}, dot(nodeColor("ecuador")), "Telecu Cloud (Guayaquil)"), "Centro de datos dentro de Ecuador (AS23246)"],
      ["AWS · Azure · hiperescalar de EE. UU.", h("span", {}, dot(nodeColor("usa")), "AWS (Ohio)"), "Mismo proveedor; sujeto al CLOUD Act"],
      ["OVHcloud (soberano europeo)", h("span", {}, dot(nodeColor("europa")), "OVHcloud (Fráncfort)"), "Mismo proveedor"],
      ["Alibaba · Tencent · Huawei · KT Cloud", h("span", {}, dot(nodeColor("china")), "Huawei Cloud (Hong Kong)"), "Proveedor asiático; Alibaba pidió pasaporte"],
      ["Sonda · Movistar · Internexa · Claro · Netlife", h("span", {}, dot(nodeColor("latam")), "DonWeb (Argentina) y Telecu"), "Proveedores regionales de tarifa fija"],
    ]));

  const cards = QS.map((q) => evCard(q, ev[q], busy));
  root.replaceChildren(head, ...cards.map((c) => h("div", { style: { marginTop: "16px" } }, c)));
}

function evCard(q, v, busy) {
  const info = EV_INFO[q];
  v = v || {};
  const data = v.datos || (v.estado === "corriendo" || v.estado === "en cola" ? v.anterior : null);
  const btn = h("button", { class: "btn", type: "button", disabled: busy }, ico("play"), v.estado === "listo" ? "Repetir" : "Ejecutar");
  btn.addEventListener("click", () => evRun(q, btn));
  const status = v.estado === "listo" ? `Ejecutada ${fmtHora(v.fin)} · ${nf(v.segundos, 1)} s`
    : v.estado === "corriendo" ? "Ejecutándose en las nubes…" : v.estado === "en cola" ? "En cola" : v.estado === "error" ? "Falló" : "Sin ejecutar";
  const eqs = h("div", { style: { display: "flex", flexWrap: "wrap", gap: "6px", margin: "8px 0 12px" } },
    info.eq.map(([a, b]) => h("span", { class: "tag" }, `${a} → `, h("b", {}, b))));
  const body = [];
  if (v.estado === "error") body.push(h("div", { class: "banner bad", style: { marginBottom: "12px" } }, `Error: ${v.error}`));
  if (v.estado === "corriendo") body.push(h("div", { class: "progress indeterminate", style: { marginBottom: "12px" } }, h("span", {})));
  if (data) {
    body.push(h("div", { class: "note", style: { marginBottom: "14px" } }, h("b", {}, "Respuesta: "), data.conclusion || ""));
    try { body.push(...EV_VIEWS[q](data)); } catch (e) { body.push(emptyEl(`No se pudo dibujar: ${e.message}`)); }
  } else if (v.estado !== "corriendo") body.push(emptyEl("Pulse «Ejecutar» para hacer la prueba en las nubes."));
  return h("div", { class: "card", id: `ev-${q}` },
    h("div", { class: "card-head" },
      h("div", {}, h("h2", { class: "card-title" }, `Pregunta ${q.slice(1)} · ${EV_TITLES[q]}`),
        h("p", { class: "card-sub" }, info.q)),
      h("div", { style: { display: "flex", gap: "10px", alignItems: "center" } }, stateChip(v.estado), btn)),
    eqs,
    h("p", { class: "muted", style: { margin: "0 0 12px" } }, h("b", {}, "Experimento: "), info.how, " ", h("span", { class: "ink2" }, `(${status})`)),
    ...body);
}

const nodeCell = (n, extra) => h("span", {}, dot(nodeColor(n)), h("b", {}, nube(n)), extra ? h("span", { class: "muted" }, ` · ${extra}`) : null);
const yes = (ok, t1 = "Sí", t2 = "No") => h("span", { style: { color: ok ? "var(--good-ink)" : "var(--critical)", fontWeight: 650 } }, ok ? `✓ ${t1}` : `✗ ${t2}`);
const chartBox = (fn) => { const c = h("div", { class: "chart" }); requestAnimationFrame(() => fn(c)); return c; };
const ms = (v) => (isNum(v) ? `${nf(v, v < 10 ? 2 : 1)} ms` : "—");

const EV_VIEWS = {
  p1(d) {
    const f = d.filas;
    return [
      chartBox((c) => barChart(c, { categories: f.map((x) => nube(x.nombre)), series: [{ name: "RTT p99", color: "var(--s1)", values: f.map((x) => x.p99) }],
        barColors: f.map((x) => nodeColor(x.nombre)), fmt: ms, ref: { value: 15, label: "límite del banco: 15 ms" }, label: "RTT p99 por nube" })),
      tableEl(["Nube (rol)", "p50", "p95", "p99", "Jitter", "< 15 ms", "Distancia", "Mín. físico"], f.map((x) => [
        nodeCell(x.nombre, x.rol), ms(x.p50), ms(x.p95), ms(x.p99), ms(x.jitter), `${nf(x.bajo_15, 0)} %`, `${nf(x.km)} km`, ms(x.minimo_fisico_ms)])),
    h("p", { class: "muted", style: { marginBottom: 0 } }, "Mínimo físico = distancia ÷ 100 km por ms (la luz en la fibra, ida y vuelta, sin contar equipos). Ninguna nube lejana puede bajar de ese número.")];
  },
  p2(d) {
    const out = [tableEl(["Nube (opción)", "Declarada", "IP pública", "Detectada", "Red (ASN)", "¿Coincide?", "Ley aplicable", "Implicación"], d.filas.map((x) => [
      nodeCell(x.nombre, x.rol), x.pais, h("span", { class: "mono" }, x.ip || "—"), `${x.ciudad || "—"} (${x.pais_real || "—"})`, x.org || "—",
      x.coincide == null ? "sin dato" : yes(x.coincide), x.ley, h("span", { style: { whiteSpace: "normal" } }, x.nota)]))];
    if (d.soberano) {
      const s = d.soberano;
      out.push(h("div", { class: "grid kpis", style: { marginTop: "14px", gridTemplateColumns: "repeat(4, minmax(0, 1fr))" } },
        kpiTile({ label: "Análisis soberano", iconName: "globe", value: s.nubes.map(nube).join(", "), foot: "Solo servidores en Ecuador" }),
        kpiTile({ label: "Genoma procesado", iconName: "file", value: nf(s.gb, 2), unit: "GB", foot: `GC ${nf(s.gc, 2)} %` }),
        kpiTile({ label: "Tiempo", iconName: "clock", value: nf(s.segundos, 1), unit: "s", foot: "Más lento, pero dentro del país" }),
        kpiTile({ label: "Datos enviados fuera", iconName: "shield", value: nf(s.bytes_red), unit: "B", foot: "Sin transferencia internacional" })));
    }
    return out;
  },
  p3(d) {
    const f = d.filas, esc = d.escenarios_tb;
    const cost = (x, i) => {
      const e = x.escenarios[i];
      return h("span", {}, `USD ${nf(e.total_usd, 0)}`, e.satura ? h("span", { style: { color: "var(--critical)", fontWeight: 650 } }, " · se satura") : null);
    };
    return [h("div", { class: "grid halves" },
      chartBox((c) => barChart(c, { categories: f.map((x) => nube(x.nombre)), series: [{ name: "Capacidad de salida medida", color: "var(--s1)", values: f.map((x) => x.mbps_medido) }],
        barColors: f.map((x) => nodeColor(x.nombre)), fmt: (v) => `${nf(v, 0)} Mbit/s`, label: "Salida medida hacia Ecuador" })),
      chartBox((c) => barChart(c, { categories: f.map((x) => nube(x.nombre)), series: [{ name: `Costo mensual con ${esc.at(-1)} TB`, color: "var(--s2)", values: f.map((x) => x.escenarios.at(-1).total_usd) }],
        barColors: f.map((x) => nodeColor(x.nombre)), fmt: (v) => `USD ${nf(v, 0)}`, label: "Costo mensual con 50 TB" }))),
    tableEl(["Nube (modelo)", "Cobro del egreso", "Salida medida", ...esc.map((t) => `Total con ${t} TB/mes`)], f.map((x) => [
      nodeCell(x.nombre, x.rol), h("span", { style: { whiteSpace: "normal" } }, x.egress), isNum(x.mbps_medido) ? `${nf(x.mbps_medido, 0)} Mbit/s` : "—", ...esc.map((_, i) => cost(x, i))])),
    h("p", { class: "muted", style: { marginBottom: 0 } }, `Total = VM del mes + egreso. Pico supuesto = 3 × el promedio (${nf(f[0].escenarios.at(-1).mbps_promedio, 0)} Mbit/s promedio con ${esc.at(-1)} TB). «Se satura» = el pico supera la capacidad. ${d.nota || ""}`)];
  },
  p4(d) {
    const f = d.filas.filter((x) => x.gflops);
    return [h("div", { class: "grid halves" },
      chartBox((c) => barChart(c, { categories: f.map((x) => nube(x.nombre)), series: [{ name: "GFLOPS", color: "var(--s1)", values: f.map((x) => x.gflops) }],
        barColors: f.map((x) => nodeColor(x.nombre)), fmt: (v) => nf(v, 1), label: "GFLOPS por nube" })),
      chartBox((c) => barChart(c, { categories: f.map((x) => nube(x.nombre)), series: [{ name: "Muestras/s al entrenar", color: "var(--s1)", values: f.map((x) => x.muestras_s) }],
        barColors: f.map((x) => nodeColor(x.nombre)), fmt: (v) => nf(v, 0), label: "Entrenamiento" }))),
    tableEl(["Nube (rol)", "CPU", "GFLOPS", "Entrenamiento", "Precisión", "Acelerador", "GFLOPS por USD/h"], d.filas.map((x) => [
      nodeCell(x.nombre, x.rol), `${x.cpus} vCPU`, nf(x.gflops, 1), x.muestras_s ? `${nf(x.muestras_s)} muestras/s` : (x.error || "—"),
      isNum(x.precision) ? `${nf(x.precision, 2)} %` : "—", x.acelerador || "—", nf(x.gflops_usd, 0)])),
    h("p", { class: "muted", style: { marginBottom: 0 } }, "Referencia: un acelerador de entrenamiento entrega cientos o miles de TFLOPS; estas CPU, decenas de GFLOPS. Por eso el entrenamiento real se hace con GPU, TPU o NPU, y ahí el código queda atado al hardware del proveedor.")];
  },
  p5(d) {
    const out = [tableEl(["Nube (rol)", "Imagen", "Arquitectura", "Kernel del host", "API de metadatos", "Cobro", "USD/mes"], d.filas.map((x) => [
      nodeCell(x.nombre, x.rol), h("span", { class: "mono" }, x.imagen || "—"), x.arquitectura || "—", x.kernel || "—", x.metadatos || "—",
      x.cobro_fijo ? "mensual fijo" : "por hora", nf(x.costo_mes, 2)]))];
    if ((d.traspasos || []).length) {
      out.push(h("h3", { style: { fontSize: "14px", margin: "16px 0 6px" } }, "El mando del clúster pasó por los 5 proveedores"));
      out.push(tableEl(["De", "A", "Tiempo de traspaso"], d.traspasos.map((t) => [
        nodeCell(t.de, providerLabel(t.de_prov)), nodeCell(t.a, providerLabel(t.a_prov)), isNum(t.segundos) ? `${nf(t.segundos, 2)} s` : "no se completó"])));
    }
    out.push(h("p", { class: "muted", style: { marginBottom: 0 } }, `Costo de operar las 5 nubes: USD ${nf(d.costo_mes_total, 2)} al mes. Sin la capa común (Docker + etcd + WireGuard), cada traspaso exigiría integrar la API de cada proveedor.`));
    return out;
  },
  p6(d) {
    const l = d.lecturas.filter((x) => !x.error);
    return [h("div", { class: "grid halves" },
      chartBox((c) => barChart(c, { categories: l.map((x) => (x.local ? "Local" : nube(x.nombre))), series: [{ name: "Recuperar 64 MB", color: "var(--s1)", values: l.map((x) => x.segundos) }],
        barColors: l.map((x) => nodeColor(x.nombre)), fmt: (v) => `${nf(v, v < 1 ? 2 : 1)} s`, label: "Tiempo de recuperación" })),
      tableEl(["Réplicas", "Pérdida anual", "Durabilidad"], d.durabilidad.map((x) => [nf(x.replicas), x.perdida.toExponential(0), `${x.durabilidad} (${x.nueves} nueves)`]))),
    tableEl(["Copia (rol)", "Distancia", "Tiempo", "Velocidad", "SHA-256 del bloque", "¿Idéntica?"], d.lecturas.map((x) => [
      nodeCell(x.nombre, x.rol), `${nf(x.km)} km`, x.error ? x.error : `${nf(x.segundos, 2)} s`, x.mb_s ? `${nf(x.mb_s, 1)} MB/s` : "—",
      h("span", { class: "mono" }, x.sha256 ? shortHash(x.sha256) : "—"), x.error ? "—" : yes(x.identico)])),
    h("p", { class: "muted", style: { marginBottom: 0 } }, `Modelo de durabilidad: cada sitio pierde sus datos con probabilidad ${nf(d.p_sitio * 100, 0)} % al año (supuesto) y las fallas son independientes; con k réplicas, la pérdida es ${nf(d.p_sitio, 2)}^k. S3 declara 11 nueves con más copias dentro de cada zona.`)];
  },
  p7(d) {
    const f = d.filas;
    return [
      chartBox((c) => barChart(c, { categories: f.map((x) => nube(x.nombre)), series: [{ name: "Reacción p95", color: "var(--s1)", values: f.map((x) => x.p95) }],
        barColors: f.map((x) => nodeColor(x.nombre)), fmt: ms, label: "Tiempo de reacción" })),
      tableEl(["Dónde se decide", "p50", "p95", "Distancia", "Alarmas", "Datos hacia la nube"], f.map((x) => [
        nodeCell(x.nombre, x.rol), ms(x.p50), ms(x.p95), `${nf(x.km)} km`, nf(x.alarmas),
        x.nombre === "ecuador" ? `${fmtBytes(x.bytes_resumen)} (resumen)` : `${fmtBytes(x.bytes_crudos)} (crudos)`])),
    h("p", { class: "muted", style: { marginBottom: 0 } }, `Todas las nubes detectan las mismas alarmas (la lógica es la misma imagen); lo que cambia es cuánto tardan en contestar y cuántos datos viajan. Umbral de alarma: 85 °C.`)];
  },
  p8(d) {
    return [h("div", { class: "grid halves" },
      tableEl(["Segundo", "Qué pasó"], d.pasos.map((p) => [`${nf(p.t, 1)} s`, h("span", { style: { whiteSpace: "normal", display: "block", textAlign: "left" } }, p.evento)])),
      tableEl(["Servicio en", "Disponibilidad", "p50", "Intentos"], d.filas.map((x) => [
        nodeCell(x.nombre, x.nacional ? "en Ecuador" : "fuera del país"),
        h("b", { style: { color: x.disponibilidad >= 99 ? "var(--good-ink)" : "var(--critical)" } }, `${nf(x.disponibilidad, 0)} %`), ms(x.p50), nf(x.intentos)]))),
    h("p", { class: "muted", style: { marginBottom: 0 } }, `Quórum de etcd: ${d.quorum} de ${d.miembros.length} miembros; en Ecuador: ${d.miembros_locales.map(nube).join(", ") || "ninguno"}. El corte se simula marcando las nubes extranjeras como apagadas: no se toca la red real.`)];
  },
};
