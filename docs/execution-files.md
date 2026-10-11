# İcra dosyaları (İcra Takibi sayfası)

`/dashboard/execution` kullanıcının UYAP'tan aktarılmış **icra dosyalarını** listeler. Ayrı bir tablo yoktur: icra
dosyası, UYAP aktarımında oluşan dava kaydıdır (`office_cases`) ve mahkeme/birim adı bir icra dairesidir.
Uç nokta: `GET /api/office/execution/files` (`api/execution.py`); yalnız oturum sahibinin satırları (RLS + `owner_id`).

## Neyin icra dosyası sayıldığı

Birim adı (katlanmış, "İ/I/ı" farkı gözetilmez) şunlardan birini içerirse:
- `icra dairesi` / `icra müdürlüğü` → **icra dairesi** (takip dosyası); "(Kapatılan)" öneki dairenin kapatıldığını söyler,
  dosyanın kapandığını **söylemez**; arayüz bunu "daire kapatılmış" diye ayrı yazar.
- `icra hukuk mahkemesi` / `icra ceza mahkemesi` → **icra mahkemesi** (şikayet, itiraz; takip dosyası değildir).

Aynı SQL kuralı (`COURT_SQL`) listeyi seçer; Sulh Hukuk, BAM gibi birimler listeye girmez.

## Evrak türü kategorileri

UYAP evrak türünden (`doc_type`) çıkarılır, içerik okunmaz: haciz (89/1–3 ihbarname, haciz talebi/tebliği), tahsilat,
reddiyat, masraf, harç (tahsil harcı, vekalet pulu, sayman mutemet), tebligat, takip talebi, ödeme emri, itiraz,
dosya hesabı, takip dayanağı. Sıra önemlidir ("tahsil harcı makbuzu" tahsilat sayılmaz). Eşleşmeyen tür "diğer"dir.

## Tutarlar: okunur, hesaplanmaz

Makbuz metninin bütün TL tutarları **aynı değerse** o değer makbuz tutarıdır; farklı tutarlar varsa (harç/faiz/vekalet
ücreti kırılımı, brüt/net) hangisinin makbuz tutarı olduğu bilinemez ve makbuz toplama girmez.

| Tür | Toplanır mı | Gerçek veride (2026-10-06, 16 dosya) |
| --- | --- | --- |
| Tahsilat makbuzu | evet | 29 / 36 okundu |
| Masraf makbuzu | evet | 29 / 29 okundu |
| Reddiyat makbuzu | **hayır** (yalnız sayılır) | 10 tutardan 2–7'si farklı; güvenle ayrılamıyor |

