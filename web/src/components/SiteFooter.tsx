import { Link } from "@/lib/router-compat";

export const SiteFooter = () => {
  return (
    <footer className="border-t border-border bg-background">
      <div className="mx-auto flex max-w-5xl flex-col items-center gap-2 px-4 py-6 text-center text-xs text-muted-foreground sm:flex-row sm:justify-between sm:text-left">
        <p>Genel bilgilendirme amaçlıdır, hukuki tavsiye niteliği taşımaz.</p>
        <div className="flex items-center gap-4">
          <Link to="/sss" className="hover:text-foreground">
            SSS
          </Link>
          <Link to="/auth" className="hover:text-foreground">
            Avukat Girişi
          </Link>
          <span>© 2026 NHR Hukuk</span>
        </div>
      </div>
    </footer>
  );
};
