# Dava belgeleri ve UYAP: RAG hattı

Büro çalışma alanındaki dava belgeleri (elle yüklenen ve UYAP eklentisinden gelenler) artık
sohbet tarafından **aranabilir ve atıf yapılabilir**. Bu belge hattın ne yaptığını, ne yapmadığını
ve bilinen sınırlarını anlatır.

## Akış

```
yükleme / UYAP eklentisi ─► office_case_documents (dosya + künye)
                               │  schedule_index (arka plan)  +  soru anında sweep_unindexed
                               ▼
              api/document_indexing.py  ─► metin çıkar ─► parçala ─► documents / document_chunks
                                                             (project_id NULL, uploaded_by = sahibi)
                               ▼
         POST /api/ai/answer { "case_id": ... }  ─► retrieve_document_contexts(case_id=...)
                               ▼
              cevap + atıf: source_type "document", verification "user_document"
```

- **Silme:** belge önce çöp kutusuna taşınır, sonra kalıcı silinir; çöpteki belge aranmaz. Kalıcı silme
  dayandığı sohbet cevaplarını da temizler: [office-document-trash.md](office-document-trash.md).
- **Dosyanın kaynağı** `office_case_documents`'te kalır. Türetilen kayıt `documents.office_case_document_id`
  ile bağlanır (migration 030). Kaynak silinirse metin ve parçaları `ON DELETE CASCADE` ile silinir.
- **Kapsam** sorguda `office_case_documents.case_id` üzerinden türetilir. Belge başka davaya bağlanırsa
  ek bir işlem gerekmez.
- **Gizlilik:** türetilen belge `project_id IS NULL` olduğundan RLS gereği yalnız yükleyene görünür.
  Başka kullanıcının belgesine bağlanma `documents_own_office_document` tetikleyicisiyle engellenir.
  Başkasının davası ile olmayan dava ayırt edilemez (404).
- **Tetikleme:** üç yazma yolu (manuel yükleme, `/api/public/uyap-ingest`, `/api/public/v1/documents/upload`)
  belgeyi arka planda indeksler. Hangi yoldan eklendiğinden bağımsız çalışması için soru sorulurken de
  indekslenmemiş belgeler bütçe içinde (en çok 5 belge, 20 sn) hazırlanır.

## Desteklenen biçimler

| Biçim | Durum |
| --- | --- |
| PDF (metin katmanlı), DOCX, TXT | Desteklenir |
| **UDF** | Desteklenir. Metin kök `<content>` CDATA'sından okunur (aşağıdaki not) |
| Taranmış PDF, TIF/JPG/PNG, çöp metin üreten PDF | **OCR ile okunur** (Tesseract, Türkçe; arka planda). OCR yoksa/başarısızsa belge `failed` olur ve nedeni gösterilir. OCR'lı belge "OCR ile okundu" diye işaretlenir. Bkz. [ocr.md](ocr.md) |
| ZIP / EYP arşivleri | İndeksleme dışı (arayüz açar, içindeki belgeler tek tek gelir) |

