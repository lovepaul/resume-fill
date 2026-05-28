#!/usr/bin/env bash
set -euo pipefail

# 一键服务管理脚本（systemd + nginx）
# 用法：
#   sudo bash deploy/linux/manage.sh start
#   sudo bash deploy/linux/manage.sh pause
#   sudo bash deploy/linux/manage.sh restart
#   sudo bash deploy/linux/manage.sh status
#   sudo bash deploy/linux/manage.sh logs

APP_NAME="${APP_NAME:-resume-web}"
SUDO_CMD=""
if [[ "${EUID}" -ne 0 ]]; then
  SUDO_CMD="sudo"
fi

usage() {
  cat <<EOF
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Resume Web 服务管理（APP_NAME=${APP_NAME}）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
用法:
  manage.sh <command>

可用命令:
  start       启动后端与 nginx
  stop        停止后端与 nginx
  pause       暂停服务（等同 stop）
  restart     重启后端与 nginx
  reload      平滑重载后端与 nginx
  status      查看服务状态
  logs-all    聚合查看后端 + Nginx + 前端访问日志
  logs        实时查看后端日志（journalctl）
  logs-nginx  实时查看 nginx 错误日志
  logs-runtime-cleanup 查看运行目录清理日志
  backup-config 备份当前 env/systemd/nginx/cron 配置
  rollback-config [backup-id] 回滚到最近或指定备份
  cleanup-logs 一次性清理历史日志（默认总量<=20M）
  setup-log-maintenance 配置每10分钟自动检测+清理日志
  help        显示本帮助

常用示例:
  sudo bash deploy/linux/manage.sh start
  sudo bash deploy/linux/manage.sh status
  sudo bash deploy/linux/manage.sh logs

排障建议:
  1) 服务起不来：先执行 status，再看 logs
  2) 页面 502/404：执行 logs-nginx + status
  3) 改了配置后：执行 reload 或 restart
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
EOF
}

cmd="${1:-}"
case "${cmd}" in
  start)
    ${SUDO_CMD} systemctl start "${APP_NAME}" nginx
    ;;
  stop|pause)
    ${SUDO_CMD} systemctl stop "${APP_NAME}" nginx
    ;;
  restart)
    ${SUDO_CMD} systemctl restart "${APP_NAME}" nginx
    ;;
  reload)
    ${SUDO_CMD} systemctl reload-or-restart "${APP_NAME}"
    ${SUDO_CMD} nginx -t
    ${SUDO_CMD} systemctl reload nginx
    ;;
  status)
    ${SUDO_CMD} systemctl status "${APP_NAME}" nginx --no-pager
    ;;
  logs)
    ${SUDO_CMD} journalctl -u "${APP_NAME}" -f
    ;;
  logs-nginx)
    ${SUDO_CMD} tail -f /var/log/nginx/error.log
    ;;
  logs-runtime-cleanup)
    ${SUDO_CMD} tail -f "/var/log/${APP_NAME}-runtime-cleanup.log"
    ;;
  logs-all)
    ${SUDO_CMD} bash "$(dirname "$0")/logs-all.sh"
    ;;
  backup-config)
    ${SUDO_CMD} bash "$(dirname "$0")/backup-config.sh"
    ;;
  rollback-config)
    ${SUDO_CMD} bash "$(dirname "$0")/rollback-config.sh" "${2:-}"
    ;;
  cleanup-logs)
    ${SUDO_CMD} bash "$(dirname "$0")/cleanup-logs.sh"
    ;;
  setup-log-maintenance)
    ${SUDO_CMD} bash "$(dirname "$0")/setup-log-maintenance.sh"
    ;;
  help|-h|--help|"")
    usage
    exit 0
    ;;
  *)
    usage
    exit 1
    ;;
esac
