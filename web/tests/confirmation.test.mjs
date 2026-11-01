import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import ts from "typescript";

function registry() {
  const source = readFileSync(new URL("../src/lib/confirmation.ts", import.meta.url), "utf8");
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  });
  const module = { exports: {} };
  new Function("module", "exports", outputText)(module, module.exports);
  return module.exports;
}

test("confirmation without a mounted host refuses instead of approving", async () => {
  assert.equal(await registry().confirmAction({ title: "Delete?" }), false);
});

test("confirmation resolves only through the registered host", async () => {
  const store = registry();
  let request;
  const cleanup = store.registerConfirmationHost((value) => {
    request = value;
  });
  const result = store.confirmAction({ title: "Delete?", destructive: true });
  assert.equal(request.destructive, true);
  request.resolve(false);
  assert.equal(await result, false);
  cleanup();
  assert.equal(await store.confirmAction({ title: "Unmounted" }), false);
});

test("old host cleanup cannot unregister a newer host", async () => {
  const store = registry();
  const oldCleanup = store.registerConfirmationHost(() => assert.fail("old host called"));
  const cleanup = store.registerConfirmationHost((request) => request.resolve(true));
  oldCleanup();
  assert.equal(await store.confirmAction({ title: "Current host" }), true);
  cleanup();
});
