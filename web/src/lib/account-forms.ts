/**
 * Hesap formlarının saf doğrulama ve mesaj kuralları (bileşenlerden bağımsız, test edilebilir).
 */
export const MIN_PASSWORD_LENGTH = 10;
export const DELETE_PHRASE = "HESABIMI SİL";

/**
 * Giriş/kayıt hatasını kullanıcıya gösterilecek cümleye çevirir.
 *
 * Eski sürüm içinde "parola" geçen her mesajı "Şifre en az 10 karakter olmalı." diye gösteriyordu; yanlış parolada sunucunun
 * "E-posta veya parola hatalı" yanıtı bu yüzden yanıltıcı bir uzunluk uyarısına dönüşüyordu. Sunucunun Türkçe mesajı varsa
 * aynen gösterilir; yalnız bilinen İngilizce/teknik kalıplar çevrilir.
 */
export function authErrorMessage(message: string, status?: number): string {
  const lowered = message.toLowerCase();
  if (status === 401 || lowered.includes("invalid login")) return "E-posta veya şifre hatalı.";
  if (
    status === 409 ||
    lowered.includes("already registered") ||
    lowered.includes("already exists")
  )
    return "Bu e-posta ile zaten bir hesap var. Giriş yapmayı deneyin.";
  if (status === 429) return message; // sunucu bekleme süresini söyler
  if (lowered.includes("at least 10 characters") || lowered.includes("string should have at least"))
    return `Şifre en az ${MIN_PASSWORD_LENGTH} karakter olmalı.`;
  if (lowered.includes("valid email") || lowered.includes("email address"))
    return "Geçerli bir e-posta adresi girin.";
  return message;
}

export function validateNewPassword(next: string, repeat: string): string | null {
  if (next.length < MIN_PASSWORD_LENGTH)
    return `Yeni şifre en az ${MIN_PASSWORD_LENGTH} karakter olmalı.`;
  if (next.length > 128) return "Şifre en çok 128 karakter olabilir.";
  if (next !== repeat) return "Şifreler birbiriyle aynı değil.";
  return null;
}

export function validatePasswordChange(
  current: string,
  next: string,
  repeat: string,
  hasPassword: boolean,
): string | null {
  if (hasPassword && !current) return "Mevcut şifrenizi girin.";
  const problem = validateNewPassword(next, repeat);
  if (problem) return problem;
  if (hasPassword && current === next) return "Yeni şifre mevcut şifreyle aynı olamaz.";
  return null;
}

export function validateAccountDeletion(
  phrase: string,
  password: string,
  hasPassword: boolean,
): string | null {
  if (phrase.trim() !== DELETE_PHRASE) return `Onaylamak için kutuya ${DELETE_PHRASE} yazın.`;
  if (hasPassword && !password) return "Şifrenizi girin.";
  return null;
}

export function validateFullName(name: string): string | null {
  const clean = name.trim().replace(/\s+/g, " ");
  if (clean.length < 2) return "Ad soyad en az 2 karakter olmalı.";
  if (clean.length > 150) return "Ad soyad en çok 150 karakter olabilir.";
  return null;
}
