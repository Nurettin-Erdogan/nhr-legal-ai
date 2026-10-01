import { NavLink, useLocation, Link, useNavigate } from "@/lib/router-compat";
import {
  LayoutDashboard,
  Scale,
  BookOpen,
  FileSearch,
  Gavel,
  Camera,
  Briefcase,
  Inbox,
  FolderOpen,
  Link2,
  ScanText,
  FileSignature,
  Rocket,
  Settings,
  Menu,
  X,
  LogOut,
  User as UserIcon,
} from "lucide-react";
import { useState, type ReactNode } from "react";
import { Logo } from "./Logo";
import { cn } from "@/lib/utils";
import { ThemeToggle } from "./ThemeToggle";
import { useAuth } from "./AuthProvider";
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
} from "@/components/ui/dropdown-menu";

const navItems = [
  { to: "/dashboard", icon: LayoutDashboard, label: "Ana Sayfa" },
  { to: "/dashboard/cases", icon: Briefcase, label: "Davalar" },
  { to: "/dashboard/automation", icon: Rocket, label: "Tek Tuşla Otomasyon" },

  { to: "/dashboard/applications", icon: Inbox, label: "Başvurular" },
  { to: "/dashboard/ai", icon: Scale, label: "Hukuk Asistanı" },
  { to: "/dashboard/legislation", icon: BookOpen, label: "Mevzuat" },
  { to: "/dashboard/research", icon: FileSearch, label: "Hukuki Araştırma" },
  { to: "/dashboard/case-law", icon: Gavel, label: "İçtihat" },
  { to: "/dashboard/drafts", icon: FileSignature, label: "Dilekçe Yaz" },
  { to: "/dashboard/files", icon: FolderOpen, label: "Dosyalar" },
  { to: "/dashboard/document-processing", icon: ScanText, label: "Belge İşleme (OCR)" },
  { to: "/dashboard/uyap", icon: Link2, label: "UYAP'a Bağlan" },
  { to: "/dashboard/scanner", icon: Camera, label: "Belge Tarayıcı" },
  { to: "/dashboard/settings", icon: Settings, label: "Ayarlar" },
];

export const DashboardLayout = ({
  children,
  title,
  subtitle,
  actions,
}: {
  children: ReactNode;
  title: string;
  subtitle?: string;
  actions?: ReactNode;
}) => {
  const [mobileOpen, setMobileOpen] = useState(false);
  const location = useLocation();
  const incompleteScreen = [
    "/dashboard/appointments", "/dashboard/execution", "/dashboard/leads",
    "/dashboard/modules", "/dashboard/payments", "/dashboard/reports", "/dashboard/staff",
  ].includes(location.pathname);
  const { profile, user, signOut } = useAuth();
  const navigate = useNavigate();

  const initials = (() => {
    const f = profile?.first_name?.[0] ?? "";
    const l = profile?.last_name?.[0] ?? "";
    const fallback = user?.email?.[0]?.toUpperCase() ?? "?";
    return ((f + l).toUpperCase() || fallback).slice(0, 2);
  })();
  const displayName =
    [profile?.first_name, profile?.last_name].filter(Boolean).join(" ") ||
    user?.email ||
    "Kullanıcı";

  const nav = (
    <nav className="space-y-1">
      {navItems.map((item) => {
        const active =
          item.to === "/dashboard"
            ? location.pathname === "/dashboard"
            : location.pathname.startsWith(item.to);
        return (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.to === "/dashboard"}
            onClick={() => setMobileOpen(false)}
            className={cn(
              "flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition-colors",
              active
                ? "bg-secondary text-primary"
                : "text-muted-foreground hover:bg-muted hover:text-foreground",
            )}
          >
            <item.icon className="h-[18px] w-[18px] shrink-0" />
            <span className="truncate">{item.label}</span>
          </NavLink>
        );
      })}
    </nav>
  );

  return (
    <div className="flex min-h-screen w-full bg-background">
      {/* Sidebar */}
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-64 flex-col border-r border-border bg-card lg:flex">
        <div className="flex h-16 items-center px-5">
          <Link to="/">
            <Logo />
          </Link>
        </div>
        <div className="flex-1 overflow-y-auto px-3 py-3">{nav}</div>
      </aside>

      {/* Mobile drawer */}
      {mobileOpen && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <button
            className="absolute inset-0 bg-foreground/30"
            onClick={() => setMobileOpen(false)}
            aria-label="Menüyü kapat"
          />
          <div className="absolute inset-y-0 left-0 w-64 border-r border-border bg-card p-3">
            <div className="mb-3 flex h-12 items-center justify-between px-2">
              <Logo />
              <button onClick={() => setMobileOpen(false)} aria-label="Kapat">
                <X className="h-5 w-5" />
              </button>
            </div>
            {nav}
          </div>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col lg:ml-64">
        <header className="sticky top-0 z-20 flex h-16 items-center justify-between gap-4 border-b border-border bg-background/90 px-4 backdrop-blur-xl lg:px-8">
          <button
            className="rounded-lg p-2 hover:bg-muted lg:hidden"
            onClick={() => setMobileOpen(true)}
            aria-label="Menü"
          >
            <Menu className="h-5 w-5" />
          </button>
          <div className="min-w-0 flex-1">
            <h1 className="truncate text-base font-semibold">{title}</h1>
            {subtitle && <p className="truncate text-xs text-muted-foreground">{subtitle}</p>}
          </div>
          <div className="flex shrink-0 items-center gap-2">
            {actions}
            <ThemeToggle />
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <button
                  className="flex h-9 w-9 items-center justify-center rounded-full bg-secondary text-sm font-semibold text-primary transition hover:opacity-90"
                  aria-label="Hesap menüsü"
                >
                  {initials}
                </button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-56">
                <DropdownMenuLabel className="font-normal">
                  <div className="truncate text-sm font-medium">{displayName}</div>
                  <div className="truncate text-xs text-muted-foreground">{user?.email}</div>
                </DropdownMenuLabel>
                <DropdownMenuSeparator />
                <DropdownMenuItem onClick={() => navigate("/dashboard/settings")}>
                  <UserIcon className="mr-2 h-4 w-4" /> Profilim
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem
                  onClick={async () => {
                    await signOut();
                    navigate("/auth");
                  }}
                >
                  <LogOut className="mr-2 h-4 w-4" /> Çıkış yap
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </header>

        <main className="animate-fade-in flex-1 p-4 lg:p-8">
          {incompleteScreen && <p role="status" className="mb-4 rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-sm">
            Bu ekranın veri bağlantısı henüz tamamlanmadı. Boş listeler ve sıfır değerleri gerçek kayıt sayısını göstermez.
          </p>}
          {children}
        </main>
      </div>
    </div>
  );
};
