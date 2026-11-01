/**
 * "UYAP Dosyalarım" durumunun sayfalar arası deposu.
 *
 * Dosya listesi ve "Tüm dosyaları aktar" koşusu bileşenin içinde tutulursa, kullanıcı JurisAI'da başka bir sayfaya geçtiğinde bileşen
 * kaldırılır: liste kaybolur, ilerleme sıfırlanır ve dönünce her şey baştan görünür. Burada koşu bileşenden bağımsız yürür ve durum modül
 * düzeyinde durur: başka sayfaya geçip dönünce liste, canlı ilerleme ve son rapor yerindedir. (Sekme kapatılır ya da sayfa yenilenirse
 * tarayıcı betiği durur; yeniden başlatınca zaten aktarılan evraklar atlanır.)
 */
import { listUyapDosyalari, type DosyaListe } from "@/lib/uyap-bridge";
import { keepAwake } from "@/lib/steady-timer";
import {
  summarize,
  blankReport,
  syncAll,
  toServerItems,
  type FileReport,
  type SyncRun,
} from "@/lib/uyap-sync-all";
import {
  checkUyapAccount,
  saveCaseDetail,
  saveSyncReport,
  saveAuditRun,
} from "@/lib/uyap-sync-api";
import { auditCheckpoint } from "@/lib/uyap-run-report";
import { reportUyapProblem } from "@/lib/uyap-diagnostics";

export interface SyncProgress {
  index: number;
  total: number;
  phase: string;
  name: string;
}

export interface UyapSyncState {
  /** Ham liste tarayıcıda; başlatılan koşunun dosya numarası/birim/sayaçları rapor geçmişine kaydedilir. */
  liste: DosyaListe | null;
  running: boolean;
  progress: SyncProgress | null;
  /** Süren koşuda o ana kadar işlenen dosyaların raporu. */
  live: FileReport[];
  /** Biten son koşu. */
  run: SyncRun | null;
  /** Son koşu yalnız denetim miydi (hiçbir evrak aktarılmadı)? */
  verifyOnly: boolean;
  saveNote: { kind: "ok" | "warn"; text: string } | null;
  /** Sunucudaki doğrulama durumu değişince artar (rozet yeniden yüklenir). */
  savedVersion: number;
}

export interface FinishedRun {
  run: SyncRun;
  pull: boolean;
  saveWarning?: boolean;
}

const initial: UyapSyncState = {
  liste: null,
  running: false,
  progress: null,
  live: [],
  run: null,
  verifyOnly: false,
  saveNote: null,
  savedVersion: 0,
};

let state: UyapSyncState = initial;
let controller: AbortController | null = null;
let activeOwner: string | null | undefined;
let scopeGeneration = 0;
const listeners = new Set<() => void>();
const finishListeners = new Set<(finished: FinishedRun) => void>();

const set = (patch: Partial<UyapSyncState>) => {
  state = { ...state, ...patch };
  for (const listener of listeners) listener();
};

export const getSyncState = (): UyapSyncState => state;
export function subscribeSync(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}
/** Koşu bitince (hangi sayfada olunursa olunsun) bir kez çağrılır: bildirim göstermek için. */
export function onSyncFinished(listener: (finished: FinishedRun) => void): () => void {
  finishListeners.add(listener);
  return () => finishListeners.delete(listener);
}

/** Dosya listesini depoya yazar. Koşu sürerken liste değiştirilmez (koşu kendi listesiyle yürür). */
export function setListe(liste: DosyaListe | null): void {
  if (state.running) return;
  set({ liste });
}

export const stopSync = (): void => controller?.abort();

/** Logout/account changes cancel the old run and discard its private in-memory UI. */
export function setSyncOwner(ownerId: string | null): void {
  if (activeOwner === ownerId) return;
  const firstBinding = activeOwner === undefined;
  activeOwner = ownerId;
  scopeGeneration += 1;
  controller?.abort();
  controller = null;
  // Initial binding may resume only this exact owner's session checkpoint.
  if (!firstBinding || !readResume()) writeResume(null);
  state = initial;
  for (const listener of listeners) listener();
}

/* ---------- Yarıda kalan koşuyu sürdürme ----------
   Sayfa yenilenir ya da sekme yeniden açılırsa tarayıcı betiği (ve koşu) durur; UYAP sekmesi yalnız o anki dosyayı bitirir. Kullanıcı
   koşuyu zaten onaylamıştı: kalan dosyaların anahtarları oturum deposunda tutulur ve liste yeniden okununca koşu KALDIĞI YERDEN sürer.
   Kullanıcı "Durdur"a bastıysa ya da koşu bittiyse kayıt silinir (kendiliğinden yeniden başlamaz). Yalnız dosya anahtarları saklanır. */
