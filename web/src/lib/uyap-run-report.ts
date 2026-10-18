/** Full-run history contains counts/warnings only; never detail.data, tokens or ephemeral portal keys. */
import { summarize, type FileReport, type SyncRun } from "@/lib/uyap-sync-all";

export interface AuditCheckpoint {
  id: string;
  revision: number;
  finished: boolean;
  verify_only: boolean;
  list_complete: boolean;
  aborted: boolean;
  stopped_because?: string;
  save_note: { kind: "ok" | "warn"; text: string } | null;
  reports: (Omit<FileReport, "key" | "who" | "detail"> & {
    detail?: Omit<NonNullable<FileReport["detail"]>, "data">;
  })[];
}

export interface StoredAuditRun {
  id: string;
  revision: number;
  finished: boolean;
  verifyOnly: boolean;
  listComplete: boolean;
  updatedAt: string;
  saveNote: { kind: "ok" | "warn"; text: string } | null;
  run: SyncRun;
}

const bounded = (text: string, max: number) => text.replace(/\s+/g, " ").trim().slice(0, max);
const warnings = (texts: string[]) => texts.slice(0, 6).map((t) => bounded(t, 300));

export function auditCheckpoint(
  id: string,
  revision: number,
  finished: boolean,
  verifyOnly: boolean,
  listComplete: boolean,
  run: SyncRun,
  saveNote: StoredAuditRun["saveNote"] = null,
): AuditCheckpoint {
  return {
    id,
    revision,
    finished,
    verify_only: verifyOnly,
    list_complete: listComplete,
    aborted: run.aborted,
    stopped_because: run.stoppedBecause?.slice(0, 1000),
    save_note: saveNote ? { ...saveNote, text: bounded(saveNote.text, 1000) } : null,
    reports: run.reports.map((r) => ({
      esas: bounded(r.who?.esas || r.esas, 60),
      birim: bounded(r.who?.birim || r.birim, 160),
      yargiTuru: bounded(r.yargiTuru || "", 80),
      outcome: r.outcome,
      declared: r.declared,
      found: r.found,
      stored: r.stored,
      sent: r.sent,
      missing: r.missing,
      pulls: r.pulls,
      problems: warnings(r.problems),
      ...(r.timing ? { timing: r.timing } : {}),
      ...(r.absent ? { absent: r.absent } : {}),
      ...(r.detail
        ? {
            detail: {
              state: r.detail.state,
              tabs: r.detail.tabs,
              saved: r.detail.saved,
              problems: warnings(r.detail.problems),
            },
          }
        : {}),
    })),
  };
}

/** Fail closed on malformed/contradictory history. Summary is recomputed, never trusted from JSON. */
export function parseAuditRun(raw: unknown): StoredAuditRun | null {
  if (!raw || typeof raw !== "object") return null;
  const row = raw as Record<string, unknown>;
  if (
    typeof row.id !== "string" ||
    !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(row.id) ||
    !Number.isInteger(row.revision) ||
    Number(row.revision) < 1 ||
    Number(row.revision) > 1_000_000
  )
    return null;
  const s = row.snapshot as Record<string, unknown> | null;
  if (
    !s ||
    typeof s !== "object" ||
    !Array.isArray(s.reports) ||
    !s.reports.length ||
    s.reports.length > 2000
  )
    return null;
  if (
    typeof s.finished !== "boolean" ||
    typeof s.verify_only !== "boolean" ||
    typeof s.list_complete !== "boolean" ||
    typeof s.aborted !== "boolean"
  )
    return null;
  if (row.finished !== undefined && row.finished !== s.finished) return null;
  const reports: FileReport[] = [];
  for (const [i, rawReport] of s.reports.entries()) {
    if (!rawReport || typeof rawReport !== "object") return null;
    const r = rawReport as Record<string, unknown>;
    if (
      typeof r.esas !== "string" ||
      typeof r.birim !== "string" ||
      typeof r.yargiTuru !== "string" ||
      !["complete", "empty", "incomplete", "failed", "pending"].includes(String(r.outcome))
    )
      return null;
    if (
      ["declared", "found", "stored", "sent", "missing", "pulls"].some(
        (k) => !Number.isInteger(r[k]) || Number(r[k]) < 0 || Number(r[k]) > 1_000_000,
      )
    )
      return null;
    if (
      Number(r.stored) + Number(r.missing) !== r.found ||
      (r.outcome === "complete" && (!r.found || r.missing)) ||
      (["empty", "pending"].includes(String(r.outcome)) && (r.found || r.sent || r.declared))
    )
      return null;
    const problems = Array.isArray(r.problems)
      ? r.problems.filter((v): v is string => typeof v === "string")
      : [];
    let detail: FileReport["detail"];
    if (r.detail) {
      const d = r.detail as Record<string, unknown>;
      if (
        !["complete", "partial", "failed", "skipped"].includes(String(d.state)) ||
        !Number.isInteger(d.tabs) ||
        Number(d.tabs) < 0 ||
        Number(d.tabs) > 20 ||
        typeof d.saved !== "boolean"
      )
        return null;
      detail = {
        state: d.state as NonNullable<FileReport["detail"]>["state"],
        tabs: Number(d.tabs),
        saved: d.saved,
        problems: warnings(
          Array.isArray(d.problems)
            ? d.problems.filter((v): v is string => typeof v === "string")
            : [],
        ),
      };
    }
    reports.push({
      key: `saved:${row.id}:${i}`,
      esas: bounded(r.esas, 60),
      birim: bounded(r.birim, 160),
      yargiTuru: bounded(r.yargiTuru, 80),
      outcome: r.outcome as FileReport["outcome"],
      declared: Number(r.declared),
      found: Number(r.found),
      stored: Number(r.stored),
      sent: Number(r.sent),
      missing: Number(r.missing),
      pulls: Number(r.pulls),
      problems: warnings(problems),
      detail,
    });
  }
  const note = s.save_note as Record<string, unknown> | null;
  return {
    id: row.id,
    revision: Number(row.revision),
    finished: s.finished,
    verifyOnly: s.verify_only,
    listComplete: s.list_complete,
    updatedAt: typeof row.updated_at === "string" ? row.updated_at : "",
    saveNote:
      note && ["ok", "warn"].includes(String(note.kind)) && typeof note.text === "string"
        ? { kind: note.kind as "ok" | "warn", text: bounded(note.text, 1000) }
        : null,
    run: {
      reports,
      summary: summarize(reports),
      aborted: s.aborted,
      stoppedBecause:
        typeof s.stopped_because === "string" ? bounded(s.stopped_because, 1000) : undefined,
    },
  };
}
