import { invokeFunction } from "@/lib/backend";
import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useState, useRef } from "react";
import { DashboardLayout } from "@/components/DashboardLayout";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Card } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { supabase } from "@/integrations/supabase/client";
import { useAuth } from "@/components/AuthContext";
import { CaseDocPicker } from "@/components/CaseDocPicker";
import { LegalDocumentEditor } from "@/components/LegalDocumentEditor";
import { DocumentJobPanel } from "@/components/DocumentJobPanel";
import { startDocumentJob } from "@/lib/document-jobs";
import {
  CONTRACT_FIELDS,
  PETITION_FIELDS,
  NOTICE_FIELDS,
  fieldsForDocument,
  type DraftFields,
} from "@/lib/draft-fields";
import { readDocumentContext } from "@/lib/document-workflow";
import { DEFAULT_DOCUMENT_LAYOUT, documentPageStyle } from "@/lib/document-layout";
import { buildDocumentDocx } from "@/lib/document-export";
import { DocumentLayoutControls } from "@/components/DocumentLayoutControls";
import { Link } from "@/lib/router-compat";
import { useSearchParam } from "@/lib/router-hooks";
import { db } from "@/lib/db";
import { toast } from "sonner";
import { Sparkles, Loader2, Download, FileText, Save, FileSignature } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { exportTextPdf } from "@/lib/pdf-export";
import { Packer } from "docx";
import { saveAs } from "file-saver";

const DOC_TYPES = [
  { value: "dilekce", label: "Dava Dilekçesi", icon: FileText },
  { value: "sozlesme", label: "Sözleşme", icon: FileSignature },
  { value: "ihtarname", label: "İhtarname", icon: FileText },
  { value: "diger", label: "Diğer Hukuki Belge", icon: FileText },
];

const EXAMPLES: Record<string, string> = {
  dilekce:
    "Kıdem ve ihbar tazminatı talepli işçi alacağı davası. Davalı: ABC İnşaat A.Ş. Müvekkil 5 yıl 3 ay çalıştı, son brüt ücret 32.000 TL, haksız fesih.",
  sozlesme:
    "Web yazılım geliştirme sözleşmesi. Hizmet bedeli: 250.000 TL + KDV, 4 ay teslim, 2 revizyon hakkı, fikri mülkiyet teslimde devir.",
  ihtarname:
    "Ödenmemiş 85.000 TL fatura alacağı için 7 gün içinde ödeme talebi, aksi halde icra takibi başlatılacağına ilişkin ihtar.",
  diger: "Kira artış oranına itiraz dilekçesi. TÜFE üzerinde artış talebine karşı.",
};

