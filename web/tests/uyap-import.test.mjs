import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
import ts from "typescript";
import { zipSync, strToU8 } from "fflate";

const require = createRequire(import.meta.url);
function compile(path, dependencies = {}) {
  const source = readFileSync(new URL(path, import.meta.url), "utf8").replaceAll(
    "import.meta.env",
    "({})",
  );
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  });
  const module = { exports: {} };
  new Function("require", "module", "exports", outputText)(
    (id) => dependencies[id] ?? require(id),
    module,
    module.exports,
  );
  return module.exports;
}
const uyap = compile("../src/lib/uyap.ts");
function imports(upload = async () => ({ ok: true, id: "id", duplicate: false })) {
  return compile("../src/lib/uyap-import.ts", {
    "@/lib/uyap": uyap,
    "@/lib/office-api": { importUyapDocument: upload },
  });
}
const bytes = strToU8;

test("single ODT and mixed PDF/ODT archives include every document", async () => {
  const { expandDroppedFiles } = imports();
  const odt = zipSync({ "content.xml": bytes("<p>Evrak</p>") });
  const single = await expandDroppedFiles([new File([odt], "evrak.odt")]);
  assert.equal(single.length, 1);
  const archive = zipSync({ "evrak.pdf": bytes("%PDF synthetic"), "evrak.odt": odt });
  const entries = await expandDroppedFiles([new File([archive], "uyap.zip")]);
  assert.deepEqual(entries.map((x) => x.name).sort(), ["evrak.odt", "evrak.pdf"]);
});

test("manual extension allowlist matches the server storage formats", () => {
  const source = readFileSync(new URL("../../api/uyap_meta.py", import.meta.url), "utf8");
  const declaration = source.slice(
    source.indexOf("ALLOWED_EXTENSIONS ="),
    source.indexOf("MAX_FILE_BYTES ="),
  );
  const server = [...declaration.matchAll(/"([a-z0-9]+)"/g)].map((m) => m[1]).sort();
  assert.deepEqual([...uyap.ALLOWED_EXTENSIONS].sort(), server);
  const page = readFileSync(
    new URL("../src/routes/_authenticated/dashboard.uyap.tsx", import.meta.url),
    "utf8",
  );
  assert.match(page, /accept=\{ALLOWED_EXTENSIONS\.map/); // Picker cannot drift from drag/drop.
});

test("unsupported and empty files are reported, never silently dropped", async () => {
  const importer = imports(() => {
    throw new Error("Must not upload rejected entries");
  });
  const archive = zipSync({ "virus.exe": bytes("MZ"), "empty.txt": bytes("") });
  const entries = await importer.expandDroppedFiles([
    new File([archive], "uyap.zip"),
    new File([bytes("MZ")], "bad.exe"),
  ]);
  const result = await importer.importEntries("ignored-owner", entries);
  assert.equal(result.found, 3);
  assert.equal(result.failed, 3);
  assert.equal(result.errors.length, 3);
});

test("invalid and leap-year dates are checked without destroying ISO separators", () => {
  for (const [name, expected] of [
    ["odeme_31.02.2025.pdf", null],
    ["odeme_29.02.2025.pdf", null],
    ["odeme_29.02.2024.pdf", "2024-02-29"],
    ["odeme_2025-10-05.pdf", "2025-10-05"],
    ["odeme_00.12.2025.pdf", null],
    ["odeme_01.13.2025.pdf", null],
  ])
    assert.equal(uyap.parseUyapMeta(name).doc_date, expected, name);
});

test("server duplicate decisions and original archive paths are honored", async () => {
  const calls = [];
  const importer = imports(async (...args) => {
    calls.push(args);
    return { ok: true, id: "id", duplicate: calls.length > 1 };
  });
  const entries = [
    { name: "2024/1/ek.txt", data: bytes("same") },
    { name: "2024/1/ek.txt", data: bytes("same") },
  ];
  const result = await importer.importEntries("never-transmitted-owner", entries, {
    syncRunId: "run",
  });
  assert.deepEqual(result, { found: 2, inserted: 1, skipped: 1, failed: 0, errors: [] });
  assert.equal(calls[0][0], "2024/1/ek.txt");
  assert.equal(calls[0][2], "run");
  assert.equal(calls[0].length, 3); // No caller-supplied owner, checksum or evidence ID.
});

test("failed requests are failures, and the next document still imports", async () => {
  let call = 0;
  const importer = imports(async () => {
    if (++call === 1) throw new Error("storage unavailable");
    return { ok: true, id: "id", duplicate: false };
  });
  const result = await importer.importEntries("owner", [
    { name: "ek.txt", data: bytes("1") },
    { name: "ek2.txt", data: bytes("2") },
  ]);
  assert.equal(result.failed, 1);
  assert.equal(result.inserted, 1);
  assert.equal(result.skipped, 0);
  assert.match(result.errors[0], /storage unavailable/);
});

test("manual multipart API is authenticated and sends no client owner or hash", async () => {
  const api = compile("../src/lib/office-api.ts", {
    "@/lib/auth-api": { inMemoryAccessToken: () => "test-access" },
    "@/lib/db": {},
    "@/lib/uyap": uyap,
  });
  const original = globalThis.fetch;
  try {
    globalThis.fetch = async (url, init) => {
      assert.equal(url, "http://localhost:8766/api/office/uyap/import");
      assert.equal(init.credentials, "include");
      assert.equal(init.headers.Authorization, "Bearer test-access");
      assert.equal(init.headers["Content-Type"], undefined); // Browser owns multipart boundary.
      assert.deepEqual([...init.body.keys()], ["file", "path", "syncRunId"]);
      assert.equal(init.body.get("file").name, "evrak.odt");
      assert.equal(init.body.get("path"), "2024/99/evrak.odt");
      return new Response(JSON.stringify({ ok: true, duplicate: false, id: "doc" }));
    };
    await api.importUyapDocument("2024/99/evrak.odt", bytes("odt"), "run");
    globalThis.fetch = async () =>
      new Response(JSON.stringify({ detail: "Aktarım kaydı bulunamadı" }), { status: 404 });
    await assert.rejects(api.importUyapDocument("evrak.txt", bytes("text")), /Aktarım kaydı/);
    globalThis.fetch = async () => new Response(JSON.stringify({ ok: true }));
    await assert.rejects(
      api.importUyapDocument("evrak.txt", bytes("text")),
      /geçersiz aktarım yanıtı/,
    );
  } finally {
    globalThis.fetch = original;
  }
});
