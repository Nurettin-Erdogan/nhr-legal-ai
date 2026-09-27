// AvukatAI — Demo verileri kaldırıldı.
// Her kullanıcı kendi gerçek verisini görür. Sayfalar boş başlar.

export const todayCalls: any[] = [];
export const upcomingAppointments: any[] = [];
export const leads: any[] = [];
export const fileQueries: any[] = [];
export const reminders: any[] = [];
export const modules: any[] = [
  {
    id: "inbound",
    name: "Inbound AI Asistan",
    desc: "7/24 gelen aramaları doğal Türkçe sesle karşılar.",
    active: false,
    icon: "Phone",
  },
  {
    id: "appointments",
    name: "Randevu Yönetimi",
    desc: "Müsait saatlere göre otomatik randevu oluşturur.",
    active: false,
    icon: "Calendar",
  },
  {
    id: "files",
    name: "Dosya Sorgulama",
    desc: "Müvekkillere dosya durumu hakkında bilgi verir.",
    active: false,
    icon: "FolderSearch",
  },
  {
    id: "outbound",
    name: "Outbound Hatırlatma",
    desc: "Duruşma ve randevu öncesi otomatik arama yapar.",
    active: false,
    icon: "PhoneOutgoing",
  },
  {
    id: "documents",
    name: "Evrak Hatırlatma",
    desc: "Eksik evrakları takip eder ve müvekkili bilgilendirir.",
    active: false,
    icon: "FileText",
  },
  {
    id: "whatsapp",
    name: "WhatsApp Bilgilendirme",
    desc: "Randevu ve duruşma bilgilendirmesi gönderir.",
    active: false,
    icon: "MessageSquare",
  },
  {
    id: "reporting",
    name: "Raporlama",
    desc: "Detaylı çağrı, dönüşüm ve performans raporları.",
    active: false,
    icon: "BarChart3",
  },
  {
    id: "crm",
    name: "CRM Entegrasyonu",
    desc: "Mevcut CRM sisteminizle çift yönlü senkronizasyon.",
    active: false,
    icon: "Database",
  },
];

export const clients: any[] = [];
export const cases: any[] = [];
export const executions: any[] = [];
export const calendarEvents: any[] = [];
export const payments: any[] = [];
export const staff: any[] = [];
export const tasks: any[] = [];
export const activities: any[] = [];

export const monthlyRevenue = [
  { month: "Kas", value: 0 },
  { month: "Ara", value: 0 },
  { month: "Oca", value: 0 },
  { month: "Şub", value: 0 },
  { month: "Mar", value: 0 },
  { month: "Nis", value: 0 },
];

export const leadFunnel = [
  { stage: "Gelen Arama", value: 0 },
  { stage: "Lead", value: 0 },
  { stage: "Randevu", value: 0 },
  { stage: "Müvekkil", value: 0 },
];

export const precedents: any[] = [];
export const researchHistory: any[] = [];

export const draftTemplates = [
  {
    id: "bosanma",
    name: "Boşanma Dilekçesi",
    category: "Aile Hukuku",
    desc: "Anlaşmalı / çekişmeli boşanma için tam donanımlı şablon.",
    icon: "Scale",
  },
  {
    id: "icra-itiraz",
    name: "İcra İtiraz Dilekçesi",
    category: "İcra İflas",
    desc: "Ödeme emrine itiraz, borca / imzaya itiraz dahil.",
    icon: "Gavel",
  },
  {
    id: "iscilik",
    name: "İşçilik Alacağı Dilekçesi",
    category: "İş Hukuku",
    desc: "Kıdem, ihbar, fazla mesai ve diğer alacaklar.",
    icon: "Briefcase",
  },
  {
    id: "velayet",
    name: "Velayet Talep Dilekçesi",
    category: "Aile Hukuku",
    desc: "Velayet değişikliği veya ortak velayet talebi.",
    icon: "Users",
  },
  {
    id: "tahliye",
    name: "Tahliye İhtarnamesi",
    category: "Gayrimenkul",
    desc: "Kira sözleşmesinin sona ermesi için resmi ihtar.",
    icon: "FileText",
  },
  {
    id: "basvuru",
    name: "Genel Başvuru Dilekçesi",
    category: "Genel",
    desc: "Resmi kurum başvuruları için çok amaçlı şablon.",
    icon: "FileSignature",
  },
  {
    id: "ihtarname",
    name: "Ödeme İhtarnamesi",
    category: "Ticaret",
    desc: "Borçluya çekilecek noter ihtarı şablonu.",
    icon: "Mail",
  },
  {
    id: "tazminat",
    name: "Tazminat Davası Dilekçesi",
    category: "Tazminat",
    desc: "Maddi-manevi tazminat talepleri için baz şablon.",
    icon: "Shield",
  },
];

export const aiPipeline = [
  { step: 1, name: "Kullanıcı Sorgusu", desc: "Doğal dilde soru veya belge" },
  { step: 2, name: "Metin Temizleme", desc: "Normalizasyon ve ön işlem" },
  { step: 3, name: "Intent Sınıflandırma", desc: "Sorgu tipi belirleme" },
  { step: 4, name: "Belge Parsing", desc: "PDF/DOCX yapı çıkarımı" },
  { step: 5, name: "Hukuki Embedding", desc: "Vektör temsil oluşturma" },
  { step: 6, name: "Vector DB Sorgu", desc: "Semantik benzerlik araması" },
  { step: 7, name: "Semantik Arama", desc: "İçtihat & mevzuat tarama" },
  { step: 8, name: "Hukuk LLM", desc: "Bağlamsal analiz ve sentez" },
  { step: 9, name: "Kaynak Doğrulama", desc: "Atıf doğruluğu kontrolü" },
  { step: 10, name: "Tutarlılık Skoru", desc: "Çelişki tespiti" },
  { step: 11, name: "Legal Engineer", desc: "İnsan denetim katmanı" },
  { step: 12, name: "Doğrulanmış Sonuç", desc: "Kaynakçalı çıktı" },
];

export const aiCallLogs: any[] = [];
