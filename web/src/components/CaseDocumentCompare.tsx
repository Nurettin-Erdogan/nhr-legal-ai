import { useEffect, useRef, useState } from "react";
import { ArrowRight, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { inMemoryAccessToken } from "@/lib/auth-api";
import { getCaseDocumentIndex } from "@/lib/ai-api";
import { documentStatusLabel, type CaseDocumentIndexItem } from "@/lib/document-scope";
import {
  CompareError,
  compareDocuments,
  describeCounts,
  foldBlocks,
  hasDifferences,
  type CompareResult,
  type FoldedItem,
} from "@/lib/document-compare";

function Redline({ words, side }: { words: Extract<FoldedItem, { kind: "changed" }>["words"]; side: "left" | "right" }) {
  // Sol sütun silinenleri, sağ sütun eklenenleri işaretler; ikisinde de değişmeyen sözcükler düz görünür.
  return (
    <>
      {words
        .filter((piece) => piece.op === "equal" || (side === "left" ? piece.op === "delete" : piece.op === "insert"))
        .map((piece, index) =>
          piece.op === "equal" ? (
            <span key={index}>{piece.text} </span>
          ) : piece.op === "delete" ? (
            <del key={index} className="rounded bg-red-500/15 px-0.5 text-red-800 dark:text-red-300">
              {piece.text}{" "}
            </del>
          ) : (
            <ins key={index} className="rounded bg-emerald-500/15 px-0.5 no-underline text-emerald-800 dark:text-emerald-300">
              {piece.text}{" "}
            </ins>
          ),
        )}
    </>
  );
}

function Item({ item, leftName, rightName }: { item: FoldedItem; leftName: string; rightName: string }) {
  const [open, setOpen] = useState(false);
  if (item.kind === "equal") {
    return (
      <div className="space-y-1 text-sm text-muted-foreground" data-testid="diff-equal">
        {item.units.map((unit, index) => (
          <p key={index}>{unit}</p>
        ))}
      </div>
    );
  }
  if (item.kind === "fold") {
    return open ? (
      <div className="space-y-1 text-sm text-muted-foreground" data-testid="diff-equal">
        {item.units.map((unit, index) => (
          <p key={index}>{unit}</p>
        ))}
        <button type="button" className="text-xs underline" onClick={() => setOpen(false)}>
          Aynı bölümü gizle
        </button>
      </div>
    ) : (
      <button type="button" className="w-full rounded-md border border-dashed py-1 text-xs text-muted-foreground hover:bg-accent" onClick={() => setOpen(true)} data-testid="diff-fold">
        {item.units.length} aynı cümle gizlendi · göster
      </button>
    );
  }
  if (item.kind === "removed") {
    return (
      <div className="rounded-lg border border-red-500/30 bg-red-500/5 p-3 text-sm" data-testid="diff-removed">
        <p className="mb-1 text-xs font-medium text-red-700 dark:text-red-300">Silindi · yalnız “{leftName}” içinde var</p>
        <p>{item.text}</p>
      </div>
    );
  }
  if (item.kind === "added") {
    return (
      <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/5 p-3 text-sm" data-testid="diff-added">
        <p className="mb-1 text-xs font-medium text-emerald-700 dark:text-emerald-300">Eklendi · yalnız “{rightName}” içinde var</p>
        <p>{item.text}</p>
      </div>
    );
  }
  return (
    <div className="grid gap-2 rounded-lg border border-amber-500/30 bg-amber-500/5 p-3 text-sm sm:grid-cols-2" data-testid="diff-changed">
      <div>
        <p className="mb-1 text-xs font-medium text-muted-foreground">{leftName}</p>
        <p>
          <Redline words={item.words} side="left" />
        </p>
      </div>
      <div>
        <p className="mb-1 text-xs font-medium text-muted-foreground">{rightName}</p>
        <p>
          <Redline words={item.words} side="right" />
        </p>
      </div>
    </div>
  );
}

/**
 * "Belge Kıyasla": davaya bağlı iki belgenin cümle ve sözcük düzeyinde farkı (ör. sözleşmenin iki sürümü).
 * Sonuç yapay zekâ çıktısı değildir; yalnız metin farkıdır ve hukuki değerlendirme sayılmaz.
 */
export function CaseDocumentCompare({ caseId }: { caseId: string }) {
  const [documents, setDocuments] = useState<CaseDocumentIndexItem[]>();
  const [loadError, setLoadError] = useState("");
  const [left, setLeft] = useState("");
  const [right, setRight] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<CompareResult>();
  const [showEqual, setShowEqual] = useState(false);
  const controller = useRef<AbortController | null>(null);

  useEffect(() => {
    let active = true;
    getCaseDocumentIndex(caseId)
      .then((index) => {
        if (active) setDocuments(index.documents);
      })
      .catch((e) => {
        if (active) setLoadError(e instanceof Error ? e.message : "Belge listesi alınamadı.");
      });
    return () => {
      active = false;
      controller.current?.abort();
    };
  }, [caseId]);

  const ready = (documents ?? []).filter((item) => item.status === "ready");
  const unavailable = (documents ?? []).filter((item) => item.status !== "ready");

  const run = async () => {
    if (!left || !right || left === right || busy) return;
    controller.current?.abort();
    const abort = new AbortController();
    controller.current = abort;
    setBusy(true);
    setError("");
    setResult(undefined);
    try {
      const next = await compareDocuments(caseId, left, right, { token: inMemoryAccessToken(), signal: abort.signal });
      if (!abort.signal.aborted) setResult(next);
    } catch (e) {
      if (!abort.signal.aborted) setError(e instanceof CompareError || e instanceof Error ? e.message : "Karşılaştırma tamamlanamadı.");
    } finally {
      if (!abort.signal.aborted) setBusy(false);
    }
  };

  const items = result ? foldBlocks(result.blocks, showEqual ? Number.MAX_SAFE_INTEGER : 1) : [];

  return (
    <div className="space-y-4" data-testid="case-document-compare">
      <p className="text-sm text-muted-foreground">
        Davaya bağlı iki belgenin metin farkını gösterir (ör. sözleşmenin iki sürümü). Bu bir yapay zekâ yorumu ya da hukuki değerlendirme değildir; yalnız iki metnin hangi
        cümlelerde ayrıldığını işaretler. Rakamlar ve noktalama farkı da değişiklik sayılır.
      </p>
      {loadError && (
        <p role="alert" className="text-sm text-destructive">
          {loadError}
        </p>
      )}
      {!documents && !loadError && (
        <p role="status" className="text-sm text-muted-foreground">
          Belgeler yükleniyor…
        </p>
      )}
      {documents && ready.length < 2 && (
        <p className="rounded-lg border p-3 text-sm text-muted-foreground" role="status">
          Karşılaştırmak için davaya bağlı en az iki okunmuş (aranabilir) belge gerekir; şu an {ready.length} tane var.
          {unavailable.length > 0 && ` ${unavailable.length} belge henüz hazır değil: ${unavailable.map((item) => `${item.file_name} (${documentStatusLabel(item)})`).join(", ")}.`}
        </p>
      )}
      {ready.length >= 2 && (
        <div className="flex flex-col gap-2 sm:flex-row sm:items-end">
          <label className="flex-1 text-xs">
            Belge A (önceki / referans)
            <select aria-label="Belge A" className="mt-1 h-9 w-full rounded-md border bg-background px-2 text-sm" value={left} onChange={(event) => setLeft(event.target.value)}>
              <option value="">Seçin…</option>
              {ready.map((item) => (
                <option key={item.id} value={item.id} disabled={item.id === right}>
                  {item.file_name}
                  {item.ocr ? " (OCR)" : ""}
                </option>
              ))}
            </select>
          </label>
          <ArrowRight className="hidden h-4 w-4 shrink-0 self-center text-muted-foreground sm:block" />
          <label className="flex-1 text-xs">
            Belge B (sonraki / karşılaştırılan)
            <select aria-label="Belge B" className="mt-1 h-9 w-full rounded-md border bg-background px-2 text-sm" value={right} onChange={(event) => setRight(event.target.value)}>
              <option value="">Seçin…</option>
              {ready.map((item) => (
                <option key={item.id} value={item.id} disabled={item.id === left}>
                  {item.file_name}
                  {item.ocr ? " (OCR)" : ""}
                </option>
              ))}
            </select>
          </label>
          <Button onClick={() => void run()} disabled={!left || !right || left === right || busy}>
            {busy ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
            Karşılaştır
          </Button>
        </div>
      )}
      {unavailable.length > 0 && ready.length >= 2 && (
        <p className="text-xs text-muted-foreground">
          Listede olmayan belgeler okunamadı ya da işlenmedi: {unavailable.map((item) => item.file_name).join(", ")}.
        </p>
      )}
      {error && (
        <div role="alert" className="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm">
          {error}
        </div>
      )}
      {result && (
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-2 text-sm" role="status" data-testid="compare-summary">
            <span className="font-medium">{describeCounts(result.counts)}</span>
            <span className="text-muted-foreground">Aynı cümle oranı: %{Math.round(result.similarity * 100)}</span>
          </div>
          {(result.left.ocr || result.right.ocr) && (
            <p className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-2 text-xs text-amber-800 dark:text-amber-300" data-testid="compare-ocr">
              {[result.left.ocr ? result.left.fileName : "", result.right.ocr ? result.right.fileName : ""].filter(Boolean).join(" ve ")} metni OCR ile okundu: bazı farklar okuma
              hatasından kaynaklanabilir. Önemli bir değişikliği özgün belgeden doğrulayın.
            </p>
          )}
          {hasDifferences(result.counts) && result.counts.equal > 0 && (
            <label className="flex items-center gap-1.5 text-xs">
              <input type="checkbox" checked={showEqual} onChange={(event) => setShowEqual(event.target.checked)} />
              Aynı bölümleri de göster
            </label>
          )}
          <div className="space-y-2">
            {items.map((item, index) => (
              <Item key={index} item={item} leftName={result.left.fileName} rightName={result.right.fileName} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
