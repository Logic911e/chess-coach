"""Create the benchmark database (chess_coach_bench), migrate it and load synthetic data.

Usage: PYTHONPATH=src python scripts/seed_synthetic.py
Drops and recreates the benchmark database each run. Never touches the real one.
"""

from pathlib import Path

import psycopg
from psycopg.conninfo import conninfo_to_dict

from chess_coach import db

BENCH = "chess_coach_bench"


def main() -> None:
    base = conninfo_to_dict(db.dsn())
    with psycopg.connect(**base, autocommit=True) as admin:
        admin.execute(f'DROP DATABASE IF EXISTS "{BENCH}" WITH (FORCE)')
        admin.execute(f'CREATE DATABASE "{BENCH}"')
    base["dbname"] = BENCH
    with psycopg.connect(**base, autocommit=True) as conn:
        print("migrations:", db.migrate(conn))
        conn.execute((Path(__file__).with_name("seed_synthetic.sql")).read_text())
        for table in ("games", "moves", "evaluations", "facts"):
            print(table, conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0])


if __name__ == "__main__":
    main()
