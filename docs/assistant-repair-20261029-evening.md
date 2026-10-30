# Asistan düzeltmeleri — 29 Ekim 2026, akşam

## Kanıtlanan sorunlar

- Çok parçalı cevapta geçerli bir `source_only=false` kararı,
  `checker_part_coverage` bulunmadığı için yanlışlıkla protokol/teknik hata
  sayılıyordu. İçerik reddi ve biçim hatası ayrıldı; özgün cümle kimlikleriyle
  ret geri bildirimi onarım aşamasına korunarak aktarılıyor.
- “İki gerçek Yargıtay kararı” ifadesi eski sayı deseninden kaçıyordu.
  Sayı isteği ortak bir yardımcıya taşındı. Farklı parça/kayıt kimliklerinin aynı
  karar künyesini iki karar yapması engellendi. İstenen mahkeme de korunuyor.
- Kaynak havuzundaki karar sayısı, son cevapta gerçekten kullanılan karar sayısı
  değildi. Son kullanılan kanıtlarda karar adedi ayrıca kontrol ediliyor;
  karşılanmayan istek tam cevap/önbellek başarısı sayılmıyor ve mevcut sınırlı
  onarım bütçesine hedefli geri bildirim gidiyor. Bu sayısal kontrol tek başına
  içtihadın ilgili olduğunu kanıtlamaz; mevcut bağımsız denetim devam ediyor.
- Tekrarların temizlenmesi, esaslı bilgi kaybı gibi değerlendirilip gereksiz
  ikinci yazım/denetim turu açabiliyordu. Onaylanmış tekrarlar bu kayıptan ayrıldı.
- Aynı anlamın farklı sözcüklerle tekrarı yalnız kelime benzerliğiyle silinmiyor.
  Mevcut bağımsız denetimde isteğe bağlı açık tekrar eşleştirmesi kullanılıyor.
  İki cümle de onaylı, aynı kanıta bağlı ve sayı/birim/sınır bakımından uyumlu
  olmalı. Reddedilmiş veya gösterilmeyen hedefe bağlanarak kapsam tamamlanamaz.
  Tekrar tespiti için ilave model çağrısı yok.

## Sınırlar

- Bu tur ücretli model çağrısı yapılmadı. Gerçek modelin yeni isteğe bağlı tekrar
  alanını ne sıklıkla doğru ürettiği ve uçtan uca hız kazanımı henüz ölçülmedi.
- API yeniden başlatılmadan çalışan sürece yeni kod alınmış sayılmaz.
- Arayüz veya UYAP eklentisi değiştirilmedi; tarayıcı paketi bu tur çalıştırılmadı.
- Üretim veritabanı, model ayarları ve sırlar değiştirilmedi. Regresyonlar yalnız
  ayrı 55439 portundaki test veritabanında çalıştırılır.

## Son doğrulama

- `.local/assistant-repair-20261029-final.xml`: 3.326 başarılı, 0 başarısız,
  0 atlanan backend testi (72,34 saniye). UYAP tarayıcı paketi ayrı kapsamdır ve
  bu koşuya dahil değildir. İki mevcut uyarı: Starlette/httpx kullanımdan
  kaldırma uyarısı ve kasıtlı bozuk TIFF test verisinin EXIF uyarısı.
- `ruff check api ingestion scripts tests`: temiz.
- Kullanıcının aktif işlem olmadığı onayından sonra API yeniden başlatıldı:
  Uvicorn PID 33200, 127.0.0.1:8766, `/health` HTTP 200; başlangıçta port
  çakışması hatası yok. Embedding PID 3356 çalışmaya devam ediyor.
- İzole test veritabanı test sonunda durduruldu.
