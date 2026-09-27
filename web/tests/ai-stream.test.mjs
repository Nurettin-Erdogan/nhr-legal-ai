import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import ts from 'typescript';

function compile(file, deps = {}) {
  const source = readFileSync(new URL(file, import.meta.url), 'utf8').replaceAll('import.meta.env.VITE_API_URL', 'undefined');
  const code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
  const module = { exports: {} };
  new Function('require', 'module', 'exports', code)((id) => {
    if (!(id in deps)) throw new Error('Unexpected dependency ' + id);
    return deps[id];
  }, module, module.exports);
  return module.exports;
}
const summaryModel = compile('../src/lib/search-summary.ts');
const { askAssistant } = compile('../src/lib/ai-api.ts', {
  '@/lib/auth-api': { inMemoryAccessToken: () => '' }, './search-summary': summaryModel,
});
const summary = { candidate_documents: 29, verified_documents: 12, selected_documents: 6,
  pending_documents: 17, unverified_excluded: 17, verification_attempted: 1,
  verification_promoted: 0, verification_stop: 'time_budget', retrieval_partial: false, exhaustive: false };

function mockStream(t, text) {
  const bytes = new TextEncoder().encode(text);
  let index = 0;
  const state = { canceled: false, released: false, credentials: null };
  const reader = {
    read: async () => index >= bytes.length ? { done: true } : { done: false, value: bytes.slice(index, ++index) },
    cancel: async () => { state.canceled = true; },
    releaseLock: () => { state.released = true; },
  };
  t.mock.method(globalThis, 'fetch', async (_url, init) => {
    state.credentials = init.credentials;
    return { ok: true, body: { getReader: () => reader } };
  });
  return state;
}

test('split UTF-8 progress stream preserves summary and final answer', async t => {
  const answer = { answer: 'Türkçe yanıt', citations: [], grounded: true, search_summary: summary };
  const state = mockStream(t, JSON.stringify({ stage: 'search_summary', ...summary }) + '\n' + JSON.stringify({ stage: 'done', result: answer }));
  const seen = [];
  const result = await askAssistant('Örnek soru', { onSearchSummary: s => seen.push(s) });
  assert.deepEqual(seen, [summary]);
  assert.equal(result.answer, answer.answer);
  assert.deepEqual(result.search_summary, summary);
  assert.equal(state.credentials, 'include');
  assert.ok(state.canceled && state.released);
});

test('error after progress never becomes a successful answer; stream closes', async t => {
  const state = mockStream(t, JSON.stringify({ stage: 'search_summary', ...summary }) + '\n' + JSON.stringify({ stage: 'error', detail: 'Kaynak doğrulanamadı' }));
  const seen = [];
  await assert.rejects(askAssistant('Örnek soru', { onSearchSummary: s => seen.push(s) }), /Kaynak doğrulanamadı/);
  assert.equal(seen.length, 1);
  assert.ok(state.canceled && state.released);
});

test('disconnection without done event is an error', async t => {
  const state = mockStream(t, JSON.stringify({ stage: 'ping' }));
  await assert.rejects(askAssistant('Örnek soru', {}), /bağlantı kesildi/);
  assert.ok(state.canceled && state.released);
});

test('legacy answer does not fabricate candidate counters', async t => {
  mockStream(t, JSON.stringify({ stage: 'done', result: { answer: 'Yanıt', citations: [] } }));
  assert.equal((await askAssistant('Örnek soru', {})).search_summary, undefined);
});
