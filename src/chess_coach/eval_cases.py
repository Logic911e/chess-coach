"""Evaluation positions with known answers.

Each case was checked against Stockfish (depth 14) before it went in, so the
`expected` label is the engine's verdict, not just my opinion.
`must_mention`: a regex a correct explanation should match (the key idea).
`forbidden`: a regex that would contradict the known answer (a false claim).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Case:
    id: str
    fen: str
    played_uci: str
    expected: str  # Stockfish classification at depth 14
    idea: str
    must_mention: str
    forbidden: str | None = None


QH5 = "r1bqkbnr/pppp1ppp/2n5/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR b KQkq - 3 3"
FORK = "3q3k/8/8/6N1/8/8/8/4K3 w - - 0 1"
BACKRANK = "6k1/5ppp/8/8/8/8/8/R3K3 w - - 0 1"
WINQ = "rnb1kbnr/pppp1ppp/8/4p3/4P2q/5N2/PPPP1PPP/RNBQKB1R w KQkq - 0 1"

CASES: list[Case] = [
    Case("qh5_nf6", QH5, "g8f6", "blunder", "ignores the threat Qxf7#", r"f7"),
    Case("qh5_g6", QH5, "g7g6", "best", "defends against Qxf7#", r"g6|f7|queen",
         r"blunder|mistake|inaccuracy"),
    Case("fork_win", FORK, "g5f7", "best", "Nf7+ forks king and queen", r"fork|queen",
         r"checkmate"),
    Case("fork_missed", FORK, "e1e2", "blunder", "misses Nf7+ winning the queen", r"f7|fork|queen"),
    Case("free_queen_take", WINQ, "f3h4", "best", "knight captures the loose queen", r"queen",
         r"checkmate"),
    Case("free_queen_ignored", WINQ, "d2d3", "blunder", "ignores a free queen", r"queen"),
    Case("queen_hung", "rnbqkbnr/ppp1pppp/8/3p4/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2", "d1g4",
         "blunder", "queen moves to a square the bishop attacks", r"queen|bishop", r"checkmate"),
    Case("backrank_mate", BACKRANK, "a1a8", "best", "back-rank checkmate", r"mate",
         r"blunder|mistake|stalemate"),
    Case("missed_mate", BACKRANK, "e1d2", "mistake", "misses Ra8# mate in one", r"mate|Ra8"),
    Case("bxf7_sac", "r1bqkbnr/pppp1ppp/2n5/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 4 4", "c4f7",
         "blunder", "bishop sacrifice that just loses the bishop", r"bishop"),
    Case("castle", "r1bqk1nr/pppp1ppp/2n5/2b1p3/2B1P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 4 4", "e1g1",
         "excellent", "castling is fine", r"castl|king", r"blunder|mistake"),
    Case("develop", "rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2", "g1f3",
         "best", "natural developing move", r"knight|develop|f3", r"blunder|mistake"),
]
