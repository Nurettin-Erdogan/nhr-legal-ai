/**
 * Kaynak etiketi: bir karar/mevzuat kaydının ekranda ve kopyalanan metinde nasıl yazılacağı.
 *
 * Kural (AGENTS.md, kullanıcı kararı 2026-10-18): uygulamada yalnız resmî metinle karşılaştırılmış kayıtlar aranır ve gösterilir.
 * Her kaynak doğrulanmış olduğundan "doğrulanmış / doğrulanmamış" ayrımı ekrandan kalktı: kayıt künyesiyle ("Yargıtay kararı ·
 * E./K.") ve kararı resmî portalda açan "Resmî sitede aç" bağlantısıyla gösterilir, ✓ rozeti yoktur.
 *   - Kullanıcının kendi belgesi hukuk kaynağı değildir; "kullanıcı belgesi" diye ayrılır.
 *   - Resmî olmayan bir kayıt (eski bir sohbette kalmış olabilir) hiçbir yerde "resmî", "doğrulandı" ya da ✓ ile gösterilmez.
 */

export type SourceVerification = "official" | "third_party" | "user_document" | "unknown" | string;

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
export function decisionSourceName(
  url: string | null | undefined,
  courtName?: string | null,
): string {
  const value = (url ?? "").trim();
  const portal = PORTALS.find(([pattern]) => pattern.test(value));
  if (portal) return portal[1];
  const court = (courtName ?? "").toLocaleLowerCase("tr-TR");
  if (court.includes("yargıtay")) return "Yargıtay kararı";
  if (court.includes("danıştay")) return "Danıştay kararı";
  return "Karar";
}

/** Ekranda gösterilecek rozet: yalnız kullanıcı belgesi ayrılır; hukuk kaynaklarında doğrulama rozeti yoktur. */
export function verificationTag(
  verification: SourceVerification,
): { label: string; tone: "document" } | null {
  if (verification === "user_document") return { label: "kullanıcı belgesi", tone: "document" };
  return null;
}

/**
 * Kopyalanan/dışa aktarılan atıf satırının eki: kullanıcı belgesi "(kullanıcı belgesi)"; karar resmî portal adresiyle
 * ("— resmî sitede: …"). Doğrulama ibaresi ya da ✓ yazılmaz.
 */
export function citationSuffix(verification: SourceVerification, url?: string | null): string {
  if (verification === "user_document") return " (kullanıcı belgesi)";
  const portal = officialPortalUrl(url);
  return portal ? ` — resmî sitede: ${portal}` : "";
}
