import { Link } from "@/lib/router-compat";

export const SiteFooter = () => {
  return (
    <footer className="border-t border-border bg-background">
      <div className="mx-auto flex max-w-5xl flex-col items-center gap-2 px-4 py-6 text-center text-xs text-muted-foreground sm:flex-row sm:justify-between sm:text-left">
        <p>Genel bilgilendirme amaçlıdır, hukuki tavsiye niteliği taşımaz.</p>
        <div className="flex flex-wrap items-center justify-center gap-x-4 gap-y-1">
          <Link to="/sss" className="hover:text-foreground">
            SSS
          </Link>
          <Link to="/gizlilik" className="hover:text-foreground">
            Gizlilik ve KVKK
          </Link>
          <Link to="/kullanim-sartlari" className="hover:text-foreground">
            Kullanım Şartları
          </Link>
          <Link to="/auth" className="hover:text-foreground">
            Avukat Girişi
          </Link>
          <span>© 2026 JurisAI</span>
        </div>
      </div>
    </footer>
  );
};
