export const API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8765";

export type CorpusStats = {
  source_count: number;
  chunk_count: number;
  latest_decision_date: string | null;
};

export type LegalSearchHit = {
  id: string;
  title: string;
  source_url: string | null;
  chamber: string | null;
  docket_no: string | null;
  decision_no: string | null;
  decision_date: string | null;
  excerpt: string;
  rank: number;
};

export type LegalSearchResponse = {
  query: string;
  total: number;
  limit: number;
  offset: number;
  results: LegalSearchHit[];
};

export type LegalSourceDetail = {
  id: string;
  title: string;
  source_url: string | null;
  external_id: string | null;
  authority: string | null;
  chamber: string | null;
  docket_no: string | null;
  decision_no: string | null;
  decision_date: string | null;
  raw_text: string;
  metadata: Record<string, unknown>;
  chunks: Array<{ id: string; chunk_index: number; content: string }>;
};

export async function getDecision(id: string): Promise<LegalSourceDetail | null> {
  const response = await fetch(`${API_URL}/api/legal/sources/${encodeURIComponent(id)}`, {
    cache: "no-store",
  });
  if (response.status === 404) return null;
  if (!response.ok) throw new Error("Karar ayrıntısı alınamadı");
  return response.json();
}
