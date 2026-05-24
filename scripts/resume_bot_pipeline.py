#!/usr/bin/env python3
"""
resume_bot_pipeline
===================
面向 Hermes + Telegram 的简历处理流水线：
1) 提取简历文本（PDF / DOCX / TXT）
2) 使用结构化 JSON 填充 TEK 模板
3) 通过 himalaya 发送附件邮件
4) 更新 tracker 与错误日志
"""

from __future__ import annotations

import argparse
import json
import sys
import subprocess
import os
import re
import time
import signal
import shutil
import urllib.request
import urllib.error
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

# 确保可从 scripts/ 目录运行并导入项目模块
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

TEMPLATE_PATH = PROJECT_ROOT / "muban" / "简历模板 TEK.docx"
VENV_DIR = Path(os.environ.get("RESUME_BOT_VENV_PATH", str(PROJECT_ROOT / ".venv")))
VENV_PYTHON = VENV_DIR / "bin" / "python"
VENV_READY_MARKER = VENV_DIR / ".resume_bot_ready"
REQUIREMENTS_PATH = PROJECT_ROOT / "requirements.txt"
REQUIREMENTS_LOCK_PATH = PROJECT_ROOT / "requirements.lock.txt"
REEXEC_FLAG = "RESUME_BOT_ALREADY_IN_VENV"
UV_BIN = os.environ.get("RESUME_BOT_UV_BIN", "uv")
RUNTIME_HOME = Path(
    os.environ.get("RESUME_BOT_HOME", str(Path.home() / ".hermes" / "resume-bot"))
)
TRACKER_PATH = RUNTIME_HOME / "tracker.json"
ERROR_LOG_PATH = RUNTIME_HOME / "errors.log"
BOT_CONFIG_PATH = RUNTIME_HOME / "bot_config.json"
TMP_DIR = Path(os.environ.get("RESUME_BOT_TMP_DIR", "/tmp/resume-bot"))
DEFAULT_OUTPUT = TMP_DIR / "简历_标准版.docx"
SESSION_LOCK_PATH = TMP_DIR / ".processing.lock"
STATUS_PATH = TMP_DIR / "status.json"
DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1/chat/completions"
DEFAULT_DEEPSEEK_MODEL = "deepseek-chat"
LOCK_STALE_SECONDS = int(os.environ.get("RESUME_BOT_LOCK_STALE_SECONDS", "900"))
CURRENT_PROCESS_HAS_LOCK = False


@dataclass
class PipelineResult:
    output_docx: Path
    tracker_total: int
    email_sent: bool
    recipient: str | None


def sanitize_filename_part(text: str) -> str:
    value = re.sub(r"[\\/:*?\"<>|]+", "_", text.strip())
    return value or "候选人"


def standard_docx_name(candidate_name: str) -> str:
    return f"{sanitize_filename_part(candidate_name)}-TEK-标准简历.docx"


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def render_progress_bar(progress: int, width: int = 10) -> str:
    p = max(0, min(100, int(progress)))
    filled = round((p / 100) * width)
    return "█" * filled + "░" * (width - filled)


