import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
import ts from "typescript";

const require = createRequire(import.meta.url);
function compile(relative) {
  const source = readFileSync(new URL(relative, import.meta.url), "utf8");
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  });
  const module = { exports: {} };
  // Bekleme yardımcısı tarayıcı çalışanı kullanır; testte olağan zamanlayıcıyla değiştirilir.
  const resolve = (name) => (name === "@/lib/steady-timer" ? { steadySleep: (ms) => new Promise((done) => setTimeout(done, ms)) } : require(name));
  new Function("require", "module", "exports", outputText)(resolve, module, module.exports);
  return module.exports;
}

const bridge = compile("../src/lib/uyap-bridge.ts");

test("document origin recognizes both UYAP import and extension transfer without changing stored provenance", () => {
  const { isUyapSource } = compile("../src/lib/uyap.ts");
  assert.equal(isUyapSource("uyap"), true);
  assert.equal(isUyapSource("uyap-avukat-eklentisi"), true);
  for (const source of ["manual", "uyap-other", "", null, undefined]) {
    assert.equal(isUyapSource(source), false);
  }
});

test("concurrent tree starts share one request and release it for a later rescan", async () => {
  let posted = 0;
  fakeWindow((message, deliver) => {
    assert.equal(message.type, "TREE");
    posted += 1;
    const jobId = `tree-${posted}`;
    setTimeout(() => deliver({ source: "jurisai-extension", id: message.id, ok: true, jobId, tabId: 7 }), 10);
  });
  const [first, second] = await Promise.all([
    bridge.startTreeJob("case-a", "Ceza"),
    bridge.startTreeJob("case-a", "Ceza"),
  ]);
  assert.equal(posted, 1);
  assert.deepEqual(first, second);
  assert.equal(first.jobId, "tree-1");
  assert.equal((await bridge.startTreeJob("case-a", "Ceza")).jobId, "tree-2");
});

test("tree starts never merge different case scopes and a failed start can be retried", async () => {
  let posted = 0;
  fakeWindow((message, deliver) => {
    posted += 1;
    setTimeout(() => deliver({ source: "jurisai-extension", id: message.id, ok: false, code: "busy", error: "Meşgul" }), 5);
  });
  const replies = await Promise.all([
    bridge.startTreeJob("case-a", "Ceza"),
    bridge.startTreeJob("case-a", "Hukuk"),
    bridge.startTreeJob("case-b", "Ceza"),
  ]);
  assert.equal(posted, 3);
  assert.ok(replies.every((reply) => !reply.ok && reply.code === "busy"));
  await bridge.startTreeJob("case-a", "Ceza");
  assert.equal(posted, 4);
});

/** window.postMessage/addEventListener'ı taklit eden küçük bir ortam; `onPost` eklentinin yerine yanıtı üretir. */
function fakeWindow(onPost) {
  const listeners = new Set();
  const origin = "https://jurisai.example";
  const fake = {
    location: { origin },
    addEventListener: (_type, listener) => listeners.add(listener),
    removeEventListener: (_type, listener) => listeners.delete(listener),
    postMessage: (message, targetOrigin) => {
      assert.equal(targetOrigin, origin); // yalnız kendi kaynağına gönderir
      onPost(message, (data, options = {}) => {
        for (const listener of [...listeners])
          listener({ source: options.source ?? fake, origin: options.origin ?? origin, data });
      });
    },
    listenerCount: () => listeners.size,
  };
  globalThis.window = fake;
  return fake;
}

test("a request resolves with the extension's reply and cleans up its listener", async () => {
  const fake = fakeWindow((message, deliver) => {
    assert.equal(message.source, "jurisai-web");
    assert.equal(message.type, "PING");
    deliver({ source: "jurisai-extension", id: message.id, ok: true, version: "2.21.0", connected: true });
  });
  const status = await bridge.detectExtension(500);
  assert.deepEqual(status, { installed: true, version: "2.21.0", connected: true });
  assert.equal(fake.listenerCount(), 0);
});

