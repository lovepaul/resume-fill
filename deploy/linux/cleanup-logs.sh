#!/usr/bin/env bash
set -euo pipefail

# 一次性清理日志：
# 1) 常规轮转/过期清理（nginx + journal）
# 2) 强制总量治理（nginx + journal + maintenance log 总计 <= 20M，默认）

APP_NAME="${APP_NAME:-resume-web}"
NGINX_LOG_DIR="${NGINX_LOG_DIR:-/var/log/nginx}"
NGINX_ARCHIVE_KEEP_DAYS="${NGINX_ARCHIVE_KEEP_DAYS:-14}"
NGINX_MAX_SIZE="${NGINX_MAX_SIZE:-10M}"
NGINX_ROTATE_COUNT="${NGINX_ROTATE_COUNT:-14}"
JOURNAL_KEEP_DAYS="${JOURNAL_KEEP_DAYS:-14}"
JOURNAL_MAX_SIZE="${JOURNAL_MAX_SIZE:-20M}"
TOTAL_LOG_MAX_SIZE="${TOTAL_LOG_MAX_SIZE:-20M}"
MAINTENANCE_LOG_FILE="${MAINTENANCE_LOG_FILE:-/var/log/${APP_NAME}-log-cleanup.log}"
LOGROTATE_POLICY_FILE="/etc/logrotate.d/${APP_NAME}-nginx"

if [[ "${EUID}" -ne 0 ]]; then
  echo "请使用 root 或 sudo 运行。" >&2
  exit 1
fi

size_to_bytes() {
  local size="${1^^}"
  local num unit
  if [[ "${size}" =~ ^([0-9]+)([KMG]?)B?$ ]]; then
    num="${BASH_REMATCH[1]}"
    unit="${BASH_REMATCH[2]}"
  else
    echo "0"
    return
  fi

  case "${unit}" in
    K) echo $((num * 1024)) ;;
    M) echo $((num * 1024 * 1024)) ;;
    G) echo $((num * 1024 * 1024 * 1024)) ;;
    *) echo "${num}" ;;
  esac
}

dir_size_bytes() {
  local dir="$1"
  if [[ -d "${dir}" ]]; then
    du -sb "${dir}" | awk "{print \$1}"
  else
    echo "0"
  fi
}

file_size_bytes() {
  local file="$1"
  if [[ -f "${file}" ]]; then
    stat -c%s "${file}"
  else
    echo "0"
  fi
}

journal_size_bytes() {
  local total=0
  total=$((total + $(dir_size_bytes "/var/log/journal")))
  total=$((total + $(dir_size_bytes "/run/log/journal")))
  echo "${total}"
}

current_total_log_bytes() {
  local nginx_size journal_size maintenance_size
  nginx_size="$(dir_size_bytes "${NGINX_LOG_DIR}")"
  journal_size="$(journal_size_bytes)"
  maintenance_size="$(file_size_bytes "${MAINTENANCE_LOG_FILE}")"
  echo $((nginx_size + journal_size + maintenance_size))
}

enforce_total_cap() {
  local total_cap total_now nginx_size maintenance_size journal_target_bytes
  total_cap="$(size_to_bytes "${TOTAL_LOG_MAX_SIZE}")"
  total_now="$(current_total_log_bytes)"
  if (( total_cap <= 0 )); then
    return
  fi

  if (( total_now <= total_cap )); then
    echo "总日志大小 ${total_now} bytes，未超过上限 ${total_cap} bytes"
    return
  fi

  echo "检测到总日志超限：${total_now} bytes > ${total_cap} bytes，开始回收"

  nginx_size="$(dir_size_bytes "${NGINX_LOG_DIR}")"
  maintenance_size="$(file_size_bytes "${MAINTENANCE_LOG_FILE}")"
  journal_target_bytes=$((total_cap - nginx_size - maintenance_size))
  if (( journal_target_bytes < 1048576 )); then
    journal_target_bytes=1048576
  fi
  journalctl --vacuum-size="${journal_target_bytes}B" --vacuum-time="${JOURNAL_KEEP_DAYS}d" >/dev/null 2>&1 || true

  total_now="$(current_total_log_bytes)"
  if (( total_now <= total_cap )); then
    echo "通过压缩 journal 已回收，总大小 ${total_now} bytes"
    return
  fi

  if [[ -d "${NGINX_LOG_DIR}" ]]; then
    local file
    while IFS= read -r file; do
      rm -f "${file}"
      total_now="$(current_total_log_bytes)"
      if (( total_now <= total_cap )); then
        echo "通过删除 Nginx 归档日志已回收，总大小 ${total_now} bytes"
        return
      fi
    done < <(ls -1tr "${NGINX_LOG_DIR}"/*.gz "${NGINX_LOG_DIR}"/*.log.* 2>/dev/null || true)
  fi

  : > "${NGINX_LOG_DIR}/access.log" 2>/dev/null || true
  : > "${NGINX_LOG_DIR}/error.log" 2>/dev/null || true
  total_now="$(current_total_log_bytes)"
  echo "已执行兜底截断，当前总日志大小 ${total_now} bytes"
}

echo "[1/5] 生成 Nginx 日志轮转策略（maxsize=${NGINX_MAX_SIZE}, rotate=${NGINX_ROTATE_COUNT}）"
cat > "${LOGROTATE_POLICY_FILE}" <<EOF
${NGINX_LOG_DIR}/*.log {
    daily
    rotate ${NGINX_ROTATE_COUNT}
    maxsize ${NGINX_MAX_SIZE}
    missingok
    notifempty
    compress
    delaycompress
    sharedscripts
    postrotate
        [ -s /run/nginx.pid ] && kill -USR1 \`cat /run/nginx.pid\`
    endscript
}
EOF

echo "[2/5] 清理 Nginx 归档日志（保留 ${NGINX_ARCHIVE_KEEP_DAYS} 天）"
if [[ -d "${NGINX_LOG_DIR}" ]]; then
  find "${NGINX_LOG_DIR}" -type f \( -name "*.log.*" -o -name "*.gz" \) -mtime +"${NGINX_ARCHIVE_KEEP_DAYS}" -delete
else
  echo "提示: ${NGINX_LOG_DIR} 不存在，跳过 Nginx 归档清理"
fi

echo "[3/5] 执行 Nginx 日志轮转"
if [[ -f "${LOGROTATE_POLICY_FILE}" ]]; then
  logrotate -f "${LOGROTATE_POLICY_FILE}"
else
  echo "提示: 未找到 ${LOGROTATE_POLICY_FILE}，跳过强制轮转"
fi

echo "[4/5] 清理 systemd journal（保留 ${JOURNAL_KEEP_DAYS} 天，最多 ${JOURNAL_MAX_SIZE}）"
journalctl --vacuum-time="${JOURNAL_KEEP_DAYS}d" --vacuum-size="${JOURNAL_MAX_SIZE}"

echo "[5/5] 执行总量控制（nginx+journal+maintenance <= ${TOTAL_LOG_MAX_SIZE}）"
enforce_total_cap

echo "日志清理完成。"
