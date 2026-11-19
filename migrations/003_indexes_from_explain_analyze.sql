-- Indexes kept after measuring candidates with scripts/index_experiments.py on 139k synthetic
-- moves (results in docs/index_experiments.txt, discussion in docs/query_plans.md).
-- Candidates measured and rejected: games(white/black), partial index on blunders, covering
-- index on evaluations. They gave no gain, so they would only slow writes.

-- "All moves of one player in a game": the unique (game_id, ply) index cannot filter on color.
-- Player queries went from ~26 ms / ~22 ms to ~4 ms / ~3 ms.
CREATE INDEX moves_game_color_ply_idx ON moves (game_id, color, ply);

-- Containment lookups on the facts record, e.g. blunders that ignored a knight threat.
-- jsonb_path_ops is smaller and faster than the default GIN class and supports @>.
-- A selective pattern (3% of rows) went from ~3.3 ms to ~0.5 ms.
CREATE INDEX facts_gin_idx ON facts USING gin (facts jsonb_path_ops);
