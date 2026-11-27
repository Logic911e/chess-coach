"""Stats over a player's stored games: record, accuracy, phases, pieces and openings.

Everything is computed in SQL from what the importer already stores (engine scores per move, the
phase, the result, the opening). Numbers are compared with the player's OWN average, not with other
players: there is no reference population here.

"Loss" is the expected points lost per move (0 to 1, a win-chance drop). "Accuracy" turns that into
a 0-100 scale with the published Lichess curve, 103.1668 * exp(-0.04354 * win% lost) - 3.1669,
fed with this app's own win-chance model. It is an estimate on this app's scale, and the real
Lichess and Chess.com accuracy figures will differ.
"""

from __future__ import annotations

import psycopg

from chess_coach.openings import family  # noqa: F401  (re-exported for callers)

ACCURACY = "greatest(0, least(100, 103.1668 * exp(-4.354 * loss) - 3.1669))"

_MINE = """
WITH mine AS (
    SELECT g.id AS game_id, g.played_on, g.result, g.eco, g.opening, g.time_control,
           CASE WHEN lower(g.white) = lower(%(p)s) THEN 'white' ELSE 'black' END AS side,
           (g.result = '1-0' AND lower(g.white) = lower(%(p)s))
             OR (g.result = '0-1' AND lower(g.black) = lower(%(p)s)) AS won,
           g.result = '1/2-1/2' AS drawn,
           (g.result = '0-1' AND lower(g.white) = lower(%(p)s))
             OR (g.result = '1-0' AND lower(g.black) = lower(%(p)s)) AS lost
    FROM games g
    WHERE lower(g.white) = lower(%(p)s) OR lower(g.black) = lower(%(p)s)
),
my_moves AS (
    SELECT mi.game_id, mi.side, m.ply, m.phase, m.san,
           e.expected_points_lost::float AS loss, e.classification,
           {accuracy} AS acc,
           CASE WHEN m.san LIKE 'O-O%%' OR left(m.san, 1) = 'K' THEN 'king'
                WHEN left(m.san, 1) = 'Q' THEN 'queen' WHEN left(m.san, 1) = 'R' THEN 'rook'
                WHEN left(m.san, 1) = 'B' THEN 'bishop' WHEN left(m.san, 1) = 'N' THEN 'knight'
                ELSE 'pawn' END AS piece
    FROM mine mi
    JOIN moves m ON m.game_id = mi.game_id AND m.color = mi.side
    JOIN evaluations e ON e.move_id = m.id
)
""".replace("{accuracy}", ACCURACY.replace("loss", "e.expected_points_lost::float"))

ERRORS = "classification IN ('mistake', 'blunder')"
PHASE_ORDER = ("opening", "middlegame", "endgame")
PIECE_ORDER = ("pawn", "knight", "bishop", "rook", "queen", "king")
FEW_MOVES = 30  # a group with fewer moves than this is shown, but marked as too small to read
FEW_GAMES = 5


def time_class(time_control: str | None) -> str:
    """bullet, blitz, rapid, classical or unknown, by the Lichess rule: base seconds plus 40 moves
    of increment."""
    if not time_control or "/" in time_control or time_control == "-":
        return "unknown"
    try:
        base, _, inc = time_control.partition("+")
        total = int(base) + 40 * int(inc or 0)
    except ValueError:
        return "unknown"
    if total <= 29:
        return "ultrabullet"
    return ("bullet" if total <= 179 else "blitz" if total <= 479
            else "rapid" if total <= 1499 else "classical")


FAST_SHARE = 0.02     # a move that took under 2% of the starting time
SLOW_SHARE = 0.08     # a move that took over 8% of it (1.2 s and 4.8 s in a 1-minute game)
TROUBLE_SHARE = 0.10  # under a tenth of the starting time left