const Drafts = () => {
  const { user } = useAuth();
  const currentOwner = useRef(user?.id);
  currentOwner.current = user?.id;
  const contextKey = useSearchParam("context");
  const urlCaseId = useSearchParam("case");
  const [caseId, setCaseId] = useState<string>();
  const [officeProjectId, setOfficeProjectId] = useState<string>();
  const [contextError, setContextError] = useState("");
  const [contextLoading, setContextLoading] = useState(false);
  const [docType, setDocType] = useState("dilekce");
  const [title, setTitle] = useState("");
  const [partiesText, setPartiesText] = useState("");
  const [subject, setSubject] = useState("");
  const [details, setDetails] = useState("");
  const [draftFields, setDraftFields] = useState<DraftFields>({});
  const [generating, setGenerating] = useState(false);
  const [saving, setSaving] = useState(false);
  const [content, setContent] = useState("");
  const [docIds, setDocIds] = useState<string[]>([]);
  const [jobId, setJobId] = useState<string>();
  const [layout, setLayout] = useState(DEFAULT_DOCUMENT_LAYOUT);

  useEffect(() => {
    let active = true;
    setDocIds([]);
    setCaseId(undefined);
    setOfficeProjectId(undefined);
    setContextError("");
    setContextLoading(false);
    setContent("");
    setJobId(undefined);
    setLayout(DEFAULT_DOCUMENT_LAYOUT);
    setGenerating(false);
    setTitle("");
    setSubject("");
    setPartiesText("");
    setDetails("");
    setDraftFields({});
    if (!currentOwner.current) return;
    const context = contextKey ? readDocumentContext(currentOwner.current, contextKey) : null;
    if (contextKey && !context) {
      setContextError(
        "Belge seçiminin süresi dolmuş veya bu oturumda erişilemiyor. Belgeler ekranından yeniden seçin.",
      );
      return;
    }
    setDocIds(context?.ids ?? []);
    setOfficeProjectId(context?.officeProjectId);
    const selectedCase =
      context?.caseId ?? (context?.officeProjectId ? undefined : urlCaseId || undefined);
    if (!selectedCase) return;
    if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(selectedCase)) {
      setContextError("Dosya bağlantısı geçersiz.");
      return;
    }
    setCaseId(selectedCase);
    setContextLoading(true);
    void (async () => {
      try {
        const result = await db
          .from("cases")
          .select("id,title,case_no,esas_no,court,opponent,client_id")
          .eq("id", selectedCase)
          .maybeSingle();
        if (result.error || !result.data)
          throw new Error(result.error?.message ?? "Dosya bulunamadı veya erişim yetkiniz yok.");
        let clientName = "";
        if (result.data.client_id) {
          const client = await db
            .from("clients")
            .select("full_name")
            .eq("id", result.data.client_id)
            .maybeSingle();
          if (client.error) throw new Error(client.error.message);
          clientName = client.data?.full_name ?? "";
        }
        if (!active) return;
        setTitle(result.data.title);
        setSubject(result.data.title);
        setPartiesText(
          [
            clientName && `Müvekkil: ${clientName}`,
            result.data.opponent && `Karşı taraf: ${result.data.opponent}`,
          ]
            .filter(Boolean)
            .join("\n"),
        );
        setDetails(
          [
            result.data.case_no || result.data.esas_no
              ? `Dosya no: ${result.data.case_no || result.data.esas_no}`
              : "",
            result.data.court ? `Mahkeme / birim: ${result.data.court}` : "",
          ]
            .filter(Boolean)
            .join("\n"),
        );
      } catch (error) {
        if (active)
          setContextError(error instanceof Error ? error.message : "Dosya bilgileri yüklenemedi.");
      } finally {
        if (active) setContextLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, [user?.id, contextKey, urlCaseId]);

  const handleGenerate = async () => {
    const initiatedBy = user?.id;
    if (!initiatedBy) return;
    if (contextError || contextLoading || docIds.length > 2000) return;
    if (!subject.trim()) {
      toast.error("Konu alanı zorunludur");
      return;
    }
    setGenerating(true);
    setContent("");
    if (docIds.length) {
      try {
        const startedJob = await startDocumentJob({
          module: "draft",
          document_ids: docIds,
          case_id: caseId,
          project_id: officeProjectId,
          doc_type: docType,
          title: title || subject.slice(0, 100),
          subject,
          details,
          draft_fields: fieldsForDocument(docType, draftFields),
          parties: partiesText.split("\n").filter(Boolean),
          prompt: subject,
        });
        if (currentOwner.current !== initiatedBy) return;
        setJobId(startedJob);
        toast.success("Tam metin belge hazırlama işi kuyruğa alındı.");
      } catch (error) {
        toast.error(error instanceof Error ? error.message : "İş başlatılamadı.");
      } finally {
        setGenerating(false);
      }
      return;
    }
    try {
      const parties = partiesText.split("\n").filter(Boolean);
      const { data, error } = await invokeFunction("generate-legal-document", {
        body: {
          docType,
          title,
          parties,
          subject,
          details,
          docIds,
          draftFields: fieldsForDocument(docType, draftFields),
        },
      });
      if (currentOwner.current !== initiatedBy) return;
      if (error) throw error;
      if (data?.error) throw new Error(data.error);
      setContent(data?.content || "");
      if (!title && data?.content) {
        const firstLine = String(data.content)
          .split("\n")
          .find((l: string) => l.trim());
        if (firstLine) setTitle(firstLine.replace(/^#+\s*/, "").slice(0, 80));
      }
      toast.success("Belge hazır. İnceleyip kaydedebilirsiniz.");
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "Belge üretilemedi");
    } finally {
      setGenerating(false);
    }
  };

  const handleSave = async () => {
    if (!user || !content) return;
    setSaving(true);
    try {
      const { error } = await supabase.from("legal_documents").insert({
        user_id: user.id,
        doc_type: docType,
        title: title || subject.slice(0, 80),
        content,
        parties: partiesText.split("\n").filter(Boolean),
        metadata: {
          subject,
          details,
          draft_fields: fieldsForDocument(docType, draftFields),
          case_id: caseId ?? null,
          office_project_id: officeProjectId ?? null,
          document_ids: docIds,
          page_layout: layout,
        },
      });
      if (error) throw error;
      toast.success("Belge kaydedildi");
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "Kaydedilemedi");
    } finally {
      setSaving(false);
    }
  };

  const exportPDF = async () => {
    if (!content) return;
    try {
      await exportTextPdf(content, title || "belge", layout);
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "PDF oluşturulamadı");
    }
  };

  const exportDOCX = async () => {
    if (!content) return;
    try {
      const blob = await Packer.toBlob(buildDocumentDocx(content, layout));
      saveAs(blob, `${(title || "belge").replace(/[\\/:*?"<>|\s]+/g, "-")}.docx`);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Word belgesi oluşturulamadı.");
    }
  };

  const exportTXT = () => {
    if (!content) return;
    const blob = new Blob([content], { type: "text/plain;charset=utf-8" });
    saveAs(blob, `${(title || "belge").replace(/\s+/g, "-")}.txt`);
  };

  return (
    <DashboardLayout
      title="Belge Hazırla"
      subtitle="AI ile dilekçe, sözleşme ve ihtarname hazırlayın"
    >
      {(contextLoading || contextError || caseId || docIds.length > 0) && (
        <div className="mb-5 flex flex-wrap items-center gap-3 rounded-xl border border-border p-3 text-sm">
          {contextError ? (
            <p role="alert" className="text-destructive">
              {contextError}
            </p>
          ) : contextLoading ? (
            <p role="status">Dosya bilgileri yükleniyor…</p>
          ) : (
            <p>
              {caseId ? "Dosya bilgileri forma alındı." : "Belge seçiminiz alındı."} {docIds.length}{" "}
              belge seçili.
            </p>
          )}
          <Link
            to={caseId ? `/dashboard/cases/${caseId}?tab=evraklar` : "/dashboard/files"}
            className="ml-auto underline"
          >
            {caseId ? "Dosyaya dön" : "Belgelere dön"}
          </Link>
        </div>
      )}
      <div className="grid lg:grid-cols-2 gap-6">
        {/* Form */}
        <Card className="p-6 space-y-4">
          <div className="space-y-2">
            <Label>Belge Türü</Label>
            <Select
              value={docType}
              onValueChange={(v) => {
                setDocType(v);
                if (!subject) setSubject(EXAMPLES[v] ?? "");
              }}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {DOC_TYPES.map((t) => (
                  <SelectItem key={t.value} value={t.value}>
                    {t.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-2">
            <Label htmlFor="title">
              Başlık{" "}
              <span className="text-muted-foreground text-xs">
                (opsiyonel — boş bırakırsanız AI üretir)
              </span>
            </Label>
            <Input
              id="title"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="Örn: İşçi Alacakları Davası Dilekçesi"
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="parties">
              Taraflar <span className="text-muted-foreground text-xs">(her satıra bir taraf)</span>
            </Label>
            <Textarea
              id="parties"
              value={partiesText}
              onChange={(e) => setPartiesText(e.target.value)}
              placeholder="Davacı: Av. Mehmet Yılmaz vekili Ali Demir&#10;Davalı: ABC İnşaat A.Ş."
              rows={3}
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="subject">
              Konu <span className="text-destructive">*</span>{" "}
              <span className="text-muted-foreground text-xs">(kısaca, bir cümle)</span>
            </Label>
            <Textarea
              id="subject"
              value={subject}
              onChange={(e) => setSubject(e.target.value)}
              placeholder={EXAMPLES[docType]}
              rows={4}
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="details">
              Olaylar ve ek detaylar{" "}
              <span className="text-muted-foreground text-xs">(tarihler, tutarlar, deliller)</span>
            </Label>
            <p className="text-xs text-muted-foreground">
              Açıklamalar bölümü yalnız burada yazdıklarınızdan (ya da seçtiğiniz belgelerden)
              kurulur; hiçbir olay, tarih veya tutar eklenmez. Boş bırakırsanız bu bölüm doldurmanız
              için boş kalır.
            </p>
            <Textarea
              id="details"
              value={details}
              onChange={(e) => setDetails(e.target.value)}
              placeholder="İş sözleşmesi tarihi: 12.03.2019, fesih tarihi: 28.06.2024, tanıklar: ..."
              rows={4}
            />
          </div>

          {(docType === "dilekce" || docType === "sozlesme" || docType === "ihtarname") && (
            <fieldset className="space-y-3 rounded-lg border p-4">
              <legend className="px-2 font-medium">
                {docType === "sozlesme"
                  ? "Sözleşme koşulları"
                  : docType === "ihtarname"
                    ? "İhtarname bilgileri"
                    : "Dilekçe bilgileri"}
              </legend>
              <p className="text-xs text-muted-foreground">
                Yazdığınız bilgiler taslağa aktarılır; hukuken uygun oldukları otomatik kabul
                edilmez. Boş alanlar […] olarak bırakılır, koşul veya talep uydurulmaz.
              </p>
              {(docType === "sozlesme"
                ? CONTRACT_FIELDS
                : docType === "ihtarname"
                  ? NOTICE_FIELDS
                  : PETITION_FIELDS
              ).map(([key, label]) => (
                <div key={key} className="space-y-1">
                  <Label htmlFor={`draft-${key}`}>{label}</Label>
                  <Textarea
                    id={`draft-${key}`}
                    value={draftFields[key] ?? ""}
                    maxLength={
                      key === "evidence" || key === "requests" || key === "obligations"
                        ? 8000
                        : key === "authority" ||
                            key === "representative" ||
                            key === "effective_date"
                          ? 500
                          : 4000
                    }
                    onChange={(event) =>
                      setDraftFields((previous) => ({ ...previous, [key]: event.target.value }))
                    }
                    rows={2}
                  />
                </div>
              ))}
            </fieldset>
          )}

          <CaseDocPicker
            value={docIds}
            onChange={setDocIds}
            max={2000}
            caseId={caseId}
            officeProjectId={officeProjectId}
          />

          <Button
            onClick={handleGenerate}
            disabled={generating || contextLoading || !!contextError || docIds.length > 2000}
            variant="elite"
            size="lg"
            className="w-full"
          >
            {generating ? (
              <Loader2 className="h-5 w-5 animate-spin" />
            ) : (
              <Sparkles className="h-5 w-5" />
            )}
            {generating ? "AI belgeyi hazırlıyor..." : "Belgeyi Oluştur"}
          </Button>
        </Card>

        {/* Result */}
        <Card className="p-6">
          <DocumentJobPanel
            jobId={jobId}
            module="draft"
            onCompleted={(job) => {
              if (job.output) setContent(job.output);
            }}
          />
          {content ? (
            <Tabs defaultValue="edit" className="w-full">
              <DocumentLayoutControls value={layout} onChange={setLayout} />
              <div className="flex items-center justify-between mb-4 flex-wrap gap-2">
                <TabsList>
                  <TabsTrigger value="edit">Düzenle</TabsTrigger>
                  <TabsTrigger value="preview">Önizleme</TabsTrigger>
                  <TabsTrigger value="markdown">Düz metin</TabsTrigger>
                </TabsList>
                <div className="flex gap-2 flex-wrap">
                  <Button size="sm" variant="outline" onClick={exportPDF}>
                    <Download className="h-4 w-4" />
                    PDF
                  </Button>
                  <Button size="sm" variant="outline" onClick={exportDOCX}>
                    <Download className="h-4 w-4" />
                    DOCX
                  </Button>
                  <Button size="sm" variant="outline" onClick={exportTXT}>
                    <Download className="h-4 w-4" />
                    TXT
                  </Button>
                  <Button size="sm" variant="elite" onClick={handleSave} disabled={saving}>
                    {saving ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <Save className="h-4 w-4" />
                    )}
                    Kaydet
                  </Button>
                </div>
              </div>
              <TabsContent value="edit">
                <LegalDocumentEditor value={content} onChange={setContent} layout={layout} />
              </TabsContent>
              <TabsContent value="preview">
                <div
                  style={documentPageStyle(layout)}
                  className="prose prose-sm dark:prose-invert max-h-[70vh] overflow-y-auto rounded-lg bg-muted/30"
                >
                  <ReactMarkdown remarkPlugins={[remarkGfm]} components={{ img: () => null }}>
                    {content}
                  </ReactMarkdown>
                </div>
              </TabsContent>
              <TabsContent value="markdown">
                <Textarea
                  value={content}
                  onChange={(e) => setContent(e.target.value)}
                  rows={28}
                  className="font-mono text-xs"
                />
              </TabsContent>
            </Tabs>
          ) : (
            <div className="flex flex-col items-center justify-center h-full text-center py-20 text-muted-foreground">
              <FileText className="h-16 w-16 mb-4 opacity-30" />
              <p className="font-medium">Belge önizlemesi burada görünecek</p>
              <p className="text-xs mt-2 max-w-xs">
                Sol taraftaki formu doldurup "Belgeyi Oluştur" butonuna basın.
              </p>
              <Button
                className="mt-4"
                variant="outline"
                onClick={() => {
                  setTitle((value) => value || "Yeni belge");
                  setContent("# Yeni belge\n\nBelge metnini buraya yazın.");
                }}
              >
                Boş belgeyle başla
              </Button>
            </div>
          )}
        </Card>
      </div>
    </DashboardLayout>
  );
};

export const Route = createFileRoute("/_authenticated/dashboard/drafts")({
  component: Drafts,
});
