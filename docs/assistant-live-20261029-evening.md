# Sınırlı canlı ölçüm — 29 Ekim 2026

Kullanıcı onayı: en fazla 0,02 USD mevcut kredi; bakiye yüklemesi yok.
Rapor: `.local/assistant-live-final-20261029-evening.json`.

| Senaryo | Süre | Çağrı | Kapsam sonucu |
| --- | ---: | ---: | --- |
| Senetsiz borç / ilamsız takip | 21,736 sn | 5 | Eksik; başarısız |
| Yıllık izin | 19,955 sn | 5 | Denetçi kapsamı tam işaretledi |
| İki gerçek Yargıtay kararı / işe iade | Tamamlanmadı | 1 planlama | Maliyet rezervinde durdu |

Toplam usage maliyeti: **0,004185215 USD** (11 çağrı). Üçüncü senaryonun
tamamlanmamış planlama maliyeti bu toplama dahildir. Rezerv koruması kalan
bakiye harcanmadan durabilir; kullanılmamış kredi harcanmış sayılmaz.

## Bulgular

- İcrada kaynak havuzunda m. 42, 67 ve 62 var; m. 68 yok. Kaynak hazırlığının
  her alt soruda bir belge bulması, bütün alternatif başvuru yollarını
  karşılamıyor. Denetçi iki parçayı da eksik işaretledi. Kaynaklı görünmesi
  tam bir cevap veya hukuki doğruluk garantisi değildir.
- İcrada planlama 3,55 sn, parça araması 0,085 sn, yazım/denetim 17,97 sn.
- İzinde planlama 2,56 sn, parça araması 0,081 sn, yazım/denetim 17,11 sn.
  İki denemelik zincir hâlâ çalışıyor. Önceki küçük örneklemdeki 9 sn sonucu
  bu koşuda tekrarlanmadı; hız artışı iddia edilmiyor.
- İki karar senaryosunun yeni son-kapsam kontrolü ücretsiz testlerle sınandı;
  bu canlı koşuda cevap oluşmadığından gerçek model davranışı doğrulanamadı.

## Ölçüm sınırları

Gerçek korpus ve uygulama pipeline'ı kullanıldı; ayrı test sürecinde internet
ingestion kapalıydı, sohbet kaydedilmedi, üretim ayarları değiştirilmedi.
Hızlı/low düzeyi ve yalnız test için 4096 çıktı token tavanı kullanıldı.
Bu HTTP/tarayıcı uçtan uca ölçümü değildir. İnsan hukukçu incelemesi yapılmadı.
Mevcut bütçe koruması ve kanıt denetimi kaldırılmadı.
