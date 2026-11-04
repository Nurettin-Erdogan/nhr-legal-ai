# Dilekçe ve sözleşme hazırlama

## Yapılandırılmış kullanıcı talimatları

İhtarname için talep edilen işlem, süre ve başlangıcı, yerine getirilmemesi
hâlindeki bildirim ve tarih ayrı alanlardır. Sistem kendiliğinden hukuki süre,
fesih iradesi veya zarar sorumluluğu eklemez. Boş talimatlar boşlukla işaretlenir.
Sözleşmenin konu metni tüm koşullarıyla korunur. Olay anlatımında altı paragraf
kesmesi yoktur. Modelin yeniden yazarken atladığı kullanıcı açıklamaları,
kullanıcı beyanı olarak ayrıca korunur; doğrulanmış hukuki sonuç sayılmaz.

Belge Hazırla ekranında dilekçe için merci, vekil, deliller ve açık talepler;
sözleşme için ödeme, süre, yükümlülükler, fesih, gizlilik, uyuşmazlık çözümü ve
yürürlük alanları bulunur. Bunlar kullanıcının talimatıdır; doğrulanmış hukuki
tespit olarak işaretlenmez. Boş koşullar uydurulmaz, `[…]` olarak bırakılır.

`DraftFields` şeması doğrudan `/api/office-ai/document` ve kalıcı belge kuyruğunda
ortaktır. Kuyruk yükünde saklanır; yeniden denemede kaybolmaz. Form kaydının
metadata alanına da eklenir. Belge türü değiştirilince diğer türe ait alanlar
isteğe gönderilmez. Kullanıcının dava/belge erişim kontrolleri değişmez.

Bu aşama tam bir dilekçe veya sözleşme uzman sistemi değildir: dava türüne özel
bilgi toplama, kaynaklı hukuki gerekçe, koşullar arası çelişki denetimi ve son
avukat incelemesi ayrı geliştirme/doğrulama gerektirir. Olay anlatımının mevcut
kaynak doğrulaması ve otomatik mevzuat listesi korunur.
