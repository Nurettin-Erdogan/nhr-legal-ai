# Resmî korpus yenilemesi — uygulama ve devam eden kampanya

Kullanıcı 27 Ekim 2026'da farklı kayıtların resmî asıllarıyla yenilenmesini ve
veri işi bitmeden asistana dönülmemesini istedi. Bu rapor **tamamlanma onayı
değildir**. Asistan kodu/modeli bu turda değiştirilmedi; ücretli model çağrısı yok.

## Güvenli yenileme davranışı

- Kanun PDF bağlantısı mevcut resmî doğrulama kaydından veya MBS'nin resmî arama
  sonucundan alınır. Eski Düstur serilerinde `1.3.*` vb. bağlantı kullanılır;
  her kanuna `1.5.*` yolu tahmin edilmez. Host, HTTPS, belge no, PDF başlığı ve
  kanun numarası kontrol edilir.
- Madde tek ve tam başlığıyla ayrılabiliyorsa ham resmî metin yeni sürüm olarak
  alınır. Benzerlik yüzdesiyle doğrulama yok. Yeni metnin hash'i ve tüm resmî
  belge metninin hash'i kanıta yazılır; Gazette doğrulaması uydurulmaz.
- Önizleme digest'i apply öncesi yeniden kontrol edilir. Eşzamanlı kayıt
  değişiminde işlem iptal edilir. Önce özel izin gerektirmeyen kamu-korpus
  yedeği diske yazılır ve fsync yapılır; DB işlemi atomiktir.
- Eski metin/chunk/citation fiziksel silinmez. Yeni güncel sürüm eski sürümün
  yerini alır. Kimliği hatalı tarihsel kayıt pending olur; geçmiş atıfları
  korunur ama kamu kanıtı olarak kullanılamaz. Bu yüzden işlem geri alınabilir.
- Resmî başlık belirsizse, PDF alınamazsa veya kimlik doğrulanamazsa kayıt
  değiştirilmez. Bunlar başarı sayılmaz. CAPTCHA/beklenmeyen yanıt/portal
  erişim hatasında kampanya durur; VPN/proxy/yeni istemcilerle dolanılmaz.

## İlk altı kanun — DB sonrası kontrol

| Kanun | Güncel mevcut madde | Resmî metin kanıtıyla yenilenen/doğrulanan | Belirsiz bırakılan |
| --- | ---: | ---: | ---: |
| 6325 | 40 | 40 | 0 |
| 6098 | 649 | 637 | 12 |
| 4857 | 122 | 121 | 1 |
| 6361 | 54 | 54 | 0 |
| 4458 | 248 | 243 | 5 |
| 1512 | 210 | 210 | 0 |
| Toplam | 1323 | 1305 | 18 |

Tamamlanan maddelerde metadata'daki resmî article_hash, güncel kaynak
content_hash'iyle eşleşiyor. Çift güncel kimlik sıfır. İş Kanunu ilk denemesi
yazma zaman aşımı nedeniyle bütünüyle rollback oldu; bakım yazısı süresi
kaldırılarak atomik olarak tekrar uygulandı ve son kontrol geçti.

## Kimlik hatalı kayıtları uygulamadan çıkarma

Yakın başlangıç başlığı ile madde no açıkça uyuşmayan kalan altı hazır kayıt
pending yapıldı: 1169 m.5/5-B, 200712937 m.167/167-A,
16148 m.4/4-A, 20023975 m.27/27-A, 13950 m.3/Geçici 1,
1 sayılı kararname m.527/527-F. Kaynak ve chunk kimlikleri korunuyor.
Uzak alıntı veya tanınamayan başlık otomatik bu sınıfa sokulmadı.

Yedek: `.local/corpus-repair-backups/identity-quarantine-20261027T171437478983Z.json`.
Diğer bütün partiler aynı dizinde `official-refresh-*.json` ile yedekli.

## Devam eden iş

İlk altı kanundan ayrı **893 mevcut kanun** için sabit kuyruk oluşturuldu.
`scripts/refresh_official_law_campaign.py --limit 0 --apply` tek istemciyle,
portal adımları arasında beş saniye bekleyerek çalışıyor; journal ile sürüyor.
27 Ekim 17:15 UTC anlık kontrolünde ek 487 madde işlendi; pilot dahil **1792**.
Bu sayı çalışma sürdükçe eskir; toplam benzersiz resmî hukuk kapsamı değildir.
Bazı kanunlarda işlem kısmi veya başarısızdır; journal bunları ayrı tutar.

- Kuyruk: `.local/corpus-refresh/manifest.json`
- Sonuçlar: `.local/corpus-refresh/applied.jsonl`
- Süreç kilidi/PID: `.local/corpus-refresh/runner.lock`
- Güncel günlük: `.local/official-law-campaign-v2.out.log`
- Durdurma: `.local/corpus-refresh/STOP` dosyası → mevcut kanundan sonra durur.

Beklenmeyen PDF yanıtında bir durma yaşandı. İncelemede 1219 için eski
Düstur-serisi bağlantısının kullanılması gerektiği anlaşıldı; resmî bağlantı
çözümü düzeltildi ve 75 maddelik güvenli planla kampanya sürdürüldü.

## Henüz yapılmayanlar / dürüst kapsam

- Kampanya mevcut **kanun** kayıtlarını yeniliyor; eksik madde keşfi/ekleme,
  kararname-yönetmelik-tebliğ türleri ve milyonlarca mahkeme kararının yeniden
  portal karşılaştırması bu çalışan işin kapsamında değil.
- Belirsiz kalan maddeler ve eski kayıtlı kimlik/sürüm çakışmaları ayrı inceleme
  kuyruğunda. Hiçbiri yanlış diye körlemesine silinmedi veya başarı sayılmadı.
- Değişen metinler yeni chunk'larla geldi; embeddingler eski metinden
  kopyalanmadı. Yeni parçalarda vektörler ayrıca üretilecek. Veri doğrulama
  bittiğinde değişen parçaların indeksleme/kapsam kontrolü gerekir.
- Resmî PDF çıkarımı kusursuzluk garantisi değildir. Bütün veri hatasız/onaylı
  denilemez; bu sonuç yalnız yapılan işler ve kayıtlı kanıtları kapsar.

Araçlar: `refresh_official_law.py`, `refresh_official_law_campaign.py`,
`quarantine_legislation_identity_errors.py`, `check_official_refresh.py`.
Commit/push yapılmadı; mevcut kullanıcı değişiklikleri korunuyor.
