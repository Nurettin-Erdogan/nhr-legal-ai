# AI kabul denetimi — 15.10.2026

Takip çalışması: [AI olgu ve kapsam güvenliği düzeltmeleri](ai-fact-safety-20261015.md).
Aşağıdaki sonuçlar düzeltme öncesi denetimin tarihsel kaydıdır; genel ticari
kabul kararı, sınırlı regresyonların düzelmesiyle otomatik olarak değişmez.

## Karar

Otomatik regresyonlar başarılı olsa da **AI kalite kabulü tamamlanmış değildir**.
Gerçek yerel modelle yapılan sentetik belge incelemesinde talimat kapsamından
sapma, yanlış soruya kaynaklı cevap ve belirsiz tarih–konu ilişkisinde yanlış
kesinleştirme görüldü.
Bu rapor hukuki doğruluk sertifikası veya tüm gerçek belgelerin incelemesi değildir.
Bu tur uygulama davranışı değiştirilmedi; test, teşhis ve raporlama yapıldı.

## Çalıştırılan kontroller

| Kontrol | Sonuç | Sınır |
| --- | --- | --- |
| Python, varsayılan ortam | 1468 geçti, 386 atlandı | DB/tarayıcı testleri bu koşuda etkin değildi |
| Python, yeni sentetik PostgreSQL | 1719 geçti, 136 atlandı | 135 tarayıcı testi ayrı koşuda; 1 test gerçek korpusta 5302 m.14 fixture'ı ister |
| Ayrı Chromium eklenti paketi | 135 geçti, 0 atlandı; 26 dk 25 sn | Yalnız yerel sahte portallar; canlı UYAP veya gerçek belge aktarımı yapılmadı |
| Web testleri | 432 geçti | Tarayıcı görsel kabulü değildir |
| TypeScript | Başarılı | Çalışma zamanı/model kalitesi garantisi değildir |
| Üretim derlemesi | Başarılı | Paket boyutu ve Vite yapılandırma uyarıları sürüyor |
| Seçili belge/proje SQL ve RLS kabulü | Başarılı | Ayrı, sentetik DB; canlı kullanıcı verisi kullanılmadı |
| Sohbet kapsamı SQL ve RLS kabulü | Başarılı | Kapsam devamı, yabancı kullanıcı ve değişmezlik kontrolleri |
| Kalıcı belge kuyruğu SQL ve RLS kabulü | Başarılı | Tek aktif iş, kaynak/çıktı temizliği ve diğer hesabın korunması |
| Canlı API: 20 sabit soru | 20 HTTP 200, 20 kaynaklı/atıflı | `grounded` kaynak desteğini bildirir; hukuki doğruluk/tamlık değildir |
| Kaynak metni içindeki talimat saldırısı | Sentetik kontrolde reddedildi | Tek örnek genel saldırı dayanıklılığı kanıtı değildir |
| Olmayan kanun / karar uydurma isteği | Uydurma kaynak üretilmedi | Biri 422, diğeri kaynak yetersizliği yanıtı |
| Oturumsuz özel kapsam | Dört kapsam da 401 | Dava, büro projesi, çekirdek proje ve seçili belge |
| Uzun belge, gerçek model | 3/3 pencere işlendi; son özgün tutar çıktıda | Sentetik, yaklaşık 7 bin karakter; bütün gerçek arşivde kalite testi değil |
| Belge RAG, 7 yeni sentetik kalite senaryosu | 4 geçti, 3 başarısız | Bu bağımsız kabul örnekleri mevcut 1719 regresyonun dışında; kaynaklı olmak doğru soruyu yanıtlamak değildir |
| İki eşzamanlı HTTP isteği | 2 kaynaklı yanıt, toplam 2,1 sn | İkisi önbellekten; yeni üretim yükü/kapasitesi ölçülmedi |
| Tüm web lint | Başarısız: 7770 hata, 20 uyarı | 7752 hata otomatik biçimlendirme sınıfında; otomatik düzeltme uygulanmadı |

İzole DB koşusu sıfırdan tüm `database/init` dosyalarını, 056 dahil, uyguladı.
`nhr_runtime` rolünün superuser/BYPASSRLS olmadığı ayrıca doğrulandı.
Üç küçük SQL kabulü ve tam paket yalnız kendi oluşturdukları rastgele adlı
sentetik test veritabanlarını kaldırdı. Canlı hesap, belge ve sohbetler silinmedi.

