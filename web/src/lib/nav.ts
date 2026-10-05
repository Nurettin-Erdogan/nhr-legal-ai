/**
 * Kenar çubuğu menüsü (veri ve eşleştirme; simgeler bileşende). Çalışan her ana sayfa buradan erişilebilir olmalıdır; "henüz bağlı değil"
 * diyen sayfalar (İcra, Müvekkil Adayları, Raporlar, Personel, Tahsilat, Aramalar) bilerek menüde yoktur: gerçek veri olmadan
 * çalışıyormuş izlenimi verilmez.
 */
export interface NavEntry {
  to: string;
  label: string;
}

export interface NavGroup {
  title: string;
  items: NavEntry[];
}

export const NAV_GROUPS: NavGroup[] = [
  {
    title: "Büro",
    items: [
      { to: "/dashboard", label: "Ana Sayfa" },
      { to: "/dashboard/cases", label: "Davalar" },
      { to: "/dashboard/clients", label: "Müvekkiller" },
      { to: "/dashboard/tasks", label: "Görevler" },
      { to: "/dashboard/calendar", label: "Takvim" },
      { to: "/dashboard/reminders", label: "Hatırlatmalar" },
      { to: "/dashboard/applications", label: "Başvurular" },
    ],
  },
  {
    title: "Hukuki araştırma",
    items: [
      { to: "/dashboard/ai", label: "Hukuk Asistanı" },
      { to: "/dashboard/legislation", label: "Mevzuat" },
      { to: "/dashboard/case-law", label: "İçtihat" },
      { to: "/dashboard/semantic-search", label: "Semantik İçtihat" },
      { to: "/dashboard/agent-research", label: "Derin Araştırma" },
    ],
  },
  {
    title: "Belge üretimi ve analiz",
    items: [
      { to: "/dashboard/drafts", label: "Dilekçe Yaz" },
      { to: "/dashboard/document-analysis", label: "Belge Analizi" },
      { to: "/dashboard/auto-summary", label: "Toplu Özet" },
      { to: "/dashboard/risk-analysis", label: "Risk Analizi" },
    ],
  },
  {
    title: "Dosyalar ve UYAP",
    items: [
      { to: "/dashboard/files", label: "Dosyalar" },
      { to: "/dashboard/uyap", label: "UYAP'a Bağlan" },
      { to: "/dashboard/document-processing", label: "Belge İşleme (OCR)" },
      { to: "/dashboard/scanner", label: "Belge Tarayıcı" },
      { to: "/dashboard/automation", label: "Tek Tuşla Otomasyon" },
    ],
  },
  {
    title: "Hesap",
    items: [{ to: "/dashboard/settings", label: "Ayarlar" }],
  },
];

export const NAV_ITEMS: NavEntry[] = NAV_GROUPS.flatMap((group) => group.items);

/** Kapatılan menü başlıkları tarayıcıda bu anahtarla saklanır (yalnız görünüm tercihi; sunucuya gitmez). */
export const NAV_COLLAPSED_KEY = "jurisai.nav.collapsed";

/** Saklanan değeri okur: bozuk veri ya da artık var olmayan başlık menüyü bozmaz, yok sayılır. */
export function parseCollapsedGroups(raw: string | null | undefined, groups: NavGroup[] = NAV_GROUPS): string[] {
  if (!raw) return [];
  try {
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    const titles = new Set(groups.map((group) => group.title));
    return [...new Set(parsed.filter((value): value is string => typeof value === "string" && titles.has(value)))];
  } catch {
    return [];
  }
}

export function toggleCollapsedGroup(collapsed: string[], title: string): string[] {
  return collapsed.includes(title) ? collapsed.filter((value) => value !== title) : [...collapsed, title];
}

/** Kapalı başlık altında yalnız açık olan sayfa görünür kalır; kullanıcı nerede olduğunu menüde kaybetmez. */
export function visibleNavItems(group: NavGroup, collapsed: boolean, activePath: string | null): NavEntry[] {
  return collapsed ? group.items.filter((item) => item.to === activePath) : group.items;
}

/**
 * Hangi menü girdisi etkin: tam eşleşme ya da yol öneki (alt sayfalar: /dashboard/cases/123 → Davalar). Birden çok girdi eşleşirse en uzun
 * yol kazanır, böylece /dashboard/case-law ile /dashboard/cases birbirine karışmaz; Ana Sayfa yalnız tam eşleşmede etkindir.
 */
export function activeNavPath(pathname: string, items: NavEntry[] = NAV_ITEMS): string | null {
  const clean = pathname.length > 1 ? pathname.replace(/\/+$/, "") : pathname;
  const matches = items.filter((item) => (item.to === "/dashboard" ? clean === item.to : clean === item.to || clean.startsWith(`${item.to}/`)));
  return matches.sort((a, b) => b.to.length - a.to.length)[0]?.to ?? null;
}
