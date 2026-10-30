/**
 * İcra dosyası dökümü: `/api/office/execution/files/{case_id}` yanıtının okunması ve gösterimi.
 *
 * Makbuz tutarları metinden okunur (toplanmaz, seçilmez). Haciz ihbarnamesi cevaplarında sonuç SÖYLENMEZ: banka yazısında
 * ne geçtiği (tutar, "bloke", "bulunmamaktadır" türü ifade) gösterilir, cümle aynen alıntılanır ve liste buna göre sıralanır.
 */
import { inMemoryAccessToken } from "@/lib/auth-api";

export interface FileRef {
  id: string;
  fileName: string;
  /** Belgeyi indirmek için depolama anahtarı; yoksa boş. */
  storagePath: string;
}

export interface ReceiptItem {
  document: FileRef;
  kind: string;
  label: string;
  date: string | null;
  /** Belgenin metni okunabildi mi (taranmış ya da henüz işlenmemiş belgede hayır). */
  readable: boolean;
  /** Metinde tek tutar varsa o tutar ("100,00 TL"); birden çok farklı tutar varsa null. */
  amount: string | null;
  /** Metinde geçen farklı tutarlar, yazıldığı gibi. */
  amounts: string[];
}

export const REPLY_GROUPS = ["amount", "block", "unclear", "negative"] as const;
export type ReplyGroup = (typeof REPLY_GROUPS)[number];

export interface ReplyItem {
  date: string | null;
  readable: boolean;
  /** Aynı yazının kopyaları (KEP paketi + PDF) tek satırda; hepsi açılabilir. */
  documents: FileRef[];
  group: ReplyGroup;
  sender: string | null;
  amounts: string[];
  quotes: string[];
}

export interface ExecutionBreakdown {
  caseId: string;
  fileNo: string | null;
  court: string;
  receipts: ReceiptItem[];
  replies: {
    /** "… Haciz İhbarnamesi Cevabı" evrak sayısı (KEP zarfı). */
    envelopes: number;
    /** O evrakların ek sayısı (banka yazıları). */
    attachments: number;
    unread: number;
    items: ReplyItem[];
    groups: Partial<Record<ReplyGroup, number>>;
  };
  replyGroupLabels: Record<ReplyGroup, string>;
  /** UYAP'tan çekilen dosya bilgisinden künye, taraflar, önemli işlemler ve sorgular; UYAP bilgisi çekilmediyse null. */
  overview: ExecutionOverview | null;
}

export interface Pair {
  label: string;
  value: string;
}

export interface OverviewParty {
  role: string;
  type: string;
  name: string;
  lawyer: string;
}

/** Safahat kaydındaki "Sorgu Sonucu" ifadesi; aynı gün iki farklı sonuç yazıyorsa "VAR/YOK"; hiç yazmıyorsa null. */
export type QueryResult = "VAR" | "YOK" | "VAR/YOK" | null;

export interface OverviewQuery {
  key: string;
  label: string;
  count: number;
  lastDate: string | null;
  result: QueryResult;
  resultDate: string | null;
}

export interface OverviewPerson {
  /** Sorgulanan kişinin adı, kayıtta yazıldığı gibi; okunamadıysa null. */
  name: string | null;
  /** Taraflar tablosuyla tek ve açık biçimde eşleşen rol; yoksa null. */
  role: string | null;
  queries: OverviewQuery[];
}

export interface OverviewMilestone {
  key: string;
  label: string;
  count: number;
  firstDate: string | null;
  lastDate: string | null;
  /** Bu başlık altında sayılan UYAP işlem türü adları. */
  uyapTypes: string[];
  recent: Array<{ date: string | null; text: string }>;
}

export interface OverviewService {
  barcode: string | null;
  recipient: string | null;
  method: string | null;
  sentDate: string | null;
  /** Sonuç metni ("Tebliğ Edildi"); kayıtta yazmıyorsa null. */
  result: string | null;
  resultDate: string | null;
}

