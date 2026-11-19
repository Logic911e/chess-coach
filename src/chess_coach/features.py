"""Checkable position facts for a chess coach.

Everything in here is computed with python-chess. None of it is guessed by a
language model. The coach's language model should be given these facts (plus the
engine's evaluation) and told to explain only those facts.

Known limits, on purpose, to keep this a readable first version:
- "Hanging" ignores pins on the attackers and does not do a full exchange
  sequence (static exchange evaluation). It checks: attacked and undefended,
  attacked by a cheaper piece, or attacked more times than defended.
- Forks only look at the moved piece's immediate targets.
- Pins are absolute pins only (a piece pinned against its own king).
"""

from __future__ import annotations

import math
import re

import chess

PIECE_VALUES = {
    chess.PAWN: 1,
    chess.KNIGHT: 3,
    chess.BISHOP: 3,
    chess.ROOK: 5,
    chess.QUEEN: 9,
    chess.KING: 0,
}

MATE_CP = 10_000  # clamp for mate scores; convert engine mate scores to this

# Chess.com publishes expected-points-lost cutoffs for its move labels. They are
# a starting point here, to tune against your own data.
LABEL_UPPER_LIMITS = [
    ("excellent", 0.02),
    ("good", 0.05),
    ("inaccuracy", 0.10),
    ("mistake", 0.20),
    ("blunder", 1.00),
]

WHITE_START_MINORS = {chess.B1, chess.G1, chess.C1, chess.F1}
BLACK_START_MINORS = {chess.B8, chess.G8, chess.C8, chess.F8}


# ----------------------------------------------------------------- helpers


def _name(square: int) -> str:
    return chess.square_name(square)


def _piece_name(piece: chess.Piece) -> str:
    return chess.piece_name(piece.piece_type)


def _color_name(color: bool) -> str:
    return "white" if color == chess.WHITE else "black"


def _attacker_value(board: chess.Board, square: int) -> int:
    piece = board.piece_at(square)
    # A king can only take an undefended piece, so never count it as "cheap".
    return 1000 if piece.piece_type == chess.KING else PIECE_VALUES[piece.piece_type]


def material(board: chess.Board, color: bool) -> int:
    return sum(
        PIECE_VALUES[p.piece_type] for p in board.piece_map().values() if p.color == color
    )


def material_balance(board: chess.Board) -> int:
    """White minus black, in pawns."""
    return material(board, chess.WHITE) - material(board, chess.BLACK)


# --------------------------------------------------------- position features


def hanging_pieces(board: chess.Board, color: bool) -> list[dict]:
    """Pieces of `color` that the opponent can win, judged statically."""
    out = []
    for square, piece in board.piece_map().items():
        if piece.color != color or piece.piece_type == chess.KING:
            continue
        attackers = board.attackers(not color, square)
        if not attackers:
            continue
        defenders = board.attackers(color, square)
        cheapest = min(_attacker_value(board, a) for a in attackers)
        if not defenders:
            reason = "attacked and undefended"
        elif cheapest < PIECE_VALUES[piece.piece_type]:
            reason = "attacked by a cheaper piece"
        elif len(attackers) > len(defenders):
            reason = "attacked more times than defended"
        else:
            continue
        out.append({"square": _name(square), "piece": _piece_name(piece), "reason": reason})
    return out


def pins(board: chess.Board, color: bool) -> list[dict]:
    """Absolute pins against the king of `color`."""
    king = board.king(color)
    if king is None:
        return []
    out = []
    for square, piece in board.piece_map().items():
        if piece.color != color or square == king:
            continue
        if not board.is_pinned(color, square):
            continue
        ray = board.pin(color, square)
        pinner = next(
            (s for s in ray if board.piece_at(s) and board.piece_at(s).color != color),
            None,
        )
        entry = {"square": _name(square), "piece": _piece_name(piece)}
        if pinner is not None:
            entry["pinned_by"] = f"{_piece_name(board.piece_at(pinner))} on {_name(pinner)}"
        out.append(entry)
    return out