_TIMED = r"""
, timed AS (
    SELECT mm.game_id, mm.phase, mm.loss, mm.classification, m.clock_ms,
           mi.time_control ~ '^[0-9]+(\+[0-9]+)?$' AS plain,
           lag(m.clock_ms) OVER (PARTITION BY mm.game_id ORDER BY mm.ply) AS prev_ms
    FROM my_moves mm
    JOIN mine mi ON mi.game_id = mm.game_id
    JOIN moves m ON m.game_id = mm.game_id AND m.ply = mm.ply
    WHERE m.clock_ms IS NOT NULL
),
spent AS (
    SELECT t.*, mi.time_control,
           CASE WHEN plain THEN split_part(mi.time_control, '+', 1)::int * 1000 END AS base_ms,
           CASE WHEN plain THEN coalesce(nullif(split_part(mi.time_control, '+', 2), '')::int, 0)
                     * 1000 END AS inc_ms
    FROM timed t JOIN mine mi ON mi.game_id = t.game_id
)
"""


def _time_section(conn: psycopg.Connection, player: str) -> dict | None:
    """How the player's time use relates to the quality of their moves, from the clock times
    stored with each move. None when no game has them."""
    base = _MINE.rstrip().rstrip(")") + ")" + _TIMED
    sql = base + f"""
        SELECT CASE WHEN spent_ms < {FAST_SHARE} * base_ms THEN 'fast'
                    WHEN spent_ms <= {SLOW_SHARE} * base_ms THEN 'medium' ELSE 'slow' END AS bucket,
               CASE WHEN clock_ms < {TROUBLE_SHARE} * base_ms THEN 1 ELSE 0 END AS trouble,
               phase, loss, classification, game_id, spent_ms
        FROM (SELECT *, greatest(0, prev_ms - clock_ms + inc_ms) AS spent_ms FROM spent
              WHERE prev_ms IS NOT NULL AND base_ms IS NOT NULL) x"""
    rows = conn.execute(sql, {"p": player}).fetchall()
    if not rows:
        return None

    def agg(sel) -> dict:
        r = [x for x in rows if sel(x)]
        n = len(r)
        errs = sum(1 for x in r if x[4] in ("mistake", "blunder"))
        return {"moves": n, "avg_loss": _round(sum(x[3] for x in r) / n) if n else None,
                "errors_per_100": _round(100 * errs / n, 1) if n else None,
                "small": n < FEW_MOVES}

    by_time = [{"key": k, **agg(lambda x, k=k: x[0] == k)} for k in ("fast", "medium", "slow")]
    phases = []
    for ph in PHASE_ORDER:
        sp = [x[6] for x in rows if x[2] == ph]
        if sp:
            phases.append({"key": ph, "moves": len(sp), "avg_seconds": round(sum(sp) / len(sp) / 1000, 1)})
    return {
        "games": len({x[5] for x in rows}), "moves": len(rows), "by_time": by_time,
        "trouble": agg(lambda x: x[1] == 1), "not_trouble": agg(lambda x: x[1] == 0),
        "phases": phases,
        "thresholds": {"fast_share": FAST_SHARE, "slow_share": SLOW_SHARE,
                       "trouble_share": TROUBLE_SHARE},
    }


def _round(x: float | None, places: int = 4) -> float | None:
    return None if x is None else round(float(x), places)


