function $(id) { return document.getElementById(id); }

function switchPage(name) {
  document.querySelectorAll(".nav-btn").forEach((b) => b.classList.toggle("active", b.dataset.page === name));
  document.querySelectorAll(".page").forEach((p) => p.classList.toggle("active", p.id === "page-" + name));
  document.body.classList.toggle("graph-page", name === "graph");
  if (name === "graph") ensureGraphFrame();
}

function ensureGraphFrame() {
  const frame = $("graph-frame");
  if (!frame) return;
  if (!frame.dataset.loaded) {
    frame.src = "/three_layer_graph";
    frame.dataset.loaded = "1";
    return;
  }
  setTimeout(function () {
    if (frame.contentWindow) {
      frame.contentWindow.postMessage({ type: "configpilot-relayout" }, "*");
    }
  }, 80);
}

function reloadGraphFrame() {
  const frame = $("graph-frame");
  if (!frame) return;
  frame.src = "/three_layer_graph?t=" + Date.now();
  frame.dataset.loaded = "1";
}

function showStatus(id, kind, text) {
  const el = $(id);
  el.className = "status show " + kind;
  el.textContent = text;
}

function ns(id) {
  return ($(id) && $(id).value) || "default";
}

const CONN_LABEL = { up: "已连接", down: "未连接", unknown: "未配置" };
let connTimer = null;
let endpointMeta = { fields: [], derived: {} };

