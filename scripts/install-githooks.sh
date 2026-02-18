#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [[ -z "${REPO_ROOT}" ]]; then
  echo "install-githooks: not a git repo (run from inside the repo)" >&2
  exit 1
fi

cd "${REPO_ROOT}"

git config core.hooksPath .githooks
chmod +x .githooks/pre-commit

echo "Installed repo hooks via core.hooksPath=.githooks"
echo "To bypass once: git commit --no-verify (or SKIP_SECRET_SCAN=1)"

