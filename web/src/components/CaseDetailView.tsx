import { useState, type ReactNode } from "react";
import {
  caseStatusLabels,
  displayCaseDate,
  type CaseDetailData,
  type Section,
} from "../lib/case-detail";

const tabs = [
  "Özet",
  "Evraklar",
  "UYAP Bilgileri",
  "Süreler",
  "Belgelerle Sor",
  "Belge Kıyasla",
  "Dosya Özeti",
  "Notlar",
  "Görevler",
  "Takvim",
  "Aramalar",
] as const;
type Tab = (typeof tabs)[number];
const actionClass =
  "rounded-md border border-border px-3 py-2 text-sm hover:bg-secondary disabled:opacity-50";

function Records<T>({
  section,
  children,
}: {
  section: Section<T>;
  children: (row: T) => ReactNode;
}) {
  if (section.error)
    return (
      <p role="alert" className="text-sm text-destructive">
        {section.error}
      </p>
    );
  if (!section.rows.length)
    return <p className="text-sm text-muted-foreground">Bu davaya bağlı kayıt bulunmuyor.</p>;
  return (
    <>
      {section.hasMore && (
        <p className="text-sm text-muted-foreground mb-3">
          Son 50 kayıt gösteriliyor. Diğer kayıtlar ilgili modülden görüntülenebilir.
        </p>
      )}
      <ul className="divide-y divide-border">{section.rows.map(children)}</ul>
    </>
  );
}

