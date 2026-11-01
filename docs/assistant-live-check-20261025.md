# Embedding sonrası asistan kontrolü

Bu rapor yalnız bu turdaki gözlemleri kaydeder; tüm soruların doğru yanıtlandığı
veya hukuki doğruluğun otomatik testle kanıtlandığı anlamına gelmez.

## Ölçülen durum

- API `/health`: 200.
- OpenRouter / `deepseek/deepseek-v4-flash` gerçek çağrısı başarılı.
- `idx_legal_chunks_embedding_bq`: `indisvalid=true`, `indisready=true`.
- İndeks ifadesi: `(binary_quantize(embedding)::bit(768))`.
- Kira ödenmemesi sorusu: `grounded=true`, TBK 315 atfı, yaklaşık 7,7 saniye.
- İşten çıkarılma genel haklar sorusu: `grounded=true`, 1475/14 ve
  4857/17,32,59,18,20 kaynaklarıyla cevap. Yaklaşık 52,8 saniye; model onarım
  çağrısı ve kısmi metin arama zaman aşımı var. Hız hedefi tamamlanmış değil.
- Ortak velayet: değişken sonuç. Bir koşuda denetim reddi, başka koşuda yalnız
  bir dar koşulun onaylanması görüldü. Başarılı tek yanıt genellenemez.
  Kısmi taslak onarım düzeltmesinden sonraki canlı koşuda kaynaklı koşul
  açıklaması onarımdan ve bağımsız denetimden geçti (`grounded=true`, iki atıf).
  Bu tek koşu kararlılık veya hukuki yeterlilik garantisi değildir.
- Araştırma planlayıcısı yalnız test sürecinde denendi; kabul testini geçmediği
  için kalıcı olarak açılmadı. `.env` değiştirilmedi.

## Düzeltmeler

- Canlı vektör sorgusunun hazır olma kontrolü artık aynı binary Hamming
  ifadesini ve operatör sınıfını gerektirir. Tek başına cosine indeksi veya
  yalnız doğru isimde bir indeks yeterli sayılmaz. DDL uygulanmadı.
- Bulut taslağından mekanik denetimde cümleler düşerse, yalnız kalan dar
  parçayı yayınlamak yerine mevcut tek kaynak-bağlı onarım hakkı kullanılır.
  Onarılan taslak parçalı kurtarma olmadan tekrar denetlenir; bağımsız denetim
  zorunluluğu kaldırılmadı. Değişmeden kalan hatalı iddia kabul edilmez.
- `source_digest` geri dönüşü yalnız açık aynen/tam metin isteklerine
  sınırlandı. Normal soruda başarısız açıklama uzun kanun alıntısıyla gizlenmez.
  Araştırma planı olan yanıt bu yoldan kapsam denetimini aşamaz.

## Güvenlik ve kapsam

Canlı örnekler genel, sentetik sorulardır; `user_id=None` ile iç işlem hattında
çalıştırıldığından kayıtlı kullanıcı sohbetlerine yazılmadı. Bu HTTP oturum/RLS
kabul testinin yerine geçmez. Üretim uç noktalarının kimlik doğrulaması
değiştirilmedi. Gizli anahtar, bakiye, sağlayıcı gizlilik ayarı değiştirilmedi.
Doğrulanmamış kaynaklar açılmadı; Docker/veritabanı yeniden başlatılmadı.

## Takip

Son çevrimdışı paket: **2373 geçti, 440 atlandı**, bir bağımlılık deprecation
uyarısı. Gerçek DB testleri yalnız test sürecinde devre dışı tutuldu; atlananlar
başarılı sayılmaz. `git diff --check` temiz. Son değişiklikler API yeniden
başlatılarak uygulandı: `/health` 200; başlangıç günlüğünde Uvicorn 8766 dinliyor,
`WinError 10048` yok. Commit/push yapılmadı.

Ortak velayet gibi karar gerektiren sorularda kaynak parçalarının kapsamını,
taslağın eklediği koşulları ve denetçi kararını birlikte incelemek gerekiyor.
Bu tamamlanmadan planlayıcıyı açmak veya denetimi gevşetmek çözüm sayılmaz.