test("extension detection allows a delayed service worker response beyond 1.5 seconds", async () => {
  const fake = fakeWindow((message, deliver) => {
    setTimeout(() => deliver({ source: "jurisai-extension", id: message.id, ok: true, version: "2.26.2", connected: true }), 1800);
  });
  assert.deepEqual(await bridge.detectExtension(), { installed: true, version: "2.26.2", connected: true });
  assert.equal(fake.listenerCount(), 0);
});

test("extension detection preserves a runtime failure instead of calling it a missing installation", async () => {
  fakeWindow((message, deliver) => {
    deliver({ source: "jurisai-extension", id: message.id, ok: false, code: "bridge_denied", error: "Bu kaynaktan komut kabul edilmez" });
  });
  assert.deepEqual(await bridge.detectExtension(100), {
    installed: false, code: "bridge_denied", error: "Bu kaynaktan komut kabul edilmez",
  });
});

test("no reply reports a connection timeout, not proof of a missing installation, and nothing leaks", async () => {
  const fake = fakeWindow(() => {});
  const reply = await bridge.bridgeRequest("PING", {}, 30);
  assert.equal(reply.ok, false);
  assert.equal(reply.code, "timeout");
  assert.equal(fake.listenerCount(), 0);
  assert.deepEqual(await bridge.detectExtension(30), { installed: false, code: "timeout", error: "Eklenti yanıt vermedi." });
});

test("replies from another window, origin or request id are ignored", async () => {
  fakeWindow((message, deliver) => {
    deliver({ source: "jurisai-extension", id: message.id, ok: true, version: "evil" }, { origin: "https://evil.example" });
    deliver({ source: "jurisai-extension", id: message.id, ok: true, version: "evil" }, { source: {} });
    deliver({ source: "jurisai-extension", id: "baska-istek", ok: true, version: "evil" });
    deliver({ source: "baska", id: message.id, ok: true, version: "evil" });
    deliver({ source: "jurisai-extension", id: message.id, ok: true, version: "real", connected: false });
  });
  assert.deepEqual(await bridge.detectExtension(500), { installed: true, version: "real", connected: false });
});

test("a failure reply keeps its message and code", async () => {
  fakeWindow((message, deliver) => {
    deliver({ source: "jurisai-extension", id: message.id, ok: false, code: "no_uyap_tab", error: "UYAP sekmesi yok" });
  });
  const result = await bridge.listUyapDosyalari();
  assert.deepEqual(result, { ok: false, code: "no_uyap_tab", error: "UYAP sekmesi yok" });
});

test("the dosya list is parsed defensively", async () => {
  const liste = bridge.parseDosyaListe({
    items: [
      { key: "a#1", esas: "2024/124", birim: "Ankara 33. Ağır Ceza Mahkemesi", cells: ["2024/124", "Ankara 33. Ağır Ceza Mahkemesi", "Ceza"] },
      { key: "", esas: "x" }, // anahtarsız satır atılır
      null,
      "bozuk",
      { key: "b#1", cells: "liste-değil", esas: 5 },
      { key: "c#1", esas: "x".repeat(500), cells: ["  çok   boşluklu  ", ""] },
    ],
    pages: 3,
    page: 1,
  });
  assert.equal(liste.items.length, 3);
  assert.deepEqual(liste.items[1], { key: "b#1", esas: "", birim: "", yargiTuru: "", role: "", tur: "", acilis: "", durum: "", cells: [] });
  assert.equal(liste.items[2].esas.length, 60);
  assert.deepEqual(liste.items[2].cells, ["çok boşluklu"]);
  assert.equal(liste.pages, 3);
  assert.equal(liste.page, 1);
  assert.deepEqual(bridge.parseDosyaListe(null), { items: [], types: [], errors: [], complete: false, pages: null, page: null, identity: null });
  assert.equal(bridge.parseDosyaListe({ pages: -1, page: "2" }).pages, null);
  assert.deepEqual(bridge.otherCells(liste.items[0]), ["Ceza"]);
});

test("opening a dosya sends its key to the extension", async () => {
  let sent;
  fakeWindow((message, deliver) => {
    sent = message;
    deliver({ source: "jurisai-extension", id: message.id, ok: true });
  });
  const reply = await bridge.openUyapDosya("a#1");
  assert.equal(reply.ok, true);
  assert.equal(sent.type, "OPEN_DOSYA");
  assert.deepEqual(sent.payload, { key: "a#1", yargiTuru: "" });
});