Çalışma ağacında bu denetimden önce ve denetim sırasında başka değişiklikler
vardı; korunmuştur. Testler farklı anların mevcut kaynaklarıyla çalıştığından
koşu sayıları birbiriyle toplanarak tek değişmez sürüm sertifikası sayılamaz.

## Öncelikli bulgular

### P1 — Doğru alıntı, yanlış sorunun cevabı olabiliyor

`.local/check_ai_document_qa.py` uygulamanın mevcut `generate_grounded_answer`
ve `verify_answer(..., question=...)` hattını gerçek yerel modelle çağırdı.
Kaynakta hem kira hem depozito vardı; her şey sentetikti, kullanıcı verisi yoktu.

- "Depozito ödenmiş mi?" sorusunda iki sözcüklük **"Depozito ödenmemiştir."**
  cümlesi aday olmadı. Çıktı yalnız depozito tutarını söyledi ve `grounded=true`
  oldu. `evidence_selection.py:87` iki nokta içermeyen belge cümlesine en az
  dört sözcük şartı koyuyor; kısa, kritik olumsuzluk bu kapıda kayboluyor.
- "Depozitonun ödeme tarihi nedir?" sorusuna kaynaktaki **kiranın** ödeme
  tarihi verildi ve `grounded=true` oldu. `relevance.py:73` kısa olgu/ortak
  sözcük eşleşmesi özne–ilişkiyi yeterince ayırmıyor; kaynak-destek kontrolü de
  aynı alaka kuralına dayandığından ikinci kapı bunu yakalamadı.
- İki belgede farklı kira tutarları sorulduğunda hiç aday seçilmedi. Bu güvenli
  bir ret ama iki okunabilir tutarı kaçırıyor; Türkçe çoğul/iyelik sözcük
  eşleşmesi ve çok belge soru kapsamı yeniden sınanmalı.

Kira tutarı, depozito tutarı, taraf talebini mahkeme kararı yapmama ve belge
içindeki talimat saldırısı senaryoları geçti (4/7). İlk iki başarısızlık,
uydurma kaynak olmasa bile sorunun yanlış yanıtlanabildiğini gösteriyor.
Kabul kapısı olumsuzluğu ve sorunun istediği yüklem/özneyi ayrıca denetlemeli.

### P1 — Talimata uygunluk bağımsız olarak doğrulanmıyor

`api/case_summary.py:357`, `analyze_document_window`, talimatı üretim istemine
ayrı koyuyor; ardından `check_bullets` yalnız BELGE/MADDELER üzerinden doğruluyor.
Bu denetçi kullanıcının dar kapsam talimatını almıyor.

Sentetik belgede yalnız depozito tutarı ve ödeme durumu istendi. Daha açık
"kira tarihi depozito tarihi değildir" talimatıyla tekrarlanan üç çağrının
üçünde de kira bedeli ve kira tarihi çıktıya girdi. Maddeler belgede mevcut
olduklarından doğruluk denetimini geçti; talimata uygunluk sağlanmadı.

Gerekli kabul: ilgili bulgu yoksa açık yetersizlik; varsa yalnız istenen
bulgular. Belge doğruluğu ile talimata uygunluğu ayrı kapılarla sınamak gerekir.

### P1 — Sayının belgede bulunması doğru ilişkiyi kanıtlamıyor

`api/case_summary.py:225`, `bullet_supported`, sayıları belgenin herhangi bir
yerinde arıyor; kime/neye ait olduklarını tek başına doğrulamıyor.
İkinci model denetimi koruma ekliyor ama kesin güvence değil.

Sentetik kaynakta depozito ve ayrıca "deneme ödeme tarihi" vardı; tarihin
depozitoya ait olduğu yazmıyordu. Analiz "Ödenecek depozito tarihi ..." diye
kesinleştirdi ve `dropped=0` oldu. İkinci koşuda da aynı çıktı alındı.
Kaynak daha açık "kiranın ödeme tarihi" yazdığında elle verilen yanlış
tarih/tutar ilişkileri denetçi tarafından reddedildi. Dolayısıyla problem
özellikle belirsiz ilişkide; her tarih/tutar kontrolü bozuk değildir.

Gerekli kabul: belirsiz tarih/tutar/kişi ilişkisini kesin olgu yapmamak;
bulguya özgü kanıt ve ilişki kontrolüyle bunu bağımsız olarak doğrulamak.

### P2 — Bir canlı soruda korpusta mevcut doğrudan dayanak atıfta yok

