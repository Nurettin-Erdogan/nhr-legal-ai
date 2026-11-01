import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import ts from "typescript";

function load(relative) {
  const code = readFileSync(new URL(relative, import.meta.url), "utf8");
  const { outputText } = ts.transpileModule(code, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  });
  const module = { exports: {} };
  new Function("module", "exports", outputText)(module, module.exports);
  return module.exports;
}
const forms = load("../src/lib/account-forms.ts");

test("yanlış parola uzunluk uyarısına dönüşmez", () => {
  // Eski sürüm içinde "parola" geçen her mesajı "Şifre en az 10 karakter olmalı." yapıyordu.
  assert.equal(
    forms.authErrorMessage("E-posta veya parola hatalı", 401),
    "E-posta veya şifre hatalı.",
  );
  assert.equal(
    forms.authErrorMessage("Bu e-posta zaten kayıtlı", 409),
    "Bu e-posta ile zaten bir hesap var. Giriş yapmayı deneyin.",
  );
});

test("kilit mesajı sunucunun söylediği süreyle aynen gösterilir", () => {
  const locked =
    "Çok fazla başarısız deneme. Güvenlik için giriş 15 dakika kapatıldı; sonra tekrar deneyin ya da şifrenizi sıfırlayın.";
  assert.equal(forms.authErrorMessage(locked, 429), locked);
});

test("sunucunun Türkçe mesajı değiştirilmez, doğrulama kalıpları çevrilir", () => {
  const terms =
    "Kayıt için Kullanım Şartları'nı ve Gizlilik Politikası'nı (KVKK aydınlatma metni) kabul etmelisiniz.";
  assert.equal(forms.authErrorMessage(terms, 400), terms);
  assert.equal(
    forms.authErrorMessage("String should have at least 10 characters", 422),
    "Şifre en az 10 karakter olmalı.",
  );
  assert.equal(
    forms.authErrorMessage("value is not a valid email address", 422),
    "Geçerli bir e-posta adresi girin.",
  );
});

test("şifre değiştirme: mevcut şifre, uzunluk, tekrar ve aynılık denetlenir", () => {
  assert.match(
    forms.validatePasswordChange("", "yeni-sifre-12345", "yeni-sifre-12345", true),
    /Mevcut şifrenizi/,
  );
  assert.match(forms.validatePasswordChange("eski-sifre-1", "kisa", "kisa", true), /en az 10/);
  assert.match(
    forms.validatePasswordChange("eski-sifre-1", "yeni-sifre-12345", "baska-sifre-1234", true),
    /aynı değil/,
  );
  assert.match(
    forms.validatePasswordChange("yeni-sifre-12345", "yeni-sifre-12345", "yeni-sifre-12345", true),
    /aynı olamaz/,
  );
  assert.equal(
    forms.validatePasswordChange("eski-sifre-1", "yeni-sifre-12345", "yeni-sifre-12345", true),
    null,
  );
  // Google ile açılmış, şifresi olmayan hesap mevcut şifre olmadan şifre belirleyebilir.
  assert.equal(
    forms.validatePasswordChange("", "yeni-sifre-12345", "yeni-sifre-12345", false),
    null,
  );
});

test("hesap silme onay ifadesini ve şifreyi ister", () => {
  assert.match(forms.validateAccountDeletion("sil", "x", true), /HESABIMI SİL/);
  assert.match(forms.validateAccountDeletion("HESABIMI SİL", "", true), /Şifrenizi/);
  assert.equal(forms.validateAccountDeletion(" HESABIMI SİL ", "sifre", true), null);
  assert.equal(forms.validateAccountDeletion("HESABIMI SİL", "", false), null);
});

test("ad soyad boş bırakılamaz", () => {
  assert.match(forms.validateFullName(" A "), /en az 2/);
  assert.equal(forms.validateFullName("Ayşe Demir"), null);
});
