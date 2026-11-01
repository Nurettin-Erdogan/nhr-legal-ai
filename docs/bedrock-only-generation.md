# Tek Bedrock metin üretimi — 2026-11-01

Kullanıcı özel belgeler, dava/proje ve UYAP içeriklerinin de AWS Bedrock'a
gönderilmesine açık onay verdi. `.env` içindeki `AI_PROVIDER=bedrock` ve
`AI_MODEL=deepseek.v3.2` ile metin üretimi tek sağlayıcıya yönlendirilir.
`CLOUD_AI_PROVIDER=bedrock` ve mevcut Bedrock kimlik bilgisi gerekir.
Bu mod açıkken araştırma profilinin eski ayrı model ayarı kullanılmaz.

- Sohbet, büro belge özeti/taslağı, özel kapsam ve denetim Bedrock kullanır.
- Ollama üretim sağlayıcısı veya yerel hata geri dönüşü oluşturulmaz.
- Bedrock hatası hata olarak döner; gizlice yerel model çalıştırılmaz.
- Açık onay yalnız model yönlendirmesini değiştirir. RLS, allowlist, belge
  sahipliği, kaynak doğrulaması, özel verilerin genel web aramasından ve
  ortak cevap önbelleğinden ayrılması korunur.
- Mevcut sağlayıcının maskelemesi korunur; tam anonimleştirme garantisi değildir.
- `/api/ai/status` yapılandırma hazırlığını gösterir; başarılı ücretli bir
  model çağrısının kanıtı değildir.

## Henüz taşınmayan bölüm

Embedding ayrı bir model görevidir. Mevcut 768 boyutlu nomic-embed-text ve
1024 boyutlu bge-m3 indeksleri hâlâ yerel Ollama bağımlılığı taşır. Farklı bir
bulut modelinin çıktıları, boyutları eşit olsa dahi bu indekslerle uyumlu
sayılmaz. Ya aynı modeller güvenli bir AWS hizmetine taşınmalı ya da yeni
model için ayrı embedding üretimi ve indeks göçü planlanmalıdır. Bu yapılana
kadar Ollama servisini tamamen kapatmak anlam aramasını bozabilir.

## Doğrulama

- API yeniden başlatıldı; `/health` başarılı, veritabanı bağlı.
- Çalışan `/api/ai/status`: `bedrock`, `deepseek.v3.2`, `configured=true`.
- Tam izole backend paketi: 3640 geçti, atlanan yok. Sonrasında eklenen iki
  kontrol dâhil tek-sağlayıcı test dosyası 12/12 geçti.
- Arayüz: 598 geçti, atlanan yok; tip kontrolü başarılı.
- Gerçek üretim çağrısı yapılmadı; testlerde kredi harcanmadı.
- Genel Python lint'te mevcut, bu değişiklikten bağımsız bir kullanılmayan
  değişken bulgusu kaldı (`pipeline.py`, `single`).
- Tam sentetik UYAP tekrar koşusu: 151 geçti, 4 köprü zaman aşımı hatası;
  ayrıntılar `qa-bureau-2026-11-01.md` içinde. Bu paket temiz değildir.

Bu belge anahtar/parola içermez. Ortam dosyasının önceki hali git dışındaki
`.local` altında korunmuştur. Model dosyaları silinmedi.
