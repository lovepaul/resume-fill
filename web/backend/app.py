from __future__ import annotations

import json
import os
import re
import threading
import time
import tempfile
import hashlib
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, Header, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

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
RUNTIME_DIR = Path(os.environ.get("WEB_TMP_DIR", f"{tempfile.gettempdir()}/resume-web")).resolve()
UPLOAD_DIR = RUNTIME_DIR / "uploads"
OUTPUT_DIR = RUNTIME_DIR / "outputs"
FRONTEND_DIST_DIR = WEB_ROOT / "frontend" / "dist"
TEMPLATE_PATH = PROJECT_ROOT / "muban" / "简历模板 TEK.docx"
SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md"}
FILE_RETENTION_SECONDS = int(os.environ.get("WEB_FILE_RETENTION_SECONDS", "3600"))
CLEANUP_SCAN_INTERVAL_SECONDS = int(os.environ.get("WEB_CLEANUP_SCAN_INTERVAL_SECONDS", "60"))
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


def pick_phone_number(payload: dict[str, Any], input_path: Path) -> str:
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


@dataclass
class JobState:
    id: str
    status: str = "queued"
    progress: int = 0
    message: str = "等待处理"
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)
    input_file: str | None = None
    output_file: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "status": self.status,
            "progress": self.progress,
            "message": self.message,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "download_url": f"/api/jobs/{self.id}/download"
            if self.status == "done"
            else None,
            "error": self.error,
        }


JOBS: dict[str, JobState] = {}
JOBS_LOCK = threading.Lock()
RATE_LIMIT_BUCKETS: dict[str, deque[float]] = defaultdict(deque)
RATE_LIMIT_LOCK = threading.Lock()


def get_client_ip(request: Request) -> str:
    forwarded_for = request.headers.get("x-forwarded-for", "")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip() or "unknown"
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def enforce_rate_limit(request: Request, scope: str) -> None:
    if scope not in RATE_LIMITS:
        return
    max_requests, window_seconds = RATE_LIMITS[scope]
    client_ip = get_client_ip(request)
    now = time.time()
    bucket_key = f"{scope}:{client_ip}"

    with RATE_LIMIT_LOCK:
        bucket = RATE_LIMIT_BUCKETS[bucket_key]
        while bucket and bucket[0] <= now - window_seconds:
            bucket.popleft()
        if len(bucket) >= max_requests:
            retry_after = max(1, int(window_seconds - (now - bucket[0])))
            raise HTTPException(
                status_code=429,
                detail=f"请求过于频繁，请 {retry_after} 秒后重试",
            )
        bucket.append(now)


def update_job(job_id: str, **kwargs: Any) -> None:
    with JOBS_LOCK:
        job = JOBS[job_id]
        for key, value in kwargs.items():
            setattr(job, key, value)
        job.updated_at = now_iso()


def resolve_llm_config(api_key_override: str | None) -> dict[str, str]:
    if api_key_override:
        cfg = get_deepseek_config()
        return {
            "api_key": api_key_override,
            "base_url": cfg["base_url"],
            "model": cfg["model"],
        }
    return ensure_deepseek_ready()


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


def cleanup_runtime_tmp_files() -> None:
    cutoff = time.time() - FILE_RETENTION_SECONDS
    for folder in (UPLOAD_DIR, OUTPUT_DIR):
        if not folder.exists():
            continue
        for path in folder.iterdir():
            try:
                if not path.is_file():
                    continue
                if path.stat().st_mtime <= cutoff:
                    path.unlink()
            except FileNotFoundError:
                continue


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
                    cleanup_job_artifacts(job)
                    expired_ids.append(job_id)
            for job_id in expired_ids:
                JOBS.pop(job_id, None)
        cleanup_runtime_tmp_files()
        time.sleep(max(CLEANUP_SCAN_INTERVAL_SECONDS, 10))


def run_conversion(job_id: str, input_path: Path, api_key_override: str | None) -> None:
    text_path = UPLOAD_DIR / f"{job_id}.txt"
    json_path = OUTPUT_DIR / f"{job_id}.json"
    try:
        update_job(job_id, status="processing", progress=10, message="正在提取简历文本")
        resume_text = extract_resume_text(input_path)
        text_path.write_text(resume_text, encoding="utf-8")

        update_job(job_id, progress=45, message="正在调用模型解析简历")
        llm_cfg = resolve_llm_config(api_key_override)
        parsed = call_deepseek_resume_parser(resume_text, llm_cfg=llm_cfg)
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

        update_job(
            job_id,
            status="done",
            progress=100,
            message="转换完成，可下载文件",
            output_file=str(output_path),
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


def create_app() -> FastAPI:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

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
        x_deepseek_api_key: str | None = Header(default=None, alias="X-DeepSeek-Api-Key"),
    ) -> dict[str, str]:
        enforce_rate_limit(request, "convert")
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

    @app.get("/api/jobs/{job_id}")
    def get_job(request: Request, job_id: str) -> dict[str, Any]:
        enforce_rate_limit(request, "job_status")
        with JOBS_LOCK:
            job = JOBS.get(job_id)
            if not job:
                raise HTTPException(status_code=404, detail="任务不存在")
            return job.to_dict()

    @app.get("/api/jobs/{job_id}/download")
    def download(request: Request, job_id: str) -> FileResponse:
        enforce_rate_limit(request, "download")
        with JOBS_LOCK:
            job = JOBS.get(job_id)
            if not job:
                raise HTTPException(status_code=404, detail="任务不存在")
            if job.status != "done" or not job.output_file:
                raise HTTPException(status_code=400, detail="任务未完成，暂不可下载")
            path = Path(job.output_file)
        if not path.exists():
            raise HTTPException(status_code=404, detail="输出文件不存在")
        return FileResponse(path=path, filename=path.name, media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")

    @app.delete("/api/jobs/{job_id}")
    def remove_job(request: Request, job_id: str) -> dict[str, str]:
        enforce_rate_limit(request, "delete_job")
        delete_job(job_id)
        return {"ok": "true"}

    # 注意：静态路由必须放在 API 路由后面，避免拦截 /api 请求。
    if FRONTEND_DIST_DIR.exists():
        app.mount("/", StaticFiles(directory=str(FRONTEND_DIST_DIR), html=True), name="web")

    return app


app = create_app()