test("the connection key is written to the extension and a change event is published", async () => {
  const events = [];
  const fake = fakeWindow((message, deliver) => {
    assert.equal(message.type, "SET_KEY");
    deliver({ source: "jurisai-extension", id: message.id, ok: message.payload.key.startsWith("jsai_") });
  });
  fake.dispatchEvent = (event) => events.push(event.type);
  assert.equal(await bridge.setExtensionKey("jsai_" + "a".repeat(40)), true);
  assert.deepEqual(events, ["jurisai-extension-changed"]);
  assert.equal(await bridge.setExtensionKey("bozuk"), false);
  assert.deepEqual(events, ["jurisai-extension-changed"]); // başarısızlıkta olay yok
});

test("a failed list read tells the user what to do next, and only waits when UYAP can fix it", () => {
  for (const code of ["no_uyap_tab", "login_required", "no_list", "no_content"]) {
    const help = bridge.describeListFailure(code, "x");
    assert.equal(help.waiting, true, code);
    assert.ok(help.title && help.steps.length > 0, code);
  }
  assert.match(bridge.describeListFailure("login_required", "x").title, /giriş yapılmamış/);
  assert.match(bridge.describeListFailure("no_list", "x").steps[0], /Dosya Sorgulama/);
  const other = bridge.describeListFailure("timeout", "Eklenti yanıt vermedi.");
  assert.deepEqual(other, { title: "Eklenti yanıt vermedi.", steps: [], waiting: false });
});

test("the tree reply is parsed defensively and grouped by folder", () => {
  const tree = bridge.parseTree({
    who: { esas: "2024/124", birim: "Ankara 33. Ağır Ceza Mahkemesi" },
    items: [
      { id: "a", title: "Dilekçe", folders: ["2022/608", "Talimat Üst Yazısı"], typeName: "Talimat Üst Yazısı", isEk: false, declared: 1 },
      { id: "a", title: "kopya", folders: [] }, // aynı kimlik atılır
      { id: "b", title: "Ek 1", folders: ["2022/608", "Talimat Üst Yazısı"], isEk: true, declared: null },
      { id: "", title: "kimliksiz" },
      null,
      { id: "c", title: "x".repeat(500), folders: "liste-değil" },
    ],
    counts: { declaredTotal: 2, foundTotal: 1, eks: 1, matches: false, explained: true, gapList: ["K (UYAP 2, bulunan 1)"] },
    known: ["a", 5, "", "zz"],
    knownChecked: true,
  });
  assert.deepEqual(tree.items.map((item) => item.id), ["a", "b", "c"]);
  assert.equal(tree.items[2].title.length, 200);
  assert.deepEqual(tree.items[2].folders, []);
  assert.deepEqual(tree.known, ["a", "zz"]);
  assert.equal(tree.counts.explained, true);
  assert.equal(bridge.parseTree("bozuk"), null);
  const groups = bridge.groupTreeItems(tree.items);
  assert.deepEqual(groups.map((group) => [group.label, group.items.length]), [["2022/608 / Talimat Üst Yazısı", 2], ["(klasörsüz)", 1]]);
  assert.equal(groups[0].declared, 1);
});

test("the default selection leaves out what JurisAI already has, and attachments on request", () => {
  const items = [
    { id: "a", isEk: false },
    { id: "b", isEk: true },
    { id: "c", isEk: false },
  ];
  assert.deepEqual([...bridge.defaultSelection(items, ["a"])], ["b", "c"]);
  assert.deepEqual([...bridge.defaultSelection(items, ["a"], true)], ["c"]);
  assert.deepEqual([...bridge.defaultSelection(items, [])], ["a", "b", "c"]);
});

