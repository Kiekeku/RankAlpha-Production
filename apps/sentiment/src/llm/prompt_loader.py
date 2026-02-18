from __future__ import annotations

from pathlib import Path
from typing import Mapping


def _prompts_dir() -> Path:
    """Return the directory containing prompt markdown files.

    Resolved relative to this file so it works in containers or local runs.
    """
    return Path(__file__).resolve().parent.parent / "prompts"


def load_prompt(name: str, replacements: Mapping[str, str] | None = None) -> str:
    """Load a prompt from a markdown file and apply simple token replacements.

    - `name` can be with or without `.md` extension.
    - `replacements` applies string substitutions for tokens of the form
      `{{TOKEN}}` to avoid conflicts with JSON braces in prompt content.
    """
    filename = name if name.endswith(".md") else f"{name}.md"
    path = _prompts_dir() / filename
    if not path.exists():
        raise FileNotFoundError(f"Prompt file not found: {path}")

    text = path.read_text(encoding="utf-8")
    if replacements:
        for key, value in replacements.items():
            text = text.replace(f"{{{{{key}}}}}", str(value))
    return text
