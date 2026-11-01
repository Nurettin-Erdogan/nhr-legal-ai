import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
import ts from "typescript";

const require = createRequire(import.meta.url);
function compile(relative) {
  const source = readFileSync(new URL(relative, import.meta.url), "utf8").replace(
    "import.meta.env?.VITE_API_URL",
    "undefined",
  );
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  });
  const module = { exports: {} };
  new Function("require", "module", "exports", outputText)(require, module, module.exports);
  return module.exports;
}

const lib = compile("../src/lib/deep-research.ts");

const step = (overrides = {}) => ({
  key: "mevzuat",
  title: "İlgili mevzuat",
  answer: "Bir yıl çalışma gerekir [K1].",
  grounded: true,
  citations: [
    {
      marker: "K1",
      reference: "İŞ KANUNU m. 14",
      source_url: "https://example.test/x",
      verification: "official",
      source_type: "legislation",
    },
  ],
  error: null,
  ...overrides,
});

test("an unclear grounding flag is never treated as verified", () => {
  for (const grounded of [undefined, null, "true", 1, "yes"]) {
    const parsed = lib.parseResearchState({
      job: null,
      latest: { id: "r", steps: [step({ grounded })] },
    });
    assert.equal(parsed.latest.steps[0].grounded, false);
  }
  assert.equal(
    lib.parseResearchState({ job: null, latest: { id: "r", steps: [step()] } }).latest.steps[0]
      .grounded,
    true,
  );
});

test("citations keep their verification and unsafe or unknown values are neutralised", () => {
  const parsed = lib.parseResearchState({
    job: null,
    latest: {
      id: "r",
      steps: [
        step({
          citations: [
            {
              marker: "K1",
              reference: "A",
              verification: "third_party",
              source_url: "javascript:alert(1)",
            },
            { marker: "K2", reference: "B", verification: "bilinmeyen" },
            { marker: "K3" },
            null,
          ],
        }),
      ],
    },
  });
  const [first, second] = parsed.latest.steps[0].citations;
  assert.equal(parsed.latest.steps[0].citations.length, 2);
  assert.equal(first.verification, "third_party");
  assert.equal(first.sourceUrl, null);
  assert.equal(second.verification, "unknown");
  assert.equal(lib.verificationLabel("third_party"), ""); // olumsuz ibare yok (AGENTS.md, 2026-10-15)
  assert.equal(lib.verificationLabel("official"), "");
  assert.match(lib.verificationLabel("unknown"), /bilinmiyor/);
});

test("live and saved research citations preserve source identity and excerpt for the common reader", () => {
  const source_id = "12345678-1234-1234-1234-123456789abc";
  const item = step({
    citations: [
      {
        marker: "K1",
        reference: "Karar",
        source_id,
        excerpt: "Kısa pasaj",
        source_type: "court_decision",
        verification: "third_party",
      },
    ],
  });
  const parsed = lib.parseResearchState({
    job: { id: "job", steps: [item] },
    latest: { id: "saved", steps: [item] },
  });
  for (const list of [parsed.job.steps, parsed.latest.steps]) {
    assert.equal(list[0].citations[0].sourceId, source_id);
    assert.equal(list[0].citations[0].excerpt, "Kısa pasaj");
    assert.equal(list[0].citations[0].verification, "third_party");
  }
});

test("research shows the actual model, including local fallback, without inventing it for old reports", () => {
  const parsed = lib.parseResearchState({
    job: { id: "j", steps: [step({ provider: "deepseek", model: "deepseek-v4-pro" })] },
    latest: { id: "r", steps: [step({ provider: "qwen", model: "local-qwen" }), step()] },
  });
  assert.equal(parsed.job.steps[0].provider, "deepseek");
  assert.equal(parsed.job.steps[0].model, "deepseek-v4-pro");
  assert.equal(parsed.latest.steps[0].model, "local-qwen");
  assert.equal(parsed.latest.steps[1].model, null);
  const component = readFileSync(
    new URL("../src/components/DeepResearch.tsx", import.meta.url),
    "utf8",
  );
  assert.match(component, /step\.model &&/);
  assert.match(component, /Yanıt modeli: \{step\.model\}/);
});

