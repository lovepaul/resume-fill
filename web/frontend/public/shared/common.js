export const API_BASE = "";

export function formatNumber(value) {
  return new Intl.NumberFormat("zh-CN").format(Number(value || 0));
}

export function formatBytes(value) {
  const bytes = Number(value || 0);
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(2)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

export function todayISODate() {
  return new Date().toISOString().slice(0, 10);
}

export function createSessionTokenStore(storageKey) {
  return {
    get() {
      return window.sessionStorage.getItem(storageKey) || "";
    },
    set(token) {
      window.sessionStorage.setItem(storageKey, token);
    },
    clear() {
      window.sessionStorage.removeItem(storageKey);
    }
  };
}

export async function readJsonResponse(resp) {
  const rawText = await resp.text();
  if (!rawText.trim()) {
    return null;
  }
  try {
    return JSON.parse(rawText);
  } catch {
    return null;
  }
}

export async function readJsonOrThrow(resp, fallbackMessage, options = {}) {
  const body = await readJsonResponse(resp);
  if (!resp.ok) {
    if (resp.status === 401 && typeof options.onUnauthorized === "function") {
      options.onUnauthorized();
    }
    throw new Error(body?.detail || `${fallbackMessage}（HTTP ${resp.status}）`);
  }
  return body;
}

export function createBlobDownload(blob, filename) {
  const objectUrl = window.URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = objectUrl;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.URL.revokeObjectURL(objectUrl);
}

export function renderTable(tableEl, headers, rows) {
  tableEl.textContent = "";
  const thead = document.createElement("thead");
  const headRow = document.createElement("tr");
  headers.forEach((header) => {
    const th = document.createElement("th");
    th.textContent = header;
    headRow.appendChild(th);
  });
  thead.appendChild(headRow);
  tableEl.appendChild(thead);

  const tbody = document.createElement("tbody");
  if (!rows.length) {
    const row = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = headers.length;
    td.className = "empty";
    td.textContent = "暂无数据";
    row.appendChild(td);
    tbody.appendChild(row);
  } else {
    rows.forEach((cells) => {
      const row = document.createElement("tr");
      cells.forEach((cell) => {
        const td = document.createElement("td");
        td.textContent = cell ?? "";
        row.appendChild(td);
      });
      tbody.appendChild(row);
    });
  }
  tableEl.appendChild(tbody);
}

