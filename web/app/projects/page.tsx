"use client";

import Link from "next/link";
import { FormEvent, useCallback, useEffect, useState } from "react";
import AppSidebar, { Icon } from "@/app/ui/app-sidebar";
import { API_URL } from "@/lib/api";

type Project = {
  id: string;
  name: string;
  description: string | null;
  matter_type: "case" | "enforcement" | "consultancy" | "research" | "other";
  status: string;
  reference_no: string | null;
  court_name: string | null;
  docket_no: string | null;
  opened_on: string | null;
  member_role: string;
  document_count: number;
  updated_at: string;
};

const matterLabels = {
  case: "Dava",
  enforcement: "İcra",
  consultancy: "Danışmanlık",
  research: "Araştırma",
  other: "Diğer",
};

export default function ProjectsPage() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [authenticated, setAuthenticated] = useState<boolean | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [name, setName] = useState("");
  const [matterType, setMatterType] = useState<Project["matter_type"]>("case");
  const [referenceNo, setReferenceNo] = useState("");
  const [courtName, setCourtName] = useState("");
  const [docketNo, setDocketNo] = useState("");

  const loadProjects = useCallback(async () => {
    try {
      const response = await fetch(`${API_URL}/api/projects`, { credentials: "include" });
      if (response.status === 401) {
        setAuthenticated(false);
        return;
      }
      if (!response.ok) throw new Error("Projeler alınamadı");
      setProjects(await response.json());
      setAuthenticated(true);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Projeler alınamadı");
    }
  }, []);

  useEffect(() => { loadProjects(); }, [loadProjects]);

  async function createProject(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    setError("");
    try {
      const response = await fetch(`${API_URL}/api/projects`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name,
          matter_type: matterType,
          reference_no: referenceNo || null,
          court_name: courtName || null,
          docket_no: docketNo || null,
        }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail ?? "Proje oluşturulamadı");
      setProjects((current) => [payload, ...current]);
      setName(""); setReferenceNo(""); setCourtName(""); setDocketNo("");
      setShowForm(false);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Proje oluşturulamadı");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="app-shell">
      <AppSidebar active="projects" />
      <section className="workspace">
        <header className="topbar">
          <div><span className="eyebrow">DAVA VE ÇALIŞMA DOSYALARI</span><h1>Projeler</h1></div>
          {authenticated && <button className="primary-action" onClick={() => setShowForm((value) => !value)}>+ Yeni proje</button>}
        </header>

        <div className="projects-content">
          {authenticated === false ? (
            <section className="projects-empty">
              <div className="assistant-symbol"><Icon name="folder"/></div>
              <h2>Projelerinizi görmek için oturum açın.</h2>
              <p>Dava dosyaları ve belgeler yalnızca yetkili kullanıcı hesabında görüntülenir.</p>
              <Link href="/auth">Giriş yap veya hesap oluştur</Link>
            </section>
          ) : (
            <>
              {showForm && (
                <form className="project-form" onSubmit={createProject}>
                  <div className="form-heading"><div><span className="section-kicker">YENİ ÇALIŞMA</span><h2>Proje oluştur</h2></div><button type="button" onClick={() => setShowForm(false)}>Kapat</button></div>
                  <div className="project-form-grid">
                    <label>Proje adı<input value={name} onChange={(event) => setName(event.target.value)} required minLength={2}/></label>
                    <label>Dosya türü<select value={matterType} onChange={(event) => setMatterType(event.target.value as Project["matter_type"])}>{Object.entries(matterLabels).map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label>
                    <label>Referans no<input value={referenceNo} onChange={(event) => setReferenceNo(event.target.value)}/></label>
                    <label>Mahkeme<input value={courtName} onChange={(event) => setCourtName(event.target.value)}/></label>
                    <label>Esas no<input value={docketNo} onChange={(event) => setDocketNo(event.target.value)}/></label>
                  </div>
                  {error && <div className="error-banner">{error}</div>}
                  <button className="auth-submit" disabled={loading}>{loading ? "Oluşturuluyor…" : "Projeyi oluştur"}</button>
                </form>
              )}

              {!showForm && error && <div className="error-banner">{error}</div>}
              {authenticated && projects.length === 0 && !showForm && (
                <section className="projects-empty"><div className="assistant-symbol"><Icon name="folder"/></div><h2>İlk projenizi oluşturun.</h2><p>Dava, icra, danışmanlık ve araştırma çalışmalarınızı tek yerde düzenleyin.</p><button onClick={() => setShowForm(true)}>Yeni proje oluştur</button></section>
              )}
              <section className="project-grid">
                {projects.map((project) => (
                  <article className="project-card" key={project.id}>
                    <div className="project-card-top"><span>{matterLabels[project.matter_type]}</span><small>{project.status}</small></div>
                    <h2>{project.name}</h2>
                    <p>{project.court_name || "Mahkeme bilgisi eklenmedi"}{project.docket_no ? ` · E. ${project.docket_no}` : ""}</p>
                    <div className="project-meta"><span>{project.document_count} belge</span><span>{project.member_role}</span><span>{project.reference_no || "Referans yok"}</span></div>
                  </article>
                ))}
              </section>
            </>
          )}
        </div>
      </section>
    </main>
  );
}
