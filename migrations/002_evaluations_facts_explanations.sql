-- What the engine, the feature code and the language model said about each move.

CREATE TABLE evaluations (
    move_id               BIGINT PRIMARY KEY REFERENCES moves (id) ON DELETE CASCADE,
    best_uci              TEXT NOT NULL CHECK (best_uci ~ '^[a-h][1-8][a-h][1-8][qrbn]?$'),
    cp_best               INTEGER NOT NULL,   -- centipawns, mover's perspective, mate capped at +/-10000
    cp_played             INTEGER NOT NULL,
    expected_points_lost  NUMERIC(4, 3) NOT NULL CHECK (expected_points_lost BETWEEN 0 AND 1),
    classification        TEXT NOT NULL CHECK (
        classification IN ('best', 'excellent', 'good', 'inaccuracy', 'mistake', 'blunder')
    ),
    engine_depth          INTEGER NOT NULL CHECK (engine_depth > 0),
    engine_version        TEXT NOT NULL
);

-- The full facts record the language model was allowed to talk about. JSONB because its shape
-- is nested and evolves with the feature code; the columns we filter on stay relational above.
CREATE TABLE facts (
    move_id  BIGINT PRIMARY KEY REFERENCES moves (id) ON DELETE CASCADE,
    facts    JSONB NOT NULL CHECK (jsonb_typeof(facts) = 'object'),
    reasons  TEXT[] NOT NULL DEFAULT '{}'   -- why this is a key moment: blunder, big_swing, ...
);

CREATE TABLE explanations (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    move_id     BIGINT NOT NULL REFERENCES moves (id) ON DELETE CASCADE,
    model       TEXT NOT NULL,
    body        TEXT NOT NULL,
    flagged     BOOLEAN NOT NULL,           -- still named illegal moves after all retries
    attempts    INTEGER NOT NULL CHECK (attempts >= 1),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- Foreign keys are not indexed automatically in Postgres; this one is joined constantly.
CREATE INDEX explanations_move_id_idx ON explanations (move_id);