def build_stats(conn: psycopg.Connection, player: str) -> dict | None:
    """All the stats for one player, or None if they have no stored games."""
    args = {"p": player}
    q = lambda sql: conn.execute(_MINE + sql, args).fetchall()

    games = q("""SELECT count(*), count(*) FILTER (WHERE won), count(*) FILTER (WHERE drawn),
                        count(*) FILTER (WHERE lost), min(played_on), max(played_on) FROM mine""")[0]
    if not games[0]:
        return None
    moves = q(f"""SELECT count(*), avg(loss), avg(acc), count(*) FILTER (WHERE {ERRORS})
                  FROM my_moves""")[0]
    n_moves, avg_loss = moves[0], moves[1] or 0.0
    overall = {
        "games": games[0], "wins": games[1], "draws": games[2], "losses": games[3],
        "first_game": str(games[4]) if games[4] else None,
        "last_game": str(games[5]) if games[5] else None,
        "moves": n_moves, "avg_loss": _round(avg_loss), "accuracy": _round(moves[2], 1),
        "errors_per_100": _round(100 * moves[3] / n_moves, 1) if n_moves else None,
    }

    def ratio(x: float | None) -> float | None:
        return _round(x / avg_loss, 3) if x is not None and avg_loss else None

    per_game = q(f"""
        SELECT mi.game_id, mi.played_on, mi.side, mi.won, mi.drawn, mi.lost, mi.opening,
               mi.time_control, count(*), avg(mm.loss), avg(mm.acc),
               count(*) FILTER (WHERE mm.{ERRORS})
        FROM mine mi JOIN my_moves mm ON mm.game_id = mi.game_id
        GROUP BY mi.game_id, mi.played_on, mi.side, mi.won, mi.drawn, mi.lost, mi.opening,
                 mi.time_control
        ORDER BY mi.played_on NULLS FIRST, mi.game_id""")
    trend = [{
        "game_id": r[0], "date": str(r[1]) if r[1] else None, "side": r[2],
        "result": "win" if r[3] else "draw" if r[4] else "loss" if r[5] else "unfinished",
        "opening": r[6], "time_class": time_class(r[7]), "moves": r[8],
        "avg_loss": _round(r[9]), "accuracy": _round(r[10], 1), "errors": r[11],
    } for r in per_game]
    classes: dict[str, int] = {}
    for t in trend:
        classes[t["time_class"]] = classes.get(t["time_class"], 0) + 1

    def grouped(column: str, order: tuple[str, ...]) -> list[dict]:
        rows = {r[0]: r for r in q(f"""
            SELECT {column}, count(*), avg(loss), avg(acc), count(*) FILTER (WHERE {ERRORS})
            FROM my_moves GROUP BY 1""")}
        return [{
            "key": k, "moves": rows[k][1], "avg_loss": _round(rows[k][2]),
            "accuracy": _round(rows[k][3], 1),
            "errors_per_100": _round(100 * rows[k][4] / rows[k][1], 1),
            "ratio": ratio(rows[k][2]), "small": rows[k][1] < FEW_MOVES,
        } for k in order if k in rows]

    named = q("""SELECT side, split_part(opening, ':', 1) AS fam, min(eco), count(*),
                        count(*) FILTER (WHERE won), count(*) FILTER (WHERE drawn),
                        count(*) FILTER (WHERE lost)
                 FROM mine WHERE opening IS NOT NULL GROUP BY side, fam""")
    opening_loss = {(r[0], r[1]): r[2] for r in q("""
        SELECT mm.side, split_part(mi.opening, ':', 1), avg(mm.loss)
        FROM mine mi JOIN my_moves mm ON mm.game_id = mi.game_id
        WHERE mi.opening IS NOT NULL AND mm.phase = 'opening' GROUP BY 1, 2""")}
    openings: dict[str, list[dict]] = {"white": [], "black": []}
    for side, fam, eco, n, w, d, lo in sorted(named, key=lambda r: (-r[3], r[1])):
        openings[side].append({
            "name": fam.strip(), "eco": eco, "games": n, "wins": w, "draws": d, "losses": lo,
            "opening_loss": _round(opening_loss.get((side, fam))), "small": n < FEW_GAMES,
        })
    unnamed = q("SELECT count(*) FROM mine WHERE opening IS NULL")[0][0]

    return {
        "player": player, "overview": overall, "time_classes": classes, "trend": trend,
        "phases": grouped("phase", PHASE_ORDER), "pieces": grouped("piece", PIECE_ORDER),
        "openings": {side: rows[:10] for side, rows in openings.items()}, "unnamed_games": unnamed,
        "time": _time_section(conn, player),
        "notes": {
            "compared_with": "your own average, not other players",
            "accuracy": "an estimate on this app's scale; Lichess and Chess.com figures differ",
        },
    }
