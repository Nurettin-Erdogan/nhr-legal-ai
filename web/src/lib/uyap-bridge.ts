/**
 * JurisAI sayfası ↔ tarayıcı eklentisi köprüsü (eklentideki bridge.js ile aynı protokol).
 *
 * Sayfa `window.postMessage` ile komut gönderir, eklenti aynı pencereye yanıt verir. UYAP şifresi, e-imza ya da oturum
 * çerezi bu yoldan geçmez; yalnız komut ve sonuç (dosya listesi gibi) geçer. Eklentiden gelen metinler UYAP sayfasından
 * okunmuştur: güvenilmez veri sayılır, ekranda yalnız metin olarak gösterilir.
 */

import { steadySleep } from "@/lib/steady-timer";

export interface BridgeDosya {
  /** Eklentinin satırı yeniden bulmak için kullandığı anahtar (listeyle birlikte gelir, UYAP sayfası değişince geçersizleşir). */
  key: string;
  esas: string;
  birim: string;
  /** Dosyanın bulunduğu yargı türü ("Ceza", "Hukuk", "İcra"…): dosyayı açmak için o türün sorgusu gerekir. */
  yargiTuru: string;
  /** Taraf rolü, dosya türü, açılış tarihi ve durum (UYAP tablosundaki sütunlar). */
  role: string;
  tur: string;
  acilis: string;
  durum: string;
  cells: string[];
}

export interface BridgeFailure {
  ok: false;
  error: string;
  code?: string;
}

export type BridgeReply<T extends object = object> = ({ ok: true } & T) | BridgeFailure;

export interface ExtensionStatus {
  /** true yalnız bu sayfanın köprü yanıtını aldığını gösterir; false kurulumun yokluğunu kanıtlamaz. */
  installed: boolean;
  version?: string;
  /** Eklentide JurisAI bağlantı anahtarı girilmiş mi (aktarım için gerekir). */
  connected?: boolean;
  error?: string;
  code?: string;
}

/**
 * UYAP'ta giriş yapan kişi: eklentinin tarayıcıda ürettiği parmak izi (kimlik numarası değil) ve UYAP'taki ad soyad.
 * Evraklar bu kişiyle işaretlenir; Belgeler'de dosyalar kimin UYAP'ından geldiyse onun altında durur (api/uyap_account.py).
 */
export interface UyapIdentity {
  fingerprint: string;
  kind: "tc" | "name";
  portal: "vatandas" | "avukat" | "diger";
  display: string;
}

export function parseIdentity(raw: unknown): UyapIdentity | null {
  if (!raw || typeof raw !== "object") return null;
  const source = raw as Record<string, unknown>;
  const fingerprint = typeof source.fingerprint === "string" ? source.fingerprint : "";
  const display = typeof source.display === "string" ? source.display : "";
  if (!/^[0-9a-f]{64}$/.test(fingerprint) || (source.kind !== "tc" && source.kind !== "name"))
    return null;
  if (
    !/^[A-Za-zÇĞİÖŞÜÂÎÛçğıöşüâîû][A-Za-zÇĞİÖŞÜÂÎÛçğıöşüâîû .'*-]{0,118}[A-Za-zÇĞİÖŞÜÂÎÛçğıöşüâîû.*]$/.test(
      display,
    )
  )
    return null;
  const portal =
    source.portal === "vatandas" || source.portal === "avukat" ? source.portal : "diger";
  return { fingerprint, kind: source.kind, portal, display };
}

export const sameIdentity = (
  a: UyapIdentity | null | undefined,
  b: UyapIdentity | null | undefined,
): boolean => !!a && !!b && a.kind === b.kind && a.fingerprint === b.fingerprint;

export interface DosyaListe {
  items: BridgeDosya[];
  /** Listeyi okuyan UYAP kişisi (okunamadıysa null: aktarım başlatılmaz). Sunucuya yalnız denetim için gider. */
  identity?: UyapIdentity | null;
  /** Listenin okunduğu UYAP sekmesi: koşu başka bir açık hesap/sekme seçmez. Sunucuya kaydedilmez. */
  tabId?: number;
  /** Her yargı türünde bulunan dosya sayısı (sorgulanan türlerin tamamı, boş olanlar dahil). */
  types: { label: string; count: number }[];
  errors: string[];
  /** Yalnız eklenti tüm tür/sayfaları tamamladığını bildirince true. */
  complete: boolean;
  pages: number | null;
  page: number | null;
}