function escapeHtml(text) {
  return String(text || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function renderConnectivity(data) {
  const items = data.items || [];
  const up = data.connected_count || 0;
  const total = data.total || items.length || 0;
  if ($("conn-count")) {
    $("conn-count").textContent = up + "/" + total;
    $("conn-count").className = "conn-count " + (up ? "ok" : "bad");
  }
  if ($("conn-sidebar")) {
    $("conn-sidebar").innerHTML = items.map((item) => {
      const label = CONN_LABEL[item.status] || item.status;
      return `<div class="conn-item" title="${escapeHtml(item.detail || item.target || "")}">
        <span class="lamp ${item.status}"></span>
        <span class="conn-name">${escapeHtml(item.name)}</span>
        <span class="conn-state">${label}</span>
      </div>`;
    }).join("");
  }
  if ($("conn-summary")) {
    $("conn-summary").textContent = up
      ? `已连通 ${up} / ${total}。未连通的组件会显示红灯，动态验证前请先确认集群与 Prometheus。`
      : `当前未连通集群或可观测组件（${up} / ${total}）。可离线查看已有报告；接入后点击重新检测。`;
  }
  if ($("conn-overview")) {
    $("conn-overview").innerHTML = items.map((item) => {
      const label = CONN_LABEL[item.status] || item.status;
      return `<div class="conn-card">
        <div class="top">
          <span class="lamp ${item.status}"></span>
          <span class="title">${escapeHtml(item.name)}</span>
        </div>
        <div class="meta">${label}${item.target ? " · " + escapeHtml(item.target) : ""}</div>
        <div class="meta">${escapeHtml(item.detail || "")}</div>
      </div>`;
    }).join("");
  }
}

function collectEndpointValues() {
  const values = {};
  document.querySelectorAll("#endpoint-fields [id^='ep-']").forEach((el) => {
    if (el.tagName !== "INPUT") return;
    values[el.id.slice(3)] = el.value.trim();
  });
  return values;
}

function renderField(field, values, secrets) {
  const isSecret = !!field.secret;
  const raw = values[field.key];
  const val = isSecret ? "" : (raw == null ? "" : raw);
  const configured = isSecret && secrets && secrets[field.key] ? '<span class="env-tag">已配置</span>' : "";
  const env = field.env ? `<span class="env-tag">${escapeHtml(field.env)}</span>` : "";
  const hint = field.hint ? `<div class="field-hint">${escapeHtml(field.hint)}</div>` : "";
  return `<label>${escapeHtml(field.label)} ${env}${configured}
    <input id="ep-${escapeHtml(field.key)}" type="${isSecret ? "password" : "text"}" value="${escapeHtml(val)}" placeholder="${escapeHtml(field.placeholder || "")}" autocomplete="off">
    ${hint}
  </label>`;
}

function renderEndpointFields(data) {
  endpointMeta = data || endpointMeta;
  const box = $("endpoint-fields");
  if (!box) return;
  const values = data.values || {};
  const secrets = data.secrets || {};
  const groups = data.groups && data.groups.length ? data.groups : [{ title: "", hint: "", fields: data.fields || [] }];
  box.innerHTML = groups.map((group) => {
    const fields = (group.fields || []).map((field) => renderField(field, values, secrets)).join("");
    const hint = group.hint ? `<p class="lead" style="margin:6px 0 0">${escapeHtml(group.hint)}</p>` : "";
    return `<div class="ep-section">
      <h3>${escapeHtml(group.title || "")}</h3>
      ${hint}
      <div class="ep-grid">${fields}</div>
    </div>`;
  }).join("");
}

function fillEndpointsFromHost() {
  const host = ($("ep-ssh_host") && $("ep-ssh_host").value.trim()) || "";
  const ingressPort = ($("ep-ingress_port") && $("ep-ingress_port").value.trim()) || "30476";
  if (!host) {
    showStatus("endpoint-status", "err", "请先填写 SSH / 集群主机");
    return;
  }
  if ($("ep-k8s_host")) $("ep-k8s_host").value = host;
  if ($("ep-k8s_port") && !$("ep-k8s_port").value) $("ep-k8s_port").value = "6443";
  if ($("ep-prometheus_url")) $("ep-prometheus_url").value = "http://" + host + ":31012";
  if ($("ep-jaeger_url")) $("ep-jaeger_url").value = "http://" + host + ":16686";
  if ($("ep-zipkin_url")) $("ep-zipkin_url").value = "";
  if ($("ep-kiali_url")) $("ep-kiali_url").value = "http://" + host + ":20001";
  if ($("ep-grafana_url")) $("ep-grafana_url").value = "http://" + host + ":3000";
  if ($("ep-ingress_url")) $("ep-ingress_url").value = "http://" + host + ":" + ingressPort + "/productpage";
  showStatus("endpoint-status", "info", "已按主机填入默认 URL，点击「保存并检测」后生效");
}

async function loadEndpoints() {
  try {
    const { data } = await axios.get("/api/endpoints");
    renderEndpointFields(data);
  } catch (err) {
    showStatus("endpoint-status", "err", "加载地址配置失败：" + (err.message || "未知错误"));
  }
}

async function saveEndpoints() {
  showStatus("endpoint-status", "info", "正在保存地址并重新探测...");
  try {
    const { data } = await axios.put("/api/endpoints", collectEndpointValues(), { timeout: 25000 });
    renderEndpointFields(data);
    if (data.connectivity) renderConnectivity(data.connectivity);
    if (data.values && data.values.ingress_url && $("ingress-url")) {
      $("ingress-url").value = data.values.ingress_url;
    }
    if (data.values && data.values.namespace) {
      const nsVal = data.values.namespace;
      ["stat-ns", "static-namespace", "dynamic-namespace", "consistency-namespace"].forEach((id) => {
        const el = $(id);
        if (!el) return;
        if (el.tagName === "INPUT") el.value = nsVal;
        else el.textContent = nsVal;
      });
    }
    showStatus("endpoint-status", "ok", "已写入 configpilot.json。集群、可观测与一致性容差立即生效，不必重启。");
  } catch (err) {
    showStatus("endpoint-status", "err", "保存失败：" + (err.response?.data?.error || err.message));
  }
}

async function loadConnectivity(force) {
  if (force || !$("conn-sidebar") || !$("conn-sidebar").querySelector(".lamp.up, .lamp.down, .lamp.unknown")) {
    if ($("conn-count")) $("conn-count").textContent = "检测中";
    if ($("conn-sidebar")) {
      $("conn-sidebar").innerHTML = `<div class="conn-item"><span class="lamp pending"></span><span class="conn-name">正在探测…</span></div>`;
    }
  }
  try {
    const url = force ? "/api/connectivity?refresh=1" : "/api/connectivity";
    const { data } = await axios.get(url, { timeout: 20000 });
    renderConnectivity(data);
  } catch (err) {
    if ($("conn-count")) $("conn-count").textContent = "失败";
    if ($("conn-sidebar")) {
      $("conn-sidebar").innerHTML = `<div class="conn-item"><span class="lamp down"></span><span class="conn-name">探测失败</span></div>`;
    }
    if ($("conn-summary")) {
      $("conn-summary").textContent = "连通性探测失败：" + (err.message || "未知错误");
    }
  }
}

async function loadSummary() {
  try {
    const { data } = await axios.get("/api/summary");
    $("stat-reports").textContent = data.report_count;
    $("stat-ns").textContent = data.namespace || "-";
    if (data.latest) {
      const rate = data.latest.consistency_rate;
      $("stat-rate").textContent = typeof rate === "number" ? (rate * 100).toFixed(1) + "%" : "-";
      $("stat-status").textContent = (data.latest.status || "-").toUpperCase();
    } else {
      $("stat-rate").textContent = "-";
      $("stat-status").textContent = "暂无";
    }
  } catch (e) {
    $("stat-reports").textContent = "0";
  }
}

async function runStaticAnalysis() {
  showStatus("static-status", "info", "正在执行静态分析...");
  try {
    const { data } = await axios.post("/api/static/analyze", {
      namespace: ns("static-namespace"),
    });
    const conflictN = (data.conflicts || []).length;
    const meta = (data.graph_data && data.graph_data.metadata) || {};
    showStatus(
      "static-status",
      "ok",
      "静态对齐完成：服务 " + (meta.service_count || (data.services || []).length) +
        "，资源 " + (meta.resource_count || 0) +
        "，跨资源冲突 " + conflictN + " 项"
    );
    renderStaticSummary(data);
    if (data.graph_data) drawGraph(data.graph_data);
  } catch (err) {
    showStatus("static-status", "err", "分析失败: " + (err.response?.data?.error || err.message));
  }
}

function renderStaticSummary(data) {
  const box = $("static-results");
  const s = data.summary || {};
  const conflicts = data.conflicts || [];
  const nsList = ((data.graph_data || {}).metadata || {}).namespaces || [];
  box.innerHTML =
    `<div class="static-stat-row">
      <span>命名空间 <strong>${escapeHtml(nsList.join(", ") || "-")}</strong></span>
      <span>功能对齐 <strong>${s.aligned_pair_count || 0}</strong> / ${s.total_functions || 0}</span>
      <span>期望元组 <strong>${data.expected_tuple_count || s.expected_tuple_count || 0}</strong></span>
    </div>` +
    (conflicts.length
      ? `<div class="conflict-list">${conflicts.map((c) =>
          `<div class="conflict-item"><div class="ttl">${escapeHtml(c.type || c.conflict_type || "冲突")}</div>${escapeHtml(c.description || c.message || JSON.stringify(c))}</div>`
        ).join("")}</div>`
      : "");
}

const KIND_COLOR = {
  service: "#3e8635",
  VirtualService: "#2b9af3",
  DestinationRule: "#ec7a08",
  EnvoyFilter: "#c46162",
  Gateway: "#73bcf7",
  Service: "#6a6e73",
};

let staticGraph = { nodes: [], edges: [], metadata: {} };
let staticSelected = null;

function alignmentClass(status) {
  if (["inconsistent", "mismatched", "control_only", "data_only"].indexOf(status) >= 0) return "inconsistent";
  if (["partial_matched", "partial"].indexOf(status) >= 0) return "partial";
  if (["matched", "consistent"].indexOf(status) >= 0) return "consistent";
  return "unknown";
}

function nodeFill(d) {
  if (d.type === "service") {
    const cls = alignmentClass(d.alignment);
    if (cls === "inconsistent") return "#c46162";
    if (cls === "partial") return "#f0ab00";
    if (cls === "consistent") return "#3e8635";
    return "#6a6e73";
  }
  return KIND_COLOR[d.kind] || "#8a8d90";
}

function visibleStaticNodes() {
  const ns = ($("static-ns-filter") && $("static-ns-filter").value) || "all";
  const typ = ($("static-type-filter") && $("static-type-filter").value) || "all";
  const q = (($("static-search") && $("static-search").value) || "").trim().toLowerCase();
  return (staticGraph.nodes || []).filter((n) => {
    if (ns !== "all" && n.namespace !== ns) return false;
    if (typ === "service" && n.type !== "service") return false;
    if (typ !== "all" && typ !== "service" && n.kind !== typ) return false;
    if (q) {
      const hay = [n.label, n.id, n.namespace, n.kind, n.name].join(" ").toLowerCase();
      if (hay.indexOf(q) < 0) return false;
    }
    const cfgOnly = $("static-cfg-only") && $("static-cfg-only").checked;
    if (cfgOnly) {
      if (n.type === "resource") return true;
      const hasRes = (n.resources || []).length || (n.declarative || []).length;
      const hasCp = (n.functions || []).some((f) =>
        ["matched", "partial_matched", "control_only"].indexOf(f.alignment_status) >= 0
      );
      if (!hasRes && !hasCp) return false;
    }
    return true;
  });
}

function drawGraph(graphData) {
  staticGraph = graphData || { nodes: [], edges: [] };
  const workspace = $("static-workspace");
  if (workspace) workspace.classList.add("on");
  fillStaticFilters();
  bindStaticFilters();
  renderStaticLegend();
  paintStaticGraph();
  renderStaticInspector(null);
}

function fillStaticFilters() {
  const sel = $("static-ns-filter");
  if (!sel) return;
  const current = sel.value || "all";
  const nss = ((staticGraph.metadata || {}).namespaces || []).slice().sort();
  sel.innerHTML = '<option value="all">全部</option>' + nss.map((n) =>
    `<option value="${escapeHtml(n)}">${escapeHtml(n)}</option>`
  ).join("");
  sel.value = nss.indexOf(current) >= 0 || current === "all" ? current : "all";
}

function bindStaticFilters() {
  ["static-ns-filter", "static-type-filter", "static-search", "static-cfg-only"].forEach((id) => {
    const el = $(id);
    if (!el || el.dataset.bound) return;
    el.dataset.bound = "1";
    el.addEventListener(id === "static-search" ? "input" : "change", () => {
      paintStaticGraph();
    });
  });
}

function renderStaticLegend() {
  const box = $("static-legend");
  if (!box) return;
  const items = [
    ["#3e8635", "服务（已对齐）"],
    ["#f0ab00", "服务（部分对齐）"],
    ["#c46162", "服务（不一致 / 单边）"],
    ["#2b9af3", "VirtualService"],
    ["#ec7a08", "DestinationRule"],
    ["#c46162", "EnvoyFilter"],
    ["#73bcf7", "Gateway"],
  ];
  box.innerHTML = items.map(([c, t]) =>
    `<div class="legend-item"><span class="legend-dot" style="background:${c}"></span>${t}</div>`
  ).join("");
}

function layoutStaticNodes(nodes, width, height) {
  const byNs = {};
  nodes.forEach((n) => {
    const key = n.namespace || "default";
    if (!byNs[key]) byNs[key] = { services: [], resources: [] };
    if (n.type === "service") byNs[key].services.push(n);
    else byNs[key].resources.push(n);
  });
  const nss = Object.keys(byNs).sort();
  const colW = Math.max(280, width / Math.max(nss.length, 1));
  nss.forEach((ns, col) => {
    const bucket = byNs[ns];
    const svcX = 36 + col * colW;
    let y = 48;
    const claimed = new Set();
    bucket.services.sort((a, b) => String(a.label).localeCompare(String(b.label)));
    bucket.services.forEach((svc) => {
      svc.x = svcX + 70;
      svc.y = y + 18;
      const owned = bucket.resources.filter((r) =>
        (svc.resources || []).some((ref) => ref.id === r.id)
      );
      owned.forEach((res, i) => {
        res.x = svcX + 190 + (i % 2) * 118;
        res.y = y + 10 + Math.floor(i / 2) * 36;
        claimed.add(res.id);
      });
      const rows = Math.max(1, Math.ceil(owned.length / 2));
      y += Math.max(64, rows * 36 + 28);
    });
    bucket.resources.filter((r) => !claimed.has(r.id)).forEach((res) => {
      res.x = svcX + 70;
      res.y = y + 12;
      y += 40;
    });
  });
  return nss.map((ns, col) => ({ ns, x: 16 + col * colW, y: 18, colW }));
}

function paintStaticGraph() {
  const container = $("graph-container");
  if (!container) return;
  const width = container.clientWidth || 800;
  const height = container.clientHeight || 520;
  const nodes = visibleStaticNodes().map((d) => ({ ...d }));
  d3.select("#graph-container").selectAll("*").remove();
  if (!nodes.length) {
    container.innerHTML = '<div class="empty" style="padding:24px">当前筛选下没有节点。可取消「只显示有声明式配置的节点」查看全部服务。</div>';
    return;
  }

  const idSet = new Set(nodes.map((n) => n.id));
  const edges = (staticGraph.edges || []).filter((e) => idSet.has(e.source) && idSet.has(e.target));
  const headers = layoutStaticNodes(nodes, width, height);

  const svg = d3.select("#graph-container").append("svg")
    .attr("width", width).attr("height", height);
  const root = svg.append("g");
  svg.call(d3.zoom().scaleExtent([0.35, 2.5]).on("zoom", (event) => {
    root.attr("transform", event.transform);
  }));

  root.selectAll("text.ns-head").data(headers).enter().append("text")
    .attr("class", "ns-head")
    .attr("x", (d) => d.x)
    .attr("y", (d) => d.y)
    .attr("fill", "#b8bbbe")
    .attr("font-size", 12)
    .text((d) => d.ns);

  const byId = {};
  nodes.forEach((n) => { byId[n.id] = n; });

  root.append("g").selectAll("path").data(edges).enter().append("path")
    .attr("fill", "none")
    .attr("stroke", (d) => d.type === "declares" ? "#5a5e62" : "#73bcf7")
    .attr("stroke-width", (d) => d.type === "declares" ? 1 : 1.4)
    .attr("stroke-dasharray", (d) => d.type === "declares" ? "4 3" : null)
    .attr("d", (d) => {
      const s = byId[d.source];
      const t = byId[d.target];
      if (!s || !t) return "";
      const mx = (s.x + t.x) / 2;
      return `M${s.x},${s.y} Q${mx},${s.y} ${t.x},${t.y}`;
    });

  root.append("g").selectAll("text.elabel").data(edges.filter((e) => e.type === "route" && e.label)).enter().append("text")
    .attr("class", "elabel")
    .attr("x", (d) => (byId[d.source].x + byId[d.target].x) / 2)
    .attr("y", (d) => (byId[d.source].y + byId[d.target].y) / 2 - 4)
    .attr("fill", "#b8bbbe")
    .attr("font-size", 10)
    .attr("text-anchor", "middle")
    .text((d) => d.label);

  const g = root.append("g").selectAll("g.node").data(nodes).enter().append("g")
    .attr("class", "node")
    .attr("transform", (d) => `translate(${d.x},${d.y})`)
    .style("cursor", "pointer")
    .on("click", (event, d) => {
      event.stopPropagation();
      staticSelected = d.id;
      paintStaticGraph();
      renderStaticInspector(d);
    });

  svg.on("click", () => {
    staticSelected = null;
    paintStaticGraph();
    renderStaticInspector(null);
  });

  g.append("rect")
    .attr("x", (d) => d.type === "service" ? -64 : -52)
    .attr("y", (d) => d.type === "service" ? -16 : -12)
    .attr("width", (d) => d.type === "service" ? 128 : 104)
    .attr("height", (d) => d.type === "service" ? 32 : 24)
    .attr("rx", 2)
    .attr("fill", nodeFill)
    .attr("stroke", (d) => d.id === staticSelected ? "#f0f0f0" : "transparent")
    .attr("stroke-width", 2);

  g.append("text")
    .attr("text-anchor", "middle")
    .attr("dy", (d) => d.type === "service" ? 0 : 4)
    .attr("fill", "#fff")
    .attr("font-size", 11)
    .text((d) => {
      const name = d.type === "service" ? d.label : (d.name || d.label);
      return String(name).length > 14 ? String(name).slice(0, 13) + "…" : name;
    });

  g.filter((d) => d.type === "service").append("text")
    .attr("text-anchor", "middle")
    .attr("dy", 12)
    .attr("fill", "rgba(255,255,255,0.85)")
    .attr("font-size", 9)
    .text((d) => d.namespace);
}

function renderStaticInspector(node) {
  const box = $("static-inspect");
  if (!box) return;
  if (!node) {
    box.innerHTML = '<div class="empty">点击节点查看命名空间、声明式配置和对应服务的数据面规则。</div>';
    return;
  }
  const full = (staticGraph.nodes || []).find((n) => n.id === node.id) || node;
  if (full.type === "resource") {
    box.innerHTML = resourceInspectorHtml(full);
    return;
  }
  box.innerHTML = serviceInspectorHtml(full);
  box.querySelectorAll("[data-res]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const target = (staticGraph.nodes || []).find((n) => n.id === btn.dataset.res);
      if (target) {
        staticSelected = target.id;
        paintStaticGraph();
        renderStaticInspector(target);
      }
    });
  });
}

