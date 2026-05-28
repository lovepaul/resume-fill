#!/usr/bin/env bash
set -euo pipefail

RUNTIME_DIR="${APP_RUNTIME_DIR:-/var/lib/resume-web/runtime}"
UPLOAD_DIR="${RUNTIME_DIR}/uploads"
OUTPUT_DIR="${RUNTIME_DIR}/outputs"
UPLOAD_LIMIT_BYTES="${UPLOADS_MAX_BYTES:-52428800}"
OUTPUT_LIMIT_BYTES="${OUTPUTS_MAX_BYTES:-10485760}"

dir_size_bytes() {
  local dir="$1"
  if [[ ! -d "${dir}" ]]; then
    echo 0
    return
  fi
  du -sb "${dir}" 2>/dev/null | awk '{print $1}'
}

oldest_file_in_dir() {
  local dir="$1"
  if [[ ! -d "${dir}" ]]; then
    return
  fi
  find "${dir}" -maxdepth 1 -type f -printf '%T@ %p\n' 2>/dev/null | sort -n | awk 'NR==1 {sub(/^[^ ]+ /, ""); print}'
}

prune_by_size() {
  local dir="$1"
  local max_bytes="$2"
  [[ -d "${dir}" ]] || return

  local current_size
  current_size="$(dir_size_bytes "${dir}")"
  while (( current_size > max_bytes )); do
    local oldest
    oldest="$(oldest_file_in_dir "${dir}")"
    [[ -n "${oldest}" ]] || break
    rm -f "${oldest}" || true
    current_size="$(dir_size_bytes "${dir}")"
  done
}

mkdir -p "${UPLOAD_DIR}" "${OUTPUT_DIR}"
prune_by_size "${UPLOAD_DIR}" "${UPLOAD_LIMIT_BYTES}"
prune_by_size "${OUTPUT_DIR}" "${OUTPUT_LIMIT_BYTES}"
