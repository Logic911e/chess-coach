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


def test_list_phrasing_is_checked_square_by_square():
    # The live miss: "two pawns hanging on e4 and h5" when h5 holds White's queen.
    text = "Nf6 leaves two pawns hanging on e4 and h5."
    assert false_placements(text, _boards()) == ["pawn on h5"]


def test_attacker_and_target_are_not_confused():
    # "the knight attacks the pawn on f7" says the PAWN is on f7. It is, so no complaint.
    text = "The knight attacks the pawn on f7."
    assert false_placements(text, _boards()) == []


def test_hypothetical_placement_is_not_flagged():
    # Three filler words between piece and "on": a suggestion, not a claim about the board.
    assert false_placements("A bishop would be better on d3.", _boards()) == []


def test_black_queen_on_h5_is_wrong():
    assert false_placements("the black queen on h5", _boards()) == ["black queen on h5"]
