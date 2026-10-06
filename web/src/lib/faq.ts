/**
 * Sık Sorulan Sorular: içerik ve hukuki dayanaklar.
 *
 * Kural: hukuki bir sonuç söyleyen her cevabın dayandığı kanun maddesi `dayanak` alanında yazılıdır ve sayfada cevabın
 * altında gösterilir. Buradaki madde numaraları `scripts/verify_faq_sources.py` ile resmî doğrulanmış korpusa karşı
 * denetlenir (madde var mı, metni `beklenen` ifadeyi taşıyor mu). Yeni hukuki cevap eklerken dayanağını da ekleyin ve
 * betiği çalıştırın; dayanağı gösterilemeyen hukuki ifade bu sayfaya yazılmaz. Süre tahminleri ve büronun kendi
 * çalışma biçimine ilişkin cevaplar hukuki sonuç değildir; dayanak taşımaz.
 */
export interface FaqBasis {
  /** Kanunun kısa adı (gösterim için). */
  kanun: string;
  kanunNo: string;
  madde: string;
  /** Madde metninde bulunması beklenen ifade (numara kayması denetimi; sayfada gösterilmez). */
  beklenen: string;
}

export interface FaqItem {
  kategori: string;
  q: string;
  a: string;
  dayanak?: FaqBasis[];
}

export const FAQ_CATEGORIES = ["Tümü", "Genel", "İş Hukuku", "Aile Hukuku", "Belgeler"] as const;

export const FAQ_NOTE =
  "Bu sayfadaki açıklamalar genel bilgilendirmedir; hukuki danışmanlık değildir ve somut olayınıza göre sonuç değişebilir. Hukuki açıklamaların dayandığı kanun maddeleri cevabın altında belirtilmiştir; süreler ve tutarlar için maddenin güncel metnine ve bir avukata başvurun.";

const b = (kanun: string, kanunNo: string, madde: string, beklenen: string): FaqBasis => ({ kanun, kanunNo, madde, beklenen });

