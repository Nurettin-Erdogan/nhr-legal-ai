import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import ts from "typescript";
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);

function compile(path, mocks = {}) {
  const source = readFileSync(new URL(path, import.meta.url), "utf8").replaceAll(
    "import.meta.env",
    "({})",
  );
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  });
  const module = { exports: {} };
  new Function("require", "module", "exports", outputText)(
    (name) => {
      if (name in mocks) return mocks[name];
      throw new Error("Unexpected import " + name);
    },
    module,
    module.exports,
  );
  return module.exports;
}
const auth = { inMemoryAccessToken: () => "juris-token" };
const jobs = compile("../src/lib/document-jobs.ts", { "@/lib/auth-api": auth });
const drive = compile("../src/lib/google-drive.ts", { "@/lib/auth-api": auth });
const layout = compile("../src/lib/document-layout.ts");
const editor = compile("../src/lib/document-editor.ts");

test("layout clamps malformed values and shares exact paper dimensions with DOCX", () => {
  assert.deepEqual(
    layout.normalizeDocumentLayout({ fontPt: 999, marginMm: NaN, lineHeight: -1, paper: "bogus" }),
    { paper: "a4", fontPt: 16, marginMm: 20, lineHeight: 1, alignment: "left", pageNumbers: true },
  );
  const a4 = layout.docxPageProperties({ marginMm: 25 });
  assert.deepEqual(a4.size, { width: 11906, height: 16838 });
  assert.equal(a4.margin.left, 1417);
  assert.equal(
    layout.documentPageStyle({ paper: "letter", alignment: "justify" }).width,
    "215.9mm",
  );
  assert.equal(layout.documentPageStyle({ fontPt: 12 }).fontSize, "12pt");
});

test("queue parser rejects impossible progress, unknown modules and malformed windows", () => {
  const raw = {
    id: "job",
    module: "draft",
    state: "running",
    progress: {
      total: 2000,
      done: 5,
      documents: [{ file_name: "test", windows_done: 2, windows_total: 3 }],
    },
    output_id: null,
    error: null,
  };
  assert.equal(jobs.parseDocumentJob(raw).progress.total, 2000);
  for (const patch of [
    { state: "unknown" },
    { module: "fake" },
    { output: 4 },
    { progress: { ...raw.progress, done: 2001 } },
    {
      progress: {
        ...raw.progress,
        documents: [{ file_name: "test", windows_done: 3, windows_total: 2 }],
      },
    },
  ])
    assert.throws(() => jobs.parseDocumentJob({ ...raw, ...patch }));
});

test("queue submits all selected ids with authenticated cookie/token and keeps server errors", async () => {
  const original = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (url, options) => {
    calls.push({ url, options });
    return new Response(JSON.stringify({ job_id: "job" }), { status: 202 });
  };
  try {
    assert.equal(
      await jobs.startDocumentJob({
        module: "auto_summary",
        document_ids: Array(2000).fill("doc"),
      }),
      "job",
    );
    assert.equal(JSON.parse(calls[0].options.body).document_ids.length, 2000);
    assert.equal(calls[0].options.headers.Authorization, "Bearer juris-token");
    assert.equal(calls[0].options.credentials, "include");
    globalThis.fetch = async () =>
      new Response(JSON.stringify({ detail: "Devam eden işiniz var." }), { status: 409 });
    await assert.rejects(jobs.startDocumentJob({ module: "draft" }), /Devam eden işiniz var/);
  } finally {
    globalThis.fetch = original;
  }
});

test("Drive SDK loader refuses arbitrary scripts before accessing the DOM", () => {
  assert.throws(() => drive.loadGoogleScript("https://evil.invalid/script.js"), /Geçersiz/);
});

test("Drive reads actual metadata, exports Google Docs, and never sends Google token to JurisAI", async () => {
  const original = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (url, options) => {
    calls.push({ url, options });
    if (calls.length === 1)
      return new Response(
        JSON.stringify({
          name: "Örnek",
          mimeType: "application/vnd.google-apps.document",
          capabilities: { canDownload: true },
        }),
      );
    if (calls.length === 2) return new Response("docx bytes");
    return new Response(JSON.stringify({ id: "document", duplicate: false }));
  };
  try {
    const file = await drive.downloadDriveFile({
      id: "drive_id_123",
      name: "spoofed",
      mimeType: "fake",
      token: "google-token",
    });
    assert.equal(file.name, "Örnek.docx");
    assert.match(calls[1].url, /\/export\?mimeType=/);
    await drive.importDriveFile(file);
    assert.equal(calls[0].options.headers.Authorization, "Bearer google-token");
    assert.equal(calls[2].options.headers.Authorization, "Bearer juris-token");
    assert.equal(calls[2].options.body.get("file").name, "Örnek.docx");
    assert.ok(!calls[2].options.body.has("token"));
  } finally {
    globalThis.fetch = original;
  }
});

