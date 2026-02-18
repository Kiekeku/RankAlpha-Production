"""
Guardrail test: prevent accidental JSON literals in Python modules.

Catches bare identifiers `true`, `false`, `null` in .py files which cause
NameError at import time (Python expects `True`, `False`, `None`).

Opt-out per line with:  # noqa: json-literal
"""

from __future__ import annotations

import io
import os
from pathlib import Path
import tokenize


NOQA_TAG = "noqa: json-literal"
BAD_NAMES = {"true", "false", "null"}
ROOT = Path(__file__).resolve().parents[1]


def iter_python_files() -> list[Path]:
    """Yield Python files under key project dirs, skipping vendor/build dirs."""
    include_dirs = [ROOT / "apps", ROOT / "src", ROOT / "infra", ROOT / "docker"]
    exclude_dir_names = {
        ".git",
        ".venv",
        "env",
        ".uv-cache",
        ".pytest_cache",
        "node_modules",
        "__pycache__",
        ".next",
        "dist",
        "build",
    }
    for base in include_dirs:
        if not base.exists():
            continue
        for root, dirs, files in os.walk(base):
            # prune excluded dirs in-place
            dirs[:] = [d for d in dirs if d not in exclude_dir_names]
            for f in files:
                if f.endswith(".py"):
                    yield Path(root) / f


def find_json_literals(paths: list[Path]) -> list[tuple[Path, int, int, str, str]]:
    """Return list of (path, line, col, value, line_text) for offending tokens."""
    findings: list[tuple[Path, int, int, str, str]] = []
    for p in paths:
        try:
            data = p.read_bytes()
        except Exception:
            continue
        try:
            # Tokenize from bytes to avoid encoding pitfalls
            tok_iter = tokenize.tokenize(io.BytesIO(data).readline)
            # Preload lines for fast lookup
            lines = data.decode(errors="ignore").splitlines()
            for tok in tok_iter:
                if tok.type == tokenize.NAME and tok.string in BAD_NAMES:
                    line_idx = tok.start[0] - 1
                    line_text = lines[line_idx] if 0 <= line_idx < len(lines) else ""
                    if NOQA_TAG in line_text:
                        continue
                    findings.append((p, tok.start[0], tok.start[1] + 1, tok.string, line_text.strip()))
        except tokenize.TokenError:
            # Skip files that fail to tokenize (keeps test robust)
            continue
    return findings


def test_no_json_literals_in_python_modules():
    py_files = list(iter_python_files())
    offenders = find_json_literals(py_files)
    if offenders:
        details = "\n".join(
            f"- {path}:{line}:{col} uses '{val}' -> use {'True' if val=='true' else 'False' if val=='false' else 'None'}\n    {src}"
            for path, line, col, val, src in offenders
        )
        raise AssertionError(
            "Found bare JSON literals in Python code (should be True/False/None).\n"
            + details
            + "\nAdd '# noqa: json-literal' to a line if you must intentionally use such a name."
        )

