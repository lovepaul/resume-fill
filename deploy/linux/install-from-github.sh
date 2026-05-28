#!/usr/bin/env bash
set -euo pipefail

# 从 GitHub 一键拉取并部署到 Linux
# 用法：
#   bash install-from-github.sh
#   APP_REPO=https://github.com/xxx/yyy.git APP_BRANCH=main bash install-from-github.sh
#   APP_DIR=/opt/resume-fill APP_DOMAIN=lensmanlucas.com sudo -E bash install-from-github.sh

APP_REPO="${APP_REPO:-https://github.com/lovepaul/resume-fill.git}"
APP_BRANCH="${APP_BRANCH:-main}"
APP_DIR="${APP_DIR:-/opt/resume-fill}"
APP_DOMAIN="${APP_DOMAIN:-lensmanlucas.com www.lensmanlucas.com}"

SUDO_CMD=""
if [[ "${EUID}" -ne 0 ]]; then
  SUDO_CMD="sudo"
fi

log() {
  printf "\n[%s] %s\n" "$(date +'%F %T')" "$*"
}

ensure_git() {
  if command -v git >/dev/null 2>&1; then
    return
  fi

  log "检测到 git 未安装，尝试自动安装"
  if command -v apt-get >/dev/null 2>&1; then
    ${SUDO_CMD} apt-get update
    ${SUDO_CMD} apt-get install -y git
  elif command -v dnf >/dev/null 2>&1; then
    ${SUDO_CMD} dnf install -y git
  elif command -v yum >/dev/null 2>&1; then
    ${SUDO_CMD} yum install -y git
  elif command -v apk >/dev/null 2>&1; then
    ${SUDO_CMD} apk add --no-cache git
  elif command -v pacman >/dev/null 2>&1; then
    ${SUDO_CMD} pacman -Sy --noconfirm git
  elif command -v zypper >/dev/null 2>&1; then
    ${SUDO_CMD} zypper --non-interactive install git
  else
    echo "错误: 未识别系统包管理器，无法自动安装 git。" >&2
    echo "请先手动安装 git 后重试。" >&2
    exit 1
  fi
}

sync_repo() {
  if [[ -d "${APP_DIR}/.git" ]]; then
    log "检测到已有仓库，拉取最新代码 (${APP_BRANCH})"
    git -C "${APP_DIR}" fetch origin "${APP_BRANCH}"
    git -C "${APP_DIR}" checkout "${APP_BRANCH}"
    git -C "${APP_DIR}" pull --ff-only origin "${APP_BRANCH}"
  else
    log "克隆仓库到 ${APP_DIR}"
    ${SUDO_CMD} mkdir -p "$(dirname "${APP_DIR}")"
    git clone --depth 1 --branch "${APP_BRANCH}" "${APP_REPO}" "${APP_DIR}"
  fi
}

run_bootstrap() {
  log "执行 Linux 全自动部署脚本"
  ${SUDO_CMD} chmod +x "${APP_DIR}/deploy/linux/bootstrap.sh" "${APP_DIR}/deploy/linux/manage.sh"
  if [[ -n "${SUDO_CMD}" ]]; then
    ${SUDO_CMD} env \
      APP_NAME="${APP_NAME:-resume-web}" \
      APP_USER="${APP_USER:-www-data}" \
      APP_GROUP="${APP_GROUP:-www-data}" \
      APP_PORT="${APP_PORT:-8000}" \
      APP_DOMAIN="${APP_DOMAIN}" \
      INSTALL_PACKAGES="${INSTALL_PACKAGES:-1}" \
      APP_DIR="${APP_DIR}" \
      PYTHON_BIN="${PYTHON_BIN:-python3}" \
      APP_TMP_DIR="${APP_TMP_DIR:-/var/lib/resume-web/runtime}" \
      UPLOADS_MAX_BYTES="${UPLOADS_MAX_BYTES:-52428800}" \
      OUTPUTS_MAX_BYTES="${OUTPUTS_MAX_BYTES:-10485760}" \
      DISTILL_MAX_BYTES="${DISTILL_MAX_BYTES:-209715200}" \
      NVWA_USERNAME="${NVWA_USERNAME:-lensman}" \
      NVWA_PASSWORD="${NVWA_PASSWORD:-change_me_nvwa_password}" \
      STATS_USERNAME="${STATS_USERNAME:-lensman}" \
      STATS_PASSWORD="${STATS_PASSWORD:-change_me_stats_password}" \
      ALLOW_WEAK_PASSWORDS="${ALLOW_WEAK_PASSWORDS:-0}" \
      HERMES_DISTILL_COMMAND="${HERMES_DISTILL_COMMAND:-hermes run \"distill-docs --input {input_dir} --output {output_json}\"}" \
      bash "${APP_DIR}/deploy/linux/bootstrap.sh"
  else
    env \
      APP_NAME="${APP_NAME:-resume-web}" \
      APP_USER="${APP_USER:-www-data}" \
      APP_GROUP="${APP_GROUP:-www-data}" \
      APP_PORT="${APP_PORT:-8000}" \
      APP_DOMAIN="${APP_DOMAIN}" \
      INSTALL_PACKAGES="${INSTALL_PACKAGES:-1}" \
      APP_DIR="${APP_DIR}" \
      PYTHON_BIN="${PYTHON_BIN:-python3}" \
      APP_TMP_DIR="${APP_TMP_DIR:-/var/lib/resume-web/runtime}" \
      UPLOADS_MAX_BYTES="${UPLOADS_MAX_BYTES:-52428800}" \
      OUTPUTS_MAX_BYTES="${OUTPUTS_MAX_BYTES:-10485760}" \
      DISTILL_MAX_BYTES="${DISTILL_MAX_BYTES:-209715200}" \
      NVWA_USERNAME="${NVWA_USERNAME:-lensman}" \
      NVWA_PASSWORD="${NVWA_PASSWORD:-change_me_nvwa_password}" \
      STATS_USERNAME="${STATS_USERNAME:-lensman}" \
      STATS_PASSWORD="${STATS_PASSWORD:-change_me_stats_password}" \
      ALLOW_WEAK_PASSWORDS="${ALLOW_WEAK_PASSWORDS:-0}" \
      HERMES_DISTILL_COMMAND="${HERMES_DISTILL_COMMAND:-hermes run \"distill-docs --input {input_dir} --output {output_json}\"}" \
      bash "${APP_DIR}/deploy/linux/bootstrap.sh"
  fi
}

main() {
  ensure_git
  sync_repo
  run_bootstrap
  log "完成：已从 GitHub 拉取并部署。"
}

main "$@"