Arayüz her toplamın yanında kaç makbuzdan okunduğunu yazar ("36 makbuzdan 29'i okundu"); hiçbiri okunamadıysa sıfır
değil "okunamadı" yazar. Taranmış (OCR'sız) ya da henüz okunmamış belgeden tutar çıkmaz.

## UYAP dosya hesabı (2026-10-06)

"Tüm dosyaları aktar" evrakların yanında dosya penceresinin **Dosya Hesabı** sekmesini de okur (İcra dairesi dosyalarında bulunur; icra
hukuk mahkemesi dosyasında yoktur). Listede her dosyanın altında UYAP'ın yazdığı **Toplam Alacak · Yatan Para · Bakiye Borç** metni aynen
görünür ("UYAP dosya hesabı: …") ve dava sayfasındaki **UYAP Bilgileri** sekmesine (taraflar, safahat, tüm hesap alanları, tahsilat/reddiyat
tabloları) bağlanır. Bu tutarlar UYAP'ın yazdığı metindir: JurisAI toplamaz, çarpmaz, faiz hesaplamaz. Makbuzlardan okunan tutarlarla
(yukarıdaki tablo) aynı şey değildir; ikisi yan yana durur. Sekme okunamadıysa ya da henüz çekilmediyse satır gösterilmez ("(eksik)"
yazılı bağlantı, bazı tabloların UYAP'ın sayısıyla tutmadığını söyler). Ayrıntı: docs/uyap-integration.md.

## İcra Özeti sekmesi (2026-10-09)

Listede bir dosyaya tıklanınca dava sayfası **İcra Özeti** sekmesiyle açılır (`?tab=icra`). Sekme yalnız icra
dairesi/mahkemesi dosyasında görünür. Uç nokta: `GET /api/office/execution/files/{case_id}` (yalnız sahibine; başkasının
dosyası, icra olmayan dava ve olmayan kayıt aynı 404'ü alır). Kod: `api/execution.py` (`build_detail`, `reply_summary`),
`web/src/lib/execution-breakdown.ts`, `web/src/components/ExecutionBreakdown.tsx`.

### Haciz ihbarnamesi cevapları

Gerçek veride ölçülen (2026-10-09, 18 icra dosyası): UYAP'taki "89/1 Haciz İhbarnamesi Cevabı" evrakının **kendisi yalnız KEP
zarfıdır** (41-380 karakter); bankanın yazısı o evrakın **ekindedir** (76 cevap evrakı, 168 ek; hepsinin metni okunmuş). Ek,
UYAP yolundan tanınır: `<dosya> / 89/1 Haciz İhbarnamesi Cevabı / 89/1 Haciz İhbarnamesi Cevabı 12/03/2025`; tarih yolun
sonundan okunur. 89/2 ve 89/3 cevapları da aynı kuralla girer.

**Cevabın sonucu söylenmez.** Banka yazıları kalıp ve koşullu cümlelerle doludur: 168 ekin 146'sında "bloke / haciz şerhi /
haciz işlendi" türü bir ifade geçiyor, oysa yalnız 24'ünde tutar var; anahtar sözcükle "olumlu/olumsuz" demek güvenilir değildir. Bunun yerine yazıda **ne geçtiği** gösterilir ve liste ona göre
sıralanır:

| Grup | Ne zaman | Gerçek veride (168 ek) |
| --- | --- | --- |
| Tutar geçiyor | Yazıda TL tutarı var | 24 |
| "Bloke" ifadesi geçiyor | Tutar yok, "bloke" sözcüğü var | 0 |
| Belirleyici ifade bulunamadı | Hiçbiri yok (yapısal e-haciz dökümü, tanınmayan şablon, okunamayan ek) | 44 |
| "Bulunmamaktadır" türü ifade geçiyor | "bulunmamaktadır / bulunmadığı / rastlanmamıştır / mevcut değildir…" var, tutar ve "bloke" yok | 100 |

- Sıra: tutar geçen üstte, yalnız olumsuz ifade geçen en altta; "belirleyici ifade bulunamadı" olumsuzdan **önce** gelir
  (okunmadan geçilmesin). Her satırda belirleyici ifadeyi taşıyan cümle yazıdan **aynen** alıntılanır; uzun cümle iki yandan
  kırpılır ve "…" ile işaretlenir. Kısaltmalar ("Tic. Ltd. Şti.", "A.Ş.") cümleyi bölmez.
- Gönderen kurumun adı yazının başlığından okunur (en iyi çaba; 168 ekin 165'inde bulundu); bulunamazsa "Gönderen okunamadı".
- Aynı yazının iki kopyası (KEP paketi + PDF) tek satırda birleşir, kopyaların hepsi açılabilir. Birleştirme yalnız tarih,
  gönderen, alıntılar ve tutarlar **aynıysa** yapılır; emin olunamayan kopyalar ayrı satır kalır (gerçek veride bir dosyada
  15 cevap evrakı, 33 ek, 26 ayrı satır).
- Başlık sayıları saklamaz: "15 cevap evrakı · 33 ek · 26 ayrı yazı"; metni okunamayan ek ayrıca sayılır.
- Türkçe büyük harf ve "ı/İ" farkı ifadeyi gizlemez (kalıp da metinle aynı biçimde katlanır).

### Makbuz dökümü

Tahsilat, masraf ve reddiyat makbuzları tek tek listelenir: tarih, tür, metindeki tutar, belgeyi aç. Metinde tek tutar varsa o
gösterilir; birden çok farklı tutar varsa hangisinin makbuz tutarı olduğu bilinemez ve hepsi yazıldığı gibi listelenir
("2 farklı tutar: 45,00 TL · 90,00 TL"). Hiçbir şey toplanmaz. Metni okunamayan makbuz "Metni okunamadı" diye görünür.

Belgeyi açma: yanıt her belge için depolama anahtarını taşır (zaten sahibine özeldir; indirme ucu sahipliği yeniden
denetler). Dava sayfasındaki "Evraklar" sekmesi yalnız son 50 kaydı yüklediği için döküm kendi bağlantısını kullanır.

## Dosya künyesi ve inceleme (2026-10-10)

Kaynak `office_uyap_case_detail.tabs` (UYAP sekmeleri); kod `api/execution_overview.py` (saf işlevler), arayüz
`web/src/components/ExecutionOverview.tsx`. İcra Özeti sekmesinin üstünde, sırasıyla:

- **Dosya künyesi:** Türü / Yolu / Şekli / Dosya Durumu ve taraflar (rol, tip, ad, vekil), UYAP'ın yazdığı gibi; safahatın
  kayıt sayısı, ilk ve son tarihi, son kayıttan bugüne geçen **gün sayısı** (yalnız sayı; "düştü", "yenilenmeli" denmez).
- **Dosya hesabı:** UYAP'ın hesap alanları ve tahsilat/reddiyat özet satırı, aynen. Hesaplanmaz.
- **Borçlu sorguları:** safahattaki araç, tapu (TAKBİS), SGK (aktif/pasif 4A-4B-4C, işyeri tescil, haciz), posta çeki ve
  adres sorguları kişi başına toplanır: kaç sorgu, en son ne zaman ve kayıtta yazan son **"Sorgu Sonucu: VAR/YOK"**. Sonuç
  yazmayan kayıt "sonuç yazılmamış" diye gösterilir; aynı gün iki farklı sonuç varsa ikisi de söylenir. "VAR"ın ne olduğu
  (hangi araç, çalışıyor mu) burada **söylenmez**: gerçek veride aynı kişi için hem SGK aktif 4A hem 4C "VAR" yazabiliyor;
  ifade yorumlanmadan aktarılır ve sekme UYAP'taki sorgu sonucuna bakılmasını söyler.
- **Önemli işlemler:** safahat kayıtları UYAP işlem türüne göre gruplanır (açılış, ödeme/icra emri, tebligat, kesinleşme
  bilgisi, haciz talebi, banka haciz ihbarnamesi, gelen evrak, tahsilat, reddiyat, kapanış…): kayıt sayısı, ilk-son tarih,
  son üç kayıt. Tanınmayan işlem türü hiçbir gruba sokulmaz; UYAP'taki adıyla "Diğer işlemler"de sayılır.
- **Tebligatlar:** çıkış kaydı ile sonuç kaydı barkod numarasıyla eşlenir. Sonuç metni yazıyorsa ("Tebliğ Edildi") aynen;
  yalnız "Barkod No:…" kaydı varsa "sonuç kaydı girilmiş, sonucu yazmıyor"; hiç yoksa "sonuç kaydı yok".

Özet metinlerinden kimlik numaraları (TC/vergi no, IBAN) çıkarılır; tam kayıt UYAP Bilgileri sekmesinde durur.
Gerçek hesapta ölçülen (18 icra dosyası, 957 safahat kaydı, 47 işlem türü): 435 kayıt sorgu, 468 kayıt önemli işlem,
69 kayıt "diğer"; sorgulanan 21 kişiden 18'i taraflar tablosundaki bir borçluyla eşleşti, 3 kayıt grubunda ad okunamadı
(öyle gösterilir). UYAP bilgisi çekilmemiş dosyada künye uydurulmaz; sekme nasıl çekileceğini söyler.

**Liste (`/dashboard/execution`):** her satırda alacaklı/borçlu adları, takip türü, UYAP dosya durumu, son işlem tarihi ve
geçen gün, borçlu hakkında son sonucu "VAR" yazan sorgular. Arama taraf adını da tarar ("ismail" = "ISMAIL" = "İSMAİL",
"ayse" = "AYŞE"); süzgeç "UYAP'ta açık / açık olmayan", sıralama "son evrak / son işlem / en uzun süredir işlem yok"
(işlem tarihi bilinmeyen dosya öne alınmaz).

İki düzeltme: (1) **evrakı olmayan ama UYAP bilgisi olan dosya artık listelenir** (önceden gerçek hesaptaki 18 dosyanın
11'i görünmüyordu); ne evrakı ne UYAP kaydı olan dosya listeye girmez. (2) Doğrulama kaydı "eksiksiz" dese de dosyada o
doğrulamadaki sayıdan az evrak varsa rozet **"Son doğrulamadan sonra N evrak silinmiş; UYAP'tan yeniden aktarın"** olur
(gerçek hesapta 9 dosya bu durumda: evraklar 09.10'da silindi, yeniden aktarım yarıda kaldı).

## Sınırlar / sıradaki işler

- Aşama **söylenmez** (yalnız işlemlerin kaydı ve tarihleri gösterilir); süre uyarısı (ör. haciz/satış isteme süreleri) yok:
  kural korpustan doğrulanmadan eklenmez. Liste her açılışta bütün dosyaların safahatını okur (18 dosyada 0,04 sn);
  yüzlerce dosyada özetin saklanması gerekebilir.
- Haciz cevabı grupları metinde geçen ifadeye dayanır, hukuki sonuç değildir; 44 ek "belirleyici ifade bulunamadı" grubunda
  (12'si yapısal e-haciz dökümü, 22'si tek bir banka şablonu). Banka dışı üçüncü kişilerin (işveren, kurum) adı okunmaz.
- Tebliğ tarihleri artık Süreler sekmesine aday olarak düşer (2026-10-10; her davada, yalnız icra dosyasında değil):
  `docs/deadlines.md`, "Tebliğ mazbatasından başlangıç adayı". Kâğıt mazbatalar taranmış olduğu için okunamaz.
- İcra evrakları üzerinde soru-cevap için dava sayfasındaki "Belgelerle Sor" kullanılır.

Testler: `tests/test_execution.py`, `tests/test_execution_detail.py`, `tests/test_execution_overview.py`, `web/tests/execution.test.mjs`,
`web/tests/execution-overview.test.mjs`, tarayıcı: `.local/check_icra_kunye.py`,
`web/tests/execution-breakdown.test.mjs`. Gerçek tarayıcı denetimi: `.local/check_icra_ozeti.py` (uydurma belgelerle).
