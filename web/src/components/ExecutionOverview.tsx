import { Link } from "@/lib/router-compat";
import { cn } from "@/lib/utils";
import { dateTr, daysAgo } from "@/lib/execution";
import {
  groupParties,
  milestoneDates,
  queryCell,
  serviceOutcome,
  servicesHeadline,
  type ExecutionOverview as Overview,
  type Pair,
  type QueryTone,
} from "@/lib/execution-breakdown";

const QUERY_TONE: Record<QueryTone, string> = {
  var: "border-emerald-600/40 bg-emerald-600/10 text-emerald-700 dark:text-emerald-300",
  mixed: "border-amber-500/40 bg-amber-500/10 text-amber-800 dark:text-amber-300",
  yok: "border-border bg-secondary/50 text-muted-foreground",
  none: "border-dashed border-border bg-transparent text-muted-foreground",
};

function Pairs({ pairs, testId }: { pairs: Pair[]; testId: string }) {
  return (
    <dl className="grid grid-cols-1 gap-x-6 gap-y-2 sm:grid-cols-2" data-testid={testId}>
      {pairs.map((pair) => (
        <div key={pair.label} className="min-w-0">
          <dt className="text-xs text-muted-foreground">{pair.label}</dt>
          <dd className="break-words text-sm font-medium">{pair.value}</dd>
        </div>
      ))}
    </dl>
  );
}

/**
 * "İcra Özeti" sekmesinin üst bölümü: UYAP'tan çekilen dosya bilgisinden künye, taraflar, dosya hesabı, kişi başına sorgular,
 * önemli işlemler ve tebligatlar. Her değer UYAP'ın yazdığı metindir; burada hesap yapılmaz, sonuç çıkarılmaz.
 */
