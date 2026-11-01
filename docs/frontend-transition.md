# Frontend geçiş kontrolü — 27 Eylül 2026

TanStack Start/Vite arayüzü eski Next.js ağacının yerini alır. Yeni giriş `/auth`,
asistan `/dashboard/ai`; başlatma için [web README](../web/README.md).

## Yayın sınırı

- Arayüz, sohbet listesi/okuma/silme, büro CRUD/depo API'leri, içeriksiz denetim
  yardımcıları ve `026_office_workspace` migration'ı aynı pakettedir.
- CI migration satırındaki düz metin `\n` gerçek satır devamına düzeltildi;
  frontend test ve typecheck adımları eklendi.
- Ingestion, worker, embedding süreçleri, canlı korpus ve main dalı değiştirilmedi.
- Eski Supabase/ETL ve Lovable tasarım arşivleri, ikinci paket yöneticisinin
  kilit dosyası bu yayına dahil edilmedi; kullanıcı dosyaları silinmedi.

## Düzeltilen sorunlar

- RAG keşif/kanıt/atıf sayıları birbirinden ayrı gösterilir. Sayılar tüm korpusta
  eşleşen kayıt toplamı veya eksiksiz tarama iddiası değildir.
- Akış yarıda kesilirse başarı gösterilmez; hata ve alınmış özet korunur,
  stream reader kapatılır. Sohbet geçmişi yanıtları yarışıp yanlış sohbete yazılmaz.
- Kaynağı kayıp/karantinada/pending olan geçmiş atıfları artık resmî etiketlenmez.
- Büro AI çıktısı ortak kaynak desteği kontrolünü geçmeden gösterilmez/kaydedilmez.
- Taslaklar kullanıcıya ayrılmış sessionStorage'dadır; eski ortak localStorage
  taslakları okunmaz. Hatalar harici Lovable telemetry kancalarına iletilmez.
- Etkisiz Flash/Pro seçimi kaldırıldı. Model backend konfigürasyonundan seçilir.
- İndirilebilir UYAP ZIP'leri kaynaklardan yeniden üretildi; eşitlikleri test edilir.
- Yüklenen dosyalar indirme başlığı ve nosniff ile servis edilir.

## Test kapsamı ve kalanlar

Gönderilecek dosyaların ayrı Git-index kopyasında temiz npm kurulumu, typecheck,
Node testleri, production build ve izole PostgreSQL testleri yapılır.
RLS testleri başka kullanıcı kaydını okuma/yazma ve yabancı kayda bağlanma
denemelerini kapsar. Gerçek kullanıcı verisiyle giriş/ödeme/UYAP testi yapılmaz.

Bu geçiş **üretime hazır olma onayı değildir**. Ödeme ve sosyal giriş bağlı değil;
OCR harici motor kurulumu ister. Büro belge taslağı üretimi katı alıntı doğrulaması
nedeniyle reddedilebilir. Büro `office_*` tabloları ile mevcut RAG proje/belge
tabloları ayrıdır: büroya yüklemek otomatik proje-RAG indekslemesi demek değildir.
Eski `/projects` ve `/documents` Next.js sayfaları yeni büro ekranlarıyla aynı
veri modeli değildir. Personel/profil gibi tam bağlanmamış ekranlar ayrıca
tamamlanmalıdır. Büyük korpusta arama gecikmesi ve resmî doğrulama portal
sınırları bu frontend yayınıyla çözülmüş sayılmaz.
