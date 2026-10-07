/**
 * Yasal süre hesabı. Hesap KURAL tablosuyla yapılır; her kuralın dayanağı mevzuat metninden doğrulanmıştır (2026-10-06, resmî mevzuat
 * kaynağından): HMK 127, 345, 361; CMK 273, 291; 4857 s. İş K. 20; İİK 16, 62, 168. Süre hesabı kuralları HMK 92 ve 93'tür:
 *  - gün olarak belirlenen sürede tebliğ günü hesaba katılmaz, süre son günün tatil saatinde biter (HMK 92/1);
 *  - hafta/ay olarak belirlenen süre, başladığı güne karşılık gelen günün tatil saatinde biter; o ay böyle bir gün yoksa ayın son günü (HMK 92/2);
 *  - resmî tatil süreye dâhildir; son gün resmî tatile (hafta sonu dâhil) rastlarsa süre tatili izleyen ilk iş günü biter (HMK 93).
 * Bu bir YARDIMCI hesaptır, hukuki görüş değildir: hangi kuralın dosyaya uyduğu, başlangıç tarihinin doğruluğu (gerçek tebliğ günü) ve
 * adli tatil/özel hâller avukatın sorumluluğundadır. Adli tatile (20 Temmuz–31 Ağustos) rastlayan hesaplar OTOMATİK uzatılmaz; HMK 104'e
 * göre uzamış hâli ayrıca gösterilir çünkü işin adli tatile tabi olup olmadığı bilinemez.
 */

export type PeriodUnit = "gün" | "hafta" | "ay";

export interface DeadlineRule {
  id: string;
  title: string;
  /** Dayanak: "HMK m. 345/1". */
  law: string;
  /** Mevzuatın kendi ifadesi (doğrulanan metinden). */
  quote: string;
  amount: number;
  unit: PeriodUnit;
  /** Sürenin başladığı olay (kullanıcıdan istenen tarihin adı). */
  startLabel: string;
  /** Adli tatil (HMK 104) bu kurala uygulanabilir mi: yalnız HMK sürelerinde. */
  hmkRecess: boolean;
}

export const DEADLINE_RULES: DeadlineRule[] = [
  { id: "hmk-127", title: "Cevap dilekçesi verme süresi", law: "HMK m. 127/1", quote: "Cevap dilekçesini verme süresi, dava dilekçesinin davalıya tebliğinden itibaren iki haftadır", amount: 2, unit: "hafta", startLabel: "Dava dilekçesinin tebliğ tarihi", hmkRecess: true },
  { id: "hmk-345", title: "İstinaf (hukuk) başvuru süresi", law: "HMK m. 345/1", quote: "İstinaf yoluna başvuru süresi iki haftadır", amount: 2, unit: "hafta", startLabel: "Kararın tebliğ tarihi", hmkRecess: true },
  { id: "hmk-361", title: "Temyiz (hukuk) süresi", law: "HMK m. 361/1", quote: "tebliğ tarihinden itibaren iki hafta içinde temyiz yoluna başvurulabilir", amount: 2, unit: "hafta", startLabel: "Kararın tebliğ tarihi", hmkRecess: true },
  { id: "cmk-273", title: "İstinaf (ceza) istemi süresi", law: "CMK m. 273/1", quote: "hükmün gerekçesiyle birlikte tebliğ edildiği tarihten itibaren iki hafta içinde", amount: 2, unit: "hafta", startLabel: "Gerekçeli hükmün tebliğ tarihi", hmkRecess: false },
  { id: "cmk-291", title: "Temyiz (ceza) istemi süresi", law: "CMK m. 291/1", quote: "hükmün gerekçesiyle birlikte tebliğ edildiği tarihten itibaren iki hafta içinde", amount: 2, unit: "hafta", startLabel: "Gerekçeli hükmün tebliğ tarihi", hmkRecess: false },
  { id: "isk-20-arabulucu", title: "İşe iade: arabulucuya başvuru", law: "4857 s. İş K. m. 20/1", quote: "fesih bildiriminin tebliği tarihinden itibaren bir ay içinde işe iade talebiyle … arabulucuya başvurmak zorundadır", amount: 1, unit: "ay", startLabel: "Fesih bildiriminin tebliğ tarihi", hmkRecess: false },
  { id: "isk-20-dava", title: "İşe iade: arabuluculuk sonrası dava", law: "4857 s. İş K. m. 20/1", quote: "son tutanağın düzenlendiği tarihten itibaren, iki hafta içinde iş mahkemesinde dava açabilir", amount: 2, unit: "hafta", startLabel: "Arabuluculuk son tutanağının tarihi", hmkRecess: false },
  { id: "iik-62", title: "Ödeme emrine itiraz (ilamsız takip)", law: "İİK m. 62/1", quote: "ödeme emrinin tebliği tarihinden itibaren yedi gün içinde", amount: 7, unit: "gün", startLabel: "Ödeme emrinin tebliğ tarihi", hmkRecess: false },
  { id: "iik-16", title: "İcra mahkemesine şikâyet", law: "İİK m. 16/1", quote: "Şikayet bu muamelelerin öğrenildiği tarihten yedi gün içinde yapılır", amount: 7, unit: "gün", startLabel: "İşlemin öğrenildiği tarih", hmkRecess: false },
  { id: "iik-168", title: "Kambiyo senedi takibi: şikâyet / imza itirazı", law: "İİK m. 168/3-4", quote: "beş gün içinde icra mahkemesine şikayet etmesi / imza itirazını beş gün içinde bildirmesi", amount: 5, unit: "gün", startLabel: "Ödeme emrinin tebliğ tarihi", hmkRecess: false },
];