test("Drive download permission refusal and unsupported native formats never fetch contents", async () => {
  const original = globalThis.fetch;
  let count = 0;
  try {
    for (const metadata of [
      { capabilities: { canDownload: false } },
      { mimeType: "application/vnd.google-apps.spreadsheet" },
      { mimeType: "application/pdf", size: 51 * 1024 * 1024 },
    ]) {
      count = 0;
      globalThis.fetch = async () => {
        count++;
        return new Response(JSON.stringify(metadata));
      };
      await assert.rejects(drive.downloadDriveFile({ id: "drive_id_123", token: "google-token" }));
      assert.equal(count, 1);
    }
  } finally {
    globalThis.fetch = original;
  }
});

test("Word taskpane uses explicit submission and append-only insertion without browser token storage", () => {
  const script = readFileSync(new URL("../public/word/taskpane.js", import.meta.url), "utf8");
  assert.match(script, /Word\.InsertLocation\.after/);
  assert.doesNotMatch(script, /InsertLocation\.replace|localStorage|sessionStorage|innerHTML/);
  assert.match(script, /credentials:\s*"omit"/);
  assert.match(script, /generation\s*!==\s*epoch/);
  assert.match(
    readFileSync(new URL("../public/word/taskpane.html", import.meta.url), "utf8"),
    /Bu metni JurisAI'a gönder ve işle/,
  );
});

test("generated DOCX really contains Turkish text, selected page layout, emphasis and page fields", async () => {
  const docx = require("docx");
  const { unzipSync, strFromU8 } = require("fflate");
  const exporter = compile("../src/lib/document-export.ts", {
    docx: docx,
    "@/lib/document-editor": editor,
    "@/lib/document-layout": layout,
  });
  const buffer = await docx.Packer.toBuffer(
    exporter.buildDocumentDocx("# SONUÇ\nÇağrı Şahin: **340.000 TL**, 07.10.2026. [K1]", {
      ...layout.DEFAULT_DOCUMENT_LAYOUT,
      paper: "letter",
      marginMm: 25,
      fontPt: 12,
      lineHeight: 2,
      alignment: "justify",
    }),
  );
  const files = unzipSync(buffer);
  const xml = strFromU8(files["word/document.xml"]);
  assert.match(xml, /Çağrı Şahin/);
  assert.match(xml, /340.000 TL/);
  assert.match(xml, /07.10.2026/);
  assert.match(xml, /\[K1\]/);
  assert.match(xml, /w:pgSz[^>]*w:w="12240"[^>]*w:h="15840"/);
  assert.match(xml, /w:pgMar[^>]*w:top="1417"/);
  assert.match(xml, /w:sz w:val="24"/);
  assert.match(xml, /w:line="480"/);
  assert.match(xml, /w:jc w:val="both"/);
  const footer = strFromU8(files["word/footer1.xml"]);
  assert.match(footer, /PAGE/);
  assert.match(footer, /NUMPAGES/);
});

test("generated PDF embeds fonts and really uses selected Letter page dimensions", async () => {
  const { jsPDF } = require("jspdf");
  let captured;
  function TestPdf(options) {
    const pdf = new jsPDF(options);
    pdf.save = () => {
      captured = pdf.output("arraybuffer");
    };
    return pdf;
  }
  const exporter = compile("../src/lib/pdf-export.ts", {
    jspdf: { jsPDF: TestPdf },
    "@/lib/document-layout": layout,
  });
  const original = globalThis.fetch;
  globalThis.fetch = async (url) =>
    new Response(readFileSync(new URL("../public" + url, import.meta.url)));
  try {
    await exporter.exportTextPdf("# TEST\nÇağrı Şahin 340.000 TL", "test", {
      ...layout.DEFAULT_DOCUMENT_LAYOUT,
      paper: "letter",
    });
    assert.ok(captured.byteLength > 5000);
    const text = Buffer.from(captured).toString("latin1");
    assert.match(text, /\/MediaBox \[0 0 612\. 792\.\]/);
    assert.match(text, /\/FontFile2/);
  } finally {
    globalThis.fetch = original;
  }
});
