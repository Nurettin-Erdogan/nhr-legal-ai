/**
 * Thin compatibility layer over TanStack Router so pages can keep using
 * simple string paths (`to="/dashboard/cases"`) instead of typed route params.
 */
import * as React from "react";
import {
  Link as TanStackLink,
  useNavigate as useTanStackNavigate,
  useParams as useTanStackParams,
  useLocation as useTanStackLocation,
  useRouterState,
} from "@tanstack/react-router";
import { cn } from "@/lib/utils";
import { searchParamText, splitPathQuery } from "@/lib/path-query";

type AnyProps = Record<string, unknown>;

export interface LinkProps extends Omit<React.AnchorHTMLAttributes<HTMLAnchorElement>, "href"> {
  to: string;
  replace?: boolean;
  state?: unknown;
  children?: React.ReactNode;
}

function isExternal(to: string) {
  return /^(https?:|mailto:|tel:|#)/.test(to);
}

export const Link = React.forwardRef<HTMLAnchorElement, LinkProps>(function Link(
  { to, state: _state, ...rest },
  ref,
) {
  if (isExternal(to)) {
    return <a ref={ref} href={to} {...rest} />;
  }
  const Any = TanStackLink as unknown as React.ComponentType<AnyProps>;
  // Sorgu ya da çapa taşıyan yol ("/dashboard/clients?q=…") yönlendiriciye parçalarına ayrılarak verilir.
  return <Any ref={ref} {...splitPathQuery(to)} {...(rest as AnyProps)} />;
});

export interface NavLinkProps extends LinkProps {
  className?: string;
  activeClassName?: string;
  end?: boolean;
  /** TanStack Link'in etkin eşleşmesi: varsayılan önek (alt yollar da etkin); `exact` yalnız tam yolu etkin sayar (aria-current için). */
  activeOptions?: { exact?: boolean };
}

export const NavLink = React.forwardRef<HTMLAnchorElement, NavLinkProps>(function NavLink(
  { to, className, activeClassName, end, ...rest },
  ref,
) {
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const isActive = end ? pathname === to : pathname === to || pathname.startsWith(`${to}/`);
  return (
    <Link
      ref={ref}
      to={to}
      className={cn(className, isActive && activeClassName)}
      {...(rest as AnyProps)}
    />
  );
});

export function useNavigate() {
  const navigate = useTanStackNavigate();
  return React.useCallback(
    (to: string | number, options?: { replace?: boolean; state?: unknown }) => {
      if (typeof to === "number") {
        if (typeof window !== "undefined") window.history.go(to);
        return;
      }
      if (isExternal(to)) {
        if (typeof window !== "undefined") window.location.href = to;
        return;
      }
      (navigate as unknown as (opts: AnyProps) => void)({ ...splitPathQuery(to), replace: options?.replace });
    },
    [navigate],
  );
}

export function useParams<T extends Record<string, string | undefined>>(): T {
  return useTanStackParams({ strict: false }) as unknown as T;
}

/** Adresteki tek bir sorgu değerini metin olarak verir (yoksa boş metin); adres değişince yeniden okunur. */
export function useSearchParam(name: string): string {
  return useRouterState({
    select: (state) => searchParamText((state.location.search as Record<string, unknown> | undefined)?.[name]),
  });
}

export function useLocation() {
  const location = useTanStackLocation();
  return {
    pathname: location.pathname,
    search: location.searchStr,
    hash: location.hash,
    state: (location.state ?? {}) as unknown as Record<string, unknown>,
  };
}

export function Navigate({ to, replace }: { to: string; replace?: boolean; state?: unknown }) {
  const navigate = useNavigate();
  React.useEffect(() => {
    navigate(to, { replace: replace ?? false });
  }, [navigate, to, replace]);
  return null;
}