def write_status(
    *,
    busy: bool,
    stage: str,
    progress: int,
    message: str,
    extra: dict[str, Any] | None = None,
) -> None:
    payload: dict[str, Any] = {
        "busy": busy,
        "stage": stage,
        "progress": progress,
        "message": message,
        "updated_at": now_iso(),
    }
    if extra:
        payload.update(extra)
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATUS_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def read_status() -> dict[str, Any]:
    if not STATUS_PATH.exists():
        return {
            "busy": False,
            "stage": "idle",
            "progress": 0,
            "message": "空闲",
            "updated_at": now_iso(),
        }
    try:
        return json.loads(STATUS_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {
            "busy": False,
            "stage": "idle",
            "progress": 0,
            "message": "空闲",
            "updated_at": now_iso(),
        }


def read_bot_config() -> dict[str, Any]:
    if not BOT_CONFIG_PATH.exists():
        return {}
    try:
        return json.loads(BOT_CONFIG_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def write_bot_config(data: dict[str, Any]) -> None:
    RUNTIME_HOME.mkdir(parents=True, exist_ok=True)
    BOT_CONFIG_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    os.chmod(BOT_CONFIG_PATH, 0o600)


def get_deepseek_config() -> dict[str, str]:
    env_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    env_url = os.environ.get("DEEPSEEK_BASE_URL", "").strip()
    env_model = os.environ.get("DEEPSEEK_MODEL", "").strip()
    file_cfg = read_bot_config()

    api_key = env_key or str(file_cfg.get("deepseek_api_key", "")).strip()
    base_url = (
        env_url
        or str(file_cfg.get("deepseek_base_url", "")).strip()
        or DEFAULT_DEEPSEEK_BASE_URL
    )
    model = (
        env_model
        or str(file_cfg.get("deepseek_model", "")).strip()
        or DEFAULT_DEEPSEEK_MODEL
    )
    return {"api_key": api_key, "base_url": base_url, "model": model}


def ensure_deepseek_ready() -> dict[str, str]:
    cfg = get_deepseek_config()
    if not cfg["api_key"]:
        raise RuntimeError(
            "DeepSeek API Key 未初始化。请先执行: "
            "python3 scripts/resume_bot_pipeline.py init-llm --deepseek-api-key <KEY>"
        )
    return cfg


def extract_json_block(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if "\n" in stripped:
            stripped = stripped.split("\n", 1)[1]
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("LLM 返回中未找到 JSON")
    return stripped[start : end + 1]


def validate_resume_data_schema(resume_data: dict[str, Any]) -> None:
    if not isinstance(resume_data, dict):
        raise ValueError("resume_data 必须是对象")

    required_top = [
        "resource_info",
        "summary_items",
        "education",
        "employment_history",
        "roles",
        "projects",
    ]
    for key in required_top:
        if key not in resume_data:
            raise ValueError(f"resume_data 缺少字段: {key}")

    resource_info = resume_data["resource_info"]
    if not isinstance(resource_info, dict):
        raise ValueError("resource_info 必须是对象")
    required_resource = [
        "city",
        "language",
        "birth",
        "gender",
        "interview_time",
        "status",
    ]
    for key in required_resource:
        if key not in resource_info:
            raise ValueError(f"resource_info 缺少字段: {key}")
        if not isinstance(resource_info[key], str):
            raise ValueError(f"resource_info.{key} 必须是字符串")

    if not isinstance(resume_data["summary_items"], list) or not all(
        isinstance(x, str) for x in resume_data["summary_items"]
    ):
        raise ValueError("summary_items 必须是字符串数组")

    if not isinstance(resume_data["education"], list):
        raise ValueError("education 必须是数组")
    for i, item in enumerate(resume_data["education"]):
        if not isinstance(item, dict):
            raise ValueError(f"education[{i}] 必须是对象")
        for key in ["period", "school", "degree"]:
            if key not in item or not isinstance(item[key], str):
                raise ValueError(f"education[{i}].{key} 必须是字符串")

    if not isinstance(resume_data["employment_history"], list):
        raise ValueError("employment_history 必须是数组")
    for i, item in enumerate(resume_data["employment_history"]):
        if not isinstance(item, dict):
            raise ValueError(f"employment_history[{i}] 必须是对象")
        for key in ["time", "employer", "role"]:
            if key not in item or not isinstance(item[key], str):
                raise ValueError(f"employment_history[{i}].{key} 必须是字符串")

    if not isinstance(resume_data["roles"], list):
        raise ValueError("roles 必须是数组")
    for i, item in enumerate(resume_data["roles"]):
        if not isinstance(item, dict):
            raise ValueError(f"roles[{i}] 必须是对象")
        for key in ["period", "company", "title"]:
            if key not in item or not isinstance(item[key], str):
                raise ValueError(f"roles[{i}].{key} 必须是字符串")
        for key in ["responsibilities", "achievements"]:
            if key not in item or not isinstance(item[key], list):
                raise ValueError(f"roles[{i}].{key} 必须是数组")
            if not all(isinstance(x, str) for x in item[key]):
                raise ValueError(f"roles[{i}].{key} 必须是字符串数组")

    if not isinstance(resume_data["projects"], list):
        raise ValueError("projects 必须是数组")
    for i, item in enumerate(resume_data["projects"]):
        if not isinstance(item, dict):
            raise ValueError(f"projects[{i}] 必须是对象")
        for key in ["period", "name", "description", "tech_stack"]:
            if key not in item or not isinstance(item[key], str):
                raise ValueError(f"projects[{i}].{key} 必须是字符串")
        for key in ["responsibilities", "achievements"]:
            if key not in item or not isinstance(item[key], list):
                raise ValueError(f"projects[{i}].{key} 必须是数组")
            if not all(isinstance(x, str) for x in item[key]):
                raise ValueError(f"projects[{i}].{key} 必须是字符串数组")


def validate_llm_payload_schema(payload: dict[str, Any]) -> None:
    for key in ["is_valid_resume", "rejection_reason", "candidate_name", "resume_data"]:
        if key not in payload:
            raise ValueError(f"LLM 输出缺少字段: {key}")
    if not isinstance(payload["is_valid_resume"], bool):
        raise ValueError("is_valid_resume 必须是布尔值")
    if not isinstance(payload["rejection_reason"], str):
        raise ValueError("rejection_reason 必须是字符串")
    if not isinstance(payload["candidate_name"], str):
        raise ValueError("candidate_name 必须是字符串")
    if not isinstance(payload["resume_data"], dict):
        raise ValueError("resume_data 必须是对象")
    validate_resume_data_schema(payload["resume_data"])


def call_deepseek_chat_json(
    *,
    llm_cfg: dict[str, str],
    system_prompt: str,
    user_prompt: str,
) -> dict[str, Any]:
    body = {
        "model": llm_cfg["model"],
        "temperature": 0.1,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "response_format": {"type": "json_object"},
    }
    req = urllib.request.Request(
        llm_cfg["base_url"],
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {llm_cfg['api_key']}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"DeepSeek API HTTP {e.code}: {detail}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"DeepSeek API 连接失败: {e}") from e

    response_obj = json.loads(raw)
    choices = response_obj.get("choices", [])
    if not choices:
        raise RuntimeError("DeepSeek 返回为空 choices")
    content = choices[0].get("message", {}).get("content", "")
    parsed = json.loads(extract_json_block(content))
    return parsed


def repair_llm_payload_once(
    *,
    llm_cfg: dict[str, str],
    invalid_payload_text: str,
    schema_error: str,
) -> dict[str, Any]:
    system_prompt = (
        "你是 JSON 结构修复助手。只修复 JSON 结构，不新增事实，不修改语义。"
        "必须输出严格 JSON，不要输出解释。"
    )
    user_prompt = f"""
下面是一段简历结构化 JSON，但不符合目标 schema。
请基于原始内容做最小必要修复，仅用于满足结构与类型要求。

【schema 错误】
{schema_error}

【目标规则】
1) 顶层字段必须且只能是：
   is_valid_resume(boolean), rejection_reason(string), candidate_name(string), resume_data(object)
2) resume_data 必须且只能包含：
   resource_info(object), summary_items(array<string>), education(array<object>),
   employment_history(array<object>), roles(array<object>), projects(array<object>)
3) resource_info 必须且只能包含字符串字段：
   city, language, birth, gender, interview_time, status
4) education 元素必须且只能包含字符串字段：period, school, degree
5) employment_history 元素必须且只能包含字符串字段：time, employer, role
6) roles 元素必须且只能包含：
   period(string), company(string), title(string),
   responsibilities(array<string>), achievements(array<string>)
7) projects 元素必须且只能包含：
   period(string), name(string), description(string), tech_stack(string),
   responsibilities(array<string>), achievements(array<string>)
8) 禁止 null；缺失字段补空字符串 "" 或空数组 []；禁止额外字段。

【待修复 JSON】
{invalid_payload_text}
"""
    repaired = call_deepseek_chat_json(
        llm_cfg=llm_cfg,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
    )
    validate_llm_payload_schema(repaired)
    return repaired


def call_deepseek_resume_parser(
    resume_text: str,
    llm_cfg: dict[str, str],
) -> dict[str, Any]:
    truncated = resume_text[:50000]
    system_prompt = (
        "你是简历结构化与风控校验助手。"
        "请先判断输入是否为有效真实简历文本，再输出严格 JSON，不要输出额外解释。"
    )
    user_prompt = f"""
你必须输出严格 JSON，且只能输出一个 JSON 对象，不得有任何解释文字、注释、markdown、代码块。

【文本优化与纠错要求（先做，再结构化）】
1) 先对简历原文进行轻量纠错：修复明显 OCR 错别字、断词、重复字符、乱码符号。
2) 修复明显语义错误：例如时间格式混乱、职位/公司字段错位、句子残缺导致语义不通。
3) 不得凭空捏造经历，不得补充原文没有的事实；只允许基于上下文做最小必要修正。
4) 如果某段信息无法可靠判断，保留原意并在结构化字段中使用保守值（空字符串或空数组）。
5) 姓名字段优先使用可置信的人名；无法确定时填“候选人”。

【硬性格式要求】
1) 顶层字段必须且只能是：
   is_valid_resume(boolean), rejection_reason(string), candidate_name(string), resume_data(object)
2) resume_data 必须且只能包含：
   resource_info(object), summary_items(array<string>), education(array<object>),
   employment_history(array<object>), roles(array<object>), projects(array<object>)
3) resource_info 必须且只能包含字符串字段：
   city, language, birth, gender, interview_time, status
4) education 元素必须且只能包含字符串字段：
   period, school, degree
5) employment_history 元素必须且只能包含字符串字段：
   time, employer, role
6) roles 元素必须且只能包含：
   period(string), company(string), title(string),
   responsibilities(array<string>), achievements(array<string>)
7) projects 元素必须且只能包含：
   period(string), name(string), description(string), tech_stack(string),
   responsibilities(array<string>), achievements(array<string>)
8) 严禁出现 null、数字、布尔（除 is_valid_resume）、对象扩展字段。
9) 缺失信息一律填空字符串 "" 或空数组 []，不允许省略字段。

【有效简历判定】
- 至少包含教育/工作/项目中的任意两类有效信息；
- 不能是广告、闲聊、无意义字符、明显伪造灌水；
- 若无效：is_valid_resume=false，rejection_reason 给出简短原因；
- 若有效：is_valid_resume=true，rejection_reason 必须是空字符串。

【输出样式示例（仅示例结构，内容按输入生成）】
{{
  "is_valid_resume": true,
  "rejection_reason": "",
  "candidate_name": "张三",
  "resume_data": {{
    "resource_info": {{
      "city": "",
      "language": "",
      "birth": "",
      "gender": "",
      "interview_time": "",
      "status": ""
    }},
    "summary_items": [],
    "education": [],
    "employment_history": [],
    "roles": [],
    "projects": []
  }}
}}

简历原文如下：
{truncated}
"""
    parsed = call_deepseek_chat_json(
        llm_cfg=llm_cfg,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
    )
    try:
        validate_llm_payload_schema(parsed)
        return parsed
    except Exception as schema_error:
        repaired = repair_llm_payload_once(
            llm_cfg=llm_cfg,
            invalid_payload_text=json.dumps(parsed, ensure_ascii=False),
            schema_error=str(schema_error),
        )
        return repaired


def normalize_resume_data(payload: dict[str, Any]) -> dict[str, Any]:
    if "resume_data" in payload:
        validate_llm_payload_schema(payload)
        return payload
    # 兼容旧格式：直接就是 resume_data
    return {
        "is_valid_resume": True,
        "rejection_reason": "",
        "candidate_name": "候选人",
        "resume_data": payload,
    }


def try_acquire_processing_lock(job_hint: str) -> bool:
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    now_ts = time.time()
    try:
        fd = os.open(str(SESSION_LOCK_PATH), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(fd, "w", encoding="utf-8") as lock_file:
            lock_file.write(
                json.dumps(
                    {
                        "pid": os.getpid(),
                        "job_hint": job_hint,
                        "started_at": now_iso(),
                        "started_at_ts": now_ts,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        return True
    except FileExistsError:
        lock_info = read_processing_lock()
        lock_pid = int(lock_info.get("pid", 0) or 0)
        lock_ts = float(lock_info.get("started_at_ts", 0) or 0)
        lock_is_stale = lock_ts > 0 and (now_ts - lock_ts) > LOCK_STALE_SECONDS
        lock_pid_dead = lock_pid > 0 and not is_pid_running(lock_pid)
        if lock_is_stale or lock_pid_dead:
            safe_delete_file(SESSION_LOCK_PATH)
            return try_acquire_processing_lock(job_hint=job_hint)
        return False


def release_processing_lock() -> None:
    safe_delete_file(SESSION_LOCK_PATH)


def read_processing_lock() -> dict[str, Any]:
    if not SESSION_LOCK_PATH.exists():
        return {}
    try:
        return json.loads(SESSION_LOCK_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def is_pid_running(pid: int) -> bool:
    try:
        if pid <= 0:
            return False
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def emergency_release_lock(reason: str) -> None:
    global CURRENT_PROCESS_HAS_LOCK
    if not CURRENT_PROCESS_HAS_LOCK:
        return
    release_processing_lock()
    CURRENT_PROCESS_HAS_LOCK = False
    write_status(
        busy=False,
        stage="failed",
        progress=100,
        message=f"任务中断并已自动清理锁: {reason}",
    )


def install_signal_cleanup() -> None:
    def _handler(signum: int, _frame: Any) -> None:
        emergency_release_lock(f"signal:{signum}")
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGINT, _handler)
    signal.signal(signal.SIGTERM, _handler)


def in_target_venv() -> bool:
    try:
        exe = Path(sys.executable).resolve()
        venv_bin = (VENV_DIR / "bin").resolve()
        return str(exe).startswith(f"{venv_bin}/")
    except Exception:
        return False


def ensure_uv_available() -> None:
    uv_path = shutil.which(UV_BIN)
    if uv_path:
        return
    if Path(UV_BIN).exists():
        return
    raise RuntimeError(
        "未检测到 uv，请先安装：https://docs.astral.sh/uv/getting-started/installation/"
    )


def ensure_skill_venv(reexec: bool = True) -> None:
    ensure_uv_available()
    if not VENV_PYTHON.exists():
        subprocess.run(
            [UV_BIN, "venv", str(VENV_DIR)],
            check=True,
            cwd=str(PROJECT_ROOT),
        )

    marker_stale = (
        (not VENV_READY_MARKER.exists())
        or VENV_READY_MARKER.stat().st_mtime < REQUIREMENTS_PATH.stat().st_mtime
        or (
            REQUIREMENTS_LOCK_PATH.exists()
            and VENV_READY_MARKER.stat().st_mtime < REQUIREMENTS_LOCK_PATH.stat().st_mtime
        )
    )
    if marker_stale:
        install_file = (
            REQUIREMENTS_LOCK_PATH if REQUIREMENTS_LOCK_PATH.exists() else REQUIREMENTS_PATH
        )
        install_cmd = (
            [UV_BIN, "pip", "sync", "--python", str(VENV_PYTHON), str(install_file)]
            if install_file == REQUIREMENTS_LOCK_PATH
            else [
                UV_BIN,
                "pip",
                "install",
                "--python",
                str(VENV_PYTHON),
                "-r",
                str(install_file),
            ]
        )
        subprocess.run(
            install_cmd,
            check=True,
            cwd=str(PROJECT_ROOT),
        )
        VENV_READY_MARKER.write_text(now_iso(), encoding="utf-8")

    already_reexec = os.environ.get(REEXEC_FLAG) == "1"
    if reexec and not in_target_venv() and not already_reexec:
        new_env = os.environ.copy()
        new_env[REEXEC_FLAG] = "1"
        os.execve(
            str(VENV_PYTHON),
            [str(VENV_PYTHON), str(Path(__file__).resolve()), *sys.argv[1:]],
            new_env,
        )


def ensure_runtime() -> None:
    RUNTIME_HOME.mkdir(parents=True, exist_ok=True)
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    if not TRACKER_PATH.exists():
        TRACKER_PATH.write_text(
            json.dumps(
                {"total_processed": 0, "history": [], "updated_at": now_iso()},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    if not ERROR_LOG_PATH.exists():
        ERROR_LOG_PATH.touch()
    if not STATUS_PATH.exists():
        write_status(
            busy=False, stage="idle", progress=0, message="空闲，等待新任务"
        )


def read_tracker() -> dict[str, Any]:
    ensure_runtime()
    try:
        return json.loads(TRACKER_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"total_processed": 0, "history": [], "updated_at": now_iso()}


def write_tracker(data: dict[str, Any]) -> None:
    data["updated_at"] = now_iso()
    TRACKER_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def log_error(stage: str, error: str) -> None:
    ensure_runtime()
    with ERROR_LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(f"[{now_iso()}] [{stage}] {error}\n")


def safe_delete_file(path: Path) -> None:
    try:
        if path.exists() and path.is_file():
            path.unlink()
    except Exception:
        # 清理失败不影响主流程
        pass


def extract_resume_text(resume_path: Path) -> str:
    suffix = resume_path.suffix.lower()
    if suffix == ".pdf":
        from src.extractor import extract_pdf_text

        return extract_pdf_text(str(resume_path))
    if suffix == ".docx":
        from docx import Document

        doc = Document(str(resume_path))
        return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
    if suffix in {".txt", ".md"}:
        return resume_path.read_text(encoding="utf-8")
    raise ValueError(f"不支持的简历类型: {resume_path.suffix}")


def ensure_pdf_resume(resume_path: Path) -> None:
    if resume_path.suffix.lower() != ".pdf":
        raise ValueError(
            f"当前仅允许处理 PDF 简历，收到文件类型: {resume_path.suffix or '无扩展名'}"
        )


def write_text_output(text: str, output_file: Path) -> None:
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(text, encoding="utf-8")


def load_resume_json(json_path: Path) -> dict[str, Any]:
    if not json_path.exists():
        raise FileNotFoundError(f"JSON 文件不存在: {json_path}")
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    return normalize_resume_data(payload)


def generate_docx(json_path: Path, output_docx: Path) -> None:
    payload = load_resume_json(json_path)
    if not payload.get("is_valid_resume", False):
        raise RuntimeError(
            f"简历校验未通过，拒绝生成。原因: {payload.get('rejection_reason', '未知')}"
        )
    resume_data = payload["resume_data"]
    output_docx.parent.mkdir(parents=True, exist_ok=True)
    from src.filler import fill_template

    fill_template(TEMPLATE_PATH, resume_data, output_docx)


def build_mml(
    to_email: str,
    subject: str,
    body: str,
    attachment_path: Path,
    attachment_name: str,
) -> str:
    from_email = os.environ.get("RESUME_BOT_SENDER", "lensman.lucas@gmail.com")
    from_name = "Lucas"
    return (
        f"From: {from_name} <{from_email}>\n"
        f"To: {to_email}\n"
        f"Subject: {subject}\n"
        "\n"
        "<#multipart type=mixed>\n"
        "<#part type=text/plain>\n"
        f"{body}\n"
        "<#/part>\n"
        f"<#part filename={attachment_path} name={attachment_name}><#/part>\n"
        "<#/multipart>\n"
    )


def send_email_with_himalaya(
    to_email: str, attachment_path: Path, attachment_name: str
) -> None:
    subject = "候选人标准简历（TEK 模板）"
    body = "您好，附件为自动转换后的 TEK 标准简历，请查收。"
    mml_content = build_mml(
        to_email=to_email,
        subject=subject,
        body=body,
        attachment_path=attachment_path,
        attachment_name=attachment_name,
    )
    mml_file = TMP_DIR / "resume_email.mml"
    mml_file.write_text(mml_content, encoding="utf-8")

    # himalaya v1.2.0: 读取 MML 并发送
    proc = subprocess.run(
        ["himalaya", "template", "send"],
        input=mml_content,
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"himalaya 发送失败: {proc.stderr.strip() or proc.stdout.strip()}"
        )


def update_tracker(
    source_resume: Path,
    json_path: Path,
    output_docx: Path,
    recipient: str | None,
) -> int:
    tracker = read_tracker()
    tracker["total_processed"] = int(tracker.get("total_processed", 0)) + 1
    history = tracker.setdefault("history", [])
    history.append(
        {
            "time": now_iso(),
            "source_resume": str(source_resume),
            "resume_json": str(json_path),
            "output_docx": str(output_docx),
            "recipient": recipient,
        }
    )
    tracker["history"] = history[-100:]
    write_tracker(tracker)
    return int(tracker["total_processed"])


def process_resume(
    resume_path: Path,
    json_path: Path,
    output_docx: Path,
    to_email: str | None,
    enable_email: bool,
    candidate_name: str | None,
    skip_email: bool,
) -> PipelineResult:
    ensure_runtime()
    payload = load_resume_json(json_path)
    if not payload.get("is_valid_resume", False):
        raise RuntimeError(
            f"简历校验未通过，拒绝生成。原因: {payload.get('rejection_reason', '未知')}"
        )
    final_candidate_name = (
        candidate_name or str(payload.get("candidate_name", "")).strip() or "候选人"
    )
    attachment_name = standard_docx_name(final_candidate_name)

    # 若输出文件名不符合规范，则自动改为“姓名-TEK-标准简历.docx”
    if output_docx.name != attachment_name:
        output_docx = output_docx.parent / attachment_name

    write_status(
        busy=True,
        stage="generate_docx",
        progress=55,
        message="正在生成标准简历 DOCX",
        extra={"output_docx": str(output_docx)},
    )
    generate_docx(json_path=json_path, output_docx=output_docx)

    sent = False
    if to_email and enable_email and not skip_email:
        write_status(
            busy=True,
            stage="send_email",
            progress=80,
            message="正在发送邮件附件",
            extra={"recipient": to_email},
        )
        send_email_with_himalaya(
            to_email=to_email,
            attachment_path=output_docx,
            attachment_name=attachment_name,
        )
        sent = True

    total = update_tracker(
        source_resume=resume_path,
        json_path=json_path,
        output_docx=output_docx,
        recipient=to_email if sent else None,
    )
    return PipelineResult(
        output_docx=output_docx,
        tracker_total=total,
        email_sent=sent,
        recipient=to_email if sent else None,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Hermes Resume Bot pipeline")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("bootstrap-venv", help="初始化或更新 skill 专用 .venv")
    sub.add_parser("bootstrap-uv", help="使用 uv 初始化或更新 skill 专用 .venv")
    init_cmd = sub.add_parser("init-llm", help="初始化 DeepSeek API 配置")
    init_cmd.add_argument("--deepseek-api-key", required=True, type=str)
    init_cmd.add_argument("--deepseek-model", type=str, default=DEFAULT_DEEPSEEK_MODEL)
    init_cmd.add_argument(
        "--deepseek-base-url", type=str, default=DEFAULT_DEEPSEEK_BASE_URL
    )

    extract_cmd = sub.add_parser("extract", help="提取简历文本到文件")
    extract_cmd.add_argument("--resume", required=True, type=Path)
    extract_cmd.add_argument("--out-text", required=True, type=Path)
    extract_cmd.add_argument(
        "--require-pdf",
        action="store_true",
        help="仅允许输入 PDF 简历（用于 Telegram 电子围栏场景）",
    )

    llm_parse_cmd = sub.add_parser("llm-parse", help="调用 DeepSeek 解析并校验简历")
    llm_parse_cmd.add_argument("--text-file", required=True, type=Path)
    llm_parse_cmd.add_argument("--out-json", required=True, type=Path)

    process_cmd = sub.add_parser("process", help="生成标准简历并可选发送邮件")
    process_cmd.add_argument("--resume", required=True, type=Path)
    process_cmd.add_argument("--json", required=True, type=Path)
    process_cmd.add_argument("--output-docx", type=Path, default=DEFAULT_OUTPUT)
    process_cmd.add_argument("--to-email", type=str)
    process_cmd.add_argument(
        "--enable-email",
        action="store_true",
        help="显式开启邮件发送（默认关闭，仅回传 Telegram 文件）",
    )
    process_cmd.add_argument("--candidate-name", type=str)
    process_cmd.add_argument("--skip-email", action="store_true")
    process_cmd.add_argument(
        "--require-pdf",
        action="store_true",
        help="仅允许输入 PDF 简历（用于 Telegram 电子围栏场景）",
    )
    process_cmd.add_argument(
        "--keep-temp",
        action="store_true",
        help="默认会删除临时输入文件，传入该参数则保留",
    )
    process_cmd.add_argument(
        "--delete-output",
        action="store_true",
        help="处理完成后立刻删除输出 DOCX",
    )

    cleanup_cmd = sub.add_parser("cleanup", help="清理临时文件")
    cleanup_cmd.add_argument("--paths", nargs="+", required=True, type=Path)

    status_cmd = sub.add_parser("status", help="查询当前任务状态")
    status_cmd.add_argument(
        "--text",
        action="store_true",
        help="返回适合直接回复用户的文本状态",
    )
    status_cmd.add_argument(
        "--force-reset",
        action="store_true",
        help="强制清除卡住的状态和锁文件",
    )

    reset_cmd = sub.add_parser("reset", help="强制重置 busy 状态")
    reset_cmd.add_argument(
        "--clear-temp",
        action="store_true",
        help="同时清理 /tmp/resume-bot 下中间文件",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()
    ensure_skill_venv(reexec=args.command not in {"bootstrap-venv", "bootstrap-uv"})
    ensure_runtime()
    install_signal_cleanup()

    try:
        if args.command in {"bootstrap-venv", "bootstrap-uv"}:
            print(
                json.dumps(
                    {
                        "ok": True,
                        "stage": "bootstrap-uv",
                        "package_manager": "uv",
                        "uv_bin": UV_BIN,
                        "venv_python": str(VENV_PYTHON),
                        "venv_dir": str(VENV_DIR),
                        "runtime_python": sys.executable,
                    },
                    ensure_ascii=False,
                )
            )
            return

        if args.command == "init-llm":
            write_bot_config(
                {
                    "deepseek_api_key": args.deepseek_api_key.strip(),
                    "deepseek_model": args.deepseek_model.strip()
                    or DEFAULT_DEEPSEEK_MODEL,
                    "deepseek_base_url": args.deepseek_base_url.strip()
                    or DEFAULT_DEEPSEEK_BASE_URL,
                    "updated_at": now_iso(),
                }
            )
            print(
                json.dumps(
                    {
                        "ok": True,
                        "stage": "init-llm",
                        "message": "DeepSeek 配置已保存",
                    },
                    ensure_ascii=False,
                )
            )
            return

        if args.command == "status":
            # --force-reset: 强制清除卡住的状态
            if args.force_reset:
                for p in [STATUS_PATH, SESSION_LOCK_PATH]:
                    if p.exists():
                        p.unlink()
                print(
                    json.dumps(
                        {"ok": True, "stage": "force-reset", "message": "状态已强制清除"},
                        ensure_ascii=False,
                    )
                )
                return

            status = read_status()
            llm_cfg = get_deepseek_config()

            # 自动超时检测：状态超过 5 分钟未更新且 busy=true，自动清除
            if status.get("busy"):
                try:
                    last_update = datetime.fromisoformat(status.get("updated_at", ""))
                    if (datetime.now() - last_update).total_seconds() > 300:
                        for p in [STATUS_PATH, SESSION_LOCK_PATH]:
                            if p.exists():
                                p.unlink()
                        status = {"busy": False, "stage": "idle", "progress": 0, "message": "之前任务超时已自动清除", "updated_at": now_iso()}
                except (ValueError, TypeError):
                    pass

            status["llm_configured"] = bool(llm_cfg.get("api_key"))
            status["llm_model"] = llm_cfg.get("model", DEFAULT_DEEPSEEK_MODEL)
            display_text = (
                f"进度 {status.get('progress', 0)}% "
                f"[{render_progress_bar(int(status.get('progress', 0)))}]\n"
                f"阶段：{status.get('stage', 'unknown')}\n"
                f"状态：{status.get('message', '')}"
            )
            if args.text:
                print(display_text)
                return
            print(
                json.dumps(
                    {
                        "ok": True,
                        "stage": "status",
                        "status": status,
                        "display_text": display_text,
                    },
                    ensure_ascii=False,
                )
            )
            return

        if args.command == "reset":
            for p in [STATUS_PATH, SESSION_LOCK_PATH]:
                if p.exists():
                    p.unlink()
            if args.clear_temp and TMP_DIR.exists():
                for child in TMP_DIR.iterdir():
                    if child.is_file():
                        safe_delete_file(child)
            write_status(
                busy=False,
                stage="idle",
                progress=0,
                message="已手动重置，等待新任务",
            )
            print(
                json.dumps(
                    {
                        "ok": True,
                        "stage": "reset",
                        "message": "状态已重置",
                        "clear_temp": bool(args.clear_temp),
                    },
                    ensure_ascii=False,
                )
            )
            return

        if args.command in {"extract", "llm-parse", "process"}:
            ensure_deepseek_ready()

        if args.command == "extract":
            write_status(
                busy=True,
                stage="extract_text",
                progress=25,
                message="正在提取简历文本",
                extra={"resume": str(args.resume)},
            )
            if not args.resume.exists():
                raise FileNotFoundError(f"简历文件不存在: {args.resume}")
            if args.require_pdf:
                ensure_pdf_resume(args.resume)
            text = extract_resume_text(args.resume)
            write_text_output(text, args.out_text)
            write_status(
                busy=True,
                stage="extract_done",
                progress=40,
                message="简历文本提取完成",
                extra={"out_text": str(args.out_text)},
            )
            print(
                json.dumps(
                    {
                        "ok": True,
                        "stage": "extract",
                        "resume": str(args.resume),
                        "out_text": str(args.out_text),
                        "chars": len(text),
                        "runtime_python": sys.executable,
                    },
                    ensure_ascii=False,
                )
            )
            return

        if args.command == "llm-parse":
            if not args.text_file.exists():
                raise FileNotFoundError(f"文本文件不存在: {args.text_file}")
            llm_cfg = ensure_deepseek_ready()
            write_status(
                busy=True,
                stage="llm_parse",
                progress=50,
                message="正在调用 DeepSeek 解析简历",
            )
            text = args.text_file.read_text(encoding="utf-8")
            parsed = call_deepseek_resume_parser(text, llm_cfg=llm_cfg)
            payload = normalize_resume_data(parsed)
            args.out_json.parent.mkdir(parents=True, exist_ok=True)
            args.out_json.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            is_valid = bool(payload.get("is_valid_resume", False))
            write_status(
                busy=True,
                stage="llm_parse_done",
                progress=70,
                message="简历结构化完成" if is_valid else "简历无效，已拒绝生成",
                extra={
                    "is_valid_resume": is_valid,
                    "rejection_reason": payload.get("rejection_reason", ""),
                },
            )
            # llm-parse 是独立步骤，结束后回到可接收状态
            write_status(
                busy=False,
                stage="llm_parse_done",
                progress=70,
                message="简历结构化完成，等待继续处理",
                extra={
                    "is_valid_resume": is_valid,
                    "rejection_reason": payload.get("rejection_reason", ""),
                },
            )
            print(
                json.dumps(
                    {
                        "ok": True,
                        "stage": "llm-parse",
                        "out_json": str(args.out_json),
                        "is_valid_resume": is_valid,
                        "candidate_name": payload.get("candidate_name", "候选人"),
                        "rejection_reason": payload.get("rejection_reason", ""),
                    },
                    ensure_ascii=False,
                )
            )
            return

        if args.command == "process":
            global CURRENT_PROCESS_HAS_LOCK
            if not try_acquire_processing_lock(
                job_hint=f"{(args.candidate_name or '候选人')}:{args.resume.name}"
            ):
                busy_status = read_status()
                lock_info = read_processing_lock()
                if not busy_status.get("busy"):
                    busy_status["busy"] = True
                    busy_status["stage"] = "processing"
                    busy_status["message"] = "上一份简历仍在处理中"
                if lock_info:
                    busy_status["lock"] = lock_info
                print(
                    json.dumps(
                        {
                            "ok": False,
                            "stage": "process",
                            "busy": True,
                            "error": "当前有任务正在处理中，请稍后再试",
                            "status": busy_status,
                        },
                        ensure_ascii=False,
                    )
                )
                raise SystemExit(2)
            CURRENT_PROCESS_HAS_LOCK = True

            write_status(
                busy=True,
                stage="accepted",
                progress=10,
                message="已接收任务，准备处理简历",
                extra={
                    "candidate_name": args.candidate_name,
                    "resume": str(args.resume),
                },
            )
            if not args.resume.exists():
                raise FileNotFoundError(f"简历文件不存在: {args.resume}")
            if args.require_pdf:
                ensure_pdf_resume(args.resume)
            if not args.json.exists():
                raise FileNotFoundError(f"JSON 文件不存在: {args.json}")

            write_status(
                busy=True,
                stage="validate_input",
                progress=30,
                message="正在校验输入文件",
            )
            time.sleep(0.05)

            result = process_resume(
                resume_path=args.resume,
                json_path=args.json,
                output_docx=args.output_docx,
                to_email=args.to_email,
                enable_email=args.enable_email,
                candidate_name=args.candidate_name,
                skip_email=args.skip_email,
            )
            if not args.keep_temp:
                # 清理临时输入，避免目录堆积
                write_status(
                    busy=True,
                    stage="cleanup_input",
                    progress=92,
                    message="正在清理临时输入文件",
                )
                safe_delete_file(args.resume)
                safe_delete_file(args.json)
                safe_delete_file(TMP_DIR / "resume_email.mml")
            if args.delete_output:
                write_status(
                    busy=True,
                    stage="cleanup_output",
                    progress=96,
                    message="正在清理输出文件",
                )
                safe_delete_file(result.output_docx)
                release_processing_lock()
                CURRENT_PROCESS_HAS_LOCK = False
                write_status(
                    busy=False,
                    stage="done",
                    progress=100,
                    message="任务处理完成（输出已删除）",
                    extra={
                        "output_docx": str(result.output_docx),
                        "email_sent": result.email_sent,
                        "recipient": result.recipient,
                    },
                )
            else:
                # 进入“等待回传”阶段：保持锁，避免用户 /new 打断回传步骤
                write_status(
                    busy=True,
                    stage="awaiting_delivery",
                    progress=98,
                    message="正在回传文件，请勿发送 /new 或 /reset",
                    extra={
                        "output_docx": str(result.output_docx),
                        "email_sent": result.email_sent,
                        "recipient": result.recipient,
                    },
                )
            print(
                json.dumps(
                    {
                        "ok": True,
                        "stage": "process",
                        "output_docx": str(result.output_docx),
                        "email_sent": result.email_sent,
                        "recipient": result.recipient,
                        "tracker_total": result.tracker_total,
                        "runtime_python": sys.executable,
                    },
                    ensure_ascii=False,
                )
            )
            return

        if args.command == "cleanup":
            deleted: list[str] = []
            for path in args.paths:
                safe_delete_file(path)
                if not path.exists():
                    deleted.append(str(path))
            # cleanup 作为交付完成的收尾动作：释放锁并回到 idle
            release_processing_lock()
            CURRENT_PROCESS_HAS_LOCK = False
            write_status(
                busy=False,
                stage="done",
                progress=100,
                message="回传完成并清理结束",
            )
            print(
                json.dumps(
                    {
                        "ok": True,
                        "stage": "cleanup",
                        "deleted": deleted,
                        "runtime_python": sys.executable,
                    },
                    ensure_ascii=False,
                )
            )
            return

        raise RuntimeError(f"未知命令: {args.command}")
    except Exception as exc:  # noqa: BLE001 - CLI needs single error exit
        if args.command == "process":
            release_processing_lock()
            CURRENT_PROCESS_HAS_LOCK = False
            write_status(
                busy=False,
                stage="failed",
                progress=100,
                message=f"任务失败: {exc}",
            )
        log_error(args.command, str(exc))
        print(
            json.dumps(
                {"ok": False, "stage": args.command, "error": str(exc)},
                ensure_ascii=False,
            )
        )
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
