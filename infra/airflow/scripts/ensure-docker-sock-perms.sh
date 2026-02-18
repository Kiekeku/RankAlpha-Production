#!/usr/bin/env bash
set -euo pipefail

# Default log directory path so unset LOGS_DIR doesn't abort the script.
LOGS_DIR="${LOGS_DIR:-/opt/airflow/logs}"

SOCKET_PATH="${DOCKER_SOCKET_PATH:-/var/run/docker.sock}"
TARGET_USER="${DOCKER_SOCKET_USER:-airflow}"

if [ ! -S "$SOCKET_PATH" ]; then
  echo "[ensure-docker-sock] Socket not present at $SOCKET_PATH; skipping group alignment."
  exit 0
fi

# Determine group id owning the docker socket
DOCKER_GID=$(stat -c '%g' "$SOCKET_PATH")
if [ -z "$DOCKER_GID" ]; then
  echo "[ensure-docker-sock] Failed to detect group id for $SOCKET_PATH" >&2
  exit 1
fi

# Find or create group matching the gid
DOCKER_GROUP=$(getent group "$DOCKER_GID" | cut -d: -f1 || true)
if [ -z "$DOCKER_GROUP" ]; then
  DOCKER_GROUP="dockerhost"
  if ! getent group "$DOCKER_GROUP" >/dev/null 2>&1; then
    groupadd -g "$DOCKER_GID" "$DOCKER_GROUP"
    echo "[ensure-docker-sock] Created group $DOCKER_GROUP ($DOCKER_GID)."
  fi
else
  echo "[ensure-docker-sock] Reusing existing group $DOCKER_GROUP ($DOCKER_GID)."
fi

# Ensure target user exists before modifying
if ! id "$TARGET_USER" >/dev/null 2>&1; then
  echo "[ensure-docker-sock] Target user $TARGET_USER not found; skipping." >&2
  exit 0
fi

if id -nG "$TARGET_USER" | tr ' ' '\n' | grep -Fx "$DOCKER_GROUP" >/dev/null 2>&1; then
  echo "[ensure-docker-sock] User $TARGET_USER already in group $DOCKER_GROUP."
else
  usermod -aG "$DOCKER_GROUP" "$TARGET_USER"
  echo "[ensure-docker-sock] Added $TARGET_USER to group $DOCKER_GROUP."
fi

if [ -d "$LOGS_DIR" ]; then
  TARGET_GROUP_NAME=$(id -gn "$TARGET_USER")
  if chown -R "$TARGET_USER":"$TARGET_GROUP_NAME" "$LOGS_DIR" 2>/tmp/chown_err.log; then
    echo "[ensure-docker-sock] Reset ownership on $LOGS_DIR to $TARGET_USER:$TARGET_GROUP_NAME."
  else
    echo "[ensure-docker-sock] Warning: failed to chown $LOGS_DIR; see /tmp/chown_err.log" >&2
  fi
else
  echo "[ensure-docker-sock] Logs directory $LOGS_DIR not present; skipping ownership fix."
fi

exit 0
