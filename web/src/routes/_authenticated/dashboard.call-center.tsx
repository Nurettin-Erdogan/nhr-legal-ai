import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { DashboardLayout } from "@/components/DashboardLayout";
import { useAuth } from "@/components/AuthContext";
import { db } from "@/lib/db";

type CallLog = {
  id: string;
  started_at: string;
  direction: string;
  phone: string;
  duration_sec: number;
  ai_summary: string | null;
  status: string;
};

const CallCenter = () => {
  const { user } = useAuth();
  const userId = user?.id;
  const [logs, setLogs] = useState<CallLog[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [loadedFor, setLoadedFor] = useState<string | null>(null);

  useEffect(() => {
    if (!userId) {
      setLoading(false);
      setLoadedFor(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError("");
    void (async () => {
      const result = await db
        .from("calls")
        .select("id,started_at,direction,phone,duration_sec,ai_summary,status")
        .order("started_at", { ascending: false })
        .limit(50);
      if (cancelled) return;
      if (result.error) setError(result.error.message);
      else setLogs((result.data ?? []) as CallLog[]);
      setLoadedFor(userId);
      setLoading(false);
    })();
    return () => {
      cancelled = true;
    };
  }, [userId]);

  return (
    <DashboardLayout title="Çağrılar" subtitle="Kayıtlı çağrılar ve bağlantı durumu">
      <div className="space-y-6">
        <section
          role="status"
          className="rounded-xl border border-amber-500/30 bg-amber-500/10 p-5 text-sm"
        >
          Telefon veya sesli AI sağlayıcısı bağlı değil. Bu sayfa arama yapmaz, numara tahsis etmez
          ve otomatik hatırlatma göndermez. Yalnızca hesabınızda gerçekten kayıtlı çağrılar varsa
          onları gösterir.
        </section>
        <section className="rounded-xl border border-border bg-card p-5">
          <h2 className="mb-4 text-lg font-semibold">Son 50 çağrı kaydı</h2>
          {!userId ? (
            <p>Çağrı kayıtları için oturum açın.</p>
          ) : loading || loadedFor !== userId ? (
            <p>Yükleniyor…</p>
          ) : error ? (
            <p role="alert" className="text-destructive">
              Çağrılar yüklenemedi: {error}
            </p>
          ) : logs.length === 0 ? (
            <p>Bu hesapta kayıtlı çağrı yok.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead>
                  <tr>
                    <th>Tarih</th>
                    <th>Yön</th>
                    <th>Numara</th>
                    <th>Süre</th>
                    <th>Durum</th>
                    <th>Özet</th>
                  </tr>
                </thead>
                <tbody>
                  {logs.map((call) => (
                    <tr key={call.id} className="border-t border-border">
                      <td className="p-2">{new Date(call.started_at).toLocaleString("tr-TR")}</td>
                      <td className="p-2">{call.direction === "inbound" ? "Gelen" : "Giden"}</td>
                      <td className="p-2">{call.phone}</td>
                      <td className="p-2">{call.duration_sec} sn</td>
                      <td className="p-2">{call.status}</td>
                      <td className="p-2">{call.ai_summary || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </div>
    </DashboardLayout>
  );
};

export const Route = createFileRoute("/_authenticated/dashboard/call-center")({
  component: CallCenter,
});
