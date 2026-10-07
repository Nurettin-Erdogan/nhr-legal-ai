# JurisAI yayın planı: bugün nerede, yayına çıkmak için ne gerekir

Hazırlandı: 2026-10-05. Ölçümler bu makineden alındı; maliyetler **tahmindir ve doğrulanmamıştır** (güncel fiyatlar kontrol edilmeli).

## 1. Bugünkü durum (ölçüldü)

Her şey tek bir dizüstü bilgisayarda çalışıyor: Intel i7-12700H, **32 GB RAM, RTX 3050 6 GB** ekran kartı.

| Parça | Bugün | Not |
| --- | --- | --- |
| Web | `vite dev` (geliştirme sunucusu) | Üretim derlemesi (`npm run build`) **çalışıyor**, ama varsayılan hedef Cloudflare Workers; kendi sunucumuzda Node hedefi seçilmeli |
| API | `uvicorn` elle başlatılıyor | Docker/servis tanımı yok, yalnız veritabanı için `docker-compose.yml` var |
| Veritabanı | PostgreSQL 16 + pgvector, Docker, **213 GB** | `legal_chunks` 162 GB; arama dizini 31 GB; vektör dizini 9,5 GB |
| Korpus | 28,8 M parça, 11,3 M kaynak | **424.957 kaynak resmî doğrulanmış**, ~10,9 M kaynak üçüncü taraf (doğrulanmamış) |
| Belgeler | `uploads/` klasörü (yerel disk) | Yedeklenmiyor, nesne depolama yok |
| Yapay zekâ | Ollama: qwen3.5:4b (cevap), nomic-embed-text (arama) | Ekran kartı 6 GB; model dosyası 3,4 GB |
| Toplayıcılar | PC + Azure VM (D2ds_v4) | Resmî portal sınırı IP başına ~700 kayıt/saat |
| Adres, TLS | yok (`localhost`) | UYAP eklentisi de yalnız `http://localhost:3000` kabul ediyor |

## 2. En kritik sınır: aynı anda kaç avukat kullanabilir?

Cevap üretimi tek kilitle sıraya sokuluyor (`_generation_lock`): **aynı anda tek cevap** üretilir. Ölçülen süre 20-40 sn, Derin Araştırma ~50 sn.

- Bir ekran kartı ≈ saatte 90-180 cevap.
- 5 avukat aynı anda soru sorarsa sonuncusu 2-3 dakika bekler.
- Pilot (3-5 avukat, seyrek kullanım) için yeterli; 20+ eşzamanlı kullanıcı için **birden fazla ekran kartı/model sunucusu** ya da bulut modeli gerekir.

## 3. Veri büyüklüğü: korpusun tamamını mı yayınlayacağız?

213 GB'ın yaklaşık **%90'ı doğrulanmamış üçüncü taraf kayıtlar** (10,9 M kaynak). Resmî doğrulanmış kısım parça sayısına göre ~%11 (≈3,1 M parça).

| Seçenek | Disk (tahmin) | Artı | Eksi |
| --- | --- | --- | --- |
| A. Tam korpus | 250-300 GB SSD, 32+ GB RAM | Bugünkü arama kapsamı | Pahalı sunucu, yedekleme zor (213 GB), arama soğukta 5-40 sn |
| B. Yalnız resmî doğrulanmış | ~30-45 GB (tahmin, ölçülmedi) | Küçük, hızlı, yedeklenebilir; "resmî" iddiasının dayanağı | Doğrulanmamış karar araması kalkar |
| C. B + doğrulanmamışın seçili kısmı (atıf yapılan/en yeni) | 60-100 GB (tahmin) | Denge | Seçim kuralı gerekir |

Öneri: **pilotta B ya da C**. Ürün ilkesi (doğrulanmamış veri ayrı gösterilir, resmî diye sunulmaz) iki seçenekte de korunur.

## 4. Yayına çıkmadan önce yapılacaklar

