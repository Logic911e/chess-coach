"""Write python-chess's built-in piece drawings to web/pieces/ as standalone SVG files.

The pieces are Colin M.L. Burnett's "Cburnett" set (GPL v2+ / BSD / GFDL), which python-chess
bundles in chess.svg. Run once: python scripts/export_pieces.py
"""
from pathlib import Path

import chess.svg

out = Path(__file__).resolve().parents[1] / "src/chess_coach/web/pieces"
out.mkdir(parents=True, exist_ok=True)
for key, body in chess.svg.PIECES.items():
    colour = "w" if key.isupper() else "b"
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 45 45">{body}</svg>\n'
    (out / f"{colour}{key.upper()}.svg").write_text(svg)
print(sorted(p.name for p in out.glob("*.svg")))
