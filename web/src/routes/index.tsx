import { createFileRoute } from "@tanstack/react-router";
import { citationSuffix } from "@/lib/source-label";
import { useEffect, useRef, useState } from "react";
import { SiteHeader } from "@/components/SiteHeader";
import { SiteFooter } from "@/components/SiteFooter";
import { BasvuruDialog } from "@/components/BasvuruDialog";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Scale, Send, Loader2, Sparkles, FileText, Paperclip, X } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { extractFileText, MAX_UPLOAD_BYTES } from "@/lib/extract-text";
import { useAuth } from "@/components/AuthProvider";
import { AuthDialog } from "@/components/AuthDialog";
import { askAssistant } from "@/lib/ai-api";
import { CitationList, type ChatCitation } from "@/components/ChatCitations";

type Msg = { role: "user" | "assistant"; content: string; citations?: ChatCitation[] };
type Attachment = { name: string; text: string };

const ONERILER = [
  "İşten çıkarıldım, haklarım neler?",
  "Boşanma süreci nasıl işler?",
  "Kiracım tahliye olmuyor, ne yapmalıyım?",
  "Trafik kazası geçirdim, tazminat alabilir miyim?",
];

const DOC_LIMIT = 3000;

function HomePage() {
  const { user, loading: authLoading } = useAuth();
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [parsing, setParsing] = useState(false);
  const [attachment, setAttachment] = useState<Attachment | null>(null);
  const [basvuruOpen, setBasvuruOpen] = useState(false);
  const [authOpen, setAuthOpen] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, loading]);

  const handleFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    if (!user) {
      if (fileRef.current) fileRef.current.value = "";
      setAuthOpen(true);
      return;
    }
    const file = e.target.files?.[0];
    if (fileRef.current) fileRef.current.value = "";
    if (!file) return;
    if (file.size > MAX_UPLOAD_BYTES) {
      toast.error("Dosya çok büyük (en fazla 10 MB)");
      return;
    }
    setParsing(true);
    try {
      const text = await extractFileText(file);
      if (!text.trim()) {
        toast.error("Dosyadan metin çıkarılamadı (taranmış görüntü olabilir)");
        return;
      }
      setAttachment({ name: file.name, text: text.trim() });
      toast.success(`${file.name} eklendi — sorunuzu yazıp gönderin`);
    } catch (err) {
      if ((err as Error)?.message === "unsupported") {
        toast.error("Desteklenmeyen format (PDF, DOCX veya TXT yükleyin)");
      } else {
        console.error(err);
        toast.error("Dosya okunamadı");
      }
    } finally {
      setParsing(false);
    }
  };

  const send = async (text?: string) => {
    if (!user && !authLoading) {
      if (text) setInput(text);
      setAuthOpen(true);
      return;
    }
    if (!user) return;
    const typed = (text ?? input).trim();
    const doc = attachment;
    if ((!typed && !doc) || loading) return;

    const visible = doc
      ? `${typed || "Bu belgeyi inceleyip bana sade bir dille açıklar mısın?"}\n\n📎 ${doc.name}`
      : typed;
    const forAi = doc
      ? `${typed || "Bu belgeyi inceleyip bana sade bir dille açıkla."}\n\n--- Eklenen belge: ${doc.name} ---\n${doc.text.slice(0, DOC_LIMIT)}${doc.text.length > DOC_LIMIT ? "\n...(belge kısaltıldı)" : ""}`
      : typed;

    const history = [...messages, { role: "user" as const, content: visible }];
    setMessages(history);
    setInput("");
    setAttachment(null);
    setLoading(true);

    const payload = history
      .slice(-14)
      .map((m, i, arr) => (i === arr.length - 1 ? { ...m, content: forAi } : m));

    try {
      const question = (payload[payload.length - 1]?.content ?? "").slice(0, 1990);
      const result = await askAssistant(question, {});
      setMessages((p) => [
        ...p,
        { role: "assistant", content: result.answer, citations: result.citations },
      ]);
    } catch {
      toast.error("Şu an cevap alınamadı, lütfen tekrar deneyin");
    } finally {
      setLoading(false);
    }
  };

  const ozet = messages
    .map(
      (m) =>
        `${m.role === "user" ? "Vatandaş" : "JurisAI"}: ${m.content}${
          m.citations?.length
            ? `\n\nKaynaklar\n${m.citations.map((c) => `- ${c.marker} ${c.reference}${citationSuffix(c.verification, c.source_url)}`).join("\n")}`
            : ""
        }`,
    )
    .join("\n\n");

  return (
    <div className="flex min-h-screen flex-col bg-background">
      <SiteHeader />

      <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col px-4 py-6">
        <div className="flex flex-1 flex-col overflow-hidden rounded-2xl border border-border bg-card shadow-card-elite">
          <div ref={scrollRef} className="flex-1 overflow-y-auto p-5 sm:p-8">
            {messages.length === 0 ? (
              <div className="mx-auto flex max-w-lg flex-col items-center py-8 text-center">
                <div className="mb-5 flex h-14 w-14 items-center justify-center rounded-2xl bg-secondary">
                  <Scale className="h-7 w-7 text-primary" />
                </div>
                <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">Hoş geldiniz!</h1>
                <p className="mt-3 text-sm leading-relaxed text-muted-foreground">
                  Hukuki konularda size yardımcı olabilirim. Sorununuzu anlatın, birlikte çözüm
                  yollarını keşfedelim.
                </p>

                <div className="mt-7 grid w-full gap-2">
                  {ONERILER.map((s) => (
                    <button
                      key={s}
                      onClick={() => send(s)}
                      className="flex items-center gap-3 rounded-xl border border-border bg-background px-4 py-3 text-left text-sm transition-colors hover:border-primary/40 hover:bg-secondary disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      <Sparkles className="h-4 w-4 shrink-0 text-primary" />
                      {s}
                    </button>
                  ))}
                </div>

                {!user && !authLoading && (
                  <p className="mt-6 text-xs text-muted-foreground">
                    Soru sorduğunuzda ücretsiz kayıt ekranı açılır.
                  </p>
                )}

                <Button
                  variant="outline"
                  className="mt-6 w-full rounded-full border-primary/30 text-primary hover:bg-secondary"
                  onClick={() => setBasvuruOpen(true)}
                >
                  <FileText className="h-4 w-4" /> Doğrudan Başvuru Yap
                </Button>
              </div>
            ) : (
              <div className="space-y-5">
                {messages.map((m, i) => (
                  <div
                    key={i}
                    className={cn("flex", m.role === "user" ? "justify-end" : "justify-start")}
                  >
                    <div
                      className={cn(
                        "max-w-[88%] rounded-2xl px-4 py-3 text-sm",
                        m.role === "user"
                          ? "bg-primary text-primary-foreground"
                          : "bg-secondary text-foreground",
                      )}
                    >
                      <div className="prose prose-sm dark:prose-invert max-w-none [&>*:first-child]:mt-0 [&>*:last-child]:mb-0">
                        <ReactMarkdown remarkPlugins={[remarkGfm]}>{m.content}</ReactMarkdown>
                      </div>
                      {m.role === "assistant" && m.citations && (
                        <CitationList citations={m.citations} />
                      )}
                    </div>
                  </div>
                ))}
                {loading && messages[messages.length - 1]?.role === "user" && (
                  <div className="flex items-center gap-2 rounded-2xl bg-secondary px-4 py-3 text-sm text-muted-foreground w-fit">
                    <Loader2 className="h-4 w-4 animate-spin" /> Yazıyor...
                  </div>
                )}
              </div>
            )}
          </div>

          <div className="border-t border-border p-3 sm:p-4">
            <input
              ref={fileRef}
              type="file"
              accept=".pdf,.docx,.txt,.md,.csv,text/plain"
              className="hidden"
              onChange={handleFile}
            />
            {attachment && (
              <div className="mb-2 flex items-center gap-2 rounded-xl bg-secondary px-3 py-2 text-xs">
                <FileText className="h-4 w-4 shrink-0 text-primary" />
                <span className="truncate font-medium">{attachment.name}</span>
                <span className="shrink-0 text-muted-foreground">
                  {attachment.text.length.toLocaleString("tr-TR")} karakter
                </span>
                <button
                  className="ml-auto shrink-0 text-muted-foreground hover:text-foreground"
                  onClick={() => setAttachment(null)}
                  aria-label="Dosyayı kaldır"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>
            )}
            <div className="flex items-end gap-2">
              <Button
                size="icon"
                variant="outline"
                className="h-11 w-11 shrink-0 rounded-full"
                onClick={() => (user ? fileRef.current?.click() : setAuthOpen(true))}
                disabled={loading || parsing}
                aria-label="Dosya ekle"
                title="Dosya ekle (PDF, DOCX, TXT)"
              >
                {parsing ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Paperclip className="h-4 w-4" />
                )}
              </Button>

              <Textarea
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    send();
                  }
                }}
                rows={1}
                placeholder={
                  attachment
                    ? "Belgeyle ilgili sorunuz (boş bırakabilirsiniz)..."
                    : "Hukuki sorunuzu yazın..."
                }
                className="max-h-32 min-h-11 resize-none rounded-2xl"
                disabled={loading}
              />

              <Button
                size="icon"
                className="h-11 w-11 shrink-0 rounded-full"
                onClick={() => send()}
                disabled={loading || (!input.trim() && !attachment)}
                aria-label="Gönder"
              >
                {loading ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Send className="h-4 w-4" />
                )}
              </Button>
            </div>
            <p className="mt-2 text-center text-[11px] text-muted-foreground">
              Genel bilgilendirme amaçlıdır, hukuki tavsiye niteliği taşımaz. ·{" "}
              <button
                className="text-primary underline-offset-2 hover:underline"
                onClick={() => setBasvuruOpen(true)}
              >
                Başvuru formu
              </button>
            </p>
          </div>
        </div>
      </main>

      <SiteFooter />
      <AuthDialog open={authOpen} onOpenChange={setAuthOpen} defaultMode="signup" />
      <BasvuruDialog open={basvuruOpen} onOpenChange={setBasvuruOpen} sohbetOzeti={ozet} />
    </div>
  );
}

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "JurisAI — Ücretsiz Hukuki Yapay Zekâ Asistanı" },
      {
        name: "description",
        content:
          "İş, aile, kira ve tazminat konularında sorunuzu yazın; JurisAI haklarınızı ve atmanız gereken adımları sade bir dille anlatsın.",
      },
      { property: "og:title", content: "JurisAI — Ücretsiz Hukuki Yapay Zekâ Asistanı" },
      {
        property: "og:description",
        content: "Hukuki sorununuzu anlatın, haklarınızı ve izlemeniz gereken adımları öğrenin.",
      },
    ],
  }),
  component: HomePage,
});
