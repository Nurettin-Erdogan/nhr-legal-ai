import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const source = readFileSync(new URL('../public/jurisai-avukat/background.js', import.meta.url), 'utf8');
const url = 'https://vatandas.uyap.gov.tr/main/jsp/download_document_brd.uyap?evrakId=opaque';
const data = new TextEncoder().encode('PK0123456789complete');
const headers = { 'Content-Type': 'application/zip', ETag: '"version-1"', 'Content-Length': String(data.length) };
function response(body, extra = {}, status = 200, responseUrl = url) {
  const out = new Response(body, { status, headers: { ...headers, ...extra } });
  Object.defineProperty(out, 'url', { value: responseUrl });
  return out;
}
function broken(prefix, extra = {}, { eof = false, stall = false } = {}) {
  return signal => {
    let sent = false;
    const stream = new ReadableStream({
      start(controller) {
        signal.addEventListener('abort', () => controller.error(new DOMException('abort', 'AbortError')), { once: true });
      },
      pull(controller) {
        if (!sent) { sent = true; controller.enqueue(data.slice(0, prefix)); }
        else if (eof) controller.close();
        else if (!stall) controller.error(new TypeError('network interrupted'));
      },
    }, { highWaterMark: 0 });
    return response(stream, extra);
  };
}
function tail(start, extra = {}, status = 206, responseUrl = url) {
  return () => response(data.slice(start), {
    'Content-Range': `bytes ${start}-${data.length - 1}/${data.length}`,
    'Content-Length': String(data.length - start), ...extra,
  }, status, responseUrl);
}
function harness(replies, overrides = {}) {
  const calls = [];
  const context = vm.createContext({
    Blob, URL, TextDecoder, AbortController, setTimeout, clearTimeout, setInterval, clearInterval,
    DEFAULTS: { timeoutMs: 45000 }, sleep: async () => {}, ...overrides,
    fetch: async (target, options) => {
      calls.push({ target, ...options });
      assert.ok(replies.length, 'unbounded retry or unexpected request');
      return replies.shift()(options.signal);
    },
  });
  vm.runInContext(source.slice(source.indexOf('const SITE_HOST_RE ='), source.indexOf('async function saveLocally(')) +
    '\nglobalThis.read = readUyapDocument;', context);
  return { read: context.read, calls };
}

test('a complete document uses one uncached credentialed request and keeps all bytes', async () => {
  const h = harness([() => response(data)]);
  const out = await h.read(url, 1000);
  assert.deepEqual(new Uint8Array(await out.blob.arrayBuffer()), data);
  assert.equal(h.calls.length, 1);
  assert.equal(h.calls[0].credentials, 'include');
  assert.equal(h.calls[0].cache, 'no-store');
  assert.equal(h.calls[0].headers.Range, undefined);
});

test('an already cancelled job never starts an HTTP request', async () => {
  const abort = new AbortController();
  abort.abort();
  const h = harness([() => response(data)]);
  await assert.rejects(h.read(url, 100, null, abort.signal), error => error.code === 'UYAP_CANCELLED');
  assert.equal(h.calls.length, 0);
});

test('cancelling a stalled body aborts immediately without range resume or retry', async () => {
  const abort = new AbortController();
  const progress = [];
  const h = harness([broken(7, {}, {stall: true})]);
  await assert.rejects(h.read(url, 100, value => {
    progress.push(value);
    if (value.receivedBytes) abort.abort();
  }, abort.signal), error => {
    assert.equal(error.code, 'UYAP_CANCELLED');
    assert.notEqual(error.retryable, true);
    return true;
  });
  assert.equal(h.calls.length, 1);
  assert.ok(h.calls[0].signal.aborted);
  assert.equal(progress.at(-1).receivedBytes, 7);
});

test('cancelling while waiting for headers aborts the outstanding fetch', async () => {
  const abort = new AbortController();
  const h = harness([signal => new Promise((resolve, reject) => {
    signal.addEventListener('abort', () => reject(new DOMException('abort', 'AbortError')), {once: true});
    abort.abort();
  })]);
  await assert.rejects(h.read(url, 100, null, abort.signal), error => error.code === 'UYAP_CANCELLED');
  assert.equal(h.calls.length, 1);
  assert.ok(h.calls[0].signal.aborted);
});

test('a cut stream resumes only its remaining bytes with strong If-Range validation', async () => {
  const h = harness([broken(7), tail(7)]);
  const out = await h.read(url, 1000);
  assert.deepEqual(new Uint8Array(await out.blob.arrayBuffer()), data);
  assert.equal(h.calls.length, 2);
  assert.equal(h.calls[1].headers.Range, 'bytes=7-');
  assert.equal(h.calls[1].headers['If-Range'], '"version-1"');
  assert.ok(h.calls[0].signal.aborted, 'the previous download is cancelled before resuming');
});

test('a truncated EOF and a stalled stream can resume without losing the prefix', async () => {
  for (const mode of [{ eof: true }, { stall: true }]) {
    const h = harness([broken(7, {}, mode), tail(7)]);
    assert.deepEqual(new Uint8Array(await (await h.read(url, 20)).blob.arrayBuffer()), data);
  }
});

test('a chunked document can obtain its total length from a validated range', async () => {
  const h = harness([broken(7, { 'Content-Length': '' }), tail(7)]);
  assert.deepEqual(new Uint8Array(await (await h.read(url, 1000)).blob.arrayBuffer()), data);
});

