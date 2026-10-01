import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { currentUser, inMemoryAccessToken, logout, type AuthUser } from "@/lib/auth-api";

type Role = "admin" | "lawyer" | "intern" | "secretary";

interface Profile {
  id: string;
  first_name: string | null;
  last_name: string | null;
  phone: string | null;
  office_name: string | null;
  avatar_url: string | null;
}

interface LocalSession {
  access_token: string;
  user: AuthUser;
}

interface AuthCtx {
  user: AuthUser | null;
  session: LocalSession | null;
  profile: Profile | null;
  roles: Role[];
  loading: boolean;
  signOut: () => Promise<void>;
  refreshProfile: () => Promise<void>;
  refreshAuth: () => Promise<AuthUser | null>;
}

const Ctx = createContext<AuthCtx | undefined>(undefined);

export const AuthProvider = ({ children }: { children: ReactNode }) => {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [session, setSession] = useState<LocalSession | null>(null);
  const [profile, setProfile] = useState<Profile | null>(null);
  const [roles, setRoles] = useState<Role[]>([]);
  const [loading, setLoading] = useState(true);

  const applyUser = (nextUser: AuthUser | null) => {
    setUser(nextUser);
    setSession(nextUser ? { access_token: inMemoryAccessToken(), user: nextUser } : null);
    if (!nextUser) {
      setProfile(null);
      setRoles([]);
      return;
    }

    const [firstName, ...lastNameParts] = (nextUser.full_name ?? "").trim().split(/\s+/);
    setProfile({
      id: nextUser.id,
      first_name: firstName || null,
      last_name: lastNameParts.join(" ") || null,
      phone: null,
      office_name: null,
      avatar_url: null,
    });
    setRoles(
      nextUser.roles.filter((role): role is Role =>
        ["admin", "lawyer", "intern", "secretary"].includes(role),
      ),
    );
  };

  const refreshAuth = async () => {
    const nextUser = await currentUser();
    applyUser(nextUser);
    return nextUser;
  };

  useEffect(() => {
    refreshAuth()
      .catch(() => applyUser(null))
      .finally(() => setLoading(false));
  }, []);

  const signOut = async () => {
    try {
      await logout();
    } catch {
      // Sunucuya ulaşılamasa da arayüzdeki oturum kapatılır; çerez sunucu dönünce silinir.
    } finally {
      applyUser(null);
    }
  };

  const refreshProfile = async () => {
    await refreshAuth();
  };

  return (
    <Ctx.Provider
      value={{ user, session, profile, roles, loading, signOut, refreshProfile, refreshAuth }}
    >
      {children}
    </Ctx.Provider>
  );
};

export const useAuth = () => {
  const c = useContext(Ctx);
  if (!c) throw new Error("useAuth must be inside AuthProvider");
  return c;
};
