/**
 * Aynı kaynağa giden atıfları tek satırda toplar. Uzun bir kanun maddesi birkaç parçaya bölünmüş olarak gelir; her parça ayrı bir
 * [K] işareti alır ve liste aynı satırı dört kez gösteriyordu ("İŞ KANUNU (1475) m. 14" × 4). İşaretler değişmez (metindeki [K2]
 * hâlâ geçerlidir); yalnız liste sadeleşir. Yalnız künyesi, bağlantısı ve doğrulama durumu AYNI olan atıflar birleştirilir.
 */
export interface GroupableCitation {
  marker: string;
  source_id?: string | null;
  reference: string;
  source_url: string | null;
  verification: string;
}

export interface CitationGroup<T extends GroupableCitation> {
  /** Gösterilecek işaret: "K1", "K1, K3" ya da ardışıksa "K1–K4". */
  label: string;
  markers: string[];
  citation: T;
}

function markerLabel(markers: string[]): string {
  if (markers.length === 1) return markers[0];
  const numbers = markers.map((marker) => Number(/^K(\d+)$/.exec(marker)?.[1] ?? NaN));
  const consecutive = numbers.every(
    (value, index) => Number.isFinite(value) && (index === 0 || value === numbers[index - 1] + 1),
  );
  return consecutive ? `${markers[0]}–${markers[markers.length - 1]}` : markers.join(", ");
}

export function groupCitations<T extends GroupableCitation>(citations: T[]): CitationGroup<T>[] {
  const groups = new Map<string, { markers: string[]; citation: T }>();
  for (const citation of citations) {
    const key = JSON.stringify([
      citation.source_id ?? "",
      citation.reference,
      citation.source_url ?? "",
      citation.verification,
    ]);
    const existing = groups.get(key);
    if (existing) existing.markers.push(citation.marker);
    else groups.set(key, { markers: [citation.marker], citation });
  }
  return [...groups.values()].map((group) => ({ ...group, label: markerLabel(group.markers) }));
}
