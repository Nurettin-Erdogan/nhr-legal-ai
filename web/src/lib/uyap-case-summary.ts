/**
 * UYAP dosya bilgilerinden tek bakışlık DURUM ÖZETİ. Yalnız UYAP'ın yazdığı metinler ve kayıt SAYILARI kullanılır; "dosya şu aşamada",
 * "alacak tahsil edilir" gibi hiçbir çıkarım ya da hukuki yorum yapılmaz. Tutarlar toplanmaz, aşama tahmin edilmez.
 */
import type { DetailTab, DetailTable, DosyaDetail } from "@/lib/uyap-bridge";
import { foldText, accountSummary } from "@/lib/uyap-detail-view";
import { formatDateTr, isoFromTr } from "@/lib/deadlines";

export interface SummaryFact {
  label: string;
  value: string;
}

export interface CaseStatusSummary {
  /** Dosya bilgileri ve hesap/tahsilat alanları (UYAP'ın yazdığı metin). */
  facts: SummaryFact[];
  /** Taraf sayısı ve rol dağılımı ("2 taraf: 1 Alacaklı, 1 Borçlu"). */
  parties: string | null;
  /** Safahat: kayıt sayısı, ilk/son tarih, son işlem. */
  safahat: {
    count: number;
    first: string | null;
    last: string | null;
    lastAction: string | null;
    recent: { date: string; text: string }[];
  } | null;
  /** Safahatta en sık görülen işlem türleri (sayı). */
  actionTypes: { label: string; count: number }[];
}

const tab = (detail: DosyaDetail, key: string): DetailTab | undefined =>
  detail.tabs.find((item) => item.key === key);
const column = (table: DetailTable, name: string): number =>
  table.headers.findIndex((header) => foldText(header) === foldText(name));

export function summarizeDetail(detail: DosyaDetail): CaseStatusSummary {
  const facts: SummaryFact[] = [];
  for (const pair of tab(detail, "bilgiler")?.pairs ?? [])
    if (pair.value) facts.push({ label: pair.label, value: pair.value });
  for (const pair of accountSummary(tab(detail, "hesap")?.pairs ?? [])) facts.push(pair);

  // Tahsilat/reddiyat özet satırı: başlıklar "Tahsilat", "Reddiyat", "Tahsilat Kalanı"...
  const summaryTable = (tab(detail, "tahsilat")?.tables ?? []).find(
    (table) =>
      column(table, "Tahsilat") >= 0 && column(table, "Reddiyat") >= 0 && table.rows.length === 1,
  );
  if (summaryTable)
    for (const name of ["Tahsilat", "Reddiyat", "Tahsilat Kalanı"]) {
      const at = column(summaryTable, name);
      const value = at >= 0 ? summaryTable.rows[0]![at] : "";
      if (value) facts.push({ label: name, value });
    }

  let parties: string | null = null;
  const partyTable = tab(detail, "taraflar")?.tables[0];
  if (partyTable && partyTable.rows.length) {
    const at = column(partyTable, "Rol");
    const counts = new Map<string, number>();
    if (at >= 0)
      for (const row of partyTable.rows)
        counts.set(row[at] || "Rolsüz", (counts.get(row[at] || "Rolsüz") ?? 0) + 1);
    const roles = [...counts].map(([role, count]) => `${count} ${role}`).join(", ");
    parties = `${partyTable.rows.length} taraf${roles ? `: ${roles}` : ""}`;
  }

  let safahat: CaseStatusSummary["safahat"] = null;
  let actionTypes: CaseStatusSummary["actionTypes"] = [];
  const log = tab(detail, "safahat")?.tables[0];
  if (log) {
    const dateAt = column(log, "Tarih");
    const typeAt = column(log, "İşlem Türü");
    const textAt = column(log, "Açıklama");
    const dated = log.rows
      .map((row) => ({
        iso: dateAt >= 0 ? isoFromTr(row[dateAt] ?? "") : null,
        type: typeAt >= 0 ? (row[typeAt] ?? "") : "",
        text: textAt >= 0 ? (row[textAt] ?? "") : "",
      }))
      .filter((item): item is { iso: string; type: string; text: string } => item.iso !== null)
      .sort((a, b) => (a.iso < b.iso ? 1 : a.iso > b.iso ? -1 : 0));
    const newest = dated[0];
    safahat = {
      count: log.rows.length,
      first: dated.length ? formatDateTr(dated[dated.length - 1]!.iso) : null,
      last: newest ? formatDateTr(newest.iso) : null,
      lastAction: newest
        ? [newest.type, newest.text].filter(Boolean).join(" — ").slice(0, 200)
        : null,
      recent: dated.slice(0, 5).map((item) => ({
        date: formatDateTr(item.iso),
        text: [item.type, item.text].filter(Boolean).join(" — ").slice(0, 160),
      })),
    };
    if (typeAt >= 0) {
      const counts = new Map<string, number>();
      for (const row of log.rows)
        if (row[typeAt]) counts.set(row[typeAt]!, (counts.get(row[typeAt]!) ?? 0) + 1);
      actionTypes = [...counts]
        .map(([label, count]) => ({ label, count }))
        .sort((a, b) => b.count - a.count)
        .slice(0, 6);
    }
  }
  return { facts, parties, safahat, actionTypes };
}
