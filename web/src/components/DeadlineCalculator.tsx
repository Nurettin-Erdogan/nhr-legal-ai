import { useEffect, useMemo, useState } from "react";
import { db } from "@/lib/db";
import { useAuth } from "@/components/AuthContext";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  DEADLINE_RULES,
  calculateDeadline,
  formatDateTr,
  ruleById,
  startCandidates,
  weekdayName,
  type StartCandidate,
} from "@/lib/deadlines";
import { loadCaseDetail } from "@/lib/uyap-sync-api";
import { ServiceRecordCandidates } from "@/components/ServiceRecordCandidates";

/**
 * Dava detayındaki "Süreler" sekmesi: yasal süreyi hesaplar ve takvime işler. Hesap bir YARDIMCIDIR: kuralın dosyaya uyup uymadığı,
 * başlangıç tarihinin (gerçek tebliğ günü) doğruluğu ve adli tatil gibi özel hâller avukatın sorumluluğundadır. Safahattaki tebligat benzeri
 * kayıtlar yalnız tarihi doldurmak için ÖNERİLİR; süre kendiliğinden başlatılmaz.
 */
export function DeadlineCalculator({ caseId, onSaved }: { caseId: string; onSaved: () => void }) {
  const { user } = useAuth();
  const [ruleId, setRuleId] = useState(DEADLINE_RULES[0]!.id);
  const [start, setStart] = useState("");
  const [candidates, setCandidates] = useState<StartCandidate[]>([]);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    void loadCaseDetail(caseId, controller.signal).then((stored) => {
      const table = stored?.detail.tabs.find((tab) => tab.key === "safahat")?.tables[0];
      if (!controller.signal.aborted && table)
        setCandidates(startCandidates(table.headers, table.rows));
    });
    return () => controller.abort();
  }, [caseId]);

  const rule = ruleById(ruleId)!;
  const result = useMemo(() => (start ? calculateDeadline(rule, start) : null), [rule, start]);

  const addToCalendar = async () => {
    if (!result || !result.ok) return;
    if (!user?.id) return setMessage({ kind: "error", text: "Oturum bulunamadı." });
    setBusy(true);
    setMessage(null);
    const description = [
      `${result.rule.law}: ${result.rule.quote}.`,
      `Başlangıç (${result.rule.startLabel}): ${formatDateTr(result.start)}.`,
      ...result.steps,
      ...result.warnings,
      "Bu tarih yardımcı bir hesaptır; kural, başlangıç tarihi ve özel hâller (adli tatil vb.) avukatça doğrulanmalıdır.",
    ].join("\n");
    const { error } = await db.from("calendar_events").insert({
      owner_id: user.id,
      case_id: caseId,
      title: `Süre sonu: ${result.rule.title}`.slice(0, 200),
      description: description.slice(0, 4000),
      event_type: "deadline",
      start_at: new Date(`${result.end}T09:00:00`).toISOString(),
      all_day: true,
      reminder_minutes: 1440,
    });
    setBusy(false);
    if (error) return setMessage({ kind: "error", text: error.message || "Takvime eklenemedi." });
    setMessage({
      kind: "ok",
      text: `Takvime eklendi: ${formatDateTr(result.end)} (1 gün önce hatırlatılır).`,
    });
    onSaved();
  };

  return (
    <div className="space-y-5" data-testid="deadline-calculator">
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="space-y-1 text-xs text-muted-foreground">
          Süre türü
          <select
            value={ruleId}
            onChange={(event) => setRuleId(event.target.value)}
            className="h-9 w-full rounded-md border border-input bg-background px-2 text-sm text-foreground"
            data-testid="deadline-rule"
          >
            {DEADLINE_RULES.map((item) => (
              <option key={item.id} value={item.id}>
                {item.title} ({item.law})
              </option>
            ))}
          </select>
        </label>
        <label className="space-y-1 text-xs text-muted-foreground">
          {rule.startLabel}
          <Input
            type="date"
            value={start}
            onChange={(event) => setStart(event.target.value)}
            data-testid="deadline-start"
          />
        </label>
      </div>
      <p className="text-xs text-muted-foreground">
        <span className="font-medium">{rule.law}:</span> “{rule.quote}” — süre {rule.amount}{" "}
        {rule.unit}.
      </p>

      {/* Tebliğ mazbatasından okunan günler safahattan daha kesindir (safahat işlem tarihidir); önce onlar sunulur. */}
      <ServiceRecordCandidates caseId={caseId} onPick={setStart} />

      {candidates.length > 0 && (
        <div>
          <p className="mb-1 text-xs text-muted-foreground">
            Safahatta olası başlangıçlar (safahat tarihi işlem tarihidir, gerçek tebliğ günü
            olmayabilir; seçince tarihi doldurur, siz doğrulayın):
          </p>
          <ul className="flex flex-wrap gap-2" data-testid="deadline-candidates">
            {candidates.map((item) => (
              <li key={`${item.date}-${item.label}`}>
                <button
                  type="button"
                  className="rounded-md border px-2 py-1 text-left text-xs hover:bg-secondary"
                  onClick={() => setStart(item.date)}
                >
                  {formatDateTr(item.date)} · {item.label}
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      {result && !result.ok && (
        <p role="alert" className="text-sm text-destructive">
          {result.error}
        </p>
      )}
      {result && result.ok && (
        <div className="space-y-3 rounded-lg border p-4" data-testid="deadline-result">
          <p className="text-lg font-semibold" data-testid="deadline-end">
            Son gün: {formatDateTr(result.end)} {weekdayName(result.end)}
          </p>
          <ol className="list-decimal space-y-1 pl-5 text-sm">
            {result.steps.map((step) => (
              <li key={step}>{step}</li>
            ))}
          </ol>
          {result.recessEnd && (
            <p className="text-sm" data-testid="deadline-recess">
              İş adli tatile tabi ise (HMK m. 104):{" "}
              <span className="font-medium">
                {formatDateTr(result.recessEnd)} {weekdayName(result.recessEnd)}
              </span>
            </p>
          )}
          {result.warnings.length > 0 && (
            <ul
              role="note"
              className="list-disc space-y-1 pl-5 text-xs text-amber-700 dark:text-amber-300"
            >
              {result.warnings.map((warning) => (
                <li key={warning}>{warning}</li>
              ))}
            </ul>
          )}
          <div className="flex flex-wrap items-center gap-3">
            <Button
              type="button"
              size="sm"
              disabled={busy}
              onClick={() => void addToCalendar()}
              data-testid="deadline-add"
            >
              {busy ? "Ekleniyor…" : "Takvime ekle"}
            </Button>
            {message && (
              <span
                role={message.kind === "error" ? "alert" : "status"}
                className={`text-xs ${message.kind === "error" ? "text-destructive" : "text-emerald-700 dark:text-emerald-400"}`}
              >
                {message.text}
              </span>
            )}
          </div>
        </div>
      )}
      <p className="text-xs text-muted-foreground">
        Hesap yardımcı bir araçtır, hukuki görüş değildir: hangi sürenin uygulandığı, başlangıç
        tarihi ve özel hâller (adli tatil, tutuklu işler, özel kanun hükümleri) avukatın
        sorumluluğundadır. Süre kuralları ve dayanakları resmî mevzuat metniyle doğrulanmıştır;
        bayram tarihleri Diyanet takvimine göre girilmiştir.
      </p>
    </div>
  );
}
