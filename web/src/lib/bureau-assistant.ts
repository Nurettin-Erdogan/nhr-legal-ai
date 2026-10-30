import { inMemoryAccessToken } from "@/lib/auth-api";

export interface BureauProposal {
  key: string;
  kind: "hearing" | "document";
  title: string;
  description: string;
  case_id: string | null;
  case_title: string;
  source_label: string;
  source_url: string;
  date: string;
  priority: "high" | "medium";
  action_label: string;
}
export interface BureauData {
  proposals: BureauProposal[];
  hearings: {
    id: string;
    title: string;
    next_hearing: string;
    case_no: string | null;
    court: string | null;
  }[];
  tasks: { id: string; title: string; due_date: string | null; case_id: string | null }[];
  counts: { open_tasks: number; overdue_tasks: number; upcoming_hearings: number };
  limited: boolean;
  generated_at: string;
  window_days: number;
}
const BASE = (import.meta.env.VITE_API_URL ?? "http://localhost:8766").replace(/\/$/, "");

async function call(path: string, body?: unknown, signal?: AbortSignal) {
  const token = inMemoryAccessToken();
  const response = await fetch(`${BASE}/api/bureau-assistant${path}`, {
    method: body ? "POST" : "GET",
    credentials: "include",
    cache: "no-store",
    headers: {
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(body ? { "Content-Type": "application/json" } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
    signal: signal
      ? AbortSignal.any([signal, AbortSignal.timeout(20000)])
      : AbortSignal.timeout(20000),
  });
  if (!response.ok) {
    let detail = "Büro Asistanı verileri alınamadı. Yeniden deneyin.";
    try {
      const data = await response.json();
      if (typeof data.detail === "string") detail = data.detail;
    } catch {
      /* keep safe message */
    }
    throw new Error(detail);
  }
  return response.json();
}
export const loadBureau = (signal?: AbortSignal): Promise<BureauData> =>
  call("", undefined, signal);
export const decideBureau = (key: string, action: "approve" | "dismiss", title?: string) =>
  call("/decisions", { key, action, ...(title ? { title } : {}) });
