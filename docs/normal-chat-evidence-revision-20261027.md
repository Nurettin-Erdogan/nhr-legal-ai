# Normal sohbet: kanıt seçimi ve düzeltme

27 Ekim 2026. Luna korunuyor; model/anahtar/ödeme ayarı değiştirilmedi.

## Uygulananlar

- İpucu maddeleri, anlam/kelime araması ve kararlar ayrı kaynak şeritleri olarak
  dengeli seçiliyor. İlk iki ipucu bütün mevzuat yerlerini tüketmiyor.
- Bir alt sorunun iki sorgusu da kaynak havuzuna katılıyor; ilk sorgunun
  sonuçları ikinci sorguyu bütünüyle dışlayamıyor. Alt soru başına en fazla altı
  kaynak; toplam 36.000 karakterlik kanıt bütçesi aynı kaldı.
- Yerel alt-soru aramaları en fazla iki paralel bağlantı kullanıyor.
- Mevcut iki denemelik üretim sınırı içinde, eksik veya reddedilmiş bölüm için
  en fazla üç yerel arama ve altı yeni doğrulanmış kaynakla düzeltme yapılabiliyor.
  Önceki doğrulanmış cevap düzeltmeye aktarılıyor, fakat kanıt yerine sayılmıyor:
  yeni cevap yine mekanik ve bağımsız model denetiminden geçiyor.
- Aynı kanıt bütçesinde yeni kaynakların sona itilip tamamen kaybolması önlendi.
- Açık kira yüzdesi hesabında çıktı para birimi ve birinci tekil kişi çekimi
  tanınıyor. Hukuki uygunluk soruları hesap makinesine çevrilmiyor.

Kaynak doğrulama, sayı/ödeme yönü/alt-üst sınır kapıları ve özel belge bulut
izolasyonu kaldırılmadı. Bu bir model eğitimi veya doğrulama atlatması değil.

## Doğrulama ve sınırlar

- Tam çevrimdışı takım: 2598 geçti, 442 ortam gerektiren test atlandı.
- Son küçük değişikliklerden sonra ilgili 93 test tekrar çalıştırıldı, geçti.
- İki önceki canlı başarısız örneğin yeniden kontrolü başlatıldı. İlk cevap
  dakikalar içinde tamamlanmadığından yalnız bu testin iki Python süreci
  sonlandırıldı; yeni ücretli deneme yapılmadı. Veritabanı gözleminde yalnız
  gözlem sorgusu aktif görünüyordu. Gecikmenin nedeni bu gözlemle belirlenemez.
- Dolayısıyla canlı çok-parçalı cevap kalitesi bu turda doğrulanmış sayılmıyor.
  Önceki başarısızlıklar kapandı iddiası yok. Sonraki kontrol aşama sürelerini
  (planlama/yerel arama/üretim/denetim) ayrı ölçmeli.
- Yalnız ana API mevcut yeniden başlatma betiğiyle yenilendi: health 200,
  Uvicorn 127.0.0.1:8766. Veritabanı, MCP ve embedding işçileri değiştirilmedi.

Commit atılmadı; diğer çalışma ağacı değişiklikleri korunuyor.
