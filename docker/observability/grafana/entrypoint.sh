#!/usr/bin/env sh
set -eu

# Map shared SMTP_* environment variables (used by other RankAlpha services)
# to Grafana's unified alerting SMTP settings.
#
# NOTE: Compose-time interpolation does not see variables loaded via env_file,
# so we do this mapping at container runtime.

if [ -z "${GF_SMTP_ENABLED:-}" ]; then
  if [ -n "${SMTP_HOST:-}" ]; then
    export GF_SMTP_ENABLED="true"
  else
    export GF_SMTP_ENABLED="false"
  fi
fi

if [ -z "${GF_SMTP_HOST:-}" ] && [ -n "${SMTP_HOST:-}" ]; then
  export GF_SMTP_HOST="${SMTP_HOST}:${SMTP_PORT:-587}"
fi

if [ -z "${GF_SMTP_USER:-}" ] && [ -n "${SMTP_USER:-}" ]; then
  export GF_SMTP_USER="${SMTP_USER}"
fi

if [ -z "${GF_SMTP_PASSWORD:-}" ] && [ -n "${SMTP_PASS:-}" ]; then
  export GF_SMTP_PASSWORD="${SMTP_PASS}"
fi

if [ -z "${GF_SMTP_FROM_ADDRESS:-}" ]; then
  if [ -n "${SMTP_FROM:-}" ]; then
    export GF_SMTP_FROM_ADDRESS="${SMTP_FROM}"
  elif [ -n "${SMTP_USER:-}" ]; then
    export GF_SMTP_FROM_ADDRESS="${SMTP_USER}"
  fi
fi

if [ -z "${GF_SMTP_FROM_NAME:-}" ]; then
  export GF_SMTP_FROM_NAME="RankAlpha"
fi

exec /run.sh "$@"

