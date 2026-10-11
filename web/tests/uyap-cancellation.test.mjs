import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const source = readFileSync(new URL('../public/jurisai-avukat/background.js', import.meta.url), 'utf8');
const sender = {tab: {id: 7, url: 'https://vatandas.uyap.gov.tr/main/'}, frameId: 0};
function harness() {
  let listener;
  const context = vm.createContext({
    AbortController, setTimeout, clearTimeout, UYAP_HOST: /^https:\/\/(?:[a-z0-9-]+\.)*(?:uyap|adalet)\.gov\.tr(?:\/|$)/i,
    textArg: value => String(value || ''), pullRun: null, pull: null,
    getSettings: async () => ({apiUrl: 'http://localhost:8766/upload', apiKey: 'test'.repeat(8), throttleMs: 1500}),
    chrome: {runtime: {onMessage: {addListener: fn => {listener = fn;}}}},
  });
  vm.runInContext(source.slice(source.indexOf('function throwIfPullCancelled('), source.indexOf('/** Güçlü ETag')) +
    source.slice(source.indexOf('function ownsPullRun('), source.indexOf('chrome.tabs.onRemoved.addListener(')) +
    source.slice(source.indexOf('chrome.runtime.onMessage.addListener(', source.indexOf('async function runDirectProbe(')),
      source.indexOf('chrome.runtime.onMessage.addListener(', source.indexOf('case "JURISAI_PULL_END":'))) +
    '\nglobalThis.abortRun = abortPullRun;', context);
  const send = (type, payload = {}, from = sender) => new Promise(resolve => listener({type, ...payload}, from, resolve));
  return {context, send, abort: (...args) => context.abortRun(...args)};
}

test('only the owning tab and matching job may cancel the running transfer', async () => {
  const h = harness();
  assert.equal((await h.send('JURISAI_PULL_BEGIN', {jobId: 'job-1'})).ok, true);
  const run = h.context.pullRun;
  for (const [from, jobId] of [[{...sender, tab: {...sender.tab, id: 8}}, 'job-1'],
    [{...sender, frameId: 1}, 'job-1'], [sender, 'old-job']]) {
    assert.equal((await h.send('JURISAI_PULL_CANCEL', {jobId}, from)).ok, false);
    assert.equal(run.controller.signal.aborted, false);
  }
  assert.equal(h.abort(8, 'job-1'), false);
  assert.equal(h.abort(7, 'old-job'), false);
  assert.equal((await h.send('JURISAI_PULL_CANCEL', {jobId: 'job-1'})).ok, true);
  assert.equal(run.controller.signal.aborted, true);
});

test('a late END from a different job or frame does not erase an active transfer', async () => {
  const h = harness();
  await h.send('JURISAI_PULL_BEGIN', {jobId: 'job-1'});
  const run = h.context.pullRun;
  for (const [from, jobId] of [[sender, 'old-job'], [{...sender, frameId: 1}, 'job-1'],
    [{...sender, tab: {...sender.tab, id: 8}}, 'job-1']]) {
    await h.send('JURISAI_PULL_END', {jobId}, from);
    assert.equal(h.context.pullRun, run);
    assert.equal(run.controller.signal.aborted, false);
  }
  await h.send('JURISAI_PULL_END', {jobId: 'job-1'});
  assert.equal(run.controller.signal.aborted, true);
  assert.equal(h.context.pullRun, null);
  assert.equal((await h.send('JURISAI_PULL_BEGIN', {jobId: 'job-2'})).ok, true);
});

test('another BEGIN cannot overwrite a running job and lose its abort controller', async () => {
  const h = harness();
  const out = await Promise.all([h.send('JURISAI_PULL_BEGIN', {jobId: 'job-1'}),
    h.send('JURISAI_PULL_BEGIN', {jobId: 'job-2'})]);
  assert.equal(out.filter(item => item.ok).length, 1);
  assert.equal(out.find(item => !item.ok).code, 'busy');
  assert.equal(h.context.pullRun.jobId, 'job-1');
});

test('cancellation interrupts retry/cooldown waits instead of waiting twenty seconds', async () => {
  const h = harness();
  await h.send('JURISAI_PULL_BEGIN', {jobId: 'job-1'});
  const started = performance.now();
  const wait = h.send('JURISAI_PULL_WAIT', {jobId: 'job-1', ms: 20000});
  await h.send('JURISAI_PULL_CANCEL', {jobId: 'job-1'});
  assert.equal((await wait).code, 'UYAP_CANCELLED');
  assert.ok(performance.now() - started < 500);
});

test('non-UYAP sources cannot begin, cancel, arm or end a transfer', async () => {
  const h = harness();
  for (const from of [{}, {...sender, url: 'http://localhost:3000/'},
    {...sender, url: 'https://vatandas.uyap.gov.tr.evil.example/'}]) {
    for (const type of ['BEGIN', 'CANCEL', 'END', 'ARM', 'FETCH', 'STATUS', 'WAIT']) {
      assert.equal((await h.send(`JURISAI_PULL_${type}`, {}, from)).code, 'wrong_source');
    }
  }
  assert.equal(h.context.pullRun, null);
});
