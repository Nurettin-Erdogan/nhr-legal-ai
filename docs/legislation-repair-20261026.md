# Mevzuat kimliği onarımı — 26 Ekim 2026

## Uygulanan değişiklikler

- Mevzuat aktarımında madde başlığındaki harfli, ek ve geçici madde kimliği korunuyor. Portal numarası ile metin başlığı uyuşmuyorsa kayıt reddediliyor; başka bir maddenin sürümü olarak saklanmıyor.
- Resmî PDF metin çıkarımı `18`, `18/A`, `18/B` gibi maddeleri tam başlık eşleşmesiyle ayırıyor. Arşivde aynı sayısal numaranın bulunması, farklı portal madde kimliğinin aktarımını artık engellemiyor.
- Canlı korpusta açıkça ayırt edilebilen 10 kaynak kaydı, 6 kimlik grubu içinde yeniden sınıflandırıldı. Kaynak ve chunk kimlikleri, metin, hash ve embeddingler korundu. 6325 m.18 ve 18/A ile 6100 m.183 ve 183/A ayrı güncel kimliklere kavuştu. 195, 6964, 2813 ve 2009 sayılı kanunlardaki açık harfli madde çakışmaları da ayrıldı.
- Eksik 6325 m.18/B, [resmî Mevzuat Bilgi Sistemi PDF'sinden](https://www.mevzuat.gov.tr/MevzuatMetin/1.5.6325.pdf) tam başlığıyla çıkarılıp ayrı kaynak olarak eklendi. Doğrulama yalnız bu kaydın PDF metin/hash kanıtına dayanıyor; Resmî Gazete kanıtı varsayılmadı.

## Son kontrol ve sınırlar

Canlı salt okunur taramada silinmemiş mevzuat kaydı 87.674, güncel kayıt 86.532, görünür güncel kayıt 86.492. Güncel anahtar çakışması ve içerik-hash hatası sıfır. Onarımın tekrar çalıştırılmasına ilişkin kuru çalıştırmada yeni otomatik değişiklik çıkmadı.

İlk başlık ile kayıt kimliği uyuşmayan **11** güncel kayıt ve farklı başlıklar içeren **10** sürüm zinciri adayı kaldı. Otomatik onarıcının atladığı 11 belirsiz grup, resmî madde ağacı ve sürüm tarihleriyle tek tek incelenmeli. Başka madde başlıkları içeren 2.001 kayıt ve tanınan başlığı bulunmayan 80 kayıt da hata sayısı değil, inceleme adayıdır; alıntı ve değişiklik kanunu metinleri olabilir.

6100 m.183'ün yeniden ayrılmış kaydı güncel resmî PDF metniyle yeterince eşleşmediği için **doğrulanmış olarak açılmadı**. Bu maddeyi güncel metin/sürüm karşılaştırmasıyla yenilemek gerekiyor. Diğer eski kayıtların tüm metinlerinin güncel resmî PDF ile eşleştiği iddia edilmiyor. Yeni 6325 m.18/B'nin üç chunk'ı mevcut ve kaynak görünür; embeddingleri henüz yok, bu nedenle vektör sıralamasında değil metin aramasında bulunabilir.

Çevrimdışı backend ve ayrılmış test veritabanıyla yapılan son çalıştırmada **2.866 test geçti**. Ücretli model çağrısı yapılmadı. Çalışan uygulama API'si bu onarım sırasında yeniden başlatılmadı; mevzuat verisi anında okunabilir, kod tarafındaki yeni ayrıştırma kuralları API yeniden başlatılınca devreye girer.

## Geri dönüş ve tekrarlanabilirlik

Canlı onarım öncesi yedekler, git dışında `.local/corpus-repair-backups/identity-20261026T145543256437Z.json` ve `.local/corpus-repair-backups/official-20261026T150123157609Z.json` dosyalarında. İlk dosya eski kaynak/ayrıntı/atıf başlıklarını; ikincisi eklenen resmî madde metnini ve PDF kanıtını içerir. Veritabanında otomatik geri alma yapılmadı.

Salt okunur tarama: `python scripts/audit_legislation_integrity.py`. Kimlik düzeltme aracı varsayılan olarak yalnız plan üretir: `python scripts/repair_legislation_identities.py`. Resmî PDF'den tek madde içe aktarma da `--apply` verilmedikçe salt okunurdur: `python scripts/import_official_article.py --law 6325 --article 18/B --url https://www.mevzuat.gov.tr/MevzuatMetin/1.5.6325.pdf`.
