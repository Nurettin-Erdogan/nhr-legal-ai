import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import ts from "typescript";

function compile(relative, requires) {
  const source = readFileSync(new URL(relative, import.meta.url), "utf8");
  const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } });
  const module = { exports: {} };
  new Function("require", "module", "exports", outputText)((name) => requires[name], module, module.exports);
  return module.exports;
}

const liste = { items: [{ key: "k1", esas: "2025/1", birim: "A" }, { key: "k2", esas: "2025/2", birim: "A" }], complete: true };
const report = (key, outcome = "complete") => ({ key, esas: key, birim: "A", yargiTuru: "", outcome, problems: [], declared: 0, found: outcome === "complete" ? 1 : 0, stored: outcome === "complete" ? 1 : 0, sent: 0, missing: 0, pulls: 0 });
const runReport = compile("../src/lib/uyap-run-report.ts", { "@/lib/uyap-sync-all": { summarize: reports => ({ files: reports.length }) } });

/** Sahte orkestratör: her dosyada `gate` açılana kadar bekler (koşu "sürerken" durumu incelemek için). */
function world(outcomes = {}, saveReport, saveAudit, accountRefusal, identityOnRelist) {
  const gates = [];
  const saved = { reports: 0, details: 0, checkpoints: [] };
  const store = compile("../src/lib/uyap-sync-store.ts", {
    "@/lib/steady-timer": { keepAwake: () => () => {} },
    "@/lib/uyap-diagnostics": { reportUyapProblem: async () => false },
    "@/lib/uyap-bridge": { listUyapDosyalari: async () => { saved.relists = (saved.relists ?? 0) + 1; return identityOnRelist ? { ok: true, liste: { ...liste, identity: identityOnRelist } } : { ok: false }; } },
    "@/lib/uyap-run-report": runReport,
    "@/lib/uyap-sync-api": { checkUyapAccount: async (identity) => { saved.identity = identity; saved.accountChecks = (saved.accountChecks ?? 0) + 1; if (accountRefusal) throw new Error(accountRefusal); return "same"; }, saveAuditRun: async checkpoint => { saved.checkpoints.push(checkpoint); return saveAudit ? await saveAudit(checkpoint) : { run: { reports: checkpoint.reports } }; }, saveCaseDetail: async () => { saved.details += 1; }, saveSyncReport: async (items) => { saved.reports += items.length; return saveReport ? await saveReport(items) : { saved: items.length, downgraded: [], unmatched: 0 }; } },
    "@/lib/uyap-sync-all": {
      summarize: (reports) => ({ files: reports.length }),
      blankReport: d => report(d.key, "pending"),
      toServerItems: (reports) => reports.map((r) => ({ esas: r.esas })),
      syncAll: async (items, options) => {
        const list = options.only ? items.filter((i) => options.only.has(i.key)) : items;
        const reports = [];
        for (let index = 0; index < list.length; index += 1) {
          options.onProgress({ index, total: list.length, phase: "Evrak aktarılıyor", report: report(list[index].key, "pending") });
          await new Promise((resolve) => gates.push(resolve));
          if (options.signal.aborted) return { reports, summary: { files: list.length }, aborted: true };
          reports.push(report(list[index].key, outcomes[list[index].key] ?? "complete"));
        }
        return { reports, summary: { files: list.length }, aborted: false };
      },
    },
  });
  return { store, gates, saved };
}
const tick = () => new Promise((resolve) => setTimeout(resolve, 0));

test("run history writes an initial checkpoint and final report including all files", async () => {
  const { store, gates, saved } = world({ k2: "failed" });
  const done = store.startSync(liste, undefined, false);
  await tick(); gates.shift()(); await tick(); gates.shift()(); await done;
  assert.equal(saved.checkpoints[0].finished, false);
  assert.deepEqual(saved.checkpoints[0].reports.map(r => r.outcome), ["pending", "pending"]);
  const final = saved.checkpoints.at(-1);
  assert.equal(final.finished, true);
  assert.equal(final.verify_only, true);
  assert.deepEqual(final.reports.map(r => r.outcome), ["complete", "failed"]);
  assert.equal(store.getSyncState().savedVersion, 1);
});

test("history save failure does not silently become a durable success", async () => {
  const { store, gates } = world({}, undefined, async () => { throw new Error("Tam koşu raporu kaydedilemedi"); });
  const finished = [];
  store.onSyncFinished(e => finished.push(e));
  const done = store.startSync(liste, new Set(["k1"]));
  await tick(); gates.shift()(); await done;
  assert.equal(store.getSyncState().running, false);
  assert.equal(store.getSyncState().saveNote.kind, "warn");
  assert.equal(finished[0].saveWarning, true);
});