test("a job status is parsed defensively", () => {
  assert.equal(bridge.parseJobStatus(null), null);
  assert.equal(bridge.parseJobStatus({ job: { state: "done" } }), null); // kimliksiz iş
  const status = bridge.parseJobStatus({
    job: { id: "j1", kind: "pull", state: "weird", phase: "Aktarılıyor" },
    run: { mode: "disk", chosen: 3, total: 3, done: 1, current: "Dilekçe", stats: { sent: 1, failed: "x", errors: ["e1", 5] }, result: { summary: "özet", stopped: true } },
  });
  assert.equal(status.job.state, "running"); // bilinmeyen durum çalışıyor sayılır
  assert.equal(status.job.kind, "pull");
  assert.equal(status.run.mode, "disk");
  assert.deepEqual(status.run.stats, { sent: 1, duplicates: 0, sameContent: 0, failed: 0, known: 0, errors: ["e1"], absent: [] });
  assert.equal(status.run.result.stopped, true);
});

test("waiting for a job polls until it ends, reports progress, and gives up when the UYAP tab is gone", async () => {
  let polls = 0;
  fakeWindow((message, deliver) => {
    assert.equal(message.type, "JOB_STATUS");
    polls += 1;
    const state = polls < 3 ? "running" : "done";
    deliver({ source: "jurisai-extension", id: message.id, ok: true, job: { id: "j1", kind: "pull", state, phase: "x" }, run: { mode: "upload", chosen: 2, total: 2, done: polls, current: "", stats: { sent: polls } } });
  });
  const seen = [];
  const finished = await bridge.waitForJob(7, "j1", { intervalMs: 5, onUpdate: (status) => seen.push(status.run.done) });
  assert.equal(finished.ok, true);
  assert.equal(finished.status.job.state, "done");
  assert.deepEqual(seen, [1, 2, 3]);

  fakeWindow((message, deliver) => deliver({ source: "jurisai-extension", id: message.id, ok: false, code: "no_uyap_tab", error: "UYAP sekmesi kapanmış" }));
  const gone = await bridge.waitForJob(7, "j1", { intervalMs: 5 });
  assert.equal(gone.ok, false);
  assert.equal(gone.code, "no_uyap_tab"); // ilk hatada vazgeçer

  const controller = new AbortController();
  fakeWindow((message, deliver) => deliver({ source: "jurisai-extension", id: message.id, ok: true, job: { id: "j1", kind: "tree", state: "running", phase: "x" } }));
  setTimeout(() => controller.abort(), 20);
  const aborted = await bridge.waitForJob(7, "j1", { intervalMs: 5, signal: controller.signal });
  assert.equal(aborted.code, "aborted");
});

test("starting jobs sends the right commands and validates the replies", async () => {
  const sent = [];
  fakeWindow((message, deliver) => {
    sent.push([message.type, message.payload]);
    if (message.type === "TREE") deliver({ source: "jurisai-extension", id: message.id, ok: true, jobId: "j1", tabId: 9 });
    else if (message.type === "PULL_IDS") deliver({ source: "jurisai-extension", id: message.id, ok: true, jobId: "j2", total: 2 });
    else deliver({ source: "jurisai-extension", id: message.id, ok: true });
  });
  assert.deepEqual(await bridge.startTreeJob("k#1"), { ok: true, jobId: "j1", tabId: 9 });
  assert.deepEqual(await bridge.startPullJob(9, ["a", "b"]), { ok: true, jobId: "j2", total: 2, tabId: 9 });
  await bridge.stopJob(9, "j2");
  assert.deepEqual(sent, [
    ["TREE", { key: "k#1", yargiTuru: "" }],
    ["PULL_IDS", { tabId: 9, ids: ["a", "b"], mode: "upload" }],
    ["STOP_JOB", { tabId: 9, jobId: "j2" }],
  ]);
  fakeWindow((message, deliver) => deliver({ source: "jurisai-extension", id: message.id, ok: true })); // eski eklenti: işi tanımaz
  const old = await bridge.startTreeJob("k#1");
  assert.equal(old.ok, false);
  assert.match(old.error, /2\.23/);
});

