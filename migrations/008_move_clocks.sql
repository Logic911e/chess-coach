-- Time left on the mover's own clock right after each move, in milliseconds, from the PGN's
-- [%clk] comments. NULL when the game has no clock times (a Chess.com export without them).
ALTER TABLE moves ADD COLUMN clock_ms INTEGER CHECK (clock_ms >= 0);
