# Kamu hukuk verisi tamamlama — 28 Ekim 2026

## Kapsam

21 kurum, 22 ayrı koleksiyon. AYM bireysel başvuru ve norm denetimi aynı
koleksiyon sayılmaz. Koleksiyon planı `ingestion/official_catalog.py`;
güncellenebilir rapor `.local/official-data-campaign/inventory.json`.

Raporu yenilemek: `python scripts/official_data_inventory.py --database`.
Bu komut kamu korpusu sayaçlarını okur; model çağrısı, özel veri taraması veya
aktarım yapmaz. Sayaçlar doğrulanmış tekil resmî kimlik sayısı değildir.

Mevcut yetenekler: 4 worker koleksiyonu, 1 hub koleksiyonu, 3 portal/parser,
1 mevzuat doğrulama/yenileme, 1 yalnız künye doğrulama; **12 koleksiyon için
aktarım adaptörü eksik**. Dosyanın mevcut olması portal sözleşmesinin bugün
çalıştığını veya koleksiyonun tamamının bulunduğunu kanıtlamaz.

## Yeniden başlatılan işler

- Kanun kampanyası: 893 mevcut kanunluk manifestten devam; eski süreç
  çalışmıyordu, önceki duruş portal erişim hatasıydı. 6745 sayılı Kanunda
  43 yeni resmî sürüm kaydedildi, eski sürümler ve yedekler korundu.
  80. maddedeki belirsiz başlık atlandı ve açık sorun olarak raporlandı.
- Kamu metin/hash taraması: eski kilidin sahibi yoktu; kilit silinmek yerine
  zaman damgalı arşive taşındı. 4.558.000 kayıttan devam edilip ilerleme
  doğrulandı. Bu tarama resmî portaldan tekrar indirme/eşleştirme değildir.
- Süreçler gizli pencereyle çalıştırıldı; mevcut API, embedding, Docker,
  bulut sunucuları ve görev ayarları değiştirilmedi.

## Tamamlanma koşulu

Her koleksiyon için yayımlanmış resmî kimlik envanteri, zaman/sürüm kapsamı,
tam metin, künye, hash, doğrulama, tekilleştirme ve açık hata kuyruğu gerekir.
Yalnız aynı envanterdeki tekil kimlikler karşılaştırılır. Portal toplamı
bilinmiyorsa kapsam bilinmiyor kalır; milyonlarca yerel kayıt bunu değiştirmez.
Bir tarihte tamamlanan envanter sürekli güncelleme ihtiyacını ortadan kaldırmaz.

## Açık işler / depolama

- Yeni kurumlar için resmî koleksiyon/erişim koşulları ve gerçek sayfalama
  sözleşmeleri doğrulanıp adaptörler uygulanmalı. Sahte endpoint veya ana
  sayfanın indirilmesi tam koleksiyon aktarımı sayılmayacak.
- Kanun dışındaki mevzuat türleri ve kampanyanın mevcut manifestinde olmayan
  kanunlar ayrıca keşfedilmeli. Kısmi/başarısız kanunlar açık listede tutuluyor.
- Büyük yeni arşiv indirmeleri başlatılmadı: Windows'ta yalnız C: görünüyor,
  yaklaşık 183 GiB boş. Önceki E: HDD görünmediği için kullanıcıya soruldu.
  Çalışan iki denetim/yenileme mevcut korpus üstünde çalışır.
- Hiçbir resmî olmayan site, CAPTCHA aşma, proxy/VPN, yeni ücretli kaynak veya
  model kredisi kullanılmadı. Bütün veri eksiksizdir iddiası yoktur.
