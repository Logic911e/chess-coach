import { test } from "node:test";
import assert from "node:assert/strict";
import { createChat, HONESTY_NOTE } from "../../src/chess_coach/web/js/chat.js";

function setup({ reply, blocked = false } = {}) {
  const sent = [], log = [];
  let moveId = 1;
  const api = { chatMove: async (id, q, h) => {
    sent.push({ id, q, h: h.map((x) => ({ ...x })) });
    const r = typeof reply === "function" ? await reply(id, q) : reply;
    if (r instanceof Error) throw r;
    return r || { body: "an answer", flagged: false };
  } };
  const rec = (name) => (...a) => log.push([name, ...a]);
  const ui = { open: rec("open"), close: rec("close"), reset: rec("reset"), user: rec("user"),
    pending: rec("pending"), answer: rec("answer"), error: rec("error"), restore: rec("restore"),
    blocked: rec("blocked") };
  const chat = createChat({ api, ui, getMoveId: () => moveId, isBlocked: () => blocked });
  return { chat, sent, log, setMove: (m) => { moveId = m; } };
}

test("empty question is not sent", async () => {
  const { chat, sent, log } = setup();
  assert.equal(await chat.send("   \n "), false);
  assert.equal(await chat.send(""), false);
  assert.equal(sent.length, 0);
  assert.ok(!log.some((l) => l[0] === "pending"));
});

test("question is trimmed and the answer is shown with its flag", async () => {
  const { chat, sent, log } = setup({ reply: { body: "Nf3 is fine", flagged: true } });
  await chat.send("  why? ");
  assert.equal(sent[0].q, "why?");
  assert.deepEqual(log.filter((l) => l[0] === "answer"), [["answer", "Nf3 is fine", true]]);
  assert.deepEqual(log.filter((l) => l[0] === "pending").map((l) => l[1]), [true, false]);
  assert.match(HONESTY_NOTE, /legal moves and piece squares only/);
});

test("history resets when the move changes", async () => {
  const { chat, sent, setMove } = setup();
  await chat.send("one");
  await chat.send("two");
  assert.deepEqual(sent[1].h, [{ role: "user", content: "one" }, { role: "assistant", content: "an answer" }]);
  setMove(2);
  await chat.send("three");
  assert.deepEqual(sent[2].h, []);
  assert.equal(sent[2].id, 2);
});

test("error from api is shown not thrown", async () => {
  const { chat, log, sent } = setup({ reply: new Error("The local model is unavailable") });
  assert.equal(await chat.send("hello"), false);
  assert.ok(log.some((l) => l[0] === "error" && l[1] === "The local model is unavailable"));
  assert.deepEqual(log.filter((l) => l[0] === "restore"), [["restore", "hello"]]);
  assert.deepEqual(log.filter((l) => l[0] === "pending").map((l) => l[1]), [true, false]);
  // still usable, and the failed question is not kept in history
  await chat.send("again");
  assert.equal(sent.length, 2);
  assert.deepEqual(sent[1].h, []);
});

test("a late answer for a move the user has left is discarded", async () => {
  let release;
  const gate = new Promise((r) => { release = r; });
  const { chat, log, setMove, sent } = setup({ reply: async () => { await gate; return { body: "late", flagged: false }; } });
  const p = chat.send("slow");
  setMove(2);
  chat.sync();
  release();
  await p;
  assert.ok(!log.some((l) => l[0] === "answer"));
  await chat.send("next");
  assert.deepEqual(sent[1].h, []);
});

test("a second send while one is in flight is ignored", async () => {
  let release;
  const gate = new Promise((r) => { release = r; });
  const { chat, sent } = setup({ reply: async () => { await gate; return { body: "x", flagged: false }; } });
  const p = chat.send("a");
  assert.equal(await chat.send("b"), false);
  release(); await p;
  assert.equal(sent.length, 1);
});

test("blocked chat (active guess) does not send", async () => {
  const { chat, sent, log } = setup({ blocked: true });
  assert.equal(await chat.send("hint?"), false);
  assert.equal(sent.length, 0);
  assert.ok(log.some((l) => l[0] === "blocked"));
});

test("history sent is capped at 20 turns", async () => {
  const { chat, sent } = setup();
  for (let i = 0; i < 12; i++) await chat.send("q" + i);
  assert.equal(sent[11].h.length, 20);
});

test("invalidate drops an answer in flight, clears busy and history", async () => {
  let release;
  const gate = new Promise((r) => { release = r; });
  const { chat, log, sent } = setup({ reply: async () => { await gate; return { body: "leak", flagged: false }; } });
  const p = chat.send("slow");
  assert.equal(chat.busy(), true);
  chat.invalidate();
  assert.equal(chat.busy(), false);
  assert.deepEqual(log.filter((l) => l[0] === "pending").map((l) => l[1]), [true, false]);
  assert.ok(log.some((l) => l[0] === "reset"));
  release(); await p;
  assert.ok(!log.some((l) => l[0] === "answer"));
  await chat.send("next");
  assert.deepEqual(sent[1].h, []);
});

test("open while blocked reports it instead of opening", () => {
  const { chat, log } = setup({ blocked: true });
  assert.equal(chat.open(), false);
  assert.deepEqual(log.map((l) => l[0]), ["blocked"]);
});

test("no move on screen: no api call, a short message", async () => {
  const sent = [], log = [];
  const ui = new Proxy({}, { get: (_, n) => (...a) => log.push([n, ...a]) });
  const chat = createChat({ api: { chatMove: async (...a) => { sent.push(a); } }, ui, getMoveId: () => null });
  assert.equal(await chat.send("hi"), false);
  assert.equal(sent.length, 0);
  assert.ok(log.some((l) => l[0] === "error"));
});
