#!/usr/bin/env bash
set -euo pipefail

# 全自动 Linux 部署脚本（systemd + nginx）
# 用法：
#   sudo bash deploy/linux/bootstrap.sh
# 可选环境变量：
#   APP_NAME=resume-web
#   APP_USER=www-data
#   APP_GROUP=www-data
#   APP_PORT=8000
#   APP_DOMAIN=_
#   INSTALL_PACKAGES=1
#   PYTHON_BIN=python3

APP_NAME="${APP_NAME:-resume-web}"
APP_USER="${APP_USER:-www-data}"
APP_GROUP="${APP_GROUP:-www-data}"
APP_PORT="${APP_PORT:-8000}"
APP_DOMAIN="${APP_DOMAIN:-_}"
INSTALL_PACKAGES="${INSTALL_PACKAGES:-1}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
APP_TMP_DIR="${APP_TMP_DIR:-/tmp/${APP_NAME}}"
TMP_RETENTION_MINUTES="${TMP_RETENTION_MINUTES:-60}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
APP_DIR="${APP_DIR:-${REPO_ROOT}}"
VENV_DIR="${VENV_DIR:-${APP_DIR}/.venv-web}"
ENV_FILE="${ENV_FILE:-/etc/${APP_NAME}.env}"
SERVICE_FILE="/etc/systemd/system/${APP_NAME}.service"
CRON_FILE="/etc/cron.d/${APP_NAME}-tmp-cleanup"

SUDO_CMD=""
if [[ "${EUID}" -ne 0 ]]; then
  SUDO_CMD="sudo"
fi

log() {
  printf "\n[%s] %s\n" "$(date +'%F %T')" "$*"
}

install_packages() {
  if [[ "${INSTALL_PACKAGES}" != "1" ]]; then
    log "跳过系统依赖安装（INSTALL_PACKAGES=${INSTALL_PACKAGES}）"
    return
  fi

  local required_cmds=("git" "nginx" "${PYTHON_BIN}" "node" "npm")
  local missing_cmds=()
  local cmd
  for cmd in "${required_cmds[@]}"; do
    if ! command -v "${cmd}" >/dev/null 2>&1; then
      missing_cmds+=("${cmd}")
    fi
  done

  if [[ "${#missing_cmds[@]}" -eq 0 ]]; then
    log "检测到系统依赖已安装，跳过安装步骤"
    return
  fi

  if command -v apt-get >/dev/null 2>&1; then
    log "使用 apt-get 安装系统依赖"
    ${SUDO_CMD} apt-get update
    ${SUDO_CMD} apt-get install -y \
      git \
      nginx \
      curl \
      ca-certificates \
      "${PYTHON_BIN}" \
      python3-venv \
      python3-pip \
      nodejs \
      npm
  elif command -v dnf >/dev/null 2>&1; then
    log "使用 dnf 安装系统依赖"
    ${SUDO_CMD} dnf install -y \
      git \
      nginx \
      curl \
      ca-certificates \
      "${PYTHON_BIN}" \
      python3-pip \
      nodejs \
      npm
  elif command -v yum >/dev/null 2>&1; then
    log "使用 yum 安装系统依赖"
    ${SUDO_CMD} yum install -y \
      git \
      nginx \
      curl \
      ca-certificates \
      "${PYTHON_BIN}" \
      python3-pip \
      nodejs \
      npm
  elif command -v apk >/dev/null 2>&1; then
    log "使用 apk 安装系统依赖"
    ${SUDO_CMD} apk add --no-cache \
      git \
      nginx \
      curl \
      ca-certificates \
      "${PYTHON_BIN}" \
      py3-pip \
      nodejs \
      npm
  elif command -v pacman >/dev/null 2>&1; then
    log "使用 pacman 安装系统依赖"
    ${SUDO_CMD} pacman -Sy --noconfirm \
      git \
      nginx \
      curl \
      ca-certificates \
      python \
      python-pip \
      nodejs \
      npm
  elif command -v zypper >/dev/null 2>&1; then
    log "使用 zypper 安装系统依赖"
    ${SUDO_CMD} zypper --non-interactive install \
      git \
      nginx \
      curl \
      ca-certificates \
      python3 \
      python3-pip \
      nodejs \
      npm
  elif command -v brew >/dev/null 2>&1; then
    log "使用 brew 安装系统依赖"
    brew install git nginx "${PYTHON_BIN}" node npm || true
  else
    log "未识别包管理器，尝试继续执行（缺失命令: ${missing_cmds[*]}）"
    log "若后续失败，请先手动安装: git/nginx/python3/nodejs/npm"
  fi
}