const RESUME_KEY = "jurisai.uyap.sync.resume";
interface ResumeNote {
  pull: boolean;
  pending: string[];
}
function writeResume(note: ResumeNote | null): void {
  try {
    if (note)
      sessionStorage.setItem(RESUME_KEY, JSON.stringify({ ...note, ownerId: activeOwner ?? null }));
    else sessionStorage.removeItem(RESUME_KEY);
  } catch {
    /* depolama yoksa sürdürme özelliği çalışmaz; koşu etkilenmez */
  }
}
export function readResume(): ResumeNote | null {
  try {
    const raw = JSON.parse(sessionStorage.getItem(RESUME_KEY) ?? "null") as unknown;
    if (!raw || typeof raw !== "object") return null;
    const note = raw as Record<string, unknown>;
    if (activeOwner !== undefined && (!activeOwner || note.ownerId !== activeOwner)) return null;
    const pending = Array.isArray(note.pending)
      ? note.pending.filter((key): key is string => typeof key === "string")
      : [];
    return pending.length ? { pull: note.pull !== false, pending } : null;
  } catch {
    return null;
  }
}
/** Yarıda kalmış bir koşu varsa kalan dosyalarla sürdürür; sürdürdüyse true. Liste değiştiyse yalnız hâlâ listede olanlar işlenir. */
export function resumeIfInterrupted(liste: DosyaListe): boolean {
  if (state.running) return false;
  const note = readResume();
  if (!note) return false;
  const only = new Set(
    liste.items.filter((item) => note.pending.includes(item.key)).map((item) => item.key),
  );
  if (!only.size) {
    writeResume(null);
    return false;
  }
  void startSync(liste, only, note.pull);
  return true;
}

