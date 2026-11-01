import { useEffect, useState } from "react";
import {
  INTEGRATION_BASE,
  loadIntegrationConfig,
  type IntegrationConfig,
} from "@/lib/google-drive";
export function IntegrationSettings() {
  const [config, setConfig] = useState<IntegrationConfig>();
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    let active = true;
    setError("");
    void loadIntegrationConfig()
      .then((value) => {
        if (active) setConfig(value);
      })
      .catch((e) => {
        if (active) setError(e.message);
      });
    return () => {
      active = false;
    };
  }, [retry]);
  return (
    <section className="space-y-4 rounded-xl border border-border bg-card p-6" id="connections">
      <h2 className="text-xl font-semibold">Bağlantılar: Drive ve Word</h2>
      {error && (
        <p role="alert" className="text-destructive">
          {error}{" "}
          <button className="underline" onClick={() => setRetry((value) => value + 1)}>
            Yeniden dene
          </button>
        </p>
      )}
      <div>
        <h3 className="font-medium">
          Google Drive ·{" "}
          {error
            ? "Durum alınamadı"
            : config
              ? config.drive.configured
                ? "Yapılandırıldı"
                : "Kurulum gerekli"
              : "Kontrol ediliyor…"}
        </h3>
        <p className="text-sm text-muted-foreground">
          Dosyalar → Google Drive'dan ekle ile yalnız seçtiğiniz belgeleri içe aktarın. Google
          Dokümanlar DOCX olarak alınır; Drive dosyası değiştirilmez. Google ile giriş yapmak bu
          erişimi otomatik vermez.
        </p>
        <details className="mt-2 text-sm">
          <summary>Yönetici kurulumu</summary>
          <p>
            Google Cloud'da Drive ve Picker API'lerini etkinleştirin. OAuth web istemcisinin izin
            verilen JavaScript kaynaklarına bu uygulamanın adresini ekleyin. Sunucuda
            GOOGLE_DRIVE_CLIENT_ID (veya GOOGLE_CLIENT_ID), GOOGLE_PICKER_API_KEY ve
            GOOGLE_CLOUD_PROJECT_NUMBER tanımlayın; API anahtarını uygulama adresi ve gereken
            API'lerle kısıtlayın. OAuth için drive.file kapsamını yapılandırın. Sunucuyu yeniden
            başlatın.
          </p>
        </details>
      </div>
      <div>
        <h3 className="font-medium">
          Microsoft Word ·{" "}
          {error
            ? "Durum alınamadı"
            : config
              ? config.word.configured
                ? "Manifest hazır"
                : "HTTPS adresi gerekli"
              : "Kontrol ediliyor…"}
        </h3>
        <p className="text-sm text-muted-foreground">
          Word görev bölmesi seçili metni veya belgenin metnini açık onayınızla işler; sonucu mevcut
          metni değiştirmeden ekler. JurisAI hesabıyla giriş gerekir.
        </p>
        {config?.word.configured && (
          <a
            className="mt-2 inline-block text-sm text-primary underline"
            href={`${INTEGRATION_BASE}${config.word.manifest_path}`}
          >
            Word eklenti manifestini indir
          </a>
        )}
        <details className="mt-2 text-sm">
          <summary>Yönetici kurulumu</summary>
          <p>
            Uygulamayı geçerli HTTPS sertifikalı bir adreste yayınlayın ve WORD_ADDIN_ORIGIN
            değerini bu adres yapın. Bu adresteki /api istekleri JurisAI API'sine yönlenmeli.
            Microsoft 365 yönetim merkezinde manifesti dağıtın veya desteklenen Word sürümünde
            sideload edin. Eklenti mağazada yayınlanmış değildir. Önce test hesabıyla kontrol edin.
          </p>
        </details>
      </div>
    </section>
  );
}
