# Embedding ve kaynak arama ölçümü — 2026-11-01

## Kapsam

Yalnız sentetik/kamusal hukuk sorguları kullanıldı. Üretim modeli çağrılmadı,
ücretli kaynak açılmadı, kullanıcı belgeleri gönderilmedi. Uygulama ayarları,
indeksler ve korpus değiştirilmedi. Veritabanı bağlantıları açıkça
`default_transaction_read_only=on` ile açıldı.

Donanım: NVIDIA GeForce RTX 3050 6 GB Laptop GPU. Model ölçümünden önce
Ollama'nın çalışan modeller listesi boştu. Zorla model boşaltma yapılmadı.
Benchmark, uygulamadaki `/api/embed` parametrelerini kullandı: tek metin,
truncate açık, model başına mevcut boyut ve 5 dakika keep-alive.

## Yerel embedding

| Model | Boyut | İlk istek | Sunucu model yüklemesi | Hazır model ortanca (12 istek) | Hazır model P95 |
| --- | ---: | ---: | ---: | ---: | ---: |
| nomic-embed-text | 768 | 3034 ms | 2794 ms | 18.62 ms | 67.61 ms |
| bge-m3 | 1024 | 7516 ms | 7126 ms | 35.33 ms | 268.38 ms |

İki modelin aynı sorgu için paralel çağrılması: 4 denemede ortanca **31.07 ms**,
en yüksek **33.73 ms**. Bu küçük örneklemde P95 en yüksek gözlemdir;
üretim yükü için istatistiksel garanti değildir. Vektörlerin boyutu, sayısı,
sonluluğu ve sıfır olmaması kontrol edildi; arama kalitesi ayrıca değerlendirilmedi.

Ham zamanlar, model digest'leri ve yalnız sentetik sorgunun karşılaştırma
vektörleri git dışı `.local/embedding-local-20261101.json` içinde.

## Embedding hariç kaynak arama

`retrieve_contexts` mevcut canlı korpusta, hazır nomic ve bge-m3 sorgu vektörleriyle
doğrudan çalıştırıldı. Her sorgu iki kez, top_k=6 ile denendi. Süre;
bağlantı, SQL ve Python kaynak getirme işlemlerini kapsar; embedding/model
yazımı ve resmî internet araştırması içermez. Üretim arama kodunun kendi kol
zaman aşımı davranışları değiştirilmedi.

| Sorgu | İlk deneme | Tekrar | Kısmi |
| --- | ---: | ---: | --- |
| Kira borcu/bildirim | 19.470 sn | 32.081 sn | Hayır / Evet |
| İşe iade/işçi sayısı | 55.944 sn | 47.806 sn | Evet / Evet |
| Havale borcu/takibe itiraz | 37.201 sn | 46.305 sn | Evet / Evet |

Altı denemenin ortancası **41.753 sn**; beşi kısmi döndü. Kaynak getirme
katmanı bu ölçümlerde, hazır embedding üretiminden çok daha uzun sürdü.
Kesin SQL/indeks kök nedeni bu ölçümle kanıtlanmış değildir.

Ham satırlar `.local/embedding-retrieval-local-20261101.json` içinde.

## Bulut karşılaştırması ve sonuç sınırı

Güncel `data/campaign/embed-nodes.json` yalnız `pc-gpu` / `local` içeriyordu.
Aynı modelleri çalıştıran erişilebilir bir bulut embedding hizmeti belirlenmedi.
Bedrock DeepSeek bir metin üretim hizmetidir; içine bu iki model kurulmadı.
Dolayısıyla **bulut süresi ölçülmedi; bulut/yerel kazananı ilan edilmedi**.

Yeni ücretli sunucu açılmadı veya mevcut sunucuya yazılım yüklenmedi.
Üretimde embedding konumu değiştirilmedi. Bir bulut adayı sağlandığında
`scripts/benchmark_embedding_latency.py` aynı istek setiyle tekrar kullanılabilir.
Aday model ağırlıkları/digest, boyut ve ön işleme bakımından uyumlu olmalı;
aynı boyuta sahip farklı model mevcut korpusa karşılaştırılmamalıdır.

Öncelik: kaynak getirme kol zamanlarını ve indeks kullanımını incelemek.
Yerel model yükleme süresini azaltma ayrı bir iyileştirmedir. Bulut taşıma
kararı hızdan başka erişilebilirlik ve işletim ihtiyaçları da içerir.

Benchmark yardımcı testleri: 6 geçti, atlanan yok. Canlı model cevap kalitesi
ve gerçek çok-kullanıcılı yük testi bu çalışmanın kapsamı değildir.
