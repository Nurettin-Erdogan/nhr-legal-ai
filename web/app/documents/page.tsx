"use client";

import Link from "next/link";
import { ChangeEvent, FormEvent, useCallback, useEffect, useState } from "react";
import AppSidebar, { Icon } from "@/app/ui/app-sidebar";
import { API_URL } from "@/lib/api";

type Project = { id: string; name: string };
type LegalDocument = {
  id: string;
  project_id: string | null;
  file_name: string;
  mime_type: string | null;
  file_size: number | null;
  status: "uploaded" | "processing" | "ready" | "failed";
  processing_error: string | null;
  chunk_count: number;
  created_at: string;
  processed_at: string | null;
};

function formatBytes(value: number | null) {
  if (value === null) return "—";
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

export default function DocumentsPage() {
  const [documents, setDocuments] = useState<LegalDocument[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [authenticated, setAuthenticated] = useState<boolean | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [projectId, setProjectId] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  const loadWorkspace = useCallback(async () => {
    setError("");
    try {
      const [documentsResponse, projectsResponse] = await Promise.all([
        fetch(`${API_URL}/api/documents`, { credentials: "include" }),
        fetch(`${API_URL}/api/projects`, { credentials: "include" }),
      ]);
      if (documentsResponse.status === 401 || projectsResponse.status === 401) {
        setAuthenticated(false);
        return;
      }
      if (!documentsResponse.ok || !projectsResponse.ok) {
        throw new Error("Belge çalışma alanı alınamadı");
      }
      setDocuments(await documentsResponse.json());
      setProjects(await projectsResponse.json());
      setAuthenticated(true);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Belgeler alınamadı");
    }
  }, []);

  useEffect(() => { loadWorkspace(); }, [loadWorkspace]);

  function chooseFile(event: ChangeEvent<HTMLInputElement>) {
    setFile(event.target.files?.[0] ?? null);
    setError("");
    setMessage("");
  }

  async function upload(event: FormEvent) {
    event.preventDefault();
    if (!file) return;
    setLoading(true);
    setError("");
    setMessage("");
    try {
      const form = new FormData();
      form.append("file", file);
      if (projectId) form.append("project_id", projectId);
      const response = await fetch(`${API_URL}/api/documents`, {
        method: "POST",
        credentials: "include",
        body: form,
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail ?? "Belge yüklenemedi");
      setDocuments((current) => [payload, ...current]);
      setFile(null);
      setMessage(`${payload.file_name} işlendi ve ${payload.chunk_count} parçaya ayrıldı.`);
      const input = document.getElementById("document-file") as HTMLInputElement | null;
      if (input) input.value = "";
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Belge yüklenemedi");
    } finally {
      setLoading(false);
    }
  }

  const projectNames = new Map(projects.map((project) => [project.id, project.name]));

  return (
    <main className="app-shell">
      <AppSidebar active="documents" />
      <section className="workspace">
        <header className="topbar">
          <div><span className="eyebrow">KULLANICI ÇALIŞMA ALANI</span><h1>Belgeler</h1></div>
          <span className="corpus-pill"><span>{documents.length}</span> özel belge</span>
        </header>

        <div className="documents-content">
          {authenticated === false ? (
            <section className="projects-empty">
              <div className="assistant-symbol"><Icon name="file"/></div>
              <h2>Belgelerinizi görmek için oturum açın.</h2>
              <p>Yüklenen dosyalar yalnız sizin ve yetkili proje üyelerinin çalışma alanında tutulur.</p>
              <Link href="/auth">Giriş yap veya hesap oluştur</Link>
            </section>
          ) : authenticated ? (
            <>
              <form className="document-upload" onSubmit={upload}>
                <div>
                  <span className="section-kicker">YENİ BELGE</span>
                  <h2>Dosyayı analiz için yükleyin</h2>
                  <p>PDF, DOCX veya UTF-8 TXT · En fazla 10 MB. Taranmış PDF’ler için OCR sonraki aşamada eklenecek.</p>
                </div>
                <div className="upload-controls">
                  <label className="file-picker" htmlFor="document-file">
                    <Icon name="file"/>
                    <span>{file ? file.name : "Dosya seçin"}</span>
                    <input id="document-file" type="file" accept=".pdf,.docx,.txt" onChange={chooseFile}/>
                  </label>
                  <select aria-label="Proje" value={projectId} onChange={(event) => setProjectId(event.target.value)}>
                    <option value="">Projesiz özel belge</option>
                    {projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}
                  </select>
                  <button className="primary-action" disabled={!file || loading}>{loading ? "İşleniyor…" : "Yükle ve işle"}</button>
                </div>
              </form>
              {error && <div className="error-banner">{error}</div>}
              {message && <div className="success-banner">{message}</div>}

              <div className="documents-heading"><h2>Belge arşivi</h2><span>Her kayıt RLS ile kullanıcı ve proje yetkisine göre filtrelenir.</span></div>
              {documents.length === 0 ? (
                <section className="empty-state"><Icon name="file"/><h4>Henüz belge yüklenmedi</h4><p>İlk dosyanızı seçip analiz hattını başlatabilirsiniz.</p></section>
              ) : (
                <section className="document-list">
                  {documents.map((item) => (
                    <article key={item.id} className="document-row">
                      <div className="document-file-icon"><Icon name="file"/></div>
                      <div className="document-row-main">
                        <h3>{item.file_name}</h3>
                        <p>{item.project_id ? projectNames.get(item.project_id) ?? "Yetkili proje" : "Projesiz özel belge"}</p>
                      </div>
                      <div className="document-row-meta"><span>{formatBytes(item.file_size)}</span><span>{item.chunk_count} parça</span><span>{new Date(item.created_at).toLocaleDateString("tr-TR")}</span></div>
                      <strong className={`document-status ${item.status}`}>{item.status === "ready" ? "Hazır" : item.status}</strong>
                    </article>
                  ))}
                </section>
              )}
            </>
          ) : null}
        </div>
      </section>
    </main>
  );
}
