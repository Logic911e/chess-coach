from chess_coach.claims import check_claims, false_placements, truth_boards

QH5 = "r1bqkbnr/pppp1ppp/2n5/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR b KQkq - 3 3"


def _boards():
    return truth_boards(QH5, "g8f6", ["g7g6", "h5f3"])


def test_true_placements_pass():
    text = "The queen on h5 attacks the pawn on f7, and the white bishop on c4 helps."
    assert false_placements(text, _boards()) == []


def test_false_placements_are_caught():
    text = "The black knight on e4 is strong and the rook on a5 is loose."
    assert false_placements(text, _boards()) == ["black knight on e4", "rook on a5"]


def test_color_must_match():
    # There is a white bishop on c4, not a black one.
    assert false_placements("the black bishop on c4", _boards()) == ["black bishop on c4"]


def test_pieces_along_the_engine_line_count_as_true():
    # After ...g6 and Qf3 the queen stands on f3.
    assert false_placements("the queen on f3", _boards()) == []


def test_check_claims_combines_both():
    r = check_claims("Nxe5 hits the rook on h5.", _boards())
    assert r.illegal_moves == ["Nxe5"] and r.false_placements == ["rook on h5"] and r.count == 2


def test_naming_a_threat_is_allowed():
    # After ...g6 the move Qxf7 is illegal, but "g6 stops Qxf7" is a true statement
    # about the threat that existed before the move.
    from chess_coach.claims import check_claims, truth_boards

    boards = truth_boards(QH5, "g7g6", ["g7g6"])
    assert check_claims("g6 stops Qxf7.", boards).count == 0
