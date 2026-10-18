/**
 * UYAP'taki bütün dosyaları sırayla aktarır ve her dosya için EKSİKSİZLİĞİ kanıtlar.
 *
 * Kanıt, aktarım sayacı değil sunucunun kendi kaydıdır: aktarımdan sonra dosyanın evrak ağacı UYAP'tan yeniden okunur ve
 * "JurisAI hesabında zaten olan evrak kimlikleri" listesiyle karşılaştırılır. Bir dosya yalnız şu üç koşul birlikte
 * sağlanınca "eksiksiz" sayılır:
 *   1. UYAP'ın ağaçta yazdığı evrak sayısı bulunan evrak sayısıyla uyuşuyor (ya da fark yalnız aynı evrakın birden çok
 *      klasörde görünmesinden), açılamayan klasör ve kimliksiz evrak yok;
 *   2. ağaçtaki her evrak kimliği sunucuda kayıtlı;
 *   3. sunucu kayıtlarını gerçekten bildirdi (`knownChecked`).
 * Eksik kalan evrak "aktarıldı" diye sayılmaz: dosya "eksik" olarak raporlanır, kaç evrağın eksik olduğu ve nedeni yazılır.
 * Aynı dosya tekrar çalıştırılınca yalnız eksikler çekilir (zaten olanlar atlanır).
 */
import {
  startDetailJob,
  startPullJob,
  startTreeJob,
  recoverReadJob,
  listUyapDosyalari,
  stopJob,
  waitForJob,
  type BridgeDosya,
  type BridgeFailure,
  type BridgeReply,
  type DosyaDetail,
  type JobStatus,
  type TreeResult,
  type UyapIdentity,
  type WaitOptions,
} from "@/lib/uyap-bridge";
import { steadySleep } from "@/lib/steady-timer";

/** Aynı UYAP kişisi mi (parmak izi + tür). Köprüdeki `sameIdentity` ile aynı kural; testler köprüyü sahtelediği için burada da tanımlı. */
const sameIdentity = (a: UyapIdentity | null | undefined, b: UyapIdentity | null | undefined): boolean =>
  !!a && !!b && a.kind === b.kind && a.fingerprint === b.fingerprint;

/** "empty": UYAP dosyada evrak bulunmadığını kendisi bildiriyor; aktarılacak bir şey yoktur, eksik sayılmaz. */
export type FileOutcome = "complete" | "empty" | "incomplete" | "failed" | "pending";

export interface FileReport {
  key: string;
  esas: string;
  birim: string;
  yargiTuru: string;
  outcome: FileOutcome;
  /** UYAP'ın ağaçta yazdığı toplam evrak sayısı (yazmıyorsa 0). */
  declared: number;
  /** Ağaçta bulunan evrak sayısı. */
  found: number;
  /** Son doğrulamada sunucuda kayıtlı olan, ağaçtaki evrak sayısı. */
  stored: number;
  /** Bu çalışmada JurisAI'ya gönderilen evrak sayısı. */
  sent: number;
  /** Son doğrulamada sunucuda bulunmayan evrak sayısı. */
  missing: number;
  /** Kaç kez çekim denendi. */
  pulls: number;
  /** Kullanıcıya gösterilecek kısa nedenler (en çok 6). */
  problems: string[];
  /**
   * UYAP'ın "Evrak UYAP sistemine yüklenmemiş" dediği evraklar: içerik UYAP'ın kendisinde yok, aktarılamaz. `found` ve
   * `missing` bunları içermez (eksik sayılmaz); ayrıca gösterilir.
   */
  absent?: number;
  /** Bu dosyada harcanan süre (saniye): ağaç okuma + doğrulama, evrak aktarımı, dosya bilgileri. Hız ölçümü içindir. */
  timing?: { tree: number; pull: number; detail: number };
  /**
   * Evrak dışı bilgilerin (dosya bilgileri, dosya hesabı, taraflar, safahat, tahsilat/reddiyat) okunması. Evrak sonucunu etkilemez:
   * "complete": her sekme UYAP'ın sayılarıyla tam okundu; "partial": okundu ama bir tablo eksik; "failed": okunamadı;
   * "skipped": istenmedi.
   */
  detail?: {
    state: "complete" | "partial" | "failed" | "skipped";
    tabs: number;
    problems: string[];
    saved: boolean;
    data?: DosyaDetail;
  };
  /**
   * Dosya penceresinin kendi yazdığı esas no ve birim. Evraklar JurisAI'a bu kimlikle yüklenir; sunucudaki dava kaydı
   * da bununla bulunur (liste satırındaki yazım farklı olabilir).
   */
  who?: { esas: string; birim: string };
}

export interface SyncBridge {
  startTree(
    key: string,
    yargiTuru: string,
    tabId?: number,
  ): Promise<BridgeReply<{ jobId: string; tabId: number }>>;
  startDetail(
    key: string,
    yargiTuru: string,
    tabId?: number,
  ): Promise<BridgeReply<{ jobId: string; tabId: number }>>;
  startPull(
    tabId: number,
    ids: string[],
  ): Promise<BridgeReply<{ jobId: string; total: number; tabId: number }>>;
  wait(
    tabId: number,
    jobId: string,
    options: WaitOptions,
  ): Promise<{ ok: true; status: JobStatus } | BridgeFailure>;
  stop(tabId: number, jobId: string): Promise<unknown>;
  recoverRead?(tabId: number, jobId: string): Promise<BridgeReply<{ tabId: number }>>;
  /** UYAP dosya listesini yeniden okur (sayfa yenilendiyse satır anahtarları değişir); okunamazsa null. */
  relist?(): Promise<BridgeDosya[] | null>;
  sleep(ms: number): Promise<void>;
}

export const defaultBridge: SyncBridge = {
  startTree: (key, yargiTuru, tabId) => startTreeJob(key, yargiTuru, tabId),
  startDetail: (key, yargiTuru, tabId) => startDetailJob(key, yargiTuru, tabId),
  recoverRead: recoverReadJob,
  relist: async () => {
    const listed = await listUyapDosyalari();
    return listed.ok ? listed.liste.items : null;
  },
  startPull: (tabId, ids) => startPullJob(tabId, ids, "upload"),
  wait: (tabId, jobId, options) => waitForJob(tabId, jobId, options),
  stop: (tabId, jobId) => stopJob(tabId, jobId),
  sleep: (ms) => steadySleep(ms),
};

/** Oturum ya da UYAP sekmesi kaybolduysa kalan dosyalar denenmez: tekrar denemek de başarısız olur. */
export const FATAL_CODES = new Set([
  "no_uyap_tab",
  "login_required",
  "unknown_job",
  "no_content",
  "pairing_rejected",
  "destination_unavailable",
  "uyap_account_mismatch",
  "no_list",
  "idle",
]);