function serviceInspectorHtml(d) {
  const funcs = (d.functions || []).map((f) =>
    `<span class="badge ${alignmentClass(f.alignment_status)}">${escapeHtml(f.function_type)} · ${escapeHtml(f.alignment_status)}</span>`
  ).join(" ");
  const subsets = (d.subsets || []).length ? (d.subsets || []).join(", ") : "—";
  const resBtns = (d.resources || []).map((r) =>
    `<button type="button" class="res-btn" data-res="${escapeHtml(r.id)}">${escapeHtml(r.kind)}/${escapeHtml(r.name)} <span style="color:var(--muted)">${escapeHtml(r.namespace)}</span></button>`
  ).join("");
  const manifests = (d.declarative || []).map((m) =>
    `<div class="sec-title">${escapeHtml((m.kind || "Resource") + "/" + ((m.metadata || {}).name || ""))}</div><pre>${escapeHtml(JSON.stringify(m, null, 2))}</pre>`
  ).join("");
  const dps = (d.data_plane_rules || []).map(dataPlaneBlock).join("");
  return `
    <div class="insp-title">${escapeHtml(d.label)}</div>
    <dl class="kv">
      <dt>命名空间</dt><dd>${escapeHtml(d.namespace || "default")}</dd>
      <dt>类型</dt><dd>服务</dd>
      <dt>对齐</dt><dd><span class="badge ${alignmentClass(d.alignment)}">${escapeHtml(d.alignment || "unknown")}</span></dd>
      <dt>subset</dt><dd>${escapeHtml(subsets)}</dd>
    </dl>
    <div class="sec-title">功能</div>
    <div>${funcs || "—"}</div>
    <div class="sec-title">声明式资源</div>
    ${resBtns || '<div class="empty" style="padding:0">无控制面资源</div>'}
    ${manifests}
    <div class="sec-title">数据面规则</div>
    ${dps || '<div class="empty" style="padding:0">无对应数据面规则</div>'}
  `;
}