test("a malformed state is rejected and an unknown job state keeps polling", () => {
  assert.equal(lib.parseResearchState(null), null);
  assert.equal(lib.parseResearchState({ job: { state: "running" }, latest: null }), null);
  assert.deepEqual(lib.parseResearchState({ job: null, latest: null }), {
    job: null,
    latest: null,
  });
  assert.equal(
    lib.parseResearchState({ job: { id: "j", state: "weird" }, latest: null }).job.state,
    "running",
  );
  const steps = lib.parseResearchState({
    job: { id: "j", state: "done", steps: [step(), { key: "x" }, null] },
    latest: null,
  }).job.steps;
  assert.equal(steps.length, 1);
});

test("progress lines explain running, failed and partially failed jobs", () => {
  const job = (state, extra = {}) => ({
    id: "j",
    state,
    stage: "",
    total: 3,
    done: 1,
    error: null,
    steps: [],
    savedId: null,
    ...extra,
  });
  assert.equal(
    lib.progressLine(job("running", { stage: "2/3: Yargı kararları aranıyor ve yazılıyor…" })),
    "2/3: Yargı kararları aranıyor ve yazılıyor…",
  );
  assert.equal(lib.progressLine(job("running")), "1/3 başlık tamamlandı…");
  assert.equal(
    lib.progressLine(job("failed", { error: "Hiçbir başlık için cevap üretilemedi." })),
    "Hiçbir başlık için cevap üretilemedi.",
  );
  assert.equal(
    lib.progressLine(job("done", { steps: [{ error: null }, { error: null }, { error: null }] })),
    "3 başlık tamamlandı.",
  );
  assert.equal(
    lib.progressLine(job("done", { steps: [{ error: null }, { error: "x" }, { error: null }] })),
    "3 başlıktan 2 tanesi tamamlandı; 1 başlık için cevap üretilemedi.",
  );
});

test("a question must be long enough and not too long", () => {
  assert.equal(lib.canStart("kısa soru"), false);
  assert.equal(lib.canStart("   kıdem tazminatı şartları   "), true);
  assert.equal(lib.canStart("a".repeat(lib.MAX_QUESTION + 1)), false);
  assert.equal(lib.canStart("a".repeat(lib.MAX_QUESTION)), true);
});

test("requests send the trimmed question and surface server messages", async () => {
  const calls = [];
  const respond = (status, body) => async (url, init) => {
    calls.push({ url: String(url), init });
    return { ok: status >= 200 && status < 300, status, json: async () => body };
  };
  const original = globalThis.fetch;
  try {
    globalThis.fetch = respond(202, { job_id: "j1", steps: [] });
    assert.deepEqual(
      await lib.startResearch("  kıdem tazminatı şartları nelerdir  ", { token: "tok" }),
      { jobId: "j1" },
    );
    assert.match(calls[0].url, /\/api\/office-ai\/deep-research$/);
    assert.equal(calls[0].init.method, "POST");
    assert.deepEqual(JSON.parse(calls[0].init.body), {
      question: "kıdem tazminatı şartları nelerdir",
    });
    assert.equal(calls[0].init.headers.Authorization, "Bearer tok");

    globalThis.fetch = respond(409, {
      detail: "Devam eden bir araştırmanız var; bitmesini bekleyin.",
    });
    await assert.rejects(
      lib.startResearch("kıdem tazminatı şartları"),
      (error) => error.status === 409 && /Devam eden/.test(error.message),
    );
    globalThis.fetch = respond(200, { job: null, latest: null });
    assert.deepEqual(await lib.loadResearchState(), { job: null, latest: null });
    globalThis.fetch = respond(200, { job: { state: "running" }, latest: null });
    await assert.rejects(lib.loadResearchState(), (error) => /geçersiz/.test(error.message));
    globalThis.fetch = respond(401, {});
    await assert.rejects(lib.loadResearchState(), (error) => /Oturumunuz/.test(error.message));
    globalThis.fetch = async () => {
      throw new TypeError("network");
    };
    await assert.rejects(lib.loadResearchState(), (error) => /ulaşılamadı/.test(error.message));
  } finally {
    globalThis.fetch = original;
  }
});
