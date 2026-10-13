import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import ts from "typescript";

function compile(relative, requires = {}) {
  const source = readFileSync(new URL(relative, import.meta.url), "utf8");
  const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } });
  const module = { exports: {} };
  new Function("require", "module", "exports", outputText)((name) => requires[name], module, module.exports);
  return module.exports;
}

// Köprünün gerçek işlevleri bu testte kullanılmaz: orkestratör sahte köprüyle (SyncBridge) denenir.
const sync = compile("../src/lib/uyap-sync-all.ts", {
  "@/lib/uyap-bridge": { startPullJob() {}, startTreeJob() {}, stopJob() {}, waitForJob() {} },
  "@/lib/steady-timer": { steadySleep: () => Promise.resolve() },
});

const dosya = (n, extra = {}) => ({ key: `k${n}`, esas: `2025/${n}`, birim: "Ankara İcra Dairesi", yargiTuru: "İcra", role: "", tur: "", acilis: "", durum: "", cells: [], ...extra });

test("stuck read is recovered once on the same tab, then freshly verified without uploading", async () => {
  const world = { k1: { ids: ["a"], treeFails: 9 } };
  const bridge = fakeBridge(world);
  bridge.stored.set("k1", new Set(["a"]));
  const recoveries = [], pins = [];
  const start = bridge.startTree;
  bridge.startTree = (key, type, tab) => { pins.push(tab); return start(key, type); };
  bridge.recoverRead = async (tab, job) => { recoveries.push([tab, job]); world.k1.treeFails = 0; return { ok: true, tabId: tab }; };
  const { report } = await sync.syncDosya(dosya(1), { bridge, pull: false });
  assert.equal(report.outcome, "complete");
  assert.equal(recoveries.length, 1);
  assert.deepEqual(pins, [undefined, 1, 1, 1]);
  assert.deepEqual(bridge.calls.pulls, []);
});
test("recovery budget is bounded across the whole run; a reload alone never proves success", async () => {
  const bridge = fakeBridge({ k1: { ids: [], treeFails: 99 }, k2: { ids: [], treeFails: 99 }, k3: { ids: [], treeFails: 99 } });
  let recoveries = 0;
  bridge.recoverRead = async tab => { recoveries++; return { ok: true, tabId: tab }; };
  const result = await sync.syncAll([1, 2, 3].map(n => dosya(n)), { bridge, pull: false, detail: false });
  assert.equal(recoveries, 2);
  assert.equal(result.summary.failed, 3);
  assert.equal(result.summary.complete, 0);
});

test("the full run pins every first tree and detail read to the listing tab", async () => {
  const bridge = fakeBridge({ k1: { ids: ["a"] }, k2: { ids: ["b"], treeFails: 3 } });
  bridge.stored.set("k1", new Set(["a"]));
  const pins = [];
  for (const method of ["startTree", "startDetail"]) {
    const original = bridge[method];
    bridge[method] = async (key, type, tabId) => {
      pins.push([method, key, tabId]);
      const result = await original(key, type);
      return result.ok ? { ...result, tabId } : result;
    };
  }
  await sync.syncAll([dosya(1), dosya(2)], { bridge, tabId: 37, pull: false });
  assert.ok(pins.some(([kind, key]) => kind === "startTree" && key === "k2"));
  assert.ok(pins.some(([kind, key]) => kind === "startDetail" && key === "k2"));
  assert.ok(pins.every(([, , tabId]) => tabId === 37));
});
test("login loss, unknown jobs, stale identity and cancellation are never auto-reloaded", async () => {
  for (const code of ["login_required", "unknown_job", "stale", "aborted"]) {
    const bridge = fakeBridge({ k1: { ids: [], startError: code } });
    bridge.recoverRead = () => { throw new Error("unsafe recovery"); };
    const result = await sync.syncDosya(dosya(1), { bridge, detail: false });
    assert.equal(result.report.outcome, "failed");
  }
});
test("checkpoints include failed and pending files before a fatal stop", async () => {
  const bridge = fakeBridge({ k1: { ids: [], startError: "login_required" }, k2: { ids: [] } });
  const checkpoints = [];
  await sync.syncAll([1, 2].map(n => dosya(n)), { bridge, onCheckpoint: async r => checkpoints.push(r) });
  assert.deepEqual(checkpoints[0].reports.map(r => r.outcome), ["failed", "pending"]);
});

/**
 * Sahte UYAP + JurisAI sunucusu. `world[key]` = { ids, declared, lose: Set (gönderilse de sunucuya yazılmayan evraklar),
 * gap: ağaç tutarsızlığı, failPull: aktarım işi hatası }.
 */