function resourceInspectorHtml(d) {
  const manifests = (d.declarative || []).map((m) =>
    `<pre>${escapeHtml(JSON.stringify(m, null, 2))}</pre>`
  ).join("");
  const svc = (staticGraph.nodes || []).find((n) =>
    n.type === "service" && (n.resources || []).some((r) => r.id === d.id)
  );
  const dp = svc ? (svc.data_plane_rules || []).map(dataPlaneBlock).join("") : "";
  return `
    <div class="insp-title">${escapeHtml(d.kind || "Resource")}/${escapeHtml(d.name || d.label)}</div>
    <dl class="kv">
      <dt>命名空间</dt><dd>${escapeHtml(d.namespace || "default")}</dd>
      <dt>类型</dt><dd>声明式资源</dd>
      <dt>kind</dt><dd>${escapeHtml(d.kind || "")}</dd>
      <dt>作用服务</dt><dd>${svc ? escapeHtml(svc.namespace + "/" + svc.label) : "—"}</dd>
    </dl>
    <div class="sec-title">声明式配置</div>
    ${manifests || "—"}
    <div class="sec-title">对应服务的数据面规则</div>
    ${dp || '<div class="empty" style="padding:0">该资源未关联到已对齐服务，或服务尚无数据面规则</div>'}
  `;
}