prepare_runtime() {
  log "准备 Python 虚拟环境与依赖"
  "${PYTHON_BIN}" -m venv "${VENV_DIR}"
  # shellcheck disable=SC1090
  source "${VENV_DIR}/bin/activate"
  pip install --upgrade pip
  pip install -r "${APP_DIR}/web/backend/requirements.txt"
}

prepare_tmp_dir() {
  log "准备 Linux 临时目录：${APP_TMP_DIR}"
  ${SUDO_CMD} mkdir -p "${APP_TMP_DIR}/uploads" "${APP_TMP_DIR}/outputs"
  ${SUDO_CMD} chown -R "${APP_USER}:${APP_GROUP}" "${APP_TMP_DIR}"
}

build_frontend() {
  log "构建前端产物"
  cd "${APP_DIR}/web/frontend"
  if [[ -f package-lock.json ]]; then
    npm ci
  else
    npm install
  fi
  npm run build
}

write_env_file() {
  if [[ -f "${ENV_FILE}" ]]; then
    log "环境文件已存在，跳过覆盖：${ENV_FILE}"
    return
  fi

  log "生成环境变量文件：${ENV_FILE}"
  ${SUDO_CMD} tee "${ENV_FILE}" >/dev/null <<'EOF'
# 请修改为真实 Key
DEEPSEEK_API_KEY=replace_me
# DEEPSEEK_BASE_URL=https://api.deepseek.com/v1/chat/completions
# DEEPSEEK_MODEL=deepseek-chat
# WEB_TMP_DIR=/tmp/resume-web
# WEB_FILE_RETENTION_SECONDS=3600
# WEB_CLEANUP_SCAN_INTERVAL_SECONDS=60
EOF
  ${SUDO_CMD} chmod 600 "${ENV_FILE}"
}

write_systemd_service() {
  log "写入 systemd 服务：${SERVICE_FILE}"
  ${SUDO_CMD} tee "${SERVICE_FILE}" >/dev/null <<EOF
[Unit]
Description=Resume Web FastAPI Service
After=network.target

[Service]
Type=simple
User=${APP_USER}
Group=${APP_GROUP}
WorkingDirectory=${APP_DIR}
EnvironmentFile=${ENV_FILE}
ExecStart=${VENV_DIR}/bin/uvicorn web.backend.app:app --host 127.0.0.1 --port ${APP_PORT}
Restart=always
RestartSec=3
TimeoutStopSec=15

[Install]
WantedBy=multi-user.target
EOF
}

