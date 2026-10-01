import { useCallback, useEffect, useRef, useState } from "react";
import { Loader2, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { LegalChat } from "@/components/LegalChat";
import { getCaseDocumentIndex, reindexCaseDocument } from "@/lib/ai-api";
import {
  canReindex,
  documentStatusLabel,
  type CaseDocumentIndex,
  type CaseDocumentIndexItem,
} from "@/lib/document-scope";

const EXAMPLES = [
  "Bu dosyadaki belgelere göre taraflar kimlerdir ve dava konusu nedir?",
  "Bilirkişi raporunda hangi tutarlar hesaplanmış?",
  "Dilekçede hangi talepler yer alıyor?",
  "Duruşma hangi tarihte yapılacak?",
];

const INTRO =
  "Sorular bu davaya bağlı belgelerde ve hukuk kaynaklarında aranır. Belgelerdeki ifadeler " +
  '"kullanıcı belgesi" olarak etiketlenir; resmî kaynak olarak sunulmaz.';

const STATUS_POLL_MS = 5000;
const MAX_STATUS_POLLS = 60; // en çok ~5 dakika

function StatusBadge({ item }: { item: CaseDocumentIndexItem }) {
  const tone =
    item.status === "ready"
      ? "bg-emerald-500/15 text-emerald-700 dark:text-emerald-400"
      : item.status === "failed"
        ? "bg-red-500/15 text-red-700 dark:text-red-400"
        : "bg-amber-500/15 text-amber-700 dark:text-amber-400";
  return (
    <span className={`rounded px-1.5 py-0.5 text-[11px] font-medium ${tone}`}>
      {documentStatusLabel(item)}
    </span>
  );
}

export function CaseDocumentAsk({ caseId }: { caseId: string }) {
  const [index, setIndex] = useState<CaseDocumentIndex>();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState<string>();
  const active = useRef(true);

  const load = useCallback(async () => {
    try {
      const next = await getCaseDocumentIndex(caseId);
      if (active.current) {
        setIndex(next);
        setError("");
      }
    } catch (e) {
      if (active.current) setError(e instanceof Error ? e.message : "Belge durumları alınamadı.");
    }
  }, [caseId]);

  useEffect(() => {
    active.current = true;
    setIndex(undefined);
    void load();
    return () => {
      active.current = false;
    };
  }, [load]);

  // OCR gerektiren belgeler arka planda işlenir (dakikalar sürebilir): bekleyen belge varken durum
  // kendiliğinden yenilenir; bir üst sınırdan sonra durur (süren iş yoksa sonsuza dek sorgulamaz).
  const hasPending = !!index?.documents.some(
    (item) => item.status !== "ready" && item.status !== "failed",
  );
  useEffect(() => {
    if (!hasPending) return;
    let polls = 0;
    const timer = window.setInterval(() => {
      if (++polls > MAX_STATUS_POLLS) return window.clearInterval(timer);
      void load();
    }, STATUS_POLL_MS);
    return () => window.clearInterval(timer);
  }, [hasPending, load]);

  const reindex = async (item: CaseDocumentIndexItem) => {
    if (busy) return;
    setBusy(item.id);
    try {
      await reindexCaseDocument(caseId, item.id);
      // İşlem arka planda yürür; kısa süre sonra durum yeniden okunur.
      window.setTimeout(() => void load(), 2500);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Belge yeniden işlenemedi.");
    } finally {
      setBusy(undefined);
    }
  };

  const unsearchable = index ? index.total - index.ready : 0;

  return (
    <div className="space-y-4">
      <section
        aria-label="Belge durumları"
        className="rounded-xl border border-border p-4 space-y-3"
      >
        <div className="flex items-center justify-between gap-2">
          <h3 className="text-sm font-semibold">Belgelerin aranabilirlik durumu</h3>
          <Button variant="outline" size="sm" onClick={() => void load()}>
            <RefreshCw className="h-3.5 w-3.5" /> Yenile
          </Button>
        </div>
        {!index && !error && (
          <p role="status" className="text-sm text-muted-foreground flex items-center gap-2">
            <Loader2 className="h-4 w-4 animate-spin" /> Belge durumları yükleniyor…
          </p>
        )}
        {error && (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}
        {index && index.total === 0 && (
          <p className="text-sm text-muted-foreground">
            Bu davaya bağlı belge yok. Evraklar sekmesinden belge yükleyin ya da UYAP'tan aktarılan
            bir belgeyi bu davaya bağlayın.
          </p>
        )}
        {index && index.total > 0 && (
          <>
            <p className="text-xs text-muted-foreground">
              {index.total} belgeden {index.ready} tanesi aranabiliyor.
              {unsearchable > 0 &&
                ` ${unsearchable} belge cevaba katılmaz; nedeni aşağıda yazıyor.`}
            </p>
            <ul className="divide-y divide-border text-sm">
              {index.documents.map((item) => (
                <li key={item.id} className="py-2 flex flex-wrap items-center gap-2">
                  <span className="break-all">{item.file_name}</span>
                  <StatusBadge item={item} />
                  {item.ocr && (
                    <span
                      title="Metin taranmış görüntüden OCR ile okundu; okuma hataları olabilir."
                      className="rounded px-1.5 py-0.5 text-[11px] font-medium bg-sky-500/15 text-sky-700 dark:text-sky-400"
                    >
                      OCR ile okundu
                    </span>
                  )}
                  {item.status === "failed" && item.error && (
                    <span className="text-xs text-muted-foreground">{item.error}</span>
                  )}
                  {canReindex(item) && (
                    <Button
                      variant="outline"
                      size="sm"
                      className="ml-auto"
                      disabled={busy === item.id}
                      onClick={() => void reindex(item)}
                    >
                      {busy === item.id ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      ) : (
                        "Yeniden işle"
                      )}
                    </Button>
                  )}
                </li>
              ))}
            </ul>
          </>
        )}
      </section>

      <LegalChat
        key={caseId}
        title="Dava belgeleriyle sohbet"
        examples={EXAMPLES}
        intro={INTRO}
        caseId={caseId}
        compact
        onAnswered={() => void load()}
      />
    </div>
  );
}
