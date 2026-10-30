import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
import ts from "typescript";
import { renderToStaticMarkup } from "react-dom/server";
import { createElement } from "react";

const require = createRequire(import.meta.url);
function compile(relative, dependencies = {}) {
  const source = readFileSync(new URL(relative, import.meta.url), "utf8").replace(
    "import.meta.env.VITE_API_URL",
    '"http://test.local"',
  );
  const result = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      jsx: ts.JsxEmit.ReactJSX,
      target: ts.ScriptTarget.ES2022,
    },
  });
  const module = { exports: {} };
  new Function("require", "module", "exports", result.outputText)(
    (id) => dependencies[id] ?? require(id),
    module,
    module.exports,
  );
  return module.exports;
}
const model = compile("../src/lib/case-detail.ts", { "@/lib/db": { db: {} } });
const { CaseDetailView } = compile("../src/components/CaseDetailView.tsx", {
  "../lib/case-detail": model,
});
const id = "11111111-1111-4111-8111-111111111111";
const clientId = "22222222-2222-4222-8222-222222222222";
const record = {
  id,
  client_id: clientId,
  title: "Gerçek dava",
  court: "Ankara Mahkemesi",
  status: "active",
  notes: "<script>example</script>",
  updated_at: "2026-09-27T12:00:00Z",
};
function fake(overrides = {}) {
  const requests = [];
  const responses = {
    cases: { data: record, error: null },
    clients: { data: { id: clientId, full_name: "Örnek Müvekkil" }, error: null },
    ...Object.fromEntries(
      ["case_documents", "tasks", "calendar_events", "calls"].map((t) => [
        t,
        { data: [], error: null },
      ]),
    ),
    ...overrides,
  };
  return {
    requests,
    from(table) {
      const query = { table, filters: [] };
      requests.push(query);
      return {
        select(columns) {
          query.columns = columns;
          return this;
        },
        eq(key, value) {
          query.filters.push([key, value]);
          return this;
        },
        order(column, options) {
          query.order = [column, options];
          return this;
        },
        limit(n) {
          query.limit = n;
          return this;
        },
        range(from, to) {
          query.offset = from;
          query.limit = to - from + 1;
          return this;
        },
        maybeSingle() {
          query.single = true;
          return this;
        },
        then(resolve, reject) {
          const result = responses[table];
          return Promise.resolve(
            query.offset !== undefined && Array.isArray(result.data)
              ? { ...result, data: result.data.slice(query.offset, query.offset + query.limit) }
              : result,
          ).then(resolve, reject);
        },
      };
    },
  };
}
test("invalid ID never reaches API; inaccessible cases do not query related records", async () => {
  const client = fake();
  await assert.rejects(model.loadCaseDetail("1", client), /Geçersiz/);
  assert.equal(client.requests.length, 0);
  for (const response of [
    { data: null, error: null },
    { data: { id: clientId }, error: null },
    { data: null, error: { message: "Yetkisiz" } },
  ]) {
    const denied = fake({ cases: response });
    await assert.rejects(model.loadCaseDetail(id, denied));
    assert.equal(denied.requests.length, 1);
  }
});
test("case and all sections use exact IDs, explicit columns and bounded queries", async () => {
  const client = fake();
  const data = await model.loadCaseDetail(id, client);
  assert.equal(data.clientName, "Örnek Müvekkil");
  assert.deepEqual(client.requests[0].filters, [["id", id]]);
  for (const query of client.requests.slice(1)) {
    assert.notEqual(query.columns, "*");
    if (query.table === "clients") assert.deepEqual(query.filters, [["id", clientId]]);
    else {
      assert.deepEqual(query.filters, [["case_id", id]]);
      assert.equal(query.limit, query.table === "case_documents" ? 1000 : 51);
    }
  }
});
test("section failures stay visible without hiding the case or claiming empty data", async () => {
  const data = await model.loadCaseDetail(
    id,
    fake({ tasks: { data: null, error: { message: "Görev servisi hatası" } } }),
  );
  assert.equal(data.record.id, id);
  const html = renderToStaticMarkup(
    createElement(CaseDetailView, { data, initialTab: "Görevler", onDownload() {} }),
  );
  assert.match(html, /role="alert"/);
  assert.match(html, /Görev servisi hatası/);
  assert.doesNotMatch(html, /bağlı kayıt bulunmuyor/);
});
test("missing linked client and malformed section responses are not fabricated", async () => {
  const data = await model.loadCaseDetail(
    id,
    fake({ clients: { data: null, error: null }, calls: { data: {}, error: null } }),
  );
  assert.match(data.clientError, /görüntülenemedi/);
  assert.match(data.calls.error, /Beklenmeyen/);
});
test("large sections explicitly disclose the 50 row window", async () => {
  const data = await model.loadCaseDetail(
    id,
    fake({
      tasks: {
        data: Array.from({ length: 51 }, (_, i) => ({
          id: String(i),
          title: "Görev " + i,
          status: "todo",
        })),
        error: null,
      },
    }),
  );
  assert.equal(data.tasks.rows.length, 50);
  assert.equal(data.tasks.hasMore, true);
  const html = renderToStaticMarkup(
    createElement(CaseDetailView, { data, initialTab: "Görevler", onDownload() {} }),
  );
  assert.match(html, /Son 50 kayıt/);
  assert.doesNotMatch(html, /Görev 50</);
});
test("all UYAP case documents load in bounded batches, not only the first 50", async () => {
  const documents = Array.from({ length: 1051 }, (_, i) => ({
    id: `doc-${i}`,
    file_name: `evrak-${i}.pdf`,
  }));
  const client = fake({ case_documents: { data: documents, error: null } });
  const data = await model.loadCaseDetail(id, client);
  assert.equal(data.documents.rows.length, 1051);
  assert.equal(data.documents.hasMore, false);
  assert.deepEqual(
    client.requests.filter((x) => x.table === "case_documents").map((x) => x.offset),
    [0, 1000],
  );
  assert.equal(data.documents.rows.at(-1).id, "doc-1050");
});
test("summary uses actual records, no invented AI success or activities", async () => {
  const data = await model.loadCaseDetail(id, fake());
  const html = renderToStaticMarkup(createElement(CaseDetailView, { data, onDownload() {} }));
  assert.match(html, /Ankara Mahkemesi/);
  assert.match(html, /Örnek Müvekkil/);
  assert.match(html, /Belirtilmemiş/);
  assert.doesNotMatch(html, /%72|bilirkişi raporuna|Selim Korkmaz/);
});
test("notes are rendered as escaped text and each empty tab is explicit", async () => {
  const data = await model.loadCaseDetail(id, fake());
  const html = renderToStaticMarkup(
    createElement(CaseDetailView, { data, initialTab: "Notlar", onDownload() {} }),
  );
  assert.match(html, /&lt;script&gt;/);
  assert.doesNotMatch(html, /<script>/);
  for (const tab of ["Evraklar", "Görevler", "Takvim", "Aramalar"]) {
    assert.match(
      renderToStaticMarkup(
        createElement(CaseDetailView, { data, initialTab: tab, onDownload() {} }),
      ),
      /bağlı kayıt bulunmuyor/,
    );
  }
});
test("document tab shows real file and download errors without exposing storage path", async () => {
  const data = await model.loadCaseDetail(
    id,
    fake({
      case_documents: {
        data: [
          {
            id: "doc",
            file_name: "Dilekçe.pdf",
            storage_path: "private-key",
            created_at: "2026-09-27",
          },
        ],
        error: null,
      },
    }),
  );
  const html = renderToStaticMarkup(
    createElement(CaseDetailView, {
      data,
      initialTab: "Evraklar",
      onDownload() {},
      downloading: "doc",
      downloadError: "İndirme hatası",
    }),
  );
  assert.match(html, /Dilekçe.pdf/);
  assert.match(html, /İndiriliyor/);
  assert.match(html, /disabled/);
  assert.match(html, /İndirme hatası/);
  assert.doesNotMatch(html, /private-key/);
});
test("dates handle missing and malformed values", () => {
  assert.equal(model.displayCaseDate(null), "Belirtilmemiş");
  assert.equal(model.displayCaseDate("not-a-date"), "Geçersiz tarih");
  assert.equal(model.displayCaseDate("2026-09-27", true), "27.09.2026");
});