const REQUEST_TIMEOUT_MS = 20000;

export type BridgeCommand =
  | "PING"
  | "LIST_DOSYALAR"
  | "OPEN_DOSYA"
  | "SET_KEY"
  | "TREE"
  | "DETAIL"
  | "RECOVER_READ"
  | "JOB_STATUS"
  | "CURRENT_JOB"
  | "PULL_IDS"
  | "STOP_JOB"
  | "DIAGNOSE";

/** Eklentiye komut gönderir; yanıt gelmezse (eklenti yok ya da eski) `timeout` hatası döner. */
export function bridgeRequest<T extends object = object>(
  type: BridgeCommand,
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

// İlk mesaj servis çalışanını uyandırabilir; kısa süre sınırı çalışan eklentiyi yanlışlıkla reddeder.
export async function detectExtension(timeoutMs = 5000): Promise<ExtensionStatus> {
  const reply = await bridgeRequest<{ version?: unknown; connected?: unknown }>(
    "PING",
    {},
    timeoutMs,
  );
  if (!reply.ok)
    return {
      installed: false,
      error:
        typeof reply.error === "string" ? reply.error.slice(0, 500) : "Eklenti yanıtı alınamadı.",
      ...(typeof reply.code === "string" ? { code: reply.code.slice(0, 80) } : {}),
    };
  return {
    installed: true,
    version: typeof reply.version === "string" ? reply.version : undefined,
    connected: reply.connected === true,
  };
}

const text = (value: unknown, max: number) =>
  typeof value === "string" ? value.replace(/\s+/g, " ").trim().slice(0, max) : "";

/** Eklentiden gelen dosya listesini savunmacı biçimde ayrıştırır: bozuk satırlar atılır, metinler kısaltılır. */
export function parseDosyaListe(raw: unknown): DosyaListe {
  const source = raw && typeof raw === "object" ? (raw as Record<string, unknown>) : {};
  const rows = Array.isArray(source.items) ? source.items : [];
  const items: BridgeDosya[] = [];
  const keys = new Set<string>();
  let invalid = 0;
  for (const row of rows) {
    if (!row || typeof row !== "object") {
      invalid += 1;
      continue;
    }
    const entry = row as Record<string, unknown>;
    const key = text(entry.key, 600);
    if (!key) {
      invalid += 1;
      continue;
    }
    if (keys.has(key)) continue;
    keys.add(key);
    const cells = Array.isArray(entry.cells)
      ? entry.cells
          .map((cell) => text(cell, 120))
          .filter(Boolean)
          .slice(0, 8)
      : [];
    items.push({
      key,
      esas: text(entry.esas, 60),
      birim: text(entry.birim, 160),
      yargiTuru: text(entry.yargiTuru, 80),
      role: text(entry.role, 60),
      tur: text(entry.tur, 80),
      acilis: text(entry.acilis, 40),
      durum: text(entry.durum, 80),
      cells,
    });
  }
  const types = (Array.isArray(source.types) ? source.types : [])
    .map((entry) => (entry && typeof entry === "object" ? (entry as Record<string, unknown>) : {}))
    .map((entry) => ({
      label: text(entry.label, 80),
      count: typeof entry.count === "number" && entry.count >= 0 ? Math.floor(entry.count) : 0,
    }))
    .filter((entry) => entry.label)
    .slice(0, 40);
  const count = (value: unknown) =>
    typeof value === "number" && Number.isInteger(value) && value > 0 ? value : null;
  const errors = Array.isArray(source.errors)
    ? source.errors.map((value) => text(value, 400)).filter(Boolean)
    : [];
  if (invalid) errors.push(`${invalid} dosya satırı okunamadı; liste eksik olabilir.`);
  return {
    items,
    ...(typeof source.tabId === "number" && Number.isSafeInteger(source.tabId) && source.tabId >= 0
      ? { tabId: source.tabId }
      : {}),
    types,
    errors,
    complete: source.complete === true && errors.length === 0,
    pages: count(source.pages),
    page: count(source.page),
    identity: parseIdentity(source.identity),
  };
}

/** Listede gösterilecek ek bilgi: esas no ve birim dışında kalan hücreler. */
export function otherCells(item: BridgeDosya): string[] {
  return item.cells.filter((cell) => cell !== item.esas && cell !== item.birim);
}

let listRequest: Promise<{ ok: true; liste: DosyaListe } | BridgeFailure> | null = null;
export function listUyapDosyalari(): Promise<{ ok: true; liste: DosyaListe } | BridgeFailure> {
  // Aynı sekmedeki otomatik yoklama ve elle yenileme UYAP formunu birlikte değiştirmesin.
  if (listRequest) return listRequest;
  listRequest = readUyapDosyalari().finally(() => {
    listRequest = null;
  });
  return listRequest;
}
async function readUyapDosyalari(): Promise<{ ok: true; liste: DosyaListe } | BridgeFailure> {
  // Eklenti her yargı türünü sırayla sorgular (türü başına ~1-2 sn): uzun zaman aşımı.
  const reply = await bridgeRequest("LIST_DOSYALAR", {}, 120000);
  if (!reply.ok) return reply;
  return { ok: true, liste: parseDosyaListe(reply) };
}

/** Sayfanın oluşturduğu bağlantı anahtarını eklentiye yazar (elle yapıştırma gerekmez); eklenti yoksa `ok: false` döner. */
export async function setExtensionKey(key: string): Promise<boolean> {
  const reply = await bridgeRequest("SET_KEY", { key }, 100000);
  if (reply.ok && typeof window !== "undefined")
    window.dispatchEvent(new Event(EXTENSION_CHANGED_EVENT));
  return reply.ok;
}

/** Eklentinin durumu değişince (ör. anahtar yazıldı) yayımlanır; "UYAP Dosyalarım" bölümü durumu yeniler. */
export const EXTENSION_CHANGED_EVENT = "jurisai-extension-changed";

export function openUyapDosya(key: string, yargiTuru = "") {
  return bridgeRequest("OPEN_DOSYA", { key, yargiTuru });
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
    case "navigating":
      return {
        title: "UYAP'ta Dosya Sorgulama sayfası açılıyor",
        steps: [
          "Eklenti UYAP'ın Sorgulama İşlemleri menüsünden Dosya Sorgulama'yı açıyor; liste birkaç saniye içinde burada görünür.",
        ],
        waiting: true,
      };
    case "query_failed":
      return {
        title: "UYAP dosya sorgusu yanıt vermedi",
        steps: [
          "UYAP yoğun olabilir ya da oturum kapanmış olabilir: UYAP sekmesine bak, gerekirse yeniden giriş yap, sonra listeyi yenile.",
        ],
        waiting: false,
      };
    case "no_content":
      return {
        title: "UYAP sekmesine ulaşılamadı",
        steps: [
          "UYAP sekmesinde F5 yap (eklenti yeni güncellendiyse sayfaya ancak yenilenince bağlanır).",
        ],
        waiting: true,
      };
    case "busy":
      return {
        title: "UYAP sekmesinde bir işlem sürüyor",
        steps: [
          "Daha önce başlattığın aktarım ya da listeleme UYAP sekmesinde devam ediyor (bu sayfa yenilense de durmaz). Bitince liste burada kendiliğinden görünür.",
        ],
        waiting: true,
      };
    default:
      return { title: message || "Dosya listesi okunamadı", steps: [], waiting: false };
  }
}

