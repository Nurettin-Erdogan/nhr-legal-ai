export const PETITION_FIELDS = [
  ["authority", "Mahkeme / başvuru mercii"],
  ["representative", "Vekil bilgileri"],
  ["evidence", "Deliller ve ekler"],
  ["requests", "Sonuç ve istem — açık talepleriniz"],
] as const;

export const CONTRACT_FIELDS = [
  ["payment", "Bedel ve ödeme koşulları"],
  ["term", "Sözleşme süresi"],
  ["obligations", "Tarafların hak ve yükümlülükleri"],
  ["termination", "Sona erme ve fesih koşulları"],
  ["confidentiality", "Gizlilik ve kişisel veri koşulları"],
  ["dispute", "Uyuşmazlık çözümü / yetki için talimatınız"],
  ["effective_date", "Yürürlük tarihi"],
] as const;

export const NOTICE_FIELDS = [
  ["notice_demand", "Talep edilen işlem"],
  ["notice_period", "Süre ve başlangıcı (örn. tebliğden itibaren 30 gün)"],
  ["notice_consequence", "Talep yerine getirilmezse yapılacak bildirim / işlem"],
  ["effective_date", "İhtarname tarihi"],
] as const;

export type DraftFields = Partial<
  Record<
    | (typeof PETITION_FIELDS)[number][0]
    | (typeof CONTRACT_FIELDS)[number][0]
    | (typeof NOTICE_FIELDS)[number][0],
    string
  >
>;

export function fieldsForDocument(type: string, values: DraftFields): DraftFields {
  const fields =
    type === "sozlesme"
      ? CONTRACT_FIELDS
      : type === "dilekce"
        ? PETITION_FIELDS
        : type === "ihtarname"
          ? NOTICE_FIELDS
          : [];
  return Object.fromEntries(fields.map(([key]) => [key, values[key]?.trim() ?? ""]));
}
