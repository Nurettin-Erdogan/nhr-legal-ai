import { Link } from "@/lib/router-compat";
import { useLocation } from "@/lib/router-hooks";
import { Button } from "@/components/ui/button";
import { Logo } from "./Logo";
import { ThemeToggle } from "./ThemeToggle";
import { cn } from "@/lib/utils";
import { useAuth } from "@/components/AuthContext";

const navItems = [
  { to: "/", label: "Ana Sayfa" },
  { to: "/sss", label: "SSS" },
];

export const SiteHeader = () => {
  const location = useLocation();
  const { user } = useAuth();

  return (
    <header className="sticky top-0 z-40 w-full border-b border-border bg-background/85 backdrop-blur-xl">
      <div className="mx-auto flex h-16 max-w-5xl items-center justify-between px-4">
        <Link to="/" aria-label="JurisAI ana sayfa">
          <Logo />
        </Link>

        <nav className="flex items-center gap-1">
          {navItems.map((item) => (
            <Link
              key={item.to}
              to={item.to}
              className={cn(
                // Dar ekranda yalnız tema ve giriş düğmesi sığar; menü bağlantıları alt bilgide de var.
                "hidden whitespace-nowrap rounded-full px-3.5 py-1.5 text-sm font-medium transition-colors sm:inline-block",
                location.pathname === item.to
                  ? "bg-secondary text-primary"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              {item.label}
            </Link>
          ))}
          <ThemeToggle />
          <Link to={user ? "/dashboard" : "/auth"} className="ml-1">
            <Button size="sm" className="shrink-0 whitespace-nowrap rounded-full">
              {user ? "Panele Git" : "Avukat Girişi"}
            </Button>
          </Link>
        </nav>
      </div>
    </header>
  );
};