function dataPlaneBlock(rule) {
  const status = rule.alignment_status || "";
  const lines = [];
  if (rule.hosts) lines.push("hosts: " + (Array.isArray(rule.hosts) ? rule.hosts.join(", ") : rule.hosts));
  (rule.routes || []).forEach((route) => {
    const match = route.match || {};
    const uri = (match.uri && (match.uri.prefix || match.uri.exact || match.uri.regex)) || match.prefix || "/";
    const dests = (route.destinations || []).map((dest) => {
      const host = dest.subset || dest.host || "";
      return dest.weight != null ? host + " " + dest.weight + "%" : host;
    }).join(" / ");
    lines.push("route " + uri + " → " + dests);
  });
  if (rule.timeout) lines.push("timeout: " + rule.timeout);
  if (rule.retry_policy) lines.push("retry: " + JSON.stringify(rule.retry_policy));
  if (rule.algorithm) lines.push("lb: " + rule.algorithm);
  if (rule.rules) lines.push("rate_limit: " + JSON.stringify(rule.rules));
  if (rule.connection_pool) lines.push("connection_pool: " + JSON.stringify(rule.connection_pool));
  if (rule.outlier_detection) lines.push("outlier: " + JSON.stringify(rule.outlier_detection));
  if (rule.envoy_clusters) {
    rule.envoy_clusters.forEach((c) => lines.push("cluster " + (c.name || "") + " lb=" + (c.lb_policy || "") + " timeout=" + (c.connect_timeout || "")));
  }
  if (rule.envoy_routes) {
    rule.envoy_routes.forEach((r) => {
      const match = (r.match && (r.match.prefix || JSON.stringify(r.match))) || "/";
      lines.push("envoy " + match + " cluster=" + (r.cluster || "") + (r.weighted_clusters ? " weighted" : ""));
    });
  }
  if (rule.destinations) {
    lines.push("destinations: " + JSON.stringify(rule.destinations));
  }
  return `<div class="dp-block">
    <div class="ttl">${escapeHtml(rule.function_type || "rule")} <span class="badge ${alignmentClass(status)}">${escapeHtml(status || "")}</span></div>
    <pre>${escapeHtml(lines.join("\n") || JSON.stringify(rule, null, 2))}</pre>
  </div>`;
}

