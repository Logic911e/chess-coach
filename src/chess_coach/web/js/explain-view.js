// What the explanation box shows. Pure (no DOM), so it can be tested in node.

/**
 * The blocks to draw, in order. An explanation written in fields gives one block per field, each with
 * a short bold label; an older one (or one without fields) is a single block of plain text.
 */
export function explainBlocks(fields, body) {
  if (!Array.isArray(fields) || !fields.length) return body ? [{ key: "text", label: "", text: body }] : [];
  return fields.filter((f) => f && typeof f.text === "string" && f.text).map((f) => ({
    key: f.key, label: f.key === "verdict" ? "" : f.label || "", text: f.text,
  }));
}

/** A sentence saying which parts were written from the facts because the model's words failed the checks. */
export function fieldsNote(fields) {
  if (!Array.isArray(fields)) return "";
  const labels = fields.filter((f) => f && f.source === "facts").map((f) => (f.label || f.key).toLowerCase());
  if (!labels.length) return "";
  return `The ${labels.join(" and ")} ${labels.length === 1 ? "was" : "were"} written straight from the engine facts, because the model's own wording did not pass the checks.`;
}
