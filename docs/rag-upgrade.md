# RAG iyileştirmesi — 27 Eylül 2026

## Etkin yerel kurulum

`AI_PROVIDER=qwen`, `AI_MODEL=qwen3.5:4b`, `RAG_QUERY_EMBEDDING=true`,
`RAG_CONTEXT_CHARS=2400`, `RAG_EXPLANATIONS=true`, 4096 bağlam / 768 çıktı tokenı.
Embedding **değişmedi**: Ollama `nomic-embed-text`, 768 boyut. DeepSeek kodu ve
modeli geri dönüş için korunur. `.env` Git'e dahil edilmez.

## Değişiklikler ve sınırlar

- Doğrulanmış olmak ile soruyu yanıtlamak ayrıldı. TÜFE/kira artışı sorusuna
  balıkçı barınağı feshi alıntısının geçmesi regresyon testiyle engellendi.
  Aynı kontrol eski önbellek cevaplarına da uygulanır. Önceki sohbetler silinmez.
- Bilinen konular için mevzuat maddesi **arama ipucu** kullanılır; mevzuat
  numarası tek başına delil sayılmaz. Kayıt mevcut, uygun sürümde ve mevcut
  resmî doğrulama filtresinden geçmiş olmalıdır. İpuçları hukuki cevap değildir.
- Önce doğrudan mevzuat ve anlamsal adaylar aranır. Uygun aday bulunursa pahalı
  genel FTS sıralaması cevap yolunu bloke etmez. Gerekirse konu koşullarını
  koruyan FTS çalışır; bütün kelimeleri OR ile gevşeten otomatik yol kaldırıldı.
- ANN önce mesafeye göre sınırlandırılır, ardından adaylar sıralanır. Embedding
  modeli filtresi, zaman/sürüm filtresi ve RLS korunur. Özel belgelerin RLS yolu
  değiştirilmedi. Bu, tüm kaynakların eksiksiz getirildiği iddiası değildir;
  yaklaşık komşuluk ve henüz embedding'i olmayan kayıtlar recall sınırıdır.
- Her sorgunun ayrı zaman bütçesi var (mevzuat 3 s, semantic 3 s, FTS 4 s).
  Başarılı kaynaklar isteğe bağlı bir dalın hatası yüzünden atılmaz. Sonuç
  bulunamayıp arama zaman aşımına uğradıysa hata gizlenmez. Disk/işletim sistemi
  yükünde PostgreSQL iptalinin duvar saati gecikmesi bütçeyi aşabilir.
- Doğrulanmamış kayıtlar modele/cevaba alınmaz; mevcut sorgu anı doğrulaması
  başarılı olursa kullanılabilir. Ölçüm scripti salt okunurdur ve doğrulama yapmaz.
- Açıklama önce tam, doğrulanmış alıntılardan atomik iddialar önerir. Atıf
  kimlikleri/sayılar kodla, destek/konu/kapsam/koşul korunumu ayrı model çağrısıyla
  kontrol edilir. Başarısızsa alıntı korunur. Bu bir **hukuki doğruluk garantisi
  değildir**; aynı yerel modelin denetimi bağımsız uzman değerlendirmesi yerine geçmez.
- Gerçek kıdem örneğinde denetçi listeden düşen koşulları kaçırdı. Bu nedenle
  üç veya daha fazla numaralı koşul içeren alıntılar özetlenmez. Kaynak içindeki
  bazı açık istisna cümleleri seçime eklenir; bu kural tüm istisnaları bulduğu
  iddiasını taşımaz. Yeni konu ve karşı-örneklerle değerlendirme sürdürülmelidir.
- Ortak velayet örneğinde model olay tespitlerini genel kurala dönüştürmeye
  çalıştı. Açık somut olay/tespit ifadeleri de açıklama dışında tutulur, aynen
  alıntılanır ve kapsam uyarısı gösterilir. Süre sorusunda süre bulunamazsa bu
  eksik ayrıca belirtilir; diğer şartları açıklamak tam cevap sayılmaz.