/* ---------- Evrak ağacı ve aktarım (iş tabanlı) ----------
   Ağaç açma ve evrak çekme dakikalar sürebilir: sayfa işi başlatır, eklenti UYAP sekmesinde yürütür, sayfa durumu yoklar. */

export interface TreeItem {
  id: string;
  title: string;
  /** Klasör yolu (en üst klasörden en yakına). */
  folders: string[];
  typeName: string;
  isEk: boolean;
  /** UYAP'ın klasör adının yanına yazdığı sayı; ek ve sayısız klasörde null. */
  declared: number | null;
}

export interface TreeCounts {
  declaredTotal: number;
  foundTotal: number;
  eks: number;
  matches: boolean;
  /** Fark yalnız aynı evrakın birden çok klasörde görünmesinden: eksik yok. */
  explained: boolean;
  gapList: string[];
  withoutId: number;
  /** Kalıcı kimliği çıkarılamayan (her oturumda değişen şifreli kimliğe düşen) evrak sayısı: bunlar için eksiksizlik doğrulanamaz. */
  unstableId: number;
  unopened: number;
  emptyOpened: number;
}

export interface TreeResult {
  who: { esas: string; birim: string };
  items: TreeItem[];
  counts: TreeCounts;
  /** JurisAI hesabında zaten olan evrak kimlikleri. */
  known: string[];
  knownChecked: boolean;
  /** Ağacı okuyan UYAP kişisi; koşunun başındaki kişiden farklıysa koşu durur. */
  identity?: UyapIdentity | null;
  /** Sunucu bu UYAP kişisini hesaba bağlı saymadıysa nedeni (boşsa sorun yok). */
  accountRefused?: string;
}

