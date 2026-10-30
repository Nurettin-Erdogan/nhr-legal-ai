import { useEffect, useState } from "react";
import { Download, Loader2 } from "lucide-react";
import { db } from "@/lib/db";
import { cn } from "@/lib/utils";
import { dateTr } from "@/lib/execution";
import { ExecutionOverview } from "@/components/ExecutionOverview";
import {
  REPLY_GROUPS,
  filterReplies,
  loadBreakdown,
  receiptCell,
  receiptCounts,
  replyHeadline,
  type ExecutionBreakdown as Breakdown,
  type FileRef,
  type ReplyFilter,
  type ReplyGroup,
} from "@/lib/execution-breakdown";

const GROUP_TONE: Record<ReplyGroup, string> = {
  amount: "border-emerald-600/40 bg-emerald-600/10 text-emerald-700 dark:text-emerald-300",
  block: "border-amber-500/40 bg-amber-500/10 text-amber-800 dark:text-amber-300",
  unclear: "border-amber-500/40 bg-amber-500/10 text-amber-800 dark:text-amber-300",
  negative: "border-border bg-secondary/50 text-muted-foreground",
};

/** Dava sayfasındaki "İcra Özeti" sekmesi: UYAP bilgisinden dosya künyesi, ardından haciz ihbarnamesi cevapları ve makbuz dökümü. */
export function ExecutionBreakdown({ caseId }: { caseId: string }) {
  const [state, setState] = useState<{ data?: Breakdown; error?: string }>({});
  const [filter, setFilter] = useState<ReplyFilter>("all");
  const [opening, setOpening] = useState<string>();
  const [openError, setOpenError] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    setState({});
    loadBreakdown(caseId, controller.signal)
      .then((data) => setState({ data }))
      .catch((error) => {
        if (!controller.signal.aborted)
          setState({ error: error instanceof Error ? error.message : "Döküm yüklenemedi." });
      });
    return () => controller.abort();
  }, [caseId]);

  const open = async (file: FileRef) => {
    if (opening) return;
    setOpening(file.id);
    setOpenError("");
    try {
      if (!file.storagePath) throw new Error("Bu belgenin dosyası kayıtlı değil.");
      const response = await db.storage.from("case-files").download(file.storagePath);
      if (response.error || !response.data)
        throw new Error(response.error?.message || "Dosya indirilemedi.");
      const url = URL.createObjectURL(response.data);
      const anchor = window.document.createElement("a");
      anchor.href = url;
      anchor.download = file.fileName;
      window.document.body.appendChild(anchor);
      try {
        anchor.click();
      } finally {
        anchor.remove();
        window.setTimeout(() => URL.revokeObjectURL(url), 1000);
      }
    } catch (error) {
      setOpenError(error instanceof Error ? error.message : "Dosya indirilemedi.");
    } finally {
      setOpening(undefined);
    }
  };

  if (state.error)
    return (
      <p role="alert" className="text-sm text-destructive">
        {state.error}
      </p>
    );
  if (!state.data)
    return (
      <p role="status" className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" /> İcra dosyası dökümü yükleniyor…
      </p>
    );

  const { replies, receipts, replyGroupLabels } = state.data;
  const visible = filterReplies(replies.items, filter);
  const counts = receiptCounts(receipts);
  const openButton = (file: FileRef, label: string) => (
    <button
      key={file.id}
      type="button"
      disabled={Boolean(opening)}
      onClick={() => void open(file)}
      className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-1 text-xs hover:bg-secondary disabled:opacity-50"
    >
      {opening === file.id ? (
        <Loader2 className="h-3 w-3 animate-spin" />
      ) : (
        <Download className="h-3 w-3" />
      )}
      {label}
    </button>
  );

  return (
    <div className="space-y-8" data-testid="execution-breakdown">
      <ExecutionOverview overview={state.data.overview} caseId={caseId} />

      {openError && (
        <p role="alert" className="text-sm text-destructive">
          {openError}
        </p>
      )}

      <section aria-labelledby="execution-replies-title">
        <h3 id="execution-replies-title" className="text-base font-semibold">
          Haciz ihbarnamesi cevapları
        </h3>
        <p className="mt-1 text-sm text-muted-foreground" data-testid="execution-replies-headline">
          {replyHeadline(replies)}
        </p>
        {replies.items.length > 0 && (
          <>
            <p className="mt-2 rounded-lg border border-amber-500/30 bg-amber-500/5 p-2 text-xs text-amber-800 dark:text-amber-300">
              Bu liste cevabın sonucunu söylemez. Yazıda ne geçtiğine göre sıralar: içinde tutar
              geçenler üstte, yalnız “bulunmamaktadır” türü ifade geçenler altta. Alıntılar yazıdan
              aynen alınmıştır; karar vermeden önce yazının kendisini açıp okuyun.
            </p>
            <div
              className="mt-3 flex flex-wrap gap-2 text-xs"
              role="group"
              aria-label="Cevap süzgeci"
            >
              <button
                type="button"
                aria-pressed={filter === "all"}
                onClick={() => setFilter("all")}
                className={cn(
                  "rounded-full border px-3 py-1.5 font-medium",
                  filter === "all"
                    ? "border-primary bg-primary text-primary-foreground"
                    : "border-border bg-card text-muted-foreground hover:text-foreground",
                )}
              >
                Tümü {replies.items.length}
              </button>
              {REPLY_GROUPS.filter((group) => replies.groups[group]).map((group) => (
                <button
                  key={group}
                  type="button"
                  aria-pressed={filter === group}
                  onClick={() => setFilter(group)}
                  className={cn(
                    "rounded-full border px-3 py-1.5 font-medium",
                    filter === group
                      ? "border-primary bg-primary text-primary-foreground"
                      : "border-border bg-card text-muted-foreground hover:text-foreground",
                  )}
                >
                  {replyGroupLabels[group]} {replies.groups[group]}
                </button>
              ))}
            </div>
            <ul
              className="mt-3 divide-y divide-border rounded-xl border border-border"
              data-testid="execution-replies"
            >
              {visible.map((item) => (
                <li key={item.documents[0].id} className="p-3 sm:p-4" data-group={item.group}>
                  <div className="flex flex-wrap items-center gap-2 text-sm">
                    <span className="font-medium">{item.sender ?? "Gönderen okunamadı"}</span>
                    <span className="text-xs text-muted-foreground">{dateTr(item.date)}</span>
                    <span
                      className={cn(
                        "rounded-full border px-2 py-0.5 text-xs",
                        GROUP_TONE[item.group],
                      )}
                    >
                      {item.readable ? replyGroupLabels[item.group] : "Metni okunamadı"}
                    </span>
                    {item.amounts.length > 0 && (
                      <span className="text-xs font-medium">{item.amounts.join(" · ")}</span>
                    )}
                  </div>
                  {item.quotes.map((quote) => (
                    <blockquote
                      key={quote}
                      className="mt-2 border-l-2 border-border pl-3 text-sm text-muted-foreground"
                    >
                      “{quote}”
                    </blockquote>
                  ))}
                  <div className="mt-2 flex flex-wrap gap-2">
                    {item.documents.map((file, index) =>
                      openButton(file, index === 0 ? "Yazıyı aç" : `${index + 1}. kopya`),
                    )}
                  </div>
                </li>
              ))}
            </ul>
          </>
        )}
      </section>

      <section aria-labelledby="execution-receipts-title">
        <h3 id="execution-receipts-title" className="text-base font-semibold">
          Makbuz dökümü
        </h3>
        {receipts.length === 0 ? (
          <p className="mt-1 text-sm text-muted-foreground">
            Bu dosyada tahsilat, masraf ya da reddiyat makbuzu yok.
          </p>
        ) : (
          <>
            <p
              className="mt-1 text-sm text-muted-foreground"
              data-testid="execution-receipts-headline"
            >
              {counts
                .map((item) => `${item.label} ${item.count} (tek tutarı okunan ${item.single})`)
                .join(" · ")}
            </p>
            <p className="mt-1 text-xs text-muted-foreground">
              Tutarlar makbuz metninden okunur; toplanmaz. Bir makbuzda birden çok farklı tutar
              varsa hangisinin makbuz tutarı olduğu bilinemez, hepsi yazıldığı gibi gösterilir.
            </p>
            <div className="mt-3 overflow-x-auto rounded-xl border border-border">
              <table className="w-full text-sm" data-testid="execution-receipts">
                <thead>
                  <tr className="bg-secondary/40 text-left text-xs uppercase tracking-wider text-muted-foreground">
                    <th className="px-3 py-2 font-medium">Tarih</th>
                    <th className="px-3 py-2 font-medium">Tür</th>
                    <th className="px-3 py-2 font-medium">Metindeki tutar</th>
                    <th className="px-3 py-2 font-medium">Belge</th>
                  </tr>
                </thead>
                <tbody>
                  {receipts.map((item) => (
                    <tr key={item.document.id} className="border-t border-border">
                      <td className="whitespace-nowrap px-3 py-2">{dateTr(item.date)}</td>
                      <td className="px-3 py-2">{item.label}</td>
                      <td className={cn("px-3 py-2", !item.amount && "text-muted-foreground")}>
                        {receiptCell(item)}
                      </td>
                      <td className="px-3 py-2">{openButton(item.document, "Aç")}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </section>
    </div>
  );
}
