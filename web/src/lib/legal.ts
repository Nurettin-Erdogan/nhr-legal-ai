/**
 * Hukuki metinlerin sürümü: başvuru formu hangi aydınlatma metni sürümünün gösterildiğini sunucuya bildirir (kayıt altına alınır).
 * Metin değiştiğinde sürüm de değiştirilir.
 *
 * `LEGAL_DRAFT` true iken sayfalarda "taslak" uyarısı gösterilir: metinler bir hukuk danışmanı onaylayıp veri sorumlusu bilgileri
 * (`CONTROLLER`) doldurulana kadar yayın metni değildir.
 */
export const LEGAL_DRAFT = true;
export const PRIVACY_NOTICE_VERSION = "2026-10-taslak";
export const TERMS_VERSION = "2026-10-taslak";

/** Doldurulmamış veri sorumlusu bilgileri bilerek köşeli parantezli bırakılır; uydurulmaz. */
export const CONTROLLER = {
  name: "[Veri sorumlusu unvanı]",
  address: "[Adres]",
  email: "[KVKK başvuru e-posta adresi]",
};

export const hasPlaceholders = (text: string): boolean => /\[[^\]]+\]/.test(text);
