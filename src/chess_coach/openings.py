"""Opening names for stored games, from the open Lichess opening list (CC0).

The list (data/openings.tsv) maps move sequences to an ECO code and a name. A game is matched by
position, not by move order, so a transposition still finds its opening, and the deepest position
within the first MAX_PLIES plies that is on the list names the game.
"""

from __future__ import annotations

import csv
import functools
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import chess
import psycopg

DATA = Path(__file__).parent / "data" / "openings.tsv"
MAX_PLIES = 40
_MOVE_NUMBER = re.compile(r"\d+\.(?:\.\.)?")


@dataclass(frozen=True)
class Opening:
    eco: str
    name: str

    @property
    def family(self) -> str:
        return family(self.name)


def family(name: str) -> str:
    """"Sicilian Defense: Closed" -> "Sicilian Defense": the name without its variation."""
    return name.split(":")[0].strip()


@functools.lru_cache(maxsize=1)
def _index() -> dict[str, tuple[str, str, int]]:
    """EPD of the position after each listed line -> (eco, name, plies). Where several lines end
    on one position the longer, more specific line wins."""
    index: dict[str, tuple[str, str, int]] = {}
    with DATA.open(newline="") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            board = chess.Board()
            plies = 0
            try:
                for token in _MOVE_NUMBER.sub(" ", row["pgn"]).split():
                    board.push_san(token)
                    plies += 1
            except ValueError:  # a row this version of the list cannot replay: skip it
                continue
            key = board.epd()
            if key not in index or plies > index[key][2]:
                index[key] = (row["eco"], row["name"], plies)
    return index


def classify(uci_moves: Iterable[str]) -> Opening | None:
    """The opening a game belongs to, from its moves in UCI, or None if it leaves the book at once."""
    index = _index()
    board = chess.Board()
    found: Opening | None = None
    for n, uci in enumerate(uci_moves, 1):
        if n > MAX_PLIES:
            break
        try:
            board.push_uci(uci)
        except ValueError:
            break
        hit = index.get(board.epd())
        if hit:
            found = Opening(hit[0], hit[1])
    return found


def backfill(conn: psycopg.Connection) -> int:
    """Name the stored games that have no opening yet. Returns how many were named."""
    ids = [r[0] for r in conn.execute(
        "SELECT id FROM games WHERE opening IS NULL OR eco IS NULL ORDER BY id")]
    named = 0
    for game_id in ids:
        ucis = [r[0] for r in conn.execute(
            "SELECT uci FROM moves WHERE game_id = %s ORDER BY ply", (game_id,))]
        found = classify(ucis)
        if found:
            conn.execute(
                "UPDATE games SET eco = COALESCE(eco, %s), opening = COALESCE(opening, %s)"
                " WHERE id = %s", (found.eco, found.name, game_id))
            named += 1
    return named