test("real office client sends authenticated select-only requests and isolates HTTP errors", async (t) => {
  const { db } = compile("../src/lib/db.ts", {
    "@/lib/auth-api": { inMemoryAccessToken: () => "test-token" },
  });
  const requests = [];
  t.mock.method(globalThis, "fetch", async (url, init) => {
    requests.push({ url, ...init, body: JSON.parse(init.body) });
    if (url.endsWith("/clients")) return new Response("invalid-json", { status: 200 });
    if (url.endsWith("/tasks"))
      return new Response(JSON.stringify({ detail: "Erişim reddedildi" }), { status: 403 });
    return new Response(
      JSON.stringify({ data: url.endsWith("/cases") ? record : [], count: null }),
      { status: 200 },
    );
  });
  const data = await model.loadCaseDetail(id, db);
  assert.equal(requests.length, 6);
  for (const request of requests) {
    assert.ok(request.url.startsWith("http://test.local/api/office/"));
    assert.equal(request.method, "POST");
    assert.equal(request.credentials, "include");
    assert.equal(request.headers.Authorization, "Bearer test-token");
    assert.equal(request.body.op, "select");
  }
  assert.equal(data.record.id, id);
  assert.match(data.clientError, /yüklenemedi/);
  assert.equal(data.tasks.error, "Erişim reddedildi");
});
