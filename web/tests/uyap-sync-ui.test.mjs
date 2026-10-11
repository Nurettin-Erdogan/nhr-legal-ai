import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

test("eski kayıt sayacı güncel koşu ve sonucu varken gösterilmez; evrak ve genel başarı ayrılır", () => {
  const source = readFileSync(new URL("../src/components/UyapSyncAll.tsx", import.meta.url), "utf8");
  assert.match(source, /!running && !run && status && status\.summary\.files > 0/);
  assert.match(source, /Önceki kayıtlı evrak denetimi/);
  assert.match(source, /run\.reports\.every\(fullyVerified\)/);
  assert.match(source, /complete: "Evraklar eksiksiz"/);
  assert.match(source, /Dosya bilgileri ayrıca aşağıda gösterilir/);
});
