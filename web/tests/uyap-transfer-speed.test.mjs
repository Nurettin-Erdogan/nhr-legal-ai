import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

// The production helpers, not copies of their implementation. Browser integration
// tests also exercise the full service worker/content-script download pipeline.
const background = readFileSync(new URL('../public/jurisai-avukat/background.js', import.meta.url), 'utf8');
const context = vm.createContext({ Blob, TextDecoder });
vm.runInContext(background.slice(background.indexOf('function htmlDocumentText('), background.indexOf('async function fetchDocument(')) +
  '\nglobalThis.helpers = {isUyapReceipt, isUyapKepDocument};', context);
const { isUyapReceipt, isUyapKepDocument } = context.helpers;
const content = readFileSync(new URL('../public/jurisai-avukat/content.js', import.meta.url), 'utf8');
vm.runInContext(content.slice(content.indexOf('  function pullPauseMs('), content.indexOf('  async function runPull(')) +
  '\nglobalThis.pause = pullPauseMs; globalThis.itemOnly = pullItemOnlyError; globalThis.sessionFailure = pullSessionFailure;', context);
const pause = context.pause;
const itemOnly = context.itemOnly;

const meta = { evrakTuru: '89/1 Haciz İhbarnamesi Cevabı', evrakAdi: '89/1 Haciz İhbarnamesi Cevabı 01/01/2025' };
const templates = [
  '<html><body><div>KEP Paketi: kurum@hs01.kep.tr</div><table><tr><td>Konu:</td><td>Yanıt</td></tr><tr><td>Tarih:</td><td>01.01.2025</td></tr></table></body></html>',
  '<html><body>KEP İletisi: kurum@banka.com.tr<br>Konu: Yanıt<br>Tarih: 01.01.2025</body></html>',
  "<html><body><div><p>PTT KEPHS'den bir Elektronik Postanız var</p></div></body></html>",
];
const blob = html => new Blob([html], { type: 'text/html; charset=utf-8' });

test('three known passive UYAP KEP templates are recognized with matching tree metadata', async () => {
  for (const html of templates) {
    assert.equal(await isUyapKepDocument(blob(html), meta), true);
    assert.equal(await isUyapKepDocument(blob(html), { evrakTuru: 'KEP Cevabı' }), true);
    assert.equal(await isUyapKepDocument(blob(html), { evrakTuru: 'Karar' }), false);
    assert.equal(await isUyapKepDocument(blob(html), null), false);
  }
});

test('generic HTML, incomplete envelopes and keyword-only pages are never documents', async () => {
  for (const html of [
    '<html><body>KEP</body></html>',
    '<html><body>KEP Paketi: Konu: Tarih:</body></html>',
    '<html><body>KEP Paketi: x@banka.com.tr Konu: X</body></html>',
    '<html><body>KEP İletisi: x@banka.com.tr Tarih: X</body></html>',
    "<html><body>PTT KEPHS'den bir Elektronik Postanız var x@kurum.gov.tr</body></html>",
  ]) assert.equal(await isUyapKepDocument(blob(html), meta), false, html);
});

test('KEP attached only as Ek needs both narrow attachment metadata and a complete passive KEP template', async () => {
  for (const html of templates) {
    for (const name of ['Ek', 'Ek 1', '  Ek 23  ']) {
      assert.equal(await isUyapKepDocument(blob(html), { evrakTuru: 'Ek', evrakAdi: name }), true);
    }
    for (const metadata of [{ evrakTuru: 'Karar', evrakAdi: 'Ek 1' },
      { evrakTuru: 'Ek', evrakAdi: 'Ek karar' }, { evrakAdi: 'Ek 1' }]) {
      assert.equal(await isUyapKepDocument(blob(html), metadata), false);
    }
  }
  for (const html of ['<html><body>Ek 1 KEP</body></html>', '<html><body>KEP İletisi: kurum@banka.com.tr</body></html>']) {
    assert.equal(await isUyapKepDocument(blob(html), { evrakTuru: 'Ek', evrakAdi: 'Ek 1' }), false);
  }
});

