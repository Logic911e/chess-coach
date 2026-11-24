"""Does giving the model verified facts reduce false claims?

Same model, same style instructions, same truth boards. The only difference is
the input: (A) the facts record, or (B) just the FEN and the move played.
Run: python -m chess_coach.evaluation --seeds 3
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import statistics
import subprocess
import time
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path

import chess

from chess_coach import features as cf
from chess_coach.claims import check_claims, truth_boards
from chess_coach.engine import Engine
from chess_coach.eval_cases import CASES, Case
from chess_coach.explainer import _STATEMENT_STYLES, SYSTEM_PROMPT, build_messages, explain
from chess_coach.factcheck import find_false_claims
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
    false_claims: list[str] = field(default_factory=list)  # tactical claims the board contradicts
    attempts: int = 1  # model calls used; more than 1 only for the *_checked conditions
    flagged: bool = False  # a *_checked condition still failed a check after its retries
    dropped: list[str] = field(default_factory=list)  # cited style: sentences removed, and why
    fallback: bool = False  # cited style: too little survived, so the text is the statements
    fields_from_facts: list[str] = field(default_factory=list)  # fields style: which were rewritten
    seconds: float = 0.0  # wall time to produce the answer

    @property
    def has_false_claim(self) -> bool:
        return bool(self.illegal_moves or self.false_placements or self.forbidden_hit
                    or self.false_claims)


# One thread, a small hash and a fresh engine per case make a fixed-depth search repeatable.
# The app keeps the engine's defaults, because it wants speed more than repeatability.
ENGINE_OPTIONS = {"Threads": 1, "Hash": 16}


def freeze_facts(path: Path, depth: int) -> dict:
    """Run the engine once per case and save the facts, so every later evaluation reads
    identical facts whatever the engine would say today."""
    cases, stockfish = {}, ""
    for case in CASES:
        with Engine(options=ENGINE_OPTIONS) as engine:
            facts, line, san = prepare(case, engine, depth)
            stockfish = engine.version
        cases[case.id] = {"facts": facts, "line": line, "san": san}
    data = {"depth": depth, "engine_options": ENGINE_OPTIONS, "stockfish": stockfish,
            "cases": cases}
    path.write_text(json.dumps(data, indent=1, sort_keys=True))
    return data


def load_frozen(path: Path) -> dict:
    return json.loads(path.read_text())


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def _get_json(url: str):
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            return json.load(resp)
    except OSError:
        return None


def manifest(model: str, host: str, frozen: dict | None, args: dict) -> dict:
    """What this run ran on, so a number can be traced and a surprise explained."""
    def git(*a: str) -> str:
        try:
            return subprocess.run(["git", *a], capture_output=True, text=True, check=True,
                                  cwd=Path(__file__).parent).stdout.strip()
        except (OSError, subprocess.CalledProcessError):
            return "unknown"

    tags = _get_json(f"{host}/api/tags") or {}
    digest = next((m.get("digest", "") for m in tags.get("models", []) if m.get("name") == model),
                  "unknown")
    return {
        "git_sha": git("rev-parse", "HEAD"),
        "git_dirty": bool(git("status", "--porcelain", "--", "src")),
        "ollama_version": (_get_json(f"{host}/api/version") or {}).get("version", "unknown"),
        "model_digest": digest[:16],
        "stockfish": (frozen or {}).get("stockfish", "live engine, not frozen"),
        "engine_options": (frozen or {}).get("engine_options"),
        "facts_sha": _sha(json.dumps((frozen or {}).get("cases"), sort_keys=True)),
        # the prompt text plus whether the style adds the richer statements, so a style that only
        # differs in its statements still gets its own fingerprint
        "prompt_sha": {name: _sha(f"{prompt}|rich={rich}")
                       for name, (prompt, rich) in _STATEMENT_STYLES.items()}
                      | {"facts": _sha(SYSTEM_PROMPT)},
        "args": args,
    }


_TOP_BAND = {"best", "excellent"}  # a loss under 0.02 expected points: the search can swing it


def _same_label(got: str, expected: str) -> bool:
    return got == expected or {got, expected} <= _TOP_BAND


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
    if not _same_label(facts["classification"], case.expected):
        raise AssertionError(
            f"{case.id}: engine says {facts['classification']!r}, case expects {case.expected!r}"
        )
    return facts, best.pv, facts["played"]["san"]


def score(
    case: Case, condition: str, seed: int, text: str, line: list[str],
    facts: dict | None = None, attempts: int = 1, flagged: bool = False,
    dropped: list[str] | None = None, fallback: bool = False,
    fields_from_facts: list[str] | None = None, seconds: float = 0.0,
) -> Result:
    report = check_claims(text, truth_boards(case.fen, case.played_uci, line))
    false_claims = [f.problem for f in find_false_claims(text, facts, line)] if facts else []
    return Result(
        case_id=case.id,
        condition=condition,
        seed=seed,
        text=text,
        illegal_moves=report.illegal_moves,
        false_placements=report.false_placements,
        forbidden_hit=bool(case.forbidden and re.search(case.forbidden, text, re.IGNORECASE)),
        key_hit=bool(re.search(case.must_mention, text, re.IGNORECASE)),
        false_claims=false_claims,
        attempts=attempts,
        flagged=flagged,
        dropped=dropped or [],
        fallback=fallback,
        fields_from_facts=fields_from_facts or [],
        seconds=round(seconds, 2),
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
            "false_tactical_claims": sum(len(r.false_claims) for r in rs),
            "forbidden_claims": sum(r.forbidden_hit for r in rs),
            "key_idea_mentioned": sum(r.key_hit for r in rs),
            "model_calls": sum(r.attempts for r in rs),
            "flagged_after_retries": sum(r.flagged for r in rs),
            "dropped_sentences": sum(len(r.dropped) for r in rs),
            "fell_back_to_statements": sum(r.fallback for r in rs),
            "fields_written_from_facts": sum(len(r.fields_from_facts) for r in rs),
            "median_seconds": round(statistics.median(r.seconds for r in rs), 1),
        }
    return out


STYLES = ("statements", "statements_strict", "statements_rich")
# "<style>_checked" runs the style through the real retry loop (explainer.explain), so the
# explanation can be rewritten when a check fails; plain styles are a single model call.
ALL_CONDITIONS = ("facts", *STYLES, *(f"{s}_checked" for s in STYLES), "cited", "fields", "fen_only")


def condition_messages(cond: str, facts: dict, fen: str, san: str) -> list[Message]:
    """The prompt for one evaluation condition."""
    if cond == "fen_only":
        return fen_only_messages(fen, san)
    return build_messages(facts, "json" if cond == "facts" else cond)


def run(
    client_factory, depth: int, seeds: list[int], out_dir: Path, model: str, temperature: float,
    conditions: tuple[str, ...] = ("facts", "statements", "fen_only"),
    frozen: dict | None = None, host: str = "http://localhost:11434",
) -> tuple[list[Result], dict]:
    results: list[Result] = []
    if frozen is None:  # no frozen file: compute now, with the repeatable engine settings
        frozen = {"cases": {}, "engine_options": ENGINE_OPTIONS}
        for c in CASES:
            with Engine(options=ENGINE_OPTIONS) as engine:
                f, ln, sn = prepare(c, engine, depth)
                frozen["stockfish"] = engine.version
            frozen["cases"][c.id] = {"facts": f, "line": ln, "san": sn}
    prepared = {cid: (v["facts"], v["line"], v["san"]) for cid, v in frozen["cases"].items()}
    for case in CASES:
        facts, line, san = prepared[case.id]
        for seed in seeds:
            client: ChatClient = client_factory(seed)
            for cond in conditions:
                started = time.perf_counter()
                dropped: list[str] = []
                from_facts: list[str] = []
                fallback = flagged = False
                attempts = 1
                if cond.endswith("_checked") or cond in ("cited", "fields"):
                    got = explain(facts, client, line, style=cond.removesuffix("_checked"))
                    text, attempts, flagged = got.text, got.attempts, got.flagged
                    dropped, fallback = got.dropped, got.fallback
                    from_facts = [f["key"] for f in got.fields if f["source"] == "facts"]
                else:
                    text = client.chat(condition_messages(cond, facts, case.fen, san))
                results.append(score(case, cond, seed, text, line, facts, attempts, flagged,
                                     dropped, fallback, from_facts, time.perf_counter() - started))
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
                "manifest": manifest(model, host, frozen, {
                    "conditions": list(conditions), "seeds": seeds, "depth": depth,
                    "temperature": temperature}),
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
    ap.add_argument(
        "--conditions", default="facts,statements,fen_only",
        help=f"comma list from: {', '.join(ALL_CONDITIONS)}",
    )
    ap.add_argument("--freeze-facts", metavar="PATH", default=None,
                    help="write the facts for every case to PATH and exit")
    ap.add_argument("--facts", metavar="PATH", default=None,
                    help="read frozen facts from PATH instead of running the engine")
    a = ap.parse_args()
    if a.freeze_facts:
        data = freeze_facts(Path(a.freeze_facts), a.depth)
        print(f"froze {len(data['cases'])} cases at depth {a.depth} ({data['stockfish']}) "
              f"to {a.freeze_facts}")
        return
    frozen = load_frozen(Path(a.facts)) if a.facts else None
    conditions = tuple(c.strip() for c in a.conditions.split(","))
    unknown = [c for c in conditions if c not in ALL_CONDITIONS]
    if unknown:
        ap.error(f"unknown condition(s): {', '.join(unknown)}")
    first = OllamaClient(model=a.model)
    _, summary = run(
        lambda s: OllamaClient(model=a.model, seed=s, temperature=a.temperature), a.depth, list(range(a.seeds)), Path(a.out),
        first.model, a.temperature, conditions, frozen, first.host,
    )
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