test("the real dosya list keeps its yargi turu, columns and per-type counts", () => {
  const liste = bridge.parseDosyaListe({
    items: [
      { key: "Ceza|a#1", esas: "2024/124", birim: "Ankara 33. Ağır Ceza Mahkemesi", yargiTuru: "Ceza", role: "Katılan", tur: "Ceza Dava Dosyası", acilis: "06.03.2024 09:25:46", durum: "Kapalı ( 27.06.2025 11:43:11 )", cells: ["Katılan", "x"] },
      { key: "İcra|b#1", esas: "2022/5", yargiTuru: "İcra", cells: [] },
    ],
    types: [{ label: "Ceza", count: 1 }, { label: "İcra", count: 1 }, { label: "Adli Tıp", count: 0 }, { label: "", count: 3 }, { label: "Bozuk", count: -2 }, null],
  });
  assert.deepEqual(liste.items.map((item) => [item.yargiTuru, item.role, item.durum]), [["Ceza", "Katılan", "Kapalı ( 27.06.2025 11:43:11 )"], ["İcra", "", ""]]);
  assert.deepEqual(liste.types, [{ label: "Ceza", count: 1 }, { label: "İcra", count: 1 }, { label: "Adli Tıp", count: 0 }, { label: "Bozuk", count: 0 }]);
});

test("new failure codes tell the user what is happening", () => {
  const navigating = bridge.describeListFailure("navigating", "x");
  assert.equal(navigating.waiting, true);
  assert.match(navigating.title, /açılıyor/);
  const failed = bridge.describeListFailure("query_failed", "x");
  assert.equal(failed.waiting, false); // yanıt vermeyen sorgu için boşuna yoklanmaz
  assert.ok(failed.steps.length > 0);
});

test("a vanished job is explained as a reloaded page or a closed UYAP session", async () => {
  fakeWindow((message, deliver) => deliver({ source: "jurisai-extension", id: message.id, ok: false, code: "unknown_job", error: "Bu iş bu sekmede yok." }));
  const result = await bridge.waitForJob(3, "j1", { intervalMs: 5 });
  assert.equal(result.ok, false);
  assert.equal(result.code, "unknown_job");
  assert.match(result.error, /oturum/i); // ham "Bu iş bu sekmede yok" değil, anlaşılır neden
});

test("lists larger than 2000 are preserved and repeated keys are not rendered twice", () => {
  const items = Array.from({ length: 2501 }, (_, i) => ({ key: `Ceza|${i}#1`, cells: [] }));
  const result = bridge.parseDosyaListe({ items: [...items, items[0]], complete: true });
  assert.equal(result.items.length, 2501);
  assert.equal(result.complete, true);
  assert.equal(result.items.at(-1).key, 'Ceza|2500#1');
});

test("partial errors survive parsing and completeness never hides invalid rows", () => {
  const result = bridge.parseDosyaListe({ items: [{ key: 'a' }, null], errors: ['İcra: sorgu yanıt vermedi', 5], complete: true });
  assert.equal(result.complete, false);
  assert.equal(result.errors.length, 2);
  assert.match(result.errors[0], /İcra/);
  assert.match(result.errors[1], /satırı okunamadı/);
  assert.equal(bridge.parseDosyaListe({ items: [{ key: 'a' }] }).complete, false);
});

test("automatic and manual list requests share one in-flight scan", async () => {
  let finish;
  let calls = 0;
  fakeWindow((message, deliver) => {
    calls += 1;
    finish = () => deliver({ source: 'jurisai-extension', id: message.id, ok: true, items: [], complete: true });
  });
  const first = bridge.listUyapDosyalari();
  const second = bridge.listUyapDosyalari();
  assert.equal(calls, 1);
  finish();
  assert.equal((await first).liste.complete, true);
  await second;
  const third = bridge.listUyapDosyalari();
  assert.equal(calls, 2);
  finish();
  await third;
});

test("transfer completion is not reported for failures, missing counters or stopped jobs", () => {
  const run = { mode: 'upload', chosen: 3, total: 3, done: 3, current: '', stats: { sent: 2, known: 0, duplicates: 1, sameContent: 0, failed: 0, errors: [] } };
  assert.equal(bridge.pullOutcome(run), 'complete');
  assert.equal(bridge.pullOutcome({ ...run, done: 2 }), 'partial');
  assert.equal(bridge.pullOutcome({ ...run, stats: { ...run.stats, failed: 1 } }), 'partial');
  assert.equal(bridge.pullOutcome({ ...run, stats: undefined }), 'partial');
  assert.equal(bridge.pullOutcome({ ...run, stats: { ...run.stats, sent: 0 } }), 'partial');
  assert.equal(bridge.pullOutcome({ ...run, result: { stopped: true } }), 'stopped');
});

