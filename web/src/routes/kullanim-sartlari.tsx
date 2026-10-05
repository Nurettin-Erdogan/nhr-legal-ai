import { createFileRoute } from "@tanstack/react-router";
import { LegalPage, type LegalSection } from "@/components/LegalPage";
import { CONTROLLER, TERMS_VERSION } from "@/lib/legal";

const sections: LegalSection[] = [
  {
    title: "Hizmetin kapsamı",
    body: (
      <p>
        JurisAI, avukatlara ve hukuk bürolarına Türk hukuku kaynaklarında araştırma, belge hazırlama, belge özetleme ve dava yönetimi için yardımcı bir araç sunar. Hizmet
        <strong> hukuki danışmanlık ya da avukatlık hizmeti değildir</strong>; hiçbir çıktı bir avukatın mesleki değerlendirmesinin yerine geçmez. Vatandaş başvuru formu yalnızca bir avukata ulaşma
        talebidir; avukat–müvekkil ilişkisi başvuruyla kurulmaz.
      </p>
    ),
  },
  {
    title: "Kaynaklar, yapay zekâ ve doğruluk",
    body: (
      <ul className="list-disc space-y-1 pl-5">
        <li>Cevaplar yalnızca hizmetin hukuk korpusundan getirilen kaynaklara dayanır; kaynak bulunamazsa bu söylenir ve cevap uydurulmaz.</li>
        <li>
          Kaynaklar <strong>resmî doğrulanmış</strong> ya da <strong>doğrulanmamış (üçüncü taraf)</strong> olarak ayrı işaretlenir. Doğrulanmamış kayıt resmî kaynak sayılmaz; kullanmadan önce
          özgün kaynaktan kontrol edilmelidir.
        </li>
        <li>Yapay zekâ çıktıları (özet, taslak, olay anlatımı) hata ya da eksik içerebilir. Her çıktı, kullanıcı tarafından özgün belgeler ve resmî kaynaklarla karşılaştırılmadan kullanılmamalıdır.</li>
        <li>Dilekçe, sözleşme ve ihtarname çıktıları <strong>taslaktır</strong>; boş alanlar kullanıcı tarafından doldurulur ve hukuki içerik avukat tarafından gözden geçirilir.</li>
        <li>Hizmet dava sonucu tahmini yapmaz.</li>
      </ul>
    ),
  },
  {
    title: "Kullanıcının sorumlulukları",
    body: (
      <ul className="list-disc space-y-1 pl-5">
        <li>Hesap bilgilerinizin gizliliğinden ve hesabınızla yapılan işlemlerden siz sorumlusunuz.</li>
        <li>
          Müvekkil verilerini yüklemeden ya da UYAP'tan aktarmadan önce yetkili olduğunuzu ve müvekkilinizi KVKK uyarınca bilgilendirme yükümlülüğünüzü yerine getirdiğinizi taahhüt edersiniz.
        </li>
        <li>Başkasına ait hesabı, yetkisiz dosyaları ya da otomatik/aşırı yükleme yapan araçları hizmete karşı kullanamazsınız; resmî portalların kullanım koşullarına uymak size aittir.</li>
        <li>Yasadışı, hakaret içeren ya da başkalarının haklarını ihlal eden içerik yüklenemez.</li>
      </ul>
    ),
  },
  {
    title: "Kullanıcı içeriği ve veriler",
    body: (
      <p>
        Yüklediğiniz belgeler ve oluşturduğunuz kayıtlar size aittir; hizmet bunları yalnızca size hizmeti sunmak için işler. Kişisel verilerin işlenmesi{" "}
        <a className="underline" href="/gizlilik">
          Gizlilik Politikası ve KVKK Aydınlatma Metni
        </a>
        'nde anlatılmıştır; yapay zekâ modelleri kullanıcı içeriğiyle eğitilmez.
      </p>
    ),
  },
  {
    title: "Hizmetin sürekliliği ve sorumluluk sınırı",
    body: (
      <p>
        Hizmet "olduğu gibi" sunulur; kesintisiz ya da hatasız çalışacağı garanti edilmez. Kaynak verisi resmî portallardan toplandığından güncelliği portalların yayınına bağlıdır. Yasaların izin verdiği
        ölçüde, hizmetin çıktısına dayanılarak alınan kararlardan doğan zararlardan hizmet sağlayıcı sorumlu tutulamaz; nihai değerlendirme ve sorumluluk kullanıcı avukata aittir.
      </p>
    ),
  },
  {
    title: "Değişiklikler, uygulanacak hukuk ve iletişim",
    body: (
      <p>
        Bu koşullar değiştirilebilir; güncel sürüm bu sayfada yayımlanır. Koşullara Türk hukuku uygulanır; yetkili mahkeme ve icra daireleri: [yetkili yer belirlenecek]. İletişim: {CONTROLLER.name},{" "}
        {CONTROLLER.email}.
      </p>
    ),
  },
];

const TermsPage = () => (
  <LegalPage
    title="Kullanım Şartları"
    version={TERMS_VERSION}
    intro={<p>JurisAI'ı kullanarak aşağıdaki koşulları kabul etmiş olursunuz.</p>}
    sections={sections}
  />
);

export const Route = createFileRoute("/kullanim-sartlari")({
  component: TermsPage,
});
