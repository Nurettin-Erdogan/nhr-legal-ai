/** Ana menü iş alanlarını gösterir; araçlar ilgili alandaki sekme ve işlemlerden açılır. */
export interface NavEntry {
  to: string;
  label: string;
  /** Yalnız yönetici rolüne gösterilir (sayfa da kendi başına denetler; sunucu yetkisi ayrıdır). */
  adminOnly?: boolean;
}

export interface NavGroup {
  title: string;
  items: NavEntry[];
}

export const NAV_GROUPS: NavGroup[] = [
  {
    title: "Çalışma alanı",
    items: [
      { to: "/dashboard", label: "Ana Sayfa" },
      { to: "/dashboard/ai", label: "Hukuk Asistanı" },
      { to: "/dashboard/cases", label: "Davalar ve Projeler" },
      { to: "/dashboard/execution", label: "İcra Takibi" },
      { to: "/dashboard/files", label: "Belgeler" },
      { to: "/dashboard/uyap", label: "UYAP Aktarımı" },
    ],
  },
  {
    title: "Araştırma ve üretim",
    items: [
      { to: "/dashboard/case-law", label: "İçtihat", adminOnly: true },
      { to: "/dashboard/legislation", label: "Mevzuat" },
      { to: "/dashboard/drafts", label: "Belge Hazırla" },
    ],
  },
  {
    title: "Büro",
    items: [
      { to: "/dashboard/bureau-assistant", label: "Büro Asistanı" },
      { to: "/dashboard/clients", label: "Müvekkiller" },
      { to: "/dashboard/tasks", label: "İş Takibi" },
    ],
  },
];

/** Menüde gösterilecek gruplar: yönetici dışındaki roller `adminOnly` girdileri görmez. */
export function visibleNavGroups(admin: boolean): NavGroup[] {
  return NAV_GROUPS.map((group) => ({
    ...group,
    items: group.items.filter((item) => admin || !item.adminOnly),
  })).filter((group) => group.items.length > 0);
}

export const ACCOUNT_NAV: NavEntry = { to: "/dashboard/settings", label: "Ayarlar" };
/** Yalnız yönetici rolündeki kullanıcıya gösterilir (yetki sunucuda ayrıca denetlenir). */
export const ADMIN_NAV: NavEntry = { to: "/dashboard/admin", label: "Yönetim" };
export const NAV_ITEMS: NavEntry[] = [...NAV_GROUPS.flatMap((group) => group.items), ACCOUNT_NAV];

/** Alt ekranlar ana menüde kendi çalışma alanlarını etkin tutar. Eski adresler de erişilebilir. */
export const NAV_PARENTS: Record<string, string> = {
  "/dashboard/projects": "/dashboard/cases",
  "/dashboard/calendar": "/dashboard/tasks",
  "/dashboard/reminders": "/dashboard/tasks",
  "/dashboard/applications": "/dashboard/clients",
  "/dashboard/scanner": "/dashboard/files",
  "/dashboard/document-processing": "/dashboard/files",
  "/dashboard/automation": "/dashboard/files",
  "/dashboard/agent-research": "/dashboard/ai",
  "/dashboard/document-analysis": "/dashboard/ai",
  "/dashboard/auto-summary": "/dashboard/ai",
  "/dashboard/risk-analysis": "/dashboard/ai",
  "/dashboard/research": "/dashboard/ai",
  "/dashboard/semantic-search": "/dashboard/case-law",
};

export const SECTION_NAV: NavGroup[] = [
  {
    title: "Dosya çalışma alanları",
    items: [
      { to: "/dashboard/cases", label: "Davalar" },
      { to: "/dashboard/projects", label: "Projeler" },
    ],
  },
  {
    title: "İş takibi görünümleri",
    items: [
      { to: "/dashboard/tasks", label: "Görevler" },
      { to: "/dashboard/calendar", label: "Takvim" },
      { to: "/dashboard/reminders", label: "Hatırlatmalar" },
    ],
  },
  {
    title: "Müvekkil görünümleri",
    items: [
      { to: "/dashboard/clients", label: "Müvekkiller" },
      { to: "/dashboard/applications", label: "Gelen başvurular" },
    ],
  },
  {
    title: "Belge araçları",
    items: [
      { to: "/dashboard/files", label: "Belge arşivi" },
      { to: "/dashboard/scanner", label: "Kamerayla tara" },
      { to: "/dashboard/document-processing", label: "Metin çıkar (OCR)" },
    ],
  },
];

/** Kapatılan menü başlıkları tarayıcıda bu anahtarla saklanır (yalnız görünüm tercihi; sunucuya gitmez). */
export const NAV_COLLAPSED_KEY = "jurisai.nav.collapsed";

/** Saklanan değeri okur: bozuk veri ya da artık var olmayan başlık menüyü bozmaz, yok sayılır. */
export function parseCollapsedGroups(
  raw: string | null | undefined,
  groups: NavGroup[] = NAV_GROUPS,
): string[] {
  if (!raw) return [];
  try {
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    const titles = new Set(groups.map((group) => group.title));
    return [
      ...new Set(
        parsed.filter((value): value is string => typeof value === "string" && titles.has(value)),
      ),
    ];
  } catch {
    return [];
  }
}

export function toggleCollapsedGroup(collapsed: string[], title: string): string[] {
  return collapsed.includes(title)
    ? collapsed.filter((value) => value !== title)
    : [...collapsed, title];
}

/** Etkin sayfanın bölümü, saklanan kapatma tercihinden bağımsız olarak her zaman açık kalır. */
export function isNavGroupCollapsed(
  group: NavGroup,
  collapsed: boolean,
  activePath: string | null,
): boolean {
  return collapsed && !group.items.some((item) => item.to === activePath);
}

export function visibleNavItems(
  group: NavGroup,
  collapsed: boolean,
  activePath: string | null,
): NavEntry[] {
  return isNavGroupCollapsed(group, collapsed, activePath) ? [] : group.items;
}

/**
 * Hangi menü girdisi etkin: tam eşleşme ya da yol öneki (alt sayfalar: /dashboard/cases/123 → Davalar). Birden çok girdi eşleşirse en uzun
 * yol kazanır, böylece /dashboard/case-law ile /dashboard/cases birbirine karışmaz; Ana Sayfa yalnız tam eşleşmede etkindir.
 */
export function activeNavPath(pathname: string, items: NavEntry[] = NAV_ITEMS): string | null {
  const clean = pathname.length > 1 ? pathname.replace(/\/+$/, "") : pathname;
  const parent = Object.keys(NAV_PARENTS)
    .sort((a, b) => b.length - a.length)
    .find((path) => clean === path || clean.startsWith(`${path}/`));
  if (parent && items.some((item) => item.to === NAV_PARENTS[parent])) return NAV_PARENTS[parent];
  const matches = items.filter((item) =>
    item.to === "/dashboard"
      ? clean === item.to
      : clean === item.to || clean.startsWith(`${item.to}/`),
  );
  return matches.sort((a, b) => b.to.length - a.to.length)[0]?.to ?? null;
}
