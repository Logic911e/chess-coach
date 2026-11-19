"""Tests on positions where the right answer is known by hand."""

import chess
import pytest

from chess_coach import features as cf

# 1.e4 e5 2.Qh5 Nc6 3.Bc4 Nf6?? 4.Qxf7# (scholar's mate)
SCHOLAR_FEN = "r1bqkb1r/pppp1ppp/2n2n2/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR w KQkq - 4 4"


def test_checkmate_and_capture_detected():
    board = chess.Board(SCHOLAR_FEN)
    info = cf.move_effects(board, chess.Move.from_uci("h5f7"))
    assert info["san"] == "Qxf7#"
    assert info["captures"] == "pawn"
    assert info["gives_check"] and info["checkmate"]


def test_knight_fork_of_king_and_queen():
    # Nc7+ attacks the king on e8 and the undefended queen on a8.
    board = chess.Board("q3k3/8/8/1N6/8/8/8/4K3 w - - 0 1")
    info = cf.move_effects(board, chess.Move.from_uci("b5c7"))
    squares = {t["square"] for t in info["forks"]}
    assert squares == {"e8", "a8"}


def test_pin_found_with_pinner():
    # White rook on e1 pins the black knight on e5 to the king on e8.
    board = chess.Board("4k3/8/8/4n3/8/8/8/4R1K1 b - - 0 1")
    result = cf.pins(board, chess.BLACK)
    assert len(result) == 1
    assert result[0]["square"] == "e5"
    assert "rook on e1" in result[0]["pinned_by"]


def test_hanging_piece_found():
    # The black bishop on d5 is attacked by the knight on c3 and has no defender.
    board = chess.Board("4k3/8/8/3b4/8/2N5/8/4K3 w - - 0 1")
    hanging = cf.hanging_pieces(board, chess.BLACK)
    assert [h["square"] for h in hanging] == ["d5"]
    assert cf.hanging_pieces(board, chess.WHITE) == []


def test_move_that_leaves_piece_hanging():
    # The white queen steps to d5, where the black pawn on e6 can capture it.
    board = chess.Board("4k3/8/4p3/8/8/8/8/3QK3 w - - 0 1")
    info = cf.move_effects(board, chess.Move.from_uci("d1d5"))
    assert [h["square"] for h in info["leaves_own_piece_hanging"]] == ["d5"]


def test_passed_pawn():
    board = chess.Board("4k3/8/8/4P3/8/8/8/4K3 w - - 0 1")
    assert cf.passed_pawns(board, chess.WHITE) == ["e5"]
    assert cf.passed_pawns(board, chess.BLACK) == []


def test_pawn_blocked_is_not_passed():
    board = chess.Board("4k3/4p3/8/4P3/8/8/8/4K3 w - - 0 1")
    assert cf.passed_pawns(board, chess.WHITE) == []


def test_start_position_is_balanced_and_undeveloped():
    board = chess.Board()
    assert cf.material_balance(board) == 0
    assert cf.undeveloped_minor_pieces(board, chess.WHITE) == 4
    assert cf.hanging_pieces(board, chess.WHITE) == []


def test_classification_boundaries():
    assert cf.classify(0.0) == "best"
    assert cf.classify(0.01) == "excellent"
    assert cf.classify(0.04) == "good"
    assert cf.classify(0.08) == "inaccuracy"
    assert cf.classify(0.15) == "mistake"
    assert cf.classify(0.35) == "blunder"


def test_throwing_away_a_win_is_a_blunder():
    loss = cf.expected_points_lost(cp_best=500, cp_played=-300)
    assert cf.classify(loss) == "blunder"


def test_build_facts_end_to_end():
    facts = cf.build_facts(
        SCHOLAR_FEN,
        played_uci="g1f3",
        best_uci="h5f7",
        cp_best=cf.mate_to_cp(1),
        cp_played=50,
        best_line_uci=["h5f7"],
    )
    assert facts["classification"] == "blunder"
    assert facts["best"]["checkmate"] is True
    assert facts["best_line"]["ends_in_checkmate"] is True
    assert facts["side_to_move"] == "white"


def test_build_facts_rejects_illegal_move():
    with pytest.raises(ValueError):
        cf.build_facts(SCHOLAR_FEN, "a1a8", "h5f7", 0, 0)


def test_find_illegal_moves_flags_invented_move():
    board = chess.Board(SCHOLAR_FEN)
    boards = cf.positions_along_line(board, ["h5f7"])
    assert cf.find_illegal_moves("The best move is Qxf7#.", boards) == []
    # The queen on h5 cannot capture on g7 here, so this one is invented.
    assert cf.find_illegal_moves("Better is Qxg7.", boards) == ["Qxg7"]


# After 1.e4 e5 2.Qh5 Nc6 3.Bc4 it is Black's move, and f7 is attacked twice
# (queen and bishop) but defended once (king).
AFTER_BC4_FEN = "r1bqkbnr/pppp1ppp/2n5/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR b KQkq - 3 3"


def test_outnumbered_pawn_counts_as_threatened():
    board = chess.Board(AFTER_BC4_FEN)
    squares = [h["square"] for h in cf.hanging_pieces(board, chess.BLACK)]
    assert squares == ["f7"]


def test_ignoring_the_threat_is_reported():
    board = chess.Board(AFTER_BC4_FEN)
    ignored = cf.move_effects(board, chess.Move.from_uci("g8f6"))["ignored_threats"]
    assert [h["square"] for h in ignored] == ["f7"]


def test_blocking_the_threat_is_not_ignoring_it():
    board = chess.Board(AFTER_BC4_FEN)
    # ...g6 blocks the queen's diagonal, so f7 is attacked once and defended once.
    ignored = cf.move_effects(board, chess.Move.from_uci("g7g6"))["ignored_threats"]
    assert ignored == []
