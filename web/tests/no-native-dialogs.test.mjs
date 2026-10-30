import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

// Yayında tarayıcının "localhost:3000 web sitesinin mesajı" penceresi görünmesin: onaylar components/ConfirmDialog ile sorulur
// (2026-10-24).
const SRC = fileURLToPath(new URL("../src", import.meta.url));

function files(dir) {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    return statSync(path).isDirectory() ? files(path) : /\.(tsx?|jsx?)$/.test(name) ? [path] : [];
  });
}

test("no page uses the browser's own confirm, alert or prompt window", () => {
  const offenders = files(SRC).filter((path) => {
    const code = readFileSync(path, "utf8").replace(/\/\*[\s\S]*?\*\/|\/\/.*$/gm, "");
    return /(?:window\.|[^\w.])(?:confirm|alert|prompt)\(/.test(code);
  });
  assert.deepEqual(
    offenders.map((path) => path.slice(SRC.length + 1)),
    [],
  );
});
