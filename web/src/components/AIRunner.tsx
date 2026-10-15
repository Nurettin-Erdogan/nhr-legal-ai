import { invokeFunction } from "@/lib/backend";
import { askAssistant } from "@/lib/ai-api";
import { describeDocumentScope } from "@/lib/document-scope";
import { CitationList, type ChatCitation } from "@/components/ChatCitations";
import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Input } from "@/components/ui/input";

import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import {
  Sparkles,
  Loader2,
  History,
  Trash2,
  Copy,
  Download,
  ShieldAlert,
  Upload,
  Zap,
  Brain,
  Gavel,
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import { supabase } from "@/integrations/supabase/client";
import { useAuth } from "@/components/AuthProvider";
import { CaseDocPicker } from "@/components/CaseDocPicker";
import { DocumentJobPanel } from "@/components/DocumentJobPanel";
import { startDocumentJob, type DocumentJobInput } from "@/lib/document-jobs";
import { toast } from "sonner";
import { cn } from "@/lib/utils";

export type AIModule =
  | "research"
  | "case_law"
  | "document_analysis"
  | "draft"
  | "semantic_case_search"
  | "auto_summary"
  | "agent_research"
  | "risk_analysis"
  | "contract_draft";

interface AIOutput {
  id: string;
  title: string;
  prompt: string;
  output: string | null;
  created_at: string;
  module: string;
}

interface Props {
  module: AIModule;
  placeholder: string;
  examples?: string[];
  initialDocIds?: string[];
  initialPrompt?: string;
  caseId?: string;
  officeProjectId?: string;
  contextKey?: string;
}

// Kaynaklı hukuk araştırması yapan modüller yerel FastAPI RAG hattından (atıf doğrulamalı) geçer.
const RAG_MODULES: ReadonlySet<AIModule> = new Set([
  "research",
  "case_law",
  "semantic_case_search",
  "agent_research",
]);

const DRAFT_KEY = (m: string, userId: string) => `ai-draft:${userId}:${m}`;

export const AIRunner = ({
  module,
  placeholder,
  examples = [],
  initialDocIds = [],
  initialPrompt = "",
  caseId,
  officeProjectId,
  contextKey = "",
}: Props) => {
  const { session } = useAuth();
  const draftKey = session
    ? `${DRAFT_KEY(module, session.user.id)}${contextKey ? `:${contextKey}` : ""}`
    : null;
  const [loadedDraftKey, setLoadedDraftKey] = useState<string | null>(null);
  const [prompt, setPrompt] = useState("");
  const [analysisInstruction, setAnalysisInstruction] = useState("");
  const [title, setTitle] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<{
    id: string | null;
    output: string;
    /** UI body excludes the text-only export bibliography; identities stay interactive. */
    body?: string;
    citations?: ChatCitation[];
    title: string;
    model?: string;
    yargitay_context?: {
      source: string;
      count: number;
      decisions?: Array<{
        daire: string;
        esas_no: string;
        karar_no: string;
        karar_tarihi: string;
        excerpt?: string;
        confidence?: string;
      }>;
    } | null;
  } | null>(null);
  const [history, setHistory] = useState<AIOutput[]>([]);
  const [historyQuery, setHistoryQuery] = useState("");
  const [docIds, setDocIds] = useState<string[]>(initialDocIds);
  const maxDocuments = RAG_MODULES.has(module) ? 40 : 2000;
  const [jobId, setJobId] = useState<string>();
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Session-only, owner-scoped drafts; never load the legacy shared drafts.
  useEffect(() => {
    setPrompt(initialPrompt);
    setAnalysisInstruction("");
    setTitle("");
    try {
      const raw = draftKey ? sessionStorage.getItem(draftKey) : null;
      if (raw) {
        const d = JSON.parse(raw);
        if (d?.prompt) setPrompt(d.prompt);
        if (d?.title) setTitle(d.title);
        if (typeof d?.analysisInstruction === "string")
          setAnalysisInstruction(d.analysisInstruction);
      } else {
        setPrompt(initialPrompt);
        setTitle("");
      }
    } catch {
      /* ignore */
    }
    setResult(null);
    setLoadedDraftKey(draftKey);
  }, [draftKey, initialPrompt]);

  // Auto-save draft
  useEffect(() => {
    if (!draftKey || loadedDraftKey !== draftKey) return;
    const t = setTimeout(() => {
      try {
        if (prompt || title || analysisInstruction)
          sessionStorage.setItem(draftKey, JSON.stringify({ prompt, title, analysisInstruction }));
        else sessionStorage.removeItem(draftKey);
      } catch {
        /* ignore */
      }
    }, 400);
    return () => clearTimeout(t);
  }, [prompt, title, analysisInstruction, draftKey, loadedDraftKey]);

  const loadHistory = async () => {
    if (RAG_MODULES.has(module)) {
      setHistory([]);
      return;
    }
    const { data } = await supabase
      .from("ai_outputs")
      .select("id, title, prompt, output, created_at, module")
      .eq("module", module)
      .order("created_at", { ascending: false })
      .limit(20);
    setHistory((data ?? []) as AIOutput[]);
  };
  useEffect(() => {
    loadHistory(); /* eslint-disable-next-line */
  }, [module]);

  const run = async () => {
    if (docIds.length > maxDocuments) {
      toast.error(`Bu işlem için en fazla ${maxDocuments} belge seçebilirsiniz.`);
      return;
    }
    if (prompt.trim().length < 5) {
      toast.error("Lütfen daha detaylı bir soru/istek yazın");
      return;
    }
    setLoading(true);
    setResult(null);
    if (RAG_MODULES.has(module)) {
      try {
        const r = await askAssistant(prompt.trim(), {
          caseId,
          selectedDocumentIds: docIds,
          ...(officeProjectId ? { officeProjectId } : {}),
        });
        const refs = r.citations
          .map(
            (c) =>
              `- ${c.marker} ${c.reference}${c.verification === "user_document" ? " (kullanıcı belgesi)" : c.verification === "official" ? " (Resmî metin ✓)" : ""}${c.source_url ? ` — ${c.source_url}` : ""}`,
          )
          .join("\n");
        const warn = r.grounded ? "" : "\n\n> Bu cevap getirilen kaynaklarla doğrulanamadı.";
        const scope = r.document_scope
          ? `\n\n${describeDocumentScope(r.document_scope).lines.join("\n\n")}`
          : "";
        const body = `${r.answer}${warn}${scope}`;
        setResult({
          id: null,
          output: `${body}${refs ? `\n\n**Kaynaklar**\n${refs}` : ""}`,
          body,
          citations: r.citations,
          title: title || prompt.trim().slice(0, 60),
          model: "yerel-rag",
        });
        try {
          if (draftKey) sessionStorage.removeItem(draftKey);
        } catch {
          /* ignore */
        }
      } catch (e: unknown) {
        toast.error(e instanceof Error ? e.message : "Hata oluştu");
      } finally {
        setLoading(false);
      }
      return;
    }
    if (!session) {
      toast.error("Oturum gerekli");
      setLoading(false);
      return;
    }
    if (["document_analysis", "auto_summary", "risk_analysis"].includes(module)) {
      try {
        setJobId(
          await startDocumentJob({
            module: module as DocumentJobInput["module"],
            document_ids: docIds,
            text: docIds.length ? "" : prompt,
            prompt: docIds.length ? prompt : analysisInstruction.trim() || "Belge metnini incele.",
            title: title || "Belge çalışması",
            case_id: caseId,
            project_id: officeProjectId,
          }),
        );
        toast.success("Belge işi kuyruğa alındı.");
      } catch (error) {
        toast.error(error instanceof Error ? error.message : "İş başlatılamadı.");
      } finally {
        setLoading(false);
      }
      return;
    }
    try {
      const { data, error } = await invokeFunction("ai-legal", {
        body: { module, prompt, title: title || undefined, docIds, caseId },
      });
      if (error) throw error;
      if (data?.error) throw new Error(data.error);
      setResult({
        id: data.id,
        output: data.output,
        title: data.title,
        model: data.model,
        yargitay_context: data.yargitay_context,
      });
      toast.success("AI çıktısı hazır");
      try {
        if (draftKey) sessionStorage.removeItem(draftKey);
      } catch {
        /* ignore */
      }
      loadHistory();
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Hata oluştu";
      toast.error(msg);
    } finally {
      setLoading(false);
    }
  };

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    if (file.size > 5 * 1024 * 1024) {
      toast.error("Dosya çok büyük (max 5 MB)");
      return;
    }
    try {
      let text = "";
      if (file.name.toLowerCase().endsWith(".pdf")) {
        toast.info("PDF metni çıkarılıyor...");
        const pdfjs = await import("pdfjs-dist");
        const workerMod = await import("pdfjs-dist/build/pdf.worker.min.mjs?url");
        pdfjs.GlobalWorkerOptions.workerSrc = (workerMod as { default: string }).default;
        const arrayBuffer = await file.arrayBuffer();
        const pdf = await pdfjs.getDocument({ data: arrayBuffer }).promise;
        const parts: string[] = [];
        for (let i = 1; i <= pdf.numPages; i++) {
          const page = await pdf.getPage(i);
          const content = await page.getTextContent();
          parts.push(
            content.items.map((it) => ("str" in it ? (it as { str: string }).str : "")).join(" "),
          );
        }
        text = parts.join("\n\n");
      } else if (file.name.toLowerCase().endsWith(".docx")) {
        toast.info("DOCX metni çıkarılıyor...");
        const mammoth = await import("mammoth/mammoth.browser.js");
        const arrayBuffer = await file.arrayBuffer();
        const out = await mammoth.extractRawText({ arrayBuffer });
        text = out.value;
      } else if (file.type.startsWith("text/") || /\.(txt|md)$/i.test(file.name)) {
        text = await file.text();
      } else {
        toast.error("Desteklenmeyen format (PDF, DOCX, TXT)");
        return;
      }
      if (!text.trim()) {
        toast.error("Dosyadan metin çıkarılamadı");
        return;
      }
      if (text.length > 2_000_000)
        throw new Error(
          "Bu metin bir kuyruk işinin 2 milyon karakter sınırını aşıyor. Belgeyi arşive yükleyip oradan seçin.",
        );
      const truncated = text;
      setPrompt((p) =>
        p ? `${p}\n\n--- ${file.name} ---\n${truncated}` : `--- ${file.name} ---\n${truncated}`,
      );
      if (!title) setTitle(file.name.replace(/\.[^.]+$/, ""));
      toast.success(`${file.name} eklendi (${truncated.length.toLocaleString("tr-TR")} karakter)`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Dosya işlenemedi");
    } finally {
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  const openHistory = (h: AIOutput) => {
    setPrompt(h.prompt);
    setTitle(h.title);
    setResult({ id: h.id, output: h.output ?? "", title: h.title });
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const removeHistory = async (id: string) => {
    const { error } = await supabase.from("ai_outputs").delete().eq("id", id);
    if (error) toast.error(error.message);
    else {
      toast.success("Silindi");
      loadHistory();
      if (result?.id === id) setResult(null);
    }
  };

  const copyOutput = async () => {
    if (!result?.output) return;
    await navigator.clipboard.writeText(result.output);
    toast.success("Panoya kopyalandı");
  };

  const downloadOutput = () => {
    if (!result?.output) return;
    const blob = new Blob([`# ${result.title}\n\n${result.output}`], { type: "text/markdown" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${result.title.replace(/[^\w\s-]/g, "").slice(0, 60)}.md`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="space-y-6">
      {/* Hero input */}
      <div className="rounded-2xl bg-gradient-hero text-primary-foreground p-6 lg:p-8 relative overflow-hidden shadow-elegant">
        <div className="absolute -top-24 -right-24 h-72 w-72 rounded-full bg-gold/20 blur-3xl" />
        <div className="relative">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full border border-gold/30 bg-gold/10 text-gold text-xs font-medium uppercase tracking-wider mb-4">
            <Sparkles className="h-3.5 w-3.5" /> AI Powered
          </div>

          <div className="bg-primary-foreground/5 backdrop-blur border border-primary-foreground/15 rounded-2xl p-4">
            <div className="grid gap-3">
              <Input
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="Başlık (opsiyonel)"
                className="bg-transparent border-primary-foreground/20 text-primary-foreground placeholder:text-primary-foreground/50"
              />
              <Textarea
                rows={5}
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                onKeyDown={(e) => {
                  if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
                    e.preventDefault();
                    if (!loading && prompt.trim().length >= 5) run();
                  }
                }}
                placeholder={placeholder}
                className="bg-transparent border-primary-foreground/20 text-primary-foreground placeholder:text-primary-foreground/50 resize-y"
              />
              <div className="rounded-xl bg-background/90 text-foreground">
                <CaseDocPicker
                  value={docIds}
                  onChange={(ids) => {
                    setDocIds(ids);
                    if (ids.length && !prompt.trim())
                      setPrompt(
                        module === "risk_analysis"
                          ? "Seçili belgeleri süre, ispat ve usul açısından kaynaklara göre incele."
                          : "Seçili belgeleri ayrı başlıklar altında özetle.",
                      );
                  }}
                  max={maxDocuments}
                  caseId={caseId}
                  officeProjectId={officeProjectId}
                />
              </div>
              {RAG_MODULES.has(module) && docIds.length > 0 && (
                <p className="text-xs">
                  Arama yalnız seçtiğiniz {docIds.length} belge içinde yapılır; soru hukuki
                  değerlendirme istiyorsa mevzuat ve içtihat da aranır. İlgili metin parçaları
                  kullanılır; bu işlem belgelerin tamamının satır satır incelenmesi değildir.
                </p>
              )}
              {module === "document_analysis" && (
                <div className="space-y-2 text-xs">
                  {!docIds.length && (
                    <label className="block space-y-1">
                      <span>İnceleme talimatı (yukarıdaki belge metninden ayrı)</span>
                      <Textarea
                        value={analysisInstruction}
                        onChange={(e) => setAnalysisInstruction(e.target.value)}
                        maxLength={2000}
                        rows={2}
                        placeholder="Örn. Metindeki ödeme tutarlarını ve vadeleri incele."
                        className="bg-transparent border-primary-foreground/20 text-primary-foreground placeholder:text-primary-foreground/50"
                      />
                    </label>
                  )}
                  <p>
                    İnceleme, talimatınıza göre bölüm bölüm doğrulanan olguları çıkarır; belgeler
                    arası kapsamlı çelişki analizi veya hukuki görüş yerine geçmez.
                  </p>
                </div>
              )}
              <div className="flex flex-wrap items-center gap-2">
                <Button
                  variant="elite"
                  size="sm"
                  onClick={run}
                  disabled={loading || prompt.trim().length < 5 || docIds.length > maxDocuments}
                >
                  {loading ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <Sparkles className="h-4 w-4" />
                  )}
                  {loading ? "AI çalışıyor..." : "Çalıştır"}
                </Button>

                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".pdf,.docx,.txt,.md"
                  onChange={handleFileUpload}
                  className="hidden"
                />
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => fileInputRef.current?.click()}
                  className="border-primary-foreground/30 text-primary-foreground hover:bg-primary-foreground/10"
                  title="PDF / DOCX / TXT yükle"
                >
                  <Upload className="h-4 w-4" /> Belge Yükle
                </Button>

                <span className="text-xs">Model sunucudaki sağlayıcı ayarından seçilir.</span>

                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => {
                    setPrompt("");
                    setAnalysisInstruction("");
                    setTitle("");
                    setResult(null);
                    try {
                      if (draftKey) sessionStorage.removeItem(draftKey);
                    } catch {
                      /* ignore */
                    }
                  }}
                  className="border-primary-foreground/30 text-primary-foreground hover:bg-primary-foreground/10"
                >
                  Temizle
                </Button>
                <kbd className="hidden sm:inline-flex items-center gap-1 text-[10px] px-2 py-1 rounded border border-primary-foreground/20 text-primary-foreground/70 font-mono">
                  Ctrl + Enter
                </kbd>
                <span
                  className={cn(
                    "text-xs ml-auto font-mono",
                    prompt.length > 2000000 ? "text-destructive" : "text-primary-foreground/60",
                  )}
                >
                  {prompt.length.toLocaleString("tr-TR")} karakter
                </span>
              </div>
            </div>
          </div>

          {examples.length > 0 && (
            <div className="mt-5">
              <div className="text-[10px] uppercase tracking-[0.18em] text-primary-foreground/60 font-semibold mb-2">
                Hızlı başla — örnek istemler
              </div>
              <div className="flex flex-wrap gap-2">
                {examples.map((ex) => (
                  <button
                    key={ex}
                    onClick={() => setPrompt(ex)}
                    title="Tıkla ve örneği kullan"
                    className={cn(
                      "text-left max-w-md inline-flex items-start gap-2 px-3 py-1.5 rounded-full text-xs",
                      "bg-primary-foreground/5 text-primary-foreground/80 border border-primary-foreground/15 hover:bg-primary-foreground/10 hover:border-gold/40 transition",
                    )}
                  >
                    <Sparkles className="h-3 w-3 text-gold mt-0.5 shrink-0" />
                    <span className="truncate">{ex}</span>
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>

      {!RAG_MODULES.has(module) && (
        <DocumentJobPanel
          jobId={jobId}
          module={module}
          onCompleted={(job) => {
            if (job.output)
              setResult({
                id: job.output_id,
                output: job.output,
                title: title || "Belge çalışması",
              });
            void loadHistory();
          }}
        />
      )}
      {/* Result */}
      {result && (
        <div className="rounded-2xl bg-card border border-border shadow-card-elite p-6 lg:p-8">
          <div className="flex items-start justify-between gap-4 mb-5 flex-wrap">
            <div className="min-w-0">
              <div className="flex items-center gap-2 mb-2 flex-wrap">
                <span className="text-xs uppercase tracking-wider text-gold font-semibold">
                  AI Çıktısı
                </span>
                {result.model && (
                  <Badge variant="outline" className="text-[10px] gap-1">
                    {result.model.includes("pro") ? (
                      <Brain className="h-3 w-3" />
                    ) : (
                      <Zap className="h-3 w-3" />
                    )}
                    {result.model.split("/")[1]}
                  </Badge>
                )}
                {result.yargitay_context && (
                  <Badge
                    variant="outline"
                    className={cn(
                      "text-[10px] gap-1",
                      result.yargitay_context.source === "yargitay"
                        ? "border-emerald-500/40 text-emerald-700 bg-emerald-500/5"
                        : "border-amber-500/40 text-amber-700 bg-amber-500/5",
                    )}
                  >
                    <Gavel className="h-3 w-3" />
                    {result.yargitay_context.source === "yargitay"
                      ? `${result.yargitay_context.count} Yargıtay kararı (resmi)`
                      : `${result.yargitay_context.count} AI karar profili`}
                  </Badge>
                )}
              </div>
              <h3 className="font-serif text-2xl font-semibold">{result.title}</h3>
            </div>
            <div className="flex gap-2">
              <Button variant="outline" size="sm" onClick={copyOutput}>
                <Copy className="h-4 w-4" />
                Kopyala
              </Button>
              <Button variant="outline" size="sm" onClick={downloadOutput}>
                <Download className="h-4 w-4" />
                İndir
              </Button>
            </div>
          </div>
          {result.yargitay_context?.decisions && result.yargitay_context.decisions.length > 0 && (
            <div className="mb-6 rounded-xl border border-border bg-secondary/30 overflow-hidden">
              <div className="px-4 py-3 border-b border-border flex items-center gap-2 bg-secondary/50">
                <Gavel className="h-4 w-4 text-gold-deep" />
                <h4 className="font-serif text-sm font-semibold">
                  Emsal Kararlar ({result.yargitay_context.count})
                </h4>
                <Badge
                  variant="outline"
                  className={cn(
                    "text-[10px] ml-auto",
                    result.yargitay_context.source === "yargitay"
                      ? "border-emerald-500/40 text-emerald-700 bg-emerald-500/5"
                      : "border-amber-500/40 text-amber-700 bg-amber-500/5",
                  )}
                >
                  {result.yargitay_context.source === "yargitay"
                    ? "Resmi Kaynak"
                    : result.yargitay_context.source === "cache"
                      ? "Yerel Veritabanı"
                      : "AI Profili — Doğrulanmalı"}
                </Badge>
              </div>
              <ul className="divide-y divide-border">
                {result.yargitay_context.decisions.map((d, i) => (
                  <li key={`${d.daire}-${d.esas_no}-${d.karar_no}-${i}`} className="px-4 py-3">
                    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 mb-1">
                      <span className="text-xs font-mono text-muted-foreground">#{i + 1}</span>
                      <span className="font-semibold text-sm text-foreground">
                        {d.daire || "—"}
                      </span>
                      <Badge variant="outline" className="text-[10px] font-mono">
                        Esas: {d.esas_no || "—"}
                      </Badge>
                      <Badge variant="outline" className="text-[10px] font-mono">
                        Karar: {d.karar_no || "—"}
                      </Badge>
                      {d.karar_tarihi && (
                        <span className="text-xs text-muted-foreground">{d.karar_tarihi}</span>
                      )}
                      {d.confidence === "ai_generated" && (
                        <Badge
                          variant="outline"
                          className="text-[10px] border-amber-500/40 text-amber-700 bg-amber-500/5"
                        >
                          AI
                        </Badge>
                      )}
                    </div>
                    {d.excerpt && (
                      <p className="text-xs text-foreground/75 leading-relaxed mt-1">{d.excerpt}</p>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )}
          <article className="prose prose-sm max-w-none dark:prose-invert prose-headings:font-serif prose-h2:text-xl prose-h2:mt-6 prose-h2:mb-2 prose-h3:text-base prose-strong:text-foreground prose-li:my-1 prose-table:text-xs text-foreground/85">
            <ReactMarkdown components={{ img: () => null }}>
              {result.body ?? result.output}
            </ReactMarkdown>
          </article>
          {result.citations && <CitationList citations={result.citations} />}

          <div className="mt-6 rounded-xl border border-gold/30 bg-gold/5 p-4 flex items-start gap-3">
            <ShieldAlert className="h-4 w-4 text-gold-deep shrink-0 mt-0.5" />
            <div className="text-xs text-foreground/75">
              <strong>Önemli:</strong> Bu çıktı hukuki danışmanlık yerine geçmez. Nihai
              değerlendirme avukat tarafından yapılmalıdır.
            </div>
          </div>
        </div>
      )}

      {/* History */}
      <div className="rounded-2xl bg-card border border-border shadow-card-elite overflow-hidden">
        <div className="p-5 border-b border-border flex items-center justify-between gap-3 flex-wrap">
          <h4 className="font-serif text-lg font-semibold flex items-center gap-2">
            <History className="h-4 w-4" /> Geçmiş
          </h4>
          <div className="flex items-center gap-2 ml-auto">
            {history.length > 0 && (
              <Input
                value={historyQuery}
                onChange={(e) => setHistoryQuery(e.target.value)}
                placeholder="Geçmişte ara..."
                className="h-8 text-xs w-44"
              />
            )}
            <span className="text-xs text-muted-foreground whitespace-nowrap">
              {history.length} kayıt
            </span>
          </div>
        </div>
        {history.length === 0 ? (
          <div className="p-10 text-center text-sm text-muted-foreground">
            Henüz çıktı yok — yukarıdan ilk sorunu çalıştır.
          </div>
        ) : (
          (() => {
            const q = historyQuery.trim().toLowerCase();
            const filtered = q
              ? history.filter(
                  (h) => h.title.toLowerCase().includes(q) || h.prompt.toLowerCase().includes(q),
                )
              : history;
            if (filtered.length === 0) {
              return (
                <div className="p-10 text-center text-sm text-muted-foreground">
                  "{historyQuery}" için sonuç bulunamadı
                </div>
              );
            }
            return (
              <ul className="divide-y divide-border">
                {filtered.map((h) => (
                  <li
                    key={h.id}
                    className="px-5 py-3 flex items-center gap-3 hover:bg-secondary/30 transition"
                  >
                    <div
                      className="flex-1 min-w-0 cursor-pointer"
                      onClick={() => openHistory(h)}
                      title="Aç"
                    >
                      <div className="text-sm font-medium truncate">{h.title}</div>
                      <div className="text-xs text-muted-foreground truncate">{h.prompt}</div>
                      <div className="text-[10px] text-muted-foreground mt-0.5">
                        {new Date(h.created_at).toLocaleString("tr-TR")}
                      </div>
                    </div>
                    <AlertDialog>
                      <AlertDialogTrigger asChild>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="text-destructive shrink-0"
                          title="Sil"
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      </AlertDialogTrigger>
                      <AlertDialogContent>
                        <AlertDialogHeader>
                          <AlertDialogTitle>Bu çıktıyı sil?</AlertDialogTitle>
                          <AlertDialogDescription>Bu işlem geri alınamaz.</AlertDialogDescription>
                        </AlertDialogHeader>
                        <AlertDialogFooter>
                          <AlertDialogCancel>İptal</AlertDialogCancel>
                          <AlertDialogAction onClick={() => removeHistory(h.id)}>
                            Sil
                          </AlertDialogAction>
                        </AlertDialogFooter>
                      </AlertDialogContent>
                    </AlertDialog>
                  </li>
                ))}
              </ul>
            );
          })()
        )}
      </div>
    </div>
  );
};