export interface ExecutionOverview {
  fetchedAt: string | null;
  /** UYAP'ın söylediği kayıt sayılarıyla her tablo tam okundu mu. */
  complete: boolean;
  identity: Pair[];
  parties: OverviewParty[];
  account: Pair[];
  collections: Pair[];
  activity: {
    entries: number;
    undated: number;
    firstDate: string | null;
    lastDate: string | null;
    daysSinceLast: number | null;
    lastType: string;
    lastText: string;
  };
  milestones: OverviewMilestone[];
  otherActions: Array<{ name: string; count: number; lastDate: string | null }>;
  people: OverviewPerson[];
  services: OverviewService[];
}

const DEFAULT_GROUP_LABELS: Record<ReplyGroup, string> = {
  amount: "Tutar geçiyor",
  block: "“Bloke” ifadesi geçiyor",
  unclear: "Belirleyici ifade bulunamadı",
  negative: "“Bulunmamaktadır” türü ifade geçiyor",
};

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);
const text = (value: unknown): string => (typeof value === "string" ? value : "");
const count = (value: unknown): number =>
  typeof value === "number" && Number.isFinite(value) && value >= 0 ? Math.trunc(value) : 0;
const strings = (value: unknown): string[] =>
  Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string" && item.trim() !== "")
    : [];
const isGroup = (value: unknown): value is ReplyGroup =>
  typeof value === "string" && (REPLY_GROUPS as readonly string[]).includes(value);

function fileRef(raw: unknown): FileRef[] {
  if (!isRecord(raw) || !text(raw.id)) return [];
  return [
    {
      id: text(raw.id),
      fileName: text(raw.file_name) || "belge",
      storagePath: text(raw.storage_path),
    },
  ];
}

function receipt(raw: unknown): ReceiptItem[] {
  if (!isRecord(raw)) return [];
  const [document] = fileRef(raw.document);
  if (!document) return [];
  const amounts = strings(raw.amounts);
  return [
    {
      document,
      kind: text(raw.kind),
      label: text(raw.label) || text(raw.kind) || "Makbuz",
      date: text(raw.date) || null,
      readable: raw.readable === true,
      // Tek tutar yalnız sunucu öyle dediyse ve listede gerçekten tek tutar varsa gösterilir.
      amount: amounts.length === 1 && text(raw.amount) === amounts[0] ? amounts[0] : null,
      amounts,
    },
  ];
}

function reply(raw: unknown): ReplyItem[] {
  if (!isRecord(raw)) return [];
  const documents = Array.isArray(raw.documents) ? raw.documents.flatMap(fileRef) : [];
  if (documents.length === 0) return [];
  return [
    {
      date: text(raw.date) || null,
      readable: raw.readable === true,
      documents,
      // Tanınmayan grup en dikkatli gruba düşer: okunmadan geçilmesin.
      group: isGroup(raw.group) ? raw.group : "unclear",
      sender: text(raw.sender) || null,
      amounts: strings(raw.amounts),
      quotes: strings(raw.quotes),
    },
  ];
}

const list = (value: unknown): unknown[] => (Array.isArray(value) ? value : []);
const dateText = (value: unknown): string | null =>
  /^\d{4}-\d{2}-\d{2}/.test(text(value)) ? text(value) : null;

function pairs(value: unknown): Pair[] {
  return list(value).flatMap((item) =>
    isRecord(item) && text(item.label) && text(item.value)
      ? [{ label: text(item.label), value: text(item.value) }]
      : [],
  );
}

function queryResult(value: unknown): QueryResult {
  return value === "VAR" || value === "YOK" || value === "VAR/YOK" ? value : null;
}

