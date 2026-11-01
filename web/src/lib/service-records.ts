/**
 * Tebliğ kayıtları: `/api/office/cases/{case_id}/service-records` yanıtının okunması ve süre hesabına aday tarihler.
 *
 * Sunucu e-tebliğ mazbatasındaki damgaları okur; burada hiçbir süre başlatılmaz. Aday tarih seçilince yalnız "süre başlangıcı"
 * kutusu dolar, hesabı avukat doğrular. Mazbatanın yazdığı gün ile kuraldan hesaplanan gün tutmuyorsa ikisi de gösterilir.
 */
import { inMemoryAccessToken } from "@/lib/auth-api";
import { formatDateTr, holidayName } from "@/lib/deadlines";

export interface ServiceEvent {
  kind: string;
  label: string;
  /** ISO damga: saat varsa "2026-09-03T10:15:00", yoksa "2026-09-08". */
  at: string;
  /** Mazbatadaki satır, aynen. */
  text: string;
}

export interface ServiceRecord {
  documentId: string;
  docType: string;
  /** Zarfın içindekiler, mazbatada yazdığı gibi. */
  served: string | null;
  events: ServiceEvent[];
  deliveredOn: string | null;
  /** Mazbatanın kendi satırındaki "yapılmış sayıldı" günü. */
  statedDeemedOn: string | null;
  /** Hesaba ulaşma gününden kurala göre hesaplanan gün; kural doğrulanamadıysa null. */
  computedDeemedOn: string | null;
  agrees: boolean | null;
}

export interface ServiceRule {
  reference: string;
  sourceUrl: string | null;
  sentence: string;
  days: number;
}

export interface ServiceRecords {
  records: ServiceRecord[];
  /** Tebliğ evrakı olup tarihi okunamayanlar (kâğıt mazbata, zarf). */
  unreadable: number;
  rule: ServiceRule | null;
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);
const text = (value: unknown): string => (typeof value === "string" ? value : "");
const ISO_DAY = /^\d{4}-\d{2}-\d{2}$/;
const day = (value: unknown): string | null =>
  typeof value === "string" && ISO_DAY.test(value.slice(0, 10)) ? value.slice(0, 10) : null;

function event(raw: unknown): ServiceEvent[] {
  if (!isRecord(raw) || !day(raw.at)) return [];
  return [
    {
      kind: text(raw.kind),
      label: text(raw.label) || text(raw.kind),
      at: text(raw.at),
      text: text(raw.text),
    },
  ];
}

function record(raw: unknown): ServiceRecord[] {
  if (!isRecord(raw)) return [];
  const document = isRecord(raw.document) ? raw.document : {};
  if (!text(document.id)) return [];
  const stated = day(raw.stated_deemed_on);
  const computed = day(raw.computed_deemed_on);
  return [
    {
      documentId: text(document.id),
      docType: text(raw.doc_type),
      served: text(raw.served) || null,
      events: Array.isArray(raw.events) ? raw.events.flatMap(event) : [],
      deliveredOn: day(raw.delivered_on),
      statedDeemedOn: stated,
      computedDeemedOn: computed,
      // Uyuşma sunucunun sözüne değil iki tarihin kendisine bakılarak söylenir.
      agrees: stated && computed ? stated === computed : null,
    },
  ];
}

/** Sunucu yanıtını güvenli biçimde okur; bozuk ya da eksik alan boş değere düşer, sayfa çökmez. */
export function parseServiceRecords(raw: unknown): ServiceRecords {
  const body = isRecord(raw) ? raw : {};
  const rule =
    isRecord(body.rule) && text(body.rule.sentence) && text(body.rule.reference)
      ? {
          reference: text(body.rule.reference),
          sourceUrl: /^https:\/\//.test(text(body.rule.source_url))
            ? text(body.rule.source_url)
            : null,
          sentence: text(body.rule.sentence),
          days:
            typeof body.rule.days === "number" && body.rule.days > 0
              ? Math.trunc(body.rule.days)
              : 0,
        }
      : null;
  return {
    records: Array.isArray(body.records) ? body.records.flatMap(record) : [],
    unreadable:
      typeof body.unreadable === "number" && body.unreadable > 0 ? Math.trunc(body.unreadable) : 0,
    rule,
  };
}

