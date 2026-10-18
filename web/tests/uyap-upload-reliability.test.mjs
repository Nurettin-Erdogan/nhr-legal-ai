import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const source = readFileSync(new URL('../public/jurisai-avukat/background.js', import.meta.url), 'utf8');
const url = 'https://vatandas.uyap.gov.tr/view_document_brd.uyap?evrakId=synthetic';
const helpers = source.slice(source.indexOf('function fileNameFor('), source.indexOf('const SITE_HOST_RE =')) +
  source.slice(source.indexOf('const SITE_HOST_RE ='), source.indexOf('async function saveLocally('));
const context = vm.createContext({ Blob, URL, TextDecoder, AbortController, setTimeout, clearTimeout, setInterval, clearInterval,
  DEFAULTS: { timeoutMs: 45000 }, fetch: async () => { throw new Error('unexpected network'); } });
vm.runInContext(helpers + '\nglobalThis.h = {fileNameFor, dispositionFileName, binaryDocumentType, fetchDocument, isUyapKepDocument};', context);
const h = context.h;

test('RFC5987 UTF-8 filename wins; ordinary and malformed encodings have safe fallbacks', () => {
  assert.equal(h.dispositionFileName("attachment; filename=old.bin; filename*=UTF-8''Ek%201%2Etif"), 'Ek 1.tif');
  assert.equal(h.dispositionFileName('attachment; filename="Ek 1.docx"'), 'Ek 1.docx');
  assert.equal(h.dispositionFileName("attachment; filename=ok.zip; filename*=UTF-8''bad%ZZ"), 'ok.zip');
  assert.equal(h.dispositionFileName("attachment; filename*=UTF-8'tr'Evrak%00%0D%0A.png"), 'Evrak.png');
  assert.equal(h.fileNameFor({evrakAdi: 'Ek 1.pdf', fileExt: 'tif'}, 'application/download'), 'Ek 1.tif');
  assert.equal(h.fileNameFor({evrakAdi: 'Ek 1', fileExt: 'exe'}, 'application/download'), 'Ek 1.exe.bin');
  assert.equal(h.fileNameFor({evrakAdi: 'Ek 1', fileExt: '../pdf'}, 'application/download'), 'Ek 1.bin');
});

for (const [signature, mime, extension] of [
  [[0x50,0x4b,3,4], 'application/zip', 'zip'],
  [[0x49,0x49,0x2a,0], 'image/tiff', 'tif'],
  [[0x4d,0x4d,0,0x2a], 'image/tiff', 'tif'],
  [[0x89,0x50,0x4e,0x47,0x0d,0x0a,0x1a,0x0a], 'image/png', 'png'],
  [[0xff,0xd8,0xff], 'image/jpeg', 'jpg'],
  [[0x47,0x49,0x46,0x38,0x39,0x61], 'image/gif', 'gif'],
  [[0x52,0x61,0x72,0x21,0x1a,0x07], 'application/vnd.rar', 'rar'],
  [[0x37,0x7a,0xbc,0xaf,0x27,0x1c], 'application/x-7z-compressed', '7z'],
]) test(`opaque ${extension} bytes get a verified MIME, not a fabricated PDF`, async () => {
  const bytes = new Uint8Array([...signature, ...new Array(5000).fill(0)]);
  context.fetch = async () => new Response(bytes, {headers: {'Content-Type': 'application/octet-stream'}});
  const out = await h.fetchDocument(url, 1000, {evrakAdi: 'Ek 1'});
  assert.equal(out.type, mime);
  assert.equal(h.fileNameFor({evrakAdi: 'Ek 1'}, out.type), `Ek 1.${extension}`);
  assert.deepEqual(new Uint8Array(await out.blob.arrayBuffer()), bytes);
});

test('unknown/OLE/executable signatures remain unknown, never silently renamed', () => {
  for (const bytes of [[0x4d,0x5a,0,0], [0xd0,0xcf,0x11,0xe0], [1,2,3,4]]) {
    assert.equal(h.binaryDocumentType(new Uint8Array(bytes)), '');
  }
  assert.equal(h.fileNameFor({evrakAdi: 'Ek 1'}, 'application/download'), 'Ek 1.bin');
});