function person(raw: unknown): OverviewPerson[] {
  if (!isRecord(raw)) return [];
  const queries = list(raw.queries).flatMap((item): OverviewQuery[] =>
    isRecord(item) && text(item.key)
      ? [
          {
            key: text(item.key),
            label: text(item.label) || text(item.key),
            count: count(item.count),
            lastDate: dateText(item.last_date),
            result: queryResult(item.result),
            resultDate: dateText(item.result_date),
          },
        ]
      : [],
  );
  return queries.length
    ? [{ name: text(raw.name) || null, role: text(raw.role) || null, queries }]
    : [];
}

/** UYAP bilgisi özetini güvenli biçimde okur; özet yoksa null (sekme bunu "henüz çekilmemiş" diye söyler). */
export function parseOverview(raw: unknown): ExecutionOverview | null {
  if (!isRecord(raw)) return null;
  const activity = isRecord(raw.activity) ? raw.activity : {};
  const last = isRecord(activity.last) ? activity.last : {};
  const days = activity.days_since_last;
  return {
    fetchedAt: text(raw.fetched_at) || null,
    complete: raw.complete === true,
    identity: pairs(raw.identity),
    parties: list(raw.parties).flatMap((item) =>
      isRecord(item) && text(item.name)
        ? [
            {
              role: text(item.role),
              type: text(item.type),
              name: text(item.name),
              lawyer: text(item.lawyer),
            },
          ]
        : [],
    ),
    account: pairs(raw.account),
    collections: pairs(raw.collections),
    activity: {
      entries: count(activity.entries),
      undated: count(activity.undated),
      firstDate: dateText(activity.first_date),
      lastDate: dateText(activity.last_date),
      daysSinceLast:
        typeof days === "number" && Number.isFinite(days) && days >= 0 ? Math.trunc(days) : null,
      lastType: text(last.type),
      lastText: text(last.text),
    },
    milestones: list(raw.milestones).flatMap((item) =>
      isRecord(item) && text(item.key)
        ? [
            {
              key: text(item.key),
              label: text(item.label) || text(item.key),
              count: count(item.count),
              firstDate: dateText(item.first_date),
              lastDate: dateText(item.last_date),
              uyapTypes: strings(item.uyap_types),
              recent: list(item.recent).flatMap((entry) =>
                isRecord(entry) && text(entry.text)
                  ? [{ date: dateText(entry.date), text: text(entry.text) }]
                  : [],
              ),
            },
          ]
        : [],
    ),
    otherActions: list(raw.other_actions).flatMap((item) =>
      isRecord(item) && text(item.name)
        ? [{ name: text(item.name), count: count(item.count), lastDate: dateText(item.last_date) }]
        : [],
    ),
    people: list(isRecord(raw.asset_queries) ? raw.asset_queries.people : []).flatMap(person),
    services: list(raw.services).flatMap((item) =>
      isRecord(item)
        ? [
            {
              barcode: text(item.barcode) || null,
              recipient: text(item.recipient) || null,
              method: text(item.method) || null,
              sentDate: dateText(item.sent_date),
              result: text(item.result) || null,
              resultDate: dateText(item.result_date),
            },
          ]
        : [],
    ),
  };
}

const trDate = (value: string | null): string => {
  const match = value ? /^(\d{4})-(\d{2})-(\d{2})/.exec(value) : null;
  return match ? `${match[3]}.${match[2]}.${match[1]}` : "tarihi yok";
};

/** Tarafları rol başlıkları altında toplar (sunucunun sırası korunur: alacaklılar, borçlular, diğerleri). */
export function groupParties(
  parties: OverviewParty[],
): Array<{ role: string; members: OverviewParty[] }> {
  const groups: Array<{ role: string; members: OverviewParty[] }> = [];
  for (const party of parties) {
    const role = party.role || "Rolü yazılmamış";
    const group = groups.find((item) => item.role === role);
    if (group) group.members.push(party);
    else groups.push({ role, members: [party] });
  }
  return groups;
}

export type QueryTone = "var" | "yok" | "mixed" | "none";

