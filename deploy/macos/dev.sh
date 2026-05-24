#!/usr/bin/env bash
set -euo pipefail

# 本地 Mac 一键开发脚本（前后端同时启动）
# 用法：
#   bash deploy/macos/dev.sh start
#   bash deploy/macos/dev.sh stop
#   bash deploy/macos/dev.sh restart
#   bash deploy/macos/dev.sh status
#   bash deploy/macos/dev.sh logs

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VENV_DIR="${VENV_DIR:-${REPO_ROOT}/.venv-web}"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
API_BASE_URL="${API_BASE_URL:-http://127.0.0.1:${BACKEND_PORT}}"

RUN_DIR="${REPO_ROOT}/.run/macos-dev"
LOG_DIR="${RUN_DIR}/logs"
BACKEND_PID_FILE="${RUN_DIR}/backend.pid"
FRONTEND_PID_FILE="${RUN_DIR}/frontend.pid"
BACKEND_LOG_FILE="${LOG_DIR}/backend.log"
FRONTEND_LOG_FILE="${LOG_DIR}/frontend.log"

log() {
  printf "\n[%s] %s\n" "$(date +'%F %T')" "$*"
}

ensure_dirs() {
  mkdir -p "${LOG_DIR}"
}

pid_running() {
  local pid_file="$1"
  if [[ ! -f "${pid_file}" ]]; then
    return 1
  fi
  local pid
  pid="$(<"${pid_file}")"
  [[ -n "${pid}" ]] && kill -0 "${pid}" >/dev/null 2>&1
}

ensure_backend_deps() {
  log "准备后端 Python 环境"
  if [[ ! -d "${VENV_DIR}" ]]; then
    python3 -m venv "${VENV_DIR}"
  fi
  "${VENV_DIR}/bin/pip" install --upgrade pip >/dev/null
  "${VENV_DIR}/bin/pip" install -r "${REPO_ROOT}/web/backend/requirements.txt" >/dev/null
}

ensure_frontend_deps() {
  log "准备前端 Node 依赖"
  if [[ -d "${REPO_ROOT}/web/frontend/node_modules" ]]; then
    return
  fi
  if [[ -f "${REPO_ROOT}/web/frontend/package-lock.json" ]]; then
    (cd "${REPO_ROOT}/web/frontend" && npm ci >/dev/null)
  else
    (cd "${REPO_ROOT}/web/frontend" && npm install >/dev/null)
  fi
}

start_backend() {
  if pid_running "${BACKEND_PID_FILE}"; then
    log "后端已在运行（PID $(<"${BACKEND_PID_FILE}"))"
    return
  fi
  log "启动后端 FastAPI（端口 ${BACKEND_PORT}）"
  nohup "${VENV_DIR}/bin/python" -m uvicorn web.backend.app:app \
    --host 0.0.0.0 \
    --port "${BACKEND_PORT}" \
    --reload >"${BACKEND_LOG_FILE}" 2>&1 &
  echo $! >"${BACKEND_PID_FILE}"
}

start_frontend() {
  if pid_running "${FRONTEND_PID_FILE}"; then
    log "前端已在运行（PID $(<"${FRONTEND_PID_FILE}"))"
    return
  fi
  log "启动前端 Vite（端口 ${FRONTEND_PORT}）"
  nohup bash -lc "cd \"${REPO_ROOT}/web/frontend\" && VITE_API_BASE_URL=\"${API_BASE_URL}\" npm run dev -- --host 0.0.0.0 --port \"${FRONTEND_PORT}\"" \
    >"${FRONTEND_LOG_FILE}" 2>&1 &
  echo $! >"${FRONTEND_PID_FILE}"
}

stop_service() {
  local name="$1"
  local pid_file="$2"
  if ! pid_running "${pid_file}"; then
    rm -f "${pid_file}"
    log "${name} 未运行"
    return
  fi
  local pid
  pid="$(<"${pid_file}")"
  log "停止 ${name}（PID ${pid}）"
  kill "${pid}" >/dev/null 2>&1 || true
  rm -f "${pid_file}"
}

status_service() {
  local name="$1"
  local pid_file="$2"
  if pid_running "${pid_file}"; then
    echo "- ${name}: running (PID $(<"${pid_file}"))"
  else
    echo "- ${name}: stopped"
  fi
}

start_all() {
  ensure_dirs
  ensure_backend_deps
  ensure_frontend_deps
  start_backend
  start_frontend
  log "启动完成"
  echo "前端地址: http://127.0.0.1:${FRONTEND_PORT}"
  echo "后端地址: http://127.0.0.1:${BACKEND_PORT}"
  echo "日志目录: ${LOG_DIR}"
}

stop_all() {
  stop_service "前端" "${FRONTEND_PID_FILE}"
  stop_service "后端" "${BACKEND_PID_FILE}"
}

status_all() {
  echo "当前状态:"
  status_service "前端" "${FRONTEND_PID_FILE}"
  status_service "后端" "${BACKEND_PID_FILE}"
  echo "- 日志目录: ${LOG_DIR}"
}

show_logs() {
  ensure_dirs
  touch "${BACKEND_LOG_FILE}" "${FRONTEND_LOG_FILE}"
  log "查看日志（Ctrl+C 退出）"
  tail -f "${BACKEND_LOG_FILE}" "${FRONTEND_LOG_FILE}"
}

usage() {
  cat <<EOF
本地 Mac 开发管理

用法:
  bash deploy/macos/dev.sh <command>

命令:
  start    一键启动前后端
  stop     停止前后端
  restart  重启前后端
  status   查看运行状态
  logs     查看实时日志
EOF
}

cmd="${1:-start}"
case "${cmd}" in
  start)
    start_all
    ;;
  stop)
    stop_all
    ;;
  restart)
    stop_all
    start_all
    ;;
  status)
    status_all
    ;;
  logs)
    show_logs
    ;;
  help|-h|--help)
    usage
    ;;
  *)
    usage
    exit 1
    ;;
esac
