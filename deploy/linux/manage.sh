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
  logs        实时查看后端日志（journalctl）
  logs-nginx  实时查看 nginx 错误日志
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
  help|-h|--help|"")
    usage
    exit 0
    ;;
  *)
    usage
    exit 1
    ;;
esac
