import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

const source = readFileSync(
  new URL("../public/jurisai-avukat/background.js", import.meta.url),
  "utf8",
);
function harness(
  run,
  status = {
    ok: true,
    job: { id: "job-1", kind: "pull", state: "running" },
    run: { phase: "Aktarılıyor" },
  },
) {
  const context = vm.createContext({
    pullRun: run,
    Date: { now: () => 20000 },
    textArg: (value) => String(value || ""),
    askTab: async () => structuredClone(status),
  });
  vm.runInContext(
    source.slice(
      source.indexOf("function transferPhase("),
      source.indexOf("async function handlePullFetch("),
    ) +
      source.slice(
        source.indexOf("async function handleBridge("),
        source.indexOf(
          "chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {",
          source.indexOf("async function handleBridge("),
        ),
      ) +
      "\nglobalThis.helpers = {handleBridge, transferPhase};",
    context,
  );
  return context.helpers;
}

test("same live job exposes numeric download progress without credentials or request metadata", async () => {
  const h = harness({
    tabId: 1,
    jobId: "job-1",
    transfer: {
      stage: "download",
      receivedBytes: 10 * 1048576,
      expectedBytes: 20 * 1048576,
      lastDataAt: 10000,
      resumes: 1,
      url: "?secret=private",
      etag: "private",
      cookie: "private",
    },
  });
  const status = await h.handleBridge("BRIDGE_JOB_STATUS", { tabId: 1, jobId: "job-1" });
  assert.match(status.run.phase, /10.0 \/ 20.0 MB/);
  assert.match(status.run.phase, /10 sn yeni veri yok/);
  assert.match(status.run.phase, /sürdürme 1\/2/);
  assert.doesNotMatch(JSON.stringify(status), /private|secret|etag|cookie/);
});

test("another tab, another job, completed job and non-pull status never get this progress", async () => {
  const run = { tabId: 1, jobId: "job-1", transfer: { stage: "upload" } };
  for (const [payload, job] of [
    [
      { tabId: 2, jobId: "job-1" },
      { kind: "pull", state: "running" },
    ],
    [
      { tabId: 1, jobId: "job-2" },
      { kind: "pull", state: "running" },
    ],
    [
      { tabId: 1, jobId: "job-1" },
      { kind: "pull", state: "done" },
    ],
    [
      { tabId: 1, jobId: "job-1" },
      { kind: "tree", state: "running" },
    ],
  ]) {
    const h = harness(run, { ok: true, job, run: { phase: "Aktarılıyor" } });
    assert.equal((await h.handleBridge("BRIDGE_JOB_STATUS", payload)).run.phase, "Aktarılıyor");
  }
});

test("unknown total is explicitly unknown; waiting and upload are distinct phases", () => {
  const { transferPhase } = harness(null);
  assert.match(
    transferPhase({
      stage: "download",
      receivedBytes: 1048576,
      expectedBytes: null,
      lastDataAt: null,
      resumes: 0,
    }),
    /1.0 MB \(toplam boyut bildirilmedi\)/,
  );
  assert.match(transferPhase({ stage: "waiting" }), /yanıt başlıkları bekleniyor/);
  assert.match(transferPhase({ stage: "upload" }), /indirildi; JurisAI'ya kaydediliyor/);
});
