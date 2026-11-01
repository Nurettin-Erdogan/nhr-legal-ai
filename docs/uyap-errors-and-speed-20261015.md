# UYAP hata ayrımı ve sonuç bekleme iyileştirmesi — 2026-10-15

Geliştirme eklentisi sürümü: **2.26.35**. İzinler, hedef alan adları ve belge aktarım onayı değişmedi.

## Hata ayrımı

- Genel `Hata Oluştu`, `Güvenli Çıkış` menüsü ve iç UYAP servis adresi tek başına oturum kaybı sayılmaz. Önceki iki genel hata → `login_required` çıkarımı kaldırıldı.
- Açık oturum bitiş/giriş ekranı belirtileri veya UYAP HTTP 401 yanıtı `UYAP_SESSION_EXPIRED` üretir; aktarım yeniden giriş bekleyen mevcut akışa geçer.
- HTTP 403 veya açık yetki reddi `UYAP_ACCESS_DENIED` üretir. Bu evrak eksik kalır; diğer evraklar durdurulmaz. Kaydet adresiyle izin reddini aşma girişimi yapılmaz.
- Genel servis hatası `UYAP_PORTAL_ERROR` olur; mevcut sınırlı yeniden deneme ve hata sonrası yavaşlama korunur.
- Doğrulama reddi ayrı `UYAP_VALIDATION_FAILED` olarak kalır. Giriş/hata sayfası hiçbir zaman belge olarak yüklenmez.
- Aynı ayrım kısa düz metin yanıtlarına da uygulanır. Tanı, kullanıcıya gösterilen 120 karakterlik kesilmiş mesajdan çıkarılmaz.

## Hız

Eski içerik betiği her indirme sonucunu okumadan önce 700 ms bekliyordu. Yeni sonuç yoklaması servis çalışanında en fazla 1 saniye açık kalır ve belge hazır olduğunda hemen yanıtlanır. Uzun indirme tek bir uzun mesaj olayına dönüştürülmez.

İptal yoklamayı uyandırır; zamanlayıcı/abort/tamamlama dinleyicileri temizlenir. İş/sekmeye sahiplik tekrar kontrol edilir; eski bir yoklama yeni işin sonucunu tüketemez. Sonuç yalnız bir kez teslim edilir. Eski çalışan kısa yanıt döndürürse içerik betiği 200 ms bekleyerek sıkı mesaj döngüsünü önler.

UYAP indirmeleri **sıralıdır**. Başarıda mevcut 500 ms doğrudan yol / 1.500 ms tıklama yolu asgari başlangıç aralığı, hata geri çekilmesi, aynı evrak kimliğiyle tekilleştirme ve aktarım sonrası sunucu doğrulaması korunur.

Deterministik 100 küçük belge senaryosu (her belge için 100 ms yapay iş süresi): eski sonuç yoklaması 70.000 ms, yeni bekleme + mevcut hız sınırı 49.600 ms. Bu yaklaşık %29 daha kısa **simülasyon süresidir**, canlı UYAP için toplam hız veya bitiş garantisi değildir. Büyük indirme ve sunucu kayıt süreleri ayrıca devam eder.

## Doğrulama

- Web testleri: **464 geçti**; paket-kaynak eşitliği dahil.
- Tür denetimi ve üretim derlemesi: geçti.
- UYAP API birim testleri: **59 geçti, 44 veritabanı koşullu test atlandı**. Bu turda veritabanlı kabul testi yapılmadı.
- Ayrı Chromium ve yerel sahte UYAP/API: iki seçili koşuda 9 ve 11 test geçti (3 ortak senaryo; 17 farklı senaryo). Genel hatadan sonra ilerleme, gerçek oturum kaybı, izin reddi, gerçek makbuz/KEP, geçici hata, iptal, indirme ve gizli sekme beklemesi kontrol edildi. Gerçek UYAP bu testlerin kaynağı değildir.
- Canlı mevcut v2.26.34 aktarım yalnız okundu; durdurulmadı, yeniden başlatılmadı, sayfa/eklenti yenilenmedi. v2.26.35'in canlı kabul testi henüz yapılmadı.

## Uygulama notu

Çalışan aktarımın ortasında eklenti güncellenmemeli. İndirilebilir paket güncellendi; kullanıcı uygun arada v2.26.35'e geçince yalnız kalan evraklar doğrulanıp denenmeli. Belgeleri silmek veya yeniden sıfırdan indirmek gerekmez. Canlı raporda kalan belge hataları ayrıca incelenmeden eksiksizlik/yayın onayı verilmez.
