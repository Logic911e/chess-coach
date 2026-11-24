"""The tactical fact check. Each false case below is a real mistake the 7B model made."""

from chess_coach import features as cf
from chess_coach.factcheck import find_false_claims

QH5 = "r1bqkbnr/pppp1ppp/2n5/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR b KQkq - 3 3"
FORK = "3q3k/8/8/6N1/8/8/8/4K3 w - - 0 1"
WINQ = "rnb1kbnr/pppp1ppp/8/4p3/4P2q/5N2/PPPP1PPP/RNBQKB1R w KQkq - 0 1"
HUNG = "rnbqkbnr/ppp1pppp/8/3p4/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2"
BACKRANK = "6k1/5ppp/8/8/8/8/8/R3K3 w - - 0 1"


def _facts(fen, played, best, cp_best=0, cp_played=0, line=None):
    return cf.build_facts(fen, played, best, cp_best, cp_played, best_line_uci=line or [best])


def problems(text, facts, line=None):
    return [f.problem for f in find_false_claims(text, facts, line)]


def test_true_claims_are_not_flagged():
    facts = _facts(QH5, "g8f6", "g7g6", 20, -700, ["g7g6", "h5f3"])
    text = ("The black knight on f6 attacks the white queen on h5 and the white pawn on e4. "
            "The white queen on h5 is attacked and undefended.")
    assert problems(text, facts, ["g7g6", "h5f3"]) == []


def test_pronoun_subject_is_resolved_to_the_moved_piece():
    facts = _facts(QH5, "g8f6", "g7g6", 20, -700, ["g7g6", "h5f3"])
    assert problems("It attacks the white queen on h5.", facts) == []
    bad = problems("It attacks the white rook on a1.", facts)
    assert bad == ["the black knight on f6 does not attack the white rook on a1"]


def test_defended_knight_called_undefended_is_flagged():
    facts = _facts(WINQ, "d2d3", "f3h4", 700, -100, ["f3h4"])
    text = "By moving the pawn to d3, the white knight on f3 becomes undefended."
    assert problems(text, facts) == ["the white knight on f3 is defended"]


def test_defended_pawn_called_hanging_is_flagged():
    facts = _facts(HUNG, "d1g4", "e4d5", 40, -600, ["e4d5"])
    text = "The engine's best move is exd5, capturing the black pawn on d5, which is also attacked and undefended."
    assert problems(text, facts) == ["the black pawn on d5 is not hanging"]


def test_a_fork_move_does_not_capture_the_queen():
    facts = _facts(FORK, "e1e2", "g5f7", 900, 0, ["g5f7", "h8g8", "f7d8"])
    line = ["g5f7", "h8g8", "f7d8"]
    text = "The engine's best move, Nf7+, gives check and captures the black queen."
    assert problems(text, facts, line) == ["Nf7+ does not capture a queen"]
    assert problems("Nf7+ gives check and forks the king and queen.", facts, line) == []


def test_material_shift_must_match_the_engine_line():
    line = ["g5f7", "h8g8", "f7d8"]
    facts = _facts(FORK, "e1e2", "g5f7", 900, 0, line)
    change = facts["best_line"]["material_change_for_mover"]
    ok = f"Along the engine's best line, material shifts by {change} points in white's favour."
    assert problems(ok, facts, line) == []
    wrong = "The engine's best line shifts material by 12 points in white's favour."
    assert len(problems(wrong, facts, line)) == 1


def test_checkmate_claim_is_verified():
    facts = _facts(BACKRANK, "e1d2", "a1a8", 9000, 0, ["a1a8"])
    assert problems("Ra8# is checkmate.", facts) == []
    assert problems("The engine's best move, Ra8#, checkmates Black.", facts) == []
    assert problems("Kd2 is checkmate.", facts) == ["Kd2 is not checkmate"]


def test_missed_own_mate_is_not_flagged_as_a_threat():
    # "the threat of Ra8#" is White's own missed mate, not a reply; the move is legal for White
    facts = _facts(BACKRANK, "e1d2", "a1a8", 9000, 0, ["a1a8"])
    assert problems("This move fails to address the threat of Ra8#.", facts) == []


