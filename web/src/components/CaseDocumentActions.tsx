import { useEffect, useRef, useState } from "react";
import {
  linkCaseDocument,
  listUnlinkedDocuments,
  uploadCaseDocument,
  type UnlinkedDocument,
} from "../lib/case-documents";

const button =
  "rounded-md border border-border px-3 py-2 text-sm hover:bg-secondary disabled:opacity-50";
export function CaseDocumentActions({
  caseId,
  clientId,
  onSaved,
}: {
  caseId: string;
  clientId: string | null;
  onSaved: () => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [open, setOpen] = useState(false);
  const [term, setTerm] = useState("");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(0);
  const [list, setList] = useState<{ rows: UnlinkedDocument[]; hasMore: boolean }>();
  const [listError, setListError] = useState("");
  const [selected, setSelected] = useState("");
  const mounted = useRef(false);
  const locked = useRef(false);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  useEffect(() => {
    if (!open) return;
    let active = true;
    setList(undefined);
    setListError("");
    setSelected("");
    listUnlinkedDocuments(search, page)
      .then((value) => {
        if (active) setList(value);
      })
      .catch((e) => {
        if (active) setListError(e instanceof Error ? e.message : "Liste yüklenemedi.");
      });
    return () => {
      active = false;
    };
  }, [open, search, page]);
  async function run(action: () => Promise<unknown>) {
    if (locked.current) return;
    locked.current = true;
    setBusy(true);
    setError("");
    try {
      await action();
      if (mounted.current) onSaved();
    } catch (e) {
      if (mounted.current) setError(e instanceof Error ? e.message : "Belge kaydedilemedi.");
    } finally {
      locked.current = false;
      if (mounted.current) setBusy(false);
    }
  }
  return (
    <div className="mb-5 rounded-xl border border-border p-4 space-y-4">
      <p className="text-sm text-muted-foreground">
        Belge bu davaya kaydedilir. Yükleme otomatik OCR, metin analizi veya RAG indeksleme yapmaz.
      </p>
      <form
        className="flex flex-wrap items-end gap-3"
        onSubmit={(e) => {
          e.preventDefault();
          if (file) void run(() => uploadCaseDocument(caseId, file));
        }}
      >
        <label className="text-sm">
          Yeni evrak (en fazla 50 MB)
          <input
            aria-label="Yüklenecek evrak"
            type="file"
            disabled={busy}
            className="block mt-2 max-w-full"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
        </label>
        <button className={button} disabled={busy || !file}>
          Davaya yükle
        </button>
      </form>
      <button
        type="button"
        className={button}
        disabled={busy}
        aria-expanded={open}
        onClick={() => setOpen(!open)}
      >
        Mevcut belgeyi bağla
      </button>
      {open && (
        <div className="space-y-3">
          <p className="text-xs text-muted-foreground">
            Yalnız herhangi bir davaya bağlı olmayan kendi belgeleriniz listelenir. Başka davanın
            belgesi taşınmaz.
          </p>
          <form
            className="flex flex-wrap gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              setSearch(term);
              setPage(0);
            }}
          >
            <input
              aria-label="Bağlanacak belge adı"
              maxLength={100}
              value={term}
              disabled={busy}
              onChange={(e) => setTerm(e.target.value)}
              className="rounded border border-border bg-background p-2 text-sm"
              placeholder="Dosya adıyla ara"
            />
            <button className={button} disabled={busy}>
              Ara
            </button>
          </form>
          {listError && (
            <p role="alert" className="text-destructive text-sm">
              {listError}
            </p>
          )}
          {!list && !listError && <p role="status">Belgeler yükleniyor…</p>}
          {list && (
            <>
              {!list.rows.length ? (
                <p className="text-sm">Bağlanabilecek belge bulunamadı.</p>
              ) : (
                <>
                  <label className="block text-sm">
                    Belge seç
                    <select
                      aria-label="Bağlanacak belge"
                      value={selected}
                      disabled={busy}
                      onChange={(e) => setSelected(e.target.value)}
                      className="block w-full border border-border bg-background rounded p-2 mt-1"
                    >
                      <option value="">Belge seçin</option>
                      {list.rows.map((d) => (
                        <option
                          key={d.id}
                          value={d.id}
                          disabled={!!d.client_id && d.client_id !== clientId}
                        >
                          {d.file_name}
                          {d.client_id && d.client_id !== clientId ? " (müvekkil eşleşmiyor)" : ""}
                        </option>
                      ))}
                    </select>
                  </label>
                  <button
                    type="button"
                    className={button}
                    disabled={busy || !selected}
                    onClick={() => void run(() => linkCaseDocument(caseId, selected))}
                  >
                    Seçili belgeyi bu davaya bağla
                  </button>
                </>
              )}
              <div className="flex gap-2 items-center text-sm">
                <button
                  type="button"
                  className={button}
                  disabled={busy || page === 0}
                  onClick={() => setPage((p) => p - 1)}
                >
                  Önceki
                </button>
                <span>Sayfa {page + 1}</span>
                <button
                  type="button"
                  className={button}
                  disabled={busy || !list.hasMore}
                  onClick={() => setPage((p) => p + 1)}
                >
                  Sonraki
                </button>
              </div>
            </>
          )}
        </div>
      )}
      {busy && (
        <p role="status" className="text-sm">
          Belge kaydediliyor…
        </p>
      )}
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
    </div>
  );
}
