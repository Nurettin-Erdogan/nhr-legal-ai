# AI olgu ve kapsam güvenliği — 15.10.2026

Bu çalışma `ai-quality-audit-20261015.md` içindeki belge soru-cevap ve dar kapsam
bulgularına yönelik ilk düzeltme paketidir. Genel hukuki doğruluk veya ticari
yayın kabulü değildir. Gerçek kullanıcı belgeleri ve canlı UYAP kullanılmadı.

## Değişiklikler

- Özet doğrulaması küçük sayıları da kontrol eder; `100.000` artık `1.100.000`
  içinde bulunmuş sayılmaz. Sayının para birimi, süre birimi, yüzde niteliği ve
  işareti ayrı korunur. Kur/dönem/tarih dönüşümü yapılmaz.
- Belge kanıt seçiminde sorunun konusu ve istediği bilgi türü ayrı denetlenir.
  Tutar, “ödendi mi?” sorusunun cevabı değildir; kira tarihi depozito tarihi
  olarak kullanılamaz. Kısa ödeme olumsuzlukları aday listesinde korunur.
- Açıkça adıyla istenen belge türü erişilebilir arama sonuçlarında yoksa
  başka belge veya kamu kararıyla ikame edilmez. 422 yanıtı, belgenin tüm
  hesapta bulunmadığı iddiasında bulunmadan seçilmesini/okunmasını ister.
  Bu kapı dava, seçili belge ve çekirdek proje kapsamında uygulanır.
- Aynı cümlenin farklı belgelere ait kimlikleri korunur. Açık iki-belge
  karşılaştırması tek belgeden atıfla tamamlanmış kabul edilmez.
- Dar analiz talimatı doğrulayıcıya BELGE'den ayrı verilir; yalnız/sadece
  kapsamındaki konu dışı maddeler ve karışık olgu cümleleri kodda da elenir.
  Talimattaki sayı/isimler kanıta katılmaz. Denetçi yalnız eleme yapar.
- Ödenmiş/ödenmemiş karşıtlığı ve koşullu ödeme ifadeleri için ek kod kapısı
  vardır. Aynı özneye ait çelişen ödeme durumlarında tahmin yapılmaz.

## Tekrar çalıştırma

Son kaynaklarla bu turdaki sonuçlar:

| Kontrol | Sonuç |
| --- | --- |
| Yeni olumsuz/olumlu regresyon paketi | 49 test geçti |
| Tam Python paketi (sahte DB URL, DB/tarayıcı opt-in kapalı) | 1518 geçti, 392 atlandı, 1 bağımlılık deprecation uyarısı |
| Web birim testleri | 468 geçti |
| Yerel model sentetik kabulü | 10/10 geçti (7 QA + 3 analiz tekrarı) |
| `git diff --check` | Temiz |

Atlanan Python testleri geçti sayılmaz; DB/RLS ve gerçek tarayıcı kabulü bu
koşuda etkin değildir. Bu tur web kaynakları değiştirilmedi.

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_ai_fact_safety.py -q
.\.venv\Scripts\python.exe scripts/eval_document_fact_safety.py
```

İkinci komut yalnız localhost Ollama'ya izin verir; veritabanını, gerçek belgeyi,
bulut sağlayıcısını veya çalışan API'yi kullanmaz. JSON sonuçlarını stdout'a
yazar, başarısız kabulde çıkış kodu 1 döndürür. Model adını ortamın mevcut
ayarından alır; model/sağlayıcı ayarı değiştirilmez.

Yerel `qwen3.5:4b` koşusunda 7 soru-cevap örneği ve dar kapsamlı analizin üç
tekrarı geçti (10/10). Kaynakta olmayan depozito tarihi ve yalnız taraf talebi
bulunan karar sorusunda güvenli yetersizlik beklenir. Yetersizlik örneklerinde
aday yoksa model çağrısının atlanması doğrudur.

## Sınırlar ve etkinleştirme

- Bunlar sınırlı sözlüksel güvenlik kapılarıdır; bütün Türkçe soru türlerini,
  kişi-tarih ilişkilerini, kronolojiyi veya hukuki çıkarımları çözmez.
- Özet/analiz hâlâ paraphrase üretir ve ayrı model denetimine tabidir. Ödeme
  durumu kabul ölçüsü olumsuz anlamı kontrol eder; belirli bir çekim ekinin
  aynen kullanılmasını zorunlu tutmaz. Kronoloji bağımsız kabul gerektirir.
- Aynı belge türündeki farklı adları kesin çözümlemek ve geniş/çok belgeli
  sorularda eksiksizlik ayrıca geliştirilmelidir. Aramada bulunamayan ad için
  güvenli ret, dosyanın depoda bulunmadığının kanıtı değildir.
- Kaynak uygunluğu, resmî/üçüncü taraf ayrımı, kullanıcı izolasyonu ve
  sağlayıcı arayüzü değiştirilmedi. Migration gerekmez.
- Çalışan API bu tur yeniden başlatılmadı. Otomatik yeniden yükleme yoksa
  mevcut işlemler bittikten sonra API'nin yeni kodla başlatılması gerekir.
- DB/RLS ve canlı UYAP kabulü bu düzeltme turunun kapsamında değildir.
