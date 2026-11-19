"""Run every query in queries/analytics.sql under EXPLAIN (ANALYZE, BUFFERS) on the bench DB.

Usage: PYTHONPATH=src python scripts/explain.py [label]
Writes docs/plans/<label>/<query>.txt (default label: current). Run it before and after adding
an index to compare. Each query is run once to warm the cache, then explained 7 times; the plan saved is the
last run's and the time printed is the median.
"""

import re
import statistics
import sys
from pathlib import Path

import psycopg
from psycopg.conninfo import conninfo_to_dict

from chess_coach import db

ROOT = Path(__file__).resolve().parents[1]


def blocks(text: str) -> dict[str, str]:
    parts = re.split(r"^-- name: (\w+)\s*$", text, flags=re.MULTILINE)
    return {parts[i]: parts[i + 1].strip() for i in range(1, len(parts), 2)}


def main() -> None:
    label = sys.argv[1] if len(sys.argv) > 1 else "current"
    out = ROOT / "docs" / "plans" / label
    out.mkdir(parents=True, exist_ok=True)
    d = conninfo_to_dict(db.dsn())
    d["dbname"] = "chess_coach_bench"
    with psycopg.connect(**d, autocommit=True) as conn:
        conn.execute("ANALYZE")
        for name, sql in blocks((ROOT / "queries" / "analytics.sql").read_text()).items():
            conn.execute(sql)  # warm-up
            times = []
            for _ in range(7):
                plan = "\n".join(r[0] for r in conn.execute(f"EXPLAIN (ANALYZE, BUFFERS) {sql}"))
                times.append(float(re.search(r"Execution Time: ([\d.]+)", plan).group(1)))  # type: ignore[union-attr]
            (out / f"{name}.txt").write_text(plan + "\n")
            print(f"{name:40s} median {statistics.median(times):8.2f} ms")


if __name__ == "__main__":
    main()