export function CaseDetailView({
  data,
  onDownload,
  downloading,
  downloadError,
  documentActions,
  documentAsk,
  documentCompare,
  caseSummary,
  uyapDetail,
  deadlines,
  documentTrash,
  onTrash,
  trashing,
  initialTab = "Özet",
  notesEditor,
  taskComposer,
}: {
  data: CaseDetailData;
  onDownload: (id: string) => void;
  downloading?: string;
  downloadError?: string;
  documentActions?: ReactNode;
  /** "Belgelerle Sor" sekmesinin içeriği (dava belgeleriyle sohbet). */
  documentAsk?: ReactNode;
  /** "Belge Kıyasla" sekmesinin içeriği (iki belgenin metin farkı). */
  documentCompare?: ReactNode;
  /** "Dosya Özeti" sekmesinin içeriği (olgu tablosu ve belge özetleri). */
  caseSummary?: ReactNode;
  /** "UYAP Bilgileri" sekmesinin içeriği (taraflar, safahat, dosya hesabı, tahsilat/reddiyat). */
  uyapDetail?: ReactNode;
  /** "Süreler" sekmesinin içeriği (yasal süre hesabı ve takvime ekleme). */
  deadlines?: ReactNode;
  /** Evraklar sekmesinin altındaki çöp kutusu bölümü. */
  documentTrash?: ReactNode;
  /** Belgeyi çöp kutusuna taşır (geri alınabilir). */
  onTrash?: (id: string) => void;
  trashing?: string;
  initialTab?: Tab;
  /** "Notlar" sekmesinde düz metin yerine gösterilen düzenleyici (not ekleme/değiştirme). */
  notesEditor?: ReactNode;
  /** "Görevler" sekmesinin üstündeki hızlı görev ekleme formu. */
  taskComposer?: ReactNode;
}) {
  const [tab, setTab] = useState<Tab>(initialTab);
  const c = data.record;
  // Telefon/çağrı hizmeti bağlı değilken "Aramalar" sekmesi boş bir söz olur: yalnız gerçek arama kaydı varsa gösterilir.
  const visibleTabs = tabs.filter((name) => name !== "Aramalar" || data.calls.rows.length > 0 || tab === "Aramalar");
  const fields = [
    ["Dosya numarası", c.case_no],
    ["Esas numarası", c.esas_no],
    ["Mahkeme", c.court],
    ["Dava türü", c.case_type],
    ["Müvekkil", data.clientError ? "Yüklenemedi" : data.clientName],
    ["Karşı taraf", c.opponent],
    ["Durum", caseStatusLabels[c.status] ?? c.status],
    ["Açılış tarihi", displayCaseDate(c.opened_at, true)],
    ["Kayıtlı duruşma tarihi", displayCaseDate(c.next_hearing)],
    ["Son kayıt güncellemesi", displayCaseDate(c.updated_at)],
  ];
  return (
    <section className="rounded-2xl bg-card border border-border p-6">
      <nav
        aria-label="Dava bölümleri"
        className="flex flex-wrap gap-2 border-b border-border pb-4 mb-5"
      >
        {visibleTabs.map((name) => (
          <button
            type="button"
            key={name}
            aria-pressed={tab === name}
            className={`${actionClass} ${tab === name ? "bg-primary text-primary-foreground" : "text-muted-foreground"}`}
            onClick={() => setTab(name)}
          >
            {name}
          </button>
        ))}
      </nav>
      <h2 className="text-lg font-semibold mb-4">{tab}</h2>
      {tab === "Özet" && (
        <>
          {data.clientError && (
            <p role="alert" className="text-destructive text-sm mb-3">
              Müvekkil: {data.clientError}
            </p>
          )}
          <dl className="grid sm:grid-cols-2 gap-5">
            {fields.map(([label, value]) => (
              <div key={label}>
                <dt className="text-xs text-muted-foreground">{label}</dt>
                <dd className="text-sm mt-1 break-words">{value || "Belirtilmemiş"}</dd>
              </div>
            ))}
          </dl>
          <p className="mt-6 text-sm text-muted-foreground">
            Bu bilgiler kayıtlı dava verileridir; AI değerlendirmesi veya dava sonucu tahmini
            değildir.
          </p>
          <p className="mt-2 text-sm text-muted-foreground">
            Notlar sekmesinden not ekleyebilir, Görevler sekmesinden bu davaya görev açabilirsiniz. Diğer dava bilgileri dava
            listesindeki Düzenle işlemiyle güncellenir.
          </p>
        </>
      )}
      {tab === "UYAP Bilgileri" &&
        (uyapDetail ?? (
          <p className="text-sm text-muted-foreground">
            UYAP dosya bilgileri bu görünümde kullanılamıyor.
          </p>
        ))}
      {tab === "Süreler" &&
        (deadlines ?? (
          <p className="text-sm text-muted-foreground">
            Süre hesabı bu görünümde kullanılamıyor.
          </p>
        ))}
      {tab === "Belgelerle Sor" &&
        (documentAsk ?? (
          <p className="text-sm text-muted-foreground">
            Belgelerle sohbet bu görünümde kullanılamıyor.
          </p>
        ))}
      {tab === "Belge Kıyasla" &&
        (documentCompare ?? (
          <p className="text-sm text-muted-foreground">
            Belge karşılaştırma bu görünümde kullanılamıyor.
          </p>
        ))}
      {tab === "Dosya Özeti" &&
        (caseSummary ?? (
          <p className="text-sm text-muted-foreground">
            Dosya özeti bu görünümde kullanılamıyor.
          </p>
        ))}
      {tab === "Notlar" &&
        (notesEditor ?? (
          <p className="whitespace-pre-wrap break-words text-sm">
            {c.notes || "Bu dava için kayıtlı not bulunmuyor."}
          </p>
        ))}
      {tab === "Evraklar" && (
        <>
          {documentActions}
          <p className="text-sm text-muted-foreground mb-3">
            Yalnız bu davaya bağlanmış evraklar listelenir; bağlantısız UYAP belgeleri burada
            görünmez.
          </p>
          {downloadError && (
            <p role="alert" className="text-sm text-destructive mb-3">
              {downloadError}
            </p>
          )}
          <Records section={data.documents}>
            {(d) => (
              <li key={d.id} className="py-3 flex items-center justify-between gap-3">
                <div className="min-w-0">
                  <p className="text-sm break-words">{d.file_name}</p>
                  {d.uyap_path && (
                    <p className="text-xs text-muted-foreground break-words" title="UYAP klasör yolu">
                      📁 {d.uyap_path}
                    </p>
                  )}
                  <p className="text-xs text-muted-foreground">
                    {d.doc_type || "Evrak"} · {displayCaseDate(d.created_at)}
                  </p>
                </div>
                <div className="flex shrink-0 gap-2">
                  <button
                    type="button"
                    className={actionClass}
                    disabled={!!downloading}
                    onClick={() => onDownload(d.id)}
                  >
                    {downloading === d.id ? "İndiriliyor…" : "İndir"}
                  </button>
                  {onTrash && (
                    <button
                      type="button"
                      className={actionClass}
                      disabled={!!trashing}
                      onClick={() => onTrash(d.id)}
                    >
                      {trashing === d.id ? "Taşınıyor…" : "Çöpe taşı"}
                    </button>
                  )}
                </div>
              </li>
            )}
          </Records>
          {documentTrash}
        </>
      )}
      {tab === "Görevler" && taskComposer}
      {tab === "Görevler" && (
        <Records section={data.tasks}>
          {(t) => (
            <li key={t.id} className="py-3 text-sm">
              <p>{t.title}</p>
              <p className="text-xs text-muted-foreground">
                {(
                  { todo: "Yapılacak", in_progress: "Sürüyor", done: "Tamamlandı" } as Record<
                    string,
                    string
                  >
                )[t.status] ?? t.status}{" "}
                · Son tarih: {displayCaseDate(t.due_date)}
              </p>
            </li>
          )}
        </Records>
      )}
      {tab === "Takvim" && c.next_hearing && (
        <div className="mb-4 rounded-lg border border-border bg-secondary/40 p-3 text-sm" data-testid="case-hearing">
          <p className="font-medium">Duruşma</p>
          <p className="text-xs text-muted-foreground">
            {displayCaseDate(c.next_hearing)} · {c.court || "Mahkeme belirtilmemiş"} · dava kaydındaki "Sonraki Duruşma" tarihi
          </p>
        </div>
      )}
      {tab === "Takvim" && (!c.next_hearing || data.events.rows.length > 0 || data.events.error) && (
        <Records section={data.events}>
          {(e) => (
            <li key={e.id} className="py-3 text-sm">
              <p>{e.title}</p>
              <p className="text-xs text-muted-foreground">
                {displayCaseDate(e.start_at)} · {e.location || "Yer belirtilmemiş"}
              </p>
            </li>
          )}
        </Records>
      )}
      {tab === "Aramalar" && (
        <Records section={data.calls}>
          {(a) => (
            <li key={a.id} className="py-3 text-sm">
              <p>
                {a.direction === "inbound"
                  ? "Gelen arama"
                  : a.direction === "outbound"
                    ? "Giden arama"
                    : a.direction}{" "}
                · {a.status}
              </p>
              <p className="text-xs text-muted-foreground">
                {displayCaseDate(a.started_at)} · {a.duration_sec} saniye
              </p>
            </li>
          )}
        </Records>
      )}
    </section>
  );
}
