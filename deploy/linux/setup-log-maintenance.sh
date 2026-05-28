#!/usr/bin/env bash
set -euo pipefail

# 配置日志自动维护（cron）：
# 每 10 分钟执行 cleanup-logs.sh（检测+清理）
# 默认策略：
# - 总日志（nginx + journal + maintenance）<= 20M
# - 同时保留 14 天的清理窗口

APP_NAME="${APP_NAME:-resume-web}"
CRON_FILE="/etc/cron.d/${APP_NAME}-log-cleanup"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLEANUP_SCRIPT="${SCRIPT_DIR}/cleanup-logs.sh"
CRON_LOG_FILE="/var/log/${APP_NAME}-log-cleanup.log"

if [[ "${EUID}" -ne 0 ]]; then
  echo "请使用 root 或 sudo 运行。" >&2
  exit 1
fi

if [[ ! -f "${CLEANUP_SCRIPT}" ]]; then
  echo "错误: 未找到 ${CLEANUP_SCRIPT}" >&2
  exit 1
fi

chmod +x "${CLEANUP_SCRIPT}"

cat > "${CRON_FILE}" <<EOF
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/sbin:/bin:/usr/sbin:/usr/bin

*/10 * * * * root APP_NAME=${APP_NAME} JOURNAL_KEEP_DAYS=14 JOURNAL_MAX_SIZE=20M NGINX_MAX_SIZE=10M NGINX_ROTATE_COUNT=14 NGINX_ARCHIVE_KEEP_DAYS=14 TOTAL_LOG_MAX_SIZE=20M MAINTENANCE_LOG_FILE=${CRON_LOG_FILE} ${CLEANUP_SCRIPT} >> ${CRON_LOG_FILE} 2>&1
EOF

chmod 644 "${CRON_FILE}"

echo "已配置自动日志维护：${CRON_FILE}"
echo "执行时间：每 10 分钟"
echo "默认策略：总日志(nginx+journal+maintenance) <=20M；保留窗口14天"
echo "清理日志：${CRON_LOG_FILE}"
