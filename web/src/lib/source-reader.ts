/** Never navigate to stored executable/credential-bearing URLs. No external fetch/proxy. */
export function safeSourceUrl(value: string | null | undefined): string | null {
  if (
    !value ||
    [...value].some((character) => character.charCodeAt(0) < 32 || character.charCodeAt(0) === 127)
  )
    return null;
  try {
    const url = new URL(value);
    return ["https:", "http:"].includes(url.protocol) && !url.username && !url.password
      ? url.href
      : null;
  } catch {
    return null;
  }
}

export function isSourceId(value: string | null | undefined): value is string {
  return !!value && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value);
}

export function sourceSiteLabel(value: string): string {
  const host = new URL(value).hostname;
  return /(^|\.)(yargitay\.gov\.tr|danistay\.gov\.tr|anayasa\.gov\.tr|mevzuat\.gov\.tr|adalet\.gov\.tr|ombudsman\.gov\.tr)$/.test(
    host,
  )
    ? "Resmî sitede aç ↗"
    : "Kaynak sitesinde aç ↗";
}

export function isRawPortalUrl(value: string): boolean {
  const url = new URL(value);
  return (
    ["karararama.yargitay.gov.tr", "karararama.danistay.gov.tr"].includes(url.hostname) &&
    /\/getDokuman\/?$/i.test(url.pathname)
  );
}