write_nginx_config() {
  local nginx_conf
  local nginx_enable_link

  if [[ -d /etc/nginx/sites-available ]]; then
    nginx_conf="/etc/nginx/sites-available/${APP_NAME}.conf"
    nginx_enable_link="/etc/nginx/sites-enabled/${APP_NAME}.conf"
  else
    nginx_conf="/etc/nginx/conf.d/${APP_NAME}.conf"
    nginx_enable_link=""
  fi

  log "写入 nginx 配置：${nginx_conf}"
  ${SUDO_CMD} tee "${nginx_conf}" >/dev/null <<EOF
limit_req_zone \$binary_remote_addr zone=api_global:10m rate=20r/s;
limit_req_zone \$binary_remote_addr zone=api_convert:10m rate=6r/m;
limit_req_zone \$binary_remote_addr zone=api_download:10m rate=30r/m;
limit_conn_zone \$binary_remote_addr zone=perip_conn:10m;

server {
    listen 80;
    server_name ${APP_DOMAIN};
    client_max_body_size 20m;

    root ${APP_DIR}/web/frontend/dist;
    index index.html;

    location = /api/convert {
        limit_conn perip_conn 20;
        limit_req zone=api_convert burst=3 nodelay;
        proxy_pass http://127.0.0.1:${APP_PORT};
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    location ~ ^/api/jobs/.*/download$ {
        limit_conn perip_conn 20;
        limit_req zone=api_download burst=10 nodelay;
        proxy_pass http://127.0.0.1:${APP_PORT};
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    location /api/ {
        limit_conn perip_conn 20;
        limit_req zone=api_global burst=60 nodelay;
        proxy_pass http://127.0.0.1:${APP_PORT};
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    location / {
        try_files \$uri /index.html;
    }
}
EOF

  if [[ -n "${nginx_enable_link}" ]]; then
    ${SUDO_CMD} ln -sf "${nginx_conf}" "${nginx_enable_link}"
    if [[ -f /etc/nginx/sites-enabled/default ]]; then
      ${SUDO_CMD} rm -f /etc/nginx/sites-enabled/default
    fi
  fi
}

write_tmp_cleanup_cron() {
  log "写入定时清理任务：${CRON_FILE}"
  ${SUDO_CMD} tee "${CRON_FILE}" >/dev/null <<EOF
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/sbin:/bin:/usr/sbin:/usr/bin

*/10 * * * * root test -d "${APP_TMP_DIR}" && find "${APP_TMP_DIR}" -type f -mmin +${TMP_RETENTION_MINUTES} -delete && find "${APP_TMP_DIR}" -mindepth 1 -type d -empty -delete
EOF
  ${SUDO_CMD} chmod 644 "${CRON_FILE}"
}

start_services() {
  log "重载并启用服务"
  ${SUDO_CMD} systemctl daemon-reload
  ${SUDO_CMD} systemctl enable "${APP_NAME}"
  ${SUDO_CMD} systemctl restart "${APP_NAME}"

  ${SUDO_CMD} nginx -t
  ${SUDO_CMD} systemctl enable nginx
  ${SUDO_CMD} systemctl restart nginx
}

show_result() {
  log "部署完成"
  echo "APP_DIR: ${APP_DIR}"
  echo "Service: ${APP_NAME}"
  echo "Port: ${APP_PORT}"
  echo "Domain: ${APP_DOMAIN}"
  echo "TmpDir: ${APP_TMP_DIR}"
  echo "TmpCron: ${CRON_FILE} (每 10 分钟清理一次，清理 ${TMP_RETENTION_MINUTES} 分钟前文件)"
  echo
  echo "下一步（请务必执行）:"
  echo "  1) 编辑环境变量（填真实 Key）:"
  echo "     sudo editor ${ENV_FILE}"
  echo "  2) 重启服务使配置生效:"
  echo "     sudo bash deploy/linux/manage.sh restart"
  echo
  echo "常用命令:"
  echo "  - 查看帮助:  sudo bash deploy/linux/manage.sh help"
  echo "  - 查看状态:  sudo bash deploy/linux/manage.sh status"
  echo "  - 查看日志:  sudo bash deploy/linux/manage.sh logs"
  echo "  - Nginx日志: sudo bash deploy/linux/manage.sh logs-nginx"
}

main() {
  install_packages
  prepare_runtime
  prepare_tmp_dir
  build_frontend
  write_env_file
  write_systemd_service
  write_nginx_config
  write_tmp_cleanup_cron
  start_services
  show_result
}

main "$@"