export const MAX_PULLS_PER_FILE = 3;
/** Eksik evrak yokken ağaç tutarsız çıkarsa ağacın kaç kez yeniden okunacağı. */
export const MAX_REREADS = 2;
/** UYAP "bu dosyada evrak yok" derse, kabul etmeden önce ağacın kaç kez daha okunacağı. */
export const EMPTY_CONFIRM_READS = 1;
const BUSY_RETRY_MS = 8000;
const BUSY_MAX_TRIES = 60;
const TREE_WAIT_MS = 45 * 60 * 1000;
const PULL_WAIT_MS = 4 * 60 * 60 * 1000;
const DETAIL_WAIT_MS = 30 * 60 * 1000;
const FILE_PAUSE_MS = 1500;
/** Üst üste hatadan sonra koşu bırakılmadan önce kaç kez beklenip yeniden denenir ve her seferinde ne kadar beklenir. */
const HEAL_ATTEMPTS = 3;
const HEAL_WAIT_MS = 60000;
/**
 * Oturum kapanınca koşu durmaz: yeniden giriş bu kadar süre beklenir (yoklama aralığı × deneme sayısı = 3 saat). UYAP oturumu
 * aktarım sürerken de ~1 saatte kapanıyor (ölçüldü); 30 dk beklemek, kullanıcı başında değilken 2 saatlik koşuyu durdurdu
 * (2026-10-17).
 */
const LOGIN_POLL_MS = 20000;
const LOGIN_WAIT_ATTEMPTS = 540;
export const LOGIN_WAIT_PHASE =
  "UYAP oturumu kapanmış görünüyor: UYAP sekmesinde yeniden giriş yapın. Giriş yapınca aktarım kaldığı dosyadan kendiliğinden devam edecek (3 saate kadar beklenir).";
const MAX_CONSECUTIVE_FAILURES = 3;
const MAX_PROBLEMS = 6;
export const MAX_READ_RETRIES = 2;
const TRANSIENT_READ_CODES = new Set(["query_failed", "no_tree", "open_failed"]);
const RECOVERABLE_READ_CODES = new Set([...TRANSIENT_READ_CODES, "cannot_close"]);

export function blankReport(dosya: BridgeDosya): FileReport {
  return {
    key: dosya.key,
    esas: dosya.esas,
    birim: dosya.birim,
    yargiTuru: dosya.yargiTuru,
    outcome: "pending",
    declared: 0,
    found: 0,
    stored: 0,
    sent: 0,
    missing: 0,
    pulls: 0,
    problems: [],
  };
}

/** Ağacın kendi tutarlılığı: bir şey açılamadıysa ya da sayılar uyuşmuyorsa nedenleri; sorun yoksa boş liste. */
export function treeProblems(tree: TreeResult): string[] {
  const problems: string[] = [];
  const counts = tree.counts;
  if (!counts.matches && !counts.explained) {
    problems.push(
      `UYAP ${counts.declaredTotal} evrak yazıyor, ağaçta ${counts.foundTotal} bulundu.`,
    );
    for (const line of counts.gapList.slice(0, 3)) problems.push(line);
  }
  if (counts.withoutId > 0) problems.push(`${counts.withoutId} evrakın kimliği okunamadı.`);
  if (counts.unstableId > 0)
    problems.push(
      `${counts.unstableId} evrakın kalıcı kimliği çıkarılamadı (UYAP her oturumda değiştiriyor): bu evraklar için eksiksizlik doğrulanamaz.`,
    );
  if (counts.unopened > 0) problems.push(`${counts.unopened} klasör açılamadı.`);
  if (counts.emptyOpened > 0) problems.push(`${counts.emptyOpened} klasör açıldı ama boş geldi.`);
  if (!tree.knownChecked) problems.push("JurisAI'da kayıtlı evraklar sunucudan doğrulanamadı.");
  return problems;
}

/** Ağaçtaki evraklardan sunucuda kayıtlı olmayanların kimlikleri (ağaç sırasıyla). */
export function missingIds(tree: TreeResult): string[] {
  const have = new Set(tree.known);
  return tree.items.filter((item) => !have.has(item.id)).map((item) => item.id);
}

const addProblem = (report: FileReport, message: string) => {
  const text = message.trim();
  if (text && !report.problems.includes(text) && report.problems.length < MAX_PROBLEMS)
    report.problems.push(text);
};

interface ReadTree {
  tree?: TreeResult;
  failure?: BridgeFailure;
  tabId?: number;
  jobId?: string;
}

async function readTreeOnce(
  dosya: BridgeDosya,
  bridge: SyncBridge,
  signal: AbortSignal | undefined,
  onPhase: (text: string) => void,
  tabId?: number,
): Promise<ReadTree> {
  let started: BridgeReply<{ jobId: string; tabId: number }> | undefined;
  for (let attempt = 0; attempt < BUSY_MAX_TRIES; attempt += 1) {
    if (signal?.aborted) return { failure: { ok: false, code: "aborted", error: "İptal edildi." } };
    started = await bridge.startTree(dosya.key, dosya.yargiTuru, tabId);
    if (started.ok || started.code !== "busy") break;
    onPhase("UYAP başka bir işi bitirmeyi bekliyor");
    await bridge.sleep(BUSY_RETRY_MS);
  }
  if (!started || !started.ok)
    return { failure: started ?? { ok: false, error: "Evrak ağacı başlatılamadı." } };
  const finished = await bridge.wait(started.tabId, started.jobId, {
    withTree: true,
    signal,
    maxMs: TREE_WAIT_MS,
    onUpdate: (status) => onPhase(status.job.phase || "Evrak ağacı okunuyor"),
  });
  if (!finished.ok) {
    // Zaman aşımı/iptalde eski iş sürerken yeni bir iş başlatma.
    await bridge.stop(started.tabId, started.jobId).catch(() => undefined);
    return { failure: finished, tabId: started.tabId };
  }
  const { status } = finished;
  if (status.job.state === "error" || !status.tree)
    return {
      failure: {
        ok: false,
        code: status.job.code,
        error: status.job.error || "Evrak ağacı okunamadı.",
      },
      tabId: started.tabId,
      jobId: started.jobId,
    };
  return { tree: status.tree, tabId: started.tabId };
}

