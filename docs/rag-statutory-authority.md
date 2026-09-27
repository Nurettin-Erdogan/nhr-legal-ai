# Genel mevzuat yanıtında birincil dayanak — 27 Eylül 2026

## Gözlenen hata

Kullanıcı TÜFE üzerinde kira artışı sorduğunda cevap, 2017 tarihli Sayıştay
kararındaki ÜFE ifadelerini genel kural olarak sunuyordu. Bir kaynağın gerçek ve
alıntının ona uygun olması, hükmün bugünkü soruya uygulanabileceğini kanıtlamaz.
İlgili kanun değişikliği [TBMM'nin 7161 sayılı Kanun metninde, madde 56'da](https://cdn.tbmm.gov.tr/KKBSPublicFile/D27/Y2/T2/KanunMetni/a9add2a3-942f-4aa1-b2d9-1dcbb70f6dc9.html)
görülebilir; burada eski kararın içindeki kural otomatik olarak güncel sayılmamalıydı.

Salt okunur incelemede TBK 344 metni veritabanında bulundu. Kaynak seçiminin ilk
sırasındaydı; fakat cümlelerin salt sözcük puanına göre sıralanması ve toplam
4.500 karakter bütçesi yüzünden modele gönderilen **12 kanıt cümlesinin hiçbirinde
yer almıyordu**. Uzun Sayıştay alıntıları bütçeyi tüketmişti. Özet denetçisi de
yalnız modelin seçtiği bu alıntıları görüyordu.

## Sınırlandırılmış düzeltme

- Genel mevzuat sorusunda, açık madde atfına veya mevcut konu eşlemesine uyan
  resmî mevzuat kaynağı getirildiyse, cevap kanıtları o maddeye dayanır. Karar
  alıntıları bu dayanağın yerine geçemez. Bu bir kaynak-öncelik politikasıdır;
  modelin bildiği varsayılan hukuk kuralı cevaba yazılmaz.
- Kararlar silinmez, toplama ve araştırma listesi değişmez. Açık içtihat/karar
  araştırması soruları bu dar mevzuat-cevabı politikasına sokulmaz.
- Seçilen maddenin tam cümleleri kaynak sırasıyla korunur. “Bu kural ...”,
  “Ancak ...” gibi bağlı koşullar, sorudaki anahtar sözcükleri tekrarlamadığı için
  düşürülmez. Kaynak metnine birebir destek denetimi uygulanmaya devam eder.
- İstisna/saklı hüküm içeren mevzuatın dört iddialık özete sıkıştırılması engellenir.
  Bütçeye sığmayan tam madde kırpılmak yerine yanıttan vazgeçilir.
- Önbellekteki eski cevabın denetimi yalnız eski atıfları değil, o istek için
  getirilen birincil mevzuat dayanağını da dikkate alır.
- Mevzuat önceliği model bağlamı seçilirken de uygulanır; `selected_documents`
  sayacı bu seçimi gösterir. Aday/doğrulanmış havuz sayaçları ayrı korunur.
- Yalnız mevzuat kuralı bulunmuşsa ve sorulan başvuru adımları desteklenmiyorsa,
  bunun henüz doğrulanamadığı belirtilir; pratik hukuki yol uydurulmaz.

## Gerçek model smoke testi

Yerel `qwen3.5:4b`, canlı korpusa salt okunur erişim, aynı kira sorusu:

- Arama yaklaşık 3,4 saniye.
- Model seçimi ve cevap denetimi 0,49 saniye (sıcak model; hız garantisi değil).
- Atıf: TBK 6098 m.344. Yanıtta ÜFE kuralı yok, kaynak metnindeki koşul ve
  istisnalar korunuyor, `grounded=true` ve desteklenmeyen iddia listesi boş.
- Portal doğrulaması, sohbet kaydı ve işçi durdurma işlemi bu testte yapılmadı.
  Bu yüzden bu ölçüm tarayıcıdan uçtan uca süre değildir.

Son tekrar ölçümünde disk/yük koşulları altında geniş metin araması yeniden
4 saniyelik timeout'a girdi (toplam arama 5,31 sn, model/denetim 1,67 sn).
Buna rağmen birincil madde bulundu, cevap yine TBK 344'e dayandı ve doğrulamadan
geçti. **Genel arama zaman aşımı sorunu tamamen çözülmüş değildir.**

## Sınırlar

Bu bir genel hukuki çelişki çözümleyicisi değildir. Birincil maddenin hiç
bulunmadığı konular, hatalı veri/sürüm etiketleri ve açık içtihat araştırmalarının
güncellik denetimi ayrıca ele alınmalıdır. Mevzuat önceliği geniş içtihat sentezi
yerine daha dar, alıntı tabanlı yanıt verir. Kaynak kapsamı yetersizken kapsamlı
bir hukuki tavsiye verdiği iddia edilmez.

Çalışan API `--reload` olmadan başlatılmıştı. Dosya değişikliği tek başına
çalışan sürece yüklenmez; yalnız uygulama API'sinin yeniden başlatılması gerekir.
Önceden kaydedilmiş sohbet cevapları değiştirilmez. Yeni soruyla yeniden test edilir.
Bu oturumda API, yalnız `api/` klasörünü izleyen `--reload --reload-dir api`
ile yeniden başlatıldı; toplama/embedding işçileri yeniden başlatılmadı.

İzole CI şemasıyla release testleri: **535 geçti, 1 atlandı**.