test("koşu bileşenden bağımsız sürer: sayfadan çıkılıp dönülse de ilerleme ve liste yerindedir", async () => {
  const { store, gates, saved } = world();
  const seen = [];
  const unsubscribe = store.subscribeSync(() => seen.push(store.getSyncState().progress?.index));
  const done = store.startSync(liste);
  await tick();
  assert.equal(store.getSyncState().running, true);
  assert.equal(store.getSyncState().progress.name, "k1 · A");

  unsubscribe(); // kullanıcı başka sayfaya geçti: bileşen kaldırıldı, dinleyen yok
  gates.shift()();
  await tick();
  // Dönünce (yeni bileşen aynı depoyu okur) koşu kaldığı yerden görünür, sıfırlanmamıştır.
  const back = store.getSyncState();
  assert.equal(back.running, true);
  assert.deepEqual([back.progress.index, back.progress.total, back.live.length], [1, 2, 2]);
  assert.equal(back.liste, liste);

  gates.shift()();
  await done;
  const end = store.getSyncState();
  assert.deepEqual([end.running, end.progress, end.run.reports.length, saved.reports], [false, null, 2, 2]);
  assert.equal(end.saveNote.kind, "ok");
  assert.equal(end.savedVersion, 1);
});

test("yalnız eksikler yeniden denenince önceki başarılı dosyalar toplam raporda korunur", async () => {
  const outcomes = { k2: "failed" };
  const { store, gates } = world(outcomes);
  let done = store.startSync(liste);
  await tick(); gates.shift()();
  await tick(); gates.shift()();
  await done;
  assert.deepEqual(store.getSyncState().run.reports.map((r) => r.outcome), ["complete", "failed"]);
  outcomes.k2 = "complete";
  done = store.startSync(liste, new Set(["k2"]));
  await tick(); gates.shift()();
  await done;
  assert.deepEqual(store.getSyncState().run.reports.map((r) => [r.key, r.outcome]), [["k1", "complete"], ["k2", "complete"]]);
  assert.equal(store.getSyncState().run.summary.files, 2);
});

test("koşu sürerken ikinci koşu başlamaz ve liste değiştirilemez; durdurma çalışır", async () => {
  const { store, gates } = world();
  const done = store.startSync(liste);
  await tick();
  await store.startSync(liste); // yok sayılır
  assert.equal(gates.length, 1);
  store.setListe(null);
  assert.equal(store.getSyncState().liste, liste);

  store.stopSync();
  gates.shift()();
  await done;
  assert.deepEqual([store.getSyncState().running, store.getSyncState().run.aborted], [false, true]);
  store.setListe(null); // koşu bitince liste yeniden değiştirilebilir
  assert.equal(store.getSyncState().liste, null);
});

test("koşu bitince bildirim dinleyicisi bir kez çağrılır (kullanıcı başka sayfada olsa da)", async () => {
  const { store, gates } = world();
  const finished = [];
  store.onSyncFinished((event) => finished.push([event.run.reports.length, event.pull]));
  const done = store.startSync(liste, new Set(["k2"]), false);
  await tick();
  assert.equal(store.getSyncState().verifyOnly, true);
  gates.shift()();
  await done;
  assert.deepEqual(finished, [[1, false]]);
});

test("sunucu doğrulaması kaydedilirken ikinci koşu başlayamaz; bildirim kayıt sonucunu bekler", async () => {
  let finishSave;
  const { store, gates } = world({}, () => new Promise((resolve) => { finishSave = resolve; }));
  const finished = [];
  store.onSyncFinished((event) => finished.push(event));
  const done = store.startSync(liste, new Set(["k1"]));
  await tick(); gates.shift()(); await tick();
  assert.equal(store.getSyncState().running, true);
  assert.match(store.getSyncState().progress.phase, /kaydediliyor/);
  await store.startSync(liste);
  assert.equal(gates.length, 0);
  assert.equal(finished.length, 0);
  finishSave({ saved: 1, downgraded: [], unmatched: 0 });
  await done;
  assert.equal(store.getSyncState().running, false);
  assert.equal(finished.length, 1);
  assert.equal(finished[0].saveWarning, false);
});

test("sunucu eksiksizliği reddederse rapor düşürülür; eksik veya bozuk kayıt yanıtı başarı bildirimi vermez", async () => {
  for (const result of [
    { saved: 1, downgraded: ["k1 · A"], unmatched: 0 },
    { saved: 0, downgraded: [], unmatched: 1 },
    new Error("Sunucuya ulaşılamadı"),
  ]) {
    const { store, gates } = world({}, async () => { if (result instanceof Error) throw result; return result; });
    const finished = [];
    store.onSyncFinished((event) => finished.push(event));
    const done = store.startSync(liste, new Set(["k1"]));
    await tick(); gates.shift()(); await done;
    assert.equal(store.getSyncState().saveNote.kind, "warn");
    assert.equal(finished[0].saveWarning, true);
    if (!(result instanceof Error) && result.downgraded.length) {
      assert.equal(store.getSyncState().run.reports[0].outcome, "incomplete");
      assert.match(store.getSyncState().run.reports[0].problems[0], /Sunucu.*doğrulamadı/);
    }
  }
});

