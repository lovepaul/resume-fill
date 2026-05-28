#!/usr/bin/env bash
set -euo pipefail

APP_NAME="${APP_NAME:-resume-web}"
SUDO_CMD=""
if [[ "${EUID}" -ne 0 ]]; then
  SUDO_CMD="sudo"
fi

BACKUP_ROOT="/var/backups/${APP_NAME}"
TARGET_BACKUP="${1:-}"
if [[ -z "${TARGET_BACKUP}" ]]; then
  TARGET_BACKUP="$(ls -1 "${BACKUP_ROOT}" 2>/dev/null | sort | tail -n 1 || true)"
fi

if [[ -z "${TARGET_BACKUP}" ]]; then
  echo "错误: 未找到可回滚的备份目录（${BACKUP_ROOT}）" >&2
  exit 1
fi

BACKUP_DIR="${BACKUP_ROOT}/${TARGET_BACKUP}"
if [[ ! -d "${BACKUP_DIR}" ]]; then
  echo "错误: 备份目录不存在: ${BACKUP_DIR}" >&2
  exit 1
fi

ENV_FILE="/etc/${APP_NAME}.env"
SERVICE_FILE="/etc/systemd/system/${APP_NAME}.service"
CRON_FILE="/etc/cron.d/${APP_NAME}-tmp-cleanup"

if [[ -f "${BACKUP_DIR}/$(basename "${ENV_FILE}")" ]]; then
  ${SUDO_CMD} cp "${BACKUP_DIR}/$(basename "${ENV_FILE}")" "${ENV_FILE}"
fi
if [[ -f "${BACKUP_DIR}/$(basename "${SERVICE_FILE}")" ]]; then
  ${SUDO_CMD} cp "${BACKUP_DIR}/$(basename "${SERVICE_FILE}")" "${SERVICE_FILE}"
fi
if [[ -f "${BACKUP_DIR}/$(basename "${CRON_FILE}")" ]]; then
  ${SUDO_CMD} cp "${BACKUP_DIR}/$(basename "${CRON_FILE}")" "${CRON_FILE}"
fi
if [[ -f "${BACKUP_DIR}/${APP_NAME}.nginx.conf" ]]; then
  if [[ -d /etc/nginx/sites-available ]]; then
    ${SUDO_CMD} cp "${BACKUP_DIR}/${APP_NAME}.nginx.conf" "/etc/nginx/sites-available/${APP_NAME}.conf"
  else
    ${SUDO_CMD} cp "${BACKUP_DIR}/${APP_NAME}.nginx.conf" "/etc/nginx/conf.d/${APP_NAME}.conf"
  fi
fi

${SUDO_CMD} systemctl daemon-reload
${SUDO_CMD} nginx -t
${SUDO_CMD} systemctl restart "${APP_NAME}" nginx

echo "回滚完成: ${BACKUP_DIR}"

