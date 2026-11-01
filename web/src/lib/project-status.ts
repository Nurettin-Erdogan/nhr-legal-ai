/** Proje durumunun Türkçe karşılığı; bilinmeyen değer olduğu gibi gösterilir. */
const LABELS: Record<string, string> = {
  active: "Aktif",
  paused: "Beklemede",
  on_hold: "Beklemede",
  completed: "Tamamlandı",
  done: "Tamamlandı",
  closed: "Kapalı",
  archived: "Arşivde",
};

export const projectStatusLabel = (status: string): string => LABELS[status] ?? status;