function fakeSession() {
  const data = new Map();
  globalThis.sessionStorage = { getItem: (k) => (data.has(k) ? data.get(k) : null), setItem: (k, v) => data.set(k, String(v)), removeItem: (k) => data.delete(k) };
  return data;
}

test("account change cancels the old run, clears resume and prevents old reports being written as new owner", async () => {
  fakeSession();
  const { store, gates, saved } = world();
  store.setSyncOwner("alice");
  const done = store.startSync(liste);
  await tick();
  assert.ok(store.readResume());
  store.setSyncOwner("bob");
  assert.equal(store.getSyncState().liste, null);
  assert.equal(store.getSyncState().run, null);
  assert.equal(store.readResume(), null);
  gates.shift()();
  await done;
  assert.equal(saved.checkpoints.length, 1, "only Alice's initial checkpoint was sent before the account switch");
  assert.equal(saved.reports, 0);
  assert.equal(store.getSyncState().run, null);
  delete globalThis.sessionStorage;
});

test("sayfa yenilenirse koşu kalan dosyalarla kaldığı yerden sürer; biten ya da durdurulan koşu kendiliğinden başlamaz", async () => {
  fakeSession();
  const first = world();
  first.store.startSync(liste);
  await tick();
  first.gates.shift()(); // k1 bitti, k2'ye geçildi
  await tick();
  assert.deepEqual(first.store.readResume(), { pull: true, pending: ["k2"] });

  // Sayfa yenilendi: yeni modül örneği (durum boş), oturum deposu duruyor.
  const second = world();
  assert.equal(second.store.getSyncState().running, false);
  assert.equal(second.store.resumeIfInterrupted(liste), true);
  await tick();
  assert.deepEqual([second.store.getSyncState().progress.total, second.store.getSyncState().progress.name], [1, "k2 · A"]); // yalnız kalan dosya
  second.gates.shift()();
  await tick(); await tick();
  assert.equal(second.store.readResume(), null); // bitti: kayıt silindi
  assert.equal(world().store.resumeIfInterrupted(liste), false);

  // Kullanıcı durdurursa da kayıt silinir.
  const third = world();
  const done = third.store.startSync(liste);
  await tick();
  third.store.stopSync();
  third.gates.shift()();
  await done;
  assert.equal(third.store.readResume(), null);
  // Liste değişmiş ve kalan dosyalar artık yoksa hiçbir şey başlamaz, kayıt temizlenir.
  globalThis.sessionStorage.setItem("jurisai.uyap.sync.resume", JSON.stringify({ pull: true, pending: ["yok"] }));
  assert.equal(world().store.resumeIfInterrupted(liste), false);
  assert.equal(globalThis.sessionStorage.getItem("jurisai.uyap.sync.resume"), null);
  delete globalThis.sessionStorage;
});

test("UYAP kişisi bu hesaba bağlı değilse koşu başlamaz ve koşu kaydı dahil hiçbir şey yazılmaz", async () => {
  const { store, gates, saved } = world({}, undefined, undefined, "UYAP'ta giriş yapan kişi (M*** K***) bu JurisAI hesabına bağlı değil.");
  await store.startSync(liste);
  assert.equal(saved.accountChecks, 1);
  assert.equal(gates.length, 0, "orkestratör hiç çalışmadı");
  assert.deepEqual([saved.checkpoints.length, saved.details, saved.reports], [0, 0, 0]);
  const state = store.getSyncState();
  assert.equal(state.running, false);
  assert.match(state.run.stoppedBecause, /bağlı değil/);
});

test("eski sürümle alınmış listede UYAP kişisi yoksa liste bir kez yeniden okunup kişi oradan alınır", async () => {
  const person = { fingerprint: "a".repeat(64), kind: "tc", portal: "vatandas", display: "AYŞE YILMAZ" };
  const { store, gates, saved } = world({}, undefined, undefined, undefined, person);
  const done = store.startSync(liste);
  await tick(); gates.shift()(); await tick(); gates.shift()(); await done;
  assert.equal(saved.relists, 1);
  assert.deepEqual(saved.identity, person);
});

test("listede UYAP kişisi varsa liste yeniden okunmaz", async () => {
  const person = { fingerprint: "b".repeat(64), kind: "tc", portal: "vatandas", display: "MEHMET KAYA" };
  const { store, gates, saved } = world();
  const done = store.startSync({ ...liste, identity: person });
  await tick(); gates.shift()(); await tick(); gates.shift()(); await done;
  assert.equal(saved.relists, undefined);
  assert.deepEqual(saved.identity, person);
});
