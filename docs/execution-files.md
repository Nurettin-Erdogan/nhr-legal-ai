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

## Sınırlar / sıradaki işler

- Takip tarihi, alacaklı/borçlu ayrımı ve aşama ayrıca alanlara ayrılmıyor; UYAP'ın yazdığı metin "UYAP Bilgileri" sekmesinde durur, yorumlanmaz.
- Haciz cevaplarının özeti, makbuz dökümü ve itiraz/süre tarihlerinin takvime düşmesi henüz yok.
- İcra evrakları üzerinde soru-cevap için dava sayfasındaki "Belgelerle Sor" kullanılır (satıra tıklayınca dava sayfası açılır).

Testler: `tests/test_execution.py`, `web/tests/execution.test.mjs`.