**Altyapı**
1. Barındırma kararı (bkz. 5). Alan adı + HTTPS sertifikası.
2. Web'i Node sunucu hedefiyle derle; API ve web için servis tanımı (Docker ya da systemd), otomatik yeniden başlatma.
3. Ortam değişkenleri: `AUTH_COOKIE_SECURE=true`, `CORS_ORIGINS` = gerçek adres, `JWT_SECRET` yeni ve rastgele, `ALLOW_REGISTRATION` kapalı/davetli, veritabanı parolaları yenilenmiş, `.env` depoda değil.
4. Belge deposu: yerel disk yerine yedeklenen bir birim ya da nesne depolama; kullanıcı başına kota. **Yükleme boyutu sınırı kaldırıldı (2026-10-06, kullanıcı kararı)**: dosyalar diske akıtılır, bu yüzden disk doluluğu izlenmeli (madde 6) ve ortak sunucuda gerekirse `MAX_UPLOAD_BYTES` ile üst sınır konabilir.
5. Yedekleme: 213 GB'ı `pg_dump` ile almak pratik değil. B/C seçeneğinde günlük dökümü + belgelerin ayrı yedeği; **geri yükleme en az bir kez denenmeli**.
6. İzleme: sağlık kontrolü, hata günlüğü, disk/RAM uyarısı, model sunucusu açık mı.
7. UYAP eklentisi: gerçek alan adı `WEB_ORIGINS`'e ve eklenti manifestine eklenmeli; Chrome Web Store hesabı + gizlilik e-postası (`docs/chrome-web-store.md`).

**Güvenlik ve KVKK**
8. Hesap silme (KVKK silme hakkı): **yapıldı** (arayüzden "HESABIMI SİL" onayıyla; genel akış testinde doğrulandı). Silinen kullanıcının belge dosyalarının diskten temizlendiği ayrıca kontrol edilmeli.
9. Aydınlatma metni, gizlilik politikası, kullanım şartları, veri saklama süreleri; müvekkil verisi işlenmesi için avukatın kendi aydınlatma yükümlülüğü hatırlatması (eklenti ayarında var).
10. Dışarıdan bağımsız temel güvenlik taraması (oturum, yetki izolasyonu testleri zaten var; dış sızma testi yok).
11. Yapay zekâ **yerelde** kalıyorsa müvekkil verisi sunucudan çıkmaz. Bulut modele geçilirse bu bir KVKK kararıdır (yurt dışı aktarım) ve ayrıca değerlendirilmelidir.

**Ürün**
12. 3-5 avukatla kapalı pilot: gerçek sorular, gerçek belgeler, bir hafta; hata ve beğenmeme listesi.
13. Ödeme/abonelik pilotta gerekmez; ticari yayından önce sağlayıcı ve fiyat kararı.

## 5. Barındırma seçenekleri

| | Nasıl | Artı | Eksi |
| --- | --- | --- | --- |
| **1. Büro sunucusu** | Bugünkü gibi tek güçlü makine, internete güvenli tünelle açılır (ör. Cloudflare Tunnel/VPN) | En ucuz; veri sizde; hızlı başlanır | Tek hata noktası, elektrik/internet kesintisi, bakım sizde |
| **2. Bulut, CPU sunucu + ekran kartlı model sunucusu** | Veritabanı/API/web bulutta, model ayrı GPU makinesinde | Ölçeklenir, yedekleme/izleme hazır | İki makine, aralarında güvenli bağlantı; GPU saatlik pahalı |
| **3. Bulut, tek GPU sunucu** | Her şey tek VM'de | En basit kurulum | Aylık maliyet yüksek; seçenek A ile tam korpus için disk de büyük |

Öneri: **pilot için 1** (B/C veri ile), sonuç iyiyse **2**'ye geç. Azure sunucunuz (D2ds_v4) toplayıcı olarak kalır; model çalıştıramaz (ekran kartı yok).

## 6. Önerilen yol

1. Bu plandaki 1-3 numaralı kararı verin: veri seçeneği (B/C), barındırma (1), alan adı.
2. Ben yaparım: Node üretim derlemesi, API/web servis tanımları, B/C veri dökümü ve geri yükleme denemesi, `.env` üretim şablonu, güvenlik ayarları kontrol listesi.
3. Siz yaparsınız: alan adı, pilot avukatları, aydınlatma metni için hukuki danışman.
4. Pilot → bulgular → ödeme ve ölçekleme kararı.

## 7. Kararlar (2026-10-05)

- **Barındırma:** şimdilik yerelde çalışılacak (bu makine); bulut/alan adı kararı ertelendi.
- **Veri seçeneği: C** (resmî doğrulanmış + doğrulanmamışın seçili kısmı). Seçim kuralı henüz yazılmadı; öneri: atıf yapılmış kayıtlar + son yıllara ait kayıtlar + resmî kısımda bulunan dairelerin karar türleri. Kural belirlenince boyutu ölçülüp bu belgeye yazılacak; doğrulanmamış kayıtlar yine ayrı işaretli kalır.