test('complete passive KEP recognition is independent of Diğer Evrak or other metadata labels', async () => {
  const meta = {evrakTuru: 'Diğer Evrak', evrakAdi: 'Diğer Evrak 09/11/2023'};
  const valid = "<html><body>PTT KEPHS'den bir Elektronik Postanız var</body></html>";
  assert.equal(await h.isUyapKepDocument(new Blob([valid]), meta), true);
  for (const html of [valid.replace('</body>', '<input type="password"></body>'),
    valid.replace('</body>', '<script>void(0)</script></body>'), valid.replace('var', 'var ve başka metin'),
    '<html><body>Hata Oluştu Hata Mesajı: Doğrulama hatası.</body></html>']) {
    assert.equal(await h.isUyapKepDocument(new Blob([html]), meta), false);
  }
  assert.equal(await h.isUyapKepDocument(new Blob([valid]), {...meta, evrakTuru: 'Karar'}), true);
});

const identityHelpers = (() => {
  const ctx = vm.createContext({});
  vm.runInContext(source.slice(source.indexOf('function cleanIdentity('), source.indexOf('/** Güçlü ETag')) +
    '\nglobalThis.out = {cleanIdentity, identityHeaders, ACCOUNT_CODES};', ctx);
  return ctx.out;
})();

function uploader(replies, overrides = {}) {
  const calls = [], waits = [];
  const ctx = vm.createContext({Blob, FormData, AbortController, setTimeout, clearTimeout,
    fileNameFor: () => 'synthetic.pdf',
    // Gerçek kimlik yardımcıları (background.js'ten aynen).
    ...identityHelpers,
    throwIfPullCancelled: signal => { if (signal?.aborted) throw Object.assign(new Error('cancelled'), {code:'UYAP_CANCELLED'}); },
    pullWait: async (ms, signal) => { waits.push(ms); if (signal?.aborted) throw Object.assign(new Error('cancelled'), {code:'UYAP_CANCELLED'}); },
    fetch: async (target, options) => { calls.push({target, ...options}); assert.ok(replies.length, 'unbounded POST retry'); return replies.shift()(options); },
    ...overrides,
  });
  vm.runInContext(source.slice(source.indexOf('function uploadFailure('), source.indexOf('async function handleUpload(')) +
    '\nglobalThis.upload = uploadDocument;', ctx);
  return {calls, waits, upload: (meta = {evrakId:'stable-id'}, signal) => ctx.upload({apiUrl:'http://localhost:8766/upload', apiKey:'synthetic'}, meta, new Blob(['%PDF-1.4']), 'application/pdf', signal)};
}
const reply = (status = 200, body = {ok:true, id:'synthetic-id'}, headers = {}) => () => new Response(JSON.stringify(body), {status, headers});

test('transient destination retry reuses the exact downloaded Blob/FormData and honors Retry-After', async () => {
  const u = uploader([reply(503, {error:'busy'}, {'Retry-After':'3'}), reply(200, {ok:true, id:'existing-id', duplicate:true})]);
  assert.equal((await u.upload()).duplicate, true);
  assert.equal(u.calls.length, 2);
  assert.equal(u.calls[0].body, u.calls[1].body);
  assert.deepEqual(u.waits, [3000]);
});

test('destination retries are bounded and unkeyed uploads are never repeated', async () => {
  const u = uploader([reply(500), reply(500), reply(500)]);
  await assert.rejects(u.upload(), e => e.code === 'destination_unavailable' && e.uploadFailed);
  assert.equal(u.calls.length, 3);
  const unkeyed = uploader([reply(500)]);
  await assert.rejects(unkeyed.upload({}), e => e.code === 'destination_unavailable');
  assert.equal(unkeyed.calls.length, 1);
});

for (const [status, code] of [[401,'pairing_rejected'], [403,'pairing_rejected'], [409,'JURISAI_DOCUMENT_REJECTED'],
  [413,'JURISAI_DOCUMENT_REJECTED'], [415,'JURISAI_DOCUMENT_REJECTED'], [507,'destination_unavailable']]) {
  test(`destination HTTP ${status} never causes another download or upload attempt`, async () => {
    const u = uploader([reply(status, {error:'synthetic refusal'})]);
    await assert.rejects(u.upload(), e => e.code === code && e.uploadFailed === true);
    assert.equal(u.calls.length, 1);
    assert.deepEqual(u.waits, []);
  });
}

test('explicit permanent server error and long Retry-After do not loop', async () => {
  for (const response of [reply(500, {error:'storage_path_invalid', retryable:false}), reply(429, {}, {'Retry-After':'600'})]) {
    const u = uploader([response]);
    await assert.rejects(u.upload());
    assert.equal(u.calls.length, 1);
    assert.deepEqual(u.waits, []);
  }
});

test('HTTP 200 without a verified saved ID cannot become successful', async () => {
  for (const body of [{}, {ok:true}, {ok:false,id:'x'}, {ok:true,id:' '}]) {
    const u = uploader([reply(200, body)]);
    await assert.rejects(u.upload(), e => e.code === 'destination_unavailable');
    assert.equal(u.calls.length, 1);
  }
});

