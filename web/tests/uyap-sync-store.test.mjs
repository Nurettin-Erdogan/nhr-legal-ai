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
const report = (key, outcome = "complete") => ({ key, esas: key, birim: "A", outcome, problems: [] });

/** Sahte orkestratör: her dosyada `gate` açılana kadar bekler (koşu "sürerken" durumu incelemek için). */
function world(outcomes = {}, saveReport) {
  const gates = [];
  const saved = { reports: 0, details: 0 };
  const store = compile("../src/lib/uyap-sync-store.ts", {
    "@/lib/steady-timer": { keepAwake: () => () => {} },
    "@/lib/uyap-sync-api": { saveCaseDetail: async () => { saved.details += 1; }, saveSyncReport: async (items) => { saved.reports += items.length; return saveReport ? await saveReport(items) : { saved: items.length, downgraded: [], unmatched: 0 }; } },
    "@/lib/uyap-sync-all": {
      summarize: (reports) => ({ files: reports.length }),
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
