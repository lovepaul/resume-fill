import {
  API_BASE,
  createSessionTokenStore,
  formatBytes,
  formatNumber,
  readJsonOrThrow,
  renderTable,
  todayISODate
} from "/shared/common.js";

const TOKEN_KEY = "stats_dashboard_token";
const REFRESH_INTERVAL_MS = 15000;
const tokenStore = createSessionTokenStore(TOKEN_KEY);

const loginCard = document.getElementById("loginCard");
const dashboard = document.getElementById("dashboard");
const loginForm = document.getElementById("loginForm");
const loginError = document.getElementById("loginError");
const generatedAt = document.getElementById("generatedAt");
const datePicker = document.getElementById("datePicker");
const refreshBtn = document.getElementById("refreshBtn");
const logoutBtn = document.getElementById("logoutBtn");
let refreshTimer = null;

async function requestOverview() {
  const token = tokenStore.get();
  const date = datePicker.value || todayISODate();
  const resp = await fetch(`${API_BASE}/api/stats/overview?date=${date}`, {
    headers: {
      Authorization: `Bearer ${token}`,
    }
  });
  return readJsonOrThrow(resp, "加载统计失败", {
    onUnauthorized: () => {
      tokenStore.clear();
      showLogin();
    }
  });
}

function renderMetrics(data) {
  const metrics = document.getElementById("metrics");
  const metricItems = [
    { label: "日期", value: String(data.date || "-") },
    { label: "总请求量", value: formatNumber(data.total_requests) },
    { label: "独立 IP", value: formatNumber(data.unique_ips) },
    { label: "流量（字节）", value: formatNumber(data.total_bytes) }
  ];
  metrics.textContent = "";
  metricItems.forEach((item) => {
    const article = document.createElement("article");
    article.className = "metric";
    const label = document.createElement("div");
    label.className = "label";
    label.textContent = item.label;
    const value = document.createElement("div");
    value.className = "value";
    value.textContent = item.value;
    article.appendChild(label);
    article.appendChild(value);
    metrics.appendChild(article);
  });
}

function renderDashboard(data) {
  generatedAt.textContent = `生成时间：${new Date(data.generated_at).toLocaleString("zh-CN")} | 日志：${data.source_log}`;
  renderMetrics(data);
  renderTable(
    document.getElementById("ipTable"),
    ["IP", "请求数"],
    data.top_ips.map((item) => [item.ip, formatNumber(item.count)])
  );
  renderTable(
    document.getElementById("pathTable"),
    ["路径", "请求数"],
    data.top_paths.map((item) => [item.path, formatNumber(item.count)])
  );
  renderTable(
    document.getElementById("statusTable"),
    ["状态码", "请求数"],
    data.status_breakdown.map((item) => [item.status, formatNumber(item.count)])
  );
  renderTable(
    document.getElementById("hourTable"),
    ["小时", "请求数"],
    data.hourly.map((item) => [item.hour, formatNumber(item.count)])
  );
  renderTable(
    document.getElementById("recentTable"),
    ["时间", "IP", "路径", "状态码"],
    data.recent_requests.map((item) => [item.time, item.ip, item.path, item.status])
  );

  const runtime = data.runtime_storage || {};
  const uploads = runtime.uploads || { files: [], total_bytes: 0, max_bytes: 0, path: "-" };
  const outputs = runtime.outputs || { files: [], total_bytes: 0, max_bytes: 0, path: "-" };
  document.getElementById("uploadsMeta").textContent =
    `目录：${uploads.path} | 已用：${formatBytes(uploads.total_bytes)} / ${formatBytes(uploads.max_bytes)}`;
  document.getElementById("outputsMeta").textContent =
    `目录：${outputs.path} | 已用：${formatBytes(outputs.total_bytes)} / ${formatBytes(outputs.max_bytes)}`;

  renderTable(
    document.getElementById("uploadsTable"),
    ["文件名", "大小", "更新时间"],
    (uploads.files || []).map((item) => [
      item.name,
      formatBytes(item.size_bytes),
      item.modified_at.replace("T", " ")
    ])
  );
  renderTable(
    document.getElementById("outputsTable"),
    ["文件名", "大小", "更新时间"],
    (outputs.files || []).map((item) => [
      item.name,
      formatBytes(item.size_bytes),
      item.modified_at.replace("T", " ")
    ])
  );
}

async function refresh() {
  try {
    const data = await requestOverview();
    renderDashboard(data);
  } catch (err) {
    generatedAt.textContent = err?.message || "加载失败";
  }
}

function showLogin() {
  if (refreshTimer) {
    window.clearInterval(refreshTimer);
    refreshTimer = null;
  }
  loginCard.classList.remove("hidden");
  dashboard.classList.add("hidden");
}

function showDashboard() {
  loginCard.classList.add("hidden");
  dashboard.classList.remove("hidden");
  if (!refreshTimer) {
    refreshTimer = window.setInterval(refresh, REFRESH_INTERVAL_MS);
  }
}

loginForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  loginError.textContent = "";
  const username = document.getElementById("username").value.trim();
  const password = document.getElementById("password").value.trim();
  const resp = await fetch(`${API_BASE}/api/stats/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  if (!resp.ok) {
    loginError.textContent = "登录失败，请检查用户名或密码";
    return;
  }
  const data = await resp.json();
  tokenStore.set(data.token);
  showDashboard();
  await refresh();
});

refreshBtn.addEventListener("click", refresh);
logoutBtn.addEventListener("click", () => {
  tokenStore.clear();
  showLogin();
});

datePicker.value = todayISODate();
if (tokenStore.get()) {
  showDashboard();
  refresh();
} else {
  showLogin();
}