/**
 * Sorgu hücresi: kayıtta yazan son sonuç ve tarihi. Sonuç yazmayan kayıt "sonuç yazılmamış" diye gösterilir, tahmin edilmez;
 * son sonuçtan sonra sonuçsuz bir sorgu daha varsa o da söylenir.
 */
export function queryCell(query: OverviewQuery): { text: string; tone: QueryTone } {
  const times = query.count > 1 ? ` · ${query.count} sorgu` : "";
  if (query.result === null)
    return { text: `sonuç yazılmamış · ${trDate(query.lastDate)}${times}`, tone: "none" };
  const later =
    query.lastDate && query.resultDate && query.lastDate > query.resultDate
      ? ` · son sorgu ${trDate(query.lastDate)} (sonuç yazılmamış)`
      : "";
  const tone: QueryTone = query.result === "VAR" ? "var" : query.result === "YOK" ? "yok" : "mixed";
  const result = query.result === "VAR/YOK" ? "aynı gün VAR ve YOK" : query.result;
  return { text: `${result} · ${trDate(query.resultDate)}${later}${times}`, tone };
}

/** Önemli işlem satırının tarih kısmı: tek kayıtta tek tarih, çok kayıtta "ilk – son". */
export function milestoneDates(item: OverviewMilestone): string {
  if (!item.firstDate && !item.lastDate) return "tarihi yok";
  if (item.count <= 1 || item.firstDate === item.lastDate)
    return trDate(item.lastDate ?? item.firstDate);
  return `${trDate(item.firstDate)} – ${trDate(item.lastDate)}`;
}

/** Tebligatın sonucu: yazıyorsa aynen; yalnız sonuç kaydı girilmişse öyle; hiç kayıt yoksa "sonuç kaydı yok". */
export function serviceOutcome(item: OverviewService): { text: string; known: boolean } {
  if (item.result)
    return {
      text: `${item.result}${item.resultDate ? ` · ${trDate(item.resultDate)}` : ""}`,
      known: true,
    };
  if (item.resultDate)
    return {
      text: `Sonuç kaydı girilmiş (${trDate(item.resultDate)}); sonucun ne olduğu kayıtta yazmıyor`,
      known: false,
    };
  return { text: "Sonuç kaydı yok", known: false };
}

/** Tebligat bölümünün başlığı: kaç kayıt, kaçında sonuç kaydı var, kaçında sonuç metni yazıyor. */
export function servicesHeadline(services: OverviewService[]): string {
  if (services.length === 0) return "Safahatta tebligat kaydı yok.";
  const recorded = services.filter((item) => item.resultDate).length;
  const written = services.filter((item) => item.result).length;
  return `${services.length} tebligat kaydı · sonuç kaydı girilen: ${recorded} · sonucu yazan: ${written}`;
}

/** Sunucu yanıtını güvenli biçimde okur; bozuk ya da eksik alan boş değere düşer, sayfa çökmez. */
export function parseBreakdown(raw: unknown): ExecutionBreakdown {
  const body = isRecord(raw) ? raw : {};
  const replies = isRecord(body.replies) ? body.replies : {};
  const items = Array.isArray(replies.items) ? replies.items.flatMap(reply) : [];
  const groups: Partial<Record<ReplyGroup, number>> = {};
  for (const item of items) groups[item.group] = (groups[item.group] ?? 0) + 1;
  const labels = { ...DEFAULT_GROUP_LABELS };
  const rawLabels =
    isRecord(body.labels) && isRecord(body.labels.reply_groups) ? body.labels.reply_groups : {};
  for (const group of REPLY_GROUPS)
    if (text(rawLabels[group])) labels[group] = text(rawLabels[group]);
  return {
    caseId: text(body.case_id),
    fileNo: text(body.file_no) || null,
    court: text(body.court),
    receipts: Array.isArray(body.receipts) ? body.receipts.flatMap(receipt) : [],
    replies: {
      envelopes: count(replies.envelopes),
      attachments: count(replies.attachments),
      unread: count(replies.unread),
      items,
      groups,
    },
    replyGroupLabels: labels,
    overview: parseOverview(body.overview),
  };
}

