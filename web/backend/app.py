from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import threading
import time
import hashlib
import secrets
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from fastapi import Body, FastAPI, File, HTTPException, Header, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from web.backend.core.rate_limiter import RateLimiter
from web.backend.core.session_store import SessionStore
from src.filler import fill_template
from scripts.resume_bot_pipeline import (
    call_deepseek_resume_parser,
    ensure_deepseek_ready,
    extract_resume_text,
    get_deepseek_config,
    normalize_resume_data,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
WEB_ROOT = PROJECT_ROOT / "web"
DEFAULT_RUNTIME_DIR = Path(os.environ.get("WEB_DEFAULT_RUNTIME_DIR", "/var/lib/resume-web/runtime")).resolve()
LOCAL_FALLBACK_RUNTIME_DIR = (PROJECT_ROOT / ".runtime" / "resume-web").resolve()
EXPLICIT_RUNTIME_DIR = (os.environ.get("WEB_RUNTIME_DIR") or os.environ.get("WEB_TMP_DIR") or "").strip()
RUNTIME_DIR = Path(
    EXPLICIT_RUNTIME_DIR or str(DEFAULT_RUNTIME_DIR)
).resolve()
UPLOAD_DIR = RUNTIME_DIR / "uploads"
OUTPUT_DIR = RUNTIME_DIR / "outputs"
EXPLICIT_DISTILL_WATCH_DIR = (os.environ.get("WEB_DISTILL_WATCH_DIR") or "").strip()
DISTILL_WATCH_DIR = Path(
    EXPLICIT_DISTILL_WATCH_DIR or str(RUNTIME_DIR / "distill-watch")
).resolve()
FRONTEND_DIST_DIR = WEB_ROOT / "frontend" / "dist"
TEMPLATE_PATH = PROJECT_ROOT / "muban" / "简历模板 TEK.docx"
SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md"}
DISTILL_PAGE_SIZE = 20
DISTILL_MAX_PAGE_SIZE = 100
DISTILL_MAX_BYTES = int(os.environ.get("WEB_DISTILL_MAX_BYTES", str(200 * 1024 * 1024)))
HERMES_DISTILL_TIMEOUT_SECONDS = max(10, int(os.environ.get("WEB_HERMES_DISTILL_TIMEOUT_SECONDS", "1800")))
HERMES_DISTILL_COMMAND = os.environ.get("WEB_HERMES_DISTILL_COMMAND", "").strip()
FILE_RETENTION_SECONDS = int(os.environ.get("WEB_FILE_RETENTION_SECONDS", "3600"))
CLEANUP_SCAN_INTERVAL_SECONDS = int(os.environ.get("WEB_CLEANUP_SCAN_INTERVAL_SECONDS", "60"))
DOWNLOAD_TOKEN_TTL_SECONDS = int(os.environ.get("WEB_DOWNLOAD_TOKEN_TTL_SECONDS", "600"))
UPLOADS_MAX_BYTES = int(os.environ.get("WEB_UPLOADS_MAX_BYTES", str(50 * 1024 * 1024)))
OUTPUTS_MAX_BYTES = int(os.environ.get("WEB_OUTPUTS_MAX_BYTES", str(10 * 1024 * 1024)))
LLM_CONCURRENCY_LIMIT = max(1, int(os.environ.get("WEB_LLM_MAX_CONCURRENCY", "2")))
LLM_QUEUE_TIMEOUT_SECONDS = max(1, int(os.environ.get("WEB_LLM_QUEUE_TIMEOUT_SECONDS", "30")))
CONVERT_CONCURRENCY_LIMIT = max(1, int(os.environ.get("WEB_CONVERT_MAX_CONCURRENCY", "4")))
CONVERT_QUEUE_TIMEOUT_SECONDS = max(1, int(os.environ.get("WEB_CONVERT_QUEUE_TIMEOUT_SECONDS", "15")))
STATS_SESSION_TTL_SECONDS = max(300, int(os.environ.get("WEB_STATS_SESSION_TTL_SECONDS", "43200")))
STATS_MAX_LOG_LINES = max(1000, int(os.environ.get("WEB_STATS_MAX_LOG_LINES", "200000")))
STATS_RUNTIME_FILE_LIMIT = max(10, int(os.environ.get("WEB_STATS_RUNTIME_FILE_LIMIT", "200")))


def env_with_legacy(primary_key: str, legacy_key: str, default_value: str) -> str:
    primary_value = os.environ.get(primary_key)
    if primary_value:
        return primary_value
    legacy_value = os.environ.get(legacy_key)
    if legacy_value:
        return legacy_value
    return default_value


STATS_USERNAME = env_with_legacy("WEB_STATS_USERNAME", "STATS_USERNAME", "lensman")
STATS_PASSWORD = env_with_legacy("WEB_STATS_PASSWORD", "STATS_PASSWORD", "666666")
NVWA_USERNAME = env_with_legacy("WEB_NVWA_USERNAME", "NVWA_USERNAME", "lensman")
NVWA_PASSWORD = env_with_legacy("WEB_NVWA_PASSWORD", "NVWA_PASSWORD", "666666")
NVWA_SESSION_TTL_SECONDS = max(300, int(os.environ.get("WEB_NVWA_SESSION_TTL_SECONDS", "43200")))
NGINX_ACCESS_LOG = Path(os.environ.get("WEB_NGINX_ACCESS_LOG", "/var/log/nginx/access.log"))
RATE_LIMITS = {
    "convert": (
        int(os.environ.get("WEB_RATE_LIMIT_CONVERT_MAX", "8")),
        int(os.environ.get("WEB_RATE_LIMIT_CONVERT_WINDOW_SECONDS", "60")),
    ),
    "job_status": (
        int(os.environ.get("WEB_RATE_LIMIT_STATUS_MAX", "180")),
        int(os.environ.get("WEB_RATE_LIMIT_STATUS_WINDOW_SECONDS", "60")),
    ),
    "download": (
        int(os.environ.get("WEB_RATE_LIMIT_DOWNLOAD_MAX", "30")),
        int(os.environ.get("WEB_RATE_LIMIT_DOWNLOAD_WINDOW_SECONDS", "60")),
    ),
    "delete_job": (
        int(os.environ.get("WEB_RATE_LIMIT_DELETE_MAX", "30")),
        int(os.environ.get("WEB_RATE_LIMIT_DELETE_WINDOW_SECONDS", "60")),
    ),
}


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def apply_runtime_dir(runtime_dir: Path) -> None:
    global RUNTIME_DIR, UPLOAD_DIR, OUTPUT_DIR, DISTILL_WATCH_DIR
    RUNTIME_DIR = runtime_dir.resolve()
    UPLOAD_DIR = RUNTIME_DIR / "uploads"
    OUTPUT_DIR = RUNTIME_DIR / "outputs"
    if not EXPLICIT_DISTILL_WATCH_DIR:
        DISTILL_WATCH_DIR = RUNTIME_DIR / "distill-watch"


def _ensure_dirs_once() -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    DISTILL_WATCH_DIR.mkdir(parents=True, exist_ok=True)
    for folder in (RUNTIME_DIR, UPLOAD_DIR, OUTPUT_DIR, DISTILL_WATCH_DIR):
        if not os.access(folder, os.R_OK | os.W_OK | os.X_OK):
            raise RuntimeError(f"运行目录无读写权限: {folder}")


def ensure_runtime_dirs() -> None:
    try:
        _ensure_dirs_once()
    except PermissionError:
        # 本地开发常见场景：默认 /var/lib/* 无权限，自动回退到项目目录内。
        if EXPLICIT_RUNTIME_DIR:
            raise
        apply_runtime_dir(LOCAL_FALLBACK_RUNTIME_DIR)
        _ensure_dirs_once()


def secure_filename(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "_", name).strip("_") or "resume"


def sanitize_docx_part(value: str, fallback: str) -> str:
    cleaned = re.sub(r"[\\/:*?\"<>|]+", "-", value).strip().strip(".")
    cleaned = re.sub(r"\s+", "-", cleaned)
    cleaned = re.sub(r"-{2,}", "-", cleaned)
    return cleaned or fallback


def extract_phone_from_text(text: str) -> str:
    match = re.search(r"(?<!\d)(1[3-9]\d{9})(?!\d)", text)
    if match:
        return match.group(1)
    return ""


def normalize_phone_value(value: str) -> str:
    digits = re.sub(r"\D+", "", value)
    if digits.startswith("86") and len(digits) > 11:
        digits = digits[2:]
    match = re.search(r"(1[3-9]\d{9})", digits)
    if match:
        return match.group(1)
    return ""


def pick_phone_number(payload: dict[str, Any], input_path: Path) -> str:
    direct_phone = normalize_phone_value(str(payload.get("candidate_phone", "")))
    if direct_phone:
        return direct_phone

    candidates: list[str] = []
    resume_data = payload.get("resume_data", {})
    if isinstance(resume_data, dict):
        resource_info = resume_data.get("resource_info", {})
        if isinstance(resource_info, dict):
            candidates.extend(str(v) for v in resource_info.values())
        summary_items = resume_data.get("summary_items", [])
        if isinstance(summary_items, list):
            candidates.extend(str(v) for v in summary_items)
    candidates.append(str(payload.get("candidate_name", "")))
    candidates.append(input_path.name)

    for item in candidates:
        phone = extract_phone_from_text(item)
        if phone:
            return phone
    return "无手机号"


def build_output_filename(payload: dict[str, Any], input_path: Path, job_id: str) -> str:
    candidate_name = str(payload.get("candidate_name", "")).strip() or "候选人"
    phone = pick_phone_number(payload, input_path)
    name_part = sanitize_docx_part(candidate_name, "候选人")
    phone_part = sanitize_docx_part(phone, "无手机号")
    base = f"{name_part}-{phone_part}-TEK"
    filename = f"{base}.docx"
    candidate_path = OUTPUT_DIR / filename
    if candidate_path.exists():
        suffix = hashlib.sha256(job_id.encode("utf-8")).hexdigest()[:6]
        filename = f"{base}-{suffix}.docx"
    return filename


def parse_iso_time(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return datetime.now()


def file_size_bytes(path: Path) -> int:
    try:
        return path.stat().st_size
    except FileNotFoundError:
        return 0


def folder_size_bytes(folder: Path) -> int:
    if not folder.exists():
        return 0
    total = 0
    for path in folder.iterdir():
        if path.is_file():
            total += file_size_bytes(path)
    return total


def prune_folder_by_size(folder: Path, max_bytes: int) -> None:
    if max_bytes <= 0:
        return
    if not folder.exists():
        return
    files = [p for p in folder.iterdir() if p.is_file()]
    files.sort(key=lambda p: p.stat().st_mtime if p.exists() else 0)
    total = sum(file_size_bytes(path) for path in files)
    for path in files:
        if total <= max_bytes:
            break
        size = file_size_bytes(path)
        try:
            path.unlink()
            total -= size
        except FileNotFoundError:
            continue


def list_runtime_files(folder: Path, limit: int = STATS_RUNTIME_FILE_LIMIT) -> list[dict[str, Any]]:
    if not folder.exists():
        return []
    entries: list[dict[str, Any]] = []
    for path in folder.iterdir():
        if not path.is_file():
            continue
        stat = path.stat()
        entries.append(
            {
                "name": path.name,
                "size_bytes": stat.st_size,
                "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
            }
        )
    entries.sort(key=lambda item: item["modified_at"], reverse=True)
    return entries[:limit]


@dataclass
class JobState:
    id: str
    status: str = "queued"
    progress: int = 0
    message: str = "等待处理"
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)
    input_file: Optional[str] = None
    output_file: Optional[str] = None
    error: Optional[str] = None
    download_token: Optional[str] = None
    download_token_expires_at: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        output_name = Path(self.output_file).name if self.output_file else None
        download_url = None
        if self.status == "done":
            download_url = f"/api/jobs/{self.id}/download"
            if self.download_token:
                download_url = f"{download_url}?token={self.download_token}"
        return {
            "id": self.id,
            "status": self.status,
            "progress": self.progress,
            "message": self.message,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "download_url": download_url,
            "output_name": output_name,
            "error": self.error,
        }


@dataclass
class DistillJobState:
    id: str
    status: str = "queued"
    progress: int = 0
    message: str = "等待蒸馏"
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)
    total_files: int = 0
    processed_files: int = 0
    result_json: Optional[str] = None
    error: Optional[str] = None
    stdout_preview: Optional[str] = None
    stderr_preview: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        result_name = Path(self.result_json).name if self.result_json else None
        result_url = None
        if self.status == "done" and self.result_json:
            result_url = f"/api/nvwa/jobs/{self.id}/result"
        return {
            "id": self.id,
            "status": self.status,
            "progress": self.progress,
            "message": self.message,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "total_files": self.total_files,
            "processed_files": self.processed_files,
            "result_name": result_name,
            "result_url": result_url,
            "error": self.error,
            "stdout_preview": self.stdout_preview,
            "stderr_preview": self.stderr_preview,
        }


