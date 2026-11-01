# UYAP aktarımı: eşzamanlı indirme, okuma turu hızı ve oturum yoklaması — 16 Ekim 2026

Eklenti sürümü **2.26.36**. İzinler ve hedef alan adları değişmedi.

## Ölçüm (gerçek hesap, canlı pencere)

Okuma turu (hiçbir şey aktarılmadan, 64 dosya, ~10 200 evrak): **27 dk**, dosya başına ortanca 23 sn.
Zamanın dağılımı (4 sn'lik yoklamayla, yaklaşık):

| Adım | Pay |
| --- | --- |
| Dosya bilgisi sekmeleri (taraf, safahat, tahsilat/reddiyat, hesap) | ~%64 |
| Dosyayı açma + evrak ağacı | ~%32 |
| Diğer | ~%4 |

İndirme (geçici deneme hesabı, aynı 191 evraklı dosya sıfırdan, her koşu öncesi hesap sıfırlandı):

| Eşzamanlı indirme | Aktarım süresi | Hata |
| --- | --- | --- |
| 1 | 125 sn (0,65 sn/evrak) | 0 |
| 2 | 58 sn | 0 |
| 3 | 47 sn | 0 |

Tek dosya, tek ölçüm; UYAP'ın günün saatine göre hızı değişir.

## Değişiklikler

1. **Eşzamanlı tıklamasız indirme** (`pullParallel`, varsayılan 3, 1-3 arası). Arka plan her evrak için ayrı iş
   yuvası tutar (`fetchId`); eşzamanlı işler tıklamayla yakalanan adresi kullanmaz. Tıklama yolu (önizleme yakalama)
   sayfayı kullandığı için her zaman tek tek ve sırayla yürür. UYAP hata vermeye başlayınca (`gap` büyür) yalnız ilk
   işçi sürer; başarılar beklemeyi normale indirince diğerleri döner. Her evrak UYAP'tan bir kez istenir, JurisAI'a
   bir kez yüklenir (Chromium testi 1/2/3 için).
2. **Oturum yoklaması.** 2.26.35 genel "Hata Oluştu" sayfasını oturum kaybı saymayı bırakmıştı. Oysa gerçek aktarımda
   oturum dolunca UYAP giriş ekranı yerine bu genel sayfayı döndürmüştü (2026-10-13). Artık art arda iki genel hata
   sayfasında UYAP sekmesinin kendi adresi salt okunur bir kez istenir: o da hata ya da giriş ekranı dönerse oturum
   kapanmış sayılır ve aktarım yeniden giriş bekler; normal sayfa dönerse aktarım sürer. Ağ hatası bir şey kanıtlamaz.
3. **Dosya bilgisi sekmeleri.** Tablo durulma yoklaması 500 → 250 ms (art arda üç aynı yoklama, üst sınır yine ~20 sn).
   UYAP'ın yazdığı kayıtların hepsi zaten ekrandaysa sayfa boyutu "Tümü"ne alınmaz (gereksiz ikinci yükleme yok).
4. **Süre kaydı.** Koşu kaydındaki her dosya `timing` (ağaç, aktarım, dosya bilgileri; saniye) taşır; evrak içeriği yoktur.
5. **Reddiyat detayı şeması.** Boş gizli reddiyat tablosu yalnız 12 sütunlu düzende "doğrulanmış boş" sayılıyordu; Ceza
   dosyalarında UYAP 9 sütunlu düzen kullanıyor ("Makbuz No, Durum, Reddiyat Tarihi, Reddiyat Nedeni, …, Net Ödenecek
   Miktar"; canlıda ölçüldü). Kural artık sütun adlarına bakar (ilk sütun "Makbuz No", "Reddiyat Tarihi" ve "Reddiyat
   Nedeni" var, son sütun "Ödenecek …", 8-14 sütun); eklenti ve sunucu (`_static_reddiyat_schema`) aynı kuralı uygular.
6. **Dosya bilgisi için son tur.** Evrakı tamam ama bir bilgi tablosu o an yüklenmemiş dosyalar koşu sonunda bir kez daha
   okunur (evrak aktarılmaz); yeni okuma yalnız tamsa eskisinin yerini alır. Canlıda iki dosyanın taraf tablosu iki
   denemede de gelmemiş, dakikalar sonra ilk okumada tam gelmişti.

## Canlı sonuç (kullanıcının hesabı)

- Yeni sürümle okuma turu: **16 dk** (önce 27 dk); dosya bilgisi sekmeleri toplam ~17 dk → ~6,5 dk.
- "Tüm dosyaları aktar": eksik kalan 13 evrak (önceki sürümlerde `.bin`, KEP ve adres yakalama hataları) çekildi;
  **64/64 dosya, 10 190/10 190 evrak kayıtlı**, 20 dk.

## Doğrulama

- Arayüz testleri 530/530, tür denetimi temiz; UYAP sunucu testleri geçti.
- Sahte UYAP Chromium takımı: 147/147 (eşzamanlı indirme ve oturum yoklaması testleri dahil); reddiyat şeması testleri ayrıca geçti.

## 17-18 Ekim: büyük dosyalar ve UYAP tarafı hatalar (2.26.39 → 2.26.42)

Canlıda ikinci bir hesap (88 dosya) üç yeni durumu gösterdi: ekleriyle 6 000-47 536 kayıtlı dosyalar (UYAP yalnız ana evrakı
sayar, ör. 972), UYAP'ın kendi iç hata sayfası ("Hata Oluştu … AVUKATWeb bağlantı hatası") ve içeriği olmayan evraklar
("Evrak UYAP sistemine yüklenmemiş"). Program her birinde dosyayı bırakıyordu. Değişenler:

- **Büyük dosya:** web, evrakları eklentinin tek iş sınırına (5 000) parçalayarak aktarır; kayıt kontrolü 5 000'lik
  parçalarla bütün evraklara sorulur; ağaç sınırı 20 000 → 200 000; sunucu bilinen evrak sınırı 250 000.
- **İçeriği UYAP'ta olmayan evrak** (`UYAP_DOCUMENT_ABSENT`): bir kez denenir, eksik sayılmaz, raporda ayrı yazılır
  (`absent`). Canlıda doğrulandı: 67/67 eksiksiz, 1 evrak "UYAP'ta içeriği yok".
- **Takılan evrak dosyayı durdurmaz:** üst üste 5 hatada dosyayı bırakma kuralı kalktı; hatalı evrak atlanır, kalanlar
  aktarılır, takılanlar dosya sonunda yeniden denenir. Hiç evrak inmiyorsa 25 denemede bırakılır ("UYAP bu dosyanın
  evraklarını şu an vermiyor"). Her 5 ardışık hatada 15 sn mola.
- **Evrağa özgü UYAP iç hatası hızı düşürmez** ve Kaydet adresi / 8 sn'lik yerinde yeniden deneme yapılmaz.
- **Boşa tekrar yok:** tamamlanıp hiç evrak indiremeyen aktarım aynı dosyada hemen tekrarlanmaz (koşu sonu turu dener).
- **Yeniden giriş beklemesi** 30 dk → 3 saat (UYAP oturumu aktarım sürerken de ~1 saatte kapanıyor).

Sahte portalda gerçek boyutlu denemeler (Chromium):

| Durum | Sonuç |
| --- | --- |
| 1 000 ana evrak × 47 ek = 48 000 kayıt | ağaç 17 sn'de eksiksiz, tekrarsız; kayıt kontrolü ≥10 parça |
| 90 evrak, 29'u UYAP iç hatası (8'i üst üste) | 61 evrak aktarıldı, 29 eksik bildirildi; 6 dk 22 sn → 75 sn |
| 200 evrak, hepsi UYAP iç hatası | 25 denemede (31 sn) bırakıldı, nedeni yazıldı |

Gerçek UYAP'ta (hesapla) henüz koşulmadı: 2.26.40-42 değişiklikleri ve Avukat Portalı. (2.26.42: "iç hata sayfası" kuralı yalnız UYAP'ın "Hata Oluştu" şablonuna daraltıldı; önizleme/Kaydet yolları etkilenmez.)

## 18 Ekim: sayfa tanınmadığında kendi kendine yapı raporu (2.26.43)

Avukat Portalı canlıda görülemediği için (avukat hesabı yok) ilk gerçek kullanımdan öğrenmek üzere: liste ya da dosya ağacı
okunamazsa (`no_list`, `query_failed`, `no_tree`, `open_failed`, `no_content`, `cannot_close`, `no_dialog`) JurisAI sayfası
eklentiden UYAP sekmesinin **yapı özetini** (`DIAGNOSE` köprü komutu → content.js `diagnose`) alıp sahibin hesabına kaydeder
(`POST /api/office/uyap/diagnostics`, tablo `office_uyap_diagnostics`, migration 057; RLS, KVKK dışa aktarımında).
Özet içerik, ad, dosya numarası ya da bağlantı değeri taşımaz; sunucu ayrıca 6+ rakamlık dizi, e-posta benzeri metin ve 200
karakterden uzun metni reddeder. Aynı sorun türü sayfa oturumunda bir kez; sahip başına saatte 20, toplam 50 kayıt.

Doğrulama: Python 8 test (süzgeç, RLS, denetim kaydında içerik yok, sınırlar), web 2 test, Chromium'da gerçek eklenti özeti
sunucu süzgecinden geçer ve dosya/kişi metni taşımaz. Tam takımlar: web 541/541, üretim derlemesi geçti, Python 1838 geçti
(4 kırık: Codex'in dosya özeti sayı denetimi, UYAP dışı), Chromium 154/155 (kırılan 1 test tek başına 3/3 geçiyor:
zamanlamaya bağlı, tekrarlanamadı).
