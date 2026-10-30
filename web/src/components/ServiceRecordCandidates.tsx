import { useEffect, useMemo, useState } from "react";
import { formatDateTr } from "@/lib/deadlines";
import {
  loadServiceRecords,
  recordsHeadline,
  serviceCandidates,
  type ServiceRecords,
} from "@/lib/service-records";

/**
 * Süreler sekmesinde, davanın e-tebliğ mazbatalarından okunan tebliğ günlerini süre başlangıcı adayı olarak sunar.
 * Seçmek yalnız tarihi doldurur; hiçbir süre kendiliğinden başlatılmaz.
 */
export function ServiceRecordCandidates({
  caseId,
  onPick,
}: {
  caseId: string;
  onPick: (isoDate: string) => void;
}) {
  const [data, setData] = useState<ServiceRecords>();

  useEffect(() => {
    const controller = new AbortController();
    setData(undefined);
    // Bu bölüm yardımcıdır: yüklenemezse süre hesabı yine elle girilen tarihle çalışır, hata gösterilmez.
    loadServiceRecords(caseId, controller.signal)
      .then((loaded) => {
        if (!controller.signal.aborted) setData(loaded);
      })
      .catch(() => undefined);
    return () => controller.abort();
  }, [caseId]);

  const candidates = useMemo(() => (data ? serviceCandidates(data) : []), [data]);
  if (!data || (data.records.length === 0 && data.unreadable === 0)) return null;

  return (
    <div data-testid="service-records">
      <p className="mb-1 text-xs text-muted-foreground">
        Tebliğ mazbatalarından okunan günler ({recordsHeadline(data)}). Seçince tarihi doldurur;
        mazbatayı açıp siz doğrulayın:
      </p>
      {data.rule ? (
        <p className="mb-2 text-xs text-muted-foreground" data-testid="service-rule">
          <span className="font-medium">{data.rule.reference}:</span> “{data.rule.sentence}”
          {data.rule.sourceUrl && (
            <>
              {" "}
              <a href={data.rule.sourceUrl} target="_blank" rel="noreferrer" className="underline">
                resmî metin
              </a>
            </>
          )}
        </p>
      ) : (
        data.records.length > 0 && (
          <p className="mb-2 text-xs text-amber-700 dark:text-amber-300">
            E-tebligatın yapılmış sayıldığı güne ilişkin kanun maddesi korpusta doğrulanamadı; gün
            hesaplanmadı, yalnız mazbatada yazan tarihler gösteriliyor.
          </p>
        )
      )}
      {candidates.length > 0 && (
        <ul className="flex flex-col gap-2" data-testid="service-candidates">
          {candidates.map((item) => (
            <li key={`${item.documentId}-${item.date}-${item.label}`}>
              <button
                type="button"
                className="rounded-md border px-2 py-1 text-left text-xs hover:bg-secondary"
                onClick={() => onPick(item.date)}
              >
                {formatDateTr(item.date)} · {item.label}
              </button>
              {item.warning && (
                <p className="mt-0.5 text-xs text-amber-700 dark:text-amber-300">{item.warning}</p>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
