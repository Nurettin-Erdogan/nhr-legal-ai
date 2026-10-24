# Genel uygulama denetimi — 24 Ekim 2026

## Sonuç

Yerel uygulama erişilebilir ve otomatik regresyon paketi başarılı. Bu sonuç,
asistanın bütün soruları doğru/tam yanıtladığı veya ticari yayın kabulünün
tamamlandığı anlamına gelmez. Bu tur uygulama kodu, yapılandırma, kullanıcı
kayıtları, çalışan servisler, embedding işleri ve korpus değiştirilmedi.

## Güncel kontroller

| Kontrol | Sonuç | Sınır |
| --- | --- | --- |
| API `/health` | 200, PostgreSQL connected, yaklaşık 0,02 sn | Tek anlık bağlantı kontrolü |
| Web `localhost:3000` | 200, yaklaşık 0,03 sn | Tüm sayfa/etkileşimlerin kabulü değil |
| Ollama `/api/tags` | 200 | Yeni model üretimi veya yük testi yapılmadı |
| Python | 2056 geçti, 433 atlandı, 1 deprecation uyarısı | DB ve tarayıcı opt-in testleri bu koşuda açık değil |
| Web | 558 geçti, 0 başarısız | Node testleri; gerçek tarayıcı E2E yerine geçmez |
| TypeScript | Başarılı | Çalışma zamanı kalite garantisi değil |
| Üretim derlemesi | Başarılı | Yapılandırma/plugin uyarıları var; yayın yapılmadı |
| `src` ESLint | 3543 hata, 20 uyarı | 3524 hata biçimlendirme; kalanlar 18 `no-explicit-any`, 1 `no-useless-escape` |
| `git diff --check` | Temiz | Önceden mevcut commit edilmemiş çalışmalar korundu |
| Özel veri GET uçları | Proje, sohbet, belge istekleri oturumsuz 401 | Kullanıcılar arası bütün CRUD senaryoları bu tur tekrar çalıştırılmadı |
| Özel dava kapsamlı AI POST | Oturumsuz 401 | Genel soru kapsamından farklı |
| Gerçek runtime rolü | `nhr_runtime`, superuser=false, bypass_rls=false | Satır politikalarının tamamının yeniden kabulü değil |

433 atlamanın 155'i tarayıcı etkinleştirme koşuluna; çoğu kalanı izole test
veritabanı eksikliğine bağlı. Atlananlar başarılı sayılmadı. Canlı veritabanında
yazma testi veya migration yapılmadı; yalnız rol/şema metaverisi salt okunur
işlemle kontrol edildi. Yeni ücretli model çağrısı yapılmadı.

## Öncelikli bulgular

### P1 — Asistan, eksik olay bilgisi ile eksik kaynak bilgisini karıştırabiliyor

Tarayıcıda son kayıtlı işten çıkarılma/tutar sohbeti incelendi. Asistan, hesap
için eksik girdileri netleştiren soru sormak yerine somut sonuç/oran
veremediğini söyleyen genel kaynak-yetersizliği metni göstermişti. Bu, yeni bir
üretim çağrısı değil, mevcut kaydın gözlemidir; bütün soruların başarısız olduğu
anlamına gelmez.

`api/ai/synthesis.py:38` kaynak-yetersizliği metnini tanımlar; `:601`
netleştirme seçenekleri çoğunlukla kaynak sözcüklerinden genel sözleşme tarihi,
tebliğ tarihi ve tutar soruları çıkarır. `:820` kaynak boşluğunu bu metinle
sonuçlandırır. Gerekli iyileştirme: konuya uygun eksik girdiyi belirlemek,
önceden verileni tekrar sormamak ve yeterli bilgiler tamamlandığında kaynaklı
cevaba geçmek. Kaynak doğrulamasını gevşetmek çözüm değildir.

Ayrıca API hata günlüğünde `draft_shape` nedeniyle onarım sonrasında doğal
üretimin yedek yola döndüğü kayıt mevcut. Bu tek kayıt hata oranını göstermez.

### P1 — Gizlilik ve kullanım metinleri güncel davranışı anlatmıyor

`web/src/routes/gizlilik.tsx:66-67`, yalnız yerel model kullanıldığını,
yazılanların üçüncü taraf AI hizmetine gönderilmediğini ve belirtilen iki
istisna dışında yurt dışına aktarım olmadığını söylüyor. Oysa mevcut ayarda
genel hukuk soruları OpenRouter üzerinden DeepSeek'e gider. Belge/dava/proje
kapsamını yerelde tutan koruma ayrı ve yerinde; bu durum genel soruların buluta
gittiğini açıklama gereğini ortadan kaldırmaz. Maskeleme tam anonimleştirme
garantisi değildir.