function fakeBridge(world, { busyFirst = 0 } = {}) {
  const stored = new Map(); // dosya anahtarı → sunucudaki evrak kimlikleri
  const calls = { trees: 0, pulls: [], sleeps: 0, details: 0, stops: [], sleepMs: [] };
  let busy = busyFirst;
  const jobs = new Map();
  let counter = 0;
  const treeOf = (key) => {
    const spec = world[key];
    const known = [...(stored.get(key) ?? [])];
    const declared = spec.declared ?? spec.ids.length;
    const mismatch = declared !== spec.ids.length && !spec.explained;
    return {
      who: { esas: "", birim: "" },
      items: spec.ids.map((id) => ({ id, title: id, folders: [], typeName: "", isEk: false, declared: null })),
      counts: { declaredTotal: declared, foundTotal: spec.ids.length, eks: 0, matches: !mismatch, explained: !!spec.explained, gapList: mismatch ? ["Klasör X: 3 yazıyor, 2 bulundu"] : [], withoutId: 0, unstableId: spec.unstable ?? 0, unopened: spec.unopened ?? 0, emptyOpened: 0 },
      known,
      knownChecked: spec.knownChecked !== false,
    };
  };
  return {
    calls,
    stored,
    startTree: async (key) => {
      if (world[key].startError) return { ok: false, code: world[key].startError, error: "başlatılamadı" };
      if (busy > 0) { busy -= 1; return { ok: false, code: "busy", error: "meşgul" }; }
      calls.trees += 1;
      const id = `j${++counter}`;
      jobs.set(id, { kind: "tree", key });
      return { ok: true, jobId: id, tabId: 1 };
    },
    startDetail: async (key) => {
      const spec = world[key];
      if (spec.detailStartError) return { ok: false, code: spec.detailStartError, error: "dosya bilgileri başlatılamadı" };
      calls.details += 1;
      const id = `j${++counter}`;
      jobs.set(id, { kind: "detail", key });
      return { ok: true, jobId: id, tabId: 1 };
    },
    startPull: async (_tab, ids) => {
      const id = `j${++counter}`;
      jobs.set(id, { kind: "pull", ids });
      calls.pulls.push(ids);
      return { ok: true, jobId: id, total: ids.length, tabId: 1 };
    },
    wait: async (_tab, jobId) => {
      const job = jobs.get(jobId);
      if (job.kind === "detail") {
        const spec = world[job.key];
        if (spec.detailFails) return { ok: true, status: { job: { id: jobId, kind: "detail", state: "error", phase: "", error: "UYAP yanıt vermedi", code: "query_failed" } } };
        if (spec.detailSessionLost) return { ok: false, code: "unknown_job", error: "oturum kapandı" };
        const table = { title: "", headers: ["Rol"], rows: [["Davacı"]], declared: spec.detailPartial ? 2 : 1, complete: spec.detailPartial !== true };
        const detail = { who: { esas: "2025/1", birim: "Ankara İcra Dairesi" }, tabs: [{ key: "taraflar", label: "Taraf Bilgileri", pairs: [], tables: [table], complete: !spec.detailPartial }], problems: spec.detailPartial ? ["Taraf Bilgileri: UYAP 2 kayıt yazıyor, 1 okundu."] : [], complete: !spec.detailPartial };
        return { ok: true, status: { job: { id: jobId, kind: "detail", state: "done", phase: "" }, detail } };
      }
      if (job.kind === "tree") {
        const spec = world[job.key];
        if (spec.treeFails > 0) { spec.treeFails -= 1; return { ok: true, status: { job: { id: jobId, kind: "tree", state: "error", phase: "", error: "UYAP yanıt vermedi", code: "query_failed" } } }; }
        if (spec.sessionLost) return { ok: false, code: "unknown_job", error: "oturum kapandı" };
        if (spec.emptyTree || spec.emptyOnce > 0) {
          if (!spec.emptyTree) spec.emptyOnce -= 1;
          return { ok: true, status: { job: { id: jobId, kind: "tree", state: "error", phase: "", error: "UYAP bu dosyada evrak bilgisi bulunmadığını bildiriyor.", code: "empty_tree" } } };
        }
        const tree = treeOf(job.key);
        if (spec.unopenedOnce > 0) { spec.unopenedOnce -= 1; tree.counts.unopened = 1; }
        return { ok: true, status: { job: { id: jobId, kind: "tree", state: "done", phase: "" }, tree } };
      }
      const key = Object.keys(world).find((k) => job.ids.every((id) => world[k].ids.includes(id)));
      const spec = world[key];
      const set = stored.get(key) ?? new Set();
      let sent = 0;
      for (const id of job.ids) {
        if (spec.lose?.has(id)) { if (spec.lose.once) spec.lose.delete(id); continue; }
        if (!set.has(id)) { set.add(id); sent += 1; }
      }
      stored.set(key, set);
      if (spec.failPull) return { ok: true, status: { job: { id: jobId, kind: "pull", state: "error", phase: "", error: "yükleme hatası" }, run: { mode: "upload", chosen: job.ids.length, total: job.ids.length, done: sent, current: "", stats: { sent, duplicates: 0, sameContent: 0, failed: job.ids.length - sent, known: 0, errors: ["evrak 7: dosya indirilemedi"] } } } };
      return { ok: true, status: { job: { id: jobId, kind: "pull", state: "done", phase: "" }, run: { mode: "upload", chosen: job.ids.length, total: job.ids.length, done: job.ids.length, current: "", stats: { sent, duplicates: 0, sameContent: 0, failed: 0, known: 0, errors: [] } } } };
    },
    stop: async (tab, job) => { calls.stops.push([tab, job]); return { ok: true }; },
    sleep: async (ms) => { calls.sleeps += 1; calls.sleepMs.push(ms); },
  };
}