## 8. Yerelde veri güvenliği: kullanıcı verisi yedeği

Yedeklenmeyen tek şey zaten yeniden üretilebilen korpus (toplayıcılar yeniden doldurur). **Avukatların verisi (hesap, müvekkil, dava, belge, sohbet, denetim kaydı, yüklenen dosyalar) yeniden üretilemez** ve düzenli yedeği yoktu (son döküm 17 Eylül).

- `scripts/backup_user_data.py`: 30 kullanıcı tablosunu + `uploads/` dosyalarını yedekler (ölçülen: 2.144 satır, ~1 MB), `--verify` ile **geçici veritabanına geri yükleyip satır sayılarını karşılaştırır**, zip'i sınar, eski yedekleri döndürür (`--keep`, varsayılan 14). Listede olmayan yeni tablo uyarıyla yedeğe dahil edilir.
- Günlük çalıştırma (kullanıcı onayıyla): `powershell -File scripts\install_user_backup_task.ps1 -Destination D:\yedekler` (her gün 02:30, bilgisayar kapalıysa açılınca). Henüz kaydedilmedi.
- **Yedek müvekkil verisi içerir (KVKK):** başka bir fiziksel diske/şifreli bir konuma alın; aynı diskte tutulan yedek diskle birlikte kaybolur.

## 9. Seçenek C'nin seçim kuralı ve boyutu (ölçüldü, 2026-10-05)

Mevcut doğrulayıcı zaten bu sırayla çalışır: önce atıf kuyruğu (`seed_verification_queue`, `request_count` çok olan önde), sonra **karar tarihi en yeni olandan geriye**. Kural bu davranışa bağlanır:

> Üretim alt kümesi = resmî doğrulanmış tüm kayıtlar + doğrulanmamış kayıtlardan **atıf kuyruğundakiler** + **son 3 yılın** (2024-2026) kayıtları. Doğrulanmamış olanlar yine ayrı işaretli kalır; doğrulandıkça "resmî" olur.

Doğrulanmamış envanterin yıllara dağılımı (`bulk_seed_inventory`, 9,9 M kayıt) ve tahmini ek disk (kayıt başına ~11 KB vektörsüz, ~40 KB vektörlü; 3.000 kayıtlık örnekten tahmin):

| Kapsam | Kayıt | Ek disk (vektörsüz / vektörlü) | Doğrulama süresi (~700 kayıt/saat, tek IP) |
| --- | --- | --- | --- |
| Son 1 yıl (2025-26) | 0,43 M | ~5 / ~17 GB | ~26 gün |
| **Son 3 yıl (2024-26)** | **0,73 M** | **~8 / ~29 GB** | **~43 gün** |
| Son 5 yıl (2022-26) | 1,36 M | ~15 / ~55 GB | ~81 gün |
| Son 10 yıl | ~5 M | ~55 / ~200 GB | ~300 gün |

Resmî kısım (~35-45 GB, tahmin) + son 3 yıl ⇒ üretim veritabanı yaklaşık **45-75 GB**. Doğrulanmamış kayıtlar doğrulanmadan da aranabilir kalır (ayrı rozetle); süre yalnız "resmî olma" için gerekir.

## 10. Pilot hazırlığı (2026-10-05)

- **Yerel yedek görevi kaydedildi:** "NHR Legal AI User Data Backup", her gün 02:30, ilk çalıştırma doğrulandı (sonuç 0). Varsayılan hedef `data/backups/user` (aynı disk): **ayrı/harici bir diske taşımak için** `scripts\install_user_backup_task.ps1 -Destination D:\yedekler -UpdateExisting`.
- **KVKK metinleri (taslak):** `/gizlilik` (gizlilik + aydınlatma), `/kullanim-sartlari`; alt bilgiden bağlı. Veri sorumlusu bilgileri ve saklama süreleri köşeli parantezli, **hukuk danışmanı onayı bekliyor**. Vatandaş başvuru formuna **zorunlu aydınlatma onayı** eklendi; sunucu onaysız başvuruyu reddeder, onay zamanı ve metin sürümü kaydedilir (migration 044).
- **Geri bildirim:** panelde "Geri bildirim" düğmesi (hata / öneri / beğeni; yalnız yazılan metin ve sayfa yolu gider, sorgu dizesi ve belge içeriği gitmez). Kullanıcı yalnız kendi mesajını görür; pilotu yürüten `scripts\list_feedback.py [--category hata] [--csv dosya.csv]` ile hepsini okur (migration 045).
