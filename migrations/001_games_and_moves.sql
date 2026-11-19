-- A game and its moves. Everything the analysis produces hangs off these two tables.

CREATE TABLE games (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    white       TEXT NOT NULL,
    black       TEXT NOT NULL,
    result      TEXT NOT NULL CHECK (result IN ('1-0', '0-1', '1/2-1/2', '*')),
    eco         TEXT CHECK (eco ~ '^[A-E][0-9]{2}$'),
    opening     TEXT,
    played_on   DATE,
    pgn         TEXT NOT NULL,
    -- sha256 of the normalised PGN: importing the same game twice is a no-op, not a duplicate.
    pgn_hash    CHAR(64) NOT NULL UNIQUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE moves (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    game_id      BIGINT NOT NULL REFERENCES games (id) ON DELETE CASCADE,
    ply          INTEGER NOT NULL CHECK (ply >= 1),          -- 1 = White's first move
    move_number  INTEGER NOT NULL CHECK (move_number >= 1),
    color        TEXT NOT NULL CHECK (color IN ('white', 'black')),
    san          TEXT NOT NULL,
    uci          TEXT NOT NULL CHECK (uci ~ '^[a-h][1-8][a-h][1-8][qrbn]?$'),
    fen_before   TEXT NOT NULL,
    phase        TEXT NOT NULL CHECK (phase IN ('opening', 'middlegame', 'endgame')),
    -- Also the index that serves "all moves of one game, in order".
    UNIQUE (game_id, ply),
    -- White always moves on odd plies.
    CHECK ((color = 'white') = (ply % 2 = 1))
);
