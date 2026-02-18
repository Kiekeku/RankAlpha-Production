from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest


@dataclass(frozen=True)
class SecretHit:
    path: str
    line: int
    kind: str
    preview: str


_SKIP_EXTENSIONS = {
    ".md",
    ".lock",
    ".xml",
    ".svg",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".pdf",
    ".parquet",
    ".zip",
    ".gz",
    ".bz2",
    ".xz",
    ".whl",
    ".so",
    ".dylib",
    ".dll",
    ".exe",
}

_SKIP_FILENAMES = {
    "uv.lock",
}

_SKIP_PATH_PARTS = {
    ".venv",
    "node_modules",
    ".pytest_cache",
}

_ALLOWLIST_VALUE_PREFIXES = (
    "your_",
    "<",
)

_ALLOWLIST_VALUES = {
    "",
    "...",
    "changeme",
    "du-changeme",
    "u-changeme",
    "redacted",
    "<redacted>",
    "<secret>",
    "<token>",
    "<key>",
    "dummy",
    "test",
}


_RX_PRIVATE_KEY_BLOCK = re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")
_RX_IBKR_ACCOUNT_ID = re.compile(r"\b(?:DU|U)\d{6,}\b")

# Examples:
#   consumer_key='abc...'
#   access_token_secret = "xyz..."
#   dh_prime="00aa..."
_RX_INLINE_OAUTH_ASSIGN = re.compile(
    r"""(?ix)
    \b(consumer_key|access_token|access_token_secret|dh_prime)\b
    \s*[:=]\s*
    (["'])
    (?P<val>[^"']{6,})
    \2
    """
)

# Examples:
#   IB_OAUTH_ACCESS_TOKEN=...
#   ACCOUNT1_BROKER_OAUTH_ACCESS_TOKEN_SECRET=...
# Intentionally case-sensitive: this should only match UPPER_SNAKE_CASE env vars
# (not Python identifiers like broker_oauth_consumer_key=...).
_RX_ENV_OAUTH_ASSIGN = re.compile(
    r"""(?x)
    \b(
      IB_OAUTH_(?:CONSUMER_KEY|ACCESS_TOKEN|ACCESS_TOKEN_SECRET|DH_PRIME)
      |BROKER_OAUTH_(?:CONSUMER_KEY|ACCESS_TOKEN|ACCESS_TOKEN_SECRET|DH_PRIME)
      |ACCOUNT\d+_BROKER_OAUTH_(?:CONSUMER_KEY|ACCESS_TOKEN|ACCESS_TOKEN_SECRET|DH_PRIME)
    )\b
    \s*=\s*
    (?P<val>[^#\n]+)
    """
)


def _is_text_file(data: bytes) -> bool:
    return b"\x00" not in data[:2048]


def _should_skip(path: Path) -> bool:
    if path.name in _SKIP_FILENAMES:
        return True
    if path.suffix.lower() in _SKIP_EXTENSIONS:
        return True
    if any(part in _SKIP_PATH_PARTS for part in path.parts):
        return True
    # Allow example env files to contain placeholders.
    if path.name.endswith(".env.example"):
        return True
    if path.name == ".env.example":
        return True
    return False


def _looks_like_placeholder(value: str) -> bool:
    v = value.strip().strip("'\"").strip()
    if not v:
        return True
    vl = v.lower()
    if vl in _ALLOWLIST_VALUES:
        return True
    if any(vl.startswith(p) for p in _ALLOWLIST_VALUE_PREFIXES):
        return True
    if "..." in vl:
        return True
    if "replace" in vl and "with" in vl:
        return True
    return False


def _redact_preview(line: str) -> str:
    s = line.rstrip("\n")
    s = re.sub(r"\bDU\d{6,}\b", "DU<REDACTED>", s)
    s = re.sub(r"\bU\d{6,}\b", "U<REDACTED>", s)
    s = re.sub(
        r"""(?ix)
        (\b(?:consumer_key|access_token|access_token_secret|dh_prime)\b\s*[:=]\s*)
        (["'])
        ([^"']+)
        \2
        """,
        r"\1\2<REDACTED>\2",
        s,
    )
    s = re.sub(
        r"""(?ix)
        (\b(?:IB_OAUTH|BROKER_OAUTH|ACCOUNT\d+_BROKER_OAUTH)_[A-Z_]+\b\s*=\s*)
        ([^#\s]+)
        """,
        r"\1<REDACTED>",
        s,
    )
    return s


def _git_tracked_files(repo_root: Path) -> list[Path]:
    try:
        out = subprocess.check_output(["git", "ls-files"], cwd=repo_root, text=True)
    except Exception:
        pytest.skip("git not available; skipping tracked-file secret scan")
        raise
    return [repo_root / line for line in out.splitlines() if line.strip()]


def _scan_file(path: Path, *, repo_root: Path) -> list[SecretHit]:
    try:
        data = path.read_bytes()
    except OSError:
        return []
    if not _is_text_file(data):
        return []

    rel = str(path.relative_to(repo_root))
    hits: list[SecretHit] = []
    lines = data.decode("utf-8", errors="replace").splitlines()
    for idx, raw in enumerate(lines, start=1):
        line = raw.strip()
        if not line:
            continue

        if _RX_PRIVATE_KEY_BLOCK.search(line):
            hits.append(SecretHit(rel, idx, "private_key_block", _redact_preview(raw)))

        if _RX_IBKR_ACCOUNT_ID.search(line):
            hits.append(SecretHit(rel, idx, "ibkr_account_id_like", _redact_preview(raw)))

        m_inline = _RX_INLINE_OAUTH_ASSIGN.search(line)
        if m_inline and not _looks_like_placeholder(m_inline.group("val")):
            hits.append(SecretHit(rel, idx, "oauth_inline_assignment", _redact_preview(raw)))

        m_env = _RX_ENV_OAUTH_ASSIGN.search(line)
        if m_env and not _looks_like_placeholder(m_env.group("val")):
            hits.append(SecretHit(rel, idx, "oauth_env_assignment", _redact_preview(raw)))

    return hits


def test_no_ibkr_secrets_or_private_keys_in_tracked_files() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    tracked = _git_tracked_files(repo_root)

    # Focus on code/config; avoid scanning the entire repo by default.
    scoped = [
        p
        for p in tracked
        if any(
            str(p.relative_to(repo_root)).startswith(prefix)
            for prefix in ("apps/broker/", "tests/", "compose/", "docker/", "infra/", "env/")
        )
    ]

    hits: list[SecretHit] = []
    for path in scoped:
        if _should_skip(path):
            continue
        hits.extend(_scan_file(path, repo_root=repo_root))

    # De-dupe identical reports (same file/line/kind).
    unique: dict[tuple[str, int, str], SecretHit] = {}
    for h in hits:
        unique[(h.path, h.line, h.kind)] = h
    hits = [unique[k] for k in sorted(unique)]

    if hits:
        msg_lines = ["Detected possible secrets in tracked files:"]
        msg_lines.extend(
            f"- {h.path}:{h.line} [{h.kind}] {h.preview}"
            for h in hits[:50]
        )
        if len(hits) > 50:
            msg_lines.append(f"... ({len(hits) - 50} more)")
        pytest.fail("\n".join(msg_lines))
