# Luna canlı karşılaştırması — 29 Ekim 2026

Kullanıcı bu koşuya mevcut OpenRouter kredisinden **en fazla 0,25 USD**
harcanmasına izin verdi. 10 sentetik kamu hukuku sorusu, low/medium/high
düzeylerinde toplam 30 kez gerçek uygulama pipeline'ından geçirildi.

## Harcama ve yöntem

- Gerçek `usage.cost` toplamı: **0,149892995 USD**.
- 137 model çağrısı; planlama, yazım, denetim ve onarım dahildir.
- 950699 giriş ve 114400 çıkış tokenı raporlandı. Çıkış düşünmeyi de içerir;
  yalnız ekrandaki metnin uzunluğuna göre hesap yapılmadı.
- Yeni kredi, kart ödemesi, otomatik yükleme veya anahtar limiti değişimi yok.
- Koşu tamamlandı; ek deneme çağrısı yapılmadı. Kalan izin otomatik harcanmaz.
- Her soru için boş sohbet geçmişi ve ayrı cevap önbelleği kullanıldı. Sıra
  sorular arasında döndürüldü. Sağlayıcı prompt önbelleği silinmiş sayılmaz.
- Üretim ayarları/modeli/varsayılan çaba değiştirilmedi. Özel belge,
  kullanıcı sohbeti veya UYAP kaydı kullanılmadı/yazılmadı.
- Resmî web ingestion yalnız bu değerlendirme sürecinde kapalıydı; yerel
  korpusun gerçek arama ve denetimi kullanıldı. Ölçüm HTTP/UI çizim süresi
  değil, `execute_answer` süresidir.
- Bu pilotta tek çağrı çıktı sınırı 16384'tü. Hiçbir çağrının raporlanan
  completion token sayısı bu sınıra ulaşmadı. Üretim sınırları değişmedi.
- İlk ön kontrolde katalogdaki isteğe bağlı web-aracı ücreti genel metin
  çağrısı ücreti sanıldığı için test ücretli çağrı başlamadan durdu. Araçların
  gönderilmesi dispatch'te yasaklandı; metin karşılaştırması bundan sonra
  başladı. Bu değişiklik ve bütçe davranışı sahte sağlayıcı testinden geçti.

## Sonuçlar

| Düzey | Medyan süre | 10 sorunun toplam maliyeti | Beklenen madde/atıf kontrolleri | Pipeline kısmi cevap işareti | Cevapsızlık |
| --- | ---: | ---: | ---: | ---: | ---: |
| Hızlı / low | 25,38 sn | 0,04288 USD | 7/10 | 8/10 | 2/10 |
| Dengeli / medium | 49,91 sn | 0,04701 USD | 10/10 | 5/10 | 0/10 |
| Yüksek / high | 53,64 sn | 0,06000 USD | 8/10 | 6/10 | 0/10 |

**Beklenen madde eşleşmesi hukuki doğruluk veya eksiksizlik puanı değildir.**
Alternatif geçerli bir dayanak beklentiyle eşleşmeyebilir; beklenen maddenin
atıfta bulunması da alt soruların cevaplandığını kanıtlamaz. Uzman incelemesi
bekliyor. Bu 10 soru tek tekrar ile sınırlı; istatistiksel üstünlük iddiası yok.

## Metin ve tanı kayıtlarında somut görülen eksikler

- Dengeli icra cevabı ilgili 67/68 atıflarını taşıdığı hâlde kullanıcının
  istediği yolları ve süreleri tamamlamıyor. Otomatik atıf kontrolü geçti
  diye başarılı tam cevap sayılmadı.
- Dengeli idari işlem cevabı yalnız sürenin başlangıcını söylüyor;
  sorulan görev ve süreyi açıklamıyor.
- Dengeli yıllık izin cevabı hak kazanmayı anlatıyor; istenen asgari süreler
  ve yaş istisnaları metinde yok.
- Dengeli tüketici cevabı cayma süresini anlatıyor; istenen temel istisnalar
  metinde yok.
- Dengeli işe iade cevabı kıdem istisnası, işçi hesabı ve başvuru sürelerini
  veriyor ama şartların giriş açıklaması eksilmiş. Tanıda
  `coverage_preserved=true` olmasına rağmen `partial_answer=true` var.
- Hızlı tahliye ve icra cevapları `insufficient_sources` olarak döndü.
- Hızlı icra tanısında 19 adaydan 14 kaynak kabul edilmiş; 2004 m.67 ve m.68
  kabul edilen kaynak başlıkları arasında. Sonra cümle denetimi reddetmiş,
  sonuç cevapsızlığa düşmüş. Bu örnekte yalnız 'veri yok' açıklaması yanlış.
- Aynı icra tanısında yürürlükten kaldırılmış hükümler derlemesi ve posta
  tüzüğü gibi aday başlıklar da var. Adayların varlığı, bunların cevaba doğru
  dayanak olduğu anlamına gelmiyor; güncellik/alaka filtreleri ayrıca
  incelenmeli. Bu testte korpus kayıtları değiştirilmedi.

## Sonuç ve sonraki teknik iş

Salt modeli veya düşünme düzeyini yükseltmek sorunu çözmedi. Bu küçük sette
Dengeli kaynak eşleşmesinde daha iyi, ancak 5 kısmi cevap ve yaklaşık 50 sn
medyan nedeniyle 'sorunsuz' kabul edilmez. Hızlı daha düşük gecikmeli ama
iki cevapsızlığı var. Yüksek daha pahalı ve her zaman daha kapsamlı değil.

Üretim değişikliği yapmadan önce kaynak kabulü → cümle denetimi → kapsam
denetimi → kısmi cevabın yayımlanması hattı düzeltilmeli. Denetçiyi kaldırmak
ya da kısmi cevabı eksiksiz etiketlemek çözüm değildir. Aynı kayıtlar, ücret
harcamadan hata inceleme/regresyon fixture'ı için kullanılabilir; değişen
model üretiminin sonucu ise eski kayıtlarla kanıtlanamaz.

## Yeniden üretim ve kanıt

- Ham sentetik cevaplar, çağrı maliyetleri ve pipeline tanıları:
  `.local/luna-live-20261029.json` (anahtar/authorization başlıkları yok).
- Ücretsiz yeniden puanlama:
  `.\.venv\Scripts\python.exe -X utf8 scripts/assistant_eval.py --replay .local/luna-live-20261029.json`
- Değerlendirme/bütçe/ücretsiz puanlama paketi: **25 test geçti**. Kaynak
  eşleşmesinin kısmi cevap işaretini gizlememesi için regresyon eklendi.
- Canlı uygulama yeniden başlatılmadı. Mod varsayılanı değiştirilmedi.