test("tamamı yeni bir dosya aktarılır ve sunucu kaydıyla doğrulanınca eksiksiz sayılır", async () => {
  const bridge = fakeBridge({ k1: { ids: ["a", "b", "c"] } });
  const { report, fatal } = await sync.syncDosya(dosya(1), { bridge });
  assert.equal(fatal, undefined);
  assert.deepEqual([report.outcome, report.found, report.stored, report.missing, report.sent, report.pulls], ["complete", 3, 3, 0, 3, 1]);
  assert.equal(bridge.calls.trees, 2, "aktarımdan sonra ağaç yeniden okunur (sunucu doğrulaması)");
  assert.deepEqual(report.problems, []);
});

test("UYAP'ın evrak yok dediği dosya hata ya da eksik sayılmaz ve koşuyu durdurmaz", async () => {
  // Canlıda görüldü: kapatılmış eski icra dairelerindeki dosyalarda UYAP "dosyaya ait evrak bilgisi bulunamadı" diyor.
  const world = { k1: { ids: ["a"] }, k2: { ids: [], emptyTree: true }, k3: { ids: [], emptyTree: true }, k4: { ids: [], emptyTree: true }, k5: { ids: [], emptyTree: true } };
  const bridge = fakeBridge(world);
  const dosyalar = [1, 2, 3, 4, 5].map((n) => dosya(n));
  const run = await sync.syncAll(dosyalar, { bridge });
  assert.deepEqual(run.reports.map((r) => r.outcome), ["complete", "empty", "empty", "empty", "empty"]);
  assert.equal(run.stoppedBecause, undefined, "art arda evraksız dosyalar 'üst üste okunamadı' sayılmaz");
  assert.deepEqual([run.summary.complete, run.summary.empty, run.summary.failed, run.summary.allComplete], [1, 4, 0, true]);
  assert.deepEqual(run.reports[1].problems, []);
  assert.equal(bridge.calls.trees, 2 + 4 * (1 + sync.EMPTY_CONFIRM_READS), "boş yanıt kabul edilmeden önce yeniden okunur");
  // Evraksız dosya da 0 evrak ve eksiksiz olarak bildirilir: yoksa her liste yenilemede "çekilmemiş" görünürdü.
  assert.deepEqual(sync.toServerItems(run.reports, dosyalar).map((item) => [item.esas, item.found, item.complete]),
    [["2025/1", 1, true], ["2025/2", 0, true], ["2025/3", 0, true], ["2025/4", 0, true], ["2025/5", 0, true]]);
  assert.ok(sync.reportText(run).includes("EVRAK YOK · 2025/2"));
});

test("bir kez boş gelen ağaç 'evrak yok' diye yazılmaz: ikinci okumadaki evraklar aktarılır", async () => {
  const bridge = fakeBridge({ k1: { ids: ["a", "b"], emptyOnce: 1 } });
  const { report } = await sync.syncDosya(dosya(1), { bridge });
  assert.deepEqual([report.outcome, report.found, report.stored, report.sent], ["complete", 2, 2, 2]);
});

test("yalnız evraksız dosyalardan oluşan koşu 'bütün dosyalar eksiksiz' diye sunulmaz", async () => {
  const bridge = fakeBridge({ k1: { ids: [], emptyTree: true } });
  const run = await sync.syncAll([dosya(1)], { bridge });
  assert.deepEqual([run.summary.empty, run.summary.allComplete], [1, false]);
});

test("kalıcı kimliği çıkarılamayan evrak varsa dosya eksiksiz sayılmaz (şifreli kimlik her oturumda değişir)", async () => {
  // Canlıda "Birim Evrak No"su boş evraklar bu yüzden her doğrulamada yeniden "eksik" görünüyor ve çoğalıyordu.
  const bridge = fakeBridge({ k1: { ids: ["a", "b"], unstable: 1 } });
  const { report } = await sync.syncDosya(dosya(1), { bridge });
  assert.equal(report.outcome, "incomplete");
  assert.ok(report.problems.some((p) => /kalıcı kimliği çıkarılamadı/.test(p)), report.problems.join(" | "));
});

test("evrak dışı dosya bilgileri evraklardan sonra okunur ve kaydedilir; evraksız dosyanın da alınır", async () => {
  const saved = [];
  const bridge = fakeBridge({ k1: { ids: ["a"] }, k2: { ids: [], emptyTree: true } });
  const run = await sync.syncAll([dosya(1), dosya(2)], { bridge, onDetail: async (detail, report) => { saved.push([report.esas, detail.tabs.length]); } });
  assert.deepEqual(run.reports.map((r) => [r.outcome, r.detail.state, r.detail.saved]), [["complete", "complete", true], ["empty", "complete", true]]);
  assert.deepEqual(saved, [["2025/1", 1], ["2025/2", 1]]);
  assert.equal(bridge.calls.details, 2);
  assert.deepEqual([run.summary.detailComplete, run.summary.detailPartial, run.summary.detailFailed, run.summary.detailSaved], [2, 0, 0, 2]);
  assert.match(sync.reportText(run), /dosya bilgileri: eksiksiz/);
});

test("dosya bilgileri okunamazsa evrak sonucu bozulmaz; sorun dosyada yazılır", async () => {
  const bridge = fakeBridge({ k1: { ids: ["a"], detailFails: true } });
  const { report, fatal } = await sync.syncDosya(dosya(1), { bridge });
  assert.equal(fatal, undefined);
  assert.equal(report.outcome, "complete"); // evraklar eksiksiz
  assert.deepEqual([report.detail.state, report.detail.saved], ["failed", false]);
  assert.match(report.detail.problems[0], /UYAP yanıt vermedi/);
  const text = sync.reportText({ reports: [report], summary: sync.summarize([report]) });
  assert.match(text, /Bilgi uyarısı: .*UYAP yanıt vermedi/);
});

