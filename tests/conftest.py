import uuid

import psycopg
import pytest

from chess_coach import db


@pytest.fixture()
def pg():
    """A fresh, migrated, throwaway database per test. Skips when Postgres is unreachable."""
    try:
        admin = psycopg.connect(db.dsn(), autocommit=True, connect_timeout=2)
    except (psycopg.OperationalError, RuntimeError):
        pytest.skip("Postgres not available (docker-compose up -d)")
    name = f"chess_test_{uuid.uuid4().hex[:10]}"
    admin.execute(f'CREATE DATABASE "{name}"')
    base = psycopg.conninfo.conninfo_to_dict(db.dsn())
    base["dbname"] = name
    conn = psycopg.connect(**base)
    db.migrate(conn)
    try:
        yield conn
    finally:
        conn.close()
        admin.execute(f'DROP DATABASE "{name}" WITH (FORCE)')
        admin.close()
