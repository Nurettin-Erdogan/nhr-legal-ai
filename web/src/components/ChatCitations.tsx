import { Info, ShieldAlert } from "lucide-react";
import { SourceReader } from "@/components/SourceReader";
import { groupCitations } from "@/lib/citation-groups";
import { officialPortalUrl, verificationTag } from "@/lib/source-label";
import type { ConsultedSource } from "@/lib/consulted-sources";
import {
  USER_DOCUMENT_NOTE,
  describeDocumentScope,
  type DocumentScope,
} from "@/lib/document-scope";

export interface ChatCitation {
  marker: string;
  source_id?: string | null;
  source_type?: string | null;
  excerpt?: string | null;
  source_url: string | null;
  reference: string;
  /** "official" resmî metinle karşılaştırılmış; "user_document" kullanıcının kendi belgesi; diğerleri karşılaştırılmamış. */
  verification: string;
}

/**
 * Atıf rozeti (kural: `@/lib/source-label`): resmî kayıtta "Resmî metin ✓", kullanıcı belgesinde "kullanıcı belgesi".
 * Karşılaştırılmamış kayıtta olumsuz rozet de ✓ de yoktur; kararı resmî portalda açan bağlantı gösterilir.
 */
function CitationBadge({ verification, url }: { verification: string; url?: string | null }) {
  const tag = verificationTag(verification);
  if (tag?.tone === "official")
    return (
      <span
        className="rounded px-1.5 py-0.5 bg-emerald-500/15 text-emerald-700 dark:text-emerald-400 text-[10px] font-medium"
        data-testid="citation-official"
      >
        {tag.label}
      </span>
    );
  if (tag)
    return (
      <span className="rounded px-1.5 py-0.5 bg-sky-500/15 text-sky-700 dark:text-sky-400 text-[10px] font-medium">
        {tag.label}
      </span>
    );
  const portal = officialPortalUrl(url);
  return portal ? (
    <a
      href={portal}
      target="_blank"
      rel="noreferrer"
      className="text-[10px] font-medium text-primary underline underline-offset-2"
      data-testid="citation-portal-link"
    >
      Resmî sitede aç ↗
    </a>
  ) : null;
}

export function CitationList({ citations }: { citations: ChatCitation[] }) {
  if (!citations.length) return null;
  const hasUserDocument = citations.some((citation) => citation.verification === "user_document");
  return (
    <div className="mt-3 pt-3 border-t border-border space-y-1.5">
      <p className="text-[11px] font-medium text-muted-foreground uppercase tracking-wide">
        Cevapta kullanılan atıflar
      </p>
      {groupCitations(citations).map(({ label, citation: c }) => (
        <div key={label} className="text-xs flex flex-wrap items-start gap-1.5">
          <span className="font-mono text-muted-foreground">{label}</span>
          {c.verification !== "user_document" && c.source_type !== "document" ? (
            <SourceReader
              sourceId={c.source_id}
              reference={c.reference}
              sourceUrl={c.source_url}
              excerpt={c.excerpt}
            >
              {c.reference}
            </SourceReader>
          ) : (
            <span>{c.reference}</span>
          )}
          <CitationBadge verification={c.verification} url={c.source_url} />
        </div>
      ))}
      {hasUserDocument && (
        <p className="text-[11px] text-muted-foreground flex items-start gap-1 pt-1">
          <Info className="h-3 w-3 mt-0.5 shrink-0" /> {USER_DOCUMENT_NOTE}
        </p>
      )}
    </div>
  );
}

/**
 * Cevapta alıntılanmayan ama incelenen doğrulanmış kaynaklar. Cevabın dayanağı değildir;
 * kullanıcı ilgili kararları pasajlarıyla kendisi okuyabilsin diye gösterilir.
 */
export function ConsultedSourceList({ sources }: { sources: ConsultedSource[] }) {
  if (!sources.length) return null;
  return (
    <details className="mt-3 pt-3 border-t border-border group">
      <summary className="cursor-pointer text-[11px] font-medium text-muted-foreground uppercase tracking-wide">
        İncelenen diğer kaynaklar ({sources.length})
      </summary>
      <p className="mt-1.5 text-[11px] text-muted-foreground flex items-start gap-1">
        <Info className="h-3 w-3 mt-0.5 shrink-0" /> Bunlar cevabın dayanağı değildir; cevap yalnız
        yukarıdaki atıflara dayanır. İlgili olup olmadığını siz değerlendirin.
      </p>
      <ul className="mt-2 space-y-2">
        {sources.map((source) => (
          <li key={source.marker + source.reference} className="text-xs">
            <div className="flex flex-wrap items-start gap-1.5">
              {source.verification !== "user_document" && source.source_type !== "document" ? (
                <SourceReader
                  sourceId={source.source_id}
                  reference={source.reference}
                  sourceUrl={source.source_url}
                  excerpt={source.excerpt}
                >
                  {source.reference}
                </SourceReader>
              ) : (
                <span className="font-medium">{source.reference}</span>
              )}
              <CitationBadge verification={source.verification} url={source.source_url} />
            </div>
            {source.excerpt && (
              <p className="mt-0.5 line-clamp-3 text-muted-foreground">{source.excerpt}</p>
            )}
          </li>
        ))}
      </ul>
    </details>
  );
}

/** Cevabın dayandığı dava belgeleri: okunamayan/işlenmeyen belge sessizce yok sayılmaz. */
export function DocumentScopeNotice({ scope }: { scope: DocumentScope }) {
  const summary = describeDocumentScope(scope);
  return (
    <div
      role="note"
      data-tone={summary.tone}
      className={
        summary.tone === "warn"
          ? "mt-2 rounded-md border border-amber-500/40 bg-amber-500/10 p-2 text-xs text-amber-800 dark:text-amber-300"
          : "mt-2 rounded-md border border-border bg-muted/40 p-2 text-xs text-muted-foreground"
      }
    >
      {summary.tone === "warn" && <ShieldAlert className="inline h-3.5 w-3.5 mr-1" />}
      {summary.lines.map((line) => (
        <p key={line}>{line}</p>
      ))}
    </div>
  );
}
