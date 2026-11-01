# Cevaptaki kararın meseleyle ilişkisi ve görünür künyesi

27 Ekim 2026. Kullanıcı, TBK 315'e göre fesih uyarısının eksikliği sorusuna
verilen cevaptaki ödeme süresi kararının ilgisini ve karar künyesini geliştirmeyi istedi.

## Uygulananlar

- Yazara ve bağımsız denetçiye, aynı kanunu/maddeyi anmanın tek başına sorulan
  hukuki meseleye emsal olmadığı açıklandı. İhtarın belli fesih/tahliye yoluna
  yetersizliği, tüm amaçlar için geçersizlik sonucuna genişletilmemeli.
- Normal sohbetin cümle denetiminden önce dar bir kontrol eklendi: kendi
  anlatımı içinde "bu karar ... ele almıyor / değerlendirme içermez" diyerek
  ilgisiz bir karar anlatan dolgu cümlesi elenir. Belirli kararın uygulanabilirliğini
  veya kararlar arası farkı soran sorularda bu açıklama korunur.
- Onaylanan cümlede açıkça anılan tek bir doğrulanmış karar varsa, E./K.
  numarası mevcut kaynak metadatasından görünür biçimde eklenir. Birden çok
  karar, eksik künye veya doğrulanmamış kayıt için numara üretilmez.
- Kaynak kontrolü ve bağımsız denetçi aynen durur. Bu regex genel bir hukuki
  ilgililik çözücüsü değildir; kendini açıkça ilgisiz ilan etmeyen hatalı
  analojileri bağımsız denetçi hâlâ değerlendirmek zorundadır.

## Test

- Odaklı 54 test geçti. Daima onaylayan sahte denetçiyle dahi ilgisiz dolgu
  cümlesinin yayınlanmadığı ve karşılaştırma istisnası sınandı.
- Ağ kapalı tüm Python paketi: **2660 geçti, 442 atlandı, 1 deprecation uyarısı**.
  Test DB'si etkin değil; ücretli model çağrısı yapılmadı. Bu sonuç gerçek
  modelin her soruya doğru cevap vereceği anlamına gelmez.
- İki veri taramasının canlı olduğu doğrulandı; metin/hash bütünlüğü taraması
  1.304.500 kayda ulaştı (anlık sayı). Bu resmî metin karşılaştırması değildir.

Kullanıcı aktif işlem olmadığını onayladıktan sonra API son değişikliklerle
yeniden başlatıldı; `/health` 200 döndü. Commit/push yapılmadı.
