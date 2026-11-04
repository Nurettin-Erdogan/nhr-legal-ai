import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import ts from "typescript";

function setup(responses) {
  const source = readFileSync(new URL("../src/lib/auth-api.ts", import.meta.url), "utf8").replace(
    "import.meta.env.VITE_API_URL",
    '"http://test"',
  );
  const compiled = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS },
  }).outputText;
  const mod = { exports: {} };
  const calls = [];
  const fetch = async (url, init) => {
    calls.push({ url, init });
    const next = responses.shift();
    if (next instanceof Error) throw next;
    return new Response(JSON.stringify(next?.body ?? {}), { status: next?.status ?? 200 });
  };
  new Function("exports", "fetch", "setTimeout", compiled)(mod.exports, fetch, (fn) => {
    fn();
  });
  return { api: mod.exports, calls };
}

test("session recovers after restart/proxy failure without using cached identity", async () => {
  const { api, calls } = setup([
    { status: 502 },
    new Error("offline"),
    { body: { user: { id: "owner" } } },
  ]);
  assert.equal((await api.currentUser()).id, "owner");
  assert.equal(calls.length, 3);
  assert.ok(calls.every(({ init }) => init.credentials === "include" && init.signal));
});

test("forbidden and expired sessions are never retried or treated as authenticated", async () => {
  for (const status of [401, 403]) {
    const { api, calls } = setup([{ status }]);
    if (status === 401) assert.equal(await api.currentUser(), null);
    else await assert.rejects(api.currentUser());
    assert.equal(calls.length, 1);
  }
});

test("persistent outage ends after four tries; login writes are never retried", async () => {
  const { api, calls } = setup(Array.from({ length: 4 }, () => ({ status: 503 })));
  await assert.rejects(api.currentUser());
  assert.equal(calls.length, 4);
  const login = setup([{ status: 502 }]);
  await assert.rejects(login.api.login("test@example.invalid", "test-only"));
  assert.equal(login.calls.length, 1);
});
