import { useEffect, useState } from "react";
import { db } from "@/lib/db";
import { useAuth } from "@/components/AuthContext";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { confirmAction } from "@/lib/confirmation";

const MAX_NOTE_CHARS = 20000;

/**
 * Dava detayındaki "Notlar" sekmesi: notu yerinde düzenler. Önceden not eklemek için dava listesine dönüp "Düzenle" penceresini
 * açmak gerekiyordu; sekme yalnız okunur metindi.
 */
export function CaseNotesEditor({
  caseId,
  initial,
  onSaved,
}: {
  caseId: string;
  initial: string | null;
  onSaved: () => void;
}) {
  const [value, setValue] = useState(initial ?? "");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [failed, setFailed] = useState(false);

  useEffect(() => setValue(initial ?? ""), [caseId, initial]);

  const dirty = value.trim() !== (initial ?? "").trim();
  const save = async () => {
    setBusy(true);
    setMessage("");
    setFailed(false);
    const { error } = await db
      .from("cases")
      .update({ notes: value.trim() || null })
      .eq("id", caseId);
    setBusy(false);
    if (error) {
      setFailed(true);
      setMessage(error.message || "Not kaydedilemedi.");
      return;
    }
    setMessage("Not kaydedildi.");
    onSaved();
  };

  return (
    <div className="space-y-3" data-testid="case-notes-editor">
      <Textarea
        rows={8}
        maxLength={MAX_NOTE_CHARS}
        value={value}
        placeholder="Bu davayla ilgili notlarınızı yazın (görüşme, strateji, yapılacaklar…)."
        aria-label="Dava notları"
        onChange={(event) => setValue(event.target.value)}
      />
      <div className="flex flex-wrap items-center gap-3">
        <Button type="button" size="sm" disabled={busy || !dirty} onClick={() => void save()}>
          {busy ? "Kaydediliyor…" : "Notu kaydet"}
        </Button>
        {dirty && !busy && (
          <span className="text-xs text-muted-foreground">Kaydedilmemiş değişiklik var.</span>
        )}
        {message && (
          <span
            role={failed ? "alert" : "status"}
            className={`text-xs ${failed ? "text-destructive" : "text-emerald-700 dark:text-emerald-400"}`}
          >
            {message}
          </span>
        )}
      </div>
    </div>
  );
}

/** Dava detayındaki "Görevler" sekmesi: bu davaya bağlı görevi yerinde açar (başlık ve isteğe bağlı son tarih). */
export function CaseTaskComposer({ caseId, onSaved }: { caseId: string; onSaved: () => void }) {
  const { user } = useAuth();
  const [title, setTitle] = useState("");
  const [due, setDue] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [added, setAdded] = useState("");

  const add = async (event: React.FormEvent) => {
    event.preventDefault();
    setError("");
    setAdded("");
    const clean = title.trim();
    if (!clean) return setError("Görev başlığı gerekli.");
    if (!user?.id) return setError("Oturum bulunamadı.");
    setBusy(true);
    const { error: insertError } = await db.from("tasks").insert({
      owner_id: user.id,
      case_id: caseId,
      title: clean.slice(0, 200),
      priority: "medium",
      status: "todo",
      due_date: due ? new Date(due).toISOString() : null,
    });
    setBusy(false);
    if (insertError) return setError(insertError.message || "Görev eklenemedi.");
    setTitle("");
    setDue("");
    setAdded("Görev eklendi.");
    onSaved();
  };

  return (
    <form
      onSubmit={add}
      className="mb-4 flex flex-wrap items-end gap-2"
      data-testid="case-task-composer"
    >
      <label className="min-w-[200px] flex-1 space-y-1 text-xs text-muted-foreground">
        Yeni görev
        <Input
          value={title}
          maxLength={200}
          placeholder="Örn: Cevap dilekçesini hazırla"
          onChange={(event) => setTitle(event.target.value)}
        />
      </label>
      <label className="space-y-1 text-xs text-muted-foreground">
        Son tarih (isteğe bağlı)
        <Input type="datetime-local" value={due} onChange={(event) => setDue(event.target.value)} />
      </label>
      <Button type="submit" size="sm" disabled={busy}>
        {busy ? "Ekleniyor…" : "Görev ekle"}
      </Button>
      {error && (
        <p role="alert" className="basis-full text-xs text-destructive">
          {error}
        </p>
      )}
      {added && !error && (
        <p role="status" className="basis-full text-xs text-emerald-700 dark:text-emerald-400">
          {added}
        </p>
      )}
    </form>
  );
}

/** Görev satırındaki işlemler: tamamlandı olarak işaretle / yeniden aç ve sil (silmeden önce sorulur). */
export function CaseTaskActions({
  taskId,
  status,
  title,
  onChanged,
}: {
  taskId: string;
  status: string;
  title: string;
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const done = status === "done";

  const toggle = async () => {
    setBusy(true);
    setError("");
    const { error: updateError } = await db
      .from("tasks")
      .update({ status: done ? "todo" : "done" })
      .eq("id", taskId);
    setBusy(false);
    if (updateError) return setError(updateError.message || "Görev güncellenemedi.");
    onChanged();
  };

  const remove = async () => {
    const confirmed = await confirmAction({
      title: "Görev silinsin mi?",
      description: `"${title}" görevi kalıcı olarak silinir.`,
      confirmLabel: "Sil",
      cancelLabel: "Vazgeç",
    });
    if (!confirmed) return;
    setBusy(true);
    setError("");
    const { error: deleteError } = await db.from("tasks").delete().eq("id", taskId);
    setBusy(false);
    if (deleteError) return setError(deleteError.message || "Görev silinemedi.");
    onChanged();
  };

  return (
    <span className="mt-1 flex flex-wrap items-center gap-2">
      <Button
        type="button"
        size="sm"
        variant="outline"
        disabled={busy}
        onClick={() => void toggle()}
      >
        {done ? "Yeniden aç" : "Tamamlandı"}
      </Button>
      <Button type="button" size="sm" variant="ghost" disabled={busy} onClick={() => void remove()}>
        Sil
      </Button>
      {error && (
        <span role="alert" className="text-xs text-destructive">
          {error}
        </span>
      )}
    </span>
  );
}
