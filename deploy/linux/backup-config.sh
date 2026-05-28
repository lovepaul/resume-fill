#!/usr/bin/env bash
set -euo pipefail

APP_NAME="${APP_NAME:-resume-web}"
SUDO_CMD=""
if [[ "${EUID}" -ne 0 ]]; then
  SUDO_CMD="sudo"
fi

BACKUP_ROOT="/var/backups/${APP_NAME}"
TIMESTAMP="$(date +'%Y%m%d-%H%M%S')"
BACKUP_DIR="${BACKUP_ROOT}/${TIMESTAMP}"
ENV_FILE="/etc/${APP_NAME}.env"
SERVICE_FILE="/etc/systemd/system/${APP_NAME}.service"
CRON_FILE="/etc/cron.d/${APP_NAME}-tmp-cleanup"

${SUDO_CMD} mkdir -p "${BACKUP_DIR}"

if [[ -f "${ENV_FILE}" ]]; then
  ${SUDO_CMD} cp "${ENV_FILE}" "${BACKUP_DIR}/$(basename "${ENV_FILE}")"
fi
if [[ -f "${SERVICE_FILE}" ]]; then
  ${SUDO_CMD} cp "${SERVICE_FILE}" "${BACKUP_DIR}/$(basename "${SERVICE_FILE}")"
fi
if [[ -f "${CRON_FILE}" ]]; then
  ${SUDO_CMD} cp "${CRON_FILE}" "${BACKUP_DIR}/$(basename "${CRON_FILE}")"
fi
if [[ -f "/etc/nginx/sites-available/${APP_NAME}.conf" ]]; then
  ${SUDO_CMD} cp "/etc/nginx/sites-available/${APP_NAME}.conf" "${BACKUP_DIR}/${APP_NAME}.nginx.conf"
elif [[ -f "/etc/nginx/conf.d/${APP_NAME}.conf" ]]; then
  ${SUDO_CMD} cp "/etc/nginx/conf.d/${APP_NAME}.conf" "${BACKUP_DIR}/${APP_NAME}.nginx.conf"
fi

echo "备份完成: ${BACKUP_DIR}"

