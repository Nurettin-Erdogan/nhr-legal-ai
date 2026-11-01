import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import ts from "typescript";

// Yönetici paneli yardımcıları (2026-10-24). Yetki sunucuda denetlenir; bunlar yalnız görünüm.
const source = readFileSync(new URL("../src/lib/admin-panel.ts", import.meta.url), "utf8");
const { outputText } = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
});
const lib = { exports: {} };
new Function("module", "exports", outputText)(lib, lib.exports);
const panel = lib.exports;

test("only the admin role opens the panel; anything malformed does not", () => {
  assert.equal(panel.isAdmin(["lawyer", "admin"]), true);
  for (const roles of [["lawyer"], [], null, undefined, "admin"])
    assert.equal(panel.isAdmin(roles), false);
});

test("audit actions read in Turkish and unknown codes stay visible instead of disappearing", () => {
  assert.equal(panel.actionLabel("admin.user_status"), "Kullanıcı durumunu değiştirdi");
  assert.equal(panel.actionLabel("auth.login_failed"), "Başarısız giriş denemesi");
  assert.equal(panel.actionLabel("something.new"), "something.new");
});

test("formatting never shows NaN or Invalid Date", () => {
  assert.equal(panel.formatDateTime(null), "—");
  assert.equal(panel.formatDateTime("bozuk"), "—");
  assert.equal(panel.formatCount(undefined), "—");
  assert.equal(panel.formatCount(1234567), (1234567).toLocaleString("tr-TR"));
  assert.equal(panel.formatUsd(4.6905), "4.69 $");
  assert.equal(panel.formatBytes(475746638), "476 MB");
  assert.equal(panel.formatBytes(-1), "—");
});

test("a backup older than a day is flagged (the nightly backup stopped silently once)", () => {
  const now = new Date("2026-10-24T12:00:00Z");
  assert.equal(Math.round(panel.backupAgeHours("2026-10-23T12:00:00Z", now)), 24);
  assert.ok(panel.backupAgeHours("2026-10-22T02:30:00Z", now) > panel.BACKUP_STALE_HOURS);
  assert.equal(panel.backupAgeHours(null, now), null);
  assert.equal(panel.backupAgeHours("bozuk", now), null);
});

test("both access modes have a label and an explanation", () => {
  assert.deepEqual(Object.keys(panel.ACCESS_MODE_LABELS).sort(), ["allowlist", "open"]);
  for (const mode of ["open", "allowlist"]) {
    assert.ok(panel.ACCESS_MODE_LABELS[mode].label && panel.ACCESS_MODE_LABELS[mode].description);
  }
  assert.match(panel.ACCESS_MODE_LABELS.allowlist.description, /Yöneticiler her zaman girer/);
});

test("switching to the access list says how many accounts will be shut out before it happens", () => {
  const confirm = panel.accessModeConfirm("allowlist", 29);
  assert.match(confirm.description, /29 hesap artık giriş yapamayacak/);
  assert.match(confirm.description, /Verileri silinmez/);
  assert.equal(confirm.destructive, true);
  assert.ok(confirm.title && confirm.confirmLabel);
  assert.doesNotMatch(panel.accessModeConfirm("allowlist", 0).description, /hesap artık/);
  assert.match(panel.accessModeConfirm("open", 29).description, /herkes/);
  assert.equal(panel.removeAccessConfirm("a@b.com", "allowlist").destructive, true);
});

test("an access-list entry tells whether the person has opened an account yet", () => {
  assert.equal(panel.accountStateLabel(null), "Henüz hesap açmadı");
  assert.equal(panel.accountStateLabel("active"), "Hesabı var");
  assert.equal(panel.accountStateLabel("suspended"), "Hesabı askıda");
});

test("blocked logins and access-list changes read in Turkish in the audit log", () => {
  assert.equal(
    panel.actionLabel("auth.login_blocked"),
    "Giriş engellendi (erişim listesinde değil)",
  );
  assert.equal(panel.actionLabel("admin.access_add"), "Erişim listesine ekledi");
  assert.equal(panel.actionLabel("admin.access_remove"), "Erişim listesinden çıkardı");
  assert.equal(panel.actionLabel("admin.access_mode"), "Erişim modunu değiştirdi");
});
