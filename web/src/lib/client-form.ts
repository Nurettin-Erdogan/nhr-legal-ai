/**
 * Müvekkil formundaki kimlik ve iletişim alanlarının denetimi.
 *
 * Alanlar isteğe bağlıdır; doldurulmuşsa biçimi denetlenir. TC kimlik ve vergi numaraları dilekçelere ve UYAP
 * kayıtlarına aynen taşındığı için yanlış yazılmış numara kaydedilmeden yakalanır (hane denetimi resmî algoritmadır).
 */

const digitsOnly = (value: string) => value.replace(/[\s.-]/g, "");

/** TC kimlik no (yabancı kimlik no dâhil): 11 hane, ilk hane 0 değil, 10. ve 11. haneler denetim hanesi. */
export function validNationalId(value: string): boolean {
  const text = digitsOnly(value);
  if (!/^[1-9]\d{10}$/.test(text)) return false;
  const d = [...text].map(Number);
  const odd = d[0] + d[2] + d[4] + d[6] + d[8];
  const even = d[1] + d[3] + d[5] + d[7];
  if ((((odd * 7 - even) % 10) + 10) % 10 !== d[9]) return false;
  return d.slice(0, 10).reduce((sum, digit) => sum + digit, 0) % 10 === d[10];
}

/** Vergi kimlik no: 10 hane, son hane denetim hanesi. */
export function validTaxId(value: string): boolean {
  const text = digitsOnly(value);
  if (!/^\d{10}$/.test(text)) return false;
  let sum = 0;
  for (let index = 0; index < 9; index += 1) {
    const shifted = (Number(text[index]) + 9 - index) % 10;
    let part = (shifted * 2 ** (9 - index)) % 9;
    if (shifted !== 0 && part === 0) part = 9;
    sum += part;
  }
  return (10 - (sum % 10)) % 10 === Number(text[9]);
}

/** Telefon: rakam, boşluk, +, parantez ve tire; 10–15 rakam. */
export function validPhone(value: string): boolean {
  const text = value.trim();
  if (!/^\+?[\d\s()-]+$/.test(text)) return false;
  const count = text.replace(/\D/g, "").length;
  return count >= 10 && count <= 15;
}

export interface ClientIdentityFields {
  client_type: string;
  national_id?: string | null;
  tax_id?: string | null;
  phone?: string | null;
}

/** İlk sorunun kullanıcıya gösterilecek açıklaması; sorun yoksa null. */
export function clientFormProblem(form: ClientIdentityFields): string | null {
  const nationalId = (form.national_id ?? "").trim();
  const taxId = (form.tax_id ?? "").trim();
  const phone = (form.phone ?? "").trim();
  if (form.client_type === "corporate") {
    // Şahıs işletmelerinde vergi numarası olarak TC kimlik no kullanılır; ikisi de kabul edilir.
    if (taxId && !validTaxId(taxId) && !validNationalId(taxId)) {
      return digitsOnly(taxId).length === 10 || digitsOnly(taxId).length === 11
        ? "Vergi numarası geçersiz görünüyor; haneleri kontrol edin."
        : "Vergi numarası 10 haneli olmalı (şahıs işletmesinde 11 haneli TC kimlik no).";
    }
  } else if (nationalId && !validNationalId(nationalId)) {
    return digitsOnly(nationalId).length === 11 && /^\d+$/.test(digitsOnly(nationalId))
      ? "TC kimlik numarası geçersiz görünüyor; haneleri kontrol edin."
      : "TC kimlik numarası 11 haneli olmalı.";
  }
  if (phone && !validPhone(phone))
    return "Telefon numarası geçersiz; alan koduyla birlikte en az 10 rakam yazın.";
  return null;
}
