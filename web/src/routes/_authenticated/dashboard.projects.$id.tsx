import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { Link } from "@/lib/router-compat";
import { useParams } from "@/lib/router-hooks";
import { DashboardLayout } from "@/components/DashboardLayout";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Badge } from "@/components/ui/badge";
import { Loader2, Plus, ArrowLeft, StickyNote, Sparkles, Trash2 } from "lucide-react";
import { supabase } from "@/integrations/supabase/client";
import { useAuth } from "@/components/AuthContext";
import { toast } from "sonner";
import { LegalChat } from "@/components/LegalChat";
import { ProjectDocuments } from "@/components/ProjectDocuments";

interface Project {
  id: string;
  name: string;
  description: string | null;
  status: string;
  color: string | null;
  case_id: string | null;
  client_id: string | null;
  created_at: string;
}
interface Note {
  id: string;
  title: string | null;
  content: string;
  created_at: string;
}
interface AIOut {
  id: string;
  title: string;
  module: string;
  created_at: string;
  output: string | null;
}

function ProjectDetail() {
  const { id } = useParams<{ id: string }>();
  const { user } = useAuth();
  return <ProjectDetailWorkspace key={`${user?.id ?? "anonymous"}:${id}`} />;
}

function ProjectDetailWorkspace() {
  const { id } = useParams<{ id: string }>();
  const { session } = useAuth();
  const [project, setProject] = useState<Project | null>(null);
  const [notes, setNotes] = useState<Note[]>([]);
  const [aiOutputs, setAiOutputs] = useState<AIOut[]>([]);
  const [loading, setLoading] = useState(true);
  const [noteTitle, setNoteTitle] = useState("");
  const [noteContent, setNoteContent] = useState("");
  const [savingNote, setSavingNote] = useState(false);

  const load = async () => {
    if (!id) return;
    setLoading(true);
    const [{ data: p }, { data: n }, { data: a }] = await Promise.all([
      supabase.from("projects").select("*").eq("id", id).maybeSingle(),
      supabase
        .from("project_notes")
        .select("*")
        .eq("project_id", id)
        .order("created_at", { ascending: false }),
      supabase
        .from("ai_outputs")
        .select("id, title, module, created_at, output")
        .eq("project_id", id)
        .order("created_at", { ascending: false }),
    ]);
    setProject(p as Project | null);
    setNotes((n ?? []) as Note[]);
    setAiOutputs((a ?? []) as AIOut[]);
    setLoading(false);
  };
  useEffect(() => {
    load(); /* eslint-disable-next-line */
  }, [id]);

  const addNote = async () => {
    if (!session || !id) return;
    if (noteContent.trim().length < 2) return toast.error("Not içeriği gerekli");
    setSavingNote(true);
    const { error } = await supabase.from("project_notes").insert({
      owner_id: session.user.id,
      project_id: id,
      title: noteTitle.trim() || null,
      content: noteContent.trim(),
    });
    setSavingNote(false);
    if (error) return toast.error(error.message);
    toast.success("Not eklendi");
    setNoteTitle("");
    setNoteContent("");
    load();
  };

  const removeNote = async (nid: string) => {
    const { error } = await supabase.from("project_notes").delete().eq("id", nid);
    if (error) return toast.error(error.message);
    load();
  };

  if (loading) {
    return (
      <DashboardLayout title="Proje" subtitle="">
        <div className="flex items-center justify-center py-20">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      </DashboardLayout>
    );
  }
  if (!project) {
    return (
      <DashboardLayout title="Proje bulunamadı" subtitle="">
        <Link to="/dashboard/projects" className="text-gold inline-flex items-center gap-2">
          <ArrowLeft className="h-4 w-4" /> Projelere dön
        </Link>
      </DashboardLayout>
    );
  }

  return (
    <DashboardLayout
      title={project.name}
      subtitle={project.description || "Dava workspace"}
      actions={
        <Link to="/dashboard/projects">
          <Button variant="outline">
            <ArrowLeft className="h-4 w-4" /> Projeler
          </Button>
        </Link>
      }
    >
      <div className="rounded-2xl bg-card border border-border p-5 mb-6 flex items-center gap-3 flex-wrap">
        <div
          className="h-3 w-3 rounded-full"
          style={{ background: project.color || "hsl(var(--gold))" }}
        />
        <Badge variant="outline">{project.status}</Badge>
        <span className="text-sm text-muted-foreground">
          Oluşturulma: {new Date(project.created_at).toLocaleString("tr-TR")}
        </span>
      </div>

      <Tabs defaultValue="notes" className="space-y-4">
        <TabsList>
          <TabsTrigger value="notes">
            <StickyNote className="h-4 w-4 mr-1.5" /> Notlar ({notes.length})
          </TabsTrigger>
          <TabsTrigger value="ai">
            <Sparkles className="h-4 w-4 mr-1.5" /> AI Çıktıları ({aiOutputs.length})
          </TabsTrigger>
          <TabsTrigger value="chat">Sohbet</TabsTrigger>
          <TabsTrigger value="documents">Belgeler</TabsTrigger>
        </TabsList>

        <TabsContent value="documents">
          <ProjectDocuments projectId={id} />
        </TabsContent>
        <TabsContent value="chat">
          <LegalChat
            key={id}
            title="Proje sohbeti"
            officeProjectId={id}
            compact
            intro={
              project.case_id
                ? "Projeye doğrudan bağlanan belgeler, bağlı davanın evrakları ve hukuk kaynakları kullanılır. Sohbet bu projede saklanır."
                : "Belgeler sekmesinden bağladığınız belgeler ve hukuk kaynakları kullanılır. Belge yoksa dosyaya özgü bilgiler uydurulmaz."
            }
            examples={
              project.case_id
                ? [
                    "Bu dosyadaki belgelere göre taraflar kimlerdir?",
                    "Dosyanın safahatında en son ne yapılmış?",
                  ]
                : ["Kira artışına ilişkin mevzuatı araştır."]
            }
          />
        </TabsContent>

        <TabsContent value="notes" className="space-y-4">
          <div className="rounded-2xl bg-card border border-border p-5 space-y-3">
            <Label>Yeni Not</Label>
            <Input
              placeholder="Başlık (opsiyonel)"
              value={noteTitle}
              onChange={(e) => setNoteTitle(e.target.value)}
            />
            <Textarea
              rows={4}
              placeholder="Notunu yaz..."
              value={noteContent}
              onChange={(e) => setNoteContent(e.target.value)}
            />
            <Button variant="elite" onClick={addNote} disabled={savingNote}>
              {savingNote ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Plus className="h-4 w-4" />
              )}{" "}
              Not Ekle
            </Button>
          </div>

          {notes.length === 0 ? (
            <div className="rounded-2xl border border-border bg-card p-12 text-center text-muted-foreground text-sm">
              Henüz not yok
            </div>
          ) : (
            <div className="space-y-3">
              {notes.map((n) => (
                <div key={n.id} className="rounded-xl bg-card border border-border p-4">
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex-1 min-w-0">
                      {n.title && <div className="font-semibold mb-1">{n.title}</div>}
                      <p className="text-sm whitespace-pre-wrap text-foreground/85">{n.content}</p>
                      <div className="text-[10px] text-muted-foreground mt-2">
                        {new Date(n.created_at).toLocaleString("tr-TR")}
                      </div>
                    </div>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="text-destructive shrink-0"
                      onClick={() => removeNote(n.id)}
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </TabsContent>

        <TabsContent value="ai" className="space-y-3">
          {aiOutputs.length === 0 ? (
            <div className="rounded-2xl border border-border bg-card p-12 text-center text-muted-foreground text-sm">
              Bu projeye bağlı AI çıktısı yok. AI sayfalarında çalıştırırken projeye bağlama
              özelliği yakında.
            </div>
          ) : (
            aiOutputs.map((a) => (
              <div key={a.id} className="rounded-xl bg-card border border-border p-4">
                <div className="flex items-center gap-2 mb-1">
                  <Badge variant="outline" className="text-xs">
                    {a.module}
                  </Badge>
                  <span className="text-xs text-muted-foreground ml-auto">
                    {new Date(a.created_at).toLocaleString("tr-TR")}
                  </span>
                </div>
                <div className="font-semibold">{a.title}</div>
                <p className="text-sm text-muted-foreground line-clamp-3 mt-1">{a.output}</p>
              </div>
            ))
          )}
        </TabsContent>
      </Tabs>
    </DashboardLayout>
  );
}

export const Route = createFileRoute("/_authenticated/dashboard/projects/$id")({
  component: ProjectDetail,
});
