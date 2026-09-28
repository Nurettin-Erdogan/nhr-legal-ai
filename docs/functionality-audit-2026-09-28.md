# Uygulama işlev denetimi — 2026-09-28

Bu denetim, **veri çekimi/ingestion işçilerine dokunmadan** mevcut çalışma dalındaki
uygulama kodunu ve yerel testleri inceler. Testin geçmesi, her gerçek kullanıcı akışının
uçtan uca doğrulandığı anlamına gelmez.

## Kontrol edilen çekirdek

| Alan | Kod bağlantısı | Bu turdaki kanıt ve sınır |
| --- | --- | --- |
| Oturum ve erişim | `api/auth/`, `api/office.py`, `api/projects.py`, `api/documents.py` | Oturumsuz proje/belge istekleri 401; otomatik testler geçti. Gerçek kullanıcı oturumuyla tarayıcıda tüm akışlar sınanmadı. |
| Hukuk asistanı ve araştırma | `api/ai/`, `web/src/components/LegalChat.tsx` | RAG ve atıf testleri geçti; her hukuk sorusu için eksiksiz/doğru cevap garantisi yok. |
| Büro dosyaları/projeler | `api/office.py`, `web/src/lib/db.ts` | Kullanıcıya özel sorgular RLS ve erişim testlerine sahip. Canlı kullanıcı hesabıyla bütün CRUD adımları sınanmadı. |
| Web uygulaması | `web/` | TypeScript, birim testleri ve üretim derlemesi geçti. Tüm tarayıcı etkileşimleri için E2E testi yok. |

## Bu turda düzeltilen yanıltıcı ekranlar

- Ayarlar, başka bir hukuk bürosunun örnek kimliğini ve işlevsiz kaydetme düğmelerini
  göstermiyor. Var olan `office_call_settings` tablosundaki tercihler kullanıcıya
  özel olarak okunup yazılıyor. Telefon hizmeti olmadığı ayrıca belirtiliyor.
- Çağrılar ekranı yalnız kullanıcının gerçekten kayıtlı son 50 çağrısını gösteriyor;
  hayalî telefon numarası, arama istatistiği ve yapılmayan e-posta bildirimi yok.
- Tahsilat, modüller, icra, adaylar, raporlar ve personel ekranları sahte tutar,
  performans veya etkin bağlantı göstermiyor. Bağlantı bulunmadığını açıklıyor.
- Eski randevu adresi, gerçek `calendar_events` kayıtlarını kullanan takvime gider.
- Başvurular, erişim/veritabanı hatasını boş liste gibi sunmak yerine hata gösterir.

## Tamamlandı denemeyecek işler

| İşlev | Engel / gerekli adım |
| --- | --- |
| Telefon/SIP, outbound arama, WhatsApp | Sağlayıcı hesabı, izinler, sunucu entegrasyonu ve gerçek durum/olay kayıtları yok. Düğmeyle taklit edilmeyecek. |
| Ödeme, tahsilat ve finans raporu | Ödeme sağlayıcısı ile gerçek işlem/veri modeli yok. Rastgele tutar veya başarı sayısı gösterilmeyecek. |
| Çok kullanıcılı personel ve rol yönetimi | Üyelik, davet ve yetkilendirme akışları ürün kararı ve ayrı test gerektirir. |
| Google ile giriş/takvim | OAuth istemcisi ve yapılandırması olmadan bağlı görünemez. |
| Tüm OCR biçimleri | Tarayıcıdaki OCR akışı ayrı; doğrudan backend PDF parser'ı taranmış PDF metnini desteklediğini iddia etmiyor. |
| Her hukuk sorusunda kaynaklı cevap | Kaynak uygunluğu, doğrulama, model cevabı ve gecikme için gerçek senaryo testleri sürmeli. |

Genel `npm run lint` mevcut ağaçta başarısızdır; özellikle eski biçimlendirme
ihlalleri vardır. Bu turda değiştirilen frontend dosyaları ayrı lint kontrolünden
geçirilir. Büyük otomatik formatlama diğer kişilerin çalıştığı dosyalara
uygulanmaz.

Veri çekimi işçileri, korpus kayıtları ve `main` dalı bu denetimin dışındadır.