`web/src/lib/legal.ts:8` metinleri hâlâ taslak sayıyor; veri sorumlusu bilgileri
yer tutucu. Gizlilikte başvuru, denetim ve yedek saklama süreleri belirsiz.
Kullanım şartları da doğrulanmamış kayıtların kullanıcıya ayrı gösterildiğini
söylüyor; güncel ürün kararı ise bu kayıtların hiç gösterilmemesi. Yayın öncesi
gerçek işleyişe uygun metin ve yetkili hukuki inceleme gerekiyor.

### P1 — Genel AI çağrılarında oturum zorunlu değil

`api/ai/routes.py:139-166`, iki genel cevap uç noktasında
`optional_current_user_id` kullanıyor. Kapsamsız istek için kullanıcı kimliği
şartı yok; `api/ai/pipeline.py:91-128` bulut seçimini kullanıcı kimliğine göre
engellemiyor. Bu uç noktalarda uygulama içi çağrı sıklığı/aktif iş koruması da
bulunmadı. Dışarıya açılırsa oturumsuz istekler hesap kredisini ve üretim
kuyruğunu tüketebilir. CORS tek başına API yetkilendirmesi değildir.

Mevcut API `127.0.0.1:8766` üzerinde; dış erişim veya internetten saldırı bu tur
doğrulanmadı. Bu bulgu mevcut özel belgelerin açığa çıktığı iddiası değildir.
Çözüm, cevapları tokenla kısaltmak değil; yetkisiz çağrıyı önlemek ve eşzamanlı
işleri güvenli yönetmek.

### P2 — Bulut üretimleri de tek ortak kilidi bekliyor

`api/ai/pipeline.py:70,875,1137,1285,1301` aynı süreç-geneli
`asyncio.Lock` kullanıyor. Doğal cevap üretiminin yazıcı/denetçi/onarım
aşamaları da bu kilit altında. Bu, yerel GPU koruması için anlamlı olabilir;
bulut çağrılarının da aynı kilidi kullanması farklı kullanıcıların birbirini
beklemesine yol açabilir. Bu tur eşzamanlı ücretli yük testi yapılmadı;
bulgu kod yoluna dayanır. Yerel kaynak kilidi ile kontrollü bulut eşzamanlılığı
ayrılmalı ve ölçülmeli.

Önceki aynı gün ölçümleri: kira sorusu 12,29 sn, geniş zamanaşımı sorusu
36,61 sn. Bunlar bu turun yeni ölçümleri veya genel hız garantisi değildir.

### P2 — E-posta kurtarma yapılandırılmamış

Canlı `/api/auth/password-reset/status`, `email_delivery=false` döndürüyor.
Bu durumda kullanıcı kendi kendine sıfırlama e-postası alamaz; yönetici akışı
gerekir. Otomatik e-posta hatırlatmaları da SMTP yapılandırmasına bağlı.
Kod bunu desteklemediği halde destekliyormuş gibi bir iddia yapılmıyor;
ticari kullanım öncesi operasyonel eksik olarak tamamlanmalı.

### P2/P3 — Yayın kabulü ve kod bakım işleri tamam değil

İzole DB/RLS ve gerçek tarayıcı kabulü son değişikliklerle yeniden koşulmalı.
Canlı UYAP, farklı dosya türleri, çok belgeli soru, takip sorusu, yanlış
ilişkilendirilmiş tarih/tutar ve eşzamanlı kullanıcı senaryoları sırf birim
testleri başarılı diye tamamlanmış sayılmaz. Mevcut dalda önemli değişiklikler
ve yeni dosyalar hâlâ commit edilmemiş; bu tur commit yapılmadı.

Lint başarısızlığı ayrıca ayrı, küçük bakım değişiklikleriyle ele alınmalı.
3543 lint hatası 3543 çalışma zamanı hatası anlamına gelmez; biçimlendirme
çoğunlukta. İlgisiz dosyalara toplu otomatik formatlama uygulanmadı.

## Tarayıcı incelemesinin sınırı

Hukuk Asistanı açıldı, mevcut sohbet okunabildi ve İçtihat sayfasına geçildi.
İçtihat ekranında ilk yükleme görüldü; sonrasında tarayıcı kontrol bağlantısı
zaman aşımına uğradığından tüm ekranların görsel kabulü tamamlanmadı. Bu
zaman aşımı uygulamanın çöktüğünün kanıtı sayılmadı. Kullanıcı kaydı silinmedi,
yeni sohbet oluşturulmadı ve form gönderilmedi.

## Önerilen sıra

1. Asistanın eksik girdi / eksik kaynak ayrımı ve doğal takip soruları.
2. Genel AI uç noktalarının yayın erişim politikası ve bulut eşzamanlılığı.
3. Gerçek bulut işleyişine uygun gizlilik/kullanım metinleri ve saklama kararı.
4. İzole DB + tarayıcı + gerçek senaryo kabul paketi; ardından SMTP ve lint bakımı.
