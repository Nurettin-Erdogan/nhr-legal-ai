import { invokeFunction } from "@/lib/backend";
import { useEffect, useState, useCallback } from "react";
import { supabase } from "@/integrations/supabase/client";
import { useAuth } from "@/components/AuthContext";

export type SubscriptionStatus = {
  subscribed: boolean;
  tier: string | null;
  subscription_end: string | null;
};

export function useSubscription() {
  const { user } = useAuth();
  const [status, setStatus] = useState<SubscriptionStatus>({
    subscribed: false,
    tier: null,
    subscription_end: null,
  });
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(async () => {
    if (!user) return;
    setLoading(true);
    try {
      const { data, error } = await invokeFunction("check-subscription");
      if (!error && data) setStatus(data as SubscriptionStatus);
    } finally {
      setLoading(false);
    }
  }, [user]);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 60_000);
    return () => clearInterval(id);
  }, [refresh]);

  return { ...status, loading, refresh };
}

export async function startCheckout(plan: "starter" | "pro" | "kurumsal") {
  const { data, error } = await invokeFunction("create-checkout", {
    body: { plan },
  });
  if (error) throw error;
  if (data?.url) window.open(data.url, "_blank");
}
