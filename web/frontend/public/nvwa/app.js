import {
  API_BASE,
  createBlobDownload,
  createSessionTokenStore,
  formatBytes,
  readJsonOrThrow,
  renderTable
} from "/shared/common.js";

const TOKEN_KEY = "nvwa_dashboard_token";
const PAGE_SIZE = 20;
const REFRESH_INTERVAL_MS = 3000;
const tokenStore = createSessionTokenStore(TOKEN_KEY);

const loginCard = document.getElementById("loginCard");
const dashboard = document.getElementById("dashboard");
const loginForm = document.getElementById("loginForm");
const loginError = document.getElementById("loginError");
const globalError = document.getElementById("globalError");
const refreshBtn = document.getElementById("refreshBtn");
const logoutBtn = document.getElementById("logoutBtn");
const uploadForm = document.getElementById("uploadForm");
const uploadInput = document.getElementById("uploadInput");
const uploadBtn = document.getElementById("uploadBtn");
const startBtn = document.getElementById("startBtn");
const jobStatus = document.getElementById("jobStatus");
const jobProgress = document.getElementById("jobProgress");
const jobMeta = document.getElementById("jobMeta");
const resultWrap = document.getElementById("resultWrap");
const resultBtn = document.getElementById("resultBtn");
const listMeta = document.getElementById("listMeta");
const fileTable = document.getElementById("fileTable");
const prevBtn = document.getElementById("prevBtn");
const nextBtn = document.getElementById("nextBtn");
const pageInfo = document.getElementById("pageInfo");

let currentPage = 1;
let totalPages = 1;
let currentJobId = "";
let currentResultUrl = "";
let refreshTimer = null;

function authHeaders() {
  return {
    Authorization: `Bearer ${tokenStore.get()}`
  };
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
    refreshTimer = window.setInterval(async () => {
      await refreshAll(true);
    }, REFRESH_INTERVAL_MS);
  }
}

async function fetchFiles(page = currentPage) {
  const resp = await fetch(`${API_BASE}/api/nvwa/files?page=${page}&page_size=${PAGE_SIZE}`, {
    headers: authHeaders()
  });
  const data = await readJsonOrThrow(resp, "读取文件列表失败", {
    onUnauthorized: () => {
      tokenStore.clear();
      showLogin();
    }
  });
  const items = data?.items || [];
  currentPage = Number(data?.page || page || 1);
  totalPages = Number(data?.total_pages || 1);
  listMeta.textContent = `总数 ${Number(data?.total || 0)}`;
  pageInfo.textContent = `第 ${currentPage} / ${Math.max(totalPages, 1)} 页`;
  prevBtn.disabled = currentPage <= 1;
  nextBtn.disabled = currentPage >= totalPages;
  renderFiles(items);
}

function renderFiles(items) {
  const tableRows = items.map((item) => [
    item.name,
    formatBytes(item.size_bytes),
    item.modified_at ? String(item.modified_at).replace("T", " ") : "-",
    "DELETE_ACTION"
  ]);
  renderTable(fileTable, ["文件名", "大小", "更新时间", "操作"], tableRows);

  const bodyRows = fileTable.querySelectorAll("tbody tr");
  bodyRows.forEach((row, index) => {
    const actionCell = row.lastElementChild;
    if (!actionCell || !items[index]) {
      return;
    }
    actionCell.textContent = "";
    const button = document.createElement("button");
    button.className = "danger";
    button.dataset.delete = String(items[index].name || "");
    button.textContent = "删除";
    actionCell.appendChild(button);
  });

  if (!items.length) {
    const emptyRow = fileTable.querySelector("tbody tr td.empty");
    if (emptyRow) {
      emptyRow.textContent = "当前目录暂无文件";
    }
  }
}

async function fetchJob() {
  if (!currentJobId) return;
  const resp = await fetch(`${API_BASE}/api/nvwa/jobs/${currentJobId}`, {
    headers: authHeaders()
  });
  const job = await readJsonOrThrow(resp, "读取任务状态失败", {
    onUnauthorized: () => {
      tokenStore.clear();
      showLogin();
    }
  });
  const progress = Number(job?.progress || 0);
  jobStatus.textContent = job?.message || "等待开始";
  jobMeta.textContent = `进度 ${progress}% | 已处理 ${job?.processed_files || 0} / ${job?.total_files || 0}`;
  jobProgress.style.width = `${Math.max(0, Math.min(100, progress))}%`;
  if (job?.status === "done" && job?.result_url) {
    resultWrap.classList.remove("hidden");
    currentResultUrl = `${API_BASE}${job.result_url}`;
  } else {
    resultWrap.classList.add("hidden");
    currentResultUrl = "";
  }
}

