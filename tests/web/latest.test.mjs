import { test } from "node:test";
import assert from "node:assert/strict";
import { createLatest } from "../../src/chess_coach/web/js/latest.js";

function deferred() { let res, rej; const p = new Promise((a, b) => { res = a; rej = b; }); return { p, res, rej }; }

test("latest: an older promise resolving after a newer one is ignored", async () => {
  const l = createLatest();
  const a = deferred(), b = deferred();
  const ra = l.track(a.p), rb = l.track(b.p);
  b.res("new"); assert.deepEqual(await rb, { value: "new" });
  a.res("old"); assert.deepEqual(await ra, { stale: true });
});

test("latest: a failed older request does not clobber a newer success", async () => {
  const l = createLatest();
  const a = deferred(), b = deferred();
  const ra = l.track(a.p), rb = l.track(b.p);
  b.res("new");
  a.rej(new Error("boom"));
  assert.deepEqual(await rb, { value: "new" });
  assert.deepEqual(await ra, { stale: true });  // swallowed, not thrown
});

test("latest: the newest request's own failure is reported", async () => {
  const l = createLatest();
  const a = deferred();
  const ra = l.track(a.p);
  a.rej(new Error("boom"));
  await assert.rejects(ra, /boom/);
});

test("latest: a lone request resolves normally and isLatest tracks the newest token", async () => {
  const l = createLatest();
  assert.deepEqual(await l.track(Promise.resolve(1)), { value: 1 });
  const t1 = l.begin(), t2 = l.begin();
  assert.equal(l.isLatest(t1), false);
  assert.equal(l.isLatest(t2), true);
});