async function readTree(
  dosya: BridgeDosya,
  bridge: SyncBridge,
  signal: AbortSignal | undefined,
  onPhase: (text: string) => void,
  budget: { remaining: number },
  pinnedTabId?: number,
): Promise<ReadTree> {
  let recovered = false;
  for (let attempt = 0; ; attempt += 1) {
    const result = await readTreeOnce(dosya, bridge, signal, onPhase, pinnedTabId);
    pinnedTabId = result.tabId ?? pinnedTabId;
    if (
      !signal?.aborted &&
      result.failure?.code &&
      RECOVERABLE_READ_CODES.has(result.failure.code) &&
      (attempt >= MAX_READ_RETRIES || !TRANSIENT_READ_CODES.has(result.failure.code)) &&
      !recovered &&
      budget.remaining > 0 &&
      bridge.recoverRead &&
      result.tabId !== undefined &&
      result.jobId
    ) {
      recovered = true;
      budget.remaining -= 1;
      onPhase("Takılan UYAP sayfası güvenli biçimde toparlanıyor");
      const recovery = await bridge.recoverRead(result.tabId, result.jobId);
      if (signal?.aborted)
        return { failure: { ok: false, code: "aborted", error: "İptal edildi." } };
      if (!recovery.ok) return { ...result, failure: recovery };
      // A reload is not success: reopen the same case on the same tab and prove its tree again.
      return readTreeOnce(dosya, bridge, signal, onPhase, result.tabId);
    }
    if (
      signal?.aborted ||
      !result.failure?.code ||
      !TRANSIENT_READ_CODES.has(result.failure.code) ||
      attempt >= MAX_READ_RETRIES
    )
      return result;
    // Yalnız salt okunur sorgu tekrarlanır; oturum kaybı, kimlik/liste değişimi ve yetki hataları tekrar edilmez.
    onPhase(`UYAP geçici okuma hatası; yeniden denenecek (${attempt + 1}/${MAX_READ_RETRIES})`);
    await bridge.sleep(4000 * (attempt + 1));
  }
}

interface PullResult {
  sent: number;
  errors: string[];
  failure?: BridgeFailure;
  /** UYAP'ta içeriği olmayan evrakların kimlikleri. */
  absent: string[];
}

/** Eklentinin bir aktarım işinde kabul ettiği en çok evrak; büyük dosya bu boyutta parçalarla aktarılır. */
export const PULL_BATCH = 5000;

async function pullIds(
  tabId: number,
  ids: string[],
  bridge: SyncBridge,
  signal: AbortSignal | undefined,
  onPhase: (text: string) => void,
): Promise<PullResult> {
  // Büyük dosya (canlıda 6 000-20 000+ evrak, 2026-10-17) eklentinin tek iş sınırına (5 000) parçalanır; önceden tamamı
  // reddediliyor ve dosyadan tek evrak inmiyordu. Ölümcül hata (oturum, hedef) kalan parçaları durdurur.
  if (ids.length > PULL_BATCH) {
    const total: PullResult = { sent: 0, errors: [], absent: [] };
    for (let start = 0; start < ids.length && !signal?.aborted; start += PULL_BATCH) {
      const part = await pullIds(tabId, ids.slice(start, start + PULL_BATCH), bridge, signal, (text) =>
        onPhase(`${text} (parça ${Math.floor(start / PULL_BATCH) + 1}/${Math.ceil(ids.length / PULL_BATCH)})`),
      );
      total.sent += part.sent;
      total.absent.push(...part.absent);
      for (const error of part.errors) if (total.errors.length < 5 && !total.errors.includes(error)) total.errors.push(error);
      if (part.failure) {
        total.failure = part.failure;
        if (part.failure.code && FATAL_CODES.has(part.failure.code)) break;
      }
    }
    return total;
  }
  const started = await bridge.startPull(tabId, ids);
  if (!started.ok) return { sent: 0, errors: [], failure: started, absent: [] };
  const finished = await bridge.wait(tabId, started.jobId, {
    signal,
    maxMs: PULL_WAIT_MS,
    onUpdate: (status) => {
      if (status.run) onPhase(`Evrak aktarılıyor: ${status.run.done}/${status.run.total}`);
    },
  });
  if (!finished.ok) {
    // Zaman aşımında da arka plandaki aktarım işi durmalı; yeni doğrulama/çekim onunla çakışmasın.
    await bridge.stop(tabId, started.jobId).catch(() => undefined);
    return { sent: 0, errors: [], failure: finished, absent: [] };
  }
  const { job, run } = finished.status;
  const absent = run?.stats?.absent ?? [];
  if (job.state === "error")
    return {
      sent: run?.stats?.sent ?? 0,
      errors: run?.stats?.errors ?? [],
      failure: { ok: false, code: job.code, error: job.error || "Aktarım başarısız." },
      absent,
    };
  return { sent: run?.stats?.sent ?? 0, errors: run?.stats?.errors ?? [], absent };
}

export interface SyncOptions {
  bridge?: SyncBridge;
  signal?: AbortSignal;
  /** Listeyi veren sekmeye sabitlenir; başka bir açık UYAP oturumuna geçilmez. */
  tabId?: number;
  /**
   * false ise hiçbir evrak aktarılmaz: yalnız UYAP ağacı okunur ve sunucudaki kayıtla karşılaştırılır ("yalnız denetle").
   * Eksik evrak bulunursa dosya "eksik" raporlanır; belge yüklenmez. Denetim raporu ve okunmuş dosya bilgileri kaydedilebilir.
   */
  pull?: boolean;
  /** false ise evrak dışı dosya bilgileri okunmaz (varsayılan: okunur; evraklar bittikten sonra, salt okunur). */
  detail?: boolean;
  /** Koşunun başladığı UYAP kişisi (sunucu bu hesaba bağlı olduğunu doğruladı). Her dosyada aynı kişi aranır. */
  identity?: UyapIdentity | null;
  /** Bir dosya okunamadığında hata koduyla çağrılır (sayfa tanınmadıysa yapı özeti kaydetmek için; içerik taşımaz). */
  onProblem?: (code: string) => void;
  /** Bir dosyanın bilgileri okununca çağrılır (sunucuya kaydetmek için). Hata fırlatırsa dosya raporuna "kaydedilemedi" yazılır. */
  onDetail?: (
    detail: DosyaDetail,
    report: FileReport,
  ) => Promise<void | { complete: boolean }> | void | { complete: boolean };
  /** Her adımda çağrılır: hangi dosyada, ne yapıldığı ve o ana kadarki dosya raporu. */
  onProgress?: (event: { index: number; total: number; phase: string; report: FileReport }) => void;
  /** Awaited after each file, including failures. Remaining files stay explicitly pending. */
  onCheckpoint?: (run: SyncRun) => Promise<void>;
  /** Shared bounded budget: at most two safe read-only page recoveries in a full run. */
  recoveryBudget?: { remaining: number };
}

/**
 * Tek dosya: evrakları aktar ve doğrula (ağacı oku → eksikleri çek → ağacı yeniden oku → gerekirse tekrarla), sonra evrak dışı
 * dosya bilgilerini (taraflar, safahat, dosya hesabı, tahsilat/reddiyat…) salt okunur oku. İkinci adım evrak sonucunu değiştirmez.
 */
