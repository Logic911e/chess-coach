"""Does giving the model verified facts reduce false claims?

Same model, same style instructions, same truth boards. The only difference is
the input: (A) the facts record, or (B) just the FEN and the move played.
Run: python -m chess_coach.evaluation --seeds 3
"""

from __future__ import annotations

import argparse
import json
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import chess

from chess_coach import features as cf
from chess_coach.claims import check_claims, truth_boards
from chess_coach.engine import Engine
from chess_coach.eval_cases import CASES, Case
from chess_coach.explainer import build_messages
from chess_coach.guess import score_after
from chess_coach.llm import ChatClient, Message, OllamaClient

FEN_ONLY_SYSTEM = """\
You are a chess coach explaining one move to an improving club player.
You are given the position (FEN) and the move that was played.
Explain whether it was a good move and why. 3 to 5 sentences. Plain language. No lists, no headings."""


def fen_only_messages(fen: str, san: str) -> list[Message]:
    side = "White" if chess.Board(fen).turn else "Black"
    return [
        {"role": "system", "content": FEN_ONLY_SYSTEM},
        {"role": "user", "content": f"Position (FEN): {fen}\n{side} played: {san}\n\nExplain this move."},
    ]


@dataclass
class Result:
    case_id: str
    condition: str
    seed: int
    text: str
    illegal_moves: list[str]
    false_placements: list[str]
    forbidden_hit: bool
    key_hit: bool

    @property
    def has_false_claim(self) -> bool:
        return bool(self.illegal_moves or self.false_placements or self.forbidden_hit)


def prepare(case: Case, engine: Engine, depth: int) -> tuple[dict, list[str], str]:
    """Engine facts for one case. Returns (facts, best line UCI, played SAN)."""
    board = chess.Board(case.fen)
    best = engine.analyse(board, depth=depth)[0]
    after = board.copy(stack=False)
    after.push_uci(case.played_uci)
    if case.played_uci == best.best_move:
        cp_played = best.cp_capped
    else:
        cp_played = score_after(after, best.cp_capped, depth, engine)
    facts = cf.build_facts(
        case.fen, case.played_uci, best.best_move, best.cp_capped, cp_played, best_line_uci=best.pv
    )
    if facts["classification"] != case.expected:
        raise AssertionError(
            f"{case.id}: engine says {facts['classification']!r}, case expects {case.expected!r}"
        )
    return facts, best.pv, facts["played"]["san"]


def score(case: Case, condition: str, seed: int, text: str, line: list[str]) -> Result:
    report = check_claims(text, truth_boards(case.fen, case.played_uci, line))
    return Result(
        case_id=case.id,
        condition=condition,
        seed=seed,
        text=text,
        illegal_moves=report.illegal_moves,
        false_placements=report.false_placements,
        forbidden_hit=bool(case.forbidden and re.search(case.forbidden, text, re.IGNORECASE)),
        key_hit=bool(re.search(case.must_mention, text, re.IGNORECASE)),
    )


def summarise(results: list[Result]) -> dict:
    out = {}
    for cond in sorted({r.condition for r in results}):
        rs = [r for r in results if r.condition == cond]
        out[cond] = {
            "responses": len(rs),
            "with_false_claim": sum(r.has_false_claim for r in rs),
            "illegal_moves": sum(len(r.illegal_moves) for r in rs),
            "false_piece_placements": sum(len(r.false_placements) for r in rs),
            "forbidden_claims": sum(r.forbidden_hit for r in rs),
            "key_idea_mentioned": sum(r.key_hit for r in rs),
        }
    return out


def run(
    client_factory, depth: int, seeds: list[int], out_dir: Path, model: str, temperature: float
) -> tuple[list[Result], dict]:
    results: list[Result] = []
    with Engine() as engine:
        prepared = {c.id: prepare(c, engine, depth) for c in CASES}
    for case in CASES:
        facts, line, san = prepared[case.id]
        for seed in seeds:
            client: ChatClient = client_factory(seed)
            for cond, msgs in (
                ("facts", build_messages(facts)),
                ("statements", build_messages(facts, "statements")),
                ("fen_only", fen_only_messages(case.fen, san)),
            ):
                results.append(score(case, cond, seed, client.chat(msgs), line))
            print(f"  done {case.id} seed={seed}", flush=True)
    summary = summarise(results)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"eval_{model.replace(':', '_')}_{time.strftime('%Y%m%d_%H%M%S')}.json"
    path.write_text(
        json.dumps(
            {
                "model": model,
                "engine_depth": depth,
                "cases": len(CASES),
                "seeds": seeds,
                "temperature": temperature,
                "summary": summary,
                "results": [asdict(r) for r in results],
            },
            indent=1,
        )
    )
    print(f"saved {path}")
    return results, summary


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=None)
    ap.add_argument("--depth", type=int, default=14)
    ap.add_argument("--seeds", type=int, default=1, help="number of seeds (0..n-1)")
    ap.add_argument(
        "--temperature", type=float, default=0.0,
        help="0 is deterministic (extra seeds repeat the same answer); use >0 with several seeds",
    )
    ap.add_argument("--out", default="results")
    a = ap.parse_args()
    first = OllamaClient(model=a.model)
    _, summary = run(
        lambda s: OllamaClient(model=a.model, seed=s, temperature=a.temperature), a.depth, list(range(a.seeds)), Path(a.out),
        first.model, a.temperature,
    )
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