for (const [name, extra, status, responseUrl] of [
  ['ignored Range (200)', {}, 200],
  ['changed ETag', { ETag: '"version-2"' }],
  ['missing ETag', { ETag: '' }],
  ['weak ETag', { ETag: 'W/"version-1"' }],
  ['wrong range start', { 'Content-Range': `bytes 0-${data.length - 1}/${data.length}` }],
  ['changed total', { 'Content-Range': `bytes 7-${data.length}/${data.length + 1}` }],
  ['short range end', { 'Content-Range': `bytes 7-${data.length - 2}/${data.length}` }],
  ['wildcard total', { 'Content-Range': `bytes 7-${data.length - 1}/*` }],
  ['unsafe integer', { 'Content-Range': 'bytes 7-9007199254740992/9007199254740993' }],
  ['wrong range length', { 'Content-Length': '1' }],
  ['changed MIME/login', { 'Content-Type': 'text/html' }],
  ['compressed range', { 'Content-Encoding': 'gzip' }],
  ['changed resource URL', {}, 206, url.replace('opaque', 'different')],
]) test(`${name} never becomes a concatenated document`, async () => {
  const h = harness([broken(7), tail(7, extra, status, responseUrl)]);
  await assert.rejects(h.read(url, 1000), /parçalar birleştirilmedi/);
  assert.equal(h.calls.length, 2);
  assert.ok(h.calls[1].signal.aborted);
});

test('without a strong validator or with compressed bytes there is no range attempt', async () => {
  for (const extra of [{ ETag: '' }, { ETag: 'W/"version-1"' }, { 'Content-Encoding': 'gzip' }]) {
    const h = harness([broken(7, extra)]);
    await assert.rejects(h.read(url, 1000), /yarıda kesti/);
    assert.equal(h.calls.length, 1);
  }
});

test('no-progress interruptions are not resumed and at most two resume attempts are made', async () => {
  const empty = harness([broken(0)]);
  await assert.rejects(empty.read(url, 1000), /yarıda kesti/);
  assert.equal(empty.calls.length, 1);
  const brokenTail = start => () => {
    let sent = false;
    return response(new ReadableStream({ pull(c) {
      if (!sent) { sent = true; c.enqueue(data.slice(start, start + 1)); }
      else c.error(new TypeError('cut again'));
    } }, { highWaterMark: 0 }), {
      'Content-Range': `bytes ${start}-${data.length - 1}/${data.length}`,
      'Content-Length': String(data.length - start),
    }, 206);
  };
  const h = harness([broken(7), brokenTail(7), brokenTail(8)]);
  await assert.rejects(h.read(url, 1000), /yarıda kesti/);
  assert.equal(h.calls.length, 3);
});

test('extra bytes, unsolicited partial responses and foreign hosts are rejected', async () => {
  const extra = harness([() => response(data, { 'Content-Length': '3' })]);
  await assert.rejects(extra.read(url, 1000), /boyutu doğrulanamadı/);
  const partial = harness([tail(7)]);
  await assert.rejects(partial.read(url, 1000), /beklenmeyen kısmi/);
  const foreign = harness([]);
  await assert.rejects(foreign.read('https://example.com/document', 1000), /Yalnız güvenli/);
  assert.equal(foreign.calls.length, 0);
});

test('the decoded length of a compressed complete response is not compared with wire length', async () => {
  const h = harness([() => response(data, { 'Content-Encoding': 'gzip', 'Content-Length': '3' })]);
  assert.deepEqual(new Uint8Array(await (await h.read(url, 1000)).blob.arrayBuffer()), data);
});

test('large active downloads get bounded idle grace but short custom timeouts are preserved', async () => {
  const big = new Uint8Array(8 * 1024 * 1024);
  for (const [timeout, grace] of [[45000, 120000], [1500, 1500]]) {
    const delays = [];
    const h = harness([() => response(big, { 'Content-Length': String(big.length) })], {
      setTimeout: (_, delay) => { delays.push(delay); return delays.length; }, clearTimeout: () => {},
    });
    await h.read(url, timeout);
    assert.deepEqual(delays, [2 * 60 * 60 * 1000, timeout, timeout, grace]);
  }
});

test('the worker heartbeat is scoped to the active job and cleaned on success or error', async () => {
  for (const fail of [false, true]) {
    const cleared = [];
    let tick;
    let pings = 0;
    const h = harness([() => { tick(); return response(fail ? null : data, {}, fail ? 500 : 200); }], {
      chrome: { runtime: { getPlatformInfo: async () => { pings += 1; } } },
      setInterval: (callback, delay) => { assert.equal(delay, 20000); tick = callback; return 123; },
      clearInterval: id => cleared.push(id),
    });
    if (fail) await assert.rejects(h.read(url, 1000), /HTTP 500/);
    else await h.read(url, 1000);
    assert.equal(pings, 1);
    assert.deepEqual(cleared, [123]);
  }
});

test('progress reports only byte counts, verified total, last data time and resume count', async () => {
  const h = harness([broken(7), tail(7)]);
  const progress = [];
  await h.read(url, 1000, value => progress.push(value));
  assert.equal(progress[0].receivedBytes, 0);
  assert.equal(progress[0].expectedBytes, data.length);
  assert.equal(progress[0].lastDataAt, null);
  assert.equal(progress.at(-1).receivedBytes, data.length);
  assert.equal(progress.at(-1).resumes, 1);
  assert.ok(progress.at(-1).lastDataAt > 0);
  for (const value of progress) {
    assert.deepEqual(Object.keys(value).sort(), ['expectedBytes', 'lastDataAt', 'receivedBytes', 'resumes']);
    assert.ok(Object.values(value).every(v => v === null || typeof v === 'number'));
  }
});
