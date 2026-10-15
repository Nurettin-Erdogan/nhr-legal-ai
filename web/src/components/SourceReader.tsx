import { useEffect, useState, type ReactNode } from "react";
import { loadSourceDetail, type SourceDetail } from "@/lib/decision-search";
import { isRawPortalUrl, isSourceId, safeSourceUrl, sourceSiteLabel } from "@/lib/source-reader";
import { verificationTag } from "@/lib/source-label";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

export interface SourceReaderProps {
  sourceId?: string | null;
  reference: string;
  sourceUrl?: string | null;
  excerpt?: string | null;
  children?: ReactNode;
  className?: string;
}

/** Public legal corpus only. User-document IDs must never be routed through this reader. */
export function SourceReader(props: SourceReaderProps) {
  // A changed source unmounts the old reader and cannot expose its late response.
  return <Reader key={props.sourceId ?? props.reference} {...props} />;
}

function Reader({
  sourceId,
  reference,
  sourceUrl,
  excerpt,
  children = "Kaynağı aç",
  className,
}: SourceReaderProps) {
  const [open, setOpen] = useState(false);
  const [detail, setDetail] = useState<SourceDetail | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    setDetail(null);
    setError("");
    setBusy(false);
    if (!open || !isSourceId(sourceId)) return;
    const controller = new AbortController();
    let active = true;
    setBusy(true);
    const timeout = setTimeout(() => {
      if (!active) return;
      active = false;
      controller.abort();
      setBusy(false);
      setError("Kaynak metni zamanında alınamadı. Yeniden deneyebilirsiniz.");
    }, 20000);
    void loadSourceDetail(sourceId, controller.signal)
      .then((result) => {
        if (active) setDetail(result);
      })
      .catch((reason: unknown) => {
        if (active) setError(reason instanceof Error ? reason.message : "Kaynak metni alınamadı.");
      })
      .finally(() => {
        clearTimeout(timeout);
        if (active) setBusy(false);
      });
    return () => {
      active = false;
      clearTimeout(timeout);
      controller.abort();
    };
  }, [open, sourceId, retry]);
  const external = safeSourceUrl(detail ? detail.sourceUrl : sourceUrl);
  const tag = detail && verificationTag(detail.verification);
  return (
    <>
      <button
        type="button"
        className={className ?? "text-left underline underline-offset-2 text-primary"}
        onClick={() => setOpen(true)}
        data-testid="source-reader-trigger"
      >
        {children}
      </button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="w-[calc(100%_-_2rem)] max-w-4xl max-h-[90dvh] flex flex-col overflow-hidden">
          <DialogHeader className="shrink-0 pr-6">
            <DialogTitle className="break-words leading-snug">
              {detail?.title || reference}
            </DialogTitle>
            <DialogDescription>Kaynak metni · Yapay zekâ özeti değildir.</DialogDescription>
          </DialogHeader>
          {tag && (
            <p className="text-xs shrink-0" data-testid="reader-verification">
              {tag.label}
            </p>
          )}
          {detail?.isCurrent === false && (
            <p role="note" className="text-sm text-amber-700 dark:text-amber-400">
              Bu kayıt güncel sürüm değil; tarihsel metin gösteriliyor.
            </p>
          )}
          <div
            className="min-h-0 flex-1 overflow-y-auto overscroll-contain rounded-lg border p-4 text-sm leading-7"
            data-testid="source-reader-body"
            aria-busy={busy}
          >
            {busy && <p role="status">Kaynak metni yükleniyor…</p>}
            {error && (
              <div role="alert">
                <p>{error}</p>
                <Button
                  className="mt-3"
                  variant="outline"
                  onClick={() => setRetry((value) => value + 1)}
                >
                  Yeniden dene
                </Button>
              </div>
            )}
            {!busy && !error && !isSourceId(sourceId) && (
              <p role="note">Bu eski atıfta kayıt kimliği bulunmadığından tam metin açılamıyor.</p>
            )}
            {!busy &&
              !error &&
              detail &&
              (detail.rawText ? (
                <p className="whitespace-pre-wrap break-words" data-testid="source-reader-text">
                  {detail.rawText}
                </p>
              ) : detail.chunks.length ? (
                <>
                  <p role="note" className="mb-3 text-muted-foreground">
                    Kaydın ana metni yok. Aşağıda kayıtlı metin parçaları gösteriliyor; tam metin
                    olduğu doğrulanmadı.
                  </p>
                  {detail.chunks.map((chunk, index) => (
                    <p key={index} className="mb-4 whitespace-pre-wrap break-words">
                      {chunk}
                    </p>
                  ))}
                </>
              ) : (
                <p role="note">Bu kayıt için okunabilir metin bulunamadı.</p>
              ))}
            {!busy && !detail && excerpt && (
              <div className="mt-3">
                <p className="font-medium">Atıftaki alıntı (tam metin değil)</p>
                <p className="whitespace-pre-wrap break-words">{excerpt}</p>
              </div>
            )}
          </div>
          <div className="shrink-0 space-y-2 text-xs">
            {external && (
              <a
                href={external}
                target="_blank"
                rel="noopener noreferrer"
                className="underline underline-offset-2"
                data-testid="source-reader-external"
              >
                {sourceSiteLabel(external)}
              </a>
            )}
            {external && isRawPortalUrl(external) && (
              <p className="text-muted-foreground">
                Resmî portalın bu bağlantısı ham XML/HTML gösterebilir. Okunabilir kayıt
                yukarıdadır.
              </p>
            )}
            <Button variant="outline" onClick={() => setOpen(false)}>
              Kapat
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