test('cancel during POST aborts its signal immediately and never retries', async () => {
  const controller = new AbortController();
  const u = uploader([options => new Promise((resolve, reject) => {
    options.signal.addEventListener('abort', () => reject(new Error('aborted')), {once:true});
    controller.abort();
  })]);
  await assert.rejects(u.upload(undefined, controller.signal), e => e.code === 'UYAP_CANCELLED');
  assert.equal(u.calls.length, 1);
  assert.equal(u.calls[0].signal.aborted, true);
  assert.deepEqual(u.waits, []);
});

test('expired response body never becomes late success and its deadline is cleaned up', async () => {
  let expire, cleared = 0;
  const u = uploader([() => ({ok:true, status:200, json:async () => {
    expire();
    return {ok:true,id:'too-late'};
  }})], {setTimeout: fn => { expire = fn; return 123; }, clearTimeout: id => { assert.equal(id,123); cleared++; }});
  await assert.rejects(u.upload({}), e => e.code === 'destination_unavailable' && /zaman aşımı/.test(e.message));
  assert.equal(cleared, 1);
  assert.equal(u.calls[0].signal.aborted, true);
});

test('an already cancelled upload never sends a POST', async () => {
  const controller = new AbortController();
  controller.abort();
  const u = uploader([]);
  await assert.rejects(u.upload(undefined, controller.signal), e => e.code === 'UYAP_CANCELLED');
  assert.equal(u.calls.length, 0);
});

test('the real download/upload handler makes one UYAP GET despite three failing destination POSTs', async () => {
  const calls = [];
  const ctx = vm.createContext({Blob, URL, TextDecoder, FormData, AbortController, setTimeout, clearTimeout, setInterval, clearInterval,
    DEFAULTS: {timeoutMs:45000}, pull:null, pullRun:null,
    getSettings: async () => ({apiUrl:'http://localhost:8766/upload', apiKey:'synthetic', timeoutMs:1000}),
    pullTargetUrl: () => url,
    fetch: async (target, options) => {
      calls.push([target, options.method || 'GET']);
      return target === url ? new Response('%PDF-1.4 synthetic', {headers:{'Content-Type':'application/pdf'}})
        : new Response(JSON.stringify({error:'busy'}), {status:503});
    },
  });
  vm.runInContext(helpers + source.slice(source.indexOf('function uploadFailure('), source.indexOf('async function handleUpload(')) +
    source.slice(source.indexOf('function acceptedDirectUrl('), source.indexOf('/* ---------- Doğrudan indirme denemesi ----------')) +
    '\npullWait = async () => {}; globalThis.run = handlePullFetch;', ctx);
  const result = await ctx.run({evrakId:'stable',evrakAdi:'synthetic'}, 'upload', url, false);
  assert.equal(result.code, 'destination_unavailable');
  assert.equal(result.uploadFailed, true);
  assert.equal(result.ok, false);
  assert.equal(calls.filter(([, method]) => method === 'GET').length, 1);
  assert.equal(calls.filter(([, method]) => method === 'POST').length, 3);
});

test('the UYAP person travels as fingerprint + name headers; an unreadable person stops without retry', async () => {
  const identity = {fingerprint: 'a'.repeat(64), kind: 'tc', portal: 'vatandas', display: 'AYŞE YILMAZ'};
  const ok = uploader([reply(200)]);
  await ok.upload({evrakId: 'stable-id', identity});
  assert.equal(ok.calls[0].headers['X-UYAP-Identity'], 'a'.repeat(64));
  assert.equal(decodeURIComponent(ok.calls[0].headers['X-UYAP-Display']), 'AYŞE YILMAZ');
  assert.equal(JSON.stringify(ok.calls[0].headers).includes('12345678901'), false);
  const forged = uploader([reply(200)]);
  await forged.upload({evrakId: 'stable-id', identity: {...identity, display: 'Ayşe 12345678901'}});
  assert.equal(forged.calls[0].headers['X-UYAP-Identity'], undefined, 'rakam taşıyan ad (kimlik numarası olabilir) gönderilmez');
  for (const code of ['uyap_account_mismatch', 'uyap_account_taken', 'uyap_identity_required']) {
    const refused = uploader([reply(code === 'uyap_identity_required' ? 428 : 409, {error: 'başka kişi', code, retryable: false})]);
    await assert.rejects(refused.upload({evrakId: 'stable-id', identity}), e => e.code === 'uyap_account_mismatch' && e.uploadFailed && !e.retryable);
    assert.equal(refused.calls.length, 1);
  }
});
