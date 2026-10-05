import { db } from "@/lib/db";

export type FeedbackCategory = "hata" | "oneri" | "begeni";

export const FEEDBACK_CATEGORIES: { value: FeedbackCategory; label: string }[] = [
  { value: "hata", label: "Bir şey çalışmıyor / yanlış" },
  { value: "oneri", label: "Öneri / eksik" },
  { value: "begeni", label: "Beğendim" },
];

export const MIN_FEEDBACK = 3;
export const MAX_FEEDBACK = 4000;

/** Gönderilebilir mi: kırpılmış metin sınırlar içinde. */
export const canSendFeedback = (message: string): boolean => {
  const length = message.trim().length;
  return length >= MIN_FEEDBACK && message.length <= MAX_FEEDBACK;
};

/** Sayfa yolu: yalnız yol; sorgu dizesi ve parça (kimlik, arama metni) atılır, en çok 200 karakter. */
export const pageOf = (pathname: string): string => pathname.split(/[?#]/)[0].slice(0, 200);

/** Geri bildirimi kaydeder. Belge/sohbet içeriği eklenmez; yalnız yazılan metin ve sayfa yolu gider. */
export async function sendFeedback(input: { category: FeedbackCategory; message: string; pathname: string }): Promise<void> {
  const { error } = await db.from("feedback").insert({ category: input.category, message: input.message.trim(), page: pageOf(input.pathname) });
  if (error) throw new Error(error.message || "Geri bildirim gönderilemedi.");
}