def passed_pawns(board: chess.Board, color: bool) -> list[str]:
    """Pawns of `color` with no enemy pawn ahead on their file or adjacent files."""
    enemy_pawns = board.pieces(chess.PAWN, not color)
    out = []
    for square in board.pieces(chess.PAWN, color):
        file, rank = chess.square_file(square), chess.square_rank(square)
        blocked = False
        for enemy in enemy_pawns:
            ahead = (
                chess.square_rank(enemy) > rank
                if color == chess.WHITE
                else chess.square_rank(enemy) < rank
            )
            if ahead and abs(chess.square_file(enemy) - file) <= 1:
                blocked = True
                break
        if not blocked:
            out.append(_name(square))
    return sorted(out)


def king_safety(board: chess.Board, color: bool) -> dict:
    king = board.king(color)
    if king is None:
        return {}
    zone = set(board.attacks(king)) | {king}
    attackers: set[int] = set()
    for square in zone:
        attackers.update(board.attackers(not color, square))
    kfile, krank = chess.square_file(king), chess.square_rank(king)
    step = 1 if color == chess.WHITE else -1
    shield = 0
    for pawn in board.pieces(chess.PAWN, color):
        pf, pr = chess.square_file(pawn), chess.square_rank(pawn)
        if abs(pf - kfile) <= 1 and pr - krank in (step, 2 * step):
            shield += 1
    own_pawn_on_king_file = any(
        chess.square_file(p) == kfile for p in board.pieces(chess.PAWN, color)
    )
    return {
        "king_square": _name(king),
        "enemy_pieces_attacking_king_zone": len(attackers),
        "pawn_shield": shield,
        "king_file_open": not own_pawn_on_king_file,
        "has_castling_rights": board.has_castling_rights(color),
    }


def undeveloped_minor_pieces(board: chess.Board, color: bool) -> int:
    """Minor pieces still on their starting squares (only meaningful early on)."""
    starts = WHITE_START_MINORS if color == chess.WHITE else BLACK_START_MINORS
    count = 0
    for square in starts:
        piece = board.piece_at(square)
        if piece and piece.color == color and piece.piece_type in (chess.KNIGHT, chess.BISHOP):
            count += 1
    return count


def side_features(board: chess.Board, color: bool) -> dict:
    return {
        "hanging_pieces": hanging_pieces(board, color),
        "pinned_pieces": pins(board, color),
        "passed_pawns": passed_pawns(board, color),
        "king_safety": king_safety(board, color),
        "undeveloped_minor_pieces": undeveloped_minor_pieces(board, color),
    }


# ------------------------------------------------------------ move features


def forks(after: chess.Board, move: chess.Move, mover: bool) -> list[dict]:
    """Targets attacked by the moved piece. Two or more targets is a fork."""
    piece = after.piece_at(move.to_square)
    if piece is None:
        return []
    targets = []
    for square in after.attacks(move.to_square):
        target = after.piece_at(square)
        if target is None or target.color == mover:
            continue
        if target.piece_type == chess.KING:
            targets.append({"square": _name(square), "piece": "king", "why": "check"})
        elif PIECE_VALUES[target.piece_type] > PIECE_VALUES[piece.piece_type]:
            targets.append(
                {"square": _name(square), "piece": _piece_name(target), "why": "worth more"}
            )
        elif not after.attackers(not mover, square):
            targets.append(
                {"square": _name(square), "piece": _piece_name(target), "why": "undefended"}
            )
    if len(targets) < 2:
        return []
    return targets


def move_effects(board: chess.Board, move: chess.Move) -> dict:
    """What a single move does, as checkable facts."""
    mover = board.turn
    piece = board.piece_at(move.from_square)
    if board.is_en_passant(move):
        captured = "pawn"
    else:
        cap = board.piece_at(move.to_square)
        captured = _piece_name(cap) if cap else None
    before_hanging = hanging_pieces(board, mover)
    info = {
        "san": board.san(move),
        "uci": move.uci(),
        "piece": _piece_name(piece),
        "from": _name(move.from_square),
        "to": _name(move.to_square),
        "captures": captured,
        "castling": board.is_castling(move),
        "promotion": chess.piece_name(move.promotion) if move.promotion else None,
    }
    after = board.copy(stack=False)
    after.push(move)
    info["gives_check"] = after.is_check()
    info["checkmate"] = after.is_checkmate()
    info["forks"] = forks(after, move, mover)
    after_hanging = hanging_pieces(after, mover)
    info["leaves_own_piece_hanging"] = [h for h in after_hanging if h not in before_hanging]
    # Threats that existed before the move and are still there: the player ignored them.
    info["ignored_threats"] = [h for h in after_hanging if h in before_hanging]
    info["enemy_pieces_hanging_after"] = hanging_pieces(after, not mover)
    return info


