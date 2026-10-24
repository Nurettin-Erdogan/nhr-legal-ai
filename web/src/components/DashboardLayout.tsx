import { NavLink, useLocation, Link, useNavigate } from "@/lib/router-compat";
import {
  LayoutDashboard,
  Scale,
  BookOpen,
  Gavel,
  Landmark,
  Briefcase,
  FolderOpen,
  Link2,
  FileSignature,
  Settings,
  Menu,
  X,
  LogOut,
  User as UserIcon,
  Users,
  ListChecks,
  FileText,
  ChevronDown,
  ShieldCheck,
  type LucideIcon,
} from "lucide-react";
import { isAdmin } from "@/lib/admin-panel";
import {
  NAV_COLLAPSED_KEY,
  ACCOUNT_NAV,
  ADMIN_NAV,
  NAV_GROUPS,
  activeNavPath,
  isNavGroupCollapsed,
  parseCollapsedGroups,
  toggleCollapsedGroup,
  visibleNavItems,
} from "@/lib/nav";
import { FeedbackButton } from "@/components/FeedbackButton";
import { GlobalSearch } from "@/components/GlobalSearch";
import { ReminderBell } from "@/components/ReminderBell";
import { SectionNavigation } from "@/components/SectionNavigation";
import { useEffect, useState, type ReactNode } from "react";
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

const NAV_ICONS: Record<string, LucideIcon> = {
  "/dashboard": LayoutDashboard,
  "/dashboard/cases": Briefcase,
  "/dashboard/execution": Landmark,
  "/dashboard/clients": Users,
  "/dashboard/tasks": ListChecks,
  "/dashboard/ai": Scale,
  "/dashboard/legislation": BookOpen,
  "/dashboard/case-law": Gavel,
  "/dashboard/drafts": FileSignature,
  "/dashboard/files": FolderOpen,
  "/dashboard/uyap": Link2,
  "/dashboard/settings": Settings,
};

