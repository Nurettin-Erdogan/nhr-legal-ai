# Normal sohbet politikası — 2026-10-26

Kullanıcı onayı: doğal ve kaynak destekli cevap; yalnız basit kavram açıklamasında
kaynak bulunamadığında açıkça etiketlenmiş genel bilgi. Süre, güncel oran/tutar,
hesap ve kişisel sonuç kaynak doğrulamasına bağlı kalır.

## Uygulama

- Kaynak araması ve kaynaklı cümle denetimi öncelikli kalır.
- Kaynak yoksa veya kaynaklı açıklama üretilemiyorsa, yalnız tek başına anlaşılır
  ve düşük riskli kavram tanımı `general_information.py` yoluna girebilir.
- Bu yol yalnız normal ve kapsamı özel olmayan sohbettir; sadece sorunun kendisi
  gönderilir. Belge/proje/dava içeriği ve sohbet geçmişi bu çağrıya taşınmaz.
- En çok bir genel açıklama çağrısı vardır. Kısa JSON yanıtındaki kaynak/atıf,
  sayı, tutar, süre, oran, zorunluluk ve hak sonucu ifadeleri kodda reddedilir.
  Bu filtreler modelin genel bilgisinin doğruluğunu kanıtlamaz.
- Başarılı genel açıklama `answer_kind=general_information`, `grounded=false`,
  boş atıf ve boş incelenen-kaynak listesiyle döner. Gerçek sağlayıcı/model
  kimliği korunur; bilgi kaynakla doğrulanmış veya uygulamanın sabit yanıtı sayılmaz.
- Arayüzde küçük “Genel bilgi” etiketi bulunur; açıklamasında bunun kaynakla
  doğrulanmış hukuki görüş olmadığı belirtilir. Boş kaynak menüsü gösterilmez.
- Bu cevap türü sohbetten yeniden açılınca korunur; doğrulama bayrağı yanlış
  kaydedilmiş olsa bile hukuki kanıt olarak geçmişe alınmaz.
- Normal sohbet denetlenmemiş taslak `draft` olayı yayınlamaz. Eski serbest
  cevap yardımcı fonksiyonunun önizleme arayüzü korunur ama üretim akışı onu çağırmaz.
- Derin araştırma ve özel belge yollarının kaynak politikası değiştirilmedi.

## Kontrol

2524 backend testi geçti, 440 ayrı veritabanı gerektiren/koşullu test atlandı.
32 sohbet/akış arayüz testi ve TypeScript tip kontrolü geçti. Testler örnek
sağlayıcılarla çalıştı; bu uygulama turunda ücretli canlı model testi yapılmadı.
Model ayarları veya anahtarlar değiştirilmedi; commit atılmadı.
