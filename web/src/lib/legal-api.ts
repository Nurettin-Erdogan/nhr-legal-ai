const API_BASE_URL = (import.meta.env.VITE_API_URL ?? "http://localhost:8766").replace(/\/$/, "");

export interface CorpusStats {
  source_count: number;
  chunk_count: number;
  decision_count: number;
  legislation_count: number;
  other_count: number;
  latest_decision_date: string | null;
  seed_count: number;
  court_decisions: {
    yargitay: number;
    danistay: number;
    anayasa_mahkemesi: number;
    istinaf_emsal: number;
  };
  third_party: {
    yargitay: number;
    danistay: number;
    istinaf_emsal: number;
    aym_norm_denetimi: number;
  };
  administrative: {
    kamu_denetciligi_kurumu: number;
    sayistay: number;
    uyusmazlik_mahkemesi: number;
  };
  legislation_verification: {
    bedesten: number;
    both_verified: number;
    gazette_only: number;
    mbs_only: number;
    neither: number;
  };
  embeddings: {
    ready: number;
    pending: number;
  };
}

export async function getCorpusStats(signal?: AbortSignal): Promise<CorpusStats> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/api/legal/stats`, {
      credentials: "include",
      signal,
    });
  } catch {
    throw new Error("Hukuk veritabanı servisine ulaşılamadı.");
  }
  if (!response.ok) throw new Error(`Korpus bilgisi alınamadı (${response.status}).`);
  return (await response.json()) as CorpusStats;
}
