export const API_BASE =
  import.meta.env.VITE_API_BASE_URL && import.meta.env.VITE_API_BASE_URL.trim()
    ? import.meta.env.VITE_API_BASE_URL.trim()
    : "";

export const STORAGE_KEYS = {
  apiKey: "resume_converter_deepseek_key",
  history: "resume_converter_done_history_v1"
};

export const LIMITS = {
  maxHistoryItems: 10,
  downloadCooldownMs: 800,
  pollingIntervalMs: 1500
};

export async function readJsonResponse(resp) {
  const raw = await resp.text();
  if (!raw.trim()) {
    return null;
  }
  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

export async function readJsonOrThrow(resp, fallbackMessage) {
  const data = await readJsonResponse(resp);
  if (!resp.ok) {
    throw new Error(data?.detail || `${fallbackMessage}（HTTP ${resp.status}）`);
  }
  return data;
}

export function saveSessionJson(storageKey, value) {
  window.sessionStorage.setItem(storageKey, JSON.stringify(value));
}

