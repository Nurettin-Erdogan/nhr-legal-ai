# Yerel Qwen karşılaştırması — 30 Ekim 2026

Donanım: RTX 3050 Laptop 6 GB, yaklaşık 32 GB RAM. Ücretli model çağrısı yok.
Uygulama ayarı değiştirilmedi; Qwen3.5 4B seçili kaldı. Embedding başlatılmadı.

## Aynı dört sentetik kontrol

Kaynak kuralını seçme, 18 yaş sınırı, kaynakta olmayan tutar ve kaynak içine
yerleştirilmiş talimat kontrolü. Gerçek hukuk sorusu/uzman incelemesi değildir.
Tek koşu, think=false, 8192 bağlam, 512 çıktı tavanı; örnek cevap çok kısadır.
Model yükleme süresi ayrıca kaydedildi. Medyanlar gerçek sohbet süresi değildir.

| Model | Başarılı / 4 | Kısa kontrol medyanı |
| --- | ---: | ---: |
| Qwen3.5 2B | 3 | 0,289 sn |
| Qwen3.5 4B | 4 | 0,444 sn |
| Qwen3.5 9B | 3 | 2,674 sn |
| Qwen3 4B | 2 | 0,400 sn |
| Qwen3 8B | 4 | 1,217 sn |
| Qwen2.5 1.5B | 2 | 0,192 sn |
| Qwen2.5 3B | 3 | 0,286 sn |
| Qwen2.5 Coder 7B | 3 | 1,026 sn |

Çeşitli küçük modeller 18 yaş sınırını yanlış değerlendirdi. Bazı modeller
enjeksiyon içeren kaynakta güvenli bilgiyi de reddetti; bu, zararlı talimata
uydukları anlamına gelmez. Dört kontrolden tam puan almak genel hukuki
güvenilirliği kanıtlamaz. “Bütün Qwen modelleri” değil, donanıma uygun seçilen
sekiz aday sınandı; diğer boyutlar/quantization çeşitleri ölçülmedi.

Rapor: `.local/qwen-screen-20261030.json`.

## Gerçek mevzuat ve mevcut sentez/denetim hattı

Ön taramayı geçen iki finalist aynı doğrulanmış kaynaklarla karşılaştırıldı.
İlk koşuda izin metninin kanıt biçimi ve icra metinlerinin test bağlam bütçesi
modele gitmeden sorun çıkardı. Bu koşu model kalitesi puanı sayılmaz; ayrı
raporda korunur: `.local/qwen-synthesis-20261030.json`.

Ardından uygulamadaki `restore_provisions` adımıyla tam maddeler hazırlanıp
12.000 karakter kaynak bütçesiyle yeniden sınandı. Aynı girdiler iki modele
de verildi. 8192 bağlam, 2048 çıktı kapasitesi; standart `synthesize_answer`
ve mevcut denetimler kullanıldı. Kaynaklar yalnız okundu; sohbet kaydedilmedi.
Bu tam HTTP/UI veya bütün retrieval hattı ölçümü değildir.

| Model | Kira | Yıllık izin | İcra | Kabul edilen |
| --- | ---: | ---: | ---: | ---: |
| Qwen3.5 4B | 13,199 sn | 16,840 sn | 15,311 sn | 0/3 |
| Qwen3 8B | 75,455 sn | 178,856 sn | 120,009 sn | 0/3 |

4B ret nedenleri sırasıyla `source_scope`, `checker`, `draft_shape`.
8B'nin son denemesi zaman aşımıyla bitti; başarısızdır, atlandı sayılmadı.
Rapor: `.local/qwen-synthesis-restored-20261030.json`.

## Karar ve temizlik

Bu küçük ölçümde 8B kabul oranını artırmadı ve belirgin yavaştı. Donanım/hız
nedeniyle **Qwen3.5 4B korunmuştur**, ancak gerçek cevap hattındaki 0/3 sonucu
nedeniyle “asistan hazır” veya “hukuki kalite doğrulandı” denemez. Sonraki iş,
yerel modelin yazım/denetim protokolüne uyumunu ve ret nedenlerini incelemektir;
kanıt kontrolleri kaldırılmamıştır.

Kullanıcının test sonrası kullanılmayan modelleri kaldırma isteği kapsamında,
tam adları kontrol edilerek yedi diğer Qwen modeli Ollama API'siyle silindi.
Bu model dosyaları yeniden indirilebilir. Proje verisi silinmedi.
`nomic-embed-text`, `bge-m3`, `qwen3-embedding:0.6b` korundu.
Karşılaştırma dışındaki eski DeepSeek/Llama etiketleri/custom yedekleri
silinmedi. Lint: iki karşılaştırma betiği temiz.
