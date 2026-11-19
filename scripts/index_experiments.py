"""Measure candidate indexes on the bench DB. Creates each one, times every query, drops it.

Usage: PYTHONPATH=src python scripts/index_experiments.py
Timing = median Execution Time of 7 EXPLAIN ANALYZE runs (after one warm-up).
"""

import re
import statistics
from pathlib import Path

import psycopg
from explain import blocks
from psycopg.conninfo import conninfo_to_dict

from chess_coach import db

ROOT = Path(__file__).resolve().parents[1]

CANDIDATES = {
    "baseline (no extra index)": None,
    "games(white), games(black)": [
        "CREATE INDEX x_games_white ON games (white)",
        "CREATE INDEX x_games_black ON games (black)",
    ],
    "facts GIN jsonb_path_ops": ["CREATE INDEX x_facts_gin ON facts USING gin (facts jsonb_path_ops)"],
    "evaluations partial (blunder)": [
        "CREATE INDEX x_eval_blunder ON evaluations (move_id) WHERE classification = 'blunder'"
    ],
    "evaluations covering": [
        "CREATE INDEX x_eval_cover ON evaluations (move_id) INCLUDE (expected_points_lost, classification)"
    ],
    "moves(game_id, color, ply)": ["CREATE INDEX x_moves_gcp ON moves (game_id, color, ply)"],
}


def run_ms(conn, sql: str) -> tuple[float, str]:
    conn.execute(sql)  # warm-up
    times, plan = [], ""
    for _ in range(7):
        plan = "\n".join(r[0] for r in conn.execute(f"EXPLAIN (ANALYZE) {sql}"))
        times.append(float(re.search(r"Execution Time: ([\d.]+)", plan).group(1)))  # type: ignore[union-attr]
    return statistics.median(times), plan


def main() -> None:
    d = conninfo_to_dict(db.dsn())
    d["dbname"] = "chess_coach_bench"
    queries = blocks((ROOT / "queries" / "analytics.sql").read_text())
    with psycopg.connect(**d, autocommit=True) as conn:
        print(f"{'candidate':34s}" + "".join(f"{n[:14]:>16s}" for n in queries))
        for label, ddl in CANDIDATES.items():
            for stmt in ddl or []:
                conn.execute(stmt)
            conn.execute("ANALYZE")
            cells = []
            for sql in queries.values():
                ms, plan = run_ms(conn, sql)
                used = "*" if re.search(r"(Index (Only )?Scan using|Bitmap Index Scan on) x_", plan) else " "
                cells.append(f"{ms:14.2f}{used} ")
            print(f"{label:34s}" + "".join(cells))
            for stmt in ddl or []:
                conn.execute("DROP INDEX " + re.search(r"INDEX (\w+)", stmt).group(1))  # type: ignore[union-attr]
        print("\n* = the planner used the candidate index. Times in ms.")


if __name__ == "__main__":
    main()
