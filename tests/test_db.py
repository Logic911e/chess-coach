import psycopg
import pytest

from chess_coach import db


def _game(conn, n=1):
    return conn.execute(
        "INSERT INTO games (white, black, result, pgn, pgn_hash) VALUES ('a','b','1-0','x',%s) RETURNING id",
        (f"{n:064d}",),
    ).fetchone()[0]


def _move(conn, game_id, ply=1, **over):
    row = {"color": "white" if ply % 2 else "black", "uci": "e2e4", "phase": "opening", **over}
    return conn.execute(
        "INSERT INTO moves (game_id, ply, move_number, color, san, uci, fen_before, phase)"
        " VALUES (%s,%s,1,%s,'e4',%s,'f',%s) RETURNING id",
        (game_id, ply, row["color"], row["uci"], row["phase"]),
    ).fetchone()[0]


def test_migrate_is_idempotent(pg):
    assert db.migrate(pg) == []
    versions = [r[0] for r in pg.execute("SELECT version FROM schema_migrations ORDER BY 1")]
    assert versions == [p.name for p in db.migration_files()]


def test_duplicate_pgn_hash_rejected(pg):
    _game(pg)
    with pytest.raises(psycopg.errors.UniqueViolation):
        _game(pg)


@pytest.mark.parametrize(
    "bad",
    [{"uci": "e2e9"}, {"phase": "midgame"}, {"color": "black"}],  # bad square, bad phase, wrong parity
)
def test_move_constraints(pg, bad):
    g = _game(pg)
    with pytest.raises(psycopg.errors.CheckViolation):
        _move(pg, g, ply=1, **bad)


def test_same_ply_twice_rejected(pg):
    g = _game(pg)
    _move(pg, g, ply=1)
    with pytest.raises(psycopg.errors.UniqueViolation):
        _move(pg, g, ply=1)


def test_evaluation_bounds_and_cascade(pg):
    g = _game(pg)
    m = _move(pg, g)
    ins = (
        "INSERT INTO evaluations VALUES (%s,'e2e4',10,10,%s,'best',14,'Stockfish 17')"
    )
    with pytest.raises(psycopg.errors.CheckViolation):
        pg.execute(ins, (m, 1.5))
    pg.rollback()
    g = _game(pg, 2)
    m = _move(pg, g)
    pg.execute(ins, (m, 0.0))
    pg.execute("INSERT INTO facts (move_id, facts) VALUES (%s, '{}')", (m,))
    pg.execute("DELETE FROM games WHERE id = %s", (g,))
    for table in ("moves", "evaluations", "facts"):
        assert pg.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0


def test_facts_must_be_a_json_object(pg):
    m = _move(pg, _game(pg))
    with pytest.raises(psycopg.errors.CheckViolation):
        pg.execute("INSERT INTO facts (move_id, facts) VALUES (%s, '[1]')", (m,))


def test_bad_migration_name_rejected(tmp_path):
    (tmp_path / "1_bad.sql").write_text("SELECT 1")
    with pytest.raises(ValueError):
        db.migration_files(tmp_path)
