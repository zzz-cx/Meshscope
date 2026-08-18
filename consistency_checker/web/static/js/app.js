function $(id) { return document.getElementById(id); }

function switchPage(name) {
  document.querySelectorAll(".nav-btn").forEach((b) => b.classList.toggle("active", b.dataset.page === name));
  document.querySelectorAll(".page").forEach((p) => p.classList.toggle("active", p.id === "page-" + name));
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
    showStatus("static-status", "ok", "静态对齐完成，跨资源冲突 " + conflictN + " 项，可执行动态验证");
    $("static-results").innerHTML = "<pre>" + JSON.stringify(data.summary || data, null, 2) + "</pre>";
    if (data.graph_data) drawGraph(data.graph_data);
  } catch (err) {
    showStatus("static-status", "err", "分析失败: " + (err.response?.data?.error || err.message));
  }
}

function drawGraph(graphData) {
  const container = $("graph-container");
  const width = container.clientWidth || 800;
  const height = 520;
  d3.select("#graph-container").selectAll("*").remove();
  const svg = d3.select("#graph-container").append("svg").attr("width", width).attr("height", height);
  const nodes = (graphData.nodes || []).map((d) => ({ ...d }));
  const edges = (graphData.edges || []).map((d) => ({ ...d }));
  const simulation = d3.forceSimulation(nodes)
    .force("link", d3.forceLink(edges).id((d) => d.id).distance(110))
    .force("charge", d3.forceManyBody().strength(-280))
    .force("center", d3.forceCenter(width / 2, height / 2));
  const link = svg.append("g").selectAll("line").data(edges).enter().append("line")
    .attr("stroke", "#4b5d78").attr("stroke-width", 1.5);
  const node = svg.append("g").selectAll("circle").data(nodes).enter().append("circle")
    .attr("r", 16).attr("fill", "#3d8bfd")
    .call(d3.drag()
      .on("start", (event) => { if (!event.active) simulation.alphaTarget(0.3).restart(); event.subject.fx = event.subject.x; event.subject.fy = event.subject.y; })
      .on("drag", (event) => { event.subject.fx = event.x; event.subject.fy = event.y; })
      .on("end", (event) => { if (!event.active) simulation.alphaTarget(0); event.subject.fx = null; event.subject.fy = null; }));
  const label = svg.append("g").selectAll("text").data(nodes).enter().append("text")
    .text((d) => d.label || d.id).attr("fill", "#d7e3f4").attr("font-size", 12).attr("dx", 20).attr("dy", 4);
  simulation.on("tick", () => {
    link.attr("x1", (d) => d.source.x).attr("y1", (d) => d.source.y).attr("x2", (d) => d.target.x).attr("y2", (d) => d.target.y);
    node.attr("cx", (d) => d.x).attr("cy", (d) => d.y);
    label.attr("x", (d) => d.x).attr("y", (d) => d.y);
  });
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
    showStatus("consistency-status", "ok", "三层图已生成");
    const box = $("reports-container");
    box.innerHTML = "<pre>" + JSON.stringify({
      summary: data.summary,
      conflicts: data.conflicts,
      graph_path: data.graph_path,
    }, null, 2) + "</pre>";
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
          <a class="btn secondary" style="margin-left:8px;text-decoration:none" href="/three_layer_graph?report=${r.id}" target="_blank">三层图</a>
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