async function generateTestMatrix() {
  showStatus("dynamic-status", "info", "正在生成测试矩阵...");
  try {
    const { data } = await axios.post("/api/dynamic/generate", {
      namespace: ns("dynamic-namespace"),
      ingress_url: $("ingress-url").value,
    });
    showStatus("dynamic-status", "ok", "测试矩阵已生成，共 " + data.total_cases + " 个用例");
    $("dynamic-results").innerHTML = "<pre>" + JSON.stringify(data, null, 2) + "</pre>";
  } catch (err) {
    showStatus("dynamic-status", "err", "生成失败: " + (err.response?.data?.error || err.message));
  }
}

async function runDynamicTests() {
  showStatus("dynamic-status", "info", "正在执行动态测试...");
  try {
    const { data } = await axios.post("/api/dynamic/run_tests", { namespace: ns("dynamic-namespace") });
    showStatus("dynamic-status", "ok", "动态测试完成");
    $("dynamic-results").innerHTML = "<pre>" + JSON.stringify(data, null, 2) + "</pre>";
  } catch (err) {
    showStatus("dynamic-status", "err", "执行失败: " + (err.response?.data?.error || err.message));
  }
}

async function buildConsistencyGraph() {
  showStatus("consistency-status", "info", "正在根据对齐产物生成三层图...");
  try {
    const { data } = await axios.post("/api/consistency/graph", {
      namespace: ns("consistency-namespace"),
    });
    showStatus("consistency-status", "ok", "三层图已生成，可在「三层依赖图」中交互查看");
    const box = $("reports-container");
    box.innerHTML = "<pre>" + JSON.stringify({
      summary: data.summary,
      conflicts: data.conflicts,
      graph_path: data.graph_path,
    }, null, 2) + "</pre>";
    reloadGraphFrame();
  } catch (err) {
    showStatus("consistency-status", "err", "构图失败: " + (err.response?.data?.error || err.message));
  }
}

