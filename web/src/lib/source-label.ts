/**
 * Kaynak etiketi: bir karar/mevzuat kaydının doğrulama durumunun ekranda ve kopyalanan metinde nasıl yazılacağı.
 *
 * Kural (AGENTS.md, kullanıcı kararı 2026-10-15):
 *   - Resmî metinle karşılaştırılmış kayıt (`official`): "Resmî metin ✓".
 *   - Karşılaştırılmamış kayıt (`third_party`, toplu derleme): olumsuz ibare YOK. Künyesiyle ("Yargıtay kararı · E./K.") ve kararı
 *     resmî portalda açan "Resmî sitede aç" bağlantısıyla gösterilir. Hiçbir yerde "resmî", "doğrulandı" ya da ✓ ile gösterilmez.
 *   - Kullanıcının kendi belgesi: "kullanıcı belgesi".
 * Ayrım kalkmıyor: resmî kayıt ✓ taşır, karşılaştırılmamış kayıt taşımaz. Durum her istekte sunucudan gelir (bir karar bugün
 * karşılaştırılmamış, yarın resmî olabilir); burada saklanmaz.
 */

export type SourceVerification = "official" | "third_party" | "user_document" | "unknown" | string;

export const OFFICIAL_TAG = "Resmî metin ✓";

// Yalnız resmî karar arama portallarına bağlantı verilir (kaydın `source_url`'i başka bir yeri gösteriyorsa bağlantı yok).
const PORTALS: ReadonlyArray<[RegExp, string]> = [
  [/^https:\/\/karararama\.yargitay\.gov\.tr\//i, "Yargıtay kararı"],
  [/^https:\/\/karararama\.danistay\.gov\.tr\//i, "Danıştay kararı"],
];

/** Kaydın resmî portal adresi ("Resmî sitede aç" için); resmî karar arama portalı değilse null. */
export function officialPortalUrl(url: string | null | undefined): string | null {
  const value = (url ?? "").trim();
  return PORTALS.some(([pattern]) => pattern.test(value)) ? value : null;
}

/** Kaynak adı ("Yargıtay kararı", "Danıştay kararı"); adresten okunur, bilinmiyorsa mahkeme adından, o da yoksa "Karar". */
export function decisionSourceName(url: string | null | undefined, courtName?: string | null): string {
  const value = (url ?? "").trim();
  const portal = PORTALS.find(([pattern]) => pattern.test(value));
  if (portal) return portal[1];
  const court = (courtName ?? "").toLocaleLowerCase("tr-TR");
  if (court.includes("yargıtay")) return "Yargıtay kararı";
  if (court.includes("danıştay")) return "Danıştay kararı";
  return "Karar";
}

/** Ekranda gösterilecek rozet; karşılaştırılmamış ya da durumu bilinmeyen kayıtta rozet yoktur (olumsuz ibare yazılmaz). */
export function verificationTag(verification: SourceVerification): { label: string; tone: "official" | "document" } | null {
  if (verification === "official") return { label: OFFICIAL_TAG, tone: "official" };
  if (verification === "user_document") return { label: "kullanıcı belgesi", tone: "document" };
  return null;
}

/**
 * Kopyalanan/dışa aktarılan atıf satırının eki. Resmî kayıt "(Resmî metin ✓)", kullanıcı belgesi "(kullanıcı belgesi)";
 * karşılaştırılmamış kayıt resmî portal adresiyle ("— resmî sitede: …") ayrışır, ✓ almaz.
 */
export function citationSuffix(verification: SourceVerification, url?: string | null): string {
  if (verification === "official") return ` (${OFFICIAL_TAG})`;
  if (verification === "user_document") return " (kullanıcı belgesi)";
  const portal = officialPortalUrl(url);
  return portal ? ` — resmî sitede: ${portal}` : "";
}
