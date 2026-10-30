import { useEffect, useState } from "react";
import { useAuth } from "./AuthContext";
import { accountSecurity, type AccountSecurity } from "@/lib/auth-api";

export function useAccountSecurity(): AccountSecurity | null {
  const { user } = useAuth();
  const [security, setSecurity] = useState<AccountSecurity | null>(null);
  useEffect(() => {
    if (!user?.id) return setSecurity(null);
    let cancelled = false;
    void accountSecurity()
      .then((value) => !cancelled && setSecurity(value))
      .catch(() => !cancelled && setSecurity(null));
    return () => {
      cancelled = true;
    };
  }, [user?.id]);
  return security;
}
