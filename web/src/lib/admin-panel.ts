/**
 * Yönetici paneli için arayüzden bağımsız yardımcılar: etiketler ve biçimlendirme.
 * Yetki sunucuda denetlenir (`/api/admin/*` yalnız yöneticiye açık); buradaki `isAdmin` yalnız menüyü ve sayfayı gizler.
 */

export const ROLE_LABELS: Record<string, string> = {
  admin: "Yönetici",
  lawyer: "Avukat",
  assistant: "Asistan",
  viewer: "Görüntüleyici",
};

export const STATUS_LABELS: Record<string, string> = {
  active: "Aktif",
  inactive: "Pasif",
  suspended: "Askıda",
};

export const ACCESS_MODE_LABELS: Record<string, { label: string; description: string }> = {
  allowlist: {
    label: "Yalnız listedeki e-postalar",
    description:
      "Yalnız erişim listesine eklediğiniz e-posta adresleri hesap açabilir ve giriş yapabilir. Yöneticiler her zaman girer.",
  },
  open: { label: "Herkes", description: "Bağlantıyı bilen herkes hesap açıp giriş yapabilir." },
};

/** Erişim modunu değiştirmeden önce sorulan soru: kaç hesabın dışarıda kalacağını sayıyla söyler. */
export function accessModeConfirm(mode: string, unlistedAccounts: number): string {
  if (mode !== "allowlist") return "Bağlantıyı bilen herkes hesap açıp giriş yapabilecek. Devam edilsin mi?";
  if (unlistedAccounts <= 0)
    return "Bundan sonra yalnız listedeki e-postalar hesap açıp giriş yapabilecek. Devam edilsin mi?";
  return `Listede olmayan ${unlistedAccounts.toLocaleString("tr-TR")} hesap artık giriş yapamayacak ve açık oturumları hemen kapanacak (yöneticiler hariç). Verileri silinmez. Devam edilsin mi?`;
}

/** Listeden çıkarmadan önce sorulan soru; "Herkes" modunda çıkarmanın hemen etkisi olmadığını da söyler. */
export function removeAccessConfirm(email: string, mode: string): string {
  return mode === "allowlist"
    ? `${email} listeden çıkarılsın mı? Hesabı varsa açık oturumu hemen kapanır ve giriş yapamaz (yöneticiler hariç). Verileri silinmez.`
    : `${email} listeden çıkarılsın mı? Erişim "Herkes" modunda olduğu için şimdilik girmeye devam eder.`;
}

/** Erişim listesindeki e-postanın hesabı: henüz açılmamış olabilir. */
export function accountStateLabel(status: string | null | undefined): string {
  if (!status) return "Henüz hesap açmadı";
  if (status === "active") return "Hesabı var";
  return `Hesabı ${(STATUS_LABELS[status] ?? status).toLocaleLowerCase("tr-TR")}`;
}

export const FEEDBACK_LABELS: Record<string, string> = { hata: "Hata", oneri: "Öneri", begeni: "Beğeni" };

const ACTION_LABELS: Record<string, string> = {
  "auth.login": "Giriş yaptı",
  "auth.login_failed": "Başarısız giriş denemesi",
  "auth.register": "Hesap açtı",
  "auth.logout": "Çıkış yaptı",
  "auth.login_blocked": "Giriş engellendi (erişim listesinde değil)",
  "auth.google_link": "Google hesabını bağladı",
  "ai.answer": "Asistana soru sordu",
  "project.create": "Proje oluşturdu",
  "document.upload": "Belge yükledi",
  "conversation.delete": "Sohbet sildi",
  "admin.user_status": "Kullanıcı durumunu değiştirdi",
  "admin.role_grant": "Rol verdi",
  "admin.role_revoke": "Rol kaldırdı",
  "admin.access_mode": "Erişim modunu değiştirdi",
  "admin.access_add": "Erişim listesine ekledi",
  "admin.access_remove": "Erişim listesinden çıkardı",
  // Erişim listesinden önceki davet düzeni (yalnız 2026-10-24 denemelerinde kayda geçti).
  "admin.registration_mode": "Kayıt modunu değiştirdi",
  "admin.invite_create": "Davet oluşturdu",
  "admin.invite_revoke": "Daveti iptal etti",
  "office.uyap_ingest": "UYAP evrakı aktardı",
  "office.uyap_case_linked": "UYAP dosyası bağladı",
  "office.document_index": "Belge dizinlendi",
  "office.case_document_trash": "Belgeyi çöpe attı",
  "office.case_document_delete_forever": "Belgeyi kalıcı sildi",
  "office.insert": "Kayıt ekledi",
  "office.update": "Kayıt güncelledi",
  "office.file_upload": "Dosya yükledi",
};

/** Denetim kaydındaki işlem kodunun Türkçe karşılığı; bilinmeyen kod olduğu gibi gösterilir (gizlenmez). */
export function actionLabel(action: string): string {
  return ACTION_LABELS[action] ?? action;
}

export function isAdmin(roles: readonly string[] | null | undefined): boolean {
  return Array.isArray(roles) && roles.includes("admin");
}

/** "24.10.2026 15:43"; boş ya da bozuk değer "—". */
export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString("tr-TR", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function formatCount(value: number | null | undefined): string {
  return typeof value === "number" && Number.isFinite(value) ? value.toLocaleString("tr-TR") : "—";
}

export function formatUsd(value: number | null | undefined): string {
  return typeof value === "number" && Number.isFinite(value) ? `${value.toFixed(2)} $` : "—";
}

export function formatBytes(value: number | null | undefined): string {
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0) return "—";
  if (value >= 1e9) return `${(value / 1e9).toFixed(1)} GB`;
  if (value >= 1e6) return `${(value / 1e6).toFixed(0)} MB`;
  return `${Math.round(value / 1e3)} KB`;
}

/** Son yedeğin yaşı saat cinsinden; 26 saatten eskiyse panel uyarır (gece yedeği sessizce durabiliyordu, 2026-10-24). */
export function backupAgeHours(createdAt: string | null | undefined, now: Date = new Date()): number | null {
  if (!createdAt) return null;
  const created = new Date(createdAt);
  if (Number.isNaN(created.getTime())) return null;
  return Math.max(0, (now.getTime() - created.getTime()) / 3_600_000);
}

export const BACKUP_STALE_HOURS = 26;