async function runPipeline() {
  showStatus("consistency-status", "info", "正在执行完整流水线...");
  try {
    const { data } = await axios.post("/api/run_pipeline", { namespace: ns("consistency-namespace") });
    showStatus("consistency-status", "ok", "流水线完成，报告 " + data.report_id);
    await loadReports();
    await loadSummary();
  } catch (err) {
    showStatus("consistency-status", "err", "执行失败: " + (err.response?.data?.error || err.message));
  }
}

async function loadReports() {
  const box = $("reports-container");
  box.innerHTML = "<p class='lead'>加载中...</p>";
  try {
    const { data } = await axios.get("/api/reports");
    const reports = data.reports || [];
    if (!reports.length) {
      box.innerHTML = "<p class='lead'>暂无报告。请先执行完整流水线。</p>";
      return;
    }
    box.innerHTML = reports.map((r) => {
      const cls = (r.status || "unknown").toLowerCase();
      return `<div class="report-item">
        <div>
          <strong>${r.title || r.id}</strong>
          <div class="lead" style="margin:4px 0 0">${r.id} · ${r.timestamp || ""}</div>
        </div>
        <div>
          <span class="badge ${cls}">${(r.status || "unknown").toUpperCase()}</span>
          <a class="btn secondary" style="margin-left:8px;text-decoration:none" href="/api/report/${r.id}" target="_blank">详情</a>
          <a class="btn secondary" style="margin-left:8px;text-decoration:none" href="/three_layer_graph?report_id=${encodeURIComponent(r.id)}" target="_blank">三层图</a>
        </div>
      </div>`;
    }).join("");
  } catch (err) {
    box.innerHTML = "<p class='lead'>加载失败: " + err.message + "</p>";
  }
}

document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll(".nav-btn").forEach((btn) => {
    btn.addEventListener("click", () => switchPage(btn.dataset.page));
  });
  const refresh = () => loadConnectivity(true);
  if ($("conn-refresh-btn")) $("conn-refresh-btn").addEventListener("click", refresh);
  if ($("conn-refresh-overview")) $("conn-refresh-overview").addEventListener("click", refresh);
  if ($("ep-save-btn")) $("ep-save-btn").addEventListener("click", saveEndpoints);
  if ($("ep-fill-btn")) $("ep-fill-btn").addEventListener("click", fillEndpointsFromHost);
  loadSummary();
  loadReports();
  loadEndpoints();
  loadConnectivity(false);
  connTimer = setInterval(() => loadConnectivity(false), 30000);
});