export async function syncDosya(
  dosya: BridgeDosya,
  options: SyncOptions & { index?: number; total?: number } = {},
): Promise<{ report: FileReport; fatal?: BridgeFailure; code?: string }> {
  options = { ...options, recoveryBudget: options.recoveryBudget ?? { remaining: 1 } };
  const result = await syncEvraks(dosya, options);
  if (options.detail === false) {
    result.report.detail = { state: "skipped", tabs: 0, problems: [], saved: false };
    return result;
  }
  if (result.fatal || options.signal?.aborted) return result;
  const detailStartedAt = Date.now();
  const fatal = await readDetail(dosya, result.report, options, result.tabId ?? options.tabId);
  if (result.report.timing) result.report.timing.detail = Math.round((Date.now() - detailStartedAt) / 100) / 10;
  return fatal ? { report: result.report, fatal } : result;
}

/** Evrak dışı bilgileri okur ve (verildiyse) `onDetail` ile kaydeder. Oturum/sekme kaybında koşuyu durduracak hatayı döndürür. */
async function readDetail(
  dosya: BridgeDosya,
  report: FileReport,
  options: SyncOptions & { index?: number; total?: number },
  pinnedTabId?: number,
): Promise<BridgeFailure | undefined> {
  const bridge = options.bridge ?? defaultBridge;
  const emit = (phase: string) =>
    options.onProgress?.({
      index: options.index ?? 0,
      total: options.total ?? 1,
      phase,
      report: { ...report, problems: [...report.problems] },
    });
  const failed = (message: string, failure?: BridgeFailure): BridgeFailure | undefined => {
    report.detail = { state: "failed", tabs: 0, problems: [message], saved: false };
    return failure?.code && FATAL_CODES.has(failure.code) ? failure : undefined;
  };
  emit("Dosya bilgileri okunuyor");
  let started: BridgeReply<{ jobId: string; tabId: number }> | undefined;
  for (let attempt = 0; attempt < BUSY_MAX_TRIES; attempt += 1) {
    if (options.signal?.aborted) return failed("İptal edildi.");
    started = await bridge.startDetail(dosya.key, dosya.yargiTuru, pinnedTabId);
    if (started.ok || started.code !== "busy") break;
    emit("UYAP başka bir işi bitirmeyi bekliyor");
    await bridge.sleep(BUSY_RETRY_MS);
  }
  if (!started || !started.ok)
    return failed(started?.error ?? "Dosya bilgileri başlatılamadı.", started);
  const finished = await bridge.wait(started.tabId, started.jobId, {
    withDetail: true,
    signal: options.signal,
    maxMs: DETAIL_WAIT_MS,
    onUpdate: (status) => emit(status.job.phase || "Dosya bilgileri okunuyor"),
  });
  if (!finished.ok) {
    await bridge.stop(started.tabId, started.jobId).catch(() => undefined);
    return failed(finished.error, finished);
  }
  const { status } = finished;
  if (
    status.job.state === "error" &&
    status.job.code &&
    RECOVERABLE_READ_CODES.has(status.job.code) &&
    !options.signal?.aborted &&
    bridge.recoverRead &&
    (options.recoveryBudget?.remaining ?? 0) > 0
  ) {
    options.recoveryBudget!.remaining -= 1;
    emit("Dosya bilgileri için UYAP sayfası güvenli biçimde toparlanıyor");
    const recovery = await bridge.recoverRead(started.tabId, started.jobId);
    if (options.signal?.aborted) return failed("İptal edildi.");
    if (!recovery.ok) return failed(recovery.error, recovery);
    return readDetail(dosya, report, options, started.tabId);
  }
  if (status.job.state === "error" || !status.detail)
    return failed(status.job.error || "Dosya bilgileri okunamadı.", {
      ok: false,
      code: status.job.code,
      error: status.job.error || "",
    });
  const data = status.detail;
  // Hiçbir bilgi sekmesi bulunamadıysa (UYAP düzeni değişmiş olabilir) bu "eksik okundu" değil "okunamadı"dır; hiçbir şey kaydedilmez.
  if (!data.tabs.length) return failed("Dosya penceresinde okunabilir bilgi sekmesi bulunamadı.");
  const problems = [...data.problems];
  let saved = false;
  let complete = data.complete;
  if (options.onDetail) {
    try {
      const verified = await options.onDetail(data, report);
      saved = true;
      if (verified && !verified.complete) {
        complete = false;
        problems.push("Sunucu dosya bilgilerinin eksiksizliğini doğrulamadı.");
      }
    } catch (cause) {
      problems.push(
        `Dosya bilgileri JurisAI'a kaydedilemedi: ${cause instanceof Error ? cause.message : "bilinmeyen hata"}`,
      );
    }
  }
  report.detail = {
    state: complete ? "complete" : "partial",
    tabs: data.tabs.length,
    problems: problems.slice(0, MAX_PROBLEMS),
    saved,
    data,
  };
  return undefined;
}

