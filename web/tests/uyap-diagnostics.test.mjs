import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import ts from "typescript";

function compile(relative, requires) {
  const source = readFileSync(new URL(relative, import.meta.url), "utf8").replaceAll(
    "import.meta.env",
    "({})",
  );
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  });
  const module = { exports: {} };
  new Function("require", "module", "exports", outputText)(
    (name) => requires[name],
    module,
    module.exports,
  );
  return module.exports;
}

function world(diagnosis = { ok: true, reports: [{ tables: 3, path: "/main/jsp/xxx" }] }) {
  const asked = [];
  const posted = [];
  globalThis.fetch = async (url, options) => {
    posted.push({ url, body: JSON.parse(options.body) });
    return { ok: true };
  };
  const lib = compile("../src/lib/uyap-diagnostics.ts", {
    "@/lib/auth-api": { inMemoryAccessToken: () => "t" },
    "@/lib/uyap-bridge": {
      bridgeRequest: async (type) => {
        asked.push(type);
        return diagnosis;
      },
    },
  });
  return { lib, asked, posted };
}

test("tanınmayan sayfa hatasında yapı özeti bir kez kaydedilir; diğer hatalarda hiçbir şey gönderilmez", async () => {
  const { lib, asked, posted } = world();
  assert.equal(
    await lib.reportUyapProblem("login_required"),
    false,
    "oturum kaybı sayfa düzeni sorunu değildir",
  );
  assert.equal(await lib.reportUyapProblem("no_list", { phase: "liste" }), true);
  assert.equal(
    await lib.reportUyapProblem("no_list", { phase: "liste" }),
    false,
    "aynı sorun türü bir kez",
  );
  assert.deepEqual(asked, ["DIAGNOSE"]);
  assert.equal(posted.length, 1);
  assert.match(posted[0].url, /\/api\/office\/uyap\/diagnostics$/);
  assert.deepEqual(posted[0].body, {
    code: "no_list",
    context: { phase: "liste" },
    reports: [{ tables: 3, path: "/main/jsp/xxx" }],
  });
});

test("eklenti tanı veremezse ya da ağ hatası olursa kullanıcının işi bozulmaz", async () => {
  const failing = world({ ok: false });
  assert.equal(await failing.lib.reportUyapProblem("no_tree"), false);
  assert.equal(failing.posted.length, 0);
  const broken = world();
  globalThis.fetch = async () => {
    throw new Error("ağ yok");
  };
  assert.equal(await broken.lib.reportUyapProblem("open_failed"), false);
});