test('login/error pages and active content fail even if receipt or KEP markers match', async () => {
  const receipt = '<html><body>VEKALET PULU MAKBUZU ADALET BAKANLIĞI Makbuz No 123</body></html>';
  for (const extra of [
    '<input type="password">', '<form action="/login"></form>', '<script>void(0)</script>',
    '<iframe src="/giris"></iframe>', '<object data="x"></object>', '<embed src="x">',
    '<base href="x">', '<div onclick="void(0)">X</div>',
    '<a href="javascript:alert(1)">X</a>', '<meta http-equiv="refresh" content="0;url=/giris">',
    '<meta http-equiv="&#114;efresh" content="0;url=/giris">', '<svg></svg>', '<link href="x">',
    'OTURUMUNUZ SONA ERDİ', 'OTURUM AÇIN', 'GİRİŞ YAP', 'Yetkiniz bulunmamaktadır',
  ]) {
    assert.equal(await isUyapKepDocument(blob(templates[0].replace('</body>', extra + '</body>')), meta), false, extra);
    assert.equal(await isUyapKepDocument(blob(templates[0].replace('</body>', extra + '</body>')), { evrakTuru: 'Ek', evrakAdi: 'Ek 1' }), false, extra);
    assert.equal(await isUyapReceipt(blob(receipt.replace('</body>', extra + '</body>')), { evrakTuru: 'Makbuz' }), false, extra);
    assert.equal(await isUyapReceipt(blob(receipt.replace('</body>', extra + '</body>')), { evrakTuru: 'Ek', evrakAdi: 'Ek 75' }), false, extra);
  }
});

test('HTML entities and Turkish uppercase letters do not cause a valid receipt to be retried', async () => {
  const receipt = blob('<html><body>VEKALET&nbsp;PULU&#160;MAKBUZU ADALET BAKANLI&#x11e;I Makbuz&nbsp;No 123</body></html>');
  assert.equal(await isUyapReceipt(receipt, { evrakTuru: 'Makbuz' }), true);
  assert.equal(await isUyapReceipt(receipt, { evrakTuru: 'Karar' }), false);
});

test('a passive receipt attached as Ek is accepted only with a matching attachment type and narrow title', async () => {
  const receipt = blob('<html><body>VEKALET PULU MAKBUZU T.C. ADALET BAKANLIĞI Makbuz No 123</body></html>');
  for (const name of ['Ek', 'Ek 1', 'Ek 75', '  Ek 23  ']) {
    assert.equal(await isUyapReceipt(receipt, { evrakTuru: 'Ek', evrakAdi: name }), true, name);
  }
  for (const metadata of [
    { evrakTuru: 'Karar', evrakAdi: 'Ek 75' },
    { evrakTuru: 'Ek', evrakAdi: 'Giriş' },
    { evrakTuru: 'Ek', evrakAdi: 'Ek karar' },
    { evrakAdi: 'Ek 75' }, null,
  ]) assert.equal(await isUyapReceipt(receipt, metadata), false);
  assert.equal(await isUyapReceipt(blob('<html><body>Ek 75</body></html>'), { evrakTuru: 'Ek', evrakAdi: 'Ek 75' }), false);
});

test('the portal variants of KEP subject/date headings need not contain colons', async () => {
  assert.equal(await isUyapKepDocument(blob('<html><body><div>KEP İletisi:<br>kurum@banka.com.tr<br>İleti konusu Test<br>İleti tarihi 01.01.2025</div></body></html>'), meta), true);
  assert.equal(await isUyapKepDocument(blob("<html><body>PTT KEPHS'den bir Elektronik Postanız var [başka içerik]</body></html>"), meta), false);
  assert.equal(await isUyapKepDocument(blob('<html><meta http-equiv="Content-Type" content="text/html; charset=utf-8"><body><div>KEP Paketi:<br>kurum@hs01.kep.tr tarafından 01.01.2025 tarihinde Cevap konulu ileti</div></body></html>'), meta), true);
});

test('unmatched metadata and oversized HTML are rejected before reading the body', async () => {
  const unreadable = { size: 2 * 1024 * 1024, text: () => { throw Error('body must not be read'); } };
  assert.equal(await isUyapKepDocument(unreadable, meta), false);
  assert.equal(await isUyapReceipt(unreadable, { evrakTuru: 'Makbuz' }), false);
});

test('successful transfers subtract work time, never overlap and keep the minimum interval', () => {
  assert.equal(pause(1500, 1500, false, true, 2100, true), 0);
  assert.equal(pause(1500, 1500, false, true, 100, true), 1400);
  assert.equal(pause(1500, 1500, true, true, 700, true), 0);
  assert.equal(pause(1500, 1500, true, true, 100, true), 400);
  assert.equal(pause(1500, 1500, true, true, -100, true), 500);
  for (const elapsed of [0, 50, 100, 500, 700, 2100, 60000]) {
    assert.ok(elapsed + pause(1500, 1500, false, true, elapsed, true) >= 1500);
    assert.ok(elapsed + pause(1500, 1500, true, true, elapsed, true) >= 500);
  }
});

