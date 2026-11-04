import { createFileRoute } from "@tanstack/react-router";
import { useEffect } from "react";
import { useAuth } from "@/components/AuthContext";
import { useNavigate } from "@/lib/router-hooks";

// Karşılama ekranı yok: oturum açıksa doğrudan panele, değilse giriş sayfasına gidilir.
function HomePage() {
  const { user, loading } = useAuth();
  const navigate = useNavigate();

  useEffect(() => {
    if (loading) return;
    navigate(user ? "/dashboard" : "/auth", { replace: true });
  }, [loading, user, navigate]);

  return <div aria-hidden="true" />;
}

export const Route = createFileRoute("/")({
  head: () => ({ meta: [{ title: "JurisAI — Hukuk Bürosu" }] }),
  component: HomePage,
});
