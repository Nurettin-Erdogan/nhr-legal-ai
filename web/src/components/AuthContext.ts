import { createContext, useContext } from "react";
import type { AuthUser } from "@/lib/auth-api";

export type Role = "admin" | "lawyer" | "intern" | "secretary";

export interface Profile {
  id: string;
  first_name: string | null;
  last_name: string | null;
  phone: string | null;
  office_name: string | null;
  avatar_url: string | null;
}

export interface LocalSession {
  access_token: string;
  user: AuthUser;
}

export interface AuthCtx {
  user: AuthUser | null;
  session: LocalSession | null;
  profile: Profile | null;
  roles: Role[];
  loading: boolean;
  signOut: () => Promise<void>;
  refreshProfile: () => Promise<void>;
  refreshAuth: () => Promise<AuthUser | null>;
}

export const Ctx = createContext<AuthCtx | undefined>(undefined);

export const useAuth = () => {
  const c = useContext(Ctx);
  if (!c) throw new Error("useAuth must be inside AuthProvider");
  return c;
};
