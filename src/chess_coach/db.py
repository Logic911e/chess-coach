"""Connection helper and a minimal migration runner.

Migrations are numbered .sql files in /migrations, applied in order, each in its own
transaction, and recorded in schema_migrations so a second run does nothing.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import psycopg

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"
_NAME = re.compile(r"^(\d{3})_[a-z0-9_]+\.sql$")


def _load_env_file() -> None:
    """Read .env from the repo root into os.environ (existing variables win)."""
    path = MIGRATIONS_DIR.parent / ".env"
    if not path.is_file():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


def dsn() -> str:
    """DATABASE_URL if set, otherwise built from the POSTGRES_* variables (see .env.example)."""
    _load_env_file()
    if url := os.environ.get("DATABASE_URL"):
        return url
    user, pw = os.environ.get("POSTGRES_USER"), os.environ.get("POSTGRES_PASSWORD")
    if not user or not pw:
        raise RuntimeError("Set DATABASE_URL, or POSTGRES_USER and POSTGRES_PASSWORD (see .env.example).")
    host = os.environ.get("POSTGRES_HOST", "127.0.0.1")
    port = os.environ.get("POSTGRES_PORT", "5433")
    name = os.environ.get("POSTGRES_DB", "chess_coach")
    return f"postgresql://{user}:{pw}@{host}:{port}/{name}"


def connect(**kwargs) -> psycopg.Connection:
    return psycopg.connect(dsn(), **kwargs)


def migration_files(directory: Path = MIGRATIONS_DIR) -> list[Path]:
    files = sorted(p for p in directory.glob("*.sql"))
    for p in files:
        if not _NAME.match(p.name):
            raise ValueError(f"Bad migration name {p.name!r}; expected 001_some_name.sql")
    numbers = [p.name[:3] for p in files]
    if len(set(numbers)) != len(numbers):
        raise ValueError("Two migrations share a number.")
    return files


def migrate(conn: psycopg.Connection, directory: Path = MIGRATIONS_DIR) -> list[str]:
    """Apply pending migrations. Returns the names applied this call."""
    with conn.transaction():
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            " version TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"
        )
        # Serialise concurrent runners for the rest of this transaction.
        conn.execute("SELECT pg_advisory_xact_lock(727274)")
        done = {r[0] for r in conn.execute("SELECT version FROM schema_migrations")}
    applied = []
    for path in migration_files(directory):
        if path.name in done:
            continue
        with conn.transaction():  # a failing file rolls back completely
            conn.execute(path.read_text())
            conn.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (path.name,))
        applied.append(path.name)
    return applied


def main() -> None:
    with connect() as conn:
        applied = migrate(conn)
    print("applied:", ", ".join(applied) if applied else "nothing (already up to date)")


if __name__ == "__main__":
    main()
