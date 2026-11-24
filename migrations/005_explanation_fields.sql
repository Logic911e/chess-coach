-- The parts of an explanation, when it was written in fields (verdict, reason, what was better):
-- [{"key": "reason", "label": "Why", "text": "...", "source": "code" | "model" | "facts"}].
-- NULL for explanations written as one block of text. The joined text stays in `body`.
ALTER TABLE explanations
    ADD COLUMN fields JSONB CHECK (fields IS NULL OR jsonb_typeof(fields) = 'array');

COMMENT ON COLUMN explanations.fields IS
    'the explanation split into named parts, each with its source: code (written from the facts '
    'by code), model (the model''s words, after the checks) or facts (a part the model''s words '
    'failed, rewritten from the statements)';
