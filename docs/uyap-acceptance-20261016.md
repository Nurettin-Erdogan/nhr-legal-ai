# UYAP hedefli düzeltmeler ve kabul sınırı — 16 Ekim 2026

Bu not son durumu anlatır. `uyap-recovery-review-20261015.md` içindeki önceki
toplu orkestrasyon adayı kullanıcı isteğiyle geri alınmıştır; o paket tekrar
uygulanmadı. Buradaki değişiklikler canlıda ayrıştırılan nedenlere yöneliktir.
Hesap, bağlantı anahtarı ve mevcut belgeler silinmedi/değiştirilmedi.

## Canlı bulgular

- Güncel sorguda 64 dosya görünüyordu. Kullanıcının kalanlarla test onayıyla
  yalnız henüz doğrulanmamış 12 dosya seçildi; tüm 64 için başarı iddia edilmez.
- İlk tur 12 dosyayı işledi: 7 evrak sonucu eksiksiz, 5 eksik;
  1567 bulunan evraktan 1553 kayıtlı, 14 eksik, bu koşuda 0 gönderilmiş.
  Aynı hataları tekrarlayan son geçiş durduruldu; belgeler korundu.
- `.bin` reddi ile API kayıt hatası farklıdır. Genel MIME ve kodlanmış/eksik
  dosya adı gerçek belge türünü gizleyebilir; bilinmeyen byte'lar PDF sayılmaz.
- 2024/196 dosyasındaki canlı tek-evrak testi, `Diğer Evrak` altında sunulan
  gerçek pasif PTT KEP bildirimini eklentinin reddettiğini gösterdi.
- 2024/300 dosyasındaki tek eksik ekte API `psycopg.DataError` verdi.
  Yerel hata kaydı NUL byte nedeniyle PostgreSQL TEXT yazımının reddedildiğini
  gösterdi; belge içeriği, kimlik veya gizli anahtar rapora alınmadı.
- NUL düzeltmesi API'ye alındıktan sonra aynı ek başarıyla aktarıldı.
  İndirme ve yükleme yaklaşık 0,3'er saniyeydi (yalnız bu evrakın ölçümü).
  Ağaç tekrar okundu: **119/119 kayıtlı, yalnızca yeni olanlar: 0**.
  Bu sonuç bütün hesap veya bütün kalan dosyalar için kabul değildir.

## Uygulanan hedefli değişiklikler

1. Orijinal dosya ve checksum korunur; çıkarılan önizleme/arama metnindeki
   NUL yalnız boşluğa çevrilir. Kelimeler/tutarlar birleştirilmez.
   Kimlik üst verisindeki NUL ise kimliği sessizce değiştirmeden reddedilir.
2. Kayıt hataları içerik/yol/secret sızdırmadan disk, yol, yetki, geçici DB,
   DB yazımı ve doğrulanmamış insert olarak ayrılır.
3. RFC5987 UTF-8 dosya adları çözümlenir; izinli ofis/medya/arşiv MIME türleri
   adlandırılır. Genel MIME altında ZIP/TIFF/PNG/JPEG/GIF/RAR/7z ve tanınan
   RIFF türleri en fazla mevcut 4 KiB başlıktan tanınır. Bilinmeyen veya
   çalıştırılabilir içerik sessizce başka bir uzantıya çevrilmez.
4. Dar `Diğer Evrak` tür/ad kalıbında tam pasif KEP şablonu kabul edilir;
   etkin HTML, giriş ve hata şablonlarının reddi korunur.
5. Geçici hedef sunucu hatasında kalıcı evrak kimliği varsa aynı Blob/FormData
   en fazla üç POST ile denenir. UYAP'tan tekrar indirilmez. `Retry-After`,
   iptal ve gövdeyi de kapsayan boyuta bağlı son süre uygulanır. Kimliksiz
   POST otomatik tekrarlanmaz; kesin belge reddi/anahtar/disk hatası döngüye girmez.
6. Hedef/anahtar arızası UYAP oturum arızası sayılmaz; koşu kayıtlı ilerlemeyi
   koruyarak durur. Kaydı doğrulayan `ok` ve `id` yoksa HTTP 200 başarı değildir.

## Test kanıtı

- Tam çevrimdışı Python: **1528 geçti, 393 atlandı**, bir bağımlılık uyarısı.
- Ayrı, boş, rastgele adlandırılmış `_test` DB'de UYAP/API/yükleme/RLS:
  **161 geçti**. 138 yerel Chromium testi bu DB komutunda ayrı tutuldu.
  Canlı veri kopyalanmadı; yalnız komutun oluşturduğu test DB'si kaldırıldı.
- Web (indirilebilir ZIP eşitliği testleri hariç): **492/492 geçti**.
- TypeScript kontrolü ve üretim derlemesi geçti.
- Tam Chromium laboratuvarı: **138/138 geçti** (25 dakika). Gerçek UYAP'a
  bağlanmaz, yalnız sentetik yerel HTTPS UYAP ve API ile çalışır. Geçersiz
  hedef anahtarının artık ilk redden sonra `pairing_rejected` ile durduğunu
  doğrulayan test beklentisi güncellendi; hata nedeni ve tek başarısız evrak
  zorunlu tutuldu, başarısızlık gizlenmedi.
- Kaynak/paket eşitliği yeni sürüm paketlenince ayrıca çalıştırılacak.

Canlı sayfa/aktarımı riske atmamak için v2.26.36 aday ZIP'i ayrı, Git dışında
`.local/uyap-release-2.26.36/` altında üretildi. İkonlar dahil 14 ZIP girdisinin aday kaynakla
birebir eşitliği, kodun incelenen çalışma ağacından geldiği ve manifestin
2.26.36 olduğu doğrulandı. Bu aday kurulu eklentiye veya canlı indirme
bağlantısına uygulanmadı. Canlı `web/public` ZIP eşitliği kontrolleri yayın
paketi yükseltilince ayrıca çalıştırılmalıdır; 492 web testine dahil değildir.

## Kapanmamış kabul adımları

Chrome kontrol bağlantısı şu anda yok. Güncel eklentiyle KEP ve bilinmeyen
uzantı düzeltmelerinin canlı kabulü, diğer kalan evraklar, eksik dosya bilgisi
sekmesi ve tüm 64 dosyanın son doğrulaması tamamlanmadı. Bütün ürün için
“kusursuz / satışa hazır” onayı verilmez. Kaynak UYAP'ın oturum/erişim/yanıt
arızaları garantiyle yok edilemez; bunlar açık hata olarak korunmalıdır.

Önceki geri alınan incelemedeki genel oturum toparlanma/eşleme/sayaç
bulgularının tamamı bu hedefli paketle kapanmış sayılmaz. Bu tur yalnız
JurisAI hedef/anahtar hatasının UYAP yeniden giriş döngüsüne sokulmasını
ayırdı. Diğer toparlanma sınırları ayrıca kabul testinden geçirilmelidir.

Aktif bir aktarım olup olmadığı kullanıcıdan teyit edilmeden canlı sayfa
yenilenmez, eklenti yüklenmez veya API tekrar başlatılmaz.

Son salt okunur API sağlık kontrolü HTTP 200 döndü. Geliştirme dalı
`feature/legal-ai`; commit, push, dağıtım veya hesap/belge temizliği yapılmadı.