// Her sayfa kendi DashboardLayout'unu kurar; tercih modülde tutulur ki sayfa geçişinde menü açılıp kapanmasın.
let rememberedCollapsed: string[] | null = null;

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
    "/dashboard/appointments",
    "/dashboard/leads",
    "/dashboard/modules",
    "/dashboard/payments",
    "/dashboard/reports",
    "/dashboard/staff",
  ].includes(location.pathname);
  const { profile, user, roles, signOut } = useAuth();
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

  const activePath = activeNavPath(location.pathname);
  const [collapsed, setCollapsed] = useState<string[]>(rememberedCollapsed ?? []);
  useEffect(() => {
    if (rememberedCollapsed !== null) return;
    try {
      rememberedCollapsed = parseCollapsedGroups(window.localStorage.getItem(NAV_COLLAPSED_KEY));
    } catch {
      rememberedCollapsed = [];
    }
    setCollapsed(rememberedCollapsed);
  }, []);
  const toggleGroup = (title: string) => {
    const next = toggleCollapsedGroup(collapsed, title);
    rememberedCollapsed = next;
    setCollapsed(next);
    try {
      window.localStorage.setItem(NAV_COLLAPSED_KEY, JSON.stringify(next));
    } catch {
      // saklama kapalıysa tercih yalnız bu oturumda geçerli olur
    }
  };
  const nav = (
    <nav className="space-y-4" aria-label="Ana menü">
      {NAV_GROUPS.map((group) => {
        const isActiveGroup = group.items.some((item) => item.to === activePath);
        const isCollapsed = isNavGroupCollapsed(group, collapsed.includes(group.title), activePath);
        return (
          <div key={group.title} className="space-y-1">
            <button
              type="button"
              onClick={() => toggleGroup(group.title)}
              disabled={isActiveGroup}
              title={
                isActiveGroup
                  ? "Bulunduğunuz bölüm açık kalır"
                  : isCollapsed
                    ? "Bölümü aç"
                    : "Bölümü kapat"
              }
              aria-expanded={!isCollapsed}
              className="flex w-full items-center justify-between gap-2 rounded-lg px-3 py-1 text-left text-[11px] font-semibold uppercase tracking-wide text-muted-foreground/70 transition-colors hover:text-foreground"
            >
              <span className="truncate">{group.title}</span>
              <ChevronDown
                className={cn(
                  "h-3.5 w-3.5 shrink-0 transition-transform",
                  isCollapsed && "-rotate-90",
                )}
              />
            </button>
            {visibleNavItems(group, isCollapsed, activePath).map((item) => {
              const Icon = NAV_ICONS[item.to] ?? FileText;
              const active = activePath === item.to;
              return (
                <NavLink
                  key={item.to}
                  to={item.to}
                  end={item.to === "/dashboard"}
                  activeOptions={{ exact: item.to === "/dashboard" }}
                  onClick={() => setMobileOpen(false)}
                  aria-current={active ? "page" : undefined}
                  className={cn(
                    "flex items-center gap-3 rounded-xl px-3 py-2 text-sm font-medium transition-colors",
                    active
                      ? "bg-secondary text-primary"
                      : "text-muted-foreground hover:bg-muted hover:text-foreground",
                  )}
                >
                  <Icon className="h-[18px] w-[18px] shrink-0" />
                  <span className="truncate">{item.label}</span>
                </NavLink>
              );
            })}
          </div>
        );
      })}
      <div className="border-t border-border pt-3">
        <Link
          to={ACCOUNT_NAV.to}
          onClick={() => setMobileOpen(false)}
          aria-current={activePath === ACCOUNT_NAV.to ? "page" : undefined}
          className={cn(
            "flex items-center gap-3 rounded-xl px-3 py-2 text-sm font-medium",
            activePath === ACCOUNT_NAV.to
              ? "bg-secondary text-primary"
              : "text-muted-foreground hover:bg-muted",
          )}
        >
          <Settings className="h-[18px] w-[18px]" /> {ACCOUNT_NAV.label}
        </Link>
        {isAdmin(roles) && (
          <Link
            to={ADMIN_NAV.to}
            onClick={() => setMobileOpen(false)}
            aria-current={activePath === ADMIN_NAV.to ? "page" : undefined}
            data-testid="admin-nav"
            className={cn(
              "mt-1 flex items-center gap-3 rounded-xl px-3 py-2 text-sm font-medium",
              activePath === ADMIN_NAV.to
                ? "bg-secondary text-primary"
                : "text-muted-foreground hover:bg-muted",
            )}
          >
            <ShieldCheck className="h-[18px] w-[18px]" /> {ADMIN_NAV.label}
          </Link>
        )}
      </div>
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
          <div className="absolute inset-y-0 left-0 w-64 overflow-y-auto border-r border-border bg-card p-3">
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
        {/* Telefonda sayfa düğmeleri ("Listeye Dön", "Yenile") üst çubuğa sığmıyor, sayfa yana taşıyordu (390 px'te 109 px;
            ölçüldü: 2026-10-09). Dar ekranda düğmeler çubuğun ikinci satırına iner; geniş ekranda düzen değişmez. */}
        <header className="sticky top-0 z-20 flex min-h-16 flex-wrap items-center justify-between gap-x-4 gap-y-2 border-b border-border bg-background/90 px-4 py-2 backdrop-blur-xl sm:flex-nowrap sm:py-0 lg:px-8">
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
          <GlobalSearch />
          {actions && (
            <div
              className="order-last flex w-full flex-wrap items-center gap-2 sm:order-none sm:w-auto sm:shrink-0 sm:flex-nowrap"
              data-testid="page-actions"
            >
              {actions}
            </div>
          )}
          <div className="flex shrink-0 items-center gap-2">
            <ReminderBell />
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
          <SectionNavigation pathname={location.pathname} />
          {incompleteScreen && (
            <p
              role="status"
              className="mb-4 rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-sm"
            >
              Bu ekranın veri bağlantısı henüz tamamlanmadı. Boş listeler ve sıfır değerleri gerçek
              kayıt sayısını göstermez.
            </p>
          )}
          {children}
        </main>
      </div>
      <FeedbackButton />
    </div>
  );
};