/** Evrakları aktarır ve doğrular: ağacı oku → eksikleri çek → ağacı yeniden oku (sunucu doğrulaması) → gerekirse tekrarla. */
async function syncEvraks(
  dosya: BridgeDosya,
  options: SyncOptions & { index?: number; total?: number } = {},
): Promise<{ report: FileReport; fatal?: BridgeFailure; tabId?: number }> {
  const bridge = options.bridge ?? defaultBridge;
  const report = blankReport(dosya);
  const emit = (phase: string) =>
    options.onProgress?.({
      index: options.index ?? 0,
      total: options.total ?? 1,
      phase,
      report: { ...report, problems: [...report.problems] },
    });
  let pinnedTabId = options.tabId;
  const fail = (
    failure: BridgeFailure,
  ): { report: FileReport; fatal?: BridgeFailure; tabId?: number; code?: string } => {
    report.outcome = "failed";
    addProblem(report, failure.error);
    return {
      report,
      fatal: failure.code && FATAL_CODES.has(failure.code) ? failure : undefined,
      tabId: pinnedTabId,
      code: failure.code,
    };
  };

  let lastTree: TreeResult | undefined;
  let rereads = 0;
  let emptyReads = 0;
  const absentIds = new Set<string>(); // UYAP'ta içeriği olmayan evraklar: bu dosyada yeniden istenmez, eksik sayılmaz
  let lastPullSent = -1; // son aktarımda inen evrak; hiç inmediyse dosya hemen yeniden denenmez (koşu sonunda bir tur daha)
  const timing = (report.timing = { tree: 0, pull: 0, detail: 0 });
  const seconds = (startedAt: number) => Math.round((Date.now() - startedAt) / 100) / 10;
  for (;;) {
    emit(
      report.pulls === 0 && rereads === 0
        ? "Evrak ağacı okunuyor"
        : "Aktarım sunucudan doğrulanıyor",
    );
    const readStartedAt = Date.now();
    const read = await readTree(
      dosya,
      bridge,
      options.signal,
      emit,
      options.recoveryBudget ?? { remaining: 1 },
      pinnedTabId,
    );
    timing.tree += seconds(readStartedAt);
    pinnedTabId = read.tabId ?? pinnedTabId;
    if (!lastTree && read.failure?.code === "empty_tree") {
      // UYAP "dosyaya ait evrak bilgisi bulunamadı" diyor (ör. kapatılmış eski icra dosyası): hata değil, evraksız dosya.
      // Geçici bir boş yanıt "evrak yok" diye yazılmasın: aynı yanıt ikinci okumada da gelirse kabul edilir.
      if (emptyReads < EMPTY_CONFIRM_READS) {
        emptyReads += 1;
        continue;
      }
      report.outcome = "empty";
      return { report, tabId: pinnedTabId };
    }
    if (!read.tree || read.tabId === undefined) {
      // Son doğrulama okunamadıysa önceki ağaçtaki durum kesin değildir: "eksiksiz" denemez.
      if (lastTree) addProblem(report, "Aktarım sonrası doğrulama yapılamadı.");
      return fail(read.failure ?? { ok: false, error: "Evrak ağacı okunamadı." });
    }
    lastTree = read.tree;
    // Dosyalar karışmasın: koşu, başladığı UYAP kişisiyle sürer. Aktarım ortasında başka biri UYAP'a girdiyse ya da sunucu
    // bu kişiyi hesaba bağlı saymadıysa hiçbir evrak/dosya bilgisi kaydedilmeden durulur (kullanıcı kararı 2026-10-16).
    if (options.identity && (lastTree.accountRefused || !sameIdentity(options.identity, lastTree.identity))) {
      report.found = 0;
      return fail({
        ok: false,
        code: "uyap_account_mismatch",
        error:
          lastTree.accountRefused ||
          `UYAP'ta giriş yapan kişi değişti (koşu ${options.identity.display} ile başlamıştı); dosyalar karışmasın diye aktarım durduruldu.`,
      });
    }
    if (lastTree.who.esas && lastTree.who.birim) report.who = { ...lastTree.who };
    const todo = missingIds(lastTree).filter((id) => !absentIds.has(id));
    const absentHere = lastTree.items.filter((item) => absentIds.has(item.id)).length;
    report.declared = lastTree.counts.declaredTotal;
    report.found = lastTree.items.length - absentHere;
    report.missing = todo.length;
    report.stored = report.found - todo.length;
    report.absent = absentHere;
    const structural = treeProblems(lastTree);

    if (todo.length === 0 && structural.length === 0) break;
    // Bir aktarım hiç evrak indiremediyse aynısını hemen tekrarlamak yalnız süre yer (canlıda 3 × ~4,5 dk, 2026-10-17).
    if (todo.length > 0 && options.pull !== false && report.pulls < MAX_PULLS_PER_FILE && lastPullSent !== 0) {
      report.pulls += 1;
      emit(`Evrak aktarılıyor: ${todo.length} evrak`);
      const pullStartedAt = Date.now();
      const pulled = await pullIds(read.tabId, todo, bridge, options.signal, emit);
      timing.pull += seconds(pullStartedAt);
      report.sent += pulled.sent;
      // Tamamlanan ama hiç evrak indiremeyen aktarım tekrarlanmaz; zaman aşımı/iş kaybı gibi yarım kalan aktarım tekrarlanır.
      lastPullSent = pulled.failure ? -1 : pulled.sent + pulled.absent.length;
      for (const id of pulled.absent) absentIds.add(id);
      for (const message of pulled.errors) addProblem(report, message);
      if (pulled.failure) {
        addProblem(report, pulled.failure.error);
        if (pulled.failure.code && FATAL_CODES.has(pulled.failure.code)) {
          report.outcome = "failed";
          return { report, fatal: pulled.failure };
        }
        // Aktarım işi hata verdi ama bir kısmı gitmiş olabilir: doğrulama turu sunucudaki gerçeği gösterir.
      }
      continue;
    }
    // Eksik evrak yok ama ağaç tutarsız (açılamayan klasör, sunucu doğrulaması yok…): geçici UYAP hatası olabilir, yeniden oku.
    if (todo.length === 0 && rereads < MAX_REREADS) {
      rereads += 1;
      continue;
    }
    break;
  }

  const finalTree = lastTree as TreeResult; // döngü ancak bir ağaç okunduktan sonra buraya çıkar
  const structural = treeProblems(finalTree);
  for (const problem of structural) addProblem(report, problem);
  if (report.absent) {
    // Yalnız UYAP'ın içerik vermediği evraklar kaldıysa önceki denemelerin indirme hata satırları artık sorun değildir.
    report.problems = report.problems.filter((line) => !/UYAP bu evrakın içeriğini vermiyor|sistemine yüklenmemiş/i.test(line));
    addProblem(report, `${report.absent} evrakın içeriği UYAP'ın kendisinde yok ("sisteme yüklenmemiş"); aktarılamaz, eksik sayılmadı.`);
  }
  if (report.missing > 0)
    addProblem(report, `${report.missing} evrak JurisAI'da kayıtlı görünmüyor.`);
  report.outcome = report.missing === 0 && structural.length === 0 ? "complete" : "incomplete";
  return { report, tabId: pinnedTabId };
}

export interface SyncSummary {
  files: number;
  complete: number;
  /** UYAP'ta evrakı bulunmayan dosyalar (eksik sayılmaz). */
  empty: number;
  incomplete: number;
  failed: number;
  pending: number;
  found: number;
  stored: number;
  missing: number;
  sent: number;
  /** Evrak dışı dosya bilgileri: tam okunan / bir tablosu eksik kalan / okunamayan dosya sayısı ve JurisAI'a kaydedilenler. */
  detailComplete: number;
  detailPartial: number;
  detailFailed: number;
  detailSaved: number;
  /** Tüm dosyalar eksiksiz mi: her dosya "complete" ya da UYAP'ta evraksız ("empty") ise true. */
  allComplete: boolean;
}

export function summarize(reports: FileReport[]): SyncSummary {
  const count = (outcome: FileOutcome) =>
    reports.filter((report) => report.outcome === outcome).length;
  const sum = (pick: (report: FileReport) => number) =>
    reports.reduce((total, report) => total + pick(report), 0);
  const complete = count("complete");
  const empty = count("empty");
  return {
    files: reports.length,
    complete,
    empty,
    incomplete: count("incomplete"),
    failed: count("failed"),
    pending: count("pending"),
    found: sum((report) => report.found),
    stored: sum((report) => report.stored),
    missing: sum((report) => report.missing),
    sent: sum((report) => report.sent),
    detailComplete: reports.filter((report) => report.detail?.state === "complete").length,
    detailPartial: reports.filter((report) => report.detail?.state === "partial").length,
    detailFailed: reports.filter((report) => report.detail?.state === "failed").length,
    detailSaved: reports.filter((report) => report.detail?.saved).length,
    allComplete: reports.length > 0 && complete > 0 && complete + empty === reports.length,
  };
}

