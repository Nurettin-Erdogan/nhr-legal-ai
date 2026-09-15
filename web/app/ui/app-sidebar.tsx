import Link from "next/link";

export type IconName = "search" | "spark" | "folder" | "file" | "user";

export function Icon({ name }: { name: IconName }) {
  const paths = {
    search: <><circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/></>,
    spark: <><path d="m12 3 1.3 4.1L17 9l-3.7 1.9L12 15l-1.3-4.1L7 9l3.7-1.9L12 3Z"/><path d="m19 14 .7 2.3L22 17.5l-2.3 1.2L19 21l-.7-2.3-2.3-1.2 2.3-1.2L19 14Z"/></>,
    folder: <><path d="M3 6.5h6l2 2h10v10H3z"/></>,
    file: <><path d="M6 3h8l4 4v14H6z"/><path d="M14 3v5h5M9 13h6M9 17h6"/></>,
    user: <><circle cx="12" cy="8" r="4"/><path d="M4.5 21a7.5 7.5 0 0 1 15 0"/></>,
  };
  return <svg viewBox="0 0 24 24" aria-hidden="true">{paths[name]}</svg>;
}

export function Brand() {
  return (
    <div className="brand">
      <div className="brand-mark">N</div>
      <div><strong>NHR Legal AI</strong><span>Hukuk araştırma asistanı</span></div>
    </div>
  );
}

export default function AppSidebar({ active }: { active: "research" | "assistant" | "projects" | "documents" | "auth" }) {
  return (
    <aside className="sidebar">
      <Brand />
      <nav>
        <p className="nav-label">ÇALIŞMA ALANI</p>
        <Link className={`nav-item ${active === "research" ? "active" : ""}`} href="/">
          <Icon name="search"/>Hukuk araştırması
        </Link>
        <Link className={`nav-item ${active === "assistant" ? "active" : ""}`} href="/assistant">
          <Icon name="spark"/>AI asistanı
        </Link>
        <Link className={`nav-item ${active === "projects" ? "active" : ""}`} href="/projects">
          <Icon name="folder"/>Projeler
        </Link>
        <Link className={`nav-item ${active === "documents" ? "active" : ""}`} href="/documents">
          <Icon name="file"/>Belgeler
        </Link>
      </nav>
      <div className="sidebar-bottom">
        <Link className={`nav-item ${active === "auth" ? "active" : ""}`} href="/auth">
          <Icon name="user"/>Oturum
        </Link>
        <div className="sidebar-status"><i/><div><strong>Yerel geliştirme</strong><span>PostgreSQL + hukuk korpusu</span></div></div>
      </div>
    </aside>
  );
}
