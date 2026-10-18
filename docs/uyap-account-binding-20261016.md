# UYAP dosyalarını kime ait olduğuna göre ayırma — 16 Ekim 2026

Kullanıcı kararı: "Dosya kimin UYAP'ından çekiliyorsa onun altında dursun, karışmasın." Bir JurisAI hesabına birden çok
kişinin UYAP'ından aktarım yapılabiliyor (örnek: kullanıcının hesabında iki ayrı UYAP hesabından gelen 64 + 19 dosya). Her
evrak geldiği UYAP kişisiyle işaretlenir; Belgeler sayfası dosyaları bu kişilere göre ayırır. **Kimse engellenmez.**

(İlk sürüm her hesabı tek kişiye bağlayıp ikinci kişiyi reddediyordu; bu, isteğin yanlış anlaşılmasıydı ve aynı gün
geri alındı.)

Eklenti **2.26.37**, migration **056** (`office_uyap_accounts`, `office_case_documents.uyap_account_id`).

## Nasıl çalışır

- Eklenti UYAP'ta giriş yapan kişiyi okur ve her isteğe ekler. Sunucu bu kişiyi hesabın UYAP kişileri arasına kaydeder
  (ad soyad her görüldüğünde tazelenir) ve yüklenen evrakı onunla işaretler.
- Bir kişi "Yalnız denetle" ya da "Tüm dosyaları aktar" çalıştırdığında, dosyasının kimden geldiği bilinmeyen eski evrakları
  onun adına işaretlenir. Başka bir kişiyle işaretlenmiş evrak el değiştirmez.
- Belgeler: "Kimin UYAP'ından" süzgeci ve "Dosyaya göre" görünümünde kişi başlıkları (kişiler, sonra "kimden geldiği
  bilinmiyor", en son UYAP dışı yüklenenler). Bir dosyanın sahibi, evraklarının çoğunun geldiği kişidir.
- UYAP sayfası: hangi kişiden kaç dosya/evrak geldiği.
- Aktarım ortasında UYAP'ta giriş yapan kişi değişirse koşu durur (liste ilk kişinindir).
- Kişi okunamazsa aktarım başlamaz (`uyap_identity_required`): kimin olduğu bilinmeyen evrak yeniden birikmez.

## Kimlik ve KVKK

Vatandaş Portalı, giriş yapan kişinin T.C. kimlik numarasını sayfanın kendi başlatma betiğinde taşır (canlıda ölçüldü:
ana sayfada ve Dosya Sorgulama'da tek numara, kontrol haneleri geçerli). Eklenti numarayı **tarayıcıda** SHA-256 ile parmak
izine çevirir (`jurisai-uyap-identity:v1:tc:<numara>`); numara bilgisayardan çıkmaz. Sunucu parmak izini ayrıca gizli bir
anahtarla HMAC'leyip saklar (`UYAP_IDENTITY_SECRET`, yoksa `JWT_SECRET`'tan amaca özel türetilir). Görünen ad, UYAP'ın üst
köşesindeki ad soyaddır (rakam kabul edilmez); yalnız hesap sahibi görür (RLS). Numara okunamayan portallarda ad soyaddan
parmak izi üretilir (`kind = 'name'`). Bir evrak, başka bir sahibin UYAP kişisiyle işaretlenemez (tetikleyici).

Avukat Portalı canlıda ölçülemedi (avukat hesabı yok): orada kimlik numarası bulunamazsa ad kullanılır; ad da okunamazsa
aktarım açık bir hatayla durur.

## Mevcut veri

Kullanıcının bugün kendi UYAP'ından doğrulanan 64 dosyası (10 190 evrak) onun kişisiyle işaretlendi
(`.local/backfill_uyap_accounts.py`). Daha önce başka bir UYAP hesabından aktarılan 19 dosya (1 382 evrak) "kimden geldiği
bilinmiyor" görünür; o kişi kendi UYAP'ıyla denetim yaptığında onun adına geçer.

## Doğrulama

- Python (gerçek RLS'li veritabanı): bir hesapta birden çok kişi, ad tazeleme, iki hesapta aynı kişi ayrı kayıt, dosya
  bazlı işaretleme (boşluk/büyük harf farkı), el değiştirmeme, başka sahibin kişisiyle işaretleme reddi, sayımlar.
- Belgeler sorgusu: kişi sayımları, "bilinmiyor" süzgeci, klasör sahibi.
- Web ve Chromium: kimlik ayrıştırma (rakam/biçim taşıyan ad geçmez), istekte yalnız parmak izi + ad.
- Canlı: kimlik okundu (tür `tc`).

## Açık

Eski `uyap-dosya-cekici` eklentisinin kullandığı `/api/public/uyap-ingest` yolu (arayüzde sunulmuyor) kişi işaretlemez.
