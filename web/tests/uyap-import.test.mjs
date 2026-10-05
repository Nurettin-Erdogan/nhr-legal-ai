import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { webcrypto } from "node:crypto";
import test from "node:test";
import ts from "typescript";

const require = createRequire(import.meta.url);
globalThis.crypto ??= webcrypto;

function model({ stored = [], sample = (name, bytes) => new TextDecoder().decode(bytes), uploadError = null } = {}) {
  const source = readFileSync(new URL("../src/lib/uyap-import.ts", import.meta.url), "utf8");
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  });
  const storage = {
    from: () => ({
      upload: async () => ({ error: uploadError }),
      download: async (path) => ({ data: new Blob([stored.find((row) => row.storage_path === path)?.bytes ?? ""]), error: null }),
      remove: async () => ({ error: null }),
    }),
  };
  const supabase = {
    storage,
    from: () => {
      const filters = {};
      return {
        select() { return this; },
        eq(key, value) { filters[key] = value; return this; },
        is(key, value) { filters[key] = value; return this; },
        order() { return this; },
        async range(from, to) {
          return { data: stored.filter((row) => Object.entries(filters).every(([key, value]) => row[key] === value)).slice(from, to + 1), error: null };
        },
        async insert(row) { stored.push(row); return { error: null }; },
      };
    },
  };
  const uyap = {
    extractTextSample: async (name, bytes) => sample(name, bytes),
    parseUyapMeta: (_name, text) => ({ uyap_file_no: text.match(/2024\/\d+/)?.[0] ?? "2024/1" }),
    storagePathFor: (_owner, name) => `path-${stored.length}-${name}`,
  };
  const module = { exports: {} };
  new Function("require", "module", "exports", outputText)(
    (id) => ({ "@/integrations/supabase/client": { supabase }, "@/lib/uyap": uyap })[id] ?? require(id),
    module,
    module.exports,
  );
  return module.exports;
}

const bytes = (value) => new TextEncoder().encode(value);

test("same filename in different cases is imported twice", async () => {
  const result = await model().importEntries("owner", [
    { name: "ek.pdf", data: bytes("2024/1 ilk dava") },
    { name: "ek.pdf", data: bytes("2024/2 ikinci dava") },
  ]);
  assert.deepEqual(result, { found: 2, inserted: 2, skipped: 0, failed: 0, errors: [] });
});

test("an exactly identical archive document is skipped", async () => {
  const stored = [{ owner_id: "owner", file_name: "ek.odt", source: "uyap", uyap_file_no: "2024/1", storage_path: "old", bytes: bytes("old zip") }];
  const result = await model({ stored, sample: () => "2024/1 Aynı metin" }).importEntries("owner", [
    { name: "ek.odt", data: bytes("old zip") },
  ]);
  assert.equal(result.skipped, 1);
  assert.equal(result.inserted, 0);
  assert.equal(result.failed, 0);
});

test("different bytes are preserved when an archive has no stable evidence identity", async () => {
  const stored = [{ owner_id: "owner", file_name: "ek.odt", source: "uyap", uyap_file_no: "2024/1", storage_path: "old", bytes: bytes("old zip") }];
  const result = await model({ stored, sample: () => "2024/1 Aynı metin" }).importEntries("owner", [
    { name: "ek.odt", data: bytes("new zip metadata") },
  ]);
  assert.equal(result.inserted, 1);
  assert.equal(result.skipped, 0);
});

test("duplicate lookup continues past the first hundred candidates", async () => {
  const stored = Array.from({ length: 101 }, (_, index) => ({
    owner_id: "owner", file_name: "ek.pdf", source: "uyap", uyap_file_no: "2024/1",
    storage_path: `old-${index}`, bytes: bytes(index === 100 ? "2024/1 actual" : `2024/1 other-${index}`),
  }));
  const result = await model({ stored }).importEntries("owner", [
    { name: "ek.pdf", data: bytes("2024/1 actual") },
  ]);
  assert.equal(result.skipped, 1);
  assert.equal(result.inserted, 0);
});

test("storage failures are reported as failures, not duplicates", async () => {
  const result = await model({ uploadError: { message: "storage unavailable" } }).importEntries("owner", [
    { name: "ek.pdf", data: bytes("2024/1 gerçek belge") },
  ]);
  assert.equal(result.skipped, 0);
  assert.equal(result.failed, 1);
  assert.match(result.errors[0], /storage unavailable/);
});