def test_move_rating_must_agree_with_the_engine():
    facts = _facts(QH5, "g8f6", "g7g6", 20, -700, ["g7g6"])
    assert problems("Nf6 was a blunder.", facts) == []
    assert problems("Nf6 was an excellent move.", facts) == ["the engine rates Nf6 as blunder"]


def test_strategy_talk_and_unreadable_text_are_ignored():
    facts = _facts(QH5, "g8f6", "g7g6", 20, -700, ["g7g6"])
    assert problems("It improves control of the centre and keeps the position flexible.", facts) == []
    assert problems("", facts) == []


def test_a_facts_record_we_cannot_read_gives_no_false_alarms():
    assert find_false_claims("The white knight on f3 is undefended.", {"fen": "bad"}) == []


def test_explicit_piece_subject_is_read_and_checked():
    facts = _facts(QH5, "g8f6", "g7g6", 20, -700, ["g7g6", "h5f3"])
    assert problems("The black knight on f6 attacks the white queen on h5.", facts) == []
    assert problems("The black knight on f6 attacks the white rook on a1.", facts) == [
        "the black knight on f6 does not attack the white rook on a1"]


def test_it_after_a_sentence_about_another_piece_is_not_bound_to_the_moved_piece():
    facts = _facts(QH5, "g8f6", "g7g6", 20, -700, ["g7g6", "h5f3"])
    text = "The white queen on h5 attacks f7. It also attacks the black pawn on e5."
    assert problems(text, facts) == []


def test_which_binds_to_the_move_only_right_after_it():
    facts = _facts(QH5, "g8f6", "g7g6", 20, -700, ["g7g6", "h5f3"])
    assert problems("The engine's best move is g6, which attacks the white queen on h5.", facts) == []
    # "which" after a piece phrase is not the moved piece, so no claim is made
    text = "Black ignores the white queen on h5, which attacks the black pawn on e5."
    assert problems(text, facts) == []


def test_check_text_counts_the_claims_it_tested():
    from chess_coach.factcheck import CHECKER_VERSION, check_text

    facts = _facts(QH5, "g8f6", "g7g6", 20, -700, ["g7g6", "h5f3"])
    text = ("The black knight on f6 attacks the white queen on h5. "
            "The white queen on h5 is attacked and undefended. It improves control of the centre.")
    result = check_text(text, facts, ["g7g6", "h5f3"])
    assert result.checked == 2 and result.false_claims == []
    assert check_text("Strategy only, nothing to test.", facts).checked == 0
    assert CHECKER_VERSION  # saved explanations record it, so a change forces a re-check


ND3 = "5rk1/5pbp/r2qp1p1/p2pN3/4n3/1P2P3/PB3PPP/2RQ1RK1 w - - 4 17"


def test_a_threat_the_move_removed_by_moving_the_piece_is_caught_even_without_a_colour():
    facts = _facts(ND3, "e5d3", "d1e2", 5, -58, ["d1e2"])
    bad = problems("The move Nd3 does not address the threat to the knight on e5.", facts)
    assert bad == [("Nd3 moves the white knight on e5 to d3, out of attack, "
                    "so it does deal with the threat")]
    assert problems("Nd3 fails to address the threat to the white knight on e5.", facts) == bad


def test_a_threat_that_really_was_left_is_not_flagged_and_the_subject_move_is_resolved():
    facts = _facts(QH5, "g8f6", "g7g6", 20, -700, ["g7g6", "h5f3"])
    assert problems("Nf6 does not address the threat to the pawn on f7.", facts) == []
    # the sentence is about the engine's move, which really does leave the knight attacked
    nd3 = _facts(ND3, "e5d3", "d1e2", 5, -58, ["d1e2"])
    assert problems("Qe2 does not deal with the threat to the knight on e5.", nd3) == []


def test_the_checker_version_moved_on_so_saved_explanations_are_checked_again():
    from chess_coach.factcheck import CHECKER_VERSION

    assert CHECKER_VERSION == "3"