test('failures and recovery backoff are not shortened; final/stopped item adds no pointless delay', () => {
  assert.equal(pause(1500, 1500, true, false, 60000, true), 1500);
  assert.equal(pause(3000, 1500, true, false, 60000, true), 3000);
  assert.equal(pause(20000, 1500, true, true, 60000, true), 20000);
  assert.equal(pause(1500, 1500, false, true, 0, false), 0);
  assert.equal(pause(20000, 1500, false, false, 0, false), 0);
});

test('transient save failures and validation refusals still allow fresh capture and backoff', () => {
  const error = 'UYAP bu evrakı önizlemede vermiyor ve "Kaydet" adresinden de alınamadı: indirme durdu';
  assert.equal(itemOnly({error, retryable: true}), false);
  assert.equal(itemOnly({error, code: 'UYAP_VALIDATION_FAILED'}), false);
  assert.equal(itemOnly({error}), true);
  assert.equal(itemOnly({error: 'Desteklenmeyen dosya türü'}), true);
  assert.equal(itemOnly({error: 'UYAP yanıt vermedi'}), false);
  assert.equal(itemOnly(null), false);
});

test('deterministic pacing benchmark: 100 sequential 700ms direct transfers remove 50s redundant wait', () => {
  const oldMs = 100 * (700 + 500);
  const newMs = Array.from({ length: 100 }, (_, i) => 700 + pause(1500, 1500, true, true, 700, i < 99))
    .reduce((a, b) => a + b, 0);
  assert.equal(oldMs, 120000);
  assert.equal(newMs, 70000);
});

test('generic errors never force login; explicit auth and permission codes remain distinct', () => {
  for (const error of ['Hata Oluştu — Güvenli Çıkış', 'Bağlantı hatası', 'oturum kapanmış olabilir']) {
    assert.equal(context.sessionFailure({ok: false, error, code: 'UYAP_PORTAL_ERROR'}), false);
  }
  assert.equal(context.sessionFailure({code: 'UYAP_SESSION_EXPIRED'}), true);
  assert.equal(context.sessionFailure({code: 'login_required'}), true);
  assert.equal(context.sessionFailure({code: 'UYAP_VALIDATION_FAILED'}), false);
  assert.equal(context.sessionFailure({code: 'UYAP_ACCESS_DENIED'}), false);
  assert.equal(itemOnly({code: 'UYAP_ACCESS_DENIED'}), true);
});

test('content polling returns a ready result without the old fixed 700ms sleep', async () => {
  const sleeps = [];
  const requests = [];
  const local = vm.createContext({
    Date, pulling: {stop: false}, sleep: async ms => sleeps.push(ms),
    chrome: {runtime: {sendMessage: async msg => {
      requests.push(msg);
      return msg.type.endsWith('START') ? {started: true} : {ok: true};
    }}},
  });
  vm.runInContext(content.slice(content.indexOf('  async function pullFetch('), content.indexOf('  function pullItemOnlyError(')) +
    '\nglobalThis.fetchOne = pullFetch;', local);
  assert.equal((await local.fetchOne({}, async () => true)).ok, true);
  assert.deepEqual(sleeps, []);
  assert.deepEqual(requests.map(msg => [msg.type, msg.waitMs]), [
    ['JURISAI_PULL_FETCH_START', undefined], ['JURISAI_PULL_FETCH_POLL', 1000],
  ]);
});

test('bounded polling remains compatible with an older worker without a busy loop', async () => {
  const sleeps = [];
  let polls = 0;
  const local = vm.createContext({
    Date, pulling: {stop: false}, sleep: async ms => sleeps.push(ms),
    chrome: {runtime: {sendMessage: async msg => msg.type.endsWith('START') ? {started: true}
      : ++polls === 1 ? {pending: true} : {ok: true}}},
  });
  vm.runInContext(content.slice(content.indexOf('  async function pullFetch('), content.indexOf('  function pullItemOnlyError(')) +
    '\nglobalThis.fetchOne = pullFetch;', local);
  assert.equal((await local.fetchOne({}, async () => true)).ok, true);
  assert.deepEqual(sleeps, [200]);
});

test('deterministic small-document benchmark preserves 500ms pacing while removing polling slack', () => {
  // Simulated 100ms work, not a claim about live UYAP throughput.
  const previous = 100 * 700;
  const improved = Array.from({length: 100}, (_, i) => 100 + pause(1500, 1500, true, true, 100, i < 99))
    .reduce((a, b) => a + b, 0);
  assert.equal(previous, 70000);
  assert.equal(improved, 49600);
});
