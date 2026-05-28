#!/usr/bin/env bash
set -euo pipefail

# Mac 本地开发一键关停脚本
# 用法：
#   bash deploy/macos/stop.sh

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"

log() {
  printf "\n[%s] %s\n" "$(date +'%F %T')" "$*"
}

kill_by_port() {
  local port="$1"
  local pids
  pids="$(lsof -ti tcp:"${port}" 2>/dev/null || true)"
  if [[ -z "${pids}" ]]; then
    return
  fi

  log "端口 ${port} 占用进程: ${pids}"
  # shellcheck disable=SC2086
  kill ${pids} >/dev/null 2>&1 || true
  sleep 1

  local remain
  remain="$(lsof -ti tcp:"${port}" 2>/dev/null || true)"
  if [[ -n "${remain}" ]]; then
    log "端口 ${port} 仍被占用，执行强制终止"
    # shellcheck disable=SC2086
    kill -9 ${remain} >/dev/null 2>&1 || true
  fi
}

main() {
  cd "${REPO_ROOT}"
  if [[ -f "${REPO_ROOT}/deploy/macos/dev.sh" ]]; then
    bash "${REPO_ROOT}/deploy/macos/dev.sh" stop || true
  fi

  # 兜底：处理 --reload / 子进程未退出导致的端口残留
  kill_by_port "${FRONTEND_PORT}"
  kill_by_port "${BACKEND_PORT}"

  log "开发环境已关停"
}

main "$@"
