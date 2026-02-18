$ErrorActionPreference = "Stop"

$repoRoot = (git rev-parse --show-toplevel 2>$null)
if (-not $repoRoot) {
  Write-Error "install-githooks: not a git repo (run from inside the repo)"
  exit 1
}

Set-Location $repoRoot
git config core.hooksPath .githooks | Out-Null

Write-Output "Installed repo hooks via core.hooksPath=.githooks"
Write-Output "To bypass once: git commit --no-verify (or `$env:SKIP_SECRET_SCAN=1`)"

