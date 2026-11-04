import { useEffect, useState } from "react";
import { Link } from "@tanstack/react-router";
import { loadUyapAccounts, type UyapAccounts } from "@/lib/uyap-sync-api";

/**
 * Bu hesaba hangi kişilerin UYAP'ından dosya aktarıldığı (kullanıcı kararı 2026-10-16: dosyalar kimin UYAP'ından geldiyse
 * onun altında dursun, karışmasın). Her aktarımda UYAP'ta giriş yapan kişi okunur ve evrakları onunla işaretlenir; Belgeler
 * sayfası bu kişiye göre ayırır.
 */
export function UyapAccountBinding() {
  const [data, setData] = useState<UyapAccounts | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let alive = true;
    loadUyapAccounts()
      .then((value) => alive && setData(value))
      .catch(
        (cause) =>
          alive && setError(cause instanceof Error ? cause.message : "UYAP hesapları okunamadı."),
      );
    return () => {
      alive = false;
    };
  }, []);

  if (!data && !error) return null;
  return (
    <section
      className="space-y-2 rounded-xl border bg-card p-5 text-sm"
      data-testid="uyap-accounts"
    >
      <h2 className="font-semibold">Dosyalar kimin UYAP'ından geldi</h2>
      {error ? (
        <p className="text-destructive">{error}</p>
      ) : !data?.accounts.length && !data?.unknown.files ? (
        <p className="text-muted-foreground">
          Henüz UYAP'tan aktarım yok. Her aktarımda UYAP'ta giriş yapan kişi okunur; dosyaları
          Belgeler'de o kişinin adı altında ayrı durur.
        </p>
      ) : (
        <>
          <ul className="space-y-1">
            {data?.accounts.map((account) => (
              <li key={account.id} className="flex flex-wrap items-center gap-x-2">
                <span className="font-medium">{account.display}</span>
                <span className="text-muted-foreground">
                  {account.documents > 0
                    ? `${account.files} dosya · ${account.documents} evrak`
                    : "şu an bu kişiden gelen belge yok (silinmiş ya da çöp kutusunda olabilir)"}
                </span>
              </li>
            ))}
            {data && data.unknown.files > 0 && (
              <li className="flex flex-wrap items-center gap-x-2">
                <span className="font-medium">Kimden geldiği bilinmiyor</span>
                <span className="text-muted-foreground">
                  {data.unknown.files} dosya · {data.unknown.documents} evrak — bu dosyaların sahibi
                  kendi UYAP'ıyla girip "Yalnız denetle" ya da "Tüm dosyaları aktar"a basınca onun
                  adına geçer.
                </span>
              </li>
            )}
          </ul>
          <p className="text-muted-foreground">
            <Link to="/dashboard/files" className="underline underline-offset-2">
              Belgeler
            </Link>{" "}
            sayfasında dosyalar bu kişilere göre ayrılır.
          </p>
        </>
      )}
    </section>
  );
}