export interface SyncRun {
  reports: FileReport[];
  summary: SyncSummary;
  /** Oturum/sekme kaybı gibi koşuyu durduran neden; kalan dosyalar "bekliyor" kalır. */
  stoppedBecause?: string;
  aborted: boolean;
}

/** Evrak sonucu ve dosya bilgisi ayrı kanıtlardır: biri eksikse genel başarı yazılmaz. */
export function fullyVerified(report: FileReport): boolean {
  return (
    (report.outcome === "complete" || report.outcome === "empty") &&
    report.detail?.state === "complete" &&
    report.detail.saved
  );
}

/** Sunucudaki son doğrulama kaydının "çekilmeyen dosyalar" listesi için gereken alanları. */
export interface VerifiedFile {
  esas: string | null;
  birim: string | null;
  complete: boolean;
  missing_count?: number;
}

export interface UnpulledFile {
  key: string;
  esas: string;
  birim: string;
  /** Neden çekilmemiş sayıldığı: hiç aktarılmamış ya da son doğrulamada eksik evrak var. */
  reason: string;
}

// Sunucudaki dosya kimliği kuralıyla aynı (api/uyap_cases.py): esas no boşluksuz, birim "İ/ı" katlanmış ve küçük harf.
const fileIdentity = (esas: string | null, birim: string | null): string =>
  `${(esas ?? "").replace(/\s+/g, "")}|${(birim ?? "").normalize("NFC").replace(/İ/g, "I").replace(/ı/g, "i").toLowerCase().replace(/\s+/g, " ").trim()}`;

/**
 * UYAP listesindeki dosyalardan JurisAI'a eksiksiz aktarıldığı doğrulanMAMIŞ olanlar: hiç doğrulama kaydı olmayan ya da son
 * doğrulamada eksiği kalan dosyalar. Yalnız sunucudaki kayda bakar; UYAP'ı okumaz, bu yüzden anında hesaplanır. Eksiksiz
 * doğrulanmış bir dosyaya sonradan UYAP'ta yeni evrak eklendiyse burada görünmez (bunu yalnız dosyayı yeniden okumak gösterir).
 */
export function unpulledFiles(items: BridgeDosya[], verified: VerifiedFile[]): UnpulledFile[] {
  const records = new Map(verified.map((row) => [fileIdentity(row.esas, row.birim), row]));
  const out: UnpulledFile[] = [];
  for (const item of items) {
    const record = records.get(fileIdentity(item.esas, item.birim));
    if (record?.complete) continue;
    const missing = record?.missing_count ?? 0;
    out.push({
      key: item.key,
      esas: item.esas,
      birim: item.birim,
      reason: !record ? "Hiç aktarılmamış" : missing > 0 ? `${missing} evrak eksik` : "Aktarım doğrulanamadı",
    });
  }
  return out;
}

export function retryKeysFor(reports: FileReport[]): Set<string> {
  return new Set(reports.filter((report) => !fullyVerified(report)).map((report) => report.key));
}

/**
 * Dosyaları sırayla işler. Tek dosyanın hatası diğerlerini durdurmaz; ama oturum kaybı ya da üst üste
 * `MAX_CONSECUTIVE_FAILURES` dosyanın başarısız olması koşuyu durdurur (kalanlar "bekliyor" olarak raporlanır).
 * `only` verilirse yalnız o anahtarlı dosyalar işlenir (ör. "eksik olanları yeniden dene").
 */
