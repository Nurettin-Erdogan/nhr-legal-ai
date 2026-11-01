import type { FileBrowserDocument } from "@/lib/file-browser";

/** Server pieces are plain text. Never interpret uploaded document content as HTML. */
export function ContentMatchExcerpt({ match }: { match: FileBrowserDocument["content_match"] }) {
  if (!match) return null;
  return (
    <div className="mt-2 max-w-xl whitespace-normal break-words text-xs leading-relaxed">
      <p>
        {match.before}
        <mark className="rounded bg-yellow-200 px-0.5 text-slate-950">{match.match}</mark>
        {match.after}
      </p>
      <p className="mt-1 text-muted-foreground">
        {match.page_number != null
          ? `Sayfa ${match.page_number}`
          : "Sayfa numarası kaynak metinde yok"}
        {match.section_title && ` · ${match.section_title}`}
      </p>
    </div>
  );
}
