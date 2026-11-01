# 3. adım — Kanıt bağlantısı onarımının akışa bağlanması

## Yapılan değişiklik

`api/ai/free_answer.py` artık istek içinde, taslağın bağlandığı gerçek birimler
için chunk/source kimliği, kaynak sürümü/revizyonu, yürürlük tarihleri ve
metin/birim hash'lerini tutar. Bunlar log veya kalıcı korpus kaydı değildir.

Bir cümle elenince onarım isteğine şu bilgiler birlikte gider:

- Orijinal cümle kimliği ve reddedilen metin (kanıt değildir).
- Mekanik ret ve varsa aynı cümleye ait denetçi gerekçesi.
- Önceki başarısız bağlantının mevcut kaynak listesindeki karşılığı.
- Bağlantının değişmeden çözülebildiği veya artık çözülemediği bilgisi.

Önceki bağlantılar **önerilen/doğru kanıt** diye sunulmaz. Model, eksik
nitelemeyi gerçekten taşıyan birimleri mevcut `sources` içinden seçmek
zorundadır. Kod otomatik yeni bir hukuki dayanak tahmin etmez. Kaynak liste
sırası değişirse yalnız aynı kimlik, sürüm ve metinle eşleşen birim numarası
yeniden çözülür. Sürüm/metin değişirse veya kaynak kaybolursa eski numara
kopyalanmaz; bağlantı `unresolved` olur.

Yeni cümle, korunan cümlelerle birleştirildikten sonra yine bütün mekanik
kontrollerden ve bağımsız anlam denetiminden geçer. Deneme/LLM çağrısı bütçesi
artırılmadı, doğrulanmamış taslak yayını açılmadı ve özel kapsamın buluta
gitmesini sağlayan bir yol eklenmedi.

## Kanıtlananlar

Kontrollü sahte sağlayıcılı uçtan uca fixture:

1. Asgari sınır birimine bağlanmayan cümle reddedilir.
2. Onarım isteği yanlış bağlantıyı ve `minimum_added` nedenini alır.
3. Sahte sağlayıcının doğru iki birimi bağlayan cevabı yeniden denetlenir.
4. Aynı bağlantıyla dört yerine beş gün yazılırsa cümle yine reddedilir.

Ek testler kaynak sırasının, revizyonunun, metninin değişmesini ve kaynağın
kaybolmasını kapsar. Bunlar onarım **orkestrasyonunu** kanıtlar; gerçek Luna'nın
bu talimatla her seferinde başarılı olduğu anlamına gelmez.

## Test / devreye alma durumu

İlgili sayı, sentez, serbest cevap, onarım, kaynak seçimi, değerlendirme ve
tanılama paketleri: **473 geçti, 0 başarısız, 0 atlanan**.

Yeni ücretli model çağrısı yok, API yeniden başlatılmadı. Değişiklik henüz
çalışan API'ye uygulanmış veya canlı cevapla doğrulanmış sayılmaz. Bu turda
bütün veritabanı/tarayıcı paketleri yeniden çalıştırılmadı.

Sıradaki iş: gösterilen son cümleler ile sorunun alt başlıkları arasındaki
kapsam kontrolü; yalnız kaynağın bulunmasını cevaplanmış saymamak.
