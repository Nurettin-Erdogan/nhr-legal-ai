/**
 * Eski Supabase edge function çağrılarının yerine geçen ince katman. Aynı `{ data, error }` sözleşmesini
 * korur; işler artık kendi FastAPI arka ucumuzda (yerel model, korpus atıfları) yapılır.
 */
import { askAssistant } from "@/lib/ai-api";
import { generateDocument, runOfficeModule } from "@/lib/office-api";

type Result<T> = { data: T | null; error: Error | null };

const handlers: Record<string, (body: Record<string, unknown>) => Promise<unknown>> = {
  "ai-legal": async (body) => {
    const result = await runOfficeModule({
      module: String(body.module ?? ""),
      prompt: String(body.prompt ?? ""),
      title: typeof body.title === "string" ? body.title : undefined,
      docIds: Array.isArray(body.docIds) ? (body.docIds as string[]) : [],
    });
    return { ...result, yargitay_context: null };
  },
  "generate-legal-document": (body) =>
    generateDocument({
      docType: String(body.docType ?? ""),
      title: typeof body.title === "string" ? body.title : undefined,
      parties: Array.isArray(body.parties) ? (body.parties as string[]) : [],
      subject: String(body.subject ?? ""),
      details: typeof body.details === "string" ? body.details : undefined,
      docIds: Array.isArray(body.docIds) ? (body.docIds as string[]) : [],
    }),
  "check-subscription": async () => ({
    // Ödeme sağlayıcısı henüz bağlı değil — herkes ücretsiz plandadır.
    subscribed: false,
    tier: null as string | null,
    subscription_end: null as string | null,
  }),
  "create-checkout": async () => {
    throw new Error(
      "Ödeme altyapısı henüz bağlı değil. Abonelik satın almak için lütfen bizimle iletişime geçin.",
    );
  },
  "legal-chat": async (body) => {
    const messages = Array.isArray(body.messages)
      ? (body.messages as Array<{ role: string; content: string }>)
      : [];
    const last = [...messages].reverse().find((m) => m.role !== "assistant");
    if (!last?.content) throw new Error("Soru bulunamadı");
    const result = await askAssistant(last.content.slice(0, 2000), {});
    const sources = result.citations.map(
      (c) =>
        `- ${c.marker} ${c.reference}${c.verification !== "official" ? " (doğrulanmadı)" : ""}`,
    );
    const content = sources.length
      ? `${result.answer}\n\n**Kaynaklar**\n${sources.join("\n")}`
      : result.answer;
    return { content, output: content };
  },
};

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export async function invokeFunction<T = any>(
  name: string,
  options?: { body?: Record<string, unknown> },
): Promise<Result<T>> {
  const handler = handlers[name];
  if (!handler) return { data: null, error: new Error(`Bilinmeyen işlev: ${name}`) };
  try {
    const data = (await handler(options?.body ?? {})) as T;
    return { data, error: null };
  } catch (e) {
    return { data: null, error: e instanceof Error ? e : new Error("Bilinmeyen hata") };
  }
}
