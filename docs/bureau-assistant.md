# Büro Asistanı

## Mevcut akış

- Günlük özet kayıtlı duruşma ve görev tarihlerini İstanbul saatine göre gösterir.
- Son 7 gündeki belge girişleri ve gelecek 7 gündeki duruşmalar öneriye dönüşür.
- İnceleme paneli kaynak metnin başlangıcını gösterir; bu alıntı özet değildir.
- Duruşma hazırlığı dosyanın kayıtlı bilgilerini, açık görevlerini ve belge durumunu bir araya getirir.
- Kullanıcı, okunabilir belgelerden hangilerinin özet işine alınacağını seçer.
  `AI_PROVIDER=bedrock` modunda bu özel belge işlemleri de açık kullanıcı
  onayıyla AWS Bedrock'ta yapılır; yerel üretim geri dönüşü yoktur.
- Özet üretimi açık düğme eylemiyle başlar ve mevcut kalıcı belge kuyruğuna kaydedilir.
- Dava sohbeti açıldığında mevcut dava kapsamlı sohbet kullanılır. Bu sohbet yalnız inceleme panelindeki seçili belgelerle sınırlı değildir.
- Taslak eylemi yalnız seçili belgelerin kimliklerini mevcut belge üretim ekranına taşır; üretim ya da UYAP gönderimi başlatmaz.
- Görev/takvim oluşturma ayrı onay ekranı ve sunucuda kaynak yeniden doğrulaması gerektirir.

## Sınırlar

İnceleme paneli en yeni 10 belgeyi, hazırlık notu ilk 20 açık görevi gösterir; sınırlı listeler ekranda belirtilir.
Hazırlık notu hukuki strateji raporu değildir. Kayıtlı tarihlerden yeni hukuki süre veya yükümlülük türetilmez.
Özetin tamamlanması her hukuki sorunun cevaplandığı anlamına gelmez; belge kuyruğunun okuma/başarısız bölüm uyarıları korunur.
Öneriyi kapatmak veya takvime eklemek duruşma hazırlığını erişilemez yapmaz; yaklaşan duruşma listesinden yeniden açılır.

## Gizlilik ve doğrulama

Okuma uçları oturum sahibinin `nhr_runtime`/RLS bağlantısını kullanır. Başka kullanıcının ya da başka davanın belgeleri eklenmez.
Özet ve dava sohbeti özel kapsamda kalır; genel sohbetin bulut ayarı özel belgeler için kullanılmaz.
Sayfayı açmak görev, takvim veya model işi oluşturmaz. Kaynak metin HTML olarak çalıştırılmaz.
Özet geçmişinde seçim/kullanıcı değişince önceki çıktı temizlenir; geciken eski istek sonucu yeni kullanıcıya yayınlanmaz.

## Test kapsamı

`tests/test_bureau_assistant.py`, `tests/test_bureau_review_database.py` öneri, tarih, kaynak kapsamı ve RLS kontrollerini sınar.
`web/tests/bureau-review.test.mjs` belge seçimi, hazırlık notu ve salt okunur incelemeyi sınar.
`web/tests/document-job-panel.test.mjs` geçmiş işler arasında geçişi ve geciken eski kullanıcı yanıtını sınar.
Bu otomatik testler gerçek modelin gerçek kullanıcı belgelerindeki özet kalitesinin veya tarayıcı görsel testinin yerine geçmez.
