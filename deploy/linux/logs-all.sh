#!/usr/bin/env bash
set -euo pipefail

# 聚合查看日志：
# - backend: systemd journal (resume-web)
# - nginx-error: /var/log/nginx/error.log
# - frontend/api: /var/log/nginx/access.log（按路径分流）

APP_NAME="${APP_NAME:-resume-web}"
ACCESS_LOG="${ACCESS_LOG:-/var/log/nginx/access.log}"
ERROR_LOG="${ERROR_LOG:-/var/log/nginx/error.log}"
TAIL_LINES="${TAIL_LINES:-30}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "请使用 root 或 sudo 运行。" >&2
  exit 1
fi

if [[ ! -f "${ACCESS_LOG}" ]]; then
  echo "错误: 找不到访问日志 ${ACCESS_LOG}" >&2
  exit 1
fi

if [[ ! -f "${ERROR_LOG}" ]]; then
  echo "错误: 找不到错误日志 ${ERROR_LOG}" >&2
  exit 1
fi

echo "开始聚合日志（Ctrl+C 退出）"
echo "  - backend: journalctl -u ${APP_NAME}"
echo "  - nginx-error: ${ERROR_LOG}"
echo "  - frontend/api: ${ACCESS_LOG}"
echo

pids=()

cleanup() {
  local pid
  for pid in "${pids[@]}"; do
    kill "${pid}" >/dev/null 2>&1 || true
  done
}

trap cleanup EXIT INT TERM

stdbuf -oL -eL journalctl -u "${APP_NAME}" -n "${TAIL_LINES}" -f \
  | stdbuf -oL -eL awk '{print "[backend] " $0; fflush();}' &
pids+=("$!")

stdbuf -oL -eL tail -n "${TAIL_LINES}" -F "${ERROR_LOG}" \
  | stdbuf -oL -eL awk '{print "[nginx-error] " $0; fflush();}' &
pids+=("$!")

stdbuf -oL -eL tail -n "${TAIL_LINES}" -F "${ACCESS_LOG}" \
  | stdbuf -oL -eL awk '
      {
        path = $7
        if (path ~ /^\/api\//) {
          print "[api-access] " $0
        } else {
          print "[frontend-access] " $0
        }
        fflush()
      }
    ' &
pids+=("$!")

wait
