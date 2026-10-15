import { LegalChat } from "@/components/LegalChat";
import { DeepResearch } from "@/components/DeepResearch";
import { AIRunner } from "@/components/AIRunner";
import { useAuth } from "@/components/AuthProvider";
import { DOCUMENT_MODES, readDocumentContext } from "@/lib/document-workflow";
import { Link, useSearchParam } from "@/lib/router-compat";
import { cn } from "@/lib/utils";

const modes = [
  { id: "chat", label: "Sohbet" },
  { id: "deep", label: "Derin araştırma" },
  { id: "analysis", label: "Belge analizi" },
  { id: "summary", label: "Özetle" },
  { id: "risk", label: "Risk incelemesi" },
];
const examples = [
  "Kira artışında uygulanacak mevzuatı ve ilgili kararları araştır.",
  "İşe iade davasının şartları nelerdir?",
];

export function AssistantWorkspace() {
  const requested = useSearchParam("mode");
  const contextKey = useSearchParam("context");
  const { user } = useAuth();
  const mode = modes.some((item) => item.id === requested) ? requested : "chat";
  const context = user && contextKey ? readDocumentContext(user.id, contextKey) : null;
  const config =
    mode === "analysis" || mode === "summary" || mode === "risk" ? DOCUMENT_MODES[mode] : null;
  return (
    <div className="space-y-5">
      <nav aria-label="Asistan çalışma modu" className="flex flex-wrap gap-2">
        {modes.map((item) => (
          <Link
            key={item.id}
            to={`/dashboard/ai?${new URLSearchParams({ mode: item.id, ...(contextKey ? { context: contextKey } : {}) })}`}
            aria-current={mode === item.id ? "page" : undefined}
            className={cn(
              "rounded-lg border px-3 py-2 text-sm font-medium",
              mode === item.id
                ? "bg-primary text-primary-foreground border-primary"
                : "text-muted-foreground border-border hover:bg-secondary",
            )}
          >
            {item.label}
          </Link>
        ))}
      </nav>
      {contextKey && !context && (
        <p role="alert" className="rounded-lg border border-amber-500/30 p-3 text-sm">
          Belge seçiminin süresi dolmuş veya bu oturumda erişilemiyor. Belgeler ekranından yeniden
          seçin.
        </p>
      )}
      {context && !config && (
        <p className="text-sm text-muted-foreground">
          Taşıdığınız {context.ids.length} belge, Belge analizi, Özetle ve Risk incelemesi
          modlarında kullanılır. Bu mod genel hukuk kaynaklarında araştırma yapar.
        </p>
      )}
      {/* Genel sohbet modlar arasında korunur; devam eden cevap sekme değişiminde kaybolmaz. */}
      <div hidden={mode !== "chat"}>
        <LegalChat
          key={user?.id}
          title="Hukuk Asistanı"
          examples={examples}
          intro="Sorunuzu sorun veya yukarıdan çalışma modunu seçin. Yanıtların kaynakları ve doğrulama durumu gösterilir."
        />
      </div>
      {mode === "deep" && <DeepResearch key={user?.id} examples={examples} />}
      {config && !(contextKey && !context) && (
        <AIRunner
          key={`${mode}:${contextKey}:${user?.id}`}
          module={config.module}
          placeholder={
            mode === "risk"
              ? "İncelenecek olayı ve dikkat edilmesini istediğiniz konuları yazın veya kayıtlı belgelerinizi seçin."
              : "Kayıtlı belge seçin veya belge metnini yapıştırın."
          }
          initialDocIds={context?.ids}
          initialPrompt={context ? config.prompt : ""}
          caseId={context?.caseId}
          officeProjectId={context?.officeProjectId}
          contextKey={contextKey}
        />
      )}
    </div>
  );
}
