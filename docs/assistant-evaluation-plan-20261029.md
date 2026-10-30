# Asistan değerlendirmesi: ücretsiz regresyon ve sınırlı canlı karşılaştırma

## Kullanım ve ayrım

`scripts/assistant_eval.py` varsayılan olarak yalnız 10 sentetik kamu hukuku
sorusunu ve low/medium/high karşılaştırma matrisini yazdırır. Anahtar okumaz,
model veya veritabanı çağırmaz. Özel belge/kişi, kayıtlı sohbet ve dava verisi
bu pakete eklenmez.

```powershell
.\.venv\Scripts\python.exe scripts/assistant_eval.py
.\.venv\Scripts\python.exe scripts/assistant_eval.py --sources --output .local/yeni-kaynak-raporu.json
.\.venv\Scripts\python.exe scripts/assistant_eval.py --replay .local/onceden-kaydedilmis-canli-rapor.json
```

`--sources` gerçek yerel korpusta **salt okunur transaction** ile yalnız madde
ipucu hattını ve beklenen referanslara doğrudan erişimi ölçer. Tam asistanın
anlam/anahtar kelime/karar aramasının yerine geçmez. On sorunun beşinde ipucu
hattı bütün beklenen maddeleri verdi; 13 beklenen maddenin tamamı ayrı doğrudan
referans kontrolünde doğrulanmış olarak bulundu. Bu sonuç başka maddelerin
eksiksiz veya cevapların doğru olduğunu kanıtlamaz.

`--replay` kaydedilmiş gerçek çıktıları ücretsiz yeniden puanlar. Modeli
yeniden üretmez; yeni prompt/model sürümünün daha iyi olduğunu kanıtlamaz.

## Canlı koşu: kullanıcı bütçesi olmadan başlatılmaz

```powershell
# AMOUNT yerine yalnız kullanıcının bu test için onayladığı toplam USD sınırı.
.\.venv\Scripts\python.exe scripts/assistant_eval.py --live --budget-usd AMOUNT --output .local/yeni-canli-rapor.json
```

- Mevcut OpenRouter GPT-6 Luna kullanılır; başka modele sessiz geçilmez.
- Yeni ödeme, bakiye yükleme, hesap/anahtar limiti değiştirme yoktur.
- Her model çağrısından önce muhafazakâr maliyet rezervasyonu yapılır.
  Güncel OpenRouter model fiyatı okunur; desteklenmeyen ek fiyat kalemi
  görülürse durur. Bu pilotta tek çağrı çıktı sınırı 16384'tür; üretim
  ayarları değişmez. Düşünme tokenları da bu sınırın içindedir.
- Planlayıcı, yazar, bağımsız denetçi ve onarım çağrıları aynı sayaca dahildir.
  Dönen gerçek `usage.cost`, tokenlar, düşünme düzeyi ve süre kaydedilir.
  Maliyet kayıpsa veya çağrı hata verirse rezervasyonun tamamı tüketilmiş
  sayılır ve koşu durur; bağlantı hatası sonrası harcama belirsizliği saklanmaz.
- Her soruda/çabada sohbet geçmişi boştur ve cevap önbelleği temizlenir.
  Mod sırası sorular arasında döndürülür; low her soruda ilk soğuk çağrı olmaz.
  Sağlayıcı prompt önbelleği temizlenmiş sayılmaz; gerçek usage raporlanır.
- Kullanıcı sohbeti yazılmaz. Resmî web ingestion bu test sürecinde kapalıdır;
  canlı uygulamanın ayarları değişmez. Dolayısıyla bu, tam HTTP/arayüz veya
  resmî web adaptörü gecikme testi değildir.
- Sağlayıcı başarısızsa yerel model/embedding duraklatma yoluna düşülmez.
- Anahtar, başlıklar ve ham exception metni rapora/loga yazılmaz.
- Koşu yarıda dursa da tamamlanan sonuçlar ve maliyet raporda korunur.

## Puanlama ve uzman değerlendirmesi

Otomatik puan: kaynaklı cevap, beklenen **aynı kanun–madde çiftinin** atıfta
bulunması, doğrulanmamış atıf/işaret yokluğu ve boş olmayan cevap.
Kelimenin kaynak alıntısında bulunması, sorunun cevaplandığı sayılmaz.
`grounded=true` veya denetçi coverage bayrağı tek başına hukuki doğruluk değildir.

Her soruda alt konu listesi vardır. Uzman aşağıdakileri incelemelidir:

1. Her alt soru gerçekten cevaplanmış mı?
2. Süre/tutar/istisna ve olayın şartları doğru mu?
3. Atıf gerçekten cümlenin hukuki sonucunu destekliyor mu?
4. Tarihsel karar güncel kuralmış gibi sunulmuş mu?
5. Eksik bilginin istendiği yer doğru mu, ilgisiz genişleme var mı?

Uzman incelemesi yapılmadıkça rapor `expert_review=pending` kalır. Başka bir
modelin otomatik puanı avukat onayı gibi sunulmaz. Bu iş bir model eğitimi
değil; kod/prompt/arama değişiklikleri için sabit regresyon ölçümüdür.

## Ücretsiz doğrulama ve kalite kontrolleri

Değerlendirme aracı için 24 test: bütçe girişleri, eşzamanlı rezervasyon,
çağrı öncesi durma, bilinmeyen maliyet, writer+auxiliary sayımı, anahtar
sızdırmama, varsayılan ücretsiz CLI, referans çiftleri ve uzman onayının
otomatik verilmemesi. Mevcut kaynak/sohbet/güvenlik testleri korunur.

Lint biçimlendirmeleri ve 19 tip/regex hatası düzeltildi; kurallar
kapatılmadı. Son lint sonucu **0 hata, 23 uyarı**; uyarılar sıfırmış gibi
raporlanmaz. Eklenti ZIP'leri kaynak biçimlendirmesi sonrasında yeniden
paketlendi; 574 arayüz testi geçti. Tip kontrolü ve üretim derlemesi geçti.

Kanıtlar `.local/eval-sources-direct-20261029.json`,
`.local/frontend-format-recheck-20261029.log`,
`.local/lint-final-20261029.log`, `.local/build-format-20261029.log`.
Canlı koşu 0,25 USD onayından sonra tamamlandı: 30 cevap, gerçek maliyet
0,149892995 USD. Ayrıntılar `docs/luna-live-comparison-20261029.md` içinde.

Yeni testler dahil son izole backend koşusu: **3217 geçti, 0 başarısız,
0 atlanan** (82,48 sn). Önceki 155 Chromium testi bu biçimlendirme koşusunda
tekrar çalıştırılmadı; güncel 574 arayüz testi içinde paket-kaynak eşitliği
yeniden doğrulandı. Başka koşudaki sonuç yeni koşuda çalışmış gibi sayılmadı.

OpenAI Docs: [GPT-6 Luna](https://developers.openai.com/api/docs/models/gpt-6-luna).
Dokümandaki düşünme düzeyleri kullanıldı; görünmeyen düşünme tokenları da
maliyete dahil olduğundan yalnız görünen cevap uzunluğu kıyaslanmaz.
