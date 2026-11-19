-- Analytic queries. Each block starts with "-- name: <id>" and is run by scripts/explain.py.
-- The literal values (player, game id) are examples.

-- name: phase_error_rate
-- Average expected points lost and mistake+blunder rate per phase and colour.
WITH graded AS (
    SELECT m.phase, m.color, e.expected_points_lost,
           (e.classification IN ('mistake', 'blunder')) AS is_error
    FROM moves m
    JOIN evaluations e ON e.move_id = m.id
)
SELECT phase, color,
       count(*)                                   AS moves,
       round(avg(expected_points_lost), 4)        AS avg_epl,
       round(100.0 * avg(is_error::int), 1)       AS error_pct
FROM graded
GROUP BY phase, color
ORDER BY phase, color;

-- name: opening_error_rate
-- Which openings lead to the most errors, ignoring openings with few games.
SELECT g.opening, g.eco,
       count(DISTINCT g.id)                       AS games,
       round(avg(e.expected_points_lost), 4)      AS avg_epl,
       round(100.0 * avg((e.classification IN ('mistake', 'blunder'))::int), 1) AS error_pct
FROM games g
JOIN moves m       ON m.game_id = g.id
JOIN evaluations e ON e.move_id = m.id
GROUP BY g.opening, g.eco
HAVING count(DISTINCT g.id) >= 20
ORDER BY avg_epl DESC;

-- name: rolling_error_one_game
-- Rolling average of the last 10 own moves for each colour in one game (window function).
SELECT m.ply, m.color, m.san, e.expected_points_lost,
       round(avg(e.expected_points_lost) OVER (
           PARTITION BY m.color ORDER BY m.ply ROWS BETWEEN 9 PRECEDING AND CURRENT ROW), 4) AS rolling_epl
FROM moves m
JOIN evaluations e ON e.move_id = m.id
WHERE m.game_id = 1234
ORDER BY m.ply;

-- name: worst_moment_per_game_of_player
-- Each game of one player with its single biggest error (RANK over a partition).
WITH own AS (
    SELECT g.id AS game_id, g.played_on, m.ply, m.san, e.expected_points_lost,
           rank() OVER (PARTITION BY g.id ORDER BY e.expected_points_lost DESC, m.ply) AS rnk
    FROM games g
    JOIN moves m       ON m.game_id = g.id
                      AND m.color = CASE WHEN g.white = 'synth_37' THEN 'white' ELSE 'black' END
    JOIN evaluations e ON e.move_id = m.id
    WHERE g.white = 'synth_37' OR g.black = 'synth_37'
)
SELECT game_id, played_on, ply, san, expected_points_lost
FROM own
WHERE rnk = 1
ORDER BY expected_points_lost DESC
LIMIT 10;

-- name: facts_ignored_knight_threat
-- Moves that ignored a threat to a knight (JSONB containment, served by a GIN index).
SELECT count(*)
FROM facts
WHERE facts @> '{"played": {"ignored_threats": [{"piece": "knight"}]}}';

-- name: blunders_of_player
-- Every blunder one player made, newest game first.
SELECT g.played_on, g.id AS game_id, m.ply, m.san, e.expected_points_lost
FROM games g
JOIN moves m       ON m.game_id = g.id
                  AND m.color = CASE WHEN g.white = 'synth_37' THEN 'white' ELSE 'black' END
JOIN evaluations e ON e.move_id = m.id
WHERE (g.white = 'synth_37' OR g.black = 'synth_37')
  AND e.classification = 'blunder'
ORDER BY g.played_on DESC, m.ply
LIMIT 50;

-- name: facts_rare_pattern
-- A selective JSONB lookup: blunders that ignored a knight threat AND left a bishop hanging.
SELECT move_id
FROM facts
WHERE facts @> '{"classification": "blunder",
                 "played": {"ignored_threats": [{"piece": "knight"}],
                            "leaves_own_piece_hanging": [{"piece": "bishop"}]}}';
