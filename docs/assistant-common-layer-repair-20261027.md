# Ortak asistan hattı incelemesi — 27 Ekim 2026

Bu tur soruya özel hukuki cevap eklemek yerine gerçek hata günlüğü, bütün
konu–madde ipucu tablosu ve sağlayıcı sözleşmesi incelendi. Ücretli model çağrısı
yok; yeni canlı cevap üretilmedi. Kullanıcı sohbetleri topluca okunmadı/değiştirilmedi.

## Kanıtlanan sorunlar

1. API günlüğündeki son başarısız normal cevap:
   `reason=checker checker=invalid_or_not_source_only attempts=2 sentences=4`,
   cümle sonuçlarında kod reddi 0, içerik reddi 0, onay 0.
   Bu log **biçim hatası ile source_only/clarification_safe=false reddini ayıramıyor**.
   Ham eski denetçi cevabı kaydedilmediği için hangisinin olduğu geriye dönük
   kesin söylenemez. 'Veri bulunamadı' teşhisi de bu logdan çıkmaz.
2. Tüm konu–madde eşleme taraması 7 uyumsuzluk verdi. Bazıları PDF satır sonu
   yüzünden `ayrım\nyapılamaz` gibi ifadelerin eşleşmemesi, bazıları madde
   gövdesinde bulunmayan bölüm başlığına dayanılmasıydı.
3. Tam madde sorguları kanun/madde no ile sınırlıydı, belge türü bağlı değildi.
   Canlı DB'de 2004/67 ve 2004/68 için hem `law` güncel kanun hem `other`
   'İCRA VE İFLAS KANUNUNUN YÜRÜRLÜKTEN KALDIRILMIŞ HÜKÜMLERİ' var.
   İpucu sorgusu sırasız LIMIT 1 ile tarihsel derlemeyi seçebiliyordu.

## Ortak düzeltmeler

- `search_plan.normalize` boşluk/satır sonlarını tekilleştirir. Sayıların
  içindeki boşluğu birleştirmez, kelime/polarite değiştirmez. Bu yalnız arama
  normalizasyonudur; ham resmî metin yeniden yazılmadı.
- `STATUTE_RETRIEVAL_SQL`, liste tam madde ekleme ve konu ipucu sorgusu,
  `legislation_type IN ('law','constitution','decree')` ile bağlıdır.
  Diğer mevzuat türleri genel aramadan silinmedi; tam kanun maddesi yerine
  aynı numaralı tarihsel/başka tür belge geçemez.
- Gövdeden doğrulanmış kısa arama ifadeleri kullanıldı. TBK 344'ün uzun çapa
  cümlesi, aynı cümlenin benzersiz başlangıcına kısaltıldı; hukuki kuralı hâlâ
  kaynak metni sağlar. Sabit cevap veya modelden bilgi ekleme yok.
- `checker_protocol.py`: biçim, id, gerçek boolean, kaynak politikası reddi ve
  güvenli netleştirme reddi ayrılır. Hiçbir false/string/eksik alan onaya
  çevrilmez. Biçim hatasında yalnız aynı kanıt yükü bir kez yeniden denetlenir.
  Bu tekrar tam cevap+denetçi tekrarının yerini alır; ek dış döngü yok.
  Tekrar yine bozuksa cevap yayınlanmaz, teknik doğrulama hatası açıklanır.
- Güvenli loglara yalnız kategori ve deneme sayıları girer; ham cevap, kişisel
  veri, kaynak gövdesi veya gizli bilgi eklenmedi.

## Sonuç ve kalan sınırlar

Tüm ipucu tablosu gerçek yerel DB üzerinde tekrar tarandı: **sorunlu satır 0**,
benzersiz çapa kontrolü geçen 26. Bu bütün mevzuatın doğru olduğunu kanıtlamaz.
Normalleştirme kelime içine PDF çıkarımından sızan `o rtalamalara` gibi boşlukları
bilinçli olarak tahminle onarmıyor; korpus/PDF çıkarım incelemesi ayrı iş.

Ön denetçi sözleşmesi ve adversarial testler 92 geçti. Son ağ kapalı tüm Python
paketi: **2708 geçti, 442 atlandı, 1 deprecation uyarısı**.
Ağ bariyeri kullanılır; DB entegrasyon testleri test DB'si
tanımlanmadığı için atlanır. Sahte sağlayıcılı testler gerçek modelin cevap
kalitesinin kanıtı değildir. Eski logun tam nedenini şimdi biliyormuş gibi
sunamayız; yeni sınıflandırma sonraki gerçek istekte bunu ayırt edecektir.

Kullanıcı aktif işlem olmadığını onayladıktan sonra API son değişikliklerle
yeniden başlatıldı; `/health` 200 döndü. Veri taramaları durdurulmadı.
Commit/push yok; önceki çalışma ağacı değişiklikleri korundu.
