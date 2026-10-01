import { useCallback, useEffect, useRef, useState } from "react";
import { Loader2, RotateCcw, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  deleteDocumentForever,
  describeRetention,
  listTrash,
  permanentDeleteWarning,
  restoreDocument,
  type TrashListing,
  type TrashedDocument,
} from "@/lib/document-trash";

/** Çöp kutusu: geri yükle ya da kalıcı sil. `caseId` verilirse yalnız o davanın belgeleri. */
export function DocumentTrash({
  caseId,
  refreshKey = 0,
  onChanged,
}: {
  caseId?: string;
  /** Üst bileşen bir belgeyi çöpe taşıdığında artırılır; liste yenilenir. */
  refreshKey?: number;
  /** Geri yükleme ya da kalıcı silme sonrası (üst listeyi yenilemek için). */
  onChanged?: () => void;
}) {
  const [listing, setListing] = useState<TrashListing>();
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState<string>();
  const active = useRef(true);

  const load = useCallback(async () => {
    try {
      const next = await listTrash(caseId);
      if (active.current) {
        setListing(next);
        setError("");
      }
    } catch (e) {
      if (active.current) setError(e instanceof Error ? e.message : "Çöp kutusu okunamadı.");
    }
  }, [caseId]);

  useEffect(() => {
    active.current = true;
    void load();
    return () => {
      active.current = false;
    };
  }, [load, refreshKey]);

  const restore = async (item: TrashedDocument) => {
    if (busy) return;
    setBusy(item.id);
    setNotice("");
    try {
      await restoreDocument(item.id);
      setNotice(`"${item.file_name}" geri yüklendi.`);
      await load();
      onChanged?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Belge geri yüklenemedi.");
    } finally {
      setBusy(undefined);
    }
  };

  const removeForever = async (item: TrashedDocument) => {
    if (busy || !window.confirm(permanentDeleteWarning(item))) return;
    setBusy(item.id);
    setNotice("");
    try {
      const result = await deleteDocumentForever(item.id);
      setNotice(
        result.redacted_answers > 0
          ? `"${item.file_name}" kalıcı silindi; ona dayanan ${result.redacted_answers} sohbet cevabı kaldırıldı.`
          : `"${item.file_name}" kalıcı silindi.`,
      );
      await load();
      onChanged?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Belge silinemedi.");
    } finally {
      setBusy(undefined);
    }
  };

  const documents = listing?.documents ?? [];
  return (
    <section aria-label="Çöp kutusu" className="mt-6 rounded-xl border border-border p-4 space-y-3">
      <div className="flex items-center gap-2">
        <Trash2 className="h-4 w-4 text-muted-foreground" />
        <h3 className="text-sm font-semibold">Çöp kutusu</h3>
        {documents.length > 0 && (
          <span className="text-xs text-muted-foreground">({documents.length})</span>
        )}
      </div>
      <p className="text-xs text-muted-foreground">
        Çöpe taşınan belgeler aranmaz ve listelerde görünmez. {listing?.retention_days ?? 30} gün
        içinde geri yükleyebilirsiniz; süre dolunca kalıcı silinir.
      </p>
      {!listing && !error && (
        <p role="status" className="text-sm text-muted-foreground flex items-center gap-2">
          <Loader2 className="h-4 w-4 animate-spin" /> Yükleniyor…
        </p>
      )}
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
      {notice && (
        <p role="status" className="text-sm">
          {notice}
        </p>
      )}
      {listing && documents.length === 0 && (
        <p className="text-sm text-muted-foreground">Çöp kutusu boş.</p>
      )}
      {documents.length > 0 && (
        <ul className="divide-y divide-border text-sm">
          {documents.map((item) => (
            <li key={item.id} className="py-2 flex flex-wrap items-center gap-2">
              <div className="min-w-0">
                <p className="break-all">{item.file_name}</p>
                <p className="text-xs text-muted-foreground">
                  {describeRetention(item)}
                  {item.cited_answers > 0 &&
                    ` · ${item.cited_answers} sohbet cevabı bu belgeye dayanıyor`}
                </p>
              </div>
              <div className="ml-auto flex gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  disabled={busy === item.id}
                  onClick={() => void restore(item)}
                >
                  <RotateCcw className="h-3.5 w-3.5" /> Geri yükle
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={busy === item.id}
                  onClick={() => void removeForever(item)}
                >
                  Kalıcı sil
                </Button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
