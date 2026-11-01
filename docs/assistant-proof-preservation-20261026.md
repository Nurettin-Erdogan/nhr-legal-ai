# Taslaktan son cevaba geçerken kanıtlı kısmın kaybolması

2026-10-26, normal sohbet. Bu turda ücretli model çağrısı yapılmadı.

Günlükte `lead_unproven`, 2 deneme, 5 cümle, 1 mekanik ret, 3 denetçi reddi
ve 1 onay görülüyor. Bunu izleyen bir koşuda `checker` hatası var; bu ikinci
koşunun eski günlük kaydı denetçinin biçim mi içerik mi reddettiğini göstermiyor.

## Düzeltmeler

- Açılış elenince en az altı cümle istemek kaldırıldı. Doğrulanmış ve bağımsız
  anlaşılabilir bir cümle bile varsa korunur; tüm soru cevaplanmış gibi sunulmaz,
  kodun kısa kısmi-cevap açıklaması eklenir. Hiç kanıt kalmazsa cevap üretilmez.
- Bir `@@ kaynak.cümle` bloğunda birden fazla cümle varsa ayrı atomik iddialara
  bölünür. Aynı kanıt her biri için bağımsız olarak denetlenir; komşu cümlenin
  kaynaksız rakamı diğer cümleyi otomatik düşürmez.
- Denetçi bütün adayları reddetse de tek mevcut düzeltme denemesine reddedilen
  ifadeler aktarılır. Daha önce bu erken çıkışta geri bildirim hazırlanmıyordu.
- Günlük artık denetçi yanıtının geçersiz/kaynak-dışı mı yoksa bütün iddiaların
  reddi mi olduğunu da ayırır; metinler, kullanıcı bilgileri ve sırlar yazılmaz.

Kaynak-only, sayı/birim, ödeme yönü, kesinlik ve eklenen sınır denetimleri
kaldırılmadı. Onaylanmamış taslak kalıcı doğrulanmış cevap yapılmadı.
Hatalı/çelişkili genel denetçi onayı kanıt olarak kabul edilmiyor.

Doğrulama: model/veritabanı gerektirmeyen testlerde komşu kanıtlı cümlenin
korunması, uydurma sayının elenmesi, tek kanıtlı cümlenin kısmi cevap olması,
kanıtsız taslağın yine reddi ve geri bildirimin düzeltmeye taşınması sınandı.
Gerçek ekrandaki koşunun tüm model çıktıları kaydedilmediğinden bütün retlerin
ayrı ayrı doğru veya yanlış olduğuna ilişkin kesin iddia yok.