test("bir tablo UYAP'ın sayısından az gelirse dosya bilgileri 'eksik' yazılır ama yine kaydedilir", async () => {
  const saved = [];
  const bridge = fakeBridge({ k1: { ids: ["a"], detailPartial: true } });
  const { report } = await sync.syncDosya(dosya(1), { bridge, onDetail: (detail) => saved.push(detail.complete) });
  assert.deepEqual([report.detail.state, report.detail.saved], ["partial", true]);
  assert.deepEqual(saved, [false]);
  assert.match(report.detail.problems[0], /UYAP 2 kayıt yazıyor, 1 okundu/);
  const text = sync.reportText({ reports: [report], summary: sync.summarize([report]) });
  assert.match(text, /1 dosyada evraklar eksiksiz/);
  assert.match(text, /birlikte doğrulanıp kaydedilen: 0\/1 dosya/);
});

test("kaydetme hatası evrak sonucunu bozmaz ve dosya bilgisi 'kaydedilemedi' diye yazılır", async () => {
  const bridge = fakeBridge({ k1: { ids: ["a"] } });
  const { report } = await sync.syncDosya(dosya(1), { bridge, onDetail: () => { throw new Error("Oturumunuz sona ermiş"); } });
  assert.equal(report.outcome, "complete");
  assert.equal(report.detail.saved, false);
  assert.match(report.detail.problems.join(" "), /kaydedilemedi: Oturumunuz sona ermiş/);
});

test("oturum kaybı dosya bilgisi okunurken de koşuyu durdurur; kalan dosyalar işlenmez", async () => {
  const bridge = fakeBridge({ k1: { ids: ["a"], detailSessionLost: true }, k2: { ids: ["b"] } });
  const run = await sync.syncAll([dosya(1), dosya(2)], { bridge });
  assert.ok(run.stoppedBecause);
  assert.deepEqual(run.reports.map((r) => r.outcome), ["complete", "pending"]);
});

test("hiç bilgi sekmesi bulunamazsa dosya bilgileri 'okunamadı' yazılır ve hiçbir şey kaydedilmez", async () => {
  const world = { k1: { ids: ["a"] } };
  const bridge = fakeBridge(world);
  const original = bridge.wait;
  bridge.wait = async (tab, jobId, options) => {
    const result = await original(tab, jobId, options);
    if (result.ok && result.status.detail) return { ok: true, status: { ...result.status, detail: { ...result.status.detail, tabs: [], complete: false } } };
    return result;
  };
  let saved = 0;
  const { report } = await sync.syncDosya(dosya(1), { bridge, onDetail: () => { saved += 1; } });
  assert.equal(report.outcome, "complete");
  assert.deepEqual([report.detail.state, report.detail.saved, saved], ["failed", false, 0]);
  assert.match(report.detail.problems[0], /bilgi sekmesi bulunamadı/);
});

test("detail:false ise dosya bilgileri hiç istenmez", async () => {
  const bridge = fakeBridge({ k1: { ids: ["a"] } });
  const { report } = await sync.syncDosya(dosya(1), { bridge, detail: false });
  assert.equal(report.detail.state, "skipped");
  assert.equal(bridge.calls.details, 0);
});

test("zaten tamamen aktarılmış dosya yeniden çekilmez", async () => {
  const bridge = fakeBridge({ k1: { ids: ["a", "b"] } });
  bridge.stored.set("k1", new Set(["a", "b"]));
  const { report } = await sync.syncDosya(dosya(1), { bridge });
  assert.deepEqual([report.outcome, report.sent, report.pulls], ["complete", 0, 0]);
  assert.deepEqual(bridge.calls.pulls, []);
});

test("bir kez kaybolan evrak ikinci turda tamamlanır; yalnız eksik olan yeniden çekilir", async () => {
  const lose = new Set(["b"]); lose.once = true;
  const bridge = fakeBridge({ k1: { ids: ["a", "b", "c"], lose } });
  const { report } = await sync.syncDosya(dosya(1), { bridge });
  assert.equal(report.outcome, "complete");
  assert.deepEqual(bridge.calls.pulls, [["a", "b", "c"], ["b"]]);
  assert.equal(report.pulls, 2);
});

