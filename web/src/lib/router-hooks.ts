import * as React from "react";
import {
  useNavigate as useTanStackNavigate,
  useParams as useTanStackParams,
  useLocation as useTanStackLocation,
  useRouterState,
} from "@tanstack/react-router";
import { searchParamText, splitPathQuery } from "@/lib/path-query";

type AnyProps = Record<string, unknown>;

export function isExternal(to: string) {
  return /^(https?:|mailto:|tel:|#)/.test(to);
}

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
      (navigate as unknown as (opts: AnyProps) => void)({
        ...splitPathQuery(to),
        replace: options?.replace,
      });
    },
    [navigate],
  );
}

export function useParams<T extends Record<string, string | undefined>>(): T {
  return useTanStackParams({ strict: false }) as unknown as T;
}

export function useSearchParam(name: string): string {
  return useRouterState({
    select: (state) =>
      searchParamText((state.location.search as Record<string, unknown> | undefined)?.[name]),
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
