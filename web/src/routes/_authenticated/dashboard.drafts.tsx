import { invokeFunction } from "@/lib/backend";
import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
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
import { useAuth } from "@/components/AuthProvider";
import { CaseDocPicker } from "@/components/CaseDocPicker";
import { toast } from "sonner";
import { Sparkles, Loader2, Download, FileText, Save, FileSignature } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { exportTextPdf } from "@/lib/pdf-export";
import { Document, Packer, Paragraph, TextRun, HeadingLevel } from "docx";
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
  const [docType, setDocType] = useState("dilekce");
  const [title, setTitle] = useState("");
  const [partiesText, setPartiesText] = useState("");
  const [subject, setSubject] = useState("");
  const [details, setDetails] = useState("");
  const [generating, setGenerating] = useState(false);
  const [saving, setSaving] = useState(false);
  const [content, setContent] = useState("");
  const [docIds, setDocIds] = useState<string[]>([]);

  const handleGenerate = async () => {
    if (!subject.trim()) {
      toast.error("Konu alanı zorunludur");
      return;
    }
    setGenerating(true);
    setContent("");
    try {
      const parties = partiesText.split("\n").filter(Boolean);
      const { data, error } = await invokeFunction("generate-legal-document", {
        body: { docType, title, parties, subject, details, docIds },
      });
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
    } catch (e: any) {
      toast.error(e?.message ?? "Belge üretilemedi");
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
        metadata: { subject, details },
      });
      if (error) throw error;
      toast.success("Belge kaydedildi");
    } catch (e: any) {
      toast.error(e?.message ?? "Kaydedilemedi");
    } finally {
      setSaving(false);
    }
  };

  const exportPDF = async () => {
    if (!content) return;
    try {
      await exportTextPdf(content, title || "belge");
    } catch (e: any) {
      toast.error(e?.message ?? "PDF oluşturulamadı");
    }
  };

  const exportDOCX = async () => {
    if (!content) return;
    const paras = content.split("\n").map((line) => {
      const isHeading = /^#{1,3}\s/.test(line);
      const text = line
        .replace(/^#+\s*/, "")
        .replace(/\*\*(.*?)\*\*/g, "$1")
        .replace(/[*_`>]/g, "");
      return new Paragraph({
        heading: isHeading ? HeadingLevel.HEADING_2 : undefined,
        children: [new TextRun({ text: text || " ", bold: isHeading })],
        spacing: { after: 120 },
      });
    });
    const doc = new Document({ sections: [{ children: paras }] });
    const blob = await Packer.toBlob(doc);
    saveAs(blob, `${(title || "belge").replace(/\s+/g, "-")}.docx`);
  };

  const exportTXT = () => {
    if (!content) return;
    const blob = new Blob([content], { type: "text/plain;charset=utf-8" });
    saveAs(blob, `${(title || "belge").replace(/\s+/g, "-")}.txt`);
  };

  return (
    <DashboardLayout
      title="Akıllı Belge Üretimi"
      subtitle="AI ile dilekçe, sözleşme ve ihtarname hazırlayın"
    >
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
              Konu <span className="text-destructive">*</span>
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
              Ek Detaylar{" "}
              <span className="text-muted-foreground text-xs">(tarihler, tutarlar, deliller)</span>
            </Label>
            <Textarea
              id="details"
              value={details}
              onChange={(e) => setDetails(e.target.value)}
              placeholder="İş sözleşmesi tarihi: 12.03.2019, fesih tarihi: 28.06.2024, tanıklar: ..."
              rows={4}
            />
          </div>

          <CaseDocPicker value={docIds} onChange={setDocIds} />

          <Button
            onClick={handleGenerate}
            disabled={generating}
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
          {content ? (
            <Tabs defaultValue="preview" className="w-full">
              <div className="flex items-center justify-between mb-4 flex-wrap gap-2">
                <TabsList>
                  <TabsTrigger value="preview">Önizleme</TabsTrigger>
                  <TabsTrigger value="markdown">Kaynak</TabsTrigger>
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
              <TabsContent value="preview">
                <div className="prose prose-sm dark:prose-invert max-w-none max-h-[70vh] overflow-y-auto p-4 rounded-lg bg-muted/30">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
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