export interface PullStats {
  sent: number;
  duplicates: number;
  sameContent: number;
  failed: number;
  known: number;
  errors: string[];
  /** UYAP'ın "sisteme yüklenmemiş" dediği evraklar (içerik UYAP'ta yok; eksik sayılmaz). */
  absent: string[];
}

/* ---------- Dosya detayı (evrak dışı bilgiler) ----------
   Eklenti dosya penceresinin dosya bilgileri / dosya hesabı / taraflar / safahat / tahsilat-reddiyat sekmelerini salt okunur okur.
   Değerler UYAP'ın yazdığı metindir; yorumlanmaz. Metinler UYAP sayfasından gelir: güvenilmez, boyut sınırlı ayrıştırılır. */

export interface DetailPair {
  label: string;
  value: string;
}

export interface DetailTable {
  title: string;
  headers: string[];
  rows: string[][];
  /** UYAP'ın "N Kayıttan" yazısındaki toplam; yazı yoksa null. */
  declared: number | null;
  /** Okunan satır sayısı UYAP'ın söylediği sayıyla uyuşuyor (ya da UYAP sayı söylemiyor). */
  complete: boolean;
}

export interface DetailTab {
  key: string;
  label: string;
  pairs: DetailPair[];
  tables: DetailTable[];
  complete: boolean;
}

export interface DosyaDetail {
  who: { esas: string; birim: string };
  tabs: DetailTab[];
  problems: string[];
  complete: boolean;
}

export interface JobInfo {
  id: string;
  kind: "tree" | "pull" | "detail";
  state: "running" | "done" | "error";
  phase: string;
  error?: string;
  code?: string;
  count?: number;
}

export interface RunInfo {
  mode: "upload" | "disk";
  chosen: number;
  total: number;
  done: number;
  current: string;
  phase?: string;
  stats?: PullStats;
  result?: { summary?: string; stopped?: boolean };
}

/** İşin sona ermesi, seçilen tüm belgelerin başarıyla aktarılması anlamına gelmez. */
export function pullOutcome(run: RunInfo): "complete" | "partial" | "stopped" {
  if (run.result?.stopped) return "stopped";
  if (!run.stats || run.stats.failed > 0 || run.done < run.total) return "partial";
  const accounted = run.stats.sent + run.stats.known + run.stats.duplicates + run.stats.sameContent;
  return accounted >= run.total ? "complete" : "partial";
}

export interface JobStatus {
  job: JobInfo;
  run?: RunInfo;
  tree?: TreeResult;
  detail?: DosyaDetail;
}

const num = (value: unknown, fallback = 0) =>
  typeof value === "number" && Number.isFinite(value) ? value : fallback;
const strings = (value: unknown, max: number, limit: number): string[] =>
  Array.isArray(value)
    ? value
        .map((entry) => text(entry, max))
        .filter(Boolean)
        .slice(0, limit)
    : [];