export async function syncAll(
  dosyalar: BridgeDosya[],
  options: SyncOptions & { only?: Set<string> } = {},
): Promise<SyncRun> {
  const bridge = options.bridge ?? defaultBridge;
  const list = options.only ? dosyalar.filter((dosya) => options.only?.has(dosya.key)) : dosyalar;
  const recoveryBudget = options.recoveryBudget ?? { remaining: 2 };
  const reports = list.map(blankReport);
  let stoppedBecause: string | undefined;
  let aborted = false;
  let consecutiveFailures = 0;
  // UYAP sayfası yenilenince (oturum tazeleme, toparlanma) listedeki satır anahtarları geçersizleşir ve kalan her dosya
  // "liste değişmiş" hatası alır; gerçek aktarımda koşu 6. dosyadan sonra böyle durdu (2026-10-12). Liste bir koşuda en çok
  // iki kez yeniden okunur, dosyalar esas no + birim + yargı türüyle yeni anahtarlarına eşlenir ve dosya yeniden denenir.
  // Raporlar özgün anahtarı taşımaya devam eder (sayfa satırları onunla eşler).
  const liveKey = new Map<string, string>();
  const identity = (dosya: BridgeDosya) => `${dosya.yargiTuru}|${dosya.esas.replace(/\s+/g, "")}|${dosya.birim.trim()}`;
  let relists = 2;
  let heals = HEAL_ATTEMPTS;
  const run = async (index: number) => {
    const dosya = list[index];
    const result = await syncDosya({ ...dosya, key: liveKey.get(dosya.key) ?? dosya.key }, {
      ...options,
      bridge,
      recoveryBudget,
      index,
      total: list.length,
    });
    result.report.key = dosya.key;
    return result;
  };
  const remap = (fresh: BridgeDosya[]) => {
    const byIdentity = new Map(fresh.map((dosya) => [identity(dosya), dosya.key]));
    for (const dosya of list) {
      const key = byIdentity.get(identity(dosya));
      if (key) liveKey.set(dosya.key, key);
    }
  };
  const relist = async (): Promise<boolean> => {
    if (!bridge.relist || relists <= 0 || options.signal?.aborted) return false;
    relists -= 1;
    const fresh = await bridge.relist();
    if (!fresh) return false;
    remap(fresh);
    return true;
  };
  // UYAP oturumu aktarım sürerken kapanabilir (gerçek sınamalarda 33. ve 65. dakikada kapandı; 2026-10-12). Koşu bu durumda
  // bırakılmaz: kullanıcıdan yeniden giriş istenir ve dosya listesi yeniden okunabilene kadar beklenir; okununca kalan
  // dosyalar yeni anahtarlarıyla sürer. Araç kullanıcı adına giriş yapmaz. Süre dolarsa ya da kullanıcı durdurursa durur.
  const waitForSession = async (index: number): Promise<boolean> => {
    if (!bridge.relist) return false;
    for (let attempt = 0; attempt < LOGIN_WAIT_ATTEMPTS; attempt += 1) {
      if (options.signal?.aborted) return false;
      options.onProgress?.({ index, total: list.length, phase: LOGIN_WAIT_PHASE, report: reports[index] });
      await bridge.sleep(LOGIN_POLL_MS);
      if (options.signal?.aborted) return false;
      const fresh = await bridge.relist();
      if (fresh && fresh.length) {
        remap(fresh);
        return true;
      }
    }
    return false;
  };
  for (let index = 0; index < list.length; index += 1) {
    if (options.signal?.aborted) {
      aborted = true;
      break;
    }
    let result = await run(index);
    if (result.report.outcome === "failed" && !result.fatal && (result.code === "stale" || result.code === "recovery_failed" || result.code === "no_list")) {
      if (await relist()) result = await run(index);
    }
    reports[index] = result.report;
    if (result.report.outcome === "failed" && result.code) options.onProblem?.(result.code);
    await options.onCheckpoint?.({
      reports: [...reports],
      summary: summarize(reports),
      aborted: !!options.signal?.aborted,
    });
    if (options.signal?.aborted) {
      aborted = true;
      break;
    }
    if (result.fatal) {
      // JurisAI hedefinin/anahtarının hatası UYAP'a tekrar girişle düzelmez.
      // Kaydedilmiş ilerlemeyi koru; UYAP'tan aynı belgeyi yeniden indirme.
      if (["pairing_rejected", "destination_unavailable", "uyap_account_mismatch"].includes(result.fatal.code || "")) {
        stoppedBecause = result.fatal.error;
        break;
      }
      // Oturum/sekme kaybı: yeniden giriş beklenir; gelirse aynı dosya baştan denenir.
      if (await waitForSession(index)) {
        reports[index] = blankReport(list[index]);
        index -= 1;
        consecutiveFailures = 0;
        continue;
      }
      stoppedBecause = result.fatal.error;
      break;
    }
    consecutiveFailures = result.report.outcome === "failed" ? consecutiveFailures + 1 : 0;
    if (consecutiveFailures >= MAX_CONSECUTIVE_FAILURES) {
      // Kendini toparlama: üst üste hata çoğu kez geçicidir (UYAP bir süre yanıt vermez, sayfa yenilenir). Koşu hemen
      // bırakılmaz: beklenir, dosya listesi yeniden okunur (oturumun açık olduğunu da bu gösterir) ve hata alan dosyalar
      // baştan denenir. Liste okunamıyorsa oturum kapanmış demektir; ancak o zaman durulur. Bir koşuda en çok
      // `HEAL_ATTEMPTS` kez; nedeni ne olursa olsun aynı yol izlenir.
      let healed = false;
      if (bridge.relist && heals > 0 && !options.signal?.aborted) {
        heals -= 1;
        options.onProgress?.({ index, total: list.length, phase: "UYAP yanıt vermiyor; bir dakika beklenip dosya listesi yeniden okunacak", report: reports[index] });
        await bridge.sleep(HEAL_WAIT_MS);
        const fresh = options.signal?.aborted ? null : await bridge.relist();
        // Liste okunamıyorsa oturum kapanmıştır: yeniden giriş beklenir.
        const back2 = fresh ? (remap(fresh), true) : await waitForSession(index);
        if (back2) {
          for (let back = index - MAX_CONSECUTIVE_FAILURES + 1; back <= index; back += 1) reports[back] = blankReport(list[back]);
          index -= MAX_CONSECUTIVE_FAILURES; // döngü artırınca hata alan ilk dosyaya döner
          consecutiveFailures = 0;
          healed = true;
        }
      }
      if (!healed) {
        stoppedBecause = `Üst üste ${MAX_CONSECUTIVE_FAILURES} dosya okunamadı; UYAP yanıt vermiyor ya da oturum kapanmış olabilir.`;
        break;
      }
      continue;
    }
    if (index < list.length - 1) await bridge.sleep(FILE_PAUSE_MS);
  }
  // Son tur: bütün dosyalar bittikten sonra evrakı eksik kalanlar bir kez daha denenir. UYAP büyük ekleri bazen dakikalarca
  // keser; aynı ek bir süre sonra çoğu kez iner (ölçüldü: 2026-10-11). Kullanıcının düğmeye yeniden basması gerekmesin.
  // Yalnız aktarım kipinde, koşu durmadıysa ve yalnız UYAP ağacı okunabilmiş ("eksik") dosyalar için; dosya bilgileri
  // yeniden okunmaz.
  if (options.pull !== false && !aborted && !stoppedBecause) {
    for (let index = 0; index < list.length; index += 1) {
      const before = reports[index];
      if (before.outcome !== "incomplete" || before.missing <= 0) continue;
      if (options.signal?.aborted) {
        aborted = true;
        break;
      }
      await bridge.sleep(FILE_PAUSE_MS);
      const result = await syncDosya({ ...list[index], key: liveKey.get(list[index].key) ?? list[index].key },
        { ...options, bridge, recoveryBudget, index, total: list.length, detail: false });
      result.report.key = list[index].key;
      if (result.fatal) {
        stoppedBecause = result.fatal.error;
        break;
      }
      // Yeni okuma yalnız daha iyiyse eskisinin yerini alır; dosya bilgisi sonucu ilk turdan korunur.
      if (result.report.outcome !== "failed" && result.report.missing <= before.missing)
        reports[index] = { ...result.report, sent: before.sent + result.report.sent, detail: before.detail };
      await options.onCheckpoint?.({ reports: [...reports], summary: summarize(reports), aborted: !!options.signal?.aborted });
    }
  }
  // Dosya bilgileri için de son tur: evrakı tamam ama bir bilgi tablosu o an yüklenmemiş dosyalar bir kez daha okunur. Gerçek
  // aktarımda (2026-10-16) iki dosyanın taraf tablosu iki denemede de gelmedi, dakikalar sonra ilk okumada tam geldi. Evrak
  // yeniden aktarılmaz (`pull: false`); yeni okuma yalnız daha iyiyse eskisinin yerini alır.
  if (options.detail !== false && !aborted && !stoppedBecause) {
    for (let index = 0; index < list.length; index += 1) {
      const before = reports[index];
      const state = before.detail?.state;
      if ((before.outcome !== "complete" && before.outcome !== "empty") || (state !== "partial" && state !== "failed")) continue;
      if (options.signal?.aborted) {
        aborted = true;
        break;
      }
      await bridge.sleep(FILE_PAUSE_MS);
      const result = await syncDosya({ ...list[index], key: liveKey.get(list[index].key) ?? list[index].key },
        { ...options, bridge, recoveryBudget, index, total: list.length, pull: false });
      result.report.key = list[index].key;
      if (result.fatal) break; // evraklar zaten doğrulandı: bu ek okuma koşuyu "durdu" diye işaretlemez
      if (result.report.detail?.state === "complete")
        reports[index] = { ...before, detail: result.report.detail };
      await options.onCheckpoint?.({ reports: [...reports], summary: summarize(reports), aborted: !!options.signal?.aborted });
    }
  }
  return { reports, summary: summarize(reports), stoppedBecause, aborted };
}