def line_summary(board: chess.Board, line_uci: list[str]) -> dict:
    """Material change for the side to move along an engine line."""
    mover = board.turn
    b = board.copy(stack=False)
    start = material(b, mover) - material(b, not mover)
    moves = []
    for uci in line_uci:
        move = chess.Move.from_uci(uci)
        if move not in b.legal_moves:
            raise ValueError(f"illegal move in line: {uci}")
        moves.append(move)
        b.push(move)
    end = material(b, mover) - material(b, not mover)
    return {
        "line_san": board.variation_san(moves),
        "material_change_for_mover": end - start,
        "ends_in_checkmate": b.is_checkmate(),
    }


# ------------------------------------------------------ engine score helpers


def mate_to_cp(mate_in: int) -> int:
    """Turn an engine 'mate in N' (positive = mover mates) into a clamped cp."""
    return MATE_CP if mate_in > 0 else -MATE_CP


def win_prob(cp: float, k: float = 0.004) -> float:
    """Winning chances from a centipawn score. k is a placeholder: fit your own,
    and make it depend on the player's rating."""
    cp = max(-MATE_CP, min(MATE_CP, cp))
    return 1.0 / (1.0 + math.exp(-k * cp))


def expected_points_lost(cp_best: float, cp_played: float, k: float = 0.004) -> float:
    """Both scores from the mover's point of view."""
    return max(0.0, win_prob(cp_best, k) - win_prob(cp_played, k))


def classify(loss: float) -> str:
    if loss <= 1e-9:
        return "best"
    for label, upper in LABEL_UPPER_LIMITS:
        if loss <= upper:
            return label
    return "blunder"


# ------------------------------------------------------------- main entry


def build_facts(
    fen: str,
    played_uci: str,
    best_uci: str,
    cp_best: float,
    cp_played: float,
    best_line_uci: list[str] | None = None,
    k: float = 0.004,
) -> dict:
    """Everything the language model is allowed to talk about, for one move."""
    board = chess.Board(fen)
    played = chess.Move.from_uci(played_uci)
    best = chess.Move.from_uci(best_uci)
    for move in (played, best):
        if move not in board.legal_moves:
            raise ValueError(f"illegal move for this position: {move.uci()}")
    loss = expected_points_lost(cp_best, cp_played, k)
    facts = {
        "fen": fen,
        "side_to_move": _color_name(board.turn),
        "material_balance_white_minus_black": material_balance(board),
        "expected_points_lost": round(loss, 3),
        "classification": classify(loss),
        "played": move_effects(board, played),
        "position": {
            "white": side_features(board, chess.WHITE),
            "black": side_features(board, chess.BLACK),
        },
    }
    if best != played:
        facts["best"] = move_effects(board, best)
    if best_line_uci:
        facts["best_line"] = line_summary(board, best_line_uci)
    return facts


# ------------------------------------------------- checking the model's claims

# Matches SAN-looking tokens. Bare pawn pushes such as "e4" are skipped on
# purpose, because "the e4 square" would be a false alarm.
_SAN = re.compile(r"\b(?:O-O-O|O-O|[KQRBN][a-h]?[1-8]?x?[a-h][1-8]|[a-h]x[a-h][1-8](?:=[QRBN])?)[+#]?")


def find_illegal_moves(text: str, boards: list[chess.Board]) -> list[str]:
    """Moves named in `text` that are legal in none of the given positions.

    Pass the starting position and the positions along the engine line, since a
    coach explanation may mention moves from deeper in the line.
    """
    bad = []
    for token in _SAN.findall(text):
        legal_somewhere = False
        for board in boards:
            try:
                board.parse_san(token)
                legal_somewhere = True
                break
            except ValueError:
                continue
        if not legal_somewhere:
            bad.append(token)
    return bad


def positions_along_line(board: chess.Board, line_uci: list[str]) -> list[chess.Board]:
    boards = [board.copy(stack=False)]
    b = board.copy(stack=False)
    for uci in line_uci:
        b.push(chess.Move.from_uci(uci))
        boards.append(b.copy(stack=False))
    return boards