export const ruleById = (id: string): DeadlineRule | undefined => DEADLINE_RULES.find((rule) => rule.id === id);

/* ---------- Tatil takvimi ----------
   Sabit resmî tatiller her yıl aynıdır. Dinî bayramlar yıla göre değişir; aşağıdaki tarihler Diyanet takvimine göre elle girilmiştir (arife
   günleri tam tatil sayılmaz). Tablonun kapsamadığı yıllarda hafta sonu dışındaki tatiller denetlenemez ve bu uyarıyla belirtilir. */
const FIXED = ["01-01", "04-23", "05-01", "05-19", "07-15", "08-30", "10-29"];
const RELIGIOUS: Record<number, string[]> = {
  2025: ["03-30", "03-31", "04-01", "06-06", "06-07", "06-08", "06-09"],
  2026: ["03-20", "03-21", "03-22", "05-27", "05-28", "05-29", "05-30"],
  2027: ["03-09", "03-10", "03-11", "05-16", "05-17", "05-18", "05-19"],
};
/** Dinî bayram bilgisi bulunan yıllar. */
export const HOLIDAY_YEARS = Object.keys(RELIGIOUS).map(Number);

const iso = (date: Date) => date.toISOString().slice(0, 10);
const parse = (value: string): Date | null => {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (!match) return null;
  const date = new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])));
  return iso(date) === value ? date : null;
};
const addDays = (date: Date, days: number) => new Date(date.getTime() + days * 86400000);

export function addMonths(date: Date, months: number): Date {
  const total = date.getUTCFullYear() * 12 + date.getUTCMonth() + months;
  const year = Math.floor(total / 12);
  const month = total % 12;
  const lastDay = new Date(Date.UTC(year, month + 1, 0)).getUTCDate();
  return new Date(Date.UTC(year, month, Math.min(date.getUTCDate(), lastDay)));
}

export function holidayName(date: Date): string | null {
  const day = date.getUTCDay();
  if (day === 6) return "Cumartesi";
  if (day === 0) return "Pazar";
  const key = iso(date).slice(5);
  if (FIXED.includes(key)) return "resmî tatil";
  if ((RELIGIOUS[date.getUTCFullYear()] ?? []).includes(key)) return "dinî bayram tatili";
  return null;
}

const WEEKDAYS = ["Pazar", "Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi"];
export const weekdayName = (value: string): string => {
  const date = parse(value);
  return date ? WEEKDAYS[date.getUTCDay()]! : "";
};
export const formatDateTr = (value: string): string => {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  return match ? `${match[3]}.${match[2]}.${match[1]}` : value;
};

export interface DeadlineResult {
  ok: true;
  rule: DeadlineRule;
  start: string;
  /** Kural süresi eklenmiş ham son gün. */
  raw: string;
  /** Tatil kaydırması uygulanmış son gün (HMK 93). */
  end: string;
  steps: string[];
  warnings: string[];
  /** Adli tatile tabi bir işse (HMK 104) uzamış son gün; hesap adli tatile rastlamıyorsa null. */
  recessEnd: string | null;
}
export interface DeadlineError {
  ok: false;
  error: string;
}

