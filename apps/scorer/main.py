"""Scorer service entrypoint (stable across local + Docker runs)."""
from __future__ import annotations

from apps.scorer.src.main import main

if __name__ == "__main__":
    main()