export function ExecutionOverview({ overview, caseId }: { overview: Overview | null; caseId: string }) {
  if (!overview)
    return (
      <section className="rounded-xl border border-border bg-card p-4 text-sm" data-testid="execution-overview-missing">
        <h3 className="text-base font-semibold">Dosya künyesi</h3>
        <p className="mt-1 text-muted-foreground">
          Bu dosyanın UYAP bilgileri (taraflar, safahat, dosya hesabı) henüz çekilmemiş. UYAP'a Bağlan sayfasındaki “Tüm dosyaları aktar” ile
          çekildiğinde künye, önemli işlemler ve borçlu sorguları burada görünür.
        </p>
        <Link to="/dashboard/uyap" className="mt-2 inline-block text-primary underline">
          UYAP'a Bağlan sayfasına git
        </Link>
      </section>
    );

  const { activity } = overview;
  const parties = groupParties(overview.parties);
  const otherCount = overview.otherActions.reduce((sum, item) => sum + item.count, 0);

  return (
    <div className="space-y-8" data-testid="execution-overview">
      <section aria-labelledby="execution-identity-title">
        <h3 id="execution-identity-title" className="text-base font-semibold">
          Dosya künyesi
        </h3>
        <p className="mt-1 text-xs text-muted-foreground">
          UYAP'tan {dateTr(overview.fetchedAt)} tarihinde çekilen bilgilerden derlenmiştir. Her değer UYAP'ın yazdığı metindir; JurisAI
          hesaplamaz, sonuç çıkarmaz. Kayıtların tamamı{" "}
          <Link to={`/dashboard/cases/${caseId}?tab=uyap`} className="underline">
            UYAP Bilgileri
          </Link>{" "}
          sekmesindedir.
        </p>
        {!overview.complete && (
          <p role="note" className="mt-2 rounded-lg border border-amber-500/30 bg-amber-500/5 p-2 text-xs text-amber-800 dark:text-amber-300">
            UYAP bilgileri eksik okunmuş olabilir: bazı tablolar UYAP'ın söylediği kayıt sayısıyla tutmuyor. Bu özet eksik kalmış olabilir.
          </p>
        )}
        <div className="mt-3 grid gap-4 rounded-xl border border-border bg-card p-4 lg:grid-cols-2">
          <div>
            {overview.identity.length > 0 ? (
              <Pairs pairs={overview.identity} testId="execution-identity" />
            ) : (
              <p className="text-sm text-muted-foreground">UYAP bu dosya için tür/durum bilgisi yazmamış.</p>
            )}
            {activity.entries > 0 && (
              <p className="mt-3 text-sm" data-testid="execution-activity">
                <span className="text-muted-foreground">Safahat: </span>
                {activity.entries} kayıt · ilk {dateTr(activity.firstDate)} · son {dateTr(activity.lastDate)}
                {activity.daysSinceLast !== null && <span className="font-medium"> ({daysAgo(activity.daysSinceLast)})</span>}
                {activity.lastType && (
                  <span className="mt-0.5 block text-xs text-muted-foreground">
                    Son kayıt: {activity.lastType}
                    {activity.lastText && activity.lastText !== activity.lastType ? ` — ${activity.lastText}` : ""}
                  </span>
                )}
              </p>
            )}
          </div>
          <div data-testid="execution-parties">
            {parties.length === 0 ? (
              <p className="text-sm text-muted-foreground">Taraf bilgisi okunmamış.</p>
            ) : (
              parties.map((group) => (
                <div key={group.role} className="mb-3 last:mb-0">
                  <div className="text-xs text-muted-foreground">
                    {group.role}
                    {group.members.length > 1 ? ` (${group.members.length})` : ""}
                  </div>
                  <ul className="mt-0.5 space-y-1">
                    {group.members.map((party, index) => (
                      <li key={`${party.name}-${index}`} className="break-words text-sm">
                        <span className="font-medium">{party.name}</span>
                        {party.type && <span className="text-xs text-muted-foreground"> · {party.type}</span>}
                        {party.lawyer && <span className="block text-xs text-muted-foreground">Vekil: {party.lawyer}</span>}
                      </li>
                    ))}
                  </ul>
                </div>
              ))
            )}
          </div>
        </div>
      </section>

      <section aria-labelledby="execution-account-title">
        <h3 id="execution-account-title" className="text-base font-semibold">
          Dosya hesabı (UYAP'ın yazdığı)
        </h3>
        {overview.account.length === 0 && overview.collections.length === 0 ? (
          <p className="mt-1 text-sm text-muted-foreground">UYAP bu dosya için hesap bilgisi yazmamış.</p>
        ) : (
          <div className="mt-3 space-y-4 rounded-xl border border-border bg-card p-4">
            {overview.account.length > 0 && <Pairs pairs={overview.account} testId="execution-account-fields" />}
            {overview.collections.length > 0 && (
              <div>
                <div className="mb-2 text-xs font-medium uppercase tracking-wider text-muted-foreground">Tahsilat / reddiyat özeti</div>
                <Pairs pairs={overview.collections} testId="execution-collections" />
              </div>
            )}
            <p className="text-xs text-muted-foreground">
              Bu tutarlar UYAP'ın yazdığı metindir. Aşağıdaki makbuz dökümünde makbuz metinlerinden okunan tutarlarla aynı şey değildir; ikisi
              yan yana durur, toplanmaz.
            </p>
          </div>
        )}
      </section>

      <section aria-labelledby="execution-queries-title">
        <h3 id="execution-queries-title" className="text-base font-semibold">
          Borçlu sorguları
        </h3>
        {overview.people.length === 0 ? (
          <p className="mt-1 text-sm text-muted-foreground">Safahatta araç, tapu, SGK ya da benzeri bir sorgu kaydı yok.</p>
        ) : (
          <>
            <p className="mt-1 rounded-lg border border-amber-500/30 bg-amber-500/5 p-2 text-xs text-amber-800 dark:text-amber-300">
              “VAR” ve “YOK”, UYAP'ın safahat kaydına yazdığı “Sorgu Sonucu” ifadesidir. Kaydın içeriği (hangi araç, hangi taşınmaz, çalışma
              durumu) burada görünmez; karar vermeden önce UYAP'taki sorgu sonucuna bakın. Kayıtta sonuç yazmıyorsa “sonuç yazılmamış” denir.
            </p>
            <ul className="mt-3 space-y-3" data-testid="execution-queries">
              {overview.people.map((person, index) => (
                <li key={`${person.name ?? "adsiz"}-${index}`} className="rounded-xl border border-border bg-card p-3 sm:p-4">
                  <div className="flex flex-wrap items-center gap-2 text-sm">
                    <span className="break-words font-medium">{person.name ?? "Kişi adı kayıtta okunamadı"}</span>
                    {person.role && <span className="rounded-full border border-border px-2 py-0.5 text-xs text-muted-foreground">{person.role}</span>}
                  </div>
                  <ul className="mt-2 flex flex-wrap gap-2">
                    {person.queries.map((query) => {
                      const cell = queryCell(query);
                      return (
                        <li key={query.key} className={cn("rounded-lg border px-2.5 py-1 text-xs", QUERY_TONE[cell.tone])} data-result={query.result ?? "none"}>
                          <span className="font-medium">{query.label}:</span> {cell.text}
                        </li>
                      );
                    })}
                  </ul>
                </li>
              ))}
            </ul>
          </>
        )}
      </section>

      <section aria-labelledby="execution-milestones-title">
        <h3 id="execution-milestones-title" className="text-base font-semibold">
          Önemli işlemler
        </h3>
        {overview.milestones.length === 0 ? (
          <p className="mt-1 text-sm text-muted-foreground">Safahat kaydı okunmamış ya da tanınan bir işlem yok.</p>
        ) : (
          <>
            <p className="mt-1 text-xs text-muted-foreground">
              Safahat kayıtları UYAP'taki işlem türüne göre gruplanmıştır (kaç kayıt, ilk ve son tarih). Bir işlemin kaydedilmiş olması onun
              hukuki sonucunu göstermez.
            </p>
            <ol className="mt-3 divide-y divide-border rounded-xl border border-border" data-testid="execution-milestones">
              {overview.milestones.map((item) => (
                <li key={item.key} className="p-3 sm:px-4">
                  <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-0.5 text-sm">
                    <span className="font-medium">{item.label}</span>
                    <span className="text-xs text-muted-foreground">
                      {item.count > 1 ? `${item.count} kayıt · ` : ""}
                      {milestoneDates(item)}
                    </span>
                  </div>
                  {item.recent.length > 0 && (
                    <details className="mt-1 text-xs text-muted-foreground">
                      <summary className="cursor-pointer select-none">{item.count > item.recent.length ? `Son ${item.recent.length} kayıt` : "Kayıt"}</summary>
                      <ul className="mt-1 space-y-1">
                        {item.recent.map((entry, index) => (
                          <li key={index} className="break-words">
                            {dateTr(entry.date)} — {entry.text}
                          </li>
                        ))}
                      </ul>
                      {item.uyapTypes.length > 0 && <p className="mt-1">UYAP işlem türü: {item.uyapTypes.join(" · ")}</p>}
                    </details>
                  )}
                </li>
              ))}
            </ol>
            {overview.otherActions.length > 0 && (
              <details className="mt-2 text-xs text-muted-foreground" data-testid="execution-other-actions">
                <summary className="cursor-pointer select-none">Diğer işlemler ({otherCount} kayıt)</summary>
                <ul className="mt-2 flex flex-wrap gap-1.5">
                  {overview.otherActions.map((item) => (
                    <li key={item.name} className="rounded-full border border-border bg-secondary/50 px-2 py-0.5">
                      {item.name} <span className="font-medium">{item.count}</span>
                    </li>
                  ))}
                </ul>
              </details>
            )}
          </>
        )}
      </section>

      <section aria-labelledby="execution-services-title">
        <h3 id="execution-services-title" className="text-base font-semibold">
          Tebligatlar
        </h3>
        <p className="mt-1 text-sm text-muted-foreground" data-testid="execution-services-headline">
          {servicesHeadline(overview.services)}
        </p>
        {overview.services.length > 0 && (
          <details className="mt-2">
            <summary className="cursor-pointer select-none text-sm text-primary">Tebligat kayıtlarını göster</summary>
            <ul className="mt-2 divide-y divide-border rounded-xl border border-border" data-testid="execution-services">
              {overview.services.map((item, index) => {
                const outcome = serviceOutcome(item);
                return (
                  <li key={`${item.barcode ?? "barkodsuz"}-${index}`} className="p-3 text-sm sm:px-4">
                    <div className="break-words font-medium">{item.recipient ?? "Muhatap kayıtta okunamadı"}</div>
                    <div className="mt-0.5 text-xs text-muted-foreground">
                      {item.sentDate ? `Çıkış kaydı: ${dateTr(item.sentDate)}` : "Çıkış kaydı yok"}
                      {item.method ? ` · ${item.method}` : ""}
                      {item.barcode ? ` · barkod ${item.barcode}` : ""}
                    </div>
                    <div className={cn("mt-0.5 text-xs", outcome.known ? "font-medium" : "text-muted-foreground")}>{outcome.text}</div>
                  </li>
                );
              })}
            </ul>
          </details>
        )}
      </section>
    </div>
  );
}
