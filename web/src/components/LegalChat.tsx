import { useCallback, useEffect, useRef, useState } from "react";
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
import { CollapsibleAnswer } from "@/components/CollapsibleAnswer";
import remarkGfm from "remark-gfm";
import { cn } from "@/lib/utils";
import { Link, useSearchParam } from "@/lib/router-compat";
import { useAuth } from "@/components/AuthProvider";
import { ResearchSources } from "@/components/ResearchSources";
import { SearchSummary } from "@/components/SearchSummary";
import { shouldAutoResearch, type SearchSummaryData } from "@/lib/search-summary";
import {
  askAssistant,
  deleteConversation,
  getConversationDetail,
  listConversations,
  STAGE_LABELS,
  type AnswerResult,
  type ChatMessage,
  type ConversationSummary,
  type ConversationScope,
} from "@/lib/ai-api";
import { CitationList, ConsultedSourceList, DocumentScopeNotice } from "@/components/ChatCitations";
import { parseConsultedSources } from "@/lib/consulted-sources";

interface LegalChatProps {
  title: string;
  examples: string[];
  intro: string;
  caseId?: string;
  projectId?: string;
  officeProjectId?: string;
  compact?: boolean;
  onAnswered?: () => void;
}

export function LegalChat(props: LegalChatProps) {
  const { user } = useAuth();
  // Hesap veya sabit kapsam değiştiğinde geçmiş/içerik bir sonraki ekrana taşınmaz.
  return (
    <ScopedLegalChat
      key={`${user?.id ?? "anonymous"}:${props.caseId ?? ""}:${props.projectId ?? ""}:${props.officeProjectId ?? ""}`}
      {...props}
    />
  );
}

