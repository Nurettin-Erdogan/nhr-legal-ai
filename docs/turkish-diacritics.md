# Türkçe karakter geri getirme (ASCII yazılmış sorular)

Avukatlar sorularını sık sık Türkçe karakter olmadan yazar: "davaci kac yil calismis", "kidem tazminati
sartlari". Arama dizini (`turkish` tsvector) ve cümle puanlaması aksanları katlamaz; "kidem" ile "kıdem"
farklı sözcüklerdir. Ölçüm (canlı korpus, değişiklikten önce): bu üç tür soru **0 sonuç** döndürüyordu,
düzgün yazılanlar 73–80 sonuç. Belge sohbetinde de model hiç çağrılmadan "yeterli bilgi yok" deniyordu.

28 milyon parçalık dizini yeniden kurmak mümkün değil. Bu yüzden aksanlar **sorgu tarafında** geri getirilir.

## Yöntem (`api/ai/turkish_text.py`)

- Resmî hukuk metinlerinden çıkarılmış bir sözlük (`api/ai/resources/tr_diacritics.json.gz`, ~300 KB):
  her ASCII biçim için en sık Türkçe biçim ("davaci" → "davacı").
- "ise/işe", "sık/sik" gibi gerçekten belirsiz sözcükler komşu sözcüklere bakılarak seçilir:
  "**ise** iade davası" → "işe iade davası", ama "davalı **ise** haksız fesih" → bağlaç korunur.
- Kural tabanlı, yerel; ağ ve model gerektirmez, soru başına mikrosaniyeler.

Güvenlik ilkeleri:

- Soruda **zaten bir Türkçe harf** varsa metne dokunulmaz (kullanıcı Türkçe yazıyor).
- Yalnız **arama metni** değişir; kullanıcının yazdığı soru olduğu gibi saklanır ve gösterilir.
- Sözlükte olmayan sözcük, kısaltma (TBK, HMK), sayı, noktalama ve kesme işareti/rakamdan sonraki ek
  ("Yargıtay'ın", "30'uncu") değişmez. Büyük/küçük harf biçimi korunur.
- Sözlük dosyası yoksa metin olduğu gibi döner; arama bozulmaz.

## Nerede uygulanır

| Yol | Not |
| --- | --- |
| Cevap hattı (`api/ai/pipeline.py`) | `search_question` (arama, kanıt seçimi, doğrulama) ve cevap üretimine giden soru. Üretime giden soru da geri getirilmelidir: kanıt cümlelerini seçen alaka filtresi aksanlara duyarlıdır, aksi halde tüm cümleler elenir. |
| Araştırma sayfası (`/api/ai/sources`) | Arama metni geri getirilir, `query` yazıldığı gibi döner. |
| Hukuk araması (`/api/legal/search`) | Aynı. |

Ölçüm (canlı API, değişiklikten sonra): "kidem tazminati sartlari" → 80 sonuç, düzgün yazılanla **aynı** sonuçlar
ve aynı ilk karar; "haksiz fesih isci tazminat" 77/77; "tuketici hakem heyeti basvuru siniri" 73/73.

## Doğruluk (ayrı tutulan kaynaklarla ölçüldü)

Sözlük kaynakların `hashtext(id) mod 10 < 8` kısmından kurulur, doğruluk `= 9` kısmında (hiç görülmemiş
metinde) ölçülür: her metin ASCII'ye çevrilir, geri getirilir, orijinalle karşılaştırılır
(şapkalı/şapkasız fark hata sayılmaz, arama zaten `â→a` eşitler).

| Ölçü | Sonuç |
| --- | --- |
| Türkçe karakterli sözcüklerin doğru geri getirilmesi | **%97,9** |
| Zaten ASCII olan sözcüğün yanlışlıkla değişmesi | **%0,145** |

Kalan hatalar çoğunlukla anlamsız ek parçaları ("ncı", "uncu"), özel isimler (kişi/firma adları) ve gerçek
belirsizlikler ("diş/dış", "kısmi/kısmı"). Bunlar arama sonucunu pek etkilemez: birkaç yanlış harf, sorunun
diğer sözcüklerinin eşleşmesini engellemez.

## Sözlüğü yeniden kurma

```powershell
.\.venv\Scripts\python.exe scripts\build_tr_vocabulary.py             # kur ve ölç
.\.venv\Scripts\python.exe scripts\build_tr_vocabulary.py --eval-only # yalnız ölç
```

Yalnız `ingest_status = 'ready'` (resmî portalla doğrulanmış) kaynaklar **salt okunur** okunur; korpusa veri
alınmaz, yalnız sözcük sıklıkları sayılır. Örneklem tekrarlanabilirdir (`setseed`). Korpus büyüyünce ya da
ölçülen doğruluk düşünce yeniden kurulmalıdır.

## Bilinen sınırlar

- Bağlamsız tek sözcük belirsizliği ("ise" yalnız başına) ya bağlaç olarak korunur ya da komşu sözcükle çözülür.
- Büyük `I` ile başlayan sözcükler sözlük eğitiminde atlanır ("Idare" = noktasız yazılmış "İdare" ya da "Işık"
  olabilir); sorguda yine de `I` küçük `i` gibi aranır.
- Doğru yazılmış ama kısmen ASCII karışık sorulara (tek bir Türkçe harf varsa) dokunulmaz.

## Testler

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_turkish_text.py -q
```
