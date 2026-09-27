/* Sayfanın kendi ağ isteklerini (fetch/XHR) dinleyip belge adreslerini toplar.
   Hiçbir giriş bilgisi, çerez veya form içeriği okunmaz; yalnızca adresler ve
   sunucudan dönen liste/JSON yanıtlarındaki belge referansları. */
(function () {
  if (window.__jurisaiSnifferReady) return;
  window.__jurisaiSnifferReady = true;
  const seen = new Set();
  const MAX_BODY = 400000;

  const serialiseBody = (body) => {
    try {
      if (typeof body === "string") return body.slice(0, MAX_BODY);
      if (body instanceof URLSearchParams) return body.toString().slice(0, MAX_BODY);
      if (body instanceof FormData) {
        const params = new URLSearchParams();
        for (const [key, value] of body.entries()) {
          if (typeof value === "string") params.append(key, value);
        }
        return params.toString().slice(0, MAX_BODY);
      }
    } catch (_) {}
    return null;
  };

  const pushRequest = (url, method, body, contentType) => {
    try {
      const abs = new URL(url, location.href).href;
      if (!abs.startsWith("http")) return;
      window.postMessage(
        {
          source: "jurisai-sniffer-request",
          url: abs,
          method: (method || "GET").toUpperCase(),
          body: serialiseBody(body),
          contentType: contentType || "",
        },
        "*",
      );
    } catch (_) {}
  };

  const bytesToBase64 = (bytes) => {
    let binary = "";
    for (let i = 0; i < bytes.length; i += 8192) {
      binary += String.fromCharCode.apply(null, bytes.subarray(i, i + 8192));
    }
    return btoa(binary);
  };

  const pushFile = async (value, url, contentType, disposition) => {
    try {
      const blob = value instanceof Blob ? value : new Blob([value], { type: contentType });
      if (!blob.size || blob.size > 50 * 1024 * 1024) return;
      const bytes = new Uint8Array(await blob.arrayBuffer());
      window.postMessage(
        {
          source: "jurisai-sniffer-file",
          url: new URL(url, location.href).href,
          contentType: contentType || blob.type || "application/octet-stream",
          disposition: disposition || "",
          contentBase64: bytesToBase64(bytes),
        },
        "*",
      );
    } catch (_) {}
  };

  const push = (url) => {
    try {
      const abs = new URL(url, location.href).href;
      if (abs.startsWith("http") && !seen.has(abs)) {
        seen.add(abs);
        window.postMessage({ source: "jurisai-sniffer", url: abs }, "*");
      }
    } catch (_) {
      /* yoksay */
    }
  };

  /** JSON yanıtlarının içine gömülü base64 belge içeriklerini yakalar. */
  const pushEmbeddedBase64 = (text, baseUrl) => {
    try {
      if (!text || typeof text !== "string") return;
      const re =
        /"(?:icerik|içerik|content|data|dosya|dosyaIcerik|belge|belgeIcerik|base64|fileContent|veri)"\s*:\s*"([A-Za-z0-9+/=\s]{2000,})"/gi;
      let m;
      let count = 0;
      while ((m = re.exec(text)) && count < 12) {
        const b64 = m[1].replace(/\s+/g, "");
        if (b64.length < 2000) continue;
        count++;
        const head = b64.slice(0, 8);
        const contentType = head.startsWith("JVBER")
          ? "application/pdf"
          : head.startsWith("UEsDB")
            ? "application/zip"
            : head.startsWith("/9j/")
              ? "image/jpeg"
              : head.startsWith("iVBOR")
                ? "image/png"
                : "application/octet-stream";
        window.postMessage(
          {
            source: "jurisai-sniffer-file",
            url: new URL(baseUrl || location.href, location.href).href,
            contentType,
            disposition: "",
            contentBase64: b64,
          },
          "*",
        );
      }
    } catch (_) {}
  };

  const pushBody = (text, baseUrl) => {
    try {
      if (!text || typeof text !== "string") return;
      pushEmbeddedBase64(text, baseUrl);
      window.postMessage(
        {
          source: "jurisai-sniffer-body",
          text: text.slice(0, MAX_BODY),
          base: baseUrl || location.href,
        },
        "*",
      );
    } catch (_) {}
  };

  // UYAP belgeleri çoğu ekranda blob olarak üretip yeni sekmede gösterir.
  const origCreateObjectURL = URL.createObjectURL;
  if (origCreateObjectURL) {
    URL.createObjectURL = function (obj) {
      try {
        if (obj instanceof Blob && obj.size > 512 && !/text\/html/i.test(obj.type || "")) {
          pushFile(obj, location.href, obj.type || "application/octet-stream", "attachment");
        }
      } catch (_) {}
      return origCreateObjectURL.apply(this, arguments);
    };
  }

  const origFetch = window.fetch;
  if (origFetch) {
    window.fetch = function (input, init) {
      const url = typeof input === "string" ? input : input?.url;
      const method = init?.method || (typeof input !== "string" ? input?.method : "GET") || "GET";
      const body = init?.body;
      let contentType = "";
      try {
        contentType =
          new Headers(
            init?.headers || (typeof input !== "string" ? input?.headers : undefined),
          ).get("content-type") || "";
      } catch (_) {}
      try {
        push(url);
        pushRequest(url, method, body, contentType);
      } catch (_) {}
      const p = origFetch.apply(this, arguments);
      try {
        p.then((res) => {
          try {
            const ct = res.headers.get("content-type") || "";
            const cd = res.headers.get("content-disposition") || "";
            if (/json|text\/plain|xml|text\/html/i.test(ct)) {
              res
                .clone()
                .text()
                .then((t) => pushBody(t, url))
                .catch(() => {});
            } else if (
              /attachment/i.test(cd) ||
              /pdf|zip|image|word|excel|octet-stream|udf/i.test(ct)
            ) {
              res
                .clone()
                .blob()
                .then((b) => pushFile(b, res.url || url, ct, cd))
                .catch(() => {});
            }
          } catch (_) {}
          return res;
        }).catch(() => {});
      } catch (_) {}
      return p;
    };
  }

  const origOpen = XMLHttpRequest.prototype.open;
  XMLHttpRequest.prototype.open = function (method, url) {
    this.__jurisaiUrl = url;
    this.__jurisaiMethod = method;
    try {
      push(url);
    } catch (_) {}
    return origOpen.apply(this, arguments);
  };

  const origSend = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.send = function (body) {
    pushRequest(
      this.__jurisaiUrl,
      this.__jurisaiMethod,
      body,
      "application/x-www-form-urlencoded; charset=UTF-8",
    );
    this.addEventListener("load", () => {
      try {
        const rt = this.responseType;
        const ct = this.getResponseHeader("content-type") || "";
        const cd = this.getResponseHeader("content-disposition") || "";
        if (rt === "" || rt === "text") {
          if (/json|text|xml|html/i.test(ct)) pushBody(this.responseText, this.__jurisaiUrl);
          else
            pushFile(
              new TextEncoder().encode(this.responseText),
              this.responseURL || this.__jurisaiUrl,
              ct,
              cd,
            );
        } else if (rt === "blob" || rt === "arraybuffer") {
          pushFile(this.response, this.responseURL || this.__jurisaiUrl, ct, cd);
        } else if (rt === "json") {
          pushBody(JSON.stringify(this.response), this.__jurisaiUrl);
        }
      } catch (_) {}
    });
    return origSend.apply(this, arguments);
  };

  const origAssign = window.open;
  window.open = function (url) {
    try {
      if (url) push(url);
    } catch (_) {}
    return origAssign.apply(this, arguments);
  };
})();
