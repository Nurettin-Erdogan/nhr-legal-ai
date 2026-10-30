import { useCallback, useEffect, useState, type ReactNode } from "react";
import { Ctx, type Role, type Profile, type LocalSession } from "./AuthContext";
import { currentUser, inMemoryAccessToken, logout, type AuthUser } from "@/lib/auth-api";
import { setSyncOwner } from "@/lib/uyap-sync-store";

export const AuthProvider = ({ children }: { children: ReactNode }) => {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [session, setSession] = useState<LocalSession | null>(null);
  const [profile, setProfile] = useState<Profile | null>(null);
  const [roles, setRoles] = useState<Role[]>([]);
  const [loading, setLoading] = useState(true);

  const applyUser = useCallback((nextUser: AuthUser | null) => {
    setSyncOwner(nextUser?.id ?? null);
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
  }, []);

  const refreshAuth = useCallback(async () => {
    const nextUser = await currentUser();
    applyUser(nextUser);
    return nextUser;
  }, [applyUser]);

  useEffect(() => {
    refreshAuth()
      .catch(() => applyUser(null))
      .finally(() => setLoading(false));
  }, [applyUser, refreshAuth]);

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
