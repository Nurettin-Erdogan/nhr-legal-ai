# Üretimden bağımsız kaynak arama denetimi

27 Ekim 2026. `scripts/audit_retrieval_cases.py`: üç sabit kamu sorusu,
gerçek yerel embedding/arama, **sıfır bulut üretimi**, kayıtlı sohbet yazısı yok.
Veritabanında veri/index/servis değişikliği yapılmadı.

## Kanıtlanan bulgular

| Aşama | Ölçüm | Sonuç |
| --- | --- | --- |
| TBK 315 + Yargıtay isteyen soru, önce | yalnız `statute` kolu; iki madde, sıfır karar | açık madde adresi tüm aramayı erken bitiriyordu |
| Aynı soru, düzeltmeden sonra | 192 kelime-arama adayı; 187 karar parçası; son havuzda Yargıtay kararları | karar aramasını kapatan erken dönüş düzeltildi |
| Aynı sorunun süreleri | önce 2,90 sn; sonra 4,55 sn | ikinci ölçüm artık gerçek karar aramasını da içeriyor |
| Başka ifade: ihtarda fesih bildirimi | kelime kolu sıfır, ortak anlam kolu 3 sn zaman aşımı | ifade değişimlerine karşı arama henüz yeterince dayanıklı değil |
| Kira arabuluculuğu | 175 kelime adayı, 174 karar parçası; 18/A ve 18/B de mevcut | veri tamamen yok değil |
| Ortak ANN anlam kolu | indeks hazır; bu üç ölçümde 3 sn zaman aşımı | hazır indeks tek başına performans kanıtı değil; sorgu planı/I/O ayrıca incelenmeli |
| 18/B ana parça | 1798 karakter; kuyruk `Tapu müdürlüğünce taşınmaza` | madde cümle ortasında parçalanmış; mevcut güvenli kanıt yolu parçayı reddediyor |

18/B'nin sonraki parçası 141 karakter ve tam cümle olarak kullanılabilir; ana
kural önceki parçada olduğundan yalnız bunun kalması soruyu karşılamıyor.
Bu kuyruk sessizce kesilmedi, doğrulama kapısı gevşetilmedi. Sonraki çözüm
aynı doğrulanmış sürümün tam madde/cümle bağlamını güvenli biçimde geri getirmek.

## Değişiklik

`retrieve_contexts`: açık madde adresi **ve içtihat talebi birlikteyse** madde
okunduktan sonra karar aramasına devam edilir. Yalnız madde metni sorularının
tek kesin lookup davranışı korunur; birden çok madde için de regresyon var.
Özel kullanıcı verisi, kaynak doğrulama ve tarih filtreleri değiştirilmedi.

## Sınırlar

187 sayısı bütün korpustaki ilgili karar sayısı değil, bu çağrıdaki aday karar
parçası sayısıdır. Aday bulunması, her adayın sorudaki hukuki önermeyi kanıtladığı
veya üretimin başarılı olduğu anlamına gelmez. Bu turda ücretli canlı cevap
üretilmedi; ANN gecikmesinin kök nedeni henüz belirlenmedi.
