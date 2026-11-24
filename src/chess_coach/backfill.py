"""Fill in what older games are missing: opening names, time control and ratings.

    python -m chess_coach.backfill

Safe to run again: it only fills empty values. New games get all of this when they are saved.
"""

from __future__ import annotations

import re

import psycopg

from chess_coach import db, openings

_TAG = re.compile(r'^\[(\w+) "([^"]*)"\]', re.MULTILINE)


def _int(value: str | None) -> int | None:
    return int(value) if value and value.isdigit() and int(value) <= 4000 else None


def game_headers(pgn: str) -> dict:
    """time_control, white_elo and black_elo from the PGN tags, None where absent."""
    tags = dict(_TAG.findall(pgn))
    return {
        "time_control": tags.get("TimeControl") or None,
        "white_elo": _int(tags.get("WhiteElo")),
        "black_elo": _int(tags.get("BlackElo")),
    }


def run(conn: psycopg.Connection) -> dict:
    named = openings.backfill(conn)
    filled = 0
    rows = conn.execute(
        "SELECT id, pgn FROM games WHERE time_control IS NULL AND white_elo IS NULL"
        " AND black_elo IS NULL").fetchall()
    for game_id, pgn in rows:
        h = game_headers(pgn)
        if any(v is not None for v in h.values()):
            conn.execute(
                "UPDATE games SET time_control = %s, white_elo = %s, black_elo = %s WHERE id = %s",
                (h["time_control"], h["white_elo"], h["black_elo"], game_id))
            filled += 1
    return {"openings_named": named, "headers_filled": filled}


def main() -> None:
    with db.connect() as conn:
        print(run(conn))
        conn.commit()


if __name__ == "__main__":
    main()