/** Süreyi HMK 92-93'e göre hesaplar. `start`: ISO tarih (YYYY-MM-DD) — tebliğ/öğrenme günü. */
export function calculateDeadline(rule: DeadlineRule, start: string): DeadlineResult | DeadlineError {
  const base = parse(start);
  if (!base) return { ok: false, error: "Geçerli bir tarih girin." };
  const raw = rule.unit === "gün" ? addDays(base, rule.amount) : rule.unit === "hafta" ? addDays(base, 7 * rule.amount) : addMonths(base, rule.amount);
  const steps = [
    rule.unit === "gün"
      ? `${formatDateTr(start)} (${weekdayName(start)}) başlangıç günü hesaba katılmaz; ${rule.amount} gün sonrası ${formatDateTr(iso(raw))} (${weekdayName(iso(raw))}) (HMK m. 92/1).`
      : `${rule.amount} ${rule.unit} sonra, başladığı güne karşılık gelen gün: ${formatDateTr(iso(raw))} (${weekdayName(iso(raw))}) (HMK m. 92/2).`,
  ];
  let end = raw;
  const shifted: string[] = [];
  for (let guard = 0; guard < 15; guard += 1) {
    const reason = holidayName(end);
    if (!reason) break;
    shifted.push(`${formatDateTr(iso(end))} ${reason}`);
    end = addDays(end, 1);
  }
  if (shifted.length) steps.push(`Son gün tatile rastlıyor (${shifted.join(", ")}): süre tatili izleyen ilk iş günü biter → ${formatDateTr(iso(end))} (${weekdayName(iso(end))}) (HMK m. 93).`);
  const warnings: string[] = [];
  const years = new Set([base.getUTCFullYear(), end.getUTCFullYear()]);
  for (const year of years) if (!HOLIDAY_YEARS.includes(year)) warnings.push(`${year} yılının dinî bayram tarihleri tabloda yok: yalnız hafta sonu ve sabit resmî tatiller denetlendi; bayram günlerini elle kontrol edin.`);
  const recessStart = new Date(Date.UTC(raw.getUTCFullYear(), 6, 20));
  const recessEnd = new Date(Date.UTC(raw.getUTCFullYear(), 7, 31));
  let recessEndResult: string | null = null;
  if (raw >= recessStart && raw <= recessEnd) {
    if (rule.hmkRecess) {
      let extended = addDays(recessEnd, 7);
      while (holidayName(extended)) extended = addDays(extended, 1);
      recessEndResult = iso(extended);
      warnings.push(`Son gün adli tatile (20 Temmuz–31 Ağustos) rastlıyor. İş adli tatile tabi ise süre, adli tatilin bittiği günden itibaren bir hafta uzamış sayılır → ${formatDateTr(recessEndResult)} (HMK m. 104). İşin adli tatile tabi olup olmadığını kontrol edin; ana tarih uzatma UYGULANMADAN hesaplandı.`);
    } else {
      warnings.push("Son gün adli tatile (20 Temmuz–31 Ağustos) rastlıyor: bu kural için adli tatil etkisi otomatik hesaplanmadı; ilgili kanundaki özel hükme bakın.");
    }
  }
  if (rule.law.startsWith("CMK") || rule.law.startsWith("İİK") || rule.law.startsWith("4857"))
    warnings.push("Süre hesabı HMK m. 92-93 ilkeleriyle yapıldı; bu kanunun kendi süre/tatil hükmü farklıysa ona göre kontrol edin.");
  return { ok: true, rule, start, raw: iso(raw), end: iso(end), steps, warnings, recessEnd: recessEndResult };
}

/** Safahattaki tarih "gg.aa.yyyy" (bazen saatle) → ISO; okunamazsa null. */
export function isoFromTr(value: string): string | null {
  const match = /(\d{2})[./-](\d{2})[./-](\d{4})/.exec(value);
  if (!match) return null;
  const candidate = `${match[3]}-${match[2]}-${match[1]}`;
  return parse(candidate) ? candidate : null;
}

export interface StartCandidate {
  /** ISO tarih. */
  date: string;
  /** Safahattaki işlem türü ve açıklama (UYAP'ın yazdığı metin, kısaltılmış). */
  label: string;
}

/**
 * Safahattan "olası başlangıç" önerileri: işlem türü ya da açıklaması tebligat/ödeme emri/karar içeren kayıtlar. Safahat tarihi İŞLEM
 * tarihidir, gerçek TEBLİĞ günü olmayabilir: öneri yalnızca tarihi doldurur, kullanıcı doğrular. Hiçbir süre kendiliğinden başlatılmaz.
 */
export function startCandidates(headers: string[], rows: string[][], limit = 12): StartCandidate[] {
  const fold = (s: string) => s.toLocaleLowerCase("tr").replace(/ı/g, "i");
  const index = (needle: string) => headers.findIndex((header) => fold(header).includes(needle));
  const dateAt = index("tarih");
  const typeAt = index("işlem türü") >= 0 ? index("işlem türü") : index("islem turu");
  const textAt = index("açıklama") >= 0 ? index("açıklama") : index("aciklama");
  if (dateAt < 0) return [];
  const out: StartCandidate[] = [];
  for (const row of rows) {
    const text = fold(`${row[typeAt] ?? ""} ${row[textAt] ?? ""}`);
    if (!/tebli[gğ]|ödeme emri|odeme emri|karar/.test(text)) continue;
    const date = isoFromTr(row[dateAt] ?? "");
    if (!date) continue;
    const label = `${row[typeAt] ?? ""}${row[textAt] ? ` — ${row[textAt]}` : ""}`.trim().slice(0, 140);
    if (!out.some((item) => item.date === date && item.label === label)) out.push({ date, label });
  }
  return out.sort((a, b) => (a.date < b.date ? 1 : -1)).slice(0, limit);
}