export interface ServiceCandidate {
  /** Süre başlangıcı kutusuna yazılacak ISO tarih. */
  date: string;
  label: string;
  /** Dikkat notu (tutmayan tarihler, hafta sonu/tatil, hesaplanamayan gün); yoksa boş. */
  warning: string;
  documentId: string;
}

function offDayNote(isoDate: string): string {
  const reason = holidayName(new Date(`${isoDate}T00:00:00Z`));
  return reason
    ? `Bu gün ${reason}; tebligatın yapılmış sayıldığı günün tatile rastlaması hâlindeki uygulamayı kontrol edin.`
    : "";
}

const join = (...parts: string[]): string => parts.filter(Boolean).join(" ");

/**
 * Tebliğ kayıtlarından süre başlangıcı adayları. Her kayıt için "yapılmış sayıldığı gün" önerilir: mazbata ile hesap
 * tutuyorsa tek aday; tutmuyorsa ikisi ayrı ayrı ve uyarıyla; gün bilinmiyorsa hesaba ulaşma günü uyarıyla.
 */
export function serviceCandidates(data: ServiceRecords): ServiceCandidate[] {
  const out: ServiceCandidate[] = [];
  for (const item of data.records) {
    const reached = item.deliveredOn ? `hesaba ulaşma ${formatDateTr(item.deliveredOn)}` : "";
    const what = item.served ? ` · ${item.served.slice(0, 90)}` : "";
    const add = (date: string, source: string, warning: string) =>
      out.push({
        date,
        label: `E-tebligat ${source}${reached ? ` (${reached})` : ""}${what}`,
        warning: join(warning, offDayNote(date)),
        documentId: item.documentId,
      });
    if (
      item.statedDeemedOn &&
      item.computedDeemedOn &&
      item.statedDeemedOn !== item.computedDeemedOn
    ) {
      const clash = `Mazbatada yazan gün (${formatDateTr(item.statedDeemedOn)}) ile hesaplanan gün (${formatDateTr(item.computedDeemedOn)}) farklı; mazbatayı açıp kontrol edin.`;
      add(item.statedDeemedOn, "mazbataya göre yapılmış sayıldı", clash);
      add(item.computedDeemedOn, "kurala göre yapılmış sayılır", clash);
    } else if (item.statedDeemedOn || item.computedDeemedOn) {
      const source =
        item.statedDeemedOn && item.computedDeemedOn
          ? "yapılmış sayıldı (mazbata ve hesap aynı)"
          : item.statedDeemedOn
            ? "mazbataya göre yapılmış sayıldı"
            : "kurala göre yapılmış sayılır";
      add((item.statedDeemedOn ?? item.computedDeemedOn)!, source, "");
    } else if (item.deliveredOn) {
      out.push({
        date: item.deliveredOn,
        label: `E-tebligat hesaba ulaştı${what}`,
        warning:
          "Yapılmış sayıldığı gün okunamadı ve hesaplanamadı; bu, hesaba ulaşma günüdür, tebliğ günü değildir.",
        documentId: item.documentId,
      });
    }
  }
  return out.sort((a, b) => (a.date < b.date ? 1 : a.date > b.date ? -1 : 0));
}

/** Bölümün başlığı: kaç kayıt okundu, kaç tebliğ evrakının tarihi okunamadı. */
export function recordsHeadline(data: ServiceRecords): string {
  const parts: string[] = [];
  if (data.records.length > 0) parts.push(`${data.records.length} e-tebliğ mazbatası okundu`);
  if (data.unreadable > 0)
    parts.push(`${data.unreadable} tebliğ evrakının tarihi okunamadı (kâğıt mazbata ya da zarf)`);
  return parts.join(" · ");
}

const BASE = (import.meta.env?.VITE_API_URL ?? "http://localhost:8766").replace(/\/$/, "");

export async function loadServiceRecords(
  caseId: string,
  signal?: AbortSignal,
): Promise<ServiceRecords> {
  const token = inMemoryAccessToken();
  const response = await fetch(
    `${BASE}/api/office/cases/${encodeURIComponent(caseId)}/service-records`,
    {
      credentials: "include",
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      signal,
    },
  );
  if (!response.ok) throw new Error("Tebliğ kayıtları yüklenemedi.");
  return parseServiceRecords(await response.json().catch(() => null));
}
