import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const source = (path) => readFileSync(new URL(`../src/${path}`, import.meta.url), "utf8");

test("both entry points use the FastAPI Google flow, not obsolete Lovable tokens", () => {
  const login = source("routes/auth.tsx");
  const dialog = source("components/AuthDialog.tsx");
  const api = source("lib/auth-api.ts");
  for (const page of [login, dialog]) {
    assert.match(page, /googleLoginAvailable/);
    assert.match(page, /beginGoogleLogin/);
    assert.doesNotMatch(page, /lovable\.auth|signInWithOAuth|setSession/);
  }
  assert.match(api, /\/api\/auth\/google\/start/);
  assert.match(api, /\/api\/auth\/google\/status/);
});

test("Google callback checks our API session and explains explicit account linking", () => {
  const callback = source("routes/auth/callback.tsx");
  assert.match(callback, /currentUser\(\)/);
  assert.match(callback, /account_exists/);
  assert.doesNotMatch(callback, /supabase\.auth|getSession\(\)/);
});
