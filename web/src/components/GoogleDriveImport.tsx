import { useEffect, useState, useRef } from "react";
import { useAuth } from "@/components/AuthProvider";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import {
  loadIntegrationConfig,
  prepareDrivePicker,
  pickDriveFiles,
  downloadDriveFile,
  importDriveFile,
  type IntegrationConfig,
  type PickedDriveFile,
} from "@/lib/google-drive";

export function GoogleDriveImport({ onImported }: { onImported: () => void }) {
  const owner = useAuth().user?.id;
  const [config, setConfig] = useState<IntegrationConfig>();
  const [ready, setReady] = useState(false);
  const currentOwner = useRef(owner);
  currentOwner.current = owner;
  const [picked, setPicked] = useState<PickedDriveFile[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [open, setOpen] = useState(false);
  useEffect(() => {
    let active = true;
    setPicked([]);
    setReady(false);
    setBusy(false);
    setOpen(false);
    setError("");
    void loadIntegrationConfig()
      .then(async (value) => {
        if (!active) return;
        setConfig(value);
        if (value.drive.configured) {
          await prepareDrivePicker();
          if (active) setReady(true);
        }
      })
      .catch((e) => {
        if (active) setError(e.message);
      });
    return () => {
      active = false;
    };
  }, [owner]);
  const select = async () => {
    const initiatedBy = owner;
    setError("");
    if (!ready) {
      setOpen(true);
      return;
    }
    try {
      const files = await pickDriveFiles(config!.drive);
      if (currentOwner.current !== initiatedBy) return;
      setPicked(files);
      if (files.length) setOpen(true);
    } catch (e) {
      if (currentOwner.current !== initiatedBy) return;
      setError(e instanceof Error ? e.message : "Drive açılamadı.");
      setOpen(true);
    }
  };
  const run = async () => {
    setBusy(true);
    setError("");
    let completed = 0;
    const initiatedBy = owner;
    try {
      for (const item of picked) {
        if (currentOwner.current !== initiatedBy) return;
        const file = await downloadDriveFile(item);
        if (currentOwner.current !== initiatedBy) return;
        await importDriveFile(file);
        completed++;
      }
      if (currentOwner.current !== initiatedBy) return;
      setPicked([]);
      setOpen(false);
    } catch (e) {
      if (currentOwner.current === initiatedBy) {
        setPicked((files) => files.slice(completed));
        setError(e instanceof Error ? e.message : "Aktarım tamamlanamadı.");
      }
    } finally {
      if (currentOwner.current === initiatedBy) {
        setBusy(false);
        onImported();
      }
    }
  };
  return (
    <>
      <Button size="sm" variant="outline" onClick={() => void select()} disabled={busy || !owner}>
        Google Drive'dan ekle
      </Button>
      <Dialog
        open={open}
        onOpenChange={(value) => {
          if (!busy) {
            setOpen(value);
            if (!value) setPicked([]);
          }
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Google Drive belgeleri</DialogTitle>
            <DialogDescription>
              Yalnız seçtiğiniz dosyalar JurisAI hesabınıza kopyalanır. Drive dosyalarının kendisi
              değiştirilmez.
            </DialogDescription>
          </DialogHeader>
          {!config?.drive.configured && (
            <p className="text-sm">
              Google Picker API anahtarı ve Cloud proje numarası henüz ayarlanmadı. Kurulum adımları
              Ayarlar → Bağlantılar bölümünde.
            </p>
          )}
          {picked.length > 0 && (
            <>
              <ul className="max-h-60 overflow-auto text-sm">
                {picked.map((file) => (
                  <li key={file.id}>{file.name}</li>
                ))}
              </ul>
              <Button onClick={() => void run()} disabled={busy}>
                {busy ? "Aktarılıyor…" : `${picked.length} belgeyi JurisAI'a aktar`}
              </Button>
            </>
          )}
          {error && (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}