test("gönderilse de sunucuya yazılmayan evrak sessizce geçilmez: dosya eksik olarak raporlanır", async () => {
  // Aynı baytlı ekin atlanması gibi kayıplar: aktarım sayacı "gönderdim" der, sunucu kaydı yoktur.
  const bridge = fakeBridge({ k1: { ids: ["a", "b", "c"], lose: new Set(["c"]) } });
  const { report } = await sync.syncDosya(dosya(1), { bridge });
  assert.equal(report.outcome, "incomplete");
  assert.deepEqual([report.found, report.stored, report.missing], [3, 2, 1]);
  assert.equal(report.pulls, sync.MAX_PULLS_PER_FILE);
  assert.ok(report.problems.some((p) => /1 evrak JurisAI'da kayıtlı görünmüyor/.test(p)));
});

test("UYAP'ın yazdığı sayı bulunanla uyuşmuyorsa her evrak kayıtlı olsa da dosya eksiksiz sayılmaz", async () => {
  const bridge = fakeBridge({ k1: { ids: ["a", "b"], declared: 5 } });
  const { report } = await sync.syncDosya(dosya(1), { bridge });
  assert.equal(report.outcome, "incomplete");
  assert.equal(report.declared, 5);
  assert.ok(report.problems.some((p) => /UYAP 5 evrak yazıyor, ağaçta 2 bulundu/.test(p)));
  // Fark yalnız aynı evrakın birden çok klasörde görünmesinden ise eksik yoktur.
  const explained = fakeBridge({ k1: { ids: ["a", "b"], declared: 3, explained: true } });
  assert.equal((await sync.syncDosya(dosya(1), { bridge: explained })).report.outcome, "complete");
});

test("açılamayan klasör geçiciyse yeniden okunarak giderilir, kalıcıysa eksik raporlanır", async () => {
  const transient = fakeBridge({ k1: { ids: ["a"], unopenedOnce: 1 } });
  assert.equal((await sync.syncDosya(dosya(1), { bridge: transient })).report.outcome, "complete");
  const permanent = fakeBridge({ k1: { ids: ["a"], unopened: 2 } });
  const { report } = await sync.syncDosya(dosya(1), { bridge: permanent });
  assert.equal(report.outcome, "incomplete");
  assert.ok(report.problems.some((p) => /2 klasör açılamadı/.test(p)));
  assert.equal(permanent.calls.trees, 2 + sync.MAX_REREADS, "ilk okuma + aktarım sonrası doğrulama + yeniden okumalar");
});

test("sunucu kaydı doğrulanamıyorsa eksiksiz denmez", async () => {
  const bridge = fakeBridge({ k1: { ids: ["a"], knownChecked: false } });
  const { report } = await sync.syncDosya(dosya(1), { bridge });
  assert.equal(report.outcome, "incomplete");
  assert.ok(report.problems.some((p) => /doğrulanamadı/.test(p)));
});

test("aktarım işi hata verse de doğrulama turu gerçek durumu gösterir ve hata nedeni yazılır", async () => {
  const bridge = fakeBridge({ k1: { ids: ["a", "b"], failPull: true } });
  const { report } = await sync.syncDosya(dosya(1), { bridge });
  assert.equal(report.outcome, "complete", "evraklar yine de sunucuya yazıldıysa dosya eksiksizdir");
  assert.ok(report.problems.includes("yükleme hatası") && report.problems.includes("evrak 7: dosya indirilemedi"));
});

test("ağaç okunamazsa dosya hatalıdır; oturum kaybı koşuyu durdurur ve kalanlar bekliyor kalır", async () => {
  const world = { k1: { ids: ["a"] }, k2: { ids: ["b"], sessionLost: true }, k3: { ids: ["c"] } };
  const run = await sync.syncAll([dosya(1), dosya(2), dosya(3)], { bridge: fakeBridge(world) });
  assert.deepEqual(run.reports.map((r) => r.outcome), ["complete", "failed", "pending"]);
  assert.match(run.stoppedBecause, /oturum kapandı/);
  assert.equal(run.summary.allComplete, false);
  assert.deepEqual([run.summary.complete, run.summary.failed, run.summary.pending], [1, 1, 1]);
  const text = sync.reportText(run);
  assert.match(text, /evrak sayısı bilinmiyor/);
  assert.match(text, /HATA · 2025\/2 .*evrak sayısı okunamadı/);
  assert.match(text, /İŞLENMEDİ · 2025\/3 .*evraklar denenmedi/);
  assert.doesNotMatch(text, /0\/0 evrak/);
});

test("tek dosyanın geçici hatası diğerlerini durdurmaz; üst üste üç hata koşuyu durdurur", async () => {
  const world = { k1: { ids: ["a"], treeFails: 99 }, k2: { ids: ["b"] }, k3: { ids: ["c"] }, k4: { ids: ["d"], treeFails: 99 }, k5: { ids: ["e"], treeFails: 99 }, k6: { ids: ["f"], treeFails: 99 }, k7: { ids: ["g"] } };
  const run = await sync.syncAll(Array.from({ length: 7 }, (_, i) => dosya(i + 1)), { bridge: fakeBridge(world) });
  assert.deepEqual(run.reports.map((r) => r.outcome), ["failed", "complete", "complete", "failed", "failed", "failed", "pending"]);
  assert.match(run.stoppedBecause, /Üst üste 3 dosya/);
});

test("geçici ağaç okuma hatası artan beklemeyle yeniden denenir ve evraklar yalnız bir kez gönderilir", async () => {
  const bridge = fakeBridge({ k1: { ids: ["a"], treeFails: 2 } });
  const { report } = await sync.syncDosya(dosya(1), { bridge });
  assert.equal(report.outcome, "complete");
  assert.deepEqual(bridge.calls.sleepMs, [4000, 8000]);
  assert.deepEqual(bridge.calls.pulls, [["a"]]);
  assert.equal(bridge.calls.trees, 4); // 2 hata + ilk ağaç + sunucu doğrulaması
});

test("kalıcı okuma hatasının deneme sayısı sınırlıdır; oturum/kimlik/liste hataları tekrarlanmaz", async () => {
  const bridge = fakeBridge({ k1: { ids: ["a"], treeFails: 99 } });
  const { report } = await sync.syncDosya(dosya(1), { bridge });
  assert.equal(report.outcome, "failed");
  assert.equal(bridge.calls.trees, 1 + sync.MAX_READ_RETRIES);
  assert.deepEqual(bridge.calls.pulls, []);
  for (const code of ["login_required", "stale", "pairing_rejected"]) {
    const b = fakeBridge({ k1: { ids: ["a"], startError: code } });
    const result = await sync.syncDosya(dosya(1), { bridge: b });
    assert.equal(result.report.outcome, "failed");
    assert.equal(b.calls.sleeps, 0, code);
  }
});

test("ağaç okurken iptal ya da zaman aşımı varsa eski iş durdurulur ve yeni iş başlatılmaz", async () => {
  for (const code of ["aborted", "timeout"]) {
    const bridge = fakeBridge({ k1: { ids: ["a"] } });
    bridge.wait = async () => ({ ok: false, code, error: code });
    const { report } = await sync.syncDosya(dosya(1), { bridge, detail: false });
    assert.equal(report.outcome, "failed");
    assert.deepEqual(bridge.calls.stops, [[1, "j1"]]);
    assert.equal(bridge.calls.trees, 1);
  }
});

test("evrakı tam olsa da eksik veya kaydedilmemiş dosya bilgileri yeniden denenecekler listesine girer", () => {
  const full = { ...sync.blankReport(dosya(1)), outcome: "complete", detail: { state: "complete", saved: true } };
  const partial = { ...full, key: "k2", detail: { state: "partial", saved: true } };
  const unsaved = { ...full, key: "k3", detail: { state: "complete", saved: false } };
  const pending = { ...sync.blankReport(dosya(4)) };
  assert.equal(sync.fullyVerified(full), true);
  assert.equal(sync.fullyVerified(partial), false);
  assert.deepEqual([...sync.retryKeysFor([full, partial, unsaved, pending])], ["k2", "k3", "k4"]);
});

test("aktarım zaman aşımında eski iş durdurulur; yalnız kalan evraklar tekrar çekilip doğrulanır", async () => {
  const bridge = fakeBridge({ k1: { ids: ["a"] } });
  const wait = bridge.wait;
  bridge.wait = async (tab, job, options) => job === "j2"
    ? { ok: false, code: "timeout", error: "İş çok uzun sürdü." }
    : wait(tab, job, options);
  const { report } = await sync.syncDosya(dosya(1), { bridge, detail: false });
  assert.deepEqual(bridge.calls.stops, [[1, "j2"]]);
  assert.deepEqual(bridge.calls.pulls, [["a"], ["a"]]);
  assert.deepEqual([report.outcome, report.stored, report.missing], ["complete", 1, 0]);
});

test("sunucunun eksik saydığı dosya bilgisi istemci tam dese de başarı olarak gösterilmez", async () => {
  const bridge = fakeBridge({ k1: { ids: ["a"] } });
  const { report } = await sync.syncDosya(dosya(1), { bridge, onDetail: async () => ({ complete: false }) });
  assert.equal(report.outcome, "complete");
  assert.deepEqual([report.detail.state, report.detail.saved], ["partial", true]);
  assert.match(report.detail.problems.join(" "), /Sunucu.*doğrulamadı/);
  assert.equal(sync.fullyVerified(report), false);
});

test("UYAP meşgulken başlatma beklenip yeniden denenir", async () => {
  const bridge = fakeBridge({ k1: { ids: ["a"] } }, { busyFirst: 3 });
  const { report } = await sync.syncDosya(dosya(1), { bridge });
  assert.equal(report.outcome, "complete");
  assert.equal(bridge.calls.sleeps, 3);
});

test("yalnız seçilen dosyalar yeniden denenir (eksikleri yeniden dene)", async () => {
  const bridge = fakeBridge({ k1: { ids: ["a"] }, k2: { ids: ["b"] } });
  const run = await sync.syncAll([dosya(1), dosya(2)], { bridge, only: new Set(["k2"]) });
  assert.deepEqual(run.reports.map((r) => r.key), ["k2"]);
});

test("iptal edilen koşu kalan dosyaları işlemez ve eksiksiz denmez", async () => {
  const controller = new AbortController();
  const bridge = fakeBridge({ k1: { ids: ["a"] }, k2: { ids: ["b"] } });
  const run = await sync.syncAll([dosya(1), dosya(2)], { bridge, signal: controller.signal, onProgress: ({ index, phase }) => { if (index === 0 && /aktarılıyor/.test(phase)) controller.abort(); } });
  assert.equal(run.aborted, true);
  assert.equal(run.reports[1].outcome, "pending");
  assert.equal(run.summary.allComplete, false);
});

test("özet ve rapor metni: sayılar tutar, eksik dosya adıyla yazılır, içerik yoktur", async () => {
  const lose = new Set(["x2"]);
  const run = await sync.syncAll([dosya(1), dosya(2)], { bridge: fakeBridge({ k1: { ids: ["a", "b"] }, k2: { ids: ["x1", "x2"], lose } }) });
  assert.deepEqual([run.summary.files, run.summary.complete, run.summary.incomplete, run.summary.found, run.summary.stored, run.summary.missing], [2, 1, 1, 4, 3, 1]);
  assert.equal(sync.summarize([]).allComplete, false);
  const text = sync.reportText(run);
  assert.match(text, /2 dosya: 1 dosyada evraklar eksiksiz, 0 evraksız, 1 evrak eksik/);
  assert.match(text, /EVRAKLAR EKSİKSİZ · 2025\/1 · Ankara İcra Dairesi · 2\/2 evrak/);
  assert.match(text, /EKSİK · 2025\/2 · Ankara İcra Dairesi · 1\/2 evrak/);
});

test("sunucuya yalnız sayısı bilinen dosyalar, UYAP listesindeki üst veriyle gönderilir", async () => {
  const dosyalar = [
    dosya(1, { role: "Alacaklı Vekili", tur: "İlamsız Takip", acilis: "23.09.2025", durum: "Açık" }),
    dosya(2), dosya(3), dosya(4, { esas: "" }),
  ];
  const reports = [
    { ...sync.blankReport(dosyalar[0]), outcome: "complete", declared: 3, found: 3, stored: 3 },
    { ...sync.blankReport(dosyalar[1]), outcome: "incomplete", found: 5, stored: 4, missing: 1, problems: ["1 evrak JurisAI'da kayıtlı görünmüyor."] },
    { ...sync.blankReport(dosyalar[2]), outcome: "failed", problems: ["UYAP yanıt vermedi"] },
    { ...sync.blankReport(dosyalar[3]), outcome: "complete", found: 1, stored: 1 },
    sync.blankReport(dosya(5)),
  ];
  const items = sync.toServerItems(reports, dosyalar);
  assert.deepEqual(items.map((i) => [i.esas, i.complete, i.found, i.missing]), [["2025/1", true, 3, 0], ["2025/2", false, 5, 1]]);
  assert.deepEqual([items[0].yargi_turu, items[0].dosya_turu, items[0].durum, items[0].rol, items[0].acilis], ["İcra", "İlamsız Takip", "Açık", "Alacaklı Vekili", "23.09.2025"]);
});

test("yalnız denetle: hiçbir evrak aktarılmaz, eksikler sayılır", async () => {
  const bridge = fakeBridge({ k1: { ids: ["a", "b", "c"] }, k2: { ids: ["d"] } });
  bridge.stored.set("k1", new Set(["a"]));
  bridge.stored.set("k2", new Set(["d"]));
  const run = await sync.syncAll([dosya(1), dosya(2)], { bridge, pull: false });
  assert.deepEqual(bridge.calls.pulls, [], "denetimde aktarım başlatılmaz");
  assert.deepEqual(run.reports.map((r) => [r.outcome, r.found, r.stored, r.missing, r.sent]), [["incomplete", 3, 1, 2, 0], ["complete", 1, 1, 0, 0]]);
  assert.equal(bridge.calls.trees, 2, "eksik evrak için ağaç yeniden okunmaz");
});

test("sunucuya dosya penceresinin yazdığı kimlik gönderilir (evraklar o kimlikle yüklenir)", async () => {
  const bridge = fakeBridge({ k1: { ids: ["a"] } });
  const original = bridge.wait;
  bridge.wait = async (...args) => {
    const result = await original(...args);
    if (result.ok && result.status.tree) result.status.tree.who = { esas: "2025/1", birim: "ANKARA İCRA DAİRESİ (pencere)" };
    return result;
  };
  const d = dosya(1, { birim: "Ankara İcra Dairesi (liste)" });
  const { report } = await sync.syncDosya(d, { bridge });
  assert.deepEqual(report.who, { esas: "2025/1", birim: "ANKARA İCRA DAİRESİ (pencere)" });
  assert.equal(report.birim, "Ankara İcra Dairesi (liste)", "ekranda liste satırındaki ad gösterilir");
  assert.equal(sync.toServerItems([report], [d])[0].birim, "ANKARA İCRA DAİRESİ (pencere)");
});

test("sunucunun eksiksiz saymadığı dosya ayrıca bildirilir", () => {
  const items = [{ esas: "2025/1", birim: "A", complete: true }, { esas: "2025/2", birim: "B", complete: true }, { esas: "2025/3", birim: "C", complete: false }];
  const saved = sync.reconcileSaved(items, { saved: 2, results: [{ status: "saved", esas: "2025/1", birim: "A", complete: true }, { status: "saved", esas: "2025/2", birim: "B", complete: false }, { status: "no_case" }] });
  assert.deepEqual(saved, { saved: 2, downgraded: ["2025/2 · B"], unmatched: 1 });
  assert.deepEqual(sync.reconcileSaved(items, null), { saved: 0, downgraded: [], unmatched: 3 });
  assert.deepEqual(sync.reconcileSaved(items, { saved: 3, results: [{ status: "saved", esas: "WRONG", complete: true }] }), { saved: 0, downgraded: [], unmatched: 3 });
  assert.deepEqual(sync.reconcileSaved(items, { results: [{ status: "saved", complete: true }] }), { saved: 0, downgraded: [], unmatched: 3 });
});

test("when the UYAP page reloads mid-run the list is read again and the remaining files continue under their new keys", async () => {
  // k2 ve k3'ün eski anahtarları geçersiz ("liste değişmiş"); yeniden listeleme aynı dosyaları n2/n3 anahtarlarıyla verir.
  const world = { k1: { ids: ["a"] }, k2: { ids: [], startError: "stale" }, k3: { ids: [], startError: "stale" }, n2: { ids: ["b"] }, n3: { ids: ["c"] } };
  const bridge = fakeBridge(world);
  let relists = 0;
  bridge.relist = async () => { relists += 1; return [dosya(1), { ...dosya(2), key: "n2" }, { ...dosya(3), key: "n3" }]; };
  const run = await sync.syncAll([1, 2, 3].map((n) => dosya(n)), { bridge, detail: false });

  assert.deepEqual(run.reports.map((r) => r.outcome), ["complete", "complete", "complete"]);
  assert.equal(run.stoppedBecause, undefined);
  assert.equal(relists, 1, "liste bir kez yeniden okunur; üçüncü dosya yeni anahtarıyla doğrudan açılır");
  assert.deepEqual(run.reports.map((r) => r.key), ["k1", "k2", "k3"], "raporlar sayfadaki satırlarla eşleşen özgün anahtarı taşır");
});

test("re-listing is bounded and a file missing from the new list still fails honestly", async () => {
  const world = { k1: { ids: [], startError: "stale" }, k2: { ids: [], startError: "stale" }, k3: { ids: [], startError: "stale" } };
  const bridge = fakeBridge(world);
  let relists = 0;
  bridge.relist = async () => { relists += 1; return []; }; // yeni listede hiçbiri yok
  const run = await sync.syncAll([1, 2, 3].map((n) => dosya(n)), { bridge, detail: false });

  assert.equal(relists, 2 + 3, "dosya başına iki yeniden listeleme + üç toparlanma denemesi; sonra dürüstçe durur");
  assert.deepEqual(run.reports.map((r) => r.outcome), ["failed", "failed", "failed"]);
  assert.match(run.stoppedBecause, /Üst üste 3 dosya/);
});

test("three files failing in a row no longer end the run: it waits, re-reads the list and retries them", async () => {
  // UYAP bir süre yanıt vermiyor (üç dosya açılamıyor); bekleyip liste yeniden okununca düzeliyor.
  const world = { k1: { ids: ["a"] }, k2: { ids: ["b"], startError: "query_failed" }, k3: { ids: ["c"], startError: "query_failed" }, k4: { ids: ["d"], startError: "query_failed" }, k5: { ids: ["e"] } };
  const bridge = fakeBridge(world);
  let relists = 0;
  bridge.relist = async () => { relists += 1; for (const key of ["k2", "k3", "k4"]) delete world[key].startError; return [1, 2, 3, 4, 5].map((n) => dosya(n)); };
  const phases = [];
  const run = await sync.syncAll([1, 2, 3, 4, 5].map((n) => dosya(n)), { bridge, detail: false, onProgress: (event) => phases.push(event.phase) });

  assert.deepEqual(run.reports.map((r) => r.outcome), ["complete", "complete", "complete", "complete", "complete"]);
  assert.equal(run.stoppedBecause, undefined);
  assert.equal(relists, 1);
  assert.ok(phases.some((phase) => /beklenip dosya listesi yeniden okunacak/.test(phase)));
});

test("if the list cannot be read after waiting the session is gone and the run stops with the reason", async () => {
  const world = { k1: { ids: [], startError: "query_failed" }, k2: { ids: [], startError: "query_failed" }, k3: { ids: [], startError: "query_failed" }, k4: { ids: ["d"] } };
  const bridge = fakeBridge(world);
  bridge.relist = async () => null;
  const run = await sync.syncAll([1, 2, 3, 4].map((n) => dosya(n)), { bridge, detail: false });

  assert.match(run.stoppedBecause, /Üst üste 3 dosya/);
  assert.deepEqual(run.reports.map((r) => r.outcome), ["failed", "failed", "failed", "pending"]);
});

test("when the session is lost the run waits for a new login and then continues from the same file", async () => {
  // k2 açılırken oturum kapanmış (ölümcül hata); liste ancak üçüncü yoklamada (kullanıcı giriş yapınca) okunabiliyor.
  const world = { k1: { ids: ["a"] }, k2: { ids: ["b"], startError: "login_required" }, k3: { ids: ["c"] } };
  const bridge = fakeBridge(world);
  let polls = 0;
  bridge.relist = async () => { polls += 1; if (polls < 3) return null; delete world.k2.startError; return [1, 2, 3].map((n) => dosya(n)); };
  const phases = [];
  const run = await sync.syncAll([1, 2, 3].map((n) => dosya(n)), { bridge, detail: false, onProgress: (event) => phases.push(event.phase) });

  assert.deepEqual(run.reports.map((r) => r.outcome), ["complete", "complete", "complete"]);
  assert.equal(run.stoppedBecause, undefined);
  assert.equal(polls, 3);
  assert.ok(phases.includes(sync.LOGIN_WAIT_PHASE), "kullanıcıya yeniden giriş yapması açıkça söylenir");
});

test("waiting for a login ends when the user stops the run, and nothing is reported as transferred", async () => {
  const world = { k1: { ids: [], startError: "login_required" }, k2: { ids: ["b"] } };
  const bridge = fakeBridge(world);
  const controller = new AbortController();
  let polls = 0;
  bridge.relist = async () => { polls += 1; if (polls === 2) controller.abort(); return null; };
  const run = await sync.syncAll([1, 2].map((n) => dosya(n)), { bridge, detail: false, signal: controller.signal });

  assert.equal(polls, 2);
  assert.deepEqual(run.reports.map((r) => r.outcome), ["failed", "pending"]);
  assert.equal(run.summary.complete, 0);
});