/** Koşuyu başlatır; zaten sürüyorsa hiçbir şey yapmaz. Bileşen kaldırılsa da sürer. */
export async function startSync(liste: DosyaListe, only?: Set<string>, pull = true): Promise<void> {
  if (state.running) return;
  const previous = only && state.run ? state.run.reports : [];
  const runController = new AbortController();
  controller = runController;
  const runScope = scopeGeneration;
  const isCurrent = () => runScope === scopeGeneration;
  const targets = only ? liste.items.filter((item) => only.has(item.key)) : liste.items;
  if (!targets.length) {
    controller = null;
    return;
  }
  const reports = new Map<number, FileReport>();
  const runId = crypto.randomUUID();
  let revision = 0;
  let historyWarning: string | undefined;
  const persist = async (run: SyncRun, finished = false) => {
    if (!isCurrent()) return;
    try {
      const saved = await saveAuditRun(
        auditCheckpoint(runId, ++revision, finished, !pull, liste.complete, run, state.saveNote),
      );
      if (!isCurrent()) return;
      historyWarning = undefined;
      if (finished) {
        // Keep live portal keys for explicit retries; history deliberately does not store those keys.
        run.reports = run.reports.map((r, i) => ({ ...r, ...saved.run.reports[i], key: r.key }));
        run.summary = summarize(run.reports);
      }
    } catch (cause) {
      historyWarning = cause instanceof Error ? cause.message : "Tam koşu raporu kaydedilemedi.";
    }
  };
  set({
    liste,
    running: true,
    run: null,
    saveNote: null,
    live: [],
    verifyOnly: !pull,
    progress: { index: 0, total: targets.length, phase: "Başlıyor", name: "" },
  });
  let result: SyncRun;
  const emptyRun: SyncRun = {
    reports: targets.map(blankReport),
    summary: summarize(targets.map(blankReport)),
    aborted: false,
  };
  // Dosyalar kimin UYAP'ından geldiyse onun altında dursun: koşu kaydı dahil hiçbir şey yazılmadan önce UYAP'ta giriş yapan
  // kişi okunur ve kaydedilir. Liste eklentinin eski sürümüyle alındıysa kişi taşımaz (gerçekte görüldü, 2026-10-16): o zaman
  // kişiyi okumak için liste bir kez yeniden okunur; dosya anahtarları değiştiyse orkestratör kendisi yeniden eşler.
  let identity = liste.identity ?? null;
  if (!identity) {
    set({
      progress: {
        index: 0,
        total: targets.length,
        phase: "UYAP'ta giriş yapan kişi okunuyor",
        name: "",
      },
    });
    const fresh = await listUyapDosyalari().catch(() => null);
    if (fresh?.ok && fresh.liste.identity) identity = fresh.liste.identity;
  }
  try {
    await checkUyapAccount(identity);
  } catch (cause) {
    if (!isCurrent()) return;
    controller = null;
    set({
      running: false,
      run: {
        ...emptyRun,
        stoppedBecause: cause instanceof Error ? cause.message : "UYAP hesabı doğrulanamadı.",
      },
      progress: null,
    });
    return;
  }
  if (!isCurrent()) return;
  const release = keepAwake();
  writeResume({ pull, pending: targets.map((item) => item.key) });
  await persist(emptyRun);
  if (!isCurrent()) {
    release();
    return;
  }
  try {
    result = await syncAll(liste.items, {
      only,
      pull,
      identity,
      tabId: liste.tabId,
      onProblem: (code) => void reportUyapProblem(code, { phase: "dosya" }),
      signal: runController.signal,
      // Dosya bilgileri (taraflar, safahat, hesap…) her dosyadan hemen sonra kaydedilir: koşu yarıda kalsa da alınanlar kaybolmaz.
      onDetail: async (detail) => {
        if (!isCurrent()) throw new Error("Hesap değişti; eski koşu durduruldu.");
        return await saveCaseDetail(detail);
      },
      onCheckpoint: async (checkpoint) => {
        if (!isCurrent()) return;
        set({ live: checkpoint.reports });
        await persist(checkpoint);
      },
      onProgress: ({ index, total, phase, report }) => {
        if (!isCurrent()) return;
        // Yeni dosyaya geçildiyse öncekiler bitmiştir: sürdürme kaydında yalnız bu ve sonraki dosyalar kalır.
        if (!reports.has(index))
          writeResume({ pull, pending: targets.slice(index).map((item) => item.key) });
        reports.set(index, report);
        set({
          live: [...reports.entries()].sort(([a], [b]) => a - b).map(([, value]) => value),
          progress: { index, total, phase, name: `${report.esas || "?"} · ${report.birim}` },
        });
      },
    });
  } catch (cause) {
    result = {
      ...emptyRun,
      reports: targets.map((d) => state.live.find((r) => r.key === d.key) ?? blankReport(d)),
      stoppedBecause: cause instanceof Error ? cause.message : "Aktarım beklenmedik biçimde durdu.",
      aborted: runController.signal.aborted,
    };
    result.summary = summarize(result.reports);
  }
  release();
  if (!isCurrent()) return;
  controller = null;
  writeResume(null); // bitti ya da kullanıcı durdurdu: kendiliğinden yeniden başlamaz
  if (previous.length) {
    // Yeniden denenen alt küme eski başarılı dosyaları rapordan silmez; güncel sonuç aynı anahtarın yerini alır.
    const merged = new Map(previous.map((report) => [report.key, report]));
    for (const report of result.reports) merged.set(report.key, report);
    const all = liste.items.flatMap((item) => {
      const report = merged.get(item.key);
      return report ? [report] : [];
    });
    result = { ...result, reports: all, summary: summarize(all) };
  }
  set({
    progress: {
      index: targets.length,
      total: targets.length,
      phase: "Doğrulama sonucu kaydediliyor",
      name: "",
    },
    run: result,
  });
  const items = toServerItems(result.reports, liste.items);
  if (items.length) {
    try {
      const saved = await saveSyncReport(items);
      if (!isCurrent()) return;
      if (saved.downgraded.length) {
        const rejected = new Set(saved.downgraded);
        const reports = result.reports.map((report) => {
          const label = `${report.who?.esas || report.esas} · ${report.who?.birim || report.birim}`;
          return rejected.has(label) && report.outcome === "complete"
            ? {
                ...report,
                outcome: "incomplete" as const,
                problems: ["Sunucu evrak eksiksizliğini doğrulamadı.", ...report.problems].slice(
                  0,
                  6,
                ),
              }
            : report;
        });
        result = { ...result, reports, summary: summarize(reports) };
        set({ run: result });
      }
      set({
        saveNote: saved.downgraded.length
          ? {
              kind: "warn",
              text: `Sunucu ${saved.downgraded.length} dosyayı eksiksiz saymadı (kendi evrak sayımı ağaçla tutmuyor): ${saved.downgraded.slice(0, 5).join("; ")}`,
            }
          : saved.unmatched > 0
            ? {
                kind: "warn",
                text: `${saved.unmatched} dosyanın doğrulama sonucu kaydedilemedi; bu dosyalar için başarı doğrulanamadı.`,
              }
            : { kind: "ok", text: `Doğrulama sonucu JurisAI'a kaydedildi (${saved.saved} dosya).` },
      });
    } catch (cause) {
      set({
        saveNote: {
          kind: "warn",
          text: cause instanceof Error ? cause.message : "Doğrulama sonucu kaydedilemedi.",
        },
      });
    }
  }
  await persist(result, true);
  if (!isCurrent()) return;
  set({
    run: result,
    running: false,
    progress: null,
    savedVersion: state.savedVersion + 1,
    ...(historyWarning
      ? { saveNote: { kind: "warn" as const, text: historyWarning } }
      : {
          saveNote:
            state.saveNote?.kind === "warn"
              ? state.saveNote
              : {
                  kind: "ok" as const,
                  text: `Tam koşu raporu kaydedildi (${result.reports.length} dosya; evraksız ve işlenmeyenler dahil).`,
                },
        }),
  });
  for (const listener of finishListeners)
    listener({ run: result, pull, saveWarning: state.saveNote?.kind === "warn" });
}

/** Yalnız testler için: depoyu ilk hâline döndürür. */
export function resetSyncStore(): void {
  controller = null;
  state = initial;
  for (const listener of listeners) listener();
}
