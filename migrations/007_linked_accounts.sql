-- Accounts the user has linked, so their games can be fetched from the public Chess.com and
-- Lichess APIs (no login or token is stored). A game remembers which account it came from;
-- unlinking can keep those games (the link is cleared) or delete them.
CREATE TABLE linked_accounts (
    id             BIGSERIAL PRIMARY KEY,
    platform       TEXT NOT NULL CHECK (platform IN ('chesscom', 'lichess')),
    username       TEXT NOT NULL CHECK (char_length(username) BETWEEN 2 AND 30),
    linked_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_synced_at TIMESTAMPTZ
);
CREATE UNIQUE INDEX linked_accounts_one_per_name ON linked_accounts (platform, lower(username));

ALTER TABLE games
    ADD COLUMN source_account BIGINT REFERENCES linked_accounts (id) ON DELETE SET NULL;
CREATE INDEX games_source_account ON games (source_account) WHERE source_account IS NOT NULL;
