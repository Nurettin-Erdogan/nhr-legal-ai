import { useState } from "react";
import { Link } from "@/lib/router-compat";
import { Button } from "@/components/ui/button";
import { linkUyapCases, type UyapCaseLinks } from "@/lib/office-api";

export function UyapCaseLinks() {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<UyapCaseLinks>();
  const [error, setError] = useState("");
  const connect = async () => {
    setBusy(true);
    setError("");
    try {
      setResult(await linkUyapCases(result?.has_more ? result.next_cursor : null));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Dava bağlantıları kurulamadı.");
    } finally {
      setBusy(false);
    }
  };
  return (
    <section className="mb-6 space-y-3 rounded-2xl border bg-card p-5">
      <h2 className="font-semibold">UYAP belgeleri ve dava bağlantıları</h2>
      <p className="text-sm text-muted-foreground">
        Yeni evraklar dosya numarası ve UYAP birimi birlikte eşleşen davaya bağlanır. Dava yoksa
        beklemede bir kayıt oluşturulur; müvekkil ve dosya durumu tahmin edilmez. Eski belgeleri de
        kayıtlı üst verileriyle eşleştirebilirsiniz. Elle kurduğunuz bağlantılar değişmez; birden
        çok eşleşme varsa belge bağlanmaz.
      </p>
      <div className="flex flex-wrap gap-2">
        <Button variant="outline" disabled={busy} onClick={() => void connect()}>
          {busy
            ? "Bağlantılar kuruluyor…"
            : result?.has_more
              ? "Kalan belgeleri eşleştir"
              : "Mevcut UYAP belgelerini davalara bağla"}
        </Button>
        <Link to="/dashboard/cases">
          <Button variant="outline">Davaları göster</Button>
        </Link>
      </div>
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
      {result && (
        <p role="status" className="text-sm">
          {result.linked} belge bağlandı; {result.ambiguous} belgenin dava eşleşmesi belirsiz,{" "}
          {result.missing_metadata} belgenin dosya numarası/birimi eksik veya geçersiz.
          {!!result.client_conflict &&
            ` ${result.client_conflict} belgenin müvekkili dava müvekkiliyle uyuşmuyor; otomatik bağlantı yapılmadı.`}
          {result.has_more &&
            " Arşivde kalan belgeler var; düğmeyle sonraki grubu işleyebilirsiniz."}
        </p>
      )}
    </section>
  );
}
