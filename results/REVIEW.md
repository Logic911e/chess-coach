# Manual review of eval_qwen2.5_7b-instruct_20261119_223913.json

Model: qwen2.5:7b-instruct (Ollama), temperature 0.5, seeds 0-2, engine depth 14.
12 positions x 3 samples = 36 responses per condition. Command:
`python -m chess_coach.evaluation --seeds 3 --temperature 0.5`

I read every flagged response by hand after the run. The scoring code was not changed
afterwards.

| Condition | Flagged by checker | Confirmed false after reading | Checker false positives |
|---|---|---|---|
| facts (engine record in the prompt) | 3 / 36 | 2 / 36 | 1 |
| fen_only (FEN + move only) | 8 / 36 | 8 / 36 | 0 |

## The 3 flagged "facts" responses
- free_queen_take s0: flagged by the "checkmate" regex, but the text says "doesn't result in an
  immediate checkmate". **False positive** (the regex ignores negation).
- free_queen_ignored s1: says there is a "pawn on h4" and that it is hanging. The piece on h4 is the
  black queen. **Confirmed false.**
- backrank_mate s2: says the rook "attacks the king on a8". The king is on g8. **Confirmed false.**

## What the checker does NOT measure (so the gap is probably understated)
- Wrong verdicts. Without facts the model called blunders "a solid choice" (Nf6 into Qxf7#, Qg4 hanging
  the queen). The checker only sees an invented square or an illegal move, not a wrong judgement.
  The "key idea mentioned" rate (regex) was 36/36 with facts and 20/36 without, but those regexes are loose.
- Vague or filler claims, such as "creating two weaknesses".

## Limits
- Only 12 positions, and 3 samples of each are not independent. Treat 2/36 vs 8/36 as suggestive,
  not a measured rate. One model, one prompt, one temperature.
- Positions and answer keys were written by the author of this repo, not an independent set.
