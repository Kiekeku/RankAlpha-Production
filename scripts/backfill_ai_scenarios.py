#!/usr/bin/env python3
"""Backfill AI scenario targets from historical report JSON files.

This script reads report JSON files (plain JSON or fenced JSON inside .md)
and upserts bull/base/bear scenario targets into rankalpha.fact_ai_price_scenario.
It matches analyses by (symbol, as_of_date) and updates the latest analysis_id
for that date/symbol.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import socket
import sys
from typing import Any, Dict, Iterable, List, Optional, Tuple

import psycopg2
from psycopg2.extras import execute_values


def load_env_file(path: str) -> None:
    """Load key=value pairs into os.environ if not already set."""
    if not path or not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as handle:
        for raw in handle:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


def extract_json_from_text(text: str) -> Dict[str, Any]:
    """Extract JSON from raw file text."""
    text = text.strip()
    if not text:
        raise ValueError("Empty file")
    # Plain JSON first
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass
    # Fenced JSON blocks
    for pattern in (r"```json\s*(\{.*?\})\s*```", r"'''json\s*(\{.*?\})\s*'''"):
        match = re.search(pattern, text, flags=re.DOTALL)
        if match:
            return json.loads(match.group(1))
    # Fallback: first {...} block
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        return json.loads(text[start : end + 1])
    raise ValueError("JSON block not found")


def coerce_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        return None


def parse_scenario_targets(data: Dict[str, Any]) -> List[Tuple[str, Optional[float], Optional[float]]]:
    scenario = data.get("scenario_price_targets") or {}
    if not isinstance(scenario, dict):
        return []
    rows: List[Tuple[str, Optional[float], Optional[float]]] = []
    if any(key in scenario for key in ("bull", "base", "bear")):
        # Legacy shape: {bull|base|bear: {price, probability_pct}}
        for scen in ("bull", "base", "bear"):
            sdata = scenario.get(scen)
            if isinstance(sdata, dict):
                price = coerce_float(sdata.get("price"))
                prob = coerce_float(sdata.get("probability_pct"))
                if prob is None:
                    prob = coerce_float(sdata.get("probability_ptc"))
                if prob is None:
                    prob = coerce_float(sdata.get("probability"))
            else:
                price = coerce_float(sdata)
                prob = None
            rows.append((scen, price, prob))
        return rows
    if any(
        key in scenario
        for key in ("bull_target", "base_target", "bear_target", "associated_probabilities")
    ):
        probs_raw = scenario.get("associated_probabilities") or {}
        probs: Dict[str, Any] = {}
        if isinstance(probs_raw, list):
            if len(probs_raw) >= 1:
                probs["bull"] = probs_raw[0]
            if len(probs_raw) >= 2:
                probs["base"] = probs_raw[1]
            if len(probs_raw) >= 3:
                probs["bear"] = probs_raw[2]
        elif isinstance(probs_raw, dict):
            probs = probs_raw
        rows.extend(
            [
                ("bull", coerce_float(scenario.get("bull_target")), coerce_float(probs.get("bull"))),
                ("base", coerce_float(scenario.get("base_target")), coerce_float(probs.get("base"))),
                ("bear", coerce_float(scenario.get("bear_target")), coerce_float(probs.get("bear"))),
            ]
        )
    return rows


def iter_report_files(reports_dir: str) -> Iterable[str]:
    for root, _dirs, files in os.walk(reports_dir):
        for name in files:
            if not (name.endswith(".md") or name.endswith(".json")):
                continue
            yield os.path.join(root, name)


def resolve_db_params(args: argparse.Namespace) -> Tuple[Optional[str], Dict[str, Any]]:
    if args.env_file:
        load_env_file(args.env_file)
    if os.path.exists("env/local/shared.env") and not args.env_file:
        load_env_file("env/local/shared.env")
    db_url = args.db_url or os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL")
    if db_url:
        return db_url, {}
    db_name = args.db_name or os.environ.get("DATABASE_NAME") or os.environ.get("POSTGRES_DB")
    db_user = args.db_user or os.environ.get("DB_USERNAME") or os.environ.get("POSTGRES_USER")
    db_password = args.db_password or os.environ.get("PASSWORD") or os.environ.get("POSTGRES_PASSWORD")
    db_host = args.db_host or os.environ.get("DB_HOST") or "localhost"
    db_port = args.db_port or os.environ.get("DB_PORT") or "5432"
    if db_host == "database" and not args.db_host:
        try:
            socket.gethostbyname(db_host)
        except socket.gaierror:
            db_host = "localhost"
            if str(db_port) == "5432" and not args.db_port:
                db_port = "6543"
    return None, {
        "database": db_name,
        "user": db_user,
        "password": db_password,
        "host": db_host,
        "port": int(db_port),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill AI scenario targets from report JSON files.")
    parser.add_argument(
        "--reports-dir",
        default="/var/lib/docker/volumes/rankalpha-prod_company_reports/_data",
        help="Directory containing report JSON files",
    )
    parser.add_argument("--env-file", default=None, help="Optional env file with DB settings")
    parser.add_argument("--db-host", default=None, help="DB host override")
    parser.add_argument("--db-port", default=None, help="DB port override")
    parser.add_argument("--db-name", default=None, help="DB name override")
    parser.add_argument("--db-user", default=None, help="DB user override")
    parser.add_argument("--db-password", default=None, help="DB password override")
    parser.add_argument("--db-url", default=None, help="Postgres connection string override")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of files processed")
    parser.add_argument("--dry-run", action="store_true", help="Parse and log without writing")
    args = parser.parse_args()

    if not os.path.exists(args.reports_dir):
        print(f"Reports dir not found: {args.reports_dir}", file=sys.stderr)
        return 2

    db_url, db_params = resolve_db_params(args)
    if not db_url:
        missing_params = [k for k, v in db_params.items() if not v]
        if missing_params:
            print(f"Missing DB params: {', '.join(missing_params)}", file=sys.stderr)
            return 2

    files = sorted(iter_report_files(args.reports_dir))
    if args.limit:
        files = files[: args.limit]

    processed = 0
    inserted = 0
    skipped = 0
    missing_analysis = 0
    parse_errors = 0

    conn = psycopg2.connect(db_url) if db_url else psycopg2.connect(**db_params)
    try:
        cur = conn.cursor()
        for path in files:
            processed += 1
            try:
                with open(path, "r", encoding="utf-8") as handle:
                    data = extract_json_from_text(handle.read())
            except Exception as exc:
                parse_errors += 1
                print(f"Parse failed: {path} ({exc})")
                continue

            ticker = (data.get("ticker") or "").strip().upper()
            as_of_date = (data.get("as_of_date") or "").strip()
            if not ticker or not as_of_date:
                skipped += 1
                continue
            date_key = as_of_date.replace("-", "")
            if not date_key.isdigit():
                skipped += 1
                continue
            scenario_rows = parse_scenario_targets(data)
            scenario_rows = [r for r in scenario_rows if r[1] is not None or r[2] is not None]
            if not scenario_rows:
                skipped += 1
                continue

            cur.execute(
                """
                SELECT a.analysis_id
                FROM rankalpha.fact_ai_stock_analysis a
                JOIN rankalpha.dim_stock s ON s.stock_key = a.stock_key
                WHERE s.symbol = %s AND a.date_key = %s
                ORDER BY a.load_ts DESC
                LIMIT 1
                """,
                (ticker, int(date_key)),
            )
            row = cur.fetchone()
            if not row:
                missing_analysis += 1
                continue
            analysis_id = row[0]
            if args.dry_run:
                inserted += len(scenario_rows)
                continue

            values = [(analysis_id, scen, price, prob) for scen, price, prob in scenario_rows]
            execute_values(
                cur,
                """
                INSERT INTO rankalpha.fact_ai_price_scenario
                    (analysis_id, scenario_type, price_target, probability_pct)
                VALUES %s
                ON CONFLICT (analysis_id, scenario_type) DO UPDATE
                SET price_target = COALESCE(EXCLUDED.price_target, rankalpha.fact_ai_price_scenario.price_target),
                    probability_pct = COALESCE(EXCLUDED.probability_pct, rankalpha.fact_ai_price_scenario.probability_pct)
                """,
                values,
            )
            inserted += len(values)
            conn.commit()
    finally:
        try:
            conn.close()
        except Exception:
            pass

    print("Backfill complete.")
    print(f"Files processed: {processed}")
    print(f"Scenario rows upserted: {inserted}")
    print(f"Skipped files: {skipped}")
    print(f"Missing analyses: {missing_analysis}")
    print(f"Parse errors: {parse_errors}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
