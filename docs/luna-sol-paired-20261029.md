# İki soruda Luna–Sol karşılaştırması — 29 Ekim 2026

Kullanıcı mevcut **0,17 USD sınırında** karşılaştırmayı onayladı.
Modeller `openai/gpt-6-luna` ve `openai/gpt-6-sol`; ikisi de medium.
Üretim modeli/ayarları değiştirilmedi, API yeniden başlatılmadı.

## Yöntem ve sınır

Tam uygulama araştırmasını yeniden ücretlendirmek yerine aynı sabit
doğrulanmış kanun paketleriyle yazım katmanı karşılaştırıldı. Gerçek
`_free_verified_answer` kod kapıları ve iki model için aynı Luna/none
bağımsız kaynak denetçisi kullanıldı. İki yazara da aynı soru ve aynı sıralı
kaynak kimlikleri verildi. Planlama, web, yeniden arama ve ikinci yazım
denemesi yoktur. Bu yüzden önceki uçtan uca sürelerle doğrudan kıyaslanmaz.

İcra için 2004 m.42/58/62/67/68; işe iade için 4857 m.18/20, tam metinler
salt okunur veritabanı transaction'ından alınarak aynı biçimde restore edildi.
Karar kaynağı eklenmedi. Her model için yalnız bir üretim: istatistiksel
üstünlük veya hukuki uzman onayı anlamına gelmez. Ortak denetçi de Luna'dır;
denetçi modelinin olası hataları bu karşılaştırmadan bağımsız doğrulanmış
sayılmaz.

## Sonuç

| Soru | Luna yazım+denetim | Sol yazım+denetim | Luna maliyeti | Sol maliyeti |
| --- | ---: | ---: | ---: | ---: |
| Senetsiz havale borcu, takip ve itiraz yolları | 19,49 sn | 10,27 sn | 0,00275535 USD | 0,01858730 USD |
| İşe iade şartları, 30 işçi, başvuru süresi | 10,13 sn | 11,11 sn | 0,00082110 USD | 0,009547475 USD |

Her dört sonuçta da denetçi `coverage_preserved=false` döndürdü; yani tam
kapsam başarısı yok. Bütün tamamlanan API çağrıları `finish_reason=stop`;
4096 çıktı sınırına dayanma nedeniyle yarım kesilen çağrı görülmedi.

### Gözle görülür fark

Sol işe iade koşullarını birbiriyle daha bağlantılı bir girişte topladı.
Luna'nın anlatımı daha ayrı cümleler hâlindeydi. Sol icrada altı aylık
itirazın kaldırılması süresini son metinde tuttu; Luna'nın aynı süre
cümlesi denetimde elendi. Buna karşılık her iki icra cevabı da sorulan
yolları ve süreleri eksiksiz sunmadı.

Her iki işe iade son cevabında ilk arabuluculuk başvurusuna ilişkin bir aylık
süre eksik; ilgili taslak cümleler denetimde kapsam/koşul gerekçesiyle
elenmiş. Dolayısıyla daha güçlü yazar seçmek, ortak denetim/paketleme
sorununu tek başına çözmedi. Bu gözlem hukuki sonuçların uzman onayı değildir.

## Maliyet mutabakatı ve kesinti

İkinci sorunun ilk koşusunda denetçi çağrısı sağlayıcı hatasıyla durdu.
Hata veren çağrının maliyeti bilinmediğinden muhafazakâr rezervi tüketilmiş
sayıldı. Yalnız ikinci soru, toplam sınırdan bu harcama düşülerek kalan
0,142751735 USD limitle yeniden çalıştırıldı.

- API yanıtlarından doğrulanmış gerçek toplam maliyet: **0,032451140 USD**.
- Maliyeti belirsiz başarısız çağrı için tutulan rezerv: **0,005165700 USD**.
- Bütçeden muhafazakâr toplam düşüm: **0,037616840 USD**; 0,17 USD altında.
- İlk koşudaki ikinci sorunun tamamlanmış yazar çağrısı da bu toplamda var;
  yalnız başarılı dört sonucun maliyetiymiş gibi gizlenmedi.
- Yeni bakiye yükleme, kart işlemi, ödeme yöntemi veya key-limit değişimi yok.
- Koşular tamamlandı; kalan izin için otomatik yeni test yok.

## Karar

Bu iki örnekte Sol'un anlatımında bir miktar iyileşme var; **bariz bir
eksiksizlik üstünlüğü yok**. Varsayılan modeli değiştirmek için yeterli
kanıt değil. Önce elenen cümlelerin neden tamamlanmadığı ve kısmi sonuçların
yayımlanması düzeltilmeli. Üretim ayarı değiştirilmedi.

Kanıtlar (yalnız sentetik sorular/kamu kaynakları, API anahtarı yok):
`.local/luna-sol-paired-20261029.json` ve
`.local/luna-sol-paired-reinstatement-20261029.json`.
Araç: `scripts/compare_luna_sol.py`.