/** Makbuz satırındaki tutar hücresi: tek tutar, "n farklı tutar: …" ya da açık bir "okunamadı". */
export function receiptCell(item: ReceiptItem): string {
  if (!item.readable) return "Metni okunamadı";
  if (item.amount) return item.amount;
  if (item.amounts.length === 0) return "Tutar bulunamadı";
  return `${item.amounts.length} farklı tutar: ${item.amounts.join(" · ")}`;
}

/** Makbuz türlerinin sayımı ("Tahsilat 29 · Masraf 29 · Reddiyat 38"), listedeki sırayla. */
export function receiptCounts(
  receipts: ReceiptItem[],
): Array<{ kind: string; label: string; count: number; single: number }> {
  const order: string[] = [];
  const byKind = new Map<string, { kind: string; label: string; count: number; single: number }>();
  for (const item of receipts) {
    let entry = byKind.get(item.kind);
    if (!entry) {
      entry = { kind: item.kind, label: item.label, count: 0, single: 0 };
      byKind.set(item.kind, entry);
      order.push(item.kind);
    }
    entry.count += 1;
    if (item.amount) entry.single += 1;
  }
  return order.map((kind) => byKind.get(kind)!);
}

/** Cevap bölümünün başlığı: kaç cevap evrakı, kaç ek, kaç ayrı yazı. */
export function replyHeadline(replies: ExecutionBreakdown["replies"]): string {
  if (replies.envelopes === 0 && replies.attachments === 0)
    return "Bu dosyada haciz ihbarnamesi cevabı yok.";
  const parts = [`${replies.envelopes} cevap evrakı`, `${replies.attachments} ek`];
  if (replies.items.length !== replies.attachments) parts.push(`${replies.items.length} ayrı yazı`);
  if (replies.unread > 0) parts.push(`${replies.unread} ekin metni okunamadı`);
  return parts.join(" · ");
}

export type ReplyFilter = "all" | ReplyGroup;

export function filterReplies(items: ReplyItem[], filter: ReplyFilter): ReplyItem[] {
  return filter === "all" ? items : items.filter((item) => item.group === filter);
}

/** Sunucudaki kuralın aynısı: birim adı icra dairesi/müdürlüğü ya da icra hukuk/ceza mahkemesi mi. */
export function isExecutionCourt(court: string | null | undefined): boolean {
  const folded = (court ?? "")
    .replace(/[İIı]/g, "i")
    .toLocaleLowerCase("tr-TR")
    .replace(/\s+/g, " ");
  return /icra (dairesi|müdürlüğü|hukuk mahkemesi|ceza mahkemesi)/.test(folded);
}

const BASE = (import.meta.env?.VITE_API_URL ?? "http://localhost:8766").replace(/\/$/, "");

export async function loadBreakdown(
  caseId: string,
  signal?: AbortSignal,
): Promise<ExecutionBreakdown> {
  const token = inMemoryAccessToken();
  let response: Response;
  try {
    response = await fetch(`${BASE}/api/office/execution/files/${encodeURIComponent(caseId)}`, {
      credentials: "include",
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      signal,
    });
  } catch (error) {
    if (signal?.aborted) throw error;
    throw new Error("Sunucuya ulaşılamadı.");
  }
  if (response.status === 401) throw new Error("Oturumunuz sona ermiş; yeniden giriş yapın.");
  if (response.status === 404) throw new Error("Bu kayıt bir icra dosyası olarak bulunamadı.");
  if (!response.ok) throw new Error("İcra dosyası dökümü şu an yüklenemiyor.");
  return parseBreakdown(await response.json().catch(() => null));
}
