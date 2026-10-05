import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

const read = (name) => readFileSync(new URL(`../public/${name}`, import.meta.url), "utf8");

test("the manifest makes the app installable: name, start page, standalone and real icons", () => {
  const manifest = JSON.parse(read("manifest.webmanifest"));
  assert.equal(manifest.display, "standalone");
  assert.equal(manifest.start_url, "/dashboard");
  assert.equal(manifest.lang, "tr");
  const sizes = manifest.icons.map((icon) => icon.sizes);
  assert.ok(sizes.includes("192x192") && sizes.includes("512x512"));
  assert.ok(manifest.icons.some((icon) => icon.purpose === "maskable"));
  for (const icon of manifest.icons) {
    const file = readFileSync(new URL(`../public${icon.src}`, import.meta.url));
    assert.equal(file.subarray(1, 4).toString(), "PNG", `${icon.src} PNG değil`);
  }
});

function load() {
  const listeners = {};
  const store = new Map();
  const context = {
    self: { addEventListener: (type, fn) => (listeners[type] = fn), skipWaiting: () => "skip", clients: { claim: () => "claim" } },
    caches: {
      open: async () => ({ addAll: async (urls) => urls.forEach((url) => store.set(url, "x")) }),
      keys: async () => ["jurisai-shell-v1", "eski"],
      delete: async (key) => store.set(`silindi:${key}`, true),
      match: async (url) => (store.has(url) ? `önbellek:${url}` : undefined),
    },
    fetch: async () => {
      throw new Error("ağ yok");
    },
  };
  vm.runInNewContext(read("sw.js"), context);
  return { listeners, context, store };
}

test("the service worker only intercepts page navigations and serves the offline page when the network fails", async () => {
  const { listeners } = load();
  await listeners.install({ waitUntil: (promise) => promise });
  let responded;
  const event = (request) => ({ request, respondWith: (promise) => (responded = promise) });
  listeners.fetch(event({ method: "GET", mode: "navigate", url: "/dashboard" }));
  assert.equal(await responded, "önbellek:/offline.html");
  responded = undefined;
  for (const request of [
    { method: "GET", mode: "cors", url: "/api/legal/search?q=kira" },
    { method: "POST", mode: "cors", url: "/api/ai/answer" },
    { method: "GET", mode: "no-cors", url: "/assets/app.js" },
  ]) {
    listeners.fetch(event(request));
    assert.equal(responded, undefined, `${request.url} ağdan bağımsız ele alınmamalı`);
  }
});

test("only the offline page and icons are cached, never API data (KVKK)", async () => {
  const { listeners, store } = load();
  await listeners.install({ waitUntil: (promise) => promise });
  assert.deepEqual([...store.keys()].sort(), ["/icon-192.png", "/icon-512.png", "/offline.html"]);
  assert.ok(![...store.keys()].some((key) => key.includes("api")));
  const source = read("sw.js");
  assert.ok(!/cache\.put|\.put\(/.test(source), "çalışma anında önbelleğe yazma olmamalı");
});
