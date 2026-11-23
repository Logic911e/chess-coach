-- Where an explanation came from, so text written by an older prompt, model or checker is never
-- shown as current. Additive: rows written before this migration keep the value 'legacy', which
-- never matches a current fingerprint, so they are regenerated the next time the move is opened.
ALTER TABLE explanations
    ADD COLUMN style           TEXT    NOT NULL DEFAULT 'legacy',
    ADD COLUMN prompt_hash     TEXT    NOT NULL DEFAULT 'legacy',
    ADD COLUMN checker_version TEXT    NOT NULL DEFAULT 'legacy',
    ADD COLUMN checked_claims  INTEGER NOT NULL DEFAULT 0 CHECK (checked_claims >= 0),
    ADD COLUMN false_claims    JSONB   NOT NULL DEFAULT '[]'::jsonb
        CHECK (jsonb_typeof(false_claims) = 'array');

COMMENT ON COLUMN explanations.flagged IS
    'a check still failed after all retries: an illegal move, a wrong piece square or (from '
    'checker version 2) a false tactical claim';
COMMENT ON COLUMN explanations.prompt_hash IS
    'fingerprint of the exact messages sent to the model (system prompt plus statements)';
COMMENT ON COLUMN explanations.checked_claims IS
    'how many tactical claims in the text were read and tested against the board';
