import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const route = (name) =>
  readFileSync(
    new URL(`../src/routes/_authenticated/dashboard.${name}.tsx`, import.meta.url),
    "utf8",
  );

test("office settings persist owner-scoped preferences, not a fictitious office identity", () => {
  const source = route("settings");
  assert.match(source, /\.from\("call_settings"\)/);
  assert.match(source, /\.upsert\(values, \{ onConflict: "owner_id" \}\)/);
  assert.match(source, /Telefon hattı[\s\S]*?bağlı\s+değil/);
  assert.doesNotMatch(source, /Korkmaz Hukuk|Bağlantıyı Kes/);
});

test("unconnected payments and modules do not present invented activity", () => {
  const payments = route("payments");
  const modules = route("modules");
  assert.match(payments, /Ödeme hizmeti bağlı değil/);
  assert.match(modules, /Harici modüller bağlı değil/);
  assert.doesNotMatch(payments, /245\.000|otomatik arama planlandı|Yeni Tahsilat/);
  assert.doesNotMatch(modules, /● Aktif|onClick=\{\(\) => toggle/);
});

test("call page reports real records and never offers disconnected telephony actions", () => {
  const source = route("call-center");
  assert.match(source, /\.from\("calls"\)/);
  assert.match(source, /Telefon veya sesli AI sağlayıcısı bağlı değil/);
  assert.doesNotMatch(source, /Test Araması|Numara Al|Korkmaz Hukuk|1\.247/);
});

test("legacy appointment route uses the real calendar; remaining mock screens are honest", () => {
  assert.match(route("appointments"), /Navigate to="\/dashboard\/calendar"/);
  for (const name of ["execution", "leads", "reports", "staff"]) {
    assert.match(route(name), /UnavailableOfficeFeature/);
    assert.doesNotMatch(route(name), /@\/data\/mock|Yeni Üye|₺ 925K|%97/);
  }
});
