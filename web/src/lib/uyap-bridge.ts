/**
 * JurisAI sayfası ↔ tarayıcı eklentisi köprüsü (eklentideki bridge.js ile aynı protokol).
 *
 * Sayfa `window.postMessage` ile komut gönderir, eklenti aynı pencereye yanıt verir. UYAP şifresi, e-imza ya da oturum
 * çerezi bu yoldan geçmez; yalnız komut ve sonuç (dosya listesi gibi) geçer. Eklentiden gelen metinler UYAP sayfasından
 * okunmuştur: güvenilmez veri sayılır, ekranda yalnız metin olarak gösterilir.
 */

export interface BridgeDosya {
  /** Eklentinin satırı yeniden bulmak için kullandığı anahtar (listeyle birlikte gelir, UYAP sayfası değişince geçersizleşir). */
  key: string;
  esas: string;
  birim: string;
  cells: string[];
}

export interface BridgeFailure {
  ok: false;
  error: string;
  code?: string;
}

export type BridgeReply<T extends object = object> = ({ ok: true } & T) | BridgeFailure;

export interface ExtensionStatus {
  installed: boolean;
  version?: string;
  /** Eklentide JurisAI bağlantı anahtarı girilmiş mi (aktarım için gerekir). */
  connected?: boolean;
}

export interface DosyaListe {
  items: BridgeDosya[];
  pages: number | null;
  page: number | null;
}

const REQUEST_TIMEOUT_MS = 20000;

/** Eklentiye komut gönderir; yanıt gelmezse (eklenti yok ya da eski) `timeout` hatası döner. */
export function bridgeRequest<T extends object = object>(
  type: "PING" | "LIST_DOSYALAR" | "OPEN_DOSYA" | "SET_KEY",
  payload: Record<string, unknown> = {},
  timeoutMs = REQUEST_TIMEOUT_MS,
): Promise<BridgeReply<T>> {
  return new Promise((resolve) => {
    const id = crypto.randomUUID();
    const finish = (reply: BridgeReply<T>) => {
      clearTimeout(timer);
      window.removeEventListener("message", onMessage);
      resolve(reply);
    };
    const timer = setTimeout(
      () => finish({ ok: false, code: "timeout", error: "Eklenti yanıt vermedi." }),
      timeoutMs,
    );
    function onMessage(event: MessageEvent) {
      if (event.source !== window || event.origin !== window.location.origin) return;
      const data = event.data as Record<string, unknown> | null;
      if (!data || data.source !== "jurisai-extension" || data.id !== id) return;
      const { source: _source, id: _id, ...rest } = data;
      finish(rest as unknown as BridgeReply<T>);
    }
    window.addEventListener("message", onMessage);
    window.postMessage({ source: "jurisai-web", id, type, payload }, window.location.origin);
  });
}

export async function detectExtension(timeoutMs = 1500): Promise<ExtensionStatus> {
  const reply = await bridgeRequest<{ version?: unknown; connected?: unknown }>("PING", {}, timeoutMs);
  if (!reply.ok) return { installed: false };
  return {
    installed: true,
    version: typeof reply.version === "string" ? reply.version : undefined,
    connected: reply.connected === true,
  };
}

const text = (value: unknown, max: number) => (typeof value === "string" ? value.replace(/\s+/g, " ").trim().slice(0, max) : "");

/** Eklentiden gelen dosya listesini savunmacı biçimde ayrıştırır: bozuk satırlar atılır, metinler kısaltılır. */
export function parseDosyaListe(raw: unknown): DosyaListe {
  const source = raw && typeof raw === "object" ? (raw as Record<string, unknown>) : {};
  const rows = Array.isArray(source.items) ? source.items : [];
  const items: BridgeDosya[] = [];
  for (const row of rows.slice(0, 2000)) {
    if (!row || typeof row !== "object") continue;
    const entry = row as Record<string, unknown>;
    const key = text(entry.key, 400);
    if (!key) continue;
    const cells = Array.isArray(entry.cells) ? entry.cells.map((cell) => text(cell, 120)).filter(Boolean).slice(0, 8) : [];
    items.push({ key, esas: text(entry.esas, 60), birim: text(entry.birim, 160), cells });
  }
  const count = (value: unknown) => (typeof value === "number" && Number.isInteger(value) && value > 0 ? value : null);
  return { items, pages: count(source.pages), page: count(source.page) };
}

/** Listede gösterilecek ek bilgi: esas no ve birim dışında kalan hücreler. */
export function otherCells(item: BridgeDosya): string[] {
  return item.cells.filter((cell) => cell !== item.esas && cell !== item.birim);
}

export async function listUyapDosyalari(): Promise<
  { ok: true; liste: DosyaListe } | BridgeFailure
> {
  const reply = await bridgeRequest("LIST_DOSYALAR");
  if (!reply.ok) return reply;
  return { ok: true, liste: parseDosyaListe(reply) };
}

/** Sayfanın oluşturduğu bağlantı anahtarını eklentiye yazar (elle yapıştırma gerekmez); eklenti yoksa `ok: false` döner. */
export async function setExtensionKey(key: string): Promise<boolean> {
  const reply = await bridgeRequest("SET_KEY", { key }, 2000);
  if (reply.ok && typeof window !== "undefined") window.dispatchEvent(new Event(EXTENSION_CHANGED_EVENT));
  return reply.ok;
}

/** Eklentinin durumu değişince (ör. anahtar yazıldı) yayımlanır; "UYAP Dosyalarım" bölümü durumu yeniler. */
export const EXTENSION_CHANGED_EVENT = "jurisai-extension-changed";

export function openUyapDosya(key: string) {
  return bridgeRequest("OPEN_DOSYA", { key });
}

export interface ListFailureHelp {
  title: string;
  steps: string[];
  /** Kullanıcı UYAP'ta ilerleyince kendiliğinden düzelebilir: sayfa listeyi aralıklarla yeniden dener. */
  waiting: boolean;
}

/** Dosya listesi okunamadığında kullanıcıya "şimdi ne yapmalı" rehberi (eklentinin hata kodlarına göre). */
export function describeListFailure(code: string | undefined, message: string): ListFailureHelp {
  switch (code) {
    case "no_uyap_tab":
      return {
        title: "UYAP açık değil",
        steps: [
          "UYAP'ı yeni sekmede aç (aşağıdaki düğmeler) ve giriş yap.",
          "Soldaki menüden Dosya Sorgulama'ya gir. Dosya listesi görününce burası kendiliğinden güncellenir.",
        ],
        waiting: true,
      };
    case "login_required":
      return {
        title: "UYAP'ta henüz giriş yapılmamış görünüyor",
        steps: [
          "UYAP sekmesinde e-Devlet (ya da e-imza) ile giriş yap.",
          "Sonra Dosya Sorgulama'yı aç. Dosya listesi görününce burası kendiliğinden güncellenir.",
        ],
        waiting: true,
      };
    case "no_list":
      return {
        title: "UYAP açık ama dosya listesi görünmüyor",
        steps: [
          "UYAP'ta soldaki menüden Dosya Sorgulama'yı aç: dosya satırları ve \"Dosya Görüntüle\" düğmeleri görünmeli.",
          "Liste görününce burası kendiliğinden güncellenir.",
        ],
        waiting: true,
      };
    case "no_content":
      return {
        title: "UYAP sekmesine ulaşılamadı",
        steps: ["UYAP sekmesinde F5 yap (eklenti yeni güncellendiyse sayfaya ancak yenilenince bağlanır)."],
        waiting: true,
      };
    default:
      return { title: message || "Dosya listesi okunamadı", steps: [], waiting: false };
  }
}
