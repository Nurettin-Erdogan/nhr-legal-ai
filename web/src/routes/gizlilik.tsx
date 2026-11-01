import { createFileRoute } from "@tanstack/react-router";
import { LegalPage, type LegalSection } from "@/components/LegalPage";
import { CONTROLLER, PRIVACY_NOTICE_VERSION } from "@/lib/legal";

const list = (items: string[]) => (
  <ul className="list-disc space-y-1 pl-5">
    {items.map((item) => (
      <li key={item}>{item}</li>
    ))}
  </ul>
);

const sections: LegalSection[] = [
  {
    title: "Veri sorumlusu",
    body: (
      <p>
        6698 sayılı Kişisel Verilerin Korunması Kanunu (KVKK) kapsamında veri sorumlusu:{" "}
        <strong>{CONTROLLER.name}</strong>, {CONTROLLER.address}. İletişim ve başvuru:{" "}
        {CONTROLLER.email}.
      </p>
    ),
  },
  {
    title: "İşlenen kişisel veriler",
    body: (
      <>
        <p className="font-medium">Başvuru formunu dolduran kişiler (vatandaşlar)</p>
        {list([
          "Kimlik ve iletişim: ad soyad, telefon, e-posta.",
          "Başvuru bilgisi: hukuk alanı, uyuşmazlık konusunu anlattığınız metin ve varsa sohbet özeti.",
          "Onay kaydı: aydınlatma metnini okuduğunuza dair onay zamanı ve metnin sürümü.",
        ])}
        <p className="mt-2">
          Konu anlatımınızda sağlık, ceza mahkûmiyeti gibi{" "}
          <strong>özel nitelikli kişisel veriler</strong> yer alabilir. Başvuruyu değerlendirmek
          için gerekli olmadıkça bu tür bilgileri yazmamanızı öneririz; yazarsanız bunları yalnızca
          başvurunuzu değerlendirmek için kullanırız.
        </p>
        <p className="mt-3 font-medium">Avukat ve büro kullanıcıları</p>
        {list([
          "Hesap: ad, e-posta, parolanızın tek yönlü özeti (parolanın kendisi saklanmaz).",
          "Çalışma alanı: müvekkil, dava, görev, takvim ve hatırlatma kayıtları; yüklediğiniz ya da UYAP'tan aktardığınız belgeler ve bunlardan çıkarılan metin.",
          "Yapay zekâ kullanımı: sohbet geçmişi, üretilen taslak ve özetler.",
          "Geri bildirim: uygulama içinden gönderdiğiniz mesaj, türü ve açık olduğunuz sayfanın yolu (belge ve sohbet içeriği eklenmez).",
          "Denetim kaydı: işlemin türü, zamanı, IP adresi ve tarayıcı bilgisi. Belge ya da yazışma içeriği denetim kaydına yazılmaz.",
        ])}
      </>
    ),
  },
  {
    title: "İşleme amaçları ve hukuki sebepler",
    body: (
      <>
        {list([
          "Başvurunuzun değerlendirilmesi ve size dönülmesi (KVKK m. 5/2-c: bir sözleşmenin kurulması için gerekli olması; m. 5/2-f: meşru menfaat).",
          "Avukat ve büro kullanıcılarına hukuk araştırma, belge hazırlama ve dava yönetimi hizmetinin sunulması.",
          "Hizmetin güvenliği, kötüye kullanımın önlenmesi ve hukuki yükümlülüklerin yerine getirilmesi.",
        ])}
        <p className="mt-2 text-xs text-muted-foreground">
          Hukuki sebep ifadeleri taslaktır; bir hukuk danışmanı doğrulamalıdır.
        </p>
      </>
    ),
  },
  {
    title: "Verilerin aktarımı ve yapay zekâ",
    body: (
      <>
        {list([
          "Başvurunuz yalnızca onu değerlendirecek büro avukatlarının erişimine açılır.",
          "Yapay zekâ ile metin üretimi bu hizmetin kendi sunucusunda çalışan yerel bir modelle yapılır. Yazdıklarınız ve belgeleriniz üçüncü taraf bir yapay zekâ hizmetine gönderilmez ve yapay zekâ modellerinin eğitiminde kullanılmaz.",
          "Verileriniz yurt dışına aktarılmaz. İki sınırlı istisna: (i) Google ile giriş seçeneğini kullanırsanız kimlik doğrulama Google üzerinden yapılır; (ii) sayfa yazı tipleri Google Fonts'tan yüklenir, bu nedenle sayfayı açtığınızda IP adresiniz Google'a iletilir.",
        ])}
      </>
    ),
  },
  {
    title: "Saklama süreleri",
    body: (
      <>
        {list([
          "Vatandaş başvuruları: [saklama süresi belirlenecek].",
          "Hesap ve çalışma alanı verileri: hesabınız açık olduğu sürece.",
          "Çöp kutusuna taşınan belgeler 30 gün sonra kalıcı olarak silinir.",
          "Denetim kayıtları: [saklama süresi belirlenecek].",
          "Yedekler: [yedek saklama süresi belirlenecek]; yedekler erişimi kısıtlı bir konumda tutulur.",
        ])}
      </>
    ),
  },
  {
    title: "Güvenlik",
    body: (
      <p>
        Her kullanıcının verisi veritabanı düzeyinde yalnız kendi hesabına açılır (satır düzeyi
        erişim denetimi); başkasının kaydına erişim denenirse sonuç boş döner. Parolalar tek yönlü
        özetle saklanır, oturum çerezi tarayıcı betiklerinden gizlidir ve önemli işlemler denetim
        kaydına alınır. Hiçbir sistem mutlak güvenlik garantisi veremez; bir ihlal fark ederseniz
        aşağıdaki adrese bildirin.
      </p>
    ),
  },
  {
    title: "Çerezler",
    body: (
      <p>
        Yalnızca oturumunuzu sürdürmek için gerekli tek bir oturum çerezi (
        <code>nhr_access_token</code>) kullanılır. Reklam, izleme ya da analiz çerezi yoktur. Tema
        tercihi gibi ayarlar yalnızca tarayıcınızda saklanır.
      </p>
    ),
  },
  {
    title: "UYAP eklentisi",
    body: (
      <p>
        UYAP'tan evrak aktaran tarayıcı eklentisinin veri işleme ilkeleri ayrı bir metinde
        anlatılır:{" "}
        <a className="underline" href="/gizlilik-uyap-eklentisi.html">
          UYAP eklentisi gizlilik politikası
        </a>
        .
      </p>
    ),
  },
  {
    title: "Haklarınız ve başvuru yolu",
    body: (
      <>
        <p>KVKK m. 11 uyarınca şunları isteyebilirsiniz:</p>
        {list([
          "Verilerinizin işlenip işlenmediğini öğrenme ve bilgi talep etme,",
          "İşlenme amacını ve amaca uygun kullanılıp kullanılmadığını öğrenme,",
          "Eksik ya da yanlış işlenmişse düzeltilmesini, koşulları oluşmuşsa silinmesini ya da yok edilmesini isteme,",
          "İşlemenin hukuka aykırı olması hâlinde zarara uğrarsanız zararın giderilmesini talep etme.",
        ])}
        <p className="mt-2">
          Hesap sahipleri verilerini <strong>Ayarlar → Verilerimi indir</strong> bölümünden JSON
          olarak indirebilir. Silme ve diğer talepler için {CONTROLLER.email} adresine yazılı
          başvuru yapabilirsiniz; hesap silme talepleri şu an yazılı başvuruyla işlenir.
        </p>
      </>
    ),
  },
];

const PrivacyPage = () => (
  <LegalPage
    title="Gizlilik Politikası ve KVKK Aydınlatma Metni"
    version={PRIVACY_NOTICE_VERSION}
    intro={
      <p>
        Bu metin, JurisAI'ı kullanırken veya başvuru formunu doldururken kişisel verilerinizin nasıl
        işlendiğini anlatır.
      </p>
    }
    sections={sections}
  />
);

export const Route = createFileRoute("/gizlilik")({
  component: PrivacyPage,
});