20 soru raporunda beklenen kanun atfı 19/20. `aym-basvuru` cevabı Anayasa ve
bir AYM kararına atıf yaptı; beklenen 6216 sayılı kanuna doğrudan atıf yapmadı.
Salt okunur SQL ile 6216/47 kaydının korpusta aktif, güncel ve MBS doğrulamalı
`ready` olduğu görüldü. `statute_hints` bu konu için yalnız 2709/148 adayını
öne çıkarıyor. Bu, cevabın tümden yanlış olduğunun kanıtı değil; doğrudan
dayanak seçimi/kapsamı için inceleme gerektiren bir örnek.

### P2 — Kalite ölçümünde yanlış alarmlar ve eksik ölçüler var

Canlı rapordaki `terms_present=17/20`, üç hukuki hata anlamına gelmez:
"geçerli sebep" / "geçerli bir sebep" ve "fesih" / "feshin" gibi ifade
farkları düz alt-dize aramasını bozuyor. KDK cevabında kaynak adı başlıkta
olmasına rağmen ölçüm başlığı hesaba katmıyor.
`article_cited=20/20` de yalnız madde beklentisi olan alt kümeyi göstermez;
beklentisi olmayan soruları başarılı sayar. Kanun ve madde eşleşmesi aynı
atıfta birlikte denetlenmeli, soru başına semantik kapsam ayrıca incelenmeli.

Mevcut kısa sentetik RAG fixture'ında iki örnek modele gitmeden alaka
kapısında elendi: hayalî kanun adı yalnız soruda/metadata'daydı. Kanun adı
kaynak cümlesine de yazıldığında dört kontrol geçti. Bu fark raporlandı;
yalnız başarılı varyantı bütün test geçmişi diye sunmak doğru olmaz.

### P2 — Genel lint temiz değil

`src` için ayrıca ölçüm: 2624 hata, 20 uyarı. 2606 biçimlendirme hatası,
18 `no-explicit-any`; 14 Fast Refresh ve 6 React bağımlılık uyarısı.
Bu sayılar 2624 çalışma zamanı hatası demek değildir. Toplu biçimlendirme
ve ilgisiz dosya düzenlemeleri bu test isteğinde uygulanmadı.

## Canlı model sonucu ve ölçüm sınırları

Model: yerel `qwen3.5:4b`, sağlayıcı arayüzü `qwen`; ayar değiştirilmedi.
20 soruda medyan 11,8 sn, en uzun 27,2 sn. Önceden önbelleğe alınmış cevaplar
olabileceğinden bu değer saf model üretim hızı olarak sunulmaz.

Sentetik belgede kira/depozito tutarları, ödeme olumsuzluğu ve tarih özet içinde
korundu. Olmayan esas numarası istendiğinde bulgu üretilmedi ve açık hata
bildirildi. Beş açık doğru/yanlış belge iddiasında (tutar ilişkisi, tarih
ilişkisi, olumsuzluk ve uydurma sonuç dahil) son denetim beklenen sonuç verdi.
Bu olumlu örnekler yukarıdaki iki kalite açığını ortadan kaldırmaz.

Gerçek özel belgeler okunmadı, yeniden aktarılmadı, modele gönderilmedi.
Gerçek Word/Drive oturumu ve canlı arayüzde görsel kabul yapılmadı.

## Kanıt dosyaları (yerel; git dışında)

- `.local/ai-audit-current-python.xml`
- `.local/ai-audit-current-web.xml`
- `.local/ai-audit-current-browser.xml`
- `.local/ai-audit-current-database.xml` ve `ai-audit-current-database.log`
- `.local/ai-audit-current-live.json`
- `.local/ai-audit-current-controls.json` (ilk kısa fixture koşusu)
- `.local/ai-audit-current-controls-v2.json` (açıklanmış kaynak/metadata varyantı)
- `.local/ai-audit-current-relations.json` (üç talimat tekrarı ve uzun belge)
- `.local/ai-audit-current-document-qa.json` (7 belge soru-cevap senaryosu)
- `.local/run_ai_audit_database.py`, `check_ai_live_controls.py`,
  `check_ai_relation_controls.py`, `check_ai_document_qa.py` yeniden
  çalıştırma araçlarıdır.

Ticari kabulden önce P1 bulguları kapatılmalı, aynı olumsuz örnekler
korunarak tekrar koşulmalı ve avukat tarafından bağımsız cevap değerlendirmesi
yapılmalıdır. Kaynaklı olma, hukuki tamlık ve işe yararlık farklı ölçülerdir.
