# UYAP dosya bilgilerine soru sorma (2026-10-10)

Dava sayfasındaki **Belgelerle Sor** sohbeti artık evrakların yanında UYAP'tan çekilen dosya bilgilerinden de cevap verir:
taraflar, dosya hesabı, kişi başına sorgular, işlemler, tebligatlar ve son safahat kayıtları. "Borçlu kim?", "Bakiye borç ne
kadar?", "En son hangi işlem yapıldı?", "Araç sorgusunun sonucu ne?" gibi soruların cevabı evrak metninde değil bu kayıtlardadır.

## Nasıl çalışır

- UYAP bilgisi (`office_uyap_case_detail.tabs`) dava başına gerçek bir belgeye yazılır: **"UYAP dosya bilgileri (GG.AA.YYYY
  tarihinde çekildi)"** — `documents` + `document_chunks`, kişisel alan (`project_id IS NULL`, yalnız sahibine görünür; RLS).
  Evrak değildir: `office_case_documents` satırı yoktur, Evraklar sekmesinde ve evrak sayılarında görünmez; davaya
  `metadata.uyap_record_case_id` ile bağlanır. Kod: `api/uyap_record_document.py`.
- Belge yedi bölümdür (Künye, Taraflar, Dosya hesabı, Sorgular, İşlemler, Tebligatlar, Son safahat kayıtları); her satır
  "Etiket: değer" biçimindedir ve `api/execution_overview.py` özetinden türetilir. Hesap ve hukuki sonuç içermez, kimlik
  numarası taşımaz, her gün değişen değer ("N gün önce") yazılmaz.
- Soru sorulduğunda belge güncellenir (içerik aynıysa dokunulmaz). UYAP bilgisi yeniden çekilip içerik değişmişse **yeni**
  belge yazılır, eskisi silinmez, kapatılır (`deleted_at`): eski cevapların atıfları o günkü metni göstermeye devam eder.
- Soruyla ilgili satır taşıyan en çok 3 bölüm, davanın belgelerinin **önüne** eklenir (`api/ai/pipeline.py`, `_retrieve`).
  Cevap öteki belgelerle aynı yoldan geçer: model yalnız satır kimliği seçer, kod seçilen satırın belgede aynen bulunduğunu
  doğrular, atıf "kullanıcı belgesi" rozetiyle gösterilir ve sohbet geçmişine kaydedilir.
- **Bu satırlar yeniden yazılmaz.** Açıklama adımı (`api/ai/explanation.py`) UYAP kaydından gelen cevapta çalışmaz: ölçümde
  yerel model "DENEME ALACAK ANONİM ŞİRKETİ"ni "Deneme Alak Anonim Şirketi" diye, UYAP'ın yazdığı bakiyeyi "uygulamada
  hesaplanan" diye yeniden yazdı; denetim yalnız sayıları karşılaştırdığı için geçti. Ad, tutar ve kayıt ifadesi aynen kalır.
- Sorunun karşılığı kayıtta varsa ve hukuki değerlendirme istenmiyorsa başka davaların kararlarına bakılmaz ("Takip kesinleşti
  mi?" → "Kesinleşme bilgisi girildi: 21.02.2025"; önceden ilgisiz bir kararın genel cümleleri geliyordu). Hukuki soru ("…
  itiraz etmezse ne olur?") eskisi gibi hukuk kaynaklarında aranır.

## Ölçüm (yerel model qwen3.5:4b, uydurma dosya, geçici hesap)

`.local/check_uyap_asistan.py`, 16 soru: UYAP kaydından cevaplanması gereken 13 sorunun 13'ü doğru satırla ve aynen
cevaplandı (2-5 sn); evraktan cevaplanan 1 soru doğru (14 sn); dosyada olmayan bilgi (telefon) için "yeterli bilgi bulunmuyor"
dendi; hukuki soru hukuk kaynaklarından cevaplandı (42 sn). Gerçek hesabın verisiyle sohbet **denenmedi** (kullanıcının
oturumu gerekir); gerçek veride yalnız belge metninin üretimi sayılarla doğrulandı.

## Sınırlar

- Cevap, kaydın satırıdır; "kesinleşti" / "malı var" gibi bir sonuç söylenmez ("VAR"ın ne olduğu için bkz.
  `docs/execution-files.md`).
- Yalnız tek dava kapsamındadır. Dosyalar arası soru ("hangi dosyalarımda araç sorgusu VAR?") henüz yok; bu bilgi şimdilik
  İcra Takibi listesinde görünür.
- Safahatın yalnız son 25 kaydı ve en yeni 40 tebligat belgeye girer; tamamı UYAP Bilgileri sekmesindedir.
- Belge parçalarının embedding'i üretilmez; ilgili bölüm sözcük eşleşmesiyle seçilir.
- Hesap silme/dışa aktarma mevcut `documents` yolundan geçer (geçici hesaplar silinince belge de silindi: doğrulandı).

Testler: `tests/test_uyap_record_document.py`.