/** Eklentiden gelen ağaç yanıtını savunmacı biçimde ayrıştırır (metinler UYAP sayfasından okunmuştur: güvenilmez). */
/** Bir dosyanın ağacından alınan en çok evrak (ekler dahil). Canlıda 20 000'i aşan ceza dosyaları görüldü (2026-10-17). */
export const MAX_TREE_ITEMS = 200000;

export function parseTree(raw: unknown): TreeResult | null {
  if (!raw || typeof raw !== "object") return null;
  const source = raw as Record<string, unknown>;
  const rows = Array.isArray(source.items) ? source.items : [];
  const items: TreeItem[] = [];
  const seen = new Set<string>();
  for (const row of rows.slice(0, MAX_TREE_ITEMS)) {
    if (!row || typeof row !== "object") continue;
    const entry = row as Record<string, unknown>;
    const id = typeof entry.id === "string" ? entry.id.slice(0, 600) : "";
    if (!id || seen.has(id)) continue;
    seen.add(id);
    items.push({
      id,
      title: text(entry.title, 200) || "Evrak",
      folders: strings(entry.folders, 160, 12),
      typeName: text(entry.typeName, 120),
      isEk: entry.isEk === true,
      declared: typeof entry.declared === "number" && entry.declared > 0 ? entry.declared : null,
    });
  }
  const c = (source.counts && typeof source.counts === "object" ? source.counts : {}) as Record<
    string,
    unknown
  >;
  const truncated = rows.length > MAX_TREE_ITEMS;
  const who = (source.who && typeof source.who === "object" ? source.who : {}) as Record<
    string,
    unknown
  >;
  return {
    who: { esas: text(who.esas, 60), birim: text(who.birim, 160) },
    items,
    counts: {
      declaredTotal: num(c.declaredTotal),
      foundTotal: num(c.foundTotal),
      eks: num(c.eks),
      matches: !truncated && c.matches === true,
      explained: !truncated && c.explained === true,
      gapList: [
        ...(truncated
          ? [
              `Güvenlik sınırı: ${MAX_TREE_ITEMS.toLocaleString("tr-TR")} evraktan sonrası alınamadı.`,
            ]
          : []),
        ...strings(c.gapList, 200, 12),
      ],
      withoutId: num(c.withoutId),
      unstableId: num(c.unstableId),
      unopened: num(c.unopened),
      emptyOpened: num(c.emptyOpened),
    },
    known: strings(source.known, 600, MAX_TREE_ITEMS),
    knownChecked: source.knownChecked === true,
    identity: parseIdentity(source.identity),
    accountRefused: text(source.accountRefused, 600),
  };
}

export interface TreeGroup {
  label: string;
  items: TreeItem[];
  declared: number | null;
}

/** Evrakları klasör yoluna göre gruplar (seçim penceresindeki düzen); gruplar ilk görülme sırasındadır. */
export function groupTreeItems(items: TreeItem[]): TreeGroup[] {
  const groups = new Map<string, TreeGroup>();
  for (const item of items) {
    const label = item.folders.join(" / ") || "(klasörsüz)";
    const group = groups.get(label) ?? { label, items: [], declared: item.declared };
    group.items.push(item);
    groups.set(label, group);
  }
  return [...groups.values()];
}

/** Aktarılacak varsayılan seçim: JurisAI'da zaten olanlar hariç hepsi (`onlyMain`: ekler de hariç). */
export function defaultSelection(
  items: TreeItem[],
  known: string[],
  onlyMain = false,
): Set<string> {
  const have = new Set(known);
  return new Set(
    items.filter((item) => !have.has(item.id) && !(onlyMain && item.isEk)).map((item) => item.id),
  );
}

const cell = (value: unknown) => (typeof value === "string" ? value.slice(0, 4000) : "");

