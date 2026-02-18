#!/bin/sh
# /etc/sftp.d/init.sh
# Ensure the SFTP upload directory is owned by the SFTP user and writable.

set -eu

USER_NAME="${SFTP_USER:-foo}"
USER_UID="$(id -u "$USER_NAME" 2>/dev/null || echo 1001)"
USER_GID="$(id -g "$USER_NAME" 2>/dev/null || echo 1001)"
UPLOAD_DIR="/home/${USER_NAME}/upload"
DEFAULT_DIR="${SFTP_DEFAULT_DIR:-/upload}"

# Optionally override sshd listen port via SFTP_PORT
SFTP_PORT_VALUE="${SFTP_PORT:-}"
if [ -n "$SFTP_PORT_VALUE" ]; then
  if grep -qE '^\s*Port\s+' /etc/ssh/sshd_config 2>/dev/null; then
    sed -i -E "s/^\s*#?\s*Port\s+.*/Port ${SFTP_PORT_VALUE}/" /etc/ssh/sshd_config || true
  else
    echo "Port ${SFTP_PORT_VALUE}" >> /etc/ssh/sshd_config || true
  fi
  echo "[sftp-init] Set sshd Port to ${SFTP_PORT_VALUE}"
fi

if grep -qE '^\s*ForceCommand\s+internal-sftp' /etc/ssh/sshd_config 2>/dev/null; then
  if ! grep -qE "^\s*ForceCommand\s+internal-sftp\s+-d\s+${DEFAULT_DIR}\b" /etc/ssh/sshd_config 2>/dev/null; then
    sed -i -E "s|^\s*ForceCommand\s+internal-sftp.*|ForceCommand internal-sftp -d ${DEFAULT_DIR}|" /etc/ssh/sshd_config || true
    echo "[sftp-init] Updated ForceCommand to internal-sftp -d ${DEFAULT_DIR}"
  fi
else
  echo "ForceCommand internal-sftp -d ${DEFAULT_DIR}" >> /etc/ssh/sshd_config || true
  echo "[sftp-init] Added ForceCommand internal-sftp -d ${DEFAULT_DIR}"
fi

mkdir -p "$UPLOAD_DIR"
chown -R "${USER_UID}:${USER_GID}" "$UPLOAD_DIR"
chmod -R u+rwX,g+rwX "$UPLOAD_DIR"

echo "[sftp-init] Ensured $UPLOAD_DIR owned by ${USER_UID}:${USER_GID} with group-writable perms"