ANN sorgu biçimi [pgvector sorgulama belgeleri](https://github.com/pgvector/pgvector#querying)
ile uyumlu doğrudan mesafe sıralaması kullanır. Yerel JSON çıktısı
[Ollama chat API](https://docs.ollama.com/api/chat) üzerinden istenir.

## Gerçek ölçümler

Arka plandaki veri toplayıcıları durdurulmadı. Sonuçlar bu bilgisayarın değişken
yükünde ölçüldü; laboratuvar karşılaştırması veya hız garantisi değildir.

İlk lexical-only turunda 7 sorunun 7'sinde ek FTS dalı zaman aşımına uğradı;
mevzuat bulunan sorular kaynaklarını korudu. Semantic-first sıcak turunda
0,28–2,43 s görüldü, fakat sonraki yük testlerinde yeniden zaman aşımı oluştu.
Yalnız hızlı tur seçilerek raporlanmamıştır.

Son 7 soruluk retrieval turu (`rag-upgrade-release-20260927.json`):

| Soru | Arama + soru vektörü | Doğrulanmış bağlam | Sonuç |
| --- | ---: | ---: | --- |
| TÜFE/kira | 7,02 s | 1 | Semantic dalı zaman aşımı; mevzuat korundu |
| İtirazın iptali | 2,96 s | 6 | Başarılı |
| Ortak velayet | 1,60 s | 4 | 2 pending kayıt dışlandı |
| Kıdem tazminatı | 0,75 s | 6 | Başarılı |
| Yıllık izin/ispat | 1,04 s | 0 | Bulunan 6 aday pending; doğrulamasız gösterilmedi |
| İdari dava süresi | 0,65 s | 6 | Başarılı; konu eşleşmesi cevap yeterliliği değildir |
| AYM başvuru | 0,53 s | 6 | Başarılı; konu eşleşmesi cevap yeterliliği değildir |

HTTP smoke: `/health` ve `/api/ai/status` 200; etkin sağlayıcı Qwen, semantik
arama açık. Kira sorusu **19,58 s / HTTP 200**, icra sorusu **6,37 s / HTTP 200**;
ikisinde de resmî atıflı açıklama döndü. Bunlar uçtan uca sürelerdir; yukarıdaki
arama süreleriyle karıştırılmamalıdır. Kira çıktısında önceki barınak kaynağı yok.

Altı sentetik açıklama denetimi (olumlu kontrol, olumsuzluk, koşul atlama, taraf
iddiası, uydurma sonuç, ilgisiz konu) son turda 6/6 geçti. Küçük set nedeniyle
genellenemez; uzun liste kör noktası ayrıca kodla kapatıldı.

Son dondurulmuş cevap turunda 7 sorudan 6'sı kaynak metni denetiminden geçti;
yıllık izin sorusu doğrulanmış bağlam olmadığı için cevaplanmadı. Bu **6/7
hukuki doğruluk skoru değildir**. AYM örneği süreyi yanıtlamıyordu; artık bu
eksik kullanıcıya açıkça belirtilir. Ortak velayet örneğindeki genelleme riski
nedeniyle olay tespitleri serbestçe özetlenmez.

Git'e hazırlanan temiz kopya, korpustan ayrı ve yalnız test için oluşturulan
veritabanında **455 geçti / 1 atlandı** sonucu verdi. Geçici test veritabanı
test sonunda kaldırıldı. Tarihsel metin parçasının retrieval'da korunması da
bu DB turunda doğrulandı; üretimde yalnız tam kaynak cümleleri kullanılmaya devam eder.

## Tekrarlama

```powershell
.\.venv\Scripts\python.exe -m scripts.eval_rag_upgrade --output data/benchmarks/yeni-lexical.json
.\.venv\Scripts\python.exe -m scripts.eval_rag_upgrade --hybrid --output data/benchmarks/yeni-semantic.json
.\.venv\Scripts\python.exe -m scripts.eval_rag_answers --fixture data/benchmarks/yeni-semantic.json --output data/benchmarks/yeni-cevaplar.json
```

Scriptler mevcut raporların üzerine yazmaz. Gerçek kaynaklar dondurulur;
sentetik denetimler gerçek hukuk verisi olarak kaydedilmez. Ham raporlar
`data/benchmarks/` altında, Git dışında tutulur. Sayılar yalnız atıf eşleşmesi
ve konu sinyallerinden bir hukuki doğruluk yüzdesi üretmez.

## Devam eden işler

Özellikle yoğun disk yükündeki kuyruklanma, lexical fallback gecikmesi, doğrulama
bekleyen yıllık izin adayları ve kaynakların sorunun tamamını karşılaması hâlâ
izlenmelidir. Eksik veya doğrulanamayan kaynaklar için uydurma cevap üretilmez.
Bu değişiklikler üretim hazırlığının tamamlandığı anlamına gelmez.
