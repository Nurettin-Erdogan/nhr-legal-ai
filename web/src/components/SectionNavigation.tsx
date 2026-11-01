import { Link } from "@/lib/router-compat";
import { SECTION_NAV } from "@/lib/nav";
import { cn } from "@/lib/utils";

/** İkincil araçlar kenar çubuğu yerine kendi çalışma alanında bulunur. */
export function SectionNavigation({ pathname }: { pathname: string }) {
  const section = SECTION_NAV.find((group) => group.items.some((item) => pathname === item.to));
  if (!section) return null;
  return (
    <nav aria-label={section.title} className="mb-6 flex flex-wrap gap-2">
      {section.items.map((item) => (
        <Link
          key={item.to}
          to={item.to}
          aria-current={pathname === item.to ? "page" : undefined}
          className={cn(
            "rounded-lg border px-3 py-2 text-sm font-medium transition-colors",
            pathname === item.to
              ? "border-primary bg-primary text-primary-foreground"
              : "border-border hover:bg-secondary text-muted-foreground",
          )}
        >
          {item.label}
        </Link>
      ))}
    </nav>
  );
}
