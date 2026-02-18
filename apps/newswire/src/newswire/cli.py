from __future__ import annotations

import argparse
import os

from newswire.db import session_factory
from newswire.llm import analyze_recent_events


def main():
    parser = argparse.ArgumentParser(prog="newswire-cli")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_an = sub.add_parser("analyze", help="Analyze recent news events with LLM")
    p_an.add_argument(
        "--hours", type=int, default=int(os.environ.get("NEWS_LLM_ANALYZE_HOURS", "6"))
    )
    p_an.add_argument(
        "--limit", type=int, default=int(os.environ.get("NEWS_LLM_ANALYZE_LIMIT", "20"))
    )

    args = parser.parse_args()
    if args.cmd == "analyze":
        SessionLocal = session_factory()
        with SessionLocal() as db:
            res = analyze_recent_events(db, hours=args.hours, limit=args.limit)
            print(res)


if __name__ == "__main__":
    main()