JOBS: dict[str, JobState] = {}
JOBS_LOCK = threading.Lock()
DISTILL_JOBS: dict[str, DistillJobState] = {}
DISTILL_JOBS_LOCK = threading.Lock()
RATE_LIMITER = RateLimiter(RATE_LIMITS)
LLM_SEMAPHORE = threading.BoundedSemaphore(LLM_CONCURRENCY_LIMIT)
CONVERT_SEMAPHORE = threading.BoundedSemaphore(CONVERT_CONCURRENCY_LIMIT)
STATS_SESSION_STORE = SessionStore(STATS_SESSION_TTL_SECONDS)
NVWA_SESSION_STORE = SessionStore(NVWA_SESSION_TTL_SECONDS)
NGINX_COMBINED_LOG_PATTERN = re.compile(
    r'^(?P<ip>\S+) \S+ \S+ \[(?P<time>[^\]]+)\] "(?P<request>[^"]*)" '
    r"(?P<status>\d{3}) (?P<size>\S+) \"(?P<referer>[^\"]*)\" \"(?P<ua>[^\"]*)\""
)


def get_client_ip(request: Request) -> str:
    forwarded_for = request.headers.get("x-forwarded-for", "")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip() or "unknown"
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def enforce_rate_limit(request: Request, scope: str) -> None:
    RATE_LIMITER.enforce(request, scope, get_client_ip)