**UDF notu:** UDF, içinde `content.xml` olan bir zip'tir; belge metni kök `<content>` öğesinin CDATA
bölümündedir. Eskiden etiketleri düzenli ifadeyle silen kod, CDATA'nın içindeki metni de silip boş
sonuç veriyordu (UDF'den künye de çıkmıyordu). Artık XML ayrıştırılır; açılmış boyut 20 MB ile
sınırlıdır ve DOCTYPE/ENTITY içeren içerik reddedilir. **Bu çözüm, bilinen UDF yapısına göre yazılmış ve
yapay örneklerle sınanmıştır; gerçek UYAP çıktılarıyla henüz denenmemiştir.** İlk gerçek dosyalarla
doğrulanmalıdır.

## Durumlar ve dürüstlük

Her belge şu durumlardan birindedir (`GET /api/office/cases/{id}/documents/index`):

- `ready` — metin çıkarıldı, aranabilir.
- `failed` — okunamadı; `processing_error` kullanıcıya gösterilebilir bir neden içerir
  (ör. "Tesseract OCR kurulu değil"). Belge **asla sessizce "hazır" sayılmaz.**
- `pending` — henüz işlenmedi.

Dava kapsamlı cevap, yanıtında `document_scope` döndürür (kaç belge hazır, hangileri okunamadı,
kaçı bekliyor). Arayüz bunu göstermelidir; böylece kullanıcı bir belgenin cevaba **katılmadığını**
bilir. `POST .../documents/{id}/reindex` belgeyi zorla yeniden işletir.

İçerik değişmediyse (SHA-256) belge yeniden işlenmez; başarısız belgeler kendiliğinden tekrar
denenmez, açık yeniden indeksleme gerekir.

## Kaynak etiketi

Bu kaynaklar `verification = "user_document"`, `authority = "Kullanıcı belgesi"` olarak gelir.
Kanıt olarak kullanılabilir (`api/ai/trust.py`) ama **resmî kaynak olarak sunulmaz**; resmî
mevzuat/karar atıfı ile karıştırılmamalıdır.

## Bilinen sınırlar (ölçüldü)

- **Türkçe embedding zayıf.** `nomic-embed-text` ile 3 belgelik bir davada ilgili belgeler 0,29–0,32
  kosinüs mesafesi aldı; belgede olmayan hukuki sorular 0,34–0,36 aldı. Aralık örtüştüğü için
  **mesafeye eşik koymak mümkün değil** ve yok. "Son maaş" sorusunda doğru belge (ücret sözcüğü)
  sona düştü. Bu nedenle belge araması bugün alakasız parçaları da döndürebilir; "kaynak yetersiz"
  kararı model/doğrulama katmanına kalır. Çözüm adayı: çok dilli embedding modeli (ör. bge-m3) ve
  alaka değerlendirme setiyle ölçüm. Bu, korpusun embedding modelini de etkiler.
- Hibrit yolun sözcük kolu sıkı (VE) eşleşir; bu yüzden dolgu sözcüklü sorularda geniş (VEYA) yedek
  hem proje hem dava belgelerinde devreye girer.
- Sohbet geçmişi dava ile ilişkilendirilmez (`conversations` tablosunda dava kolonu yok). Aynı sohbeti
  başka bir `case_id` ile sürdürmek mümkündür. Müvekkil/dava/sohbet ilişkileri ayrı bir iştir.
- Ağır belge ayrıştırma (büyük PDF) arka plan iş parçacığında çalışır; iş kuyruğu süreç içidir,
  API yeniden başlarsa bekleyenler bir sonraki soruda `sweep_unindexed` ile alınır.

## Testler

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_udf.py tests/test_document_indexing.py `
    tests/test_case_document_rag.py tests/test_case_document_index_api.py -q
```

Veritabanı testleri `NHR_TEST_DATABASE_URL` gerektirir ve işlem sonunda geri alınır. Test
veritabanında migration 026–030 uygulanmış olmalıdır.

## Arayüz: dava sayfasında "Belgelerle Sor"

Dava detayında **Belgelerle Sor** sekmesi (`web/src/components/CaseDocumentAsk.tsx`):

- Belgelerin aranabilirlik durumunu gösterir: *Aranabilir*, *Okunamadı* (nedeniyle) ve *İşlenmedi*.
  Okunamayan ya da işlenmeyen belge için **Yeniden işle** düğmesi vardır
  (`POST .../documents/{id}/reindex`).
- Aynı sekmedeki sohbet `case_id` ile sorar (`LegalChat` `caseId` + `compact`). Genel sohbet geçmişi
  bir davaya bağlı olmadığından bu sekmede listelenmez; sohbet tek oturumluktur.
- Cevap, belge atıflarını **"kullanıcı belgesi"** etiketiyle gösterir ve altında "belgedeki ifadeler bir
  tarafın iddiasıdır; hukuki dayanak ya da resmî kaynak değildir" notunu taşır
  (`web/src/components/ChatCitations.tsx`).
- Cevabın altında **belge kapsamı** vardır: "3 belgeden 2 tanesi aranabildi; `x.png` okunamadı: …".
  Okunamayan belge cevaba sessizce katılmamış olmaz.

## Belge cümlelerinde alaka kuralı

`passage_relevant` bir hukuki konu tanıdığında (ör. "kıdem tazminatı") cümlenin o konunun **tüm terim
gruplarını** içermesini ister; bu, mevzuat ve karar pasajları için ayarlıdır. Bilirkişi raporundaki
"Kıdem tazminatı 8 yıl için 340.000 TL olarak hesaplanmıştır" gibi bir olgu cümlesi bu terimleri
taşımadığından eleniyor ve model hiç çağrılmadan "yeterli bilgi yok" deniyordu (0 sn). Kullanıcı
belgeleri için `relevance.document_passage_relevant` kullanılır: sorunun sözcükleriyle örtüşme aranır,
mevzuat konu kapısı uygulanmaz. Kanıt seçimi (`evidence_selection`) ve cevap doğrulaması
(`verification`) kaynak türünü iletir. Resmî kaynaklar için davranış değişmedi; cevap yine
kaynak-destek (birebir cümle, sayı) denetiminden geçer. Testler: `tests/test_document_relevance.py`.

## Bilinen sınır: Türkçe karakter olmadan yazılan sorular

"Davaci kac yil calismis…" gibi aksansız yazılan sorular belgedeki "Davacı"/"çalışmıştır" ile
eşleşmez ve "yeterli bilgi yok" döner (arama `turkish` tsvector'ü ve cümle skoru aksanları
katlamaz). Çözüm arama ve cümle puanlamasında aksan katlamadır; bu hukuk korpusu aramasını da
etkilediğinden ayrıca ölçülerek yapılmalıdır.

## Dava kapsamlı sohbette kaynak seçimi (2026-10-01)

- **Kendi dosyasına dair olgu soruları yalnız dava belgelerinden cevaplanır** (`api/ai/case_questions.py`):
  "Davalının adresi nedir?", "Bilirkişi ne kadar hesaplamış?", "Davacı kaç yıl çalışmış?" gibi sorularda genel
  korpus hiç aranmaz; belgelerde karşılığı yoksa "yeterli bilgi yok" denir. Önceden bu sorulara başka
  davaların kararlarından alıntıyla cevap verilebiliyordu (kullanıcıyı yanıltıcı). Hukuki değerlendirme ya da
  mevzuat belirtisi taşıyan sorular ("hak kazanır mı", "madde", "şartları", "Yargıtay"…) karışık aranır.
- **Karışık aramada kullanıcının belgeleri önce gelir.** Belge ve hukuk kaynağı puanları aynı ölçekte
  olmadığından (ts_rank / RRF) ortak puanla sıralama belgeleri geriye atıyordu.
- **İndeksleme bağlanınca başlar.** Belge davaya bağlandığında (ve durum uç noktası hiç işlenmemiş belge
  görünce) arka planda indekslenir; önceden yalnız ilk soruda yetişmeye çalışılıyor, "Bekliyor" öylece kalıyordu.
- Arayüz: belge bağlayınca açılır liste yenilenir, bağlanan belge listeden düşer.
