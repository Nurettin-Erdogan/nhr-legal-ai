# Asistan kontrolü — 2026-10-26

## Bu çalışmada değişenler

- Genel hukuk aramasında bağımsız vektör sorguları, metin aramasıyla örtüşebiliyor.
  Tüm istekler arasında en çok iki ek bağlantı kullanılır. Özel belge/proje
  sorguları kendi kimlik doğrulanmış bağlantısında kalır. Kaynak filtreleri değişmedi.
- Durum uç noktası yalnız embedding varlığını değil, canlı sorguya uygun ve
  geçerli indeksi de arar. Önbellek embedding modeli değişince yeniden okunur.
- Uzun bir taslakta önemli miktarda cümle çıkarılırsa mevcut iki denemelik bütçe
  içinde denetçi bulguları yeniden yazıma iletilir. Geri bildirim kanıt sayılmaz;
  yeni taslak da bütün denetimlerden geçer. Daha az doğrulanmış cümle içeren
  ikinci deneme ilkini otomatik olarak değiştirmez.

## Ölçümler ve sınırlar

- Testler: 2446 başarılı, 440 atlandı. Atlananlar çoğunlukla ayrı test veritabanı
  gerektirir; üretim veritabanına yazmalı test çalıştırılmadı.
- Canlı kira sorusu: grounded=true, yaklaşık 13,1 saniye; TBK 344/345 ve
  iki karar atfı. O koşuda kaynak araması yaklaşık 0,8 saniye, partial=false.
- Canlı işten çıkarılma sorusu: düzeltme sonrasında kıdem, ihbar, izin ücreti
  ve işe iade başlıkları birlikte döndü; grounded=true, iki deneme, 40,9 saniye.
  Bu, eksiksizlik veya hukuki doğruluk garantisi değildir.
- Aynı makinede arama süresi sıcak/soğuk önbelleğe göre değişiyor. Geniş metin
  araması bazı sorularda hâlâ zaman aşımına uğrayıp sınırlı yedek aramaya geçiyor.
  partial bilgisi korunuyor; bütün korpus taranmış gibi sunulmuyor.
- Mevcut genel sohbet modeli OpenRouter üzerinden openai/gpt-6-luna;
  derin araştırma deepseek/deepseek-v4-pro. Bu çalışmada model/.env değiştirilmedi.

API yeniden başlatıldı ve /health başarılı. Docker/PostgreSQL yeniden
başlatılmadı, indeks bakımı yapılmadı, embedding işçileri başlatılmadı.
Commit atılmadı; önceki çalışma ağacı değişiklikleri korundu.
