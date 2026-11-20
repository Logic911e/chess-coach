import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const css = readFileSync(
  fileURLToPath(new URL("../../src/chess_coach/web/css/themes.css", import.meta.url)), "utf8");

function parse() {
  const themes = {};
  let cur = null;
  for (const line of css.split("\n")) {
    const open = line.match(/:root\[data-theme="(\w+)"\]\s*\{/);
    if (open) { cur = themes[open[1]] = {}; continue; }
    if (line.includes("}")) { cur = null; continue; }
    const d = line.match(/^\s*(--[\w-]+)\s*:\s*(.+?);\s*$/);
    if (cur && d) cur[d[1]] = d[2];
  }
  return themes;
}

const lum = (hex) => {
  const c = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255)
    .map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
  return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
};
const ratio = (a, b) => {
  const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p);
  return (x + 0.05) / (y + 0.05);
};

const themes = parse();

test("three themes with the required tokens", () => {
  assert.deepEqual(Object.keys(themes).sort(), ["paper", "slate", "walnut"]);
  for (const [name, t] of Object.entries(themes)) {
    for (const k of ["--bg", "--panel", "--ink", "--muted", "--accent", "--bad",
                     "--board-light", "--board-dark"]) {
      assert.ok(t[k], `${name} missing ${k}`);
    }
    assert.equal("--grain" in t, name === "walnut", `${name} grain`);
  }
});

for (const name of ["walnut", "slate", "paper"]) {
  test(`${name}: ink on bg and on panel >= 4.5, muted on panel >= 4.5`, () => {
    const t = themes[name];
    assert.ok(ratio(t["--ink"], t["--bg"]) >= 4.5, "ink/bg");
    assert.ok(ratio(t["--ink"], t["--panel"]) >= 4.5, "ink/panel");
    assert.ok(ratio(t["--muted"], t["--panel"]) >= 4.5, "muted/panel");
  });
  test(`${name}: no pure white or black`, () => {
    for (const [k, v] of Object.entries(themes[name])) {
      assert.ok(!/^#(fff|ffffff|000|000000)$/i.test(v), `${name} ${k}=${v}`);
    }
  });
}

test("the focus outline colour (accent) has >= 3:1 against the page and the panel in every theme", () => {
  for (const [name, t] of Object.entries(themes)) {
    for (const bg of ["--bg", "--panel"]) {
      assert.ok(ratio(t["--accent"], t[bg]) >= 3, `${name} accent on ${bg}: ${ratio(t["--accent"], t[bg]).toFixed(2)}`);
    }
  }
});
