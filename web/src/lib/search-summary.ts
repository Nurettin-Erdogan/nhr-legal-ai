/** Request-local observations, never a count of all matching corpus records. */
export interface SearchSummaryData {
  candidate_documents: number;
  verified_documents: number;
  selected_documents: number;
  pending_documents: number;
  unverified_excluded: number;
  verification_attempted: number;
  verification_promoted: number;
  verification_stop: string;
  retrieval_partial: boolean;
  exhaustive: false;
}

export function parseSearchSummary(value: unknown): SearchSummaryData | undefined {
  if (!value || typeof value !== "object") return undefined;
  const data = value as Record<string, unknown>;
  const counts = ["candidate_documents", "verified_documents", "selected_documents",
    "pending_documents", "unverified_excluded", "verification_attempted", "verification_promoted"];
  if (counts.some((key) => !Number.isSafeInteger(data[key]) || (data[key] as number) < 0)
      || typeof data.retrieval_partial !== "boolean"
      || typeof data.verification_stop !== "string" || data.exhaustive !== false) return undefined;
  if ((data.selected_documents as number) > (data.verified_documents as number)
      || (data.verified_documents as number) > (data.candidate_documents as number)) return undefined;
  return Object.fromEntries([...counts, "verification_stop", "retrieval_partial", "exhaustive"]
    .map((key) => [key, data[key]])) as unknown as SearchSummaryData;
}

export function verificationNotice(summary: SearchSummaryData): string | undefined {
  if (!summary.unverified_excluded) return undefined;
  const reasons: Record<string, string> = {
    captcha: "Resmî portal CAPTCHA istedi.",
    rate_limited: "Resmî portal istek sınırına ulaşıldı.",
    time_budget: "Resmî doğrulama için ayrılan süre doldu.",
    timeout: "Resmî doğrulama süresinde tamamlanamadı.",
    database_error: "Doğrulama için kaynak metinleri okunamadı.",
    error: "Kaynak doğrulaması tamamlanamadı.",
    document_budget: "Bu isteğin doğrulama aday sınırına ulaşıldı.",
    target_reached: "Bu cevap için kaynak seçimi tamamlandı; diğer adaylar doğrulanmadı.",
  };
  return `${summary.unverified_excluded.toLocaleString("tr-TR")} doğrulanmamış aday cevaba alınmadı. ${reasons[summary.verification_stop] ?? "Doğrulama tamamlanmayan veya metni eşleşmeyen adaylar kullanılmadı."}`;
}
