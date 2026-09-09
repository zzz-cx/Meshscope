function $(id) { return document.getElementById(id); }

function switchPage(name) {
  document.querySelectorAll(".nav-btn").forEach((b) => b.classList.toggle("active", b.dataset.page === name));
  document.querySelectorAll(".page").forEach((p) => p.classList.toggle("active", p.id === "page-" + name));
  document.body.classList.toggle("graph-page", name === "graph");
  if (name === "graph") ensureGraphFrame();
  if (name === "static") loadClusterSnapshot();
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
    const key = el.id.slice(3);
    if (el.tagName === "SELECT") {
      values[key] = el.value;
      return;
    }
    if (el.tagName !== "INPUT") return;
    if (el.type === "checkbox") {
      values[key] = el.checked;
      return;
    }
    values[key] = el.value.trim();
  });
  return values;
}

function isTruthy(value) {
  return value === true || value === "true" || value === 1 || value === "1";
}

function renderField(field, values, secrets) {
  if (field.type === "heading") {
    return `<div class="ep-heading">${escapeHtml(field.label || "")}</div>`;
  }
  const isSecret = !!field.secret;
  const raw = values[field.key];
  const val = isSecret ? "" : (raw == null ? "" : raw);
  const configured = isSecret && secrets && secrets[field.key] ? '<span class="env-tag">已配置</span>' : "";
  const env = field.env ? `<span class="env-tag">${escapeHtml(field.env)}</span>` : "";
  const hint = field.hint ? `<div class="field-hint">${escapeHtml(field.hint)}</div>` : "";
  if (field.type === "checkbox") {
    const checked = raw == null || isTruthy(raw) ? " checked" : "";
    return `<label class="ep-check">${env}${configured}
      <span class="ep-check-row"><input id="ep-${escapeHtml(field.key)}" type="checkbox"${checked}>${escapeHtml(field.label)}</span>
      ${hint}
    </label>`;
  }
  if (field.type === "select") {
    const current = raw == null ? "" : String(raw);
    const opts = (field.options || []).map((opt) => {
      const ov = opt && typeof opt === "object" ? String(opt.value) : String(opt);
      const ol = opt && typeof opt === "object" ? String(opt.label) : String(opt);
      const sel = ov === current ? " selected" : "";
      return `<option value="${escapeHtml(ov)}"${sel}>${escapeHtml(ol)}</option>`;
    }).join("");
    return `<label>${escapeHtml(field.label)} ${env}${configured}
      <select id="ep-${escapeHtml(field.key)}">${opts}</select>
      ${hint}
    </label>`;
  }
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
    return `<div class="ep-section${group.wide ? " ep-wide" : ""}" data-id="${escapeHtml(group.id || "")}">
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
    if ($("stat-findings")) {
      $("stat-findings").textContent = (data.storage && data.storage.findings != null) ? data.storage.findings : "-";
    }
    if ($("stat-ns")) $("stat-ns").textContent = data.namespace || "-";
    if ($("storage-summary") && data.storage) {
      $("storage-summary").textContent =
        "SQLite · " + (data.storage.path || "results/meshscope.db") +
        " · 报告 " + (data.storage.reports ?? 0) +
        " · 检验记录 " + (data.storage.findings ?? 0) +
        " · 图 " + (data.storage.graphs ?? 0);
    }
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

let clusterSnapshotLoaded = false;

async function loadClusterSnapshot(force) {
  if (clusterSnapshotLoaded && !force) return;
  const status = $("static-status");
  if (status) showStatus("static-status", "info", "正在加载集群快照…");
  try {
    const { data } = await axios.get("/api/static/snapshot");
    if (!data.success) throw new Error(data.error || "快照不可用");
    clusterSnapshotLoaded = true;
    const meta = (data.graph_data && data.graph_data.metadata) || {};
    const nsList = data.namespaces || meta.namespaces || [];
    if (status) {
      showStatus(
        "static-status",
        "ok",
        "已加载集群快照" + (data.generated_at ? "（" + data.generated_at + "）" : "") +
          "：命名空间 " + (nsList.join(", ") || "-") +
          "，服务 " + (meta.service_count || 0) +
          "，资源 " + (meta.resource_count || 0)
      );
    }
    renderStaticSummary(data);
    if (data.graph_data) drawGraph(data.graph_data);
  } catch (err) {
    if (status) showStatus("static-status", "err", "加载集群快照失败: " + (err.response?.data?.error || err.message));
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

function specView(m) {
  const kind = m.kind || "Resource";
  const name = (m.metadata && m.metadata.name) || "";
  const spec = m.spec || {};
  const bits = [];
  if (kind === "VirtualService") {
    if (spec.hosts) bits.push(`<div><dt>hosts</dt><dd>${escapeHtml((spec.hosts || []).join(", "))}</dd></div>`);
    if (spec.gateways) bits.push(`<div><dt>gateways</dt><dd>${escapeHtml((spec.gateways || []).join(", "))}</dd></div>`);
    (spec.http || []).forEach((http, idx) => {
      const match = http.match || {};
      const uri = (match.uri && (match.uri.prefix || match.uri.exact || match.uri.regex)) || match.uri || "*";
      const dests = (http.route || []).map((r) => {
        const dest = r.destination || {};
        const label = [dest.host, dest.subset].filter(Boolean).join("/") || "?";
        return r.weight != null ? label + " " + r.weight + "%" : label;
      }).join(" / ");
      const extra = [];
      if (http.timeout) extra.push("timeout " + http.timeout);
      if (http.retries) extra.push("retry " + (http.retries.attempts || "") + " " + (http.retries.retryOn || ""));
      bits.push(`<div class="route-line">http[${idx}] ${escapeHtml(String(uri))} → ${escapeHtml(dests)}${extra.length ? " · " + escapeHtml(extra.join(" · ")) : ""}</div>`);
    });
  } else if (kind === "DestinationRule") {
    bits.push(`<div><dt>host</dt><dd>${escapeHtml(spec.host || "—")}</dd></div>`);
    const subsets = (spec.subsets || []).map((s) => s.name).filter(Boolean);
    if (subsets.length) bits.push(`<div><dt>subsets</dt><dd>${escapeHtml(subsets.join(", "))}</dd></div>`);
    const tp = spec.trafficPolicy || {};
    if (tp.connectionPool) bits.push(`<div><dt>连接池</dt><dd>${escapeHtml(fmtCompact(tp.connectionPool))}</dd></div>`);
    if (tp.outlierDetection) bits.push(`<div><dt>outlier</dt><dd>${escapeHtml(fmtCompact(tp.outlierDetection))}</dd></div>`);
    if (tp.loadBalancer) bits.push(`<div><dt>负载均衡</dt><dd>${escapeHtml(fmtCompact(tp.loadBalancer))}</dd></div>`);
  } else if (kind === "Gateway") {
    bits.push(`<div><dt>selector</dt><dd>${escapeHtml(fmtCompact(spec.selector || {}))}</dd></div>`);
    (spec.servers || []).forEach((s, idx) => {
      const port = (s.port && (s.port.number + "/" + (s.port.protocol || ""))) || "";
      bits.push(`<div class="route-line">server[${idx}] ${escapeHtml(port)} hosts=${escapeHtml((s.hosts || []).join(", "))}</div>`);
    });
  } else {
    Object.keys(spec).slice(0, 8).forEach((k) => {
      const val = spec[k];
      if (val == null || typeof val === "object") return;
      bits.push(`<div><dt>${escapeHtml(k)}</dt><dd>${escapeHtml(String(val))}</dd></div>`);
    });
  }
  return `<div class="manifest">
    <div class="sec-title">${escapeHtml(kind + "/" + name)}</div>
    <dl class="facts" style="grid-template-columns:repeat(2,1fr)">${bits.filter((b) => b.includes("<dt>")).join("")}</dl>
    ${bits.filter((b) => b.includes("route-line")).join("")}
    <details class="raw"><summary>原始字段</summary><pre>${escapeHtml(JSON.stringify(m, null, 2))}</pre></details>
  </div>`;
}

function serviceInspectorHtml(d) {
  const funcs = (d.functions || []).map((f) =>
    `<span class="badge ${alignmentClass(f.alignment_status)}">${escapeHtml(f.function_type)} · ${escapeHtml(f.alignment_status)}</span>`
  ).join(" ");
  const subsets = (d.subsets || []).length ? (d.subsets || []).join(", ") : "—";
  const resBtns = (d.resources || []).map((r) =>
    `<button type="button" class="res-btn" data-res="${escapeHtml(r.id)}">${escapeHtml(r.kind)}/${escapeHtml(r.name)} <span style="color:var(--muted)">${escapeHtml(r.namespace)}</span></button>`
  ).join("");
  const manifests = (d.declarative || []).map(specView).join("");
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
  const manifests = (d.declarative || []).map(specView).join("");
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
  if (rule.retry_policy) lines.push("retry: " + fmtCompact(rule.retry_policy));
  if (rule.algorithm) lines.push("lb: " + rule.algorithm);
  if (rule.rules) lines.push("rate_limit: " + fmtCompact(rule.rules));
  if (rule.connection_pool) lines.push("connection_pool: " + fmtCompact(rule.connection_pool));
  if (rule.outlier_detection) lines.push("outlier: " + fmtCompact(rule.outlier_detection));
  if (rule.envoy_clusters) {
    rule.envoy_clusters.forEach((c) => lines.push("cluster " + (c.name || "") + " lb=" + (c.lb_policy || "") + " timeout=" + (c.connect_timeout || "")));
  }
  if (rule.envoy_routes) {
    rule.envoy_routes.forEach((r) => {
      const match = (r.match && (r.match.prefix || fmtCompact(r.match))) || "/";
      lines.push("envoy " + match + " cluster=" + (r.cluster || "") + (r.weighted_clusters ? " weighted" : ""));
    });
  }
  if (rule.destinations) {
    const dests = (rule.destinations || []).map((d) => {
      const name = d.subset || d.host || "?";
      return d.weight != null ? name + " " + d.weight + "%" : name;
    }).join(" / ");
    lines.push("destinations: " + dests);
  }
  return `<div class="dp-block">
    <div class="ttl">${escapeHtml(rule.function_type || "rule")} <span class="badge ${alignmentClass(status)}">${escapeHtml(status || "")}</span></div>
    ${lines.map((line) => `<div class="route-line">${escapeHtml(line)}</div>`).join("") || '<div class="empty" style="padding:0">无规则摘要</div>'}
  </div>`;
}

function renderMatrixView(data) {
  const cases = (data.test_matrix && data.test_matrix.test_cases) || data.test_cases || [];
  const kpis = `<div class="result-kpis">
    <div class="card"><h3>用例数</h3><div class="num">${cases.length || data.total_cases || 0}</div></div>
  </div>`;
  if (!cases.length) return kpis + "<p class='lead'>矩阵为空</p>";
  const rows = cases.map((c) => {
    const req = c.request_params || {};
    const load = c.load_params || {};
    return `<tr>
      <td class="mono">${esc(c.case_id)}</td>
      <td>${esc(c.description || c.name || "—")}</td>
      <td>${esc((c.test_strategies || []).join(", ") || c.type || "—")}</td>
      <td class="mono">${esc(req.host || c.source_service || "—")}${req.path ? " " + esc(req.path) : ""}</td>
      <td>${load.num_requests != null ? esc(load.num_requests) + " × " + esc(load.concurrency || 1) : "—"}</td>
    </tr>`;
  }).join("");
  return kpis + `<table class="result-table">
    <thead><tr><th>用例</th><th>说明</th><th>策略</th><th>目标</th><th>负载</th></tr></thead>
    <tbody>${rows}</tbody>
  </table>`;
}

function renderHttpResultView(data) {
  const results = data.http_results || {};
  const ids = Object.keys(results);
  const kpis = `<div class="result-kpis">
    <div class="card"><h3>执行用例</h3><div class="num">${data.total_cases || ids.length}</div></div>
    <div class="card"><h3>有结果</h3><div class="num">${ids.length}</div></div>
  </div>`;
  if (!ids.length) return kpis + "<p class='lead'>没有 HTTP 执行结果</p>";
  const rows = ids.map((id) => {
    const r = results[id] || {};
    const codes = r.status_codes
      ? (Array.isArray(r.status_codes) ? r.status_codes.join(", ") : fmtCompact(r.status_codes))
      : "—";
    const rate = r.success_rate != null ? (Number(r.success_rate) <= 1 ? (r.success_rate * 100).toFixed(1) + "%" : r.success_rate + "%") : "—";
    const lat = r.avg_response_time != null ? Number(r.avg_response_time).toFixed(0) + " ms" : "—";
    return `<tr>
      <td class="mono">${esc(id)}</td>
      <td>${esc(r.total_requests ?? "—")}</td>
      <td>${esc(rate)}</td>
      <td>${esc(lat)}</td>
      <td>${esc(codes)}</td>
      <td>${esc(r.error_count ?? 0)}</td>
    </tr>`;
  }).join("");
  return kpis + `<table class="result-table">
    <thead><tr><th>用例</th><th>请求</th><th>成功率</th><th>平均时延</th><th>状态码</th><th>错误</th></tr></thead>
    <tbody>${rows}</tbody>
  </table>`;
}

async function generateTestMatrix() {
  showStatus("dynamic-status", "info", "正在生成测试矩阵...");
  try {
    const { data } = await axios.post("/api/dynamic/generate", {
      namespace: ns("dynamic-namespace"),
      ingress_url: $("ingress-url").value,
    });
    showStatus("dynamic-status", "ok", "测试矩阵已生成，共 " + data.total_cases + " 个用例");
    $("dynamic-results").innerHTML = renderMatrixView(data);
  } catch (err) {
    showStatus("dynamic-status", "err", "生成失败: " + (err.response?.data?.error || err.message));
  }
}

async function runDynamicTests() {
  showStatus("dynamic-status", "info", "正在执行动态测试...");
  try {
    const { data } = await axios.post("/api/dynamic/run_tests", { namespace: ns("dynamic-namespace") });
    showStatus("dynamic-status", "ok", "动态测试完成");
    $("dynamic-results").innerHTML = renderHttpResultView(data);
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
    const summary = data.summary || {};
    const conflicts = data.conflicts || [];
    const note = $("graph-summary");
    if (note) {
      note.innerHTML = `<div class="graph-note">三层图已生成。对齐 ${esc(summary.aligned_pair_count ?? summary.total_pairs ?? "—")} 对 · 冲突 ${conflicts.length} 条。可在「三层依赖图」中查看。
        ${conflicts.length ? `<div class="conflict-list">${conflicts.slice(0, 6).map((c) =>
          `<div class="conflict-item"><div class="ttl">${esc(c.type || c.conflict_type || "冲突")}</div>${esc(c.description || c.message || "")}</div>`
        ).join("")}</div>` : ""}
      </div>`;
    }
    showStatus("consistency-status", "ok", "三层图已生成，可在「三层依赖图」中交互查看");
    reloadGraphFrame();
  } catch (err) {
    showStatus("consistency-status", "err", "构图失败: " + (err.response?.data?.error || err.message));
  }
}

async function runPipeline() {
  showStatus("consistency-status", "info", "正在执行完整流水线...");
  try {
    const { data } = await axios.post("/api/run_pipeline", { namespace: ns("consistency-namespace") });
    showStatus("consistency-status", "ok", "流水线完成，已写出 JSON 与 HTML 报告 " + data.report_id);
    await loadReports();
    await loadSummary();
    if (data.report_id) await openReport(data.report_id);
  } catch (err) {
    showStatus("consistency-status", "err", "执行失败: " + (err.response?.data?.error || err.message));
  }
}

function esc(v) {
  return String(v == null ? "" : v)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function joinList(arr) {
  return (arr || []).filter(Boolean).join(", ") || "—";
}

function fmtCompact(val) {
  if (val == null || val === "") return "";
  if (typeof val === "string" || typeof val === "number" || typeof val === "boolean") return String(val);
  if (Array.isArray(val)) return val.map(fmtCompact).filter(Boolean).join(", ");
  if (typeof val === "object") {
    return Object.entries(val).map(([k, v]) => {
      if (v == null) return "";
      if (typeof v === "object") return k + "=" + fmtCompact(v);
      return k + "=" + v;
    }).filter(Boolean).join(" · ");
  }
  return String(val);
}

const TYPE_NAMES = {
  control_only: "仅控制面",
  data_only: "仅数据面",
  mismatched: "平面语义不匹配",
  partial_matched: "部分匹配",
  timeout_mismatch: "超时不一致",
  behavior_deviation: "运行时行为偏差",
  traffic_split_drift: "流量分割漂移",
  scope_mismatch: "作用范围未覆盖",
  policy_not_verified: "策略未验证",
  missing_subset: "Subset 缺失",
  gateway_unmatched: "Gateway 未匹配",
  gateway_selector_empty: "Gateway 选择器为空",
  gateway_selector_conflict: "Gateway 选择器冲突",
  route_priority_conflict: "路由优先级冲突",
  policy_conflict: "策略冲突",
};

function destItems(tup) {
  const cons = (tup && tup.constraint) || {};
  const actual = (tup && tup.actual) || {};
  const expected = (tup && tup.expected) || {};
  const from = cons.destinations || actual.destinations || expected.destinations;
  if (Array.isArray(from) && from.length) {
    return from.map((d) => ({ name: d.subset || d.host || "?", weight: Number(d.weight) }));
  }
  const weights = cons.weights || actual.weights || expected.weights;
  if (weights && typeof weights === "object") {
    return Object.entries(weights).map(([name, weight]) => ({ name, weight: Number(weight) }));
  }
  return [];
}

function fmtMatch(pred) {
  if (!pred || typeof pred !== "object" || !Object.keys(pred).length) return "";
  const bits = [];
  const uri = pred.uri || pred.prefix || pred.path;
  if (uri && typeof uri === "object") {
    const key = Object.keys(uri)[0];
    bits.push((key || "uri") + "=" + uri[key]);
  } else if (uri) {
    bits.push("uri=" + uri);
  }
  if (pred.headers) bits.push("headers=" + fmtCompact(pred.headers));
  if (pred.method) bits.push("method=" + fmtCompact(pred.method));
  if (pred.fault) bits.push("fault=" + pred.fault);
  const used = { uri: 1, prefix: 1, path: 1, headers: 1, method: 1, fault: 1 };
  Object.keys(pred).forEach((k) => {
    if (!used[k] && pred[k] != null && typeof pred[k] !== "object") bits.push(k + "=" + pred[k]);
  });
  return bits.join(" · ");
}

function weightBars(items) {
  if (!items || !items.length) return "";
  const total = items.reduce((sum, item) => sum + (Number.isFinite(item.weight) ? Math.max(0, item.weight) : 0), 0) || 100;
  return `<div class="wbar">${items.map((item) => {
    const pct = Number.isFinite(item.weight) ? item.weight : 0;
    const width = Math.max(0, pct) / total * 100;
    return `<div class="wseg" style="width:${width}%" title="${esc(item.name)} ${pct}%"><span>${esc(item.name)} ${pct}%</span></div>`;
  }).join("")}</div>`;
}

function tupleFields(tup) {
  if (!tup) return {};
  const fields = {};
  const match = fmtMatch(tup.predicate);
  if (match) fields["匹配"] = match;
  const action = (tup.action && tup.action.type) || "";
  if (action && action !== "observe") fields["动作"] = action;
  const scope = tup.scope || {};
  if (scope.service) fields["服务"] = scope.service;
  if (scope.namespace) fields["命名空间"] = scope.namespace;
  if (scope.source) fields["来源"] = scope.source;
  const subsets = [].concat(scope.subsets || []).filter(Boolean);
  if (subsets.length) fields["Subset"] = subsets.join(", ");
  const dests = destItems(tup);
  if (dests.length) fields["分流"] = dests;
  const skip = { destinations: 1, weights: 1 };
  Object.keys(tup.constraint || {}).forEach((key) => {
    const val = tup.constraint[key];
    if (skip[key] || val == null || typeof val === "object") return;
    fields[key] = String(val);
  });
  if (tup.expected && Object.keys(tup.expected).length) {
    if (tup.expected.weights || tup.expected.destinations) fields["期望分流"] = destItems({ constraint: tup.expected, actual: {}, expected: {} });
    else fields["期望"] = fmtCompact(tup.expected);
  }
  if (tup.actual && Object.keys(tup.actual).length) {
    if (tup.actual.weights || tup.actual.destinations) fields["实测分流"] = destItems({ constraint: tup.actual, actual: {}, expected: {} });
    else fields["实测"] = fmtCompact(tup.actual);
  }
  if (tup.test_case_id) fields["用例"] = tup.test_case_id;
  if (tup.verified === false) fields["结果"] = "未通过";
  if (tup.verified === true) fields["结果"] = "通过";
  if (tup.function_type) fields["功能"] = tup.function_type;
  return fields;
}

function fieldKey(val) {
  if (Array.isArray(val) && val[0] && val[0].name != null) {
    return val.map((item) => item.name + ":" + item.weight).join("|");
  }
  return String(val == null ? "" : val);
}

function renderFieldValue(val) {
  if (val == null || val === "") return `<span class="empty-cell">—</span>`;
  if (Array.isArray(val) && val[0] && val[0].name != null) return weightBars(val);
  return esc(val);
}

function renderTupleCompare(decl, dp, rt) {
  const planes = [
    { tag: "Sdecl", label: "声明", fields: tupleFields(decl) },
    { tag: "Sdp", label: "数据面", fields: tupleFields(dp) },
    { tag: "Srt", label: "运行时", fields: tupleFields(rt) },
  ];
  const order = ["匹配", "动作", "服务", "命名空间", "来源", "Subset", "分流", "期望分流", "实测分流", "期望", "实测", "结果", "用例", "功能"];
  const keys = [];
  const seen = {};
  order.concat(planes.flatMap((p) => Object.keys(p.fields))).forEach((key) => {
    if (seen[key]) return;
    if (planes.some((p) => key in p.fields)) {
      seen[key] = 1;
      keys.push(key);
    }
  });
  if (!keys.length) {
    const summary = (decl && decl.summary) || (dp && dp.summary) || (rt && rt.summary);
    return summary ? `<p class="lead">${esc(summary)}</p>` : "<p class='lead'>本条没有可对照的语义字段</p>";
  }
  const body = keys.map((key) => {
    const vals = planes.map((p) => p.fields[key]);
    const present = vals.map(fieldKey).filter(Boolean);
    const differ = present.length > 1 && present.some((v) => v !== present[0]);
    return `<tr class="${differ ? "diff" : ""}">
      <td class="k">${esc(key)}</td>
      ${vals.map((v) => `<td class="v">${renderFieldValue(v)}</td>`).join("")}
    </tr>`;
  }).join("");
  return `<table class="cmp">
    <thead><tr><th></th>
      <th><span class="plane">Sdecl</span> 声明</th>
      <th><span class="plane">Sdp</span> 数据面</th>
      <th><span class="plane">Srt</span> 运行时</th>
    </tr></thead>
    <tbody>${body}</tbody>
  </table>`;
}

function typeLabel(r) {
  const key = r.inconsistency_type || r.type || "";
  return TYPE_NAMES[key] || key || "未分类";
}

function findingKey(r, idx) {
  return r.id || r.inconsistency_id || String(idx);
}

function renderFindingDetail(r) {
  const raw = {
    predicate_action_scope_constraint: {
      Sdecl: r.Sdecl || r.s_decl,
      Sdp: r.Sdp || r.s_dp,
      Srt: r.Srt || r.s_rt,
    },
    static_expectation: r.static_expectation,
    dynamic_observation: r.dynamic_observation,
    details: r.details,
  };
  return `
    <p class="lead">${esc(r.description || typeLabel(r))}</p>
    <dl class="facts">
      <div><dt>资源</dt><dd>${esc(r.resource_kind || "—")} / ${esc(r.resource_name || "—")}</dd></div>
      <div><dt>受影响服务</dt><dd>${esc(joinList(r.affected_services))}</dd></div>
      <div><dt>Subset</dt><dd>${esc(joinList(r.affected_subsets))}</dd></div>
      <div><dt>功能 / 对齐</dt><dd>${esc(r.function_type || "—")} · ${esc(r.alignment_status || "—")}</dd></div>
    </dl>
    ${renderTupleCompare(r.Sdecl || r.s_decl, r.Sdp || r.s_dp, r.Srt || r.s_rt)}
    <div class="cause"><strong>根因</strong> ${esc(r.root_cause || "待确认")}</div>
    ${(r.suggestions || []).length ? `<ul class="sugs">${r.suggestions.map((s) => `<li>${esc(s)}</li>`).join("")}</ul>` : ""}
    <details class="raw"><summary>原始数据</summary><pre>${esc(JSON.stringify(raw, null, 2))}</pre></details>
  `;
}

function reportRecords(data) {
  return data.records
    || data.detailed_findings
    || (data.consistency_check && data.consistency_check.inconsistencies)
    || [];
}

let currentReport = null;
let reportLayerFilter = "all";
let reportQuery = "";
let openFindingId = "";

function paintReportFindings() {
  const box = $("findings-list");
  const drawer = $("finding-drawer");
  if (!box || !currentReport) return;
  const records = reportRecords(currentReport);
  const rows = records.filter((r) => {
    if (reportLayerFilter !== "all" && r.layer !== reportLayerFilter) return false;
    if (!reportQuery) return true;
    const text = [
      r.inconsistency_type, r.type, TYPE_NAMES[r.inconsistency_type], r.description,
      r.resource_kind, r.resource_name,
      (r.affected_services || []).join(" "), (r.affected_subsets || []).join(" "),
    ].join(" ").toLowerCase();
    return text.includes(reportQuery);
  });

  // 根据当前筛选结果，找到被选中的那条 record
  const selected = openFindingId
    ? rows.find((r, idx) => findingKey(r, idx) === openFindingId)
    : null;

  if (drawer) {
    if (!selected) {
      drawer.innerHTML = `<div class="panel"><p class="lead">点击左侧记录查看详情</p></div>`;
    } else {
      drawer.innerHTML = `<div class="panel">${renderFindingDetail(selected)}</div>`;
    }
  }

  if (!rows.length) {
    box.innerHTML = "<p class='lead'>当前筛选下没有记录</p>";
    if (drawer) {
      drawer.innerHTML = `<div class="panel"><p class="lead">当前筛选下没有可查看的详情</p></div>`;
    }
  } else {
    box.innerHTML = `<table class="finding-table">
      <thead><tr><th>级别</th><th>类型</th><th>资源</th><th>服务</th><th>层次</th></tr></thead>
      <tbody>${rows.map((r, idx) => {
        const id = findingKey(r, idx);
        const sev = (r.severity || "medium").toLowerCase();
        const layer = r.layer || "layer2";
        const open = openFindingId === id;
        return `<tr class="finding-row${open ? " on" : ""}" data-fid="${esc(id)}">
          <td><span class="badge sev-${esc(sev)}">${esc((r.severity || "").toUpperCase())}</span></td>
          <td>${esc(typeLabel(r))}<div class="lead" style="margin:2px 0 0">${esc(r.inconsistency_type || "")}</div></td>
          <td class="mono">${esc(r.resource_kind || "—")} / ${esc(r.resource_name || "—")}</td>
          <td>${esc(joinList(r.affected_services))}</td>
          <td><span class="badge ${esc(layer)}">${esc(r.layer_name || layer)}</span></td>
        </tr>
        `;
      }).join("")}</tbody>
    </table>`;
    box.querySelectorAll(".finding-row").forEach((row) => {
      row.addEventListener("click", () => {
        openFindingId = openFindingId === row.dataset.fid ? "" : row.dataset.fid;
        paintReportFindings();
      });
    });
  }
  const shown = $("findings-shown");
  if (shown) shown.textContent = rows.length + " / " + records.length;
}

async function openReport(reportId) {
  const box = $("report-detail");
  if (!box) return;
  box.innerHTML = "<div class='panel'><p class='lead'>加载报告…</p></div>";
  try {
    const { data } = await axios.get("/api/report/" + encodeURIComponent(reportId));
    if (data.error) {
      box.innerHTML = "<div class='panel'><p class='lead'>" + esc(data.error) + "</p></div>";
      return;
    }
    currentReport = data;
    reportLayerFilter = "all";
    reportQuery = "";
    openFindingId = "";
    const cc = data.consistency_check || {};
    const meta = data.metadata || {};
    const layers = meta.layers || (cc.summary && cc.summary.layers) || [];
    const checks = meta.checks_performed || (cc.summary && cc.summary.checks_performed) || [];
    const records = reportRecords(data);
    const byLayer = Object.assign({}, (cc.summary && cc.summary.by_layer) || {});
    if (!Object.keys(byLayer).length) {
      records.forEach((r) => { if (r.layer) byLayer[r.layer] = (byLayer[r.layer] || 0) + 1; });
    }
    const status = (cc.overall_status || "unknown").toLowerCase();
    const rate = typeof cc.consistency_rate === "number" ? (cc.consistency_rate * 100).toFixed(1) + "%" : "—";
    box.innerHTML = `
      <div class="panel">
        <div class="panel-head">
          <div>
            <h2>${esc(data.title || reportId)}</h2>
            <p class="lead" style="margin:6px 0 0">${esc(data.namespace || "")} · ${esc(data.timestamp || "")} · <code>${esc(reportId)}</code></p>
          </div>
          <div class="row">
            <span class="badge ${esc(status)}">${esc((cc.overall_status || "unknown").toUpperCase())}</span>
            <a class="btn secondary" style="text-decoration:none" href="/api/report/${encodeURIComponent(reportId)}" target="_blank">JSON</a>
            <a class="btn secondary" style="text-decoration:none" href="/api/report/${encodeURIComponent(reportId)}/html" target="_blank">HTML</a>
            <a class="btn secondary" style="text-decoration:none" href="/three_layer_graph?report_id=${encodeURIComponent(reportId)}" target="_blank">三层图</a>
          </div>
        </div>
        <div class="cards" style="margin-top:14px">
          <div class="card"><h3>一致性率</h3><div class="num">${esc(rate)}</div></div>
          <div class="card"><h3>检验记录</h3><div class="num">${records.length}</div></div>
          <div class="card"><h3>第一层</h3><div class="num">${byLayer.layer1 || 0}</div></div>
          <div class="card"><h3>第二层</h3><div class="num">${byLayer.layer2 || 0}</div></div>
        </div>
        <h2 style="margin-top:8px">检验了什么</h2>
        <p class="lead">按三层图展开：全局平面对齐（Sdecl ↔ Sdp）、服务关系上的运行时偏差（Srt）、配置资源之间的引用冲突。</p>
        <div class="layer-grid">
          ${layers.map((l) => `
            <div class="layer-card" data-layer="${esc(l.id)}">
              <h3>${esc(l.name)} <span class="count">${byLayer[l.id] || 0}</span></h3>
              <p>${esc(l.what)}</p>
              <ul>${(l.checks || []).map((c) => `<li><code>${esc(c.type)}</code> ${esc(c.name)}</li>`).join("")}</ul>
            </div>`).join("") || "<p class='lead'>此报告尚未包含层次说明（请重新跑流水线）。</p>"}
        </div>
        ${checks.length ? `
        <details class="raw" open>
          <summary>检验项目（${checks.length}）</summary>
          <table class="check-table">
            <thead><tr><th>层次</th><th>类型</th><th>说明</th></tr></thead>
            <tbody>${checks.map((c) => `<tr>
              <td>${esc(c.layer_name || c.layer)}</td>
              <td>${esc(c.name)} <code>${esc(c.type)}</code></td>
              <td>${esc(c.description)}</td>
            </tr>`).join("")}</tbody>
          </table>
        </details>` : ""}
        <h2>检验记录 <span id="findings-shown" style="color:var(--muted);font-weight:500;font-size:13px"></span></h2>
        <div class="report-three">
          <div class="report-mid">
            <div class="report-toolbar">
              <button class="chip on" data-layer="all" type="button">全部</button>
              <button class="chip" data-layer="layer1" type="button">第一层</button>
              <button class="chip" data-layer="layer2" type="button">第二层</button>
              <button class="chip" data-layer="layer3" type="button">第三层</button>
              <input class="chip-search" id="finding-q" placeholder="搜索类型 / 资源 / 服务…">
            </div>
            <div id="findings-list"></div>
          </div>
          <aside class="report-drawer" id="finding-drawer">
            <div class="panel"><p class="lead">点击左侧记录查看详情</p></div>
          </aside>
        </div>
        ${(data.recommendations || []).length ? `<h2>建议</h2><ul class="recs">${data.recommendations.map((s) => `<li>${esc(s)}</li>`).join("")}</ul>` : ""}
      </div>`;
    box.querySelectorAll(".chip[data-layer]").forEach((btn) => {
      btn.addEventListener("click", () => {
        box.querySelectorAll(".chip[data-layer]").forEach((b) => b.classList.remove("on"));
        btn.classList.add("on");
        reportLayerFilter = btn.dataset.layer;
        paintReportFindings();
      });
    });
    const input = $("finding-q");
    if (input) input.addEventListener("input", () => {
      reportQuery = input.value.trim().toLowerCase();
      paintReportFindings();
    });
    paintReportFindings();
    document.querySelectorAll(".report-item").forEach((el) => {
      el.classList.toggle("active", el.dataset.id === reportId);
    });
  } catch (err) {
    box.innerHTML = "<div class='panel'><p class='lead'>加载失败: " + esc(err.message) + "</p></div>";
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
      const rate = typeof r.consistency_rate === "number" ? (r.consistency_rate * 100).toFixed(1) + "%" : "";
      return `<div class="report-item" data-id="${esc(r.id)}">
        <div>
          <strong>${esc(r.title || r.id)}</strong>
          <div class="lead" style="margin:4px 0 0">${esc(r.id)} · ${esc(r.timestamp || "")}${r.record_count != null ? " · " + r.record_count + " 条记录" : ""}</div>
        </div>
        <div>
          <span class="badge ${cls}">${esc((r.status || "unknown").toUpperCase())}${rate ? " · " + rate : ""}</span>
          <button class="btn secondary" type="button" style="margin-left:8px" data-open="${esc(r.id)}">详情</button>
          <a class="btn secondary" style="margin-left:8px;text-decoration:none" href="/api/report/${encodeURIComponent(r.id)}" target="_blank">JSON</a>
          <a class="btn secondary" style="margin-left:8px;text-decoration:none" href="/api/report/${encodeURIComponent(r.id)}/html" target="_blank">HTML</a>
          <a class="btn secondary" style="margin-left:8px;text-decoration:none" href="/three_layer_graph?report_id=${encodeURIComponent(r.id)}" target="_blank">三层图</a>
        </div>
      </div>`;
    }).join("");
    box.querySelectorAll("[data-open]").forEach((btn) => {
      btn.addEventListener("click", () => openReport(btn.dataset.open));
    });
    const preferred = reports.find((r) => r.id === "report_cluster_live") || reports.find((r) => r.id !== "report_demo_bookinfo");
    if (preferred && !currentReport) openReport(preferred.id);
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