/** Eklentiden gelen dosya detayını savunmacı ayrıştırır. Satır/hücre sayısına sınır yoktur; yalnız metin uzunlukları sınırlıdır. */
export function parseDetail(raw: unknown): DosyaDetail | null {
  if (!raw || typeof raw !== "object") return null;
  const source = raw as Record<string, unknown>;
  const who = (source.who && typeof source.who === "object" ? source.who : {}) as Record<
    string,
    unknown
  >;
  const tabs: DetailTab[] = [];
  for (const entry of (Array.isArray(source.tabs) ? source.tabs : []).slice(0, 24)) {
    if (!entry || typeof entry !== "object") continue;
    const tab = entry as Record<string, unknown>;
    const key = text(tab.key, 40);
    if (!key) continue;
    const pairs: DetailPair[] = [];
    for (const pair of (Array.isArray(tab.pairs) ? tab.pairs : []).slice(0, 500)) {
      if (!pair || typeof pair !== "object") continue;
      const row = pair as Record<string, unknown>;
      const label = text(row.label, 160);
      if (label) pairs.push({ label, value: cell(row.value) });
    }
    const tables: DetailTable[] = [];
    for (const item of (Array.isArray(tab.tables) ? tab.tables : []).slice(0, 24)) {
      if (!item || typeof item !== "object") continue;
      const table = item as Record<string, unknown>;
      const headers = (Array.isArray(table.headers) ? table.headers : [])
        .slice(0, 60)
        .map((header) => text(header, 160));
      const rows = (Array.isArray(table.rows) ? table.rows : []).map((row) =>
        (Array.isArray(row) ? row : []).slice(0, 60).map(cell),
      );
      tables.push({
        title: text(table.title, 120),
        headers,
        rows,
        declared: typeof table.declared === "number" && table.declared >= 0 ? table.declared : null,
        complete:
          table.complete === true &&
          (rows.length > 0 || table.declared === 0) &&
          (typeof table.declared !== "number" ||
            (Number.isFinite(table.declared) && rows.length === table.declared)),
      });
    }
    tabs.push({
      key,
      label: text(tab.label, 80),
      pairs,
      tables,
      complete:
        tab.complete === true &&
        (pairs.length > 0 || tables.length > 0) &&
        tables.every((table) => table.complete),
    });
  }
  return {
    who: { esas: text(who.esas, 60), birim: text(who.birim, 160) },
    tabs,
    problems: strings(source.problems, 300, 12),
    complete: source.complete === true && tabs.length > 0 && tabs.every((tab) => tab.complete),
  };
}

export function parseJobStatus(raw: unknown): JobStatus | null {
  if (!raw || typeof raw !== "object") return null;
  const source = raw as Record<string, unknown>;
  const job =
    source.job && typeof source.job === "object" ? (source.job as Record<string, unknown>) : null;
  if (!job || typeof job.id !== "string") return null;
  const state = job.state === "done" || job.state === "error" ? job.state : "running";
  const status: JobStatus = {
    job: {
      id: job.id.slice(0, 64),
      kind: job.kind === "pull" ? "pull" : job.kind === "detail" ? "detail" : "tree",
      state,
      phase: text(job.phase, 120),
      error: typeof job.error === "string" ? text(job.error, 400) : undefined,
      code: typeof job.code === "string" ? text(job.code, 40) : undefined,
      count: typeof job.count === "number" ? job.count : undefined,
    },
  };
  if (source.run && typeof source.run === "object") {
    const run = source.run as Record<string, unknown>;
    const stats =
      run.stats && typeof run.stats === "object" ? (run.stats as Record<string, unknown>) : null;
    const result =
      run.result && typeof run.result === "object" ? (run.result as Record<string, unknown>) : null;
    status.run = {
      mode: run.mode === "disk" ? "disk" : "upload",
      chosen: num(run.chosen),
      total: num(run.total),
      done: num(run.done),
      current: text(run.current, 200),
      phase: typeof run.phase === "string" ? text(run.phase, 120) : undefined,
      stats: stats
        ? {
            sent: num(stats.sent),
            duplicates: num(stats.duplicates),
            sameContent: num(stats.sameContent),
            failed: num(stats.failed),
            known: num(stats.known),
            errors: strings(stats.errors, 400, 5),
            absent: strings(stats.absent, 600, MAX_TREE_ITEMS),
          }
        : undefined,
      result: result
        ? {
            summary: typeof result.summary === "string" ? text(result.summary, 800) : undefined,
            stopped: result.stopped === true,
          }
        : undefined,
    };
  }
  if (source.tree) {
    const tree = parseTree(source.tree);
    if (tree) status.tree = tree;
  }
  if (source.detail) {
    const detail = parseDetail(source.detail);
    if (detail) status.detail = detail;
  }
  return status;
}

