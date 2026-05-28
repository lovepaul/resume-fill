import { useEffect, useMemo, useRef, useState } from "react";
import {
  API_BASE,
  LIMITS,
  readJsonOrThrow,
  readJsonResponse,
  STORAGE_KEYS
} from "./shared/common";

function formatHistoryName(jobData, fallbackName) {
  const outputName = typeof jobData?.output_name === "string" ? jobData.output_name.trim() : "";
  if (!outputName) return fallbackName || "未命名文件";
  return outputName.replace(/\.docx$/i, "");
}

function App() {
  const [file, setFile] = useState(null);
  const [apiKey, setApiKey] = useState("");
  const [job, setJob] = useState(null);
  const [history, setHistory] = useState([]);
  const [error, setError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [deletingJobId, setDeletingJobId] = useState("");
  const [isCurrentDownloading, setIsCurrentDownloading] = useState(false);
  const [downloadingHistoryIds, setDownloadingHistoryIds] = useState([]);
  const [isCurrentCooldown, setIsCurrentCooldown] = useState(false);
  const [cooldownHistoryIds, setCooldownHistoryIds] = useState([]);
  const timerRef = useRef(null);
  const apiKeyRef = useRef("");
  const currentUploadNameRef = useRef("");
  const currentCooldownTimerRef = useRef(null);
  const historyCooldownTimersRef = useRef({});

  useEffect(() => {
    const stored = window.sessionStorage.getItem(STORAGE_KEYS.apiKey) || "";
    setApiKey(stored);
    apiKeyRef.current = stored.trim();
    const rawHistory = window.sessionStorage.getItem(STORAGE_KEYS.history) || "[]";
    try {
      const parsed = JSON.parse(rawHistory);
      if (Array.isArray(parsed)) {
        setHistory(parsed.slice(0, LIMITS.maxHistoryItems));
      }
    } catch {
      setHistory([]);
    }
  }, []);

  const apiKeyReady = useMemo(() => apiKey.trim().length > 0, [apiKey]);
  const canSubmit = useMemo(
    () => !!file && apiKeyReady && !isSubmitting,
    [file, apiKeyReady, isSubmitting]
  );

  const clearPoll = () => {
    if (timerRef.current) {
      window.clearInterval(timerRef.current);
      timerRef.current = null;
    }
  };

  useEffect(() => {
    return () => {
      clearPoll();
      if (currentCooldownTimerRef.current) {
        window.clearTimeout(currentCooldownTimerRef.current);
        currentCooldownTimerRef.current = null;
      }
      Object.values(historyCooldownTimersRef.current).forEach((timerId) => {
        window.clearTimeout(timerId);
      });
      historyCooldownTimersRef.current = {};
    };
  }, []);

  const startCurrentDownloadCooldown = () => {
    setIsCurrentCooldown(true);
    if (currentCooldownTimerRef.current) {
      window.clearTimeout(currentCooldownTimerRef.current);
    }
    currentCooldownTimerRef.current = window.setTimeout(() => {
      setIsCurrentCooldown(false);
      currentCooldownTimerRef.current = null;
    }, LIMITS.downloadCooldownMs);
  };

  const startHistoryDownloadCooldown = (itemId) => {
    setCooldownHistoryIds((prev) => (prev.includes(itemId) ? prev : [...prev, itemId]));
    const oldTimer = historyCooldownTimersRef.current[itemId];
    if (oldTimer) {
      window.clearTimeout(oldTimer);
    }
    historyCooldownTimersRef.current[itemId] = window.setTimeout(() => {
      setCooldownHistoryIds((prev) => prev.filter((id) => id !== itemId));
      delete historyCooldownTimersRef.current[itemId];
    }, LIMITS.downloadCooldownMs);
  };

  const fetchJob = async (jobId) => {
    const resp = await fetch(`${API_BASE}/api/jobs/${jobId}`);
    const data = await readJsonOrThrow(resp, "获取任务状态失败");
    if (!data) {
      throw new Error("服务返回为空，无法读取任务状态");
    }
    setJob(data);
    if (data.status === "done" || data.status === "failed") {
      clearPoll();
      setIsSubmitting(false);
    }
  };

  const startPolling = (jobId) => {
    clearPoll();
    timerRef.current = window.setInterval(() => {
      fetchJob(jobId).catch((e) => {
        setError(e.message);
        clearPoll();
        setIsSubmitting(false);
      });
    }, LIMITS.pollingIntervalMs);
  };

  const handleUpload = async (event) => {
    event.preventDefault();
    if (!file || !apiKeyRef.current) return;
    setError("");
    setIsSubmitting(true);
    setJob(null);
    currentUploadNameRef.current = file.name;

    try {
      const formData = new FormData();
      formData.append("file", file);
      const resp = await fetch(`${API_BASE}/api/convert`, {
        method: "POST",
        headers: {
          "X-DeepSeek-Api-Key": apiKeyRef.current
        },
        body: formData
      });
      const data = await readJsonOrThrow(resp, "提交失败");
      if (!data?.job_id) {
        throw new Error("服务未返回任务 ID，请稍后重试");
      }
      await fetchJob(data.job_id);
      startPolling(data.job_id);
    } catch (e) {
      setError(e.message || "提交失败");
      setIsSubmitting(false);
    }
  };

  const progress = job?.progress ?? 0;
  const stageItems = [
    { label: "文件上传", done: progress >= 10 },
    { label: "内容解析", done: progress >= 45 },
    { label: "文档生成", done: progress >= 80 },
    { label: "下载就绪", done: progress >= 100 }
  ];

  useEffect(() => {
    if (job?.status !== "done" || !job.id || !job.download_url) {
      return;
    }
    const nextItem = {
      id: job.id,
      sourceName: formatHistoryName(job, currentUploadNameRef.current),
      downloadUrl: job.download_url,
      finishedAt: new Date().toISOString()
    };
    setHistory((prev) => {
      const merged = [nextItem, ...prev.filter((item) => item.id !== job.id)].slice(
        0,
        LIMITS.maxHistoryItems
      );
      window.sessionStorage.setItem(STORAGE_KEYS.history, JSON.stringify(merged));
      return merged;
    });
  }, [job]);

  const handleDeleteHistoryItem = async (itemId) => {
    setDeletingJobId(itemId);
    try {
      const resp = await fetch(`${API_BASE}/api/jobs/${itemId}`, { method: "DELETE" });
      if (!resp.ok && resp.status !== 404) {
        const data = await readJsonResponse(resp);
        throw new Error(data?.detail || "删除失败，请稍后重试");
      }
      setHistory((prev) => {
        const next = prev.filter((item) => item.id !== itemId);
        window.sessionStorage.setItem(STORAGE_KEYS.history, JSON.stringify(next));
        return next;
      });
      if (job?.id === itemId) {
        setJob(null);
      }
    } catch (e) {
      setError(e.message || "删除失败");
    } finally {
      setDeletingJobId("");
    }
  };

  const triggerBrowserDownload = async (downloadUrl, fallbackName) => {
    const resp = await fetch(`${API_BASE}${downloadUrl}`);
    if (!resp.ok) {
      const data = await readJsonResponse(resp);
      const detail = data?.detail || `下载失败（HTTP ${resp.status}）`;
      const error = new Error(detail);
      error.status = resp.status;
      throw error;
    }

    const blob = await resp.blob();
    const objectUrl = window.URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = objectUrl;
    anchor.download = `${fallbackName || "resume"}.docx`;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    window.URL.revokeObjectURL(objectUrl);
  };

  const handleHistoryDownload = async (item) => {
    if (downloadingHistoryIds.includes(item.id) || cooldownHistoryIds.includes(item.id)) return;
    setDownloadingHistoryIds((prev) => [...prev, item.id]);
    try {
      setError("");
      await triggerBrowserDownload(item.downloadUrl, item.sourceName);
    } catch (e) {
      const message = e?.message || "下载失败";
      if (message.includes("任务不存在") || message.includes("输出文件不存在")) {
        setError("文件已经被清理，请重新转换。");
        setHistory((prev) => {
          const next = prev.filter((historyItem) => historyItem.id !== item.id);
          window.sessionStorage.setItem(STORAGE_KEYS.history, JSON.stringify(next));
          return next;
        });
        if (job?.id === item.id) {
          setJob(null);
        }
        return;
      }
      setError(message);
    } finally {
      setDownloadingHistoryIds((prev) => prev.filter((id) => id !== item.id));
      startHistoryDownloadCooldown(item.id);
    }
  };

  const handleCurrentJobDownload = async () => {
    if (!job?.download_url || isCurrentDownloading || isCurrentCooldown) return;
    setIsCurrentDownloading(true);
    try {
      setError("");
      await triggerBrowserDownload(job.download_url, formatHistoryName(job, "resume"));
    } catch (e) {
      const message = e?.message || "下载失败";
      if (message.includes("任务不存在") || message.includes("输出文件不存在")) {
        setError("文件已经被清理，请重新转换。");
        if (job?.id) {
          setHistory((prev) => {
            const next = prev.filter((historyItem) => historyItem.id !== job.id);
            window.sessionStorage.setItem(STORAGE_KEYS.history, JSON.stringify(next));
            return next;
          });
        }
        setJob(null);
        return;
      }
      setError(message);
    } finally {
      setIsCurrentDownloading(false);
      startCurrentDownloadCooldown();
    }
  };

  return (
    <>
      <header className="tool-header">
        <div className="tool-header-inner">
          <h1>简历转换工具</h1>
          <p>上传文件后自动处理，完成即可下载标准 DOCX。</p>
        </div>
      </header>

      <main className="workspace">
        <section className="panel upload-panel">
          <h2>1. 上传文件</h2>
          <p className="panel-desc">支持 PDF / DOCX / TXT / MD</p>
          {!apiKeyReady ? (
            <section className="key-guide">
              <p className="key-guide-title">先完成 DeepSeek API Key 配置</p>
              <p className="key-guide-desc">
                未配置前其余功能会保持灰色不可用。请先登录 DeepSeek 并创建 API Key 后填写。
              </p>
              <div className="key-guide-links">
                <a href="https://platform.deepseek.com/sign_in" target="_blank" rel="noreferrer">
                  去登录 DeepSeek
                </a>
                <a href="https://platform.deepseek.com/api_keys" target="_blank" rel="noreferrer">
                  去创建 API Key
                </a>
              </div>
            </section>
          ) : null}

          <form onSubmit={handleUpload} className="converter-form">
            <div className="key-config">
              <label htmlFor="deepseek-api-key">DeepSeek API Key</label>
              <input
                id="deepseek-api-key"
                type="password"
                autoComplete="off"
                placeholder="请输入 sk-xxxx"
                value={apiKey}
                onChange={(e) => {
                  const nextKey = e.target.value;
                  setApiKey(nextKey);
                  apiKeyRef.current = nextKey.trim();
                  window.sessionStorage.setItem(STORAGE_KEYS.apiKey, nextKey);
                }}
              />
            </div>
            <p className="security-note">
              此网站不会保留任何 Key，Key 仅保存在当前浏览器会话中（刷新页面不丢失，关闭会话后清除）。
            </p>

            <fieldset className={`feature-lock ${!apiKeyReady ? "locked" : ""}`} disabled={!apiKeyReady}>
              <label className="upload-box">
                <span className="upload-title">点击选择文件</span>
                <span className="upload-subtitle">或直接拖拽到此区域</span>
                <input
                  type="file"
                  accept=".pdf,.docx,.txt,.md"
                  onChange={(e) => setFile(e.target.files?.[0] || null)}
                />
              </label>

              <div className="file-row">
                <span className="file-label">当前文件</span>
                <span className="file-value">{file ? file.name : "未选择"}</span>
              </div>

              <button className="button-primary" type="submit" disabled={!canSubmit}>
                {isSubmitting ? "正在提交..." : "开始转换"}
              </button>
            </fieldset>
            {!apiKeyReady ? <p className="hint">请先配置 API Key 后再开始转换。</p> : null}
          </form>

          {error ? <p className="error">失败原因：{error}</p> : null}
        </section>

        <section className={`panel progress-panel ${!apiKeyReady ? "panel-locked" : ""}`}>
          <h2>2. 转换进度</h2>
          <p className="panel-desc">任务自动刷新，无需手动操作。上传与生成文件默认 1 小时后自动删除。</p>

          <section className="status-card">
            <div className="status-row">
              <span>任务状态</span>
              <span className={`status-badge ${job ? job.status : "idle"}`}>
                {job ? job.message : "等待开始"}
              </span>
            </div>
            <div className="bar">
              <div className="bar-inner" style={{ width: `${progress}%` }} />
            </div>
            <div className="progress-number">{progress}%</div>

            <ul className="stage-list">
              {stageItems.map((item) => (
                <li key={item.label} className={item.done ? "done" : ""}>
                  <span className="dot" />
                  <span>{item.label}</span>
                </li>
              ))}
            </ul>

            {job?.status === "done" ? (
              <button
                className="button-primary download-btn"
                type="button"
                disabled={isCurrentDownloading || isCurrentCooldown}
                onClick={handleCurrentJobDownload}
              >
                {isCurrentDownloading ? "下载中..." : isCurrentCooldown ? "请稍候..." : "下载 DOCX"}
              </button>
            ) : (
              <p className="hint">转换完成后会在这里显示下载按钮。</p>
            )}

            {job?.status === "failed" && job.error ? (
              <p className="error">失败原因：{job.error}</p>
            ) : null}
          </section>

          <section className="history-block">
            <div className="history-head">
              <h3>已完成转换（当前会话，最多 10 条）</h3>
            </div>
            {history.length === 0 ? (
              <p className="hint">当前会话还没有已完成的简历。</p>
            ) : (
              <ul className="history-list">
                {history.slice(0, LIMITS.maxHistoryItems).map((item) => (
                  <li key={item.id} className="history-item">
                    <div className="history-main">
                      <p className="history-name">{item.sourceName}</p>
                      <p className="history-time">
                        完成时间：{new Date(item.finishedAt).toLocaleString("zh-CN")}
                      </p>
                    </div>
                    <div className="history-actions">
                      <button
                        type="button"
                        className="button-primary history-btn"
                        disabled={downloadingHistoryIds.includes(item.id) || cooldownHistoryIds.includes(item.id)}
                        onClick={() => handleHistoryDownload(item)}
                      >
                        {downloadingHistoryIds.includes(item.id)
                          ? "下载中..."
                          : cooldownHistoryIds.includes(item.id)
                            ? "请稍候..."
                            : "下载"}
                      </button>
                      <button
                        type="button"
                        className="button-danger history-btn"
                        disabled={
                          deletingJobId === item.id ||
                          downloadingHistoryIds.includes(item.id) ||
                          cooldownHistoryIds.includes(item.id)
                        }
                        onClick={() => handleDeleteHistoryItem(item.id)}
                      >
                        {deletingJobId === item.id ? "删除中..." : "删除"}
                      </button>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </section>
      </main>
    </>
  );
}

export default App;
