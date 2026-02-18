#!/usr/bin/env sh

set -eu

port="${REDIS_PORT:-6379}"
policy="${REDIS_MAXMEMORY_POLICY:-allkeys-lru}"

maxmemory="${REDIS_MAXMEMORY:-}"

if [ -z "${maxmemory}" ]; then
  # Prefer container memory limit when present (cgroup v2), else fall back to host MemTotal.
  total_bytes=""

  if [ -r /sys/fs/cgroup/memory.max ]; then
    v="$(cat /sys/fs/cgroup/memory.max 2>/dev/null || true)"
    if [ -n "${v}" ] && [ "${v}" != "max" ]; then
      total_bytes="${v}"
    fi
  fi

  if [ -z "${total_bytes}" ] && [ -r /sys/fs/cgroup/memory/memory.limit_in_bytes ]; then
    v="$(cat /sys/fs/cgroup/memory/memory.limit_in_bytes 2>/dev/null || true)"
    # Some runtimes report an "unlimited" sentinel near 2^63.
    if [ -n "${v}" ] && [ "${v}" -lt 9000000000000000000 ]; then
      total_bytes="${v}"
    fi
  fi

  if [ -z "${total_bytes}" ]; then
    total_kb="$(awk '/^MemTotal:/ {print $2}' /proc/meminfo)"
    total_bytes="$((total_kb * 1024))"
  fi

  ratio="${REDIS_MAXMEMORY_RATIO:-0.3}"
  maxmemory="$(awk -v total="${total_bytes}" -v ratio="${ratio}" 'BEGIN { printf "%.0f\n", total * ratio }')"
fi

exec redis-server \
  --port "${port}" \
  --maxmemory "${maxmemory}" \
  --maxmemory-policy "${policy}"

