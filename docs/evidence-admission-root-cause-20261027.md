# Kaynak bulunduğu hâlde cevapsızlık: kabul katmanı kök neden incelemesi

27 Ekim 2026. Kullanıcının rakip/yerel ekran karşılaştırması üzerine yapıldı.
Rakibin arka uç mimarisi, modeli ve cevaplarının hukuki doğruluğu bu ekranlardan
belirlenemez. Bu turda model değiştirilmedi veya ücretli üretim yapılmadı.

## Gerçek korpus ölçümü

İİK 50, 58, 62, 67, 68; İş Kanunu 1475/14 ve 4857/17, 18, 20 doğrudan
aynı güven/sürüm/tür filtreleriyle getirildi. **Dokuzu da bulundu; başlangıçta
yalnız biri `_usable` kaynak kabulünden geçti.** Dolayısıyla bu örneklerdeki
cevapsızlığın kaynağı temel maddelerin DB'de bulunmaması değildi.

Örneğin İİK 67 sonuna `b) İtirazın kesin olarak kaldırılması:28`, İş K. 17
sonuna `Feshin geçerli sebebe dayandırılması` sonraki bölüm başlıkları eklenmişti.
Kod bu tam maddeleri, sonundaki başlık bir tam cümle olmadığı için eliyordu.
Kanonik metni geri alma da aynı kabul kapısına takılıyordu. Bu engel modelden
öncedir; yalnız Luna'yı değiştirerek kaldırılmaz.

## Uygulanan düzeltmeler

1. Sonraki bölümün dar, biçimsel isim başlığı tam kanun maddesini tek başına
   geçersiz yapmaz. Kaynak metni writer/checker için korunur; başlık kanıt
   cümlesi sayılmaz. Koşul, istisna, olumsuzluk, normatif yüklem veya kural
   içindeki sayıyı taşıyan gerçek yarım cümleler hâlâ reddedilir.
2. Dipnot numarası cümle noktasına bitiştiğinde (`... kalkar.29`) cümle sınırı
   kaybolmaz; tarih/ondalık/baş harf kuralları korunur. Dipnot metni uydurulmaz
   veya sayılar silinmez.
3. Salt dilbilgisiyle başlık denemeyen ek yol: aynı tür/kanun numarasında
   sonraki maddenin TEK güncel başlığı, aynı resmî PDF URL'si ve document hash'i,
   her iki article_hash/content_hash eşleşmesiyle bağlanır. Yalnız birebir
   boşluk-eşdeğer son başlık kanıt dışı sunum metadata'sı sayılır. Böylece
   örneğin gerçek sonraki başlıkta 'değilse' yazması, önceki hükmün yanlışlıkla
   kaybolmasına yol açmaz. Kaynak/sürüm veya başlık belirsizse işlem yapılmaz.
4. Araştırma planı her alt soruya doğrulanmamış, sınırlı kanun/madde arama
   ipuçları verebilir. Bunlar cevap veya kanıt değildir; kod gerçek güncel
   resmî metni bulmadan kullanılamaz. Eksik araştırma mesajı artık tüm korpusta
   hüküm yokmuş gibi konuşmaz.
5. Sonraki gerçek istekler için kaynak kabul telemetrisi: bulunan/biçimce
   elenen/bütçeye sığmayan ve alt soruya kalan kaynak sayıları. Loglar yalnız
   sayısal/kategorik veri taşır, kaynak gövdesi veya kullanıcı metni içermez.

## Sonuç

- Aynı dokuz temel kaynak: **9/9 bulunuyor ve kabul ediliyor**.
- Yapılandırılmış tüm konu-madde/eşleme kaynakları, 70 benzersiz referans,
  model çağrısı olmadan topluca ölçüldü. Bu turdaki ilk genel başlık düzeltmesi
  sonrası 45 kabul/25 ret vardı; son kimlik-bağlı başlık düzeltmesiyle
  **58 kabul / 12 ret**, eksik DB kaydı 0.
- Kalan retler: 2004/257, 2918/85, 4721/1023; 6098/77,117,120,146,227,
  342,345,350 ve 6325/18-A. Çoğunda takip eden madde başlığı metadata'sı
  `Madde No: ...` veya boş olduğu için güvenli eşleştirme yapılamıyor.
  Bunlar zorla onaylanmadı; hepsinin düzeldiği iddia edilmez.
- Son telemetri ekinden sonra tüm test paketi de tekrar çalıştırıldı:
  2729 geçti, 442 atlandı, 1 deprecation uyarısı; ağ bariyeri etkin.
- Bu, kaynak kabul ölçümüdür. Aynı soruların gerçek modelle uçtan uca yeni
  cevapları bu turda üretilmedi. Model yeterliliği için sabit ve aynı kanıtla
  ayrı karşılaştırma gerekir; Luna'nın yetersiz olduğu kanıtlanmadı.

Araç: `scripts/audit_statute_admission.py` (`--details` yalnız kamu metni
sonlarını gösterir). Kullanıcı aktif işlem olmadığını onayladıktan sonra API
yeniden başlatıldı; `/health` 200 döndü. Veri taramaları durdurulmadı.
Commit/push yok. Eski sohbetler değiştirilmedi.