def update_job(job_id: str, **kwargs: Any) -> None:
    with JOBS_LOCK:
        job = JOBS[job_id]
        for key, value in kwargs.items():
            setattr(job, key, value)
        job.updated_at = now_iso()


def resolve_llm_config(api_key_override: Optional[str]) -> dict[str, str]:
    if api_key_override:
        cfg = get_deepseek_config()
        return {
            "api_key": api_key_override,
            "base_url": cfg["base_url"],
            "model": cfg["model"],
        }
    return ensure_deepseek_ready()


def issue_download_token() -> tuple[str, str]:
    expires_at = datetime.now() + timedelta(seconds=DOWNLOAD_TOKEN_TTL_SECONDS)
    return secrets.token_urlsafe(24), expires_at.isoformat(timespec="seconds")


def ensure_job_download_token(job: JobState) -> None:
    if job.status != "done":
        return
    if not job.download_token or not job.download_token_expires_at:
        job.download_token, job.download_token_expires_at = issue_download_token()
        return
    if parse_iso_time(job.download_token_expires_at) <= datetime.now():
        job.download_token, job.download_token_expires_at = issue_download_token()


def cleanup_job_artifacts(job: JobState) -> None:
    paths: list[Path] = []
    if job.input_file:
        paths.append(Path(job.input_file))
    if job.output_file:
        paths.append(Path(job.output_file))
    for path in paths:
        if path.exists():
            path.unlink()


