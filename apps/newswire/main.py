"""Newswire service entrypoint (stable across local + Docker runs)."""
from __future__ import annotations

import asyncio

from newswire.main import run_forever


def main() -> None:
    asyncio.run(run_forever())


if __name__ == "__main__":
    main()