/** Raporun düz metni (panoya kopyalanır): dosya numaraları ve sayılar; evrak içeriği yoktur. */
export function reportText(run: SyncRun): string {
  const s = run.summary;
  const lines = [
    `UYAP aktarım raporu — ${s.files} dosya: ${s.complete} dosyada evraklar eksiksiz, ${s.empty} evraksız, ${s.incomplete} evrak eksik, ${s.failed} hatalı, ${s.pending} işlenmedi.`,
    `Evrak: ${s.found} bulundu, ${s.stored} JurisAI'da kayıtlı, ${s.missing} eksik, bu çalışmada ${s.sent} gönderildi.`,
    `Dosya bilgileri (taraflar, safahat, hesap…): ${s.detailComplete} eksiksiz, ${s.detailPartial} eksik, ${s.detailFailed} okunamadı; ${s.detailSaved} dosya JurisAI'a kaydedildi.`,
  ];
  const fullyChecked = run.reports.filter(fullyVerified).length;
  lines.push(
    `Evrakları ve dosya bilgileri birlikte doğrulanıp kaydedilen: ${fullyChecked}/${s.files} dosya.`,
  );
  if (s.failed || s.pending)
    lines.push(
      "Okunamayan/işlenmeyen dosyaların evrak sayısı bilinmiyor; 0 sayısı bu dosyaların boş olduğunu göstermez.",
    );
  if (run.stoppedBecause) lines.push(`Durduruldu: ${run.stoppedBecause}`);
  if (run.aborted) lines.push("Kullanıcı tarafından durduruldu.");
  const label: Record<FileOutcome, string> = {
    complete: "EVRAKLAR EKSİKSİZ",
    empty: "EVRAK YOK",
    incomplete: "EKSİK",
    failed: "HATA",
    pending: "İŞLENMEDİ",
  };
  for (const report of run.reports) {
    const counts =
      report.outcome === "pending"
        ? "evraklar denenmedi"
        : report.outcome === "failed" && !report.found
          ? "evrak sayısı okunamadı"
          : `${report.stored}/${report.found} evrak${report.declared ? ` (UYAP: ${report.declared})` : ""}`;
    const detail =
      report.detail && report.detail.state !== "skipped"
        ? ` · dosya bilgileri: ${{ complete: "eksiksiz", partial: "eksik", failed: "okunamadı" }[report.detail.state]}`
        : "";
    lines.push(
      `${label[report.outcome]} · ${report.esas || "?"} · ${report.birim} · ${counts}${detail}${report.problems.length ? ` · ${report.problems.join(" ")}` : ""}`,
    );
    for (const problem of [...new Set(report.detail?.problems ?? [])].slice(0, MAX_PROBLEMS))
      lines.push(`  Bilgi uyarısı: ${problem}`);
  }
  return lines.join("\n");
}

/* ---------- Sunucuya kayıt ----------
   Doğrulama sonucu ve UYAP listesindeki üst veri (yargı türü, dosya türü, durum, rol, açılış) dava kaydının yanına yazılır;
   sayfa kapansa da "bu dosya şu tarihte eksiksiz doğrulandı" bilgisi kalır. Sunucu "eksiksiz" bilgisini kendi evrak
   sayımıyla ayrıca denetler. İşlenmemiş ya da ağacı hiç okunamamış dosya gönderilmez (söylenecek bir sayı yoktur). */

export interface ServerSyncItem {
  esas: string;
  birim: string;
  yargi_turu: string;
  dosya_turu: string;
  durum: string;
  rol: string;
  acilis: string;
  declared: number;
  found: number;
  missing: number;
  complete: boolean;
  problems: string[];
}

export function toServerItems(reports: FileReport[], dosyalar: BridgeDosya[]): ServerSyncItem[] {
  const byKey = new Map(dosyalar.map((dosya) => [dosya.key, dosya]));
  const items: ServerSyncItem[] = [];
  for (const report of reports) {
    // Evraksız dosya da bildirilir (0 evrak, eksiksiz): yoksa her liste yenilemede "çekilmemiş" görünürdü. Dava kaydı dosya
    // bilgileri kaydedilirken açılır; kayıt yoksa sunucu satırı "no_case" diye atlar.
    if (report.outcome === "pending" || (report.outcome === "failed" && report.found === 0)) continue;
    const esas = (report.who?.esas || report.esas).trim();
    const birim = (report.who?.birim || report.birim).trim();
    if (!esas || !birim) continue;
    const dosya = byKey.get(report.key);
    items.push({
      esas: esas.slice(0, 60),
      birim: birim.slice(0, 160),
      yargi_turu: (report.yargiTuru || "").slice(0, 80),
      dosya_turu: (dosya?.tur ?? "").slice(0, 80),
      durum: (dosya?.durum ?? "").slice(0, 80),
      rol: (dosya?.role ?? "").slice(0, 60),
      acilis: (dosya?.acilis ?? "").slice(0, 40),
      declared: report.declared,
      found: report.found,
      missing: report.missing,
      complete: report.outcome === "complete" || report.outcome === "empty",
      problems: report.problems.slice(0, 6),
    });
  }
  return items;
}

export interface SavedSync {
  saved: number;
  /** Sunucunun kendi sayımıyla "eksiksiz" kabul ETMEDİĞİ, tarayıcının eksiksiz dediği dosyalar (esas · birim). */
  downgraded: string[];
  /** JurisAI'da dava kaydı bulunamayan dosyalar (ör. hiç evrakı olmayan dosya). */
  unmatched: number;
}

/** Sunucu yanıtını raporla karşılaştırır: sunucunun eksiksiz saymadığı dosyalar ayrıca gösterilir. */
export function reconcileSaved(items: ServerSyncItem[], raw: unknown): SavedSync {
  const body = raw && typeof raw === "object" ? (raw as Record<string, unknown>) : {};
  const results = Array.isArray(body.results) ? body.results : [];
  const downgraded: string[] = [];
  let unmatched = 0;
  let saved = 0;
  items.forEach((item, index) => {
    const entry = results[index];
    const row = entry && typeof entry === "object" ? (entry as Record<string, unknown>) : {};
    if (row.status !== "saved" || row.esas !== item.esas || row.birim !== item.birim)
      unmatched += 1;
    else {
      saved += 1;
      if (item.complete && row.complete !== true) downgraded.push(`${item.esas} · ${item.birim}`);
    }
  });
  return { saved, downgraded, unmatched };
}
