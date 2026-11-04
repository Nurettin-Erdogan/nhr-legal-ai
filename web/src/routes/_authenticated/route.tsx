import { createFileRoute, Outlet, redirect } from "@tanstack/react-router";
import { currentUser } from "@/lib/auth-api";

export const Route = createFileRoute("/_authenticated")({
  ssr: false,
  pendingMs: 150,
  pendingComponent: () => (
    <main className="flex min-h-screen items-center justify-center bg-background text-foreground">
      <p role="status">Oturum kontrol ediliyor…</p>
    </main>
  ),
  errorComponent: () => (
    <main className="flex min-h-screen items-center justify-center bg-background text-foreground">
      <div className="space-y-4 text-center">
        <h1 className="font-semibold">Uygulamaya bağlantı kurulamadı</h1>
        <p>Sunucu geçici olarak yanıt vermiyor. Bağlantı geri geldiğinde tekrar deneyin.</p>
        <button
          className="rounded-md bg-primary px-4 py-2 text-primary-foreground"
          onClick={() => window.location.reload()}
        >
          Yeniden bağlan
        </button>
      </div>
    </main>
  ),
  beforeLoad: async () => {
    const user = await currentUser();
    if (!user) throw redirect({ to: "/auth" });
    return { user };
  },
  component: () => <Outlet />,
});
