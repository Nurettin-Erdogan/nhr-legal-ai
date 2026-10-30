import { useEffect, useMemo, useRef, useState } from "react";
import { Loader2, Search, X } from "lucide-react";
import { useNavigate } from "@/lib/router-hooks";
import {
  buildSearchRows,
  groupRows,
  moveSelection,
  searchable,
  searchWorkspace,
  type WorkspaceSearchResult,
} from "@/lib/global-search";
import { cn } from "@/lib/utils";

const DEBOUNCE_MS = 250;

/**
 * Üst çubuktaki genel arama: kullanıcının kendi davaları, müvekkilleri, belgeleri ve görevleri; altta aynı terimi içtihatta,
 * mevzuatta ya da asistanda aramaya götüren kısayollar. "/" ya da Ctrl+K ile odaklanır; ok tuşları ve Enter ile gezilir.
 */
export function GlobalSearch() {
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const [result, setResult] = useState<WorkspaceSearchResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [open, setOpen] = useState(false);
  const [selected, setSelected] = useState(-1);
  // Dar ekranda kutu yer kaplamasın diye kapalıdır; büyüteç düğmesi üst çubuğun üzerine tam genişlikte açar.
  const [mobile, setMobile] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const text = query.trim();
    setError("");
    if (!searchable(text)) {
      setResult(null);
      setBusy(false);
      return;
    }
    const controller = new AbortController();
    setBusy(true);
    const timer = window.setTimeout(async () => {
      try {
        setResult(await searchWorkspace(text, controller.signal));
      } catch (cause) {
        if (controller.signal.aborted) return;
        setResult(null);
        setError(cause instanceof Error ? cause.message : "Arama şu an yapılamıyor.");
      } finally {
        if (!controller.signal.aborted) setBusy(false);
      }
    }, DEBOUNCE_MS);
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [query]);

  // Sonuç, yazılan terime aitse gösterilir (eski terimin sonucu yeni terimin altında görünmesin).
  const current = result && result.query === query.trim().replace(/\s+/g, " ") ? result : null;
  const rows = useMemo(() => buildSearchRows(current, query), [current, query]);
  const groups = useMemo(() => groupRows(rows), [rows]);
  const workspaceHits = rows.filter((row) => row.group !== "Hukuk kaynaklarında ara").length;

  useEffect(() => setSelected(-1), [query]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      const typing =
        target &&
        (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable);
      if (
        (event.key === "k" && (event.ctrlKey || event.metaKey)) ||
        (event.key === "/" && !typing)
      ) {
        event.preventDefault();
        input.current?.focus();
        setOpen(true);
      }
    };
    const onClick = (event: MouseEvent) => {
      if (box.current && !box.current.contains(event.target as Node)) setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    window.addEventListener("mousedown", onClick);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("mousedown", onClick);
    };
  }, []);

  const go = (href: string) => {
    setOpen(false);
    setMobile(false);
    setQuery("");
    input.current?.blur();
    navigate(href);
  };

  const onKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Escape") {
      setOpen(false);
      input.current?.blur();
    } else if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      setOpen(true);
      setSelected((value) => moveSelection(value, event.key === "ArrowDown" ? 1 : -1, rows.length));
    } else if (event.key === "Enter" && rows.length > 0) {
      event.preventDefault();
      go(rows[selected >= 0 ? selected : 0].href);
    }
  };

  const showPanel = open && searchable(query);
  let index = -1;

  return (
    <>
      <button
        type="button"
        className="rounded-lg p-2 hover:bg-muted md:hidden"
        aria-label="Ara"
        data-testid="global-search-open"
        onClick={() => {
          setMobile(true);
          setOpen(true);
          window.setTimeout(() => input.current?.focus(), 0);
        }}
      >
        <Search className="h-5 w-5" />
      </button>
      <div
        ref={box}
        data-testid="global-search"
        className={cn(
          "min-w-0 flex-1 md:relative md:block md:max-w-xs xl:max-w-md",
          mobile
            ? "absolute inset-x-0 top-0 z-30 flex h-16 items-center gap-2 bg-background px-4 md:inset-auto md:z-auto md:h-auto md:bg-transparent md:px-0"
            : "hidden",
        )}
      >
        <div className="relative min-w-0 flex-1">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <input
            ref={input}
            value={query}
            onChange={(event) => {
              setQuery(event.target.value);
              setOpen(true);
            }}
            onFocus={() => setOpen(true)}
            onKeyDown={onKeyDown}
            role="combobox"
            aria-expanded={showPanel}
            aria-controls="global-search-results"
            aria-label="Dava, müvekkil, belge ara"
            placeholder="Dava, müvekkil, belge ara…  ( / )"
            autoComplete="off"
            className="h-9 w-full rounded-lg border border-transparent bg-secondary/60 pl-9 pr-8 text-sm outline-none transition focus:border-primary/40 focus:bg-background"
          />
          {query && (
            <button
              type="button"
              onClick={() => {
                setQuery("");
                input.current?.focus();
              }}
              aria-label="Aramayı temizle"
              className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-0.5 text-muted-foreground hover:text-foreground"
            >
              {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <X className="h-4 w-4" />}
            </button>
          )}
          {showPanel && (
            <div
              id="global-search-results"
              role="listbox"
              className="absolute left-0 right-0 top-11 z-50 max-h-[70vh] overflow-y-auto rounded-xl border border-border bg-popover p-1.5 shadow-lg"
            >
              {error && (
                <p role="alert" className="px-3 py-2 text-sm text-destructive">
                  {error}
                </p>
              )}
              {!error && !busy && current && workspaceHits === 0 && (
                <p className="px-3 py-2 text-sm text-muted-foreground">
                  Davalarınızda, müvekkillerinizde, belgelerinizde ve görevlerinizde eşleşen kayıt
                  yok.
                </p>
              )}
              {groups.map((group) => (
                <div key={group.group} className="py-1">
                  <div className="px-3 pb-1 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground/70">
                    {group.group}
                  </div>
                  {group.rows.map((row) => {
                    index += 1;
                    const position = index;
                    return (
                      <button
                        key={row.key}
                        type="button"
                        role="option"
                        aria-selected={selected === position}
                        onMouseEnter={() => setSelected(position)}
                        onClick={() => go(row.href)}
                        className={cn(
                          "flex w-full flex-col items-start rounded-lg px-3 py-1.5 text-left",
                          selected === position ? "bg-secondary text-foreground" : "hover:bg-muted",
                        )}
                      >
                        <span className="w-full truncate text-sm font-medium">{row.label}</span>
                        {row.detail && (
                          <span className="w-full truncate text-xs text-muted-foreground">
                            {row.detail}
                          </span>
                        )}
                      </button>
                    );
                  })}
                </div>
              ))}
            </div>
          )}
        </div>
        {mobile && (
          <button
            type="button"
            className="rounded-lg p-2 text-sm text-muted-foreground hover:bg-muted md:hidden"
            aria-label="Aramayı kapat"
            onClick={() => {
              setMobile(false);
              setOpen(false);
              setQuery("");
            }}
          >
            Kapat
          </button>
        )}
      </div>
    </>
  );
}