export const FAQ_ITEMS: FaqItem[] = [
  {
    kategori: "Genel",
    q: "İlk görüşme ücretli mi?",
    a: "JurisAI üzerinden yaptığınız ön görüşme ve bilgilendirme tamamen ücretsizdir. Dosyanız avukata aktarıldıktan sonra ücret, işin kapsamına göre baro asgari ücret tarifesi esas alınarak belirlenir ve başlamadan önce size yazılı olarak bildirilir.",
  },
  {
    kategori: "Genel",
    q: "Hangi alanlarda hizmet veriyorsunuz?",
    a: "İş hukuku, aile hukuku (boşanma, nafaka, velayet), kira ve borçlar hukuku, icra takipleri, tazminat davaları, ceza hukuku, miras ve tüketici uyuşmazlıkları başlıca çalışma alanlarımızdır.",
  },
  {
    kategori: "Genel",
    q: "Dava süreci ne kadar sürer?",
    a: "Süre; mahkemenin iş yüküne, delillerin durumuna ve dosyanın niteliğine göre değişir; kesin bir süre söylenemez. Aşağıdaki rakamlar yalnız kaba bir tahmindir: ilk derece mahkemelerinde çoğu dava 1–2 yıl, istinaf ve temyiz aşamalarıyla birlikte 2–4 yıl sürebilir. Arabuluculukta anlaşma sağlanırsa uyuşmazlık çok daha kısa sürede sonuçlanabilir.",
  },
  {
    kategori: "Genel",
    q: "Bilgilerim gizli tutulur mu?",
    a: "Evet. Paylaştığınız bilgiler avukatın sır saklama yükümlülüğü ve kişisel verilerin korunması mevzuatı kapsamında korunur; yalnızca başvurunuzu değerlendirmek için kullanılır.",
    dayanak: [b("Avukatlık Kanunu", "1136", "36", "sır")],
  },
  {
    kategori: "İş Hukuku",
    q: "İşten çıkarıldım, hangi haklarım var?",
    a: "Koşulları varsa kıdem ve ihbar tazminatı, kullanılmayan yıllık izin ücreti ve ödenmemiş fazla çalışma ücretini talep edebilirsiniz. Otuz veya daha fazla işçi çalıştıran iş yerinde belirsiz süreli sözleşmeyle çalışıyor ve en az altı aylık kıdeminiz varsa, feshin geçerli bir nedene dayanmadığı iddiasıyla işe iade yoluna da başvurabilirsiniz. Her alacağın koşulu ayrıdır; ayrıntı için ilgili maddeye bakın.",
    dayanak: [
      b("İş Kanunu (mülga, 14. madde yürürlükte)", "1475", "14", "kıdem tazminat"),
      b("İş Kanunu", "4857", "17", "bildirim"),
      b("İş Kanunu", "4857", "59", "izin"),
      b("İş Kanunu", "4857", "41", "fazla çalışma"),
      b("İş Kanunu", "4857", "18", "otuz veya daha fazla"),
    ],
  },
  {
    kategori: "İş Hukuku",
    q: "İşe iade davası için süre sınırı var mı?",
    a: "Evet. Fesih bildiriminin tebliğinden itibaren bir ay içinde arabulucuya başvurmanız gerekir. Arabuluculukta anlaşma sağlanamazsa, son tutanağın düzenlendiği tarihten itibaren iki hafta içinde iş mahkemesinde dava açılabilir.",
    dayanak: [b("İş Kanunu", "4857", "20", "iki hafta")],
  },
  {
    kategori: "İş Hukuku",
    q: "Fazla mesai ücretimi nasıl ispatlarım?",
    a: "Fazla çalışmanın karşılığı kanunda düzenlenmiştir. Uygulamada puantaj kayıtları, giriş-çıkış verileri, yazışmalar ve tanık beyanları delil olarak sunulur; hangi delilin yeterli sayılacağı somut dosyaya ve yargı kararlarına göre değişir. Kayıt tutmanız ve yazışmaları saklamanız ispatı kolaylaştırır.",
    dayanak: [b("İş Kanunu", "4857", "41", "fazla çalışma")],
  },
  {
    kategori: "Aile Hukuku",
    q: "Boşanma süreci nasıl işler?",
    a: "Evlilik en az bir yıl sürmüşse ve eşler birlikte başvurur ya da bir eş diğerinin davasını kabul ederse, hâkim tarafları bizzat dinleyip anlaşmayı uygun bulduğunda boşanmaya karar verebilir (anlaşmalı boşanma). Anlaşma yoksa çekişmeli boşanma davasında deliller ve tanıklar dinlenir; bu yol belirgin biçimde daha uzun sürer.",
    dayanak: [b("Türk Medeni Kanunu", "4721", "166", "bir yıl")],
  },
  {
    kategori: "Aile Hukuku",
    q: "Nafaka miktarı nasıl belirlenir?",
    a: "Kanun üç ayrı nafaka düzenler: dava süresince eşin ve çocukların geçimi için alınan geçici önlemler (tedbir nafakası), boşanma yüzünden yoksulluğa düşecek ve kusuru daha ağır olmayan eş için yoksulluk nafakası ve velayet kendisine verilmeyen eşin çocuğun bakım ve eğitim giderlerine gücü oranında katılması (iştirak nafakası). Miktarda yükümlünün mali gücü esas alınır; tutarı somut duruma göre hâkim belirler.",
    dayanak: [
      b("Türk Medeni Kanunu", "4721", "169", "geçim"),
      b("Türk Medeni Kanunu", "4721", "175", "yoksulluğa"),
      b("Türk Medeni Kanunu", "4721", "182", "giderlerine"),
    ],
  },
  {
    kategori: "Aile Hukuku",
    q: "Velayet kime verilir?",
    a: "Hâkim boşanmaya karar verirken olanak bulundukça ana ve babayı dinler, ana babanın haklarını ve çocukla kişisel ilişkilerini düzenler; boşanmada velayet, çocuk kendisine bırakılan tarafa aittir. Bu düzenlemede çocuğun sağlık, eğitim ve ahlak bakımından yararı esas alınır; çocuğun kime bırakılacağı her dosyada ayrı değerlendirilir.",
    dayanak: [b("Türk Medeni Kanunu", "4721", "182", "yararları esas tutulur"), b("Türk Medeni Kanunu", "4721", "336", "çocuk kendisine bırakılan")],
  },
  {
    kategori: "Belgeler",
    q: "Başvuru için hangi belgeleri hazırlamalıyım?",
    a: "Kimlik fotokopisi, konuya ilişkin sözleşmeler, bordro veya SGK hizmet dökümü, ihtarname ve tebligatlar, yazışma ekran görüntüleri ve varsa mahkeme evrakları yeterlidir.",
  },
  {
    kategori: "Belgeler",
    q: "Vekâletname nasıl çıkarılır?",
    a: "Herhangi bir notere kimliğinizle giderek avukatın bilgileriyle dava vekâletnamesi düzenletebilirsiniz. Boşanma gibi kişiye sıkı sıkıya bağlı haklara ilişkin davalar için vekâletnamede bu konuda açık yetki bulunması gerekir; notere gitmeden önce avukatınıza hangi yetkilerin yazılacağını sorun ve noterin isteyebileceği fotoğrafı yanınızda bulundurun.",
    dayanak: [b("Hukuk Muhakemeleri Kanunu", "6100", "74", "kişiye sıkı sıkıya bağlı")],
  },
  {
    kategori: "Belgeler",
    q: "Belgelerimi dijital olarak iletebilir miyim?",
    a: "Evet. Başvurunuz alındıktan sonra tarafımızdan iletilecek güvenli bağlantı üzerinden ya da e-posta ile belgelerinizi paylaşabilirsiniz.",
  },
];

/** Cevabın altında gösterilen dayanak satırı: aynı kanunun maddeleri tek girdide toplanır. */
export function basisLabel(basis: FaqBasis[] | undefined): string {
  if (!basis?.length) return "";
  const byLaw = new Map<string, { kanun: string; maddeler: string[] }>();
  for (const item of basis) {
    const entry = byLaw.get(item.kanunNo) ?? { kanun: item.kanun, maddeler: [] };
    if (!entry.maddeler.includes(item.madde)) entry.maddeler.push(item.madde);
    byLaw.set(item.kanunNo, entry);
  }
  return [...byLaw.entries()].map(([no, entry]) => `${entry.kanun} (${no}) m. ${entry.maddeler.join(", ")}`).join("; ");
}

export function faqByCategory(kategori: string, items: FaqItem[] = FAQ_ITEMS): FaqItem[] {
  return kategori === "Tümü" ? items : items.filter((item) => item.kategori === kategori);
}
