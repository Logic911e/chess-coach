-- Header facts the stats page needs and the PGN text already holds: how fast the game was and how
-- the players were rated. Additive and nullable; `python -m chess_coach.backfill` fills older games.
ALTER TABLE games
    ADD COLUMN time_control TEXT,
    ADD COLUMN white_elo    INTEGER CHECK (white_elo BETWEEN 0 AND 4000),
    ADD COLUMN black_elo    INTEGER CHECK (black_elo BETWEEN 0 AND 4000);

COMMENT ON COLUMN games.time_control IS
    'the PGN TimeControl tag as written, such as 60 (seconds), 180+2, or 1/86400 for correspondence';
