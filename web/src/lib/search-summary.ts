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
  /** "sampled": a lane answered from a bounded sample; "failed": a lane returned nothing. Absent in older messages. */
  retrieval_limit?: "sampled" | "failed";
  exhaustive: false;
  retrieval_strategy?: "verified_statute" | "full_candidates";
  research_deferred?: boolean;
}

export function parseSearchSummary(value: unknown): SearchSummaryData | undefined {
  if (!value || typeof value !== "object") return undefined;
  const data = value as Record<string, unknown>;
  const counts = [
    "candidate_documents",
    "verified_documents",
    "selected_documents",
    "pending_documents",
    "unverified_excluded",
    "verification_attempted",
    "verification_promoted",
  ];
  if (
    counts.some((key) => !Number.isSafeInteger(data[key]) || (data[key] as number) < 0) ||
    typeof data.retrieval_partial !== "boolean" ||
    typeof data.verification_stop !== "string" ||
    data.exhaustive !== false
  )
    return undefined;
  if (
    (data.selected_documents as number) > (data.verified_documents as number) ||
    (data.verified_documents as number) > (data.candidate_documents as number)
  )
    return undefined;
  const result = Object.fromEntries(
    [...counts, "verification_stop", "retrieval_partial", "exhaustive"].map((key) => [
      key,
      data[key],
    ]),
  ) as unknown as SearchSummaryData;
  if (data.retrieval_limit === "sampled" || data.retrieval_limit === "failed") {
    result.retrieval_limit = data.retrieval_limit;
  }
  if (
    data.retrieval_strategy === "verified_statute" ||
    data.retrieval_strategy === "full_candidates"
  ) {
    result.retrieval_strategy = data.retrieval_strategy;
    result.research_deferred = data.research_deferred === true;
  }
  return result;
}

export function shouldAutoResearch(
  index: number,
  messageCount: number,
  loading: boolean,
  summary?: SearchSummaryData,
): boolean {
  return (
    !loading &&
    index === messageCount - 2 &&
    summary?.retrieval_strategy === "verified_statute" &&
    summary.research_deferred === true
  );
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