const treeStarts = new Map<string, Promise<BridgeReply<{ jobId: string; tabId: number }>>>();

export function startTreeJob(
  key: string,
  yargiTuru = "",
  tabId?: number,
): Promise<BridgeReply<{ jobId: string; tabId: number }>> {
  // React StrictMode geliştirmede effect'i yeniden kurar. Aynı anda iki TREE
  // yollamak ilk işi yetim bırakıp ikinci çağrıya busy döndürür; aynı dosyanın
  // devam eden başlatma yanıtını paylaş, sonraki açık yeniden taramayı engelleme.
  const identity = JSON.stringify([key, yargiTuru, tabId]);
  const existing = treeStarts.get(identity);
  if (existing) return existing;
  const pending = requestTreeJob(key, yargiTuru, tabId).finally(() => treeStarts.delete(identity));
  treeStarts.set(identity, pending);
  return pending;
}

async function requestTreeJob(
  key: string,
  yargiTuru: string,
  tabId?: number,
): Promise<BridgeReply<{ jobId: string; tabId: number }>> {
  const reply = await bridgeRequest<{ jobId?: unknown; tabId?: unknown }>(
    "TREE",
    { key, yargiTuru, ...(tabId === undefined ? {} : { tabId }) },
    30000,
  );
  if (!reply.ok) return reply;
  if (typeof reply.jobId !== "string" || typeof reply.tabId !== "number")
    return {
      ok: false,
      error:
        "Eklenti beklenmeyen bir yanıt verdi: eklentiyi yenile (sürüm 2.23 veya üstü gerekir).",
    };
  return { ok: true, jobId: reply.jobId, tabId: reply.tabId };
}

/** Dosya penceresinin evrak dışı bilgilerini okuyan işi başlatır (salt okunur); ilerleme `waitForJob(..., { withDetail: true })` ile izlenir. */
export async function startDetailJob(
  key: string,
  yargiTuru = "",
  tabId?: number,
): Promise<BridgeReply<{ jobId: string; tabId: number }>> {
  const reply = await bridgeRequest<{ jobId?: unknown; tabId?: unknown }>(
    "DETAIL",
    { key, yargiTuru, ...(tabId === undefined ? {} : { tabId }) },
    30000,
  );
  if (!reply.ok) return reply;
  if (typeof reply.jobId !== "string" || typeof reply.tabId !== "number")
    return {
      ok: false,
      error:
        "Eklenti beklenmeyen bir yanıt verdi: eklentiyi yenile (sürüm 2.26.14 veya üstü gerekir).",
    };
  return { ok: true, jobId: reply.jobId, tabId: reply.tabId };
}

/** Only the extension can authorize reloading the exact failed read-only job's tab. */
export async function recoverReadJob(
  tabId: number,
  jobId: string,
): Promise<BridgeReply<{ tabId: number }>> {
  const reply = await bridgeRequest<{ tabId?: unknown }>("RECOVER_READ", { tabId, jobId }, 55000);
  if (!reply.ok) return reply;
  return reply.tabId === tabId
    ? { ok: true, tabId }
    : { ok: false, code: "recovery_refused", error: "Toparlanan UYAP sekmesi doğrulanamadı." };
}

export async function fetchJobStatus(
  tabId: number,
  jobId: string,
  withTree = false,
  withDetail = false,
): Promise<BridgeReply<{ status: JobStatus }>> {
  const reply = await bridgeRequest("JOB_STATUS", { tabId, jobId, withTree, withDetail }, 15000);
  if (!reply.ok) return reply;
  const status = parseJobStatus(reply);
  return status
    ? { ok: true, status }
    : { ok: false, error: "Eklentiden geçersiz iş durumu geldi." };
}

