import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import test from 'node:test';
import ts from 'typescript';
import { renderToStaticMarkup } from 'react-dom/server';
import { createElement } from 'react';

const require = createRequire(import.meta.url);
function compile(relative, dependencies = {}) {
  const code = readFileSync(new URL(relative, import.meta.url), 'utf8');
  const result = ts.transpileModule(code, { compilerOptions: {
    module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022,
  }});
  const module = { exports: {} };
  new Function('require', 'module', 'exports', result.outputText)(
    (id) => dependencies[id] ?? require(id), module, module.exports);
  return module.exports;
}
const model = compile('../src/lib/search-summary.ts');
const { SearchSummary } = compile('../src/components/SearchSummary.tsx', { '../lib/search-summary': model });
const sample = {
  candidate_documents: 29, verified_documents: 12, selected_documents: 6,
  pending_documents: 17, unverified_excluded: 17, verification_attempted: 1,
  verification_promoted: 0, verification_stop: 'time_budget', retrieval_partial: false,
  exhaustive: false,
};

test('missing/old counters are not fabricated', () => {
  for (const x of [undefined, null, {}, { ...sample, candidate_documents: -1 },
    { ...sample, selected_documents: 30 }, { ...sample, candidate_documents: NaN },
    { ...sample, exhaustive: true }]) assert.equal(model.parseSearchSummary(x), undefined);
});
test('counts and citations have distinct labels', () => {
  const html = renderToStaticMarkup(createElement(SearchSummary, { summary: sample, citedCount: 2 }));
  for (const label of ['Aday belge', 'Kaynak kontrolünü geçen', 'Modele verilen', 'Atıf yapılan belge']) {
    assert.ok(html.includes(label));
  }
  for (const n of [29, 12, 6, 2]) assert.ok(html.includes(`>${n}</dd>`));
  assert.ok(html.includes('toplamı değildir'));
  assert.ok(html.includes('17 doğrulanmamış aday cevaba alınmadı'));
});
test('partial retrieval and portal limit remain visible', () => {
  const html = renderToStaticMarkup(createElement(SearchSummary, {
    summary: { ...sample, retrieval_partial: true, verification_stop: 'captcha' },
  }));
  assert.ok(html.includes('zaman aşımına'));
  assert.ok(html.includes('CAPTCHA'));
  assert.ok(!html.includes('Atıf yapılan belge'));
});
test('unknown stop reason is not interpreted as successful verification', () => {
  assert.ok(model.verificationNotice({ ...sample, verification_stop: 'unexpected' }).includes('kullanılmadı'));
});
test('only count fields are forwarded, no source text or keys', () => {
  assert.deepEqual(model.parseSearchSummary({ ...sample, secret: 'do-not-forward' }), sample);
});

test('fast answer reports its scope without claiming a full corpus search', () => {
  const summary = model.parseSearchSummary({ ...sample, retrieval_strategy: 'verified_statute', research_deferred: true });
  assert.equal(summary.research_deferred, true);
  const html = renderToStaticMarkup(createElement(SearchSummary, { summary }));
  assert.ok(html.includes('Geniş korpus taraması bu sayılara dahil değildir'));
  assert.ok(html.includes('kaynak panelinde'));
});

test('only the latest completed fast answer triggers separate research', () => {
  const summary = { ...sample, retrieval_strategy: 'verified_statute', research_deferred: true };
  assert.equal(model.shouldAutoResearch(2, 4, false, summary), true);
  assert.equal(model.shouldAutoResearch(0, 4, false, summary), false);
  assert.equal(model.shouldAutoResearch(2, 4, true, summary), false);
  assert.equal(model.shouldAutoResearch(2, 4, false, sample), false);
  assert.equal(model.shouldAutoResearch(2, 4, false, undefined), false);
});