def delete_job(job_id: str) -> None:
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="任务不存在")
        if job.status not in {"done", "failed"}:
            raise HTTPException(status_code=400, detail="任务处理中，暂不可删除")
        cleanup_job_artifacts(job)
        JOBS.pop(job_id, None)


def list_distill_files() -> list[dict[str, Any]]:
    ensure_runtime_dirs()
    files: list[dict[str, Any]] = []
    for path in DISTILL_WATCH_DIR.iterdir():
        if not path.is_file():
            continue
        stat = path.stat()
        files.append(
            {
                "name": path.name,
                "size_bytes": stat.st_size,
                "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
            }
        )
    files.sort(key=lambda item: item["modified_at"], reverse=True)
    return files


def get_distill_page(page: int, page_size: int) -> dict[str, Any]:
    safe_page = max(1, page)
    safe_size = min(max(1, page_size), DISTILL_MAX_PAGE_SIZE)
    all_files = list_distill_files()
    total = len(all_files)
    start = (safe_page - 1) * safe_size
    end = start + safe_size
    page_items = all_files[start:end]
    return {
        "items": page_items,
        "total": total,
        "page": safe_page,
        "page_size": safe_size,
        "total_pages": max(1, (total + safe_size - 1) // safe_size),
        "updated_at": now_iso(),
    }


def resolve_distill_file_path(filename: str) -> Path:
    clean_name = Path(filename).name
    if clean_name != filename or clean_name in {"", ".", ".."}:
        raise HTTPException(status_code=400, detail="文件名不合法")
    target = (DISTILL_WATCH_DIR / clean_name).resolve()
    if target.parent != DISTILL_WATCH_DIR:
        raise HTTPException(status_code=400, detail="非法路径")
    return target


def update_distill_job(job_id: str, **kwargs: Any) -> None:
    with DISTILL_JOBS_LOCK:
        job = DISTILL_JOBS[job_id]
        for key, value in kwargs.items():
            setattr(job, key, value)
        job.updated_at = now_iso()


def build_hermes_distill_command(input_dir: Path, output_json: Path) -> list[str]:
    if not HERMES_DISTILL_COMMAND:
        raise RuntimeError(
            "未配置 WEB_HERMES_DISTILL_COMMAND，无法调用本地 Hermes skill。"
            "请配置示例：WEB_HERMES_DISTILL_COMMAND='hermes run \"distill-docs --input {input_dir} --output {output_json}\"'"
        )
    command_text = (
        HERMES_DISTILL_COMMAND.replace("{input_dir}", str(input_dir)).replace("{output_json}", str(output_json))
    )
    parts = shlex.split(command_text)
    if not parts:
        raise RuntimeError("WEB_HERMES_DISTILL_COMMAND 为空，无法执行蒸馏任务")
    return parts


def run_distill_job(job_id: str) -> None:
    ensure_runtime_dirs()
    files = list_distill_files()
    total_files = len(files)
    output_json = OUTPUT_DIR / f"distill-{job_id}.json"
    update_distill_job(
        job_id,
        status="processing",
        progress=15,
        message="正在准备蒸馏任务",
        total_files=total_files,
        processed_files=0,
    )
    if total_files == 0:
        update_distill_job(
            job_id,
            status="failed",
            progress=100,
            message="蒸馏失败",
            error="目录为空，请先上传文件",
        )
        return

    try:
        command = build_hermes_distill_command(DISTILL_WATCH_DIR, output_json)
        update_distill_job(job_id, progress=45, message="正在调用 Hermes skill")
        completed = subprocess.run(  # noqa: S603
            command,
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=HERMES_DISTILL_TIMEOUT_SECONDS,
            check=False,
        )
        stdout_preview = (completed.stdout or "").strip()[-2000:]
        stderr_preview = (completed.stderr or "").strip()[-2000:]
        if completed.returncode != 0:
            raise RuntimeError(
                f"Hermes 执行失败（exit={completed.returncode}）："
                f"{stderr_preview or stdout_preview or '无输出'}"
            )
        if not output_json.exists():
            raise RuntimeError("Hermes 执行完成但未产出输出文件，请检查技能命令")
        update_distill_job(
            job_id,
            status="done",
            progress=100,
            message="蒸馏完成",
            processed_files=total_files,
            result_json=str(output_json),
            stdout_preview=stdout_preview or None,
            stderr_preview=stderr_preview or None,
        )
    except subprocess.TimeoutExpired as exc:
        update_distill_job(
            job_id,
            status="failed",
            progress=100,
            message="蒸馏超时",
            error=f"超过超时时间 {HERMES_DISTILL_TIMEOUT_SECONDS}s：{exc}",
        )
    except Exception as exc:  # noqa: BLE001
        update_distill_job(
            job_id,
            status="failed",
            progress=100,
            message="蒸馏失败",
            error=str(exc),
        )


def cleanup_runtime_tmp_files() -> None:
    ensure_runtime_dirs()
    prune_folder_by_size(UPLOAD_DIR, UPLOADS_MAX_BYTES)
    prune_folder_by_size(OUTPUT_DIR, OUTPUTS_MAX_BYTES)
    prune_folder_by_size(DISTILL_WATCH_DIR, DISTILL_MAX_BYTES)


def cleanup_expired_jobs_forever() -> None:
    while True:
        now = datetime.now()
        expired_ids: list[str] = []
        with JOBS_LOCK:
            for job_id, job in JOBS.items():
                if job.status not in {"done", "failed"}:
                    continue
                updated_at = parse_iso_time(job.updated_at)
                if now - updated_at >= timedelta(seconds=FILE_RETENTION_SECONDS):
                    expired_ids.append(job_id)
            for job_id in expired_ids:
                JOBS.pop(job_id, None)
        cleanup_runtime_tmp_files()
        time.sleep(max(CLEANUP_SCAN_INTERVAL_SECONDS, 10))


def create_stats_session() -> tuple[str, str]:
    return STATS_SESSION_STORE.create()


def is_stats_session_valid(token: str) -> bool:
    return STATS_SESSION_STORE.is_valid(token)


def ensure_stats_auth(authorization: Optional[str]) -> None:
    STATS_SESSION_STORE.ensure_auth(authorization)


def create_nvwa_session() -> tuple[str, str]:
    return NVWA_SESSION_STORE.create()


def is_nvwa_session_valid(token: str) -> bool:
    return NVWA_SESSION_STORE.is_valid(token)


def ensure_nvwa_auth(authorization: Optional[str]) -> None:
    NVWA_SESSION_STORE.ensure_auth(authorization)


def read_recent_lines(path: Path, max_lines: int) -> list[str]:
    if max_lines <= 0:
        return []
    queue: deque[str] = deque(maxlen=max_lines)
    with path.open("r", encoding="utf-8", errors="ignore") as handle:
        for line in handle:
            queue.append(line.rstrip("\n"))
    return list(queue)


def parse_access_record(line: str) -> Optional[dict[str, Any]]:
    match = NGINX_COMBINED_LOG_PATTERN.match(line)
    if not match:
        return None
    request = match.group("request")
    method, path = "-", "-"
    if request and request != "-":
        parts = request.split(" ")
        if len(parts) >= 2:
            method, path = parts[0], parts[1]
    size_text = match.group("size")
    size = int(size_text) if size_text.isdigit() else 0
    try:
        timestamp = datetime.strptime(match.group("time"), "%d/%b/%Y:%H:%M:%S %z")
    except ValueError:
        return None
    return {
        "ip": match.group("ip"),
        "timestamp": timestamp,
        "method": method,
        "path": path,
        "status": match.group("status"),
        "size": size,
    }


def collect_access_stats(target_date: datetime.date) -> dict[str, Any]:
    if not NGINX_ACCESS_LOG.exists():
        raise HTTPException(status_code=404, detail=f"Nginx access 日志不存在: {NGINX_ACCESS_LOG}")

    lines = read_recent_lines(NGINX_ACCESS_LOG, STATS_MAX_LOG_LINES)
    ip_counter: defaultdict[str, int] = defaultdict(int)
    path_counter: defaultdict[str, int] = defaultdict(int)
    status_counter: defaultdict[str, int] = defaultdict(int)
    hourly_counter: defaultdict[int, int] = defaultdict(int)
    total_bytes = 0
    total_requests = 0
    recent_requests: deque[dict[str, Any]] = deque(maxlen=30)

    for line in lines:
        record = parse_access_record(line)
        if not record:
            continue
        ts = record["timestamp"].astimezone()
        if ts.date() != target_date:
            continue
        ip = str(record["ip"])
        path = str(record["path"])
        status = str(record["status"])
        ip_counter[ip] += 1
        path_counter[path] += 1
        status_counter[status] += 1
        hourly_counter[ts.hour] += 1
        total_requests += 1
        total_bytes += int(record["size"])
        recent_requests.append(
            {
                "time": ts.strftime("%H:%M:%S"),
                "ip": ip,
                "path": path,
                "status": status,
            }
        )

    hourly = [{"hour": f"{hour:02d}:00", "count": hourly_counter.get(hour, 0)} for hour in range(24)]
    top_ips = sorted(ip_counter.items(), key=lambda item: item[1], reverse=True)[:20]
    top_paths = sorted(path_counter.items(), key=lambda item: item[1], reverse=True)[:20]
    status_breakdown = sorted(status_counter.items(), key=lambda item: item[1], reverse=True)

    return {
        "date": target_date.isoformat(),
        "generated_at": now_iso(),
        "source_log": str(NGINX_ACCESS_LOG),
        "processed_lines": len(lines),
        "total_requests": total_requests,
        "total_bytes": total_bytes,
        "unique_ips": len(ip_counter),
        "top_ips": [{"ip": ip, "count": count} for ip, count in top_ips],
        "top_paths": [{"path": path, "count": count} for path, count in top_paths],
        "status_breakdown": [{"status": status, "count": count} for status, count in status_breakdown],
        "hourly": hourly,
        "recent_requests": list(recent_requests),
        "runtime_storage": {
            "uploads": {
                "path": str(UPLOAD_DIR),
                "max_bytes": UPLOADS_MAX_BYTES,
                "total_bytes": folder_size_bytes(UPLOAD_DIR),
                "files": list_runtime_files(UPLOAD_DIR),
            },
            "outputs": {
                "path": str(OUTPUT_DIR),
                "max_bytes": OUTPUTS_MAX_BYTES,
                "total_bytes": folder_size_bytes(OUTPUT_DIR),
                "files": list_runtime_files(OUTPUT_DIR),
            },
        },
    }


def run_conversion(job_id: str, input_path: Path, api_key_override: Optional[str]) -> None:
    ensure_runtime_dirs()
    text_path = UPLOAD_DIR / f"{job_id}.txt"
    json_path = OUTPUT_DIR / f"{job_id}.json"
    acquired = CONVERT_SEMAPHORE.acquire(timeout=CONVERT_QUEUE_TIMEOUT_SECONDS)
    if not acquired:
        update_job(
            job_id,
            status="failed",
            progress=100,
            message="转换失败",
            error="任务队列繁忙，请稍后重试",
        )
        return
    try:
        update_job(job_id, status="processing", progress=10, message="正在提取简历文本")
        resume_text = extract_resume_text(input_path)
        text_path.write_text(resume_text, encoding="utf-8")

        update_job(job_id, progress=45, message="正在调用模型解析简历")
        llm_cfg = resolve_llm_config(api_key_override)
        acquired = LLM_SEMAPHORE.acquire(timeout=LLM_QUEUE_TIMEOUT_SECONDS)
        if not acquired:
            raise RuntimeError("模型服务繁忙，请稍后重试")
        try:
            parsed = call_deepseek_resume_parser(
                resume_text,
                llm_cfg=llm_cfg,
                source_filename=input_path.name,
            )
        finally:
            LLM_SEMAPHORE.release()
        payload = normalize_resume_data(parsed)
        json_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        if not payload.get("is_valid_resume", False):
            reason = payload.get("rejection_reason", "简历信息不足，无法生成")
            raise RuntimeError(f"简历校验未通过：{reason}")

        update_job(job_id, progress=80, message="正在生成 DOCX 文件")
        output_name = build_output_filename(payload, input_path, job_id)
        output_path = OUTPUT_DIR / output_name
        fill_template(TEMPLATE_PATH, payload["resume_data"], output_path)
        download_token, download_token_expires_at = issue_download_token()

        update_job(
            job_id,
            status="done",
            progress=100,
            message="转换完成，可下载文件",
            output_file=str(output_path),
            download_token=download_token,
            download_token_expires_at=download_token_expires_at,
        )
    except Exception as exc:  # noqa: BLE001
        update_job(
            job_id,
            status="failed",
            progress=100,
            message="转换失败",
            error=str(exc),
        )
    finally:
        if text_path.exists():
            text_path.unlink()
        cleanup_runtime_tmp_files()
        CONVERT_SEMAPHORE.release()


def create_app() -> FastAPI:
    ensure_runtime_dirs()

    app = FastAPI(title="Resume Web Converter", version="1.0.0")
    cleanup_thread = threading.Thread(target=cleanup_expired_jobs_forever, daemon=True)
    cleanup_thread.start()

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"ok": "true"}

    @app.get("/api/favicon.png")
    def favicon() -> FileResponse:
        icon_path = WEB_ROOT / "resume.png"
        if not icon_path.exists():
            raise HTTPException(status_code=404, detail="favicon 文件不存在")
        return FileResponse(path=icon_path, media_type="image/png")

    @app.get("/favicon.ico")
    def favicon_ico() -> FileResponse:
        icon_path = WEB_ROOT / "resume.png"
        if not icon_path.exists():
            raise HTTPException(status_code=404, detail="favicon 文件不存在")
        return FileResponse(path=icon_path, media_type="image/png")

    @app.post("/api/convert")
    async def convert(
        request: Request,
        file: UploadFile = File(...),
        x_deepseek_api_key: Optional[str] = Header(default=None, alias="X-DeepSeek-Api-Key"),
    ) -> dict[str, str]:
        enforce_rate_limit(request, "convert")
        ensure_runtime_dirs()
        suffix = Path(file.filename or "").suffix.lower()
        if suffix not in SUPPORTED_EXTENSIONS:
            raise HTTPException(status_code=400, detail="仅支持 PDF/DOCX/TXT/MD 格式")
        if not TEMPLATE_PATH.exists():
            raise HTTPException(status_code=500, detail="模板文件不存在，无法转换")
        request_api_key = (x_deepseek_api_key or "").strip() or None
        if not request_api_key:
            raise HTTPException(status_code=400, detail="请先在页面配置 DeepSeek API Key")

        job_id = uuid.uuid4().hex
        filename = secure_filename(file.filename or f"resume{suffix}")
        input_path = UPLOAD_DIR / f"{job_id}-{filename}"
        input_path.write_bytes(await file.read())

        with JOBS_LOCK:
            JOBS[job_id] = JobState(id=job_id, input_file=str(input_path))

        worker = threading.Thread(
            target=run_conversion,
            args=(job_id, input_path, request_api_key),
            daemon=True,
        )
        worker.start()
        return {"job_id": job_id}

    @app.post("/api/stats/login")
    def stats_login(
        payload: Optional[dict[str, str]] = Body(default=None),
    ) -> dict[str, str]:
        body = payload or {}
        username = str(body.get("username", "")).strip()
        password = str(body.get("password", "")).strip()
        if username != STATS_USERNAME or password != STATS_PASSWORD:
            raise HTTPException(status_code=401, detail="用户名或密码错误")
        token, expires_at = create_stats_session()
        return {"token": token, "expires_at": expires_at}

    @app.get("/api/stats/overview")
    def stats_overview(
        authorization: Optional[str] = Header(default=None, alias="Authorization"),
        date: Optional[str] = None,
    ) -> dict[str, Any]:
        ensure_stats_auth(authorization)
        if date:
            try:
                target_date = datetime.strptime(date, "%Y-%m-%d").date()
            except ValueError as exc:
                raise HTTPException(status_code=400, detail="date 必须是 YYYY-MM-DD") from exc
        else:
            target_date = datetime.now().date()
        return collect_access_stats(target_date)

    @app.get("/api/jobs/{job_id}")
    def get_job(request: Request, job_id: str) -> dict[str, Any]:
        enforce_rate_limit(request, "job_status")
        with JOBS_LOCK:
            job = JOBS.get(job_id)
            if not job:
                raise HTTPException(status_code=404, detail="任务不存在")
            ensure_job_download_token(job)
            return job.to_dict()

    @app.get("/api/jobs/{job_id}/download")
    def download(request: Request, job_id: str, token: Optional[str] = None) -> FileResponse:
        enforce_rate_limit(request, "download")
        with JOBS_LOCK:
            job = JOBS.get(job_id)
            if not job:
                raise HTTPException(status_code=404, detail="任务不存在")
            if job.status != "done" or not job.output_file:
                raise HTTPException(status_code=400, detail="任务未完成，暂不可下载")
            ensure_job_download_token(job)
            if not token or token != job.download_token:
                raise HTTPException(status_code=403, detail="下载链接已失效，请刷新任务状态后重试")
            if not job.download_token_expires_at or parse_iso_time(job.download_token_expires_at) <= datetime.now():
                raise HTTPException(status_code=403, detail="下载链接已过期，请刷新任务状态后重试")
            path = Path(job.output_file)
        if not path.exists():
            raise HTTPException(status_code=404, detail="输出文件不存在")
        return FileResponse(path=path, filename=path.name, media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")

    @app.delete("/api/jobs/{job_id}")
    def remove_job(request: Request, job_id: str) -> dict[str, str]:
        enforce_rate_limit(request, "delete_job")
        delete_job(job_id)
        return {"ok": "true"}

    @app.post("/api/nvwa/login")
    def nvwa_login(payload: Optional[dict[str, str]] = Body(default=None)) -> dict[str, str]:
        body = payload or {}
        username = str(body.get("username", "")).strip()
        password = str(body.get("password", "")).strip()
        if username != NVWA_USERNAME or password != NVWA_PASSWORD:
            raise HTTPException(status_code=401, detail="用户名或密码错误")
        token, expires_at = create_nvwa_session()
        return {"token": token, "expires_at": expires_at}

    @app.get("/api/nvwa/files")
    def list_distill_files_api(
        authorization: Optional[str] = Header(default=None, alias="Authorization"),
        page: int = 1,
        page_size: int = DISTILL_PAGE_SIZE,
    ) -> dict[str, Any]:
        ensure_nvwa_auth(authorization)
        return get_distill_page(page, page_size)

    @app.post("/api/nvwa/upload")
    async def upload_distill_file(
        file: UploadFile = File(...),
        authorization: Optional[str] = Header(default=None, alias="Authorization"),
    ) -> dict[str, Any]:
        ensure_nvwa_auth(authorization)
        ensure_runtime_dirs()
        original_name = secure_filename(file.filename or "upload.bin")
        if not original_name:
            raise HTTPException(status_code=400, detail="文件名不能为空")
        target = DISTILL_WATCH_DIR / original_name
        if target.exists():
            stem = target.stem
            suffix = target.suffix
            target = DISTILL_WATCH_DIR / f"{stem}-{uuid.uuid4().hex[:8]}{suffix}"
        target.write_bytes(await file.read())
        cleanup_runtime_tmp_files()
        return {
            "ok": True,
            "name": target.name,
            "size_bytes": file_size_bytes(target),
            "updated_at": now_iso(),
        }

    @app.delete("/api/nvwa/files/{filename}")
    def delete_distill_file(
        filename: str,
        authorization: Optional[str] = Header(default=None, alias="Authorization"),
    ) -> dict[str, Any]:
        ensure_nvwa_auth(authorization)
        target = resolve_distill_file_path(filename)
        if not target.exists():
            raise HTTPException(status_code=404, detail="文件不存在")
        target.unlink()
        return {"ok": True, "deleted": filename}

    @app.post("/api/nvwa/start")
    def start_distill(
        authorization: Optional[str] = Header(default=None, alias="Authorization"),
    ) -> dict[str, str]:
        ensure_nvwa_auth(authorization)
        files = list_distill_files()
        if not files:
            raise HTTPException(status_code=400, detail="目录为空，请先上传文件")
        with DISTILL_JOBS_LOCK:
            running_job = next((job for job in DISTILL_JOBS.values() if job.status == "processing"), None)
            if running_job:
                return {"job_id": running_job.id}
            job_id = uuid.uuid4().hex
            DISTILL_JOBS[job_id] = DistillJobState(id=job_id, total_files=len(files))
        worker = threading.Thread(target=run_distill_job, args=(job_id,), daemon=True)
        worker.start()
        return {"job_id": job_id}

    @app.get("/api/nvwa/jobs/{job_id}")
    def get_distill_job(
        job_id: str,
        authorization: Optional[str] = Header(default=None, alias="Authorization"),
    ) -> dict[str, Any]:
        ensure_nvwa_auth(authorization)
        with DISTILL_JOBS_LOCK:
            job = DISTILL_JOBS.get(job_id)
            if not job:
                raise HTTPException(status_code=404, detail="蒸馏任务不存在")
            return job.to_dict()

    @app.get("/api/nvwa/jobs/{job_id}/result")
    def download_distill_result(
        job_id: str,
        authorization: Optional[str] = Header(default=None, alias="Authorization"),
    ) -> FileResponse:
        ensure_nvwa_auth(authorization)
        with DISTILL_JOBS_LOCK:
            job = DISTILL_JOBS.get(job_id)
            if not job:
                raise HTTPException(status_code=404, detail="蒸馏任务不存在")
            if job.status != "done" or not job.result_json:
                raise HTTPException(status_code=400, detail="蒸馏任务未完成")
            output_path = Path(job.result_json)
        if not output_path.exists():
            raise HTTPException(status_code=404, detail="蒸馏结果不存在")
        return FileResponse(path=output_path, filename=output_path.name, media_type="application/json")

    @app.get("/nvwa")
    @app.get("/nvwa/")
    def nvwa_page() -> FileResponse:
        nvwa_index = FRONTEND_DIST_DIR / "nvwa" / "index.html"
        if not nvwa_index.exists():
            raise HTTPException(status_code=404, detail="nvwa 页面尚未构建")
        return FileResponse(path=nvwa_index, media_type="text/html")

    # 注意：静态路由必须放在 API 路由后面，避免拦截 /api 请求。
    if FRONTEND_DIST_DIR.exists():
        app.mount("/", StaticFiles(directory=str(FRONTEND_DIST_DIR), html=True), name="web")

    return app


app = create_app()