async function downloadCurrentResult() {
  if (!currentResultUrl) return;
  const resp = await fetch(currentResultUrl, { headers: authHeaders() });
  if (!resp.ok) {
    await readJsonOrThrow(resp, "下载蒸馏结果失败", {
      onUnauthorized: () => {
        tokenStore.clear();
        showLogin();
      }
    });
    return;
  }
  const blob = await resp.blob();
  createBlobDownload(blob, `nvwa-distill-${new Date().toISOString().replaceAll(":", "-")}.json`);
}

async function refreshAll(silent = false) {
  if (!silent) {
    globalError.textContent = "";
  }
  try {
    await fetchFiles(currentPage);
    await fetchJob();
  } catch (err) {
    globalError.textContent = err?.message || "刷新失败";
  }
}

loginForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  loginError.textContent = "";
  const username = document.getElementById("username").value.trim();
  const password = document.getElementById("password").value.trim();
  try {
    const resp = await fetch(`${API_BASE}/api/nvwa/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password })
    });
    const data = await readJsonOrThrow(resp, "登录失败");
    tokenStore.set(data.token);
    showDashboard();
    await refreshAll();
  } catch (err) {
    loginError.textContent = err?.message || "登录失败";
  }
});

uploadForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  globalError.textContent = "";
  const file = uploadInput.files?.[0];
  if (!file) return;
  uploadBtn.disabled = true;
  try {
    const formData = new FormData();
    formData.append("file", file);
    const resp = await fetch(`${API_BASE}/api/nvwa/upload`, {
      method: "POST",
      headers: authHeaders(),
      body: formData
    });
    await readJsonOrThrow(resp, "上传失败");
    uploadInput.value = "";
    currentPage = 1;
    await refreshAll();
  } catch (err) {
    globalError.textContent = err?.message || "上传失败";
  } finally {
    uploadBtn.disabled = false;
  }
});

startBtn.addEventListener("click", async () => {
  globalError.textContent = "";
  startBtn.disabled = true;
  try {
    const resp = await fetch(`${API_BASE}/api/nvwa/start`, {
      method: "POST",
      headers: authHeaders()
    });
    const data = await readJsonOrThrow(resp, "启动蒸馏失败");
    currentJobId = data?.job_id || "";
    await fetchJob();
  } catch (err) {
    globalError.textContent = err?.message || "启动蒸馏失败";
  } finally {
    startBtn.disabled = false;
  }
});

fileTable.addEventListener("click", async (event) => {
  const target = event.target;
  if (!(target instanceof HTMLButtonElement)) return;
  const filename = target.dataset.delete || "";
  if (!filename) return;
  if (!window.confirm(`确认删除文件 ${filename} 吗？`)) return;
  globalError.textContent = "";
  target.disabled = true;
  try {
    const resp = await fetch(`${API_BASE}/api/nvwa/files/${encodeURIComponent(filename)}`, {
      method: "DELETE",
      headers: authHeaders()
    });
    await readJsonOrThrow(resp, "删除失败");
    await refreshAll();
  } catch (err) {
    globalError.textContent = err?.message || "删除失败";
  } finally {
    target.disabled = false;
  }
});

prevBtn.addEventListener("click", async () => {
  if (currentPage <= 1) return;
  currentPage -= 1;
  await refreshAll();
});

nextBtn.addEventListener("click", async () => {
  if (currentPage >= totalPages) return;
  currentPage += 1;
  await refreshAll();
});

refreshBtn.addEventListener("click", async () => {
  await refreshAll();
});

logoutBtn.addEventListener("click", () => {
  tokenStore.clear();
  currentJobId = "";
  currentResultUrl = "";
  showLogin();
});

resultBtn.addEventListener("click", async () => {
  try {
    await downloadCurrentResult();
  } catch (err) {
    globalError.textContent = err?.message || "下载蒸馏结果失败";
  }
});

if (tokenStore.get()) {
  showDashboard();
  refreshAll();
} else {
  showLogin();
}