function ScopedLegalChat({
  title,
  examples,
  intro,
  caseId,
  projectId,
  officeProjectId,
  compact = false,
  onAnswered,
}: LegalChatProps) {
  const { user } = useAuth();
  const ownerId = user?.id;
  const baseScope: ConversationScope = {
    caseId: caseId ?? null,
    projectId: projectId ?? null,
    officeProjectId: officeProjectId ?? null,
    selectedDocumentIds: [],
  };
  const [activeScope, setActiveScope] = useState<ConversationScope>(baseScope);
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  // Üst çubuktaki genel aramadan gelen metin soru kutusuna yazılır; kullanıcı düzenleyip kendisi gönderir.
  const urlQuestion = useSearchParam("q");
  useEffect(() => {
    if (urlQuestion.trim()) setInput(urlQuestion);
  }, [urlQuestion]);
  const [loading, setLoading] = useState(false);
  const [opening, setOpening] = useState(false);
  const openSequence = useRef(0);
  const [stage, setStage] = useState("");
  const [requestSummary, setRequestSummary] = useState<SearchSummaryData>();
  const [requestError, setRequestError] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);
  const alive = useRef(true);
  const listSequence = useRef(0);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  const refresh = useCallback(async () => {
    if (!ownerId) return;
    const sequence = ++listSequence.current;
    try {
      const rows = await listConversations({ caseId, projectId, officeProjectId });
      if (alive.current && sequence === listSequence.current) setConversations(rows);
    } catch {
      if (alive.current && sequence === listSequence.current)
        toast.error("Sohbet geçmişi yüklenemedi.");
    }
  }, [caseId, projectId, officeProjectId, ownerId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);
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
      const history = await getConversationDetail(id);
      if (!alive.current || sequence !== openSequence.current) return;
      if (
        (caseId && history.scope.caseId !== caseId) ||
        (projectId && history.scope.projectId !== projectId) ||
        (officeProjectId && history.scope.officeProjectId !== officeProjectId)
      ) {
        throw new Error("Bu sohbet farklı bir dosyaya ait.");
      }
      setActiveId(id);
      setActiveScope(history.scope);
      setMessages(history.messages);
    } catch (error) {
      if (alive.current && sequence === openSequence.current)
        toast.error(error instanceof Error ? error.message : "Sohbet açılamadı");
    } finally {
      if (alive.current && sequence === openSequence.current) setOpening(false);
    }
  };

  const newChat = () => {
    if (loading) return;
    ++openSequence.current;
    setOpening(false);
    setRequestSummary(undefined);
    setRequestError("");
    setActiveId(null);
    setActiveScope(baseScope);
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
    if (!alive.current) return;
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
    const asMessage = (result: AnswerResult): ChatMessage => ({
      id: result.message_id ?? undefined,
      role: "assistant",
      content: result.answer,
      citations: result.citations,
      consultedSources: parseConsultedSources(result.consulted_sources),
      grounded: result.grounded,
      unverifiedMarkers: result.unverified_markers,
      searchSummary: result.search_summary,
      documentScope: result.document_scope ?? undefined,
      interpretedQuestion:
        typeof result.interpreted_question === "string" ? result.interpreted_question : undefined,
      summary: Array.isArray(result.summary) ? result.summary : undefined,
    });
    // Özet beklenirken doğrulanmış cevap önizleme olarak gösterilir; kalıcı cevap gelince onun yerini alır.
    let previewShown = false;
    try {
      const result = await askAssistant(question, {
        conversationId: activeId,
        ...activeScope,
        onStage: (s) => {
          if (alive.current) setStage(STAGE_LABELS[s] ?? "");
        },
        onSearchSummary: (summary) => {
          if (alive.current) setRequestSummary(summary);
        },
        onPreview: (preview) => {
          if (!alive.current || previewShown) return;
          previewShown = true;
          setRequestSummary(undefined);
          setMessages((p) => [...p, asMessage(preview)]);
        },
      });
      if (!alive.current) return;
      setMessages((p) => [...(previewShown ? p.slice(0, -1) : p), asMessage(result)]);
      setRequestSummary(undefined);
      if (result.conversation_id) setActiveId(result.conversation_id);
      void refresh();
      onAnswered?.();
    } catch (e) {
      if (!alive.current) return;
      const error = e instanceof Error ? e.message : "Hata oluştu";
      setRequestError(error);
      toast.error(error);
    } finally {
      if (alive.current) {
        setLoading(false);
        setStage("");
      }
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
        {compact && (
          <div className="border-b border-border p-3 flex flex-wrap gap-2 items-center">
            <label className="text-xs flex-1 min-w-48">
              {officeProjectId ? "Bu projenin sohbetleri" : "Bu davanın sohbetleri"} (son 50)
              <select
                aria-label="Kayıtlı sohbeti aç"
                value={activeId ?? ""}
                disabled={loading || opening}
                onChange={(event) => {
                  if (event.target.value) void open(event.target.value);
                  else newChat();
                }}
                className="block w-full mt-1 rounded-md border border-border bg-background p-2 text-sm"
              >
                <option value="">Yeni sohbet</option>
                {conversations.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.title ?? "Sohbet"}
                  </option>
                ))}
              </select>
            </label>
            <Button variant="outline" size="sm" onClick={newChat} disabled={loading || opening}>
              <Plus className="h-4 w-4" />
              Yeni
            </Button>
            {activeId && (
              <Button
                variant="outline"
                size="sm"
                onClick={() => void remove(activeId)}
                disabled={loading || opening}
              >
                <Trash2 className="h-4 w-4" />
                Sohbeti sil
              </Button>
            )}
          </div>
        )}
        {(activeScope.caseId ||
          activeScope.officeProjectId ||
          activeScope.projectId ||
          activeScope.selectedDocumentIds?.length) && (
          <div
            className="border-b border-border px-4 py-2 text-xs text-muted-foreground"
            role="status"
          >
            {activeScope.officeProjectId
              ? "Proje kapsamlı sohbet"
              : activeScope.caseId
                ? "Dava kapsamlı sohbet"
                : activeScope.projectId
                  ? "Araştırma projesi sohbeti"
                  : "Belge seçimli sohbet"}
            {activeScope.selectedDocumentIds?.length
              ? ` · ${activeScope.selectedDocumentIds.length} seçili belge`
              : ""}
            {activeScope.caseId && (
              <Link className="ml-3 underline" to={`/dashboard/cases/${activeScope.caseId}`}>
                Davayı aç
              </Link>
            )}
            {activeScope.officeProjectId && (
              <Link
                className="ml-3 underline"
                to={`/dashboard/projects/${activeScope.officeProjectId}`}
              >
                Projeyi aç
              </Link>
            )}
          </div>
        )}
        <div ref={scrollRef} className="flex-1 overflow-y-auto p-6">
          {messages.length === 0 ? (
            <div className="flex flex-col items-center justify-center min-h-full text-center max-w-lg mx-auto">
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
                    {m.role === "assistant" && m.interpretedQuestion && (
                      <p
                        className="mb-2 text-xs text-muted-foreground"
                        data-testid="interpreted-question"
                      >
                        Önceki sorunuza göre şöyle anlaşıldı: “{m.interpretedQuestion}”
                      </p>
                    )}
                    {m.role === "assistant" && (m.summary?.length ?? 0) > 0 ? (
                      // Önce sorunun doğrudan cevabı, sonra koşullar; resmî madde metni açılır "Dayanak" bölümünde (2026-10-18:
                      // kullanıcı cevabın kanun metninin satır satır kopyası olmasından yakındı). Her cümle sunucuda kaynakla
                      // denetlendi; hiçbiri geçmezse özet gelmez ve cevap eskisi gibi madde metnidir.
                      <>
                        <div className="space-y-2 text-sm" data-testid="answer-summary">
                          <p className="font-medium leading-relaxed">{m.summary?.[0]}</p>
                          {(m.summary?.length ?? 0) > 1 && (
                            <ul className="list-disc space-y-1 pl-5">
                              {m.summary?.slice(1).map((item) => (
                                <li key={item}>{item}</li>
                              ))}
                            </ul>
                          )}
                          <p className="text-[11px] text-muted-foreground">
                            Bu açıklama aşağıdaki resmî metne dayanılarak yapay zekâ tarafından yazıldı ve
                            kaynakla denetlendi; koşul ve istisnaların tamamı için metni esas alın.
                          </p>
                        </div>
                        <details className="mt-3 rounded-lg border border-border bg-background/40 p-2" data-testid="answer-basis">
                          <summary className="cursor-pointer text-xs font-semibold text-primary">
                            Dayanak: madde metnini göster
                          </summary>
                          <div className="prose prose-sm dark:prose-invert mt-2 max-w-none [&>*:first-child]:mt-0 [&>*:last-child]:mb-0">
                            <ReactMarkdown remarkPlugins={[remarkGfm]}>{m.content}</ReactMarkdown>
                          </div>
                        </details>
                      </>
                    ) : (
                      <div className="prose prose-sm dark:prose-invert max-w-none [&>*:first-child]:mt-0 [&>*:last-child]:mb-0">
                        <CollapsibleAnswer length={m.role === "assistant" ? m.content.length : 0}>
                          <ReactMarkdown remarkPlugins={[remarkGfm]}>{m.content}</ReactMarkdown>
                        </CollapsibleAnswer>
                      </div>
                    )}
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
                    {m.role === "assistant" && m.consultedSources && (
                      <ConsultedSourceList sources={m.consultedSources} />
                    )}
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
