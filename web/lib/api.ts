export const API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8765";

export type CorpusStats = {
  source_count: number;
  chunk_count: number;
  decision_count: number;
  legislation_count: number;
  latest_decision_date: string | null;
};

export type LegalSearchHit = {
  id: string;
  source_type: "court_decision" | "legislation";
  title: string;
  source_url: string | null;
  authority: string | null;
  court_name: string | null;
  chamber: string | null;
  docket_no: string | null;
  decision_no: string | null;
  decision_date: string | null;
  legislation_type: string | null;
  law_name: string | null;
  law_no: string | null;
  article_no: string | null;
  article_title: string | null;
  official_gazette_date: string | null;
  version_date: string | null;
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
  source_type: "court_decision" | "legislation";
  title: string;
  source_url: string | null;
  external_id: string | null;
  authority: string | null;
  court_name: string | null;
  chamber: string | null;
  docket_no: string | null;
  decision_no: string | null;
  decision_date: string | null;
  legislation_type: string | null;
  law_name: string | null;
  law_no: string | null;
  article_no: string | null;
  article_title: string | null;
  official_gazette_no: string | null;
  official_gazette_date: string | null;
  version_date: string | null;
  raw_text: string;
  metadata: Record<string, unknown>;
  chunks: Array<{ id: string; chunk_index: number; content: string }>;
};

export async function getLegalSource(id: string): Promise<LegalSourceDetail | null> {
  const response = await fetch(`${API_URL}/api/legal/sources/${encodeURIComponent(id)}`, {
    cache: "no-store",
  });
  if (response.status === 404) return null;
  if (!response.ok) throw new Error("Hukuk kaynağı ayrıntısı alınamadı");
  return response.json();
}