test("the list preserves only a valid portal tab identity", () => {
  assert.equal(bridge.parseDosyaListe({ tabId: 37 }).tabId, 37);
  for (const tabId of [-1, 1.5, "37", null, Infinity, Number.MAX_SAFE_INTEGER + 1])
    assert.equal(bridge.parseDosyaListe({ tabId }).tabId, undefined);
});

test("oversized selection is refused instead of silently dropping the remaining evidence", async () => {
  const fake = fakeWindow(() => assert.fail('must not start a truncated upload'));
  const result = await bridge.startPullJob(1, Array.from({ length: 5001 }, (_, i) => String(i)));
  assert.equal(result.code, 'too_many');
  assert.equal(fake.listenerCount(), 0);
});

test("an oversized tree cannot claim that all evidence has been loaded", () => {
  // Sınır 200 000 (canlıda 20 000+ evraklı ceza dosyaları görüldü, 2026-10-17); 20 001 evrak artık kesilmez.
  assert.equal(bridge.parseTree({ items: Array.from({ length: 20001 }, (_, i) => ({ id: String(i) })), counts: { matches: true } }).items.length, 20001);
  const limit = bridge.MAX_TREE_ITEMS;
  const tree = bridge.parseTree({ items: Array.from({ length: limit + 1 }, (_, i) => ({ id: String(i) })), counts: { matches: true, explained: true } });
  assert.equal(tree.items.length, limit);
  assert.equal(tree.counts.matches, false);
  assert.equal(tree.counts.explained, false);
  assert.match(tree.counts.gapList[0], /200.000/);
});

test("detail completeness is checked against the parsed tables and empty unloaded panes", () => {
  const payload = (tab) => ({ who: {}, tabs: [tab], complete: true });
  const empty = { key: "hesap", label: "Dosya Hesabı", pairs: [], tables: [], complete: true };
  assert.equal(bridge.parseDetail(payload(empty)).complete, false);
  const table = { headers: ["Rol"], rows: [["Davacı"]], declared: 2, complete: true };
  assert.equal(bridge.parseDetail(payload({ ...empty, tables: [table] })).complete, false);
  assert.equal(bridge.parseDetail(payload({ ...empty, tables: [{ ...table, declared: 1 }] })).complete, true);
  assert.equal(bridge.parseDetail(payload({ ...empty, tables: [{ ...table, rows: [], declared: 0 }] })).complete, true);
  assert.equal(bridge.parseDetail(payload({ ...empty, tables: [{ ...table, rows: [], declared: null }] })).complete, false);
});

test("UYAP kişisi parmak izi + ad soyadla gelir; kimlik numarası ya da rakam/biçim taşıyan ad geçmez", () => {
  const ok = { fingerprint: "a".repeat(64), kind: "tc", portal: "vatandas", display: "AYŞE YILMAZ" };
  assert.deepEqual(bridge.parseIdentity(ok), ok);
  assert.equal(bridge.parseIdentity({ ...ok, fingerprint: "12345678901" }), null);
  assert.equal(bridge.parseIdentity({ ...ok, display: "12345678901" }), null);
  assert.equal(bridge.parseIdentity({ ...ok, display: "<b>Ayşe</b>" }), null);
  assert.equal(bridge.parseIdentity({ ...ok, kind: "email" }), null);
  // 2.26.37'nin ilk derlemesi adı maskeli gönderiyordu: güncellenmemiş eklenti "kişi okunamadı"ya düşmesin.
  assert.equal(bridge.parseIdentity({ ...ok, display: "Y*** Ü***" }).display, "Y*** Ü***");
  assert.equal(bridge.parseIdentity({ ...ok, portal: "x" }).portal, "diger");
  assert.equal(bridge.sameIdentity(ok, { ...ok }), true);
  assert.equal(bridge.sameIdentity(ok, { ...ok, fingerprint: "b".repeat(64) }), false);
  assert.equal(bridge.sameIdentity(ok, null), false);
  assert.equal(bridge.parseDosyaListe({ items: [], identity: ok }).identity.display, "AYŞE YILMAZ");
});
