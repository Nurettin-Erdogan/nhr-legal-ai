import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { ScrollArea } from "@/components/ui/scroll-area";
import { toast } from "sonner";
import {
  Send,
  Loader2,
  Plus,
  MessageSquare,
  Trash2,
  Bot,
  User as UserIcon,
  Sparkles,
  ShieldAlert,
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { cn } from "@/lib/utils";
import { ResearchSources } from "@/components/ResearchSources";
import { SearchSummary } from "@/components/SearchSummary";
import { shouldAutoResearch, type SearchSummaryData } from "@/lib/search-summary";
import {
  askAssistant,
  deleteConversation,
  getConversation,
  listConversations,
  STAGE_LABELS,
  type ChatMessage,
  type ConversationSummary,
} from "@/lib/ai-api";
import { CitationList, DocumentScopeNotice } from "@/components/ChatCitations";

export function LegalChat({
  title,
  examples,
  intro,
  caseId,
  compact = false,
  onAnswered,
}: {
  title: string;
  examples: string[];
  intro: string;
  /** Büro davası: sorular o davaya bağlı belgelerde de aranır; cevap belge kapsamını gösterir. */
  caseId?: string;
  /** Sohbet listesi olmadan, bir sayfanın içine gömülü kullanım (dava sohbeti). */
  compact?: boolean;
  onAnswered?: () => void;
}) {
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [opening, setOpening] = useState(false);
  const openSequence = useRef(0);
  const [stage, setStage] = useState("");
  const [requestSummary, setRequestSummary] = useState<SearchSummaryData>();
  const [requestError, setRequestError] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);

  const refresh = () =>
    listConversations()
      .then(setConversations)
      .catch(() => setConversations([]));

  useEffect(() => {
    // Dava sohbeti tek oturumluktur: genel sohbet geçmişi bir davaya bağlı değildir, listelenmez.
    if (!compact) refresh();
  }, [compact]);
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, loading]);

  const open = async (id: string) => {
    if (loading) return;
    const sequence = ++openSequence.current;
    setOpening(true);
    setRequestSummary(undefined);
    setRequestError("");
    try {
      const history = await getConversation(id);
      if (sequence !== openSequence.current) return;
      setActiveId(id);
      setMessages(history);
    } catch {
      if (sequence === openSequence.current) toast.error("Sohbet açılamadı");
    } finally {
      if (sequence === openSequence.current) setOpening(false);
    }
  };

  const newChat = () => {
    if (loading) return;
    ++openSequence.current;
    setOpening(false);
    setRequestSummary(undefined);
    setRequestError("");
    setActiveId(null);
    setMessages([]);
    setInput("");
  };

  const remove = async (id: string) => {
    if (loading) return;
    try {
      await deleteConversation(id);
    } catch {
      toast.error("Silinemedi");
      return;
    }
    if (activeId === id) newChat();
    refresh();
  };

  const send = async (text?: string) => {
    const question = (text ?? input).trim();
    if (question.length < 5 || loading || opening) return;
    setMessages((p) => [...p, { role: "user", content: question }]);
    setInput("");
    setLoading(true);
    setRequestSummary(undefined);
    setRequestError("");
    setStage(STAGE_LABELS.searching);
    try {
      const result = await askAssistant(question, {
        conversationId: activeId,
        caseId: caseId ?? null,
        onStage: (s) => setStage(STAGE_LABELS[s] ?? ""),
        onSearchSummary: setRequestSummary,
      });
      setMessages((p) => [
        ...p,
        {
          id: result.message_id ?? undefined,
          role: "assistant",
          content: result.answer,
          citations: result.citations,
          grounded: result.grounded,
          unverifiedMarkers: result.unverified_markers,
          searchSummary: result.search_summary,
          documentScope: result.document_scope ?? undefined,
        },
      ]);
      setRequestSummary(undefined);
      if (result.conversation_id) setActiveId(result.conversation_id);
      if (!compact) refresh();
      onAnswered?.();
    } catch (e) {
      const error = e instanceof Error ? e.message : "Hata oluştu";
      setRequestError(error);
      toast.error(error);
    } finally {
      setLoading(false);
      setStage("");
    }
  };

  return (
    <div
      className={cn(
        "grid gap-4",
        compact ? "grid-cols-1 h-[600px]" : "lg:grid-cols-[280px_1fr] h-[calc(100vh-220px)]",
      )}
      aria-label={title}
    >
      {!compact && (
        <div className="rounded-2xl bg-card border border-border p-3 flex flex-col">
          <Button onClick={newChat} variant="elite" size="sm" className="mb-3">
            <Plus className="h-4 w-4" /> Yeni Sohbet
          </Button>
          <ScrollArea className="flex-1">
            <div className="space-y-1">
              {conversations.map((c) => (
                <div
                  key={c.id}
                  onClick={() => open(c.id)}
                  className={cn(
                    "group flex items-center gap-2 px-2 py-2 rounded-md cursor-pointer hover:bg-muted text-sm",
                    activeId === c.id && "bg-muted",
                  )}
                >
                  <MessageSquare className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                  <span className="truncate flex-1">{c.title ?? "Sohbet"}</span>
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      remove(c.id);
                    }}
                    className="opacity-0 group-hover:opacity-100 transition"
                    aria-label="Sohbeti sil"
                  >
                    <Trash2 className="h-3.5 w-3.5 text-destructive" />
                  </button>
                </div>
              ))}
              {conversations.length === 0 && (
                <p className="text-xs text-muted-foreground p-2">Henüz sohbet yok</p>
              )}
            </div>
          </ScrollArea>
        </div>
      )}

      <div className="rounded-2xl bg-card border border-border flex flex-col overflow-hidden">
        <div ref={scrollRef} className="flex-1 overflow-y-auto p-6">
          {messages.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full text-center max-w-lg mx-auto">
              <div className="h-16 w-16 rounded-2xl bg-gradient-gold flex items-center justify-center mb-4">
                <Sparkles className="h-8 w-8 text-primary" />
              </div>
              <h3 className="font-serif text-2xl font-semibold mb-2">
                Size nasıl yardımcı olabilirim?
              </h3>
              <p className="text-sm text-muted-foreground mb-6">{intro}</p>
              <div className="grid sm:grid-cols-2 gap-2 w-full">
                {examples.map((s) => (
                  <button
                    key={s}
                    onClick={() => send(s)}
                    className="text-left text-xs p-3 rounded-lg border border-border hover:border-gold hover:bg-muted/40 transition"
                  >
                    {s}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div className="space-y-6 max-w-3xl mx-auto">
              {messages.map((m, i) => (
                <div
                  key={m.id ?? i}
                  className={cn("flex gap-3", m.role === "user" && "flex-row-reverse")}
                >
                  <div
                    className={cn(
                      "h-8 w-8 rounded-full flex items-center justify-center shrink-0",
                      m.role === "user"
                        ? "bg-primary text-primary-foreground"
                        : "bg-gradient-gold text-primary",
                    )}
                  >
                    {m.role === "user" ? (
                      <UserIcon className="h-4 w-4" />
                    ) : (
                      <Bot className="h-4 w-4" />
                    )}
                  </div>
                  <div
                    className={cn(
                      "max-w-[85%] rounded-2xl px-4 py-3",
                      m.role === "user" ? "bg-primary text-primary-foreground" : "bg-muted/50",
                    )}
                  >
                    <div className="prose prose-sm dark:prose-invert max-w-none [&>*:first-child]:mt-0 [&>*:last-child]:mb-0">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>{m.content}</ReactMarkdown>
                    </div>
                    {m.role === "assistant" && m.grounded === false && (
                      <p className="mt-2 text-xs flex items-center gap-1 text-amber-700 dark:text-amber-400">
                        <ShieldAlert className="h-3.5 w-3.5" /> Bu cevap getirilen kaynaklarla
                        doğrulanamadı.
                      </p>
                    )}
                    {m.role === "assistant" && (m.unverifiedMarkers?.length ?? 0) > 0 && (
                      <p className="mt-1 text-xs text-amber-700 dark:text-amber-400">
                        Doğrulanamayan atıflar: {m.unverifiedMarkers?.join(", ")}
                      </p>
                    )}
                    {m.citations && <CitationList citations={m.citations} />}
                    {m.role === "assistant" && m.documentScope && (
                      <DocumentScopeNotice scope={m.documentScope} />
                    )}
                    {m.role === "assistant" && m.searchSummary && (
                      <SearchSummary
                        summary={m.searchSummary}
                        citedCount={
                          new Set((m.citations ?? []).map((c) => c.source_id ?? c.reference)).size
                        }
                      />
                    )}
                    {m.role === "user" && (
                      <ResearchSources
                        question={m.content}
                        autoLoad={shouldAutoResearch(
                          i,
                          messages.length,
                          loading,
                          messages[i + 1]?.searchSummary,
                        )}
                      />
                    )}
                  </div>
                </div>
              ))}
              {loading && (
                <div className="flex gap-3">
                  <div className="h-8 w-8 rounded-full bg-gradient-gold flex items-center justify-center">
                    <Bot className="h-4 w-4 text-primary" />
                  </div>
                  <div className="bg-muted/50 rounded-2xl px-4 py-3 flex items-center gap-2 text-sm text-muted-foreground">
                    <Loader2 className="h-4 w-4 animate-spin" /> {stage || "Yazıyor…"}
                  </div>
                </div>
              )}
              {requestSummary && <SearchSummary summary={requestSummary} />}
              {requestError && (
                <p role="alert" className="text-sm text-destructive">
                  {requestError}
                </p>
              )}
            </div>
          )}
        </div>

        <div className="border-t border-border p-4">
          <div className="max-w-3xl mx-auto flex gap-2">
            <Textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  send();
                }
              }}
              placeholder="Sorunuzu yazın… (Enter = gönder, Shift+Enter = yeni satır)"
              rows={2}
              className="resize-none"
              disabled={loading}
            />
            <Button
              onClick={() => send()}
              disabled={loading || input.trim().length < 5}
              variant="elite"
              size="lg"
            >
              {loading ? (
                <Loader2 className="h-5 w-5 animate-spin" />
              ) : (
                <Send className="h-5 w-5" />
              )}
            </Button>
          </div>
          <p className="text-[10px] text-muted-foreground text-center mt-2">
            Cevaplar yalnızca getirilen kaynaklara dayanır; hukuki danışmanlık yerine geçmez.
          </p>
        </div>
      </div>
    </div>
  );
}