export async function startPullJob(
  tabId: number,
  ids: string[],
  mode: "upload" | "disk" = "upload",
): Promise<BridgeReply<{ jobId: string; total: number; tabId: number }>> {
  if (ids.length > 5000)
    return {
      ok: false,
      code: "too_many",
      error:
        "Bir aktarımda en fazla 5.000 evrak seç. Kalanları sonraki aktarımda seçebilirsin; hiçbir seçim sessizce atılmaz.",
    };
  const reply = await bridgeRequest<{ jobId?: unknown; total?: unknown }>(
    "PULL_IDS",
    { tabId, ids, mode },
    30000,
  );
  if (!reply.ok) return reply;
  if (typeof reply.jobId !== "string")
    return { ok: false, error: "Eklenti beklenmeyen bir yanıt verdi." };
  return { ok: true, jobId: reply.jobId, total: num(reply.total, ids.length), tabId };
}

export interface CurrentJob {
  /** UYAP sekmesi o an bir listeleme ya da aktarım yürütüyor. */
  busy: boolean;
  tabId: number | null;
  status: JobStatus | null;
}

/**
 * UYAP sekmesinde o an süren işi sorar. JurisAI sayfası yenilendiğinde ya da yeniden açıldığında süren aktarım UYAP sekmesinde devam
 * eder; sayfa bununla ona yeniden bağlanır (ilerlemeyi gösterir, durdurabilir). Eski eklenti bu komutu tanımaz: null döner.
 */
export async function currentJob(): Promise<CurrentJob | null> {
  const reply = await bridgeRequest<{ busy?: unknown; tabId?: unknown }>("CURRENT_JOB", {}, 8000);
  if (!reply.ok) return null;
  return {
    busy: reply.busy === true,
    tabId: typeof reply.tabId === "number" ? reply.tabId : null,
    status: parseJobStatus(reply),
  };
}

export const stopJob = (tabId: number, jobId: string) =>
  bridgeRequest("STOP_JOB", { tabId, jobId }, 10000);

export interface WaitOptions {
  withTree?: boolean;
  withDetail?: boolean;
  intervalMs?: number;
  /** Üst üste bu kadar yoklama başarısız olursa vazgeçilir (UYAP sekmesi kapandı ya da eklenti yok). */
  maxFailures?: number;
  maxMs?: number;
  signal?: AbortSignal;
  onUpdate?: (status: JobStatus) => void;
}

/** İş bitene (done/error) kadar yoklar; her güncellemede `onUpdate` çağrılır. Bitince son durumu ya da hatayı döndürür. */
export async function waitForJob(
  tabId: number,
  jobId: string,
  options: WaitOptions = {},
): Promise<{ ok: true; status: JobStatus } | BridgeFailure> {
  const {
    withTree = false,
    withDetail = false,
    intervalMs = 700,
    maxFailures = 6,
    maxMs = 6 * 60 * 60 * 1000,
    signal,
    onUpdate,
  } = options;
  const deadline = Date.now() + maxMs;
  let failures = 0;
  let last: BridgeFailure = { ok: false, error: "İş durumu okunamadı." };
  while (Date.now() < deadline) {
    if (signal?.aborted) return { ok: false, code: "aborted", error: "İptal edildi." };
    const reply = await fetchJobStatus(tabId, jobId, withTree, withDetail);
    if (reply.ok) {
      failures = 0;
      onUpdate?.(reply.status);
      if (reply.status.job.state !== "running") return { ok: true, status: reply.status };
    } else {
      last = reply;
      failures += 1;
      if (reply.code === "unknown_job")
        return {
          ok: false,
          code: "unknown_job",
          error:
            "UYAP sayfası yenilenmiş ya da oturumun kapanmış olabilir (UYAP boşta kalan oturumu kapatır). UYAP sekmesine bak; gerekirse yeniden giriş yapıp işlemi yeniden başlat.",
        };
      if (failures >= maxFailures || reply.code === "no_uyap_tab") return reply;
    }
    // Sekme arka plandayken de zamanında yokla (bkz. steady-timer): aktarım saatler sürebilir.
    await steadySleep(intervalMs);
  }
  return { ...last, code: "timeout", error: "İş çok uzun sürdü." };
}
