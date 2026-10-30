/**
 * "/dashboard/clients?q=Ayşe" gibi sorgu taşıyan düz yolları yönlendiricinin beklediği parçalara ayırır.
 * Yönlendirici sorguyu yoldan ayrı ister; yolun içinde bırakılırsa adres eşleşmez.
 */
export interface PathQuery {
  to: string;
  search?: Record<string, string>;
  hash?: string;
}

export function splitPathQuery(path: string): PathQuery {
  const hashAt = path.indexOf("#");
  const hash = hashAt >= 0 ? path.slice(hashAt + 1) : "";
  const withoutHash = hashAt >= 0 ? path.slice(0, hashAt) : path;
  const queryAt = withoutHash.indexOf("?");
  const result: PathQuery = { to: queryAt >= 0 ? withoutHash.slice(0, queryAt) : withoutHash };
  if (queryAt >= 0) {
    const search: Record<string, string> = {};
    for (const [key, value] of new URLSearchParams(withoutHash.slice(queryAt + 1)))
      search[key] = value;
    if (Object.keys(search).length) result.search = search;
  }
  if (hash) result.hash = hash;
  return result;
}

/** Yönlendiricinin ayrıştırdığı sorgu değerini metne çevirir ("123" sayı, "true" mantıksal değer olarak gelebilir). */
export function searchParamText(value: unknown): string {
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return "";
}
