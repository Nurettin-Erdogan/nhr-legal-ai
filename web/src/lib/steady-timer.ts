/**
 * Arka plandaki sekmede de zamanında çalışan bekleme.
 *
 * Tarayıcı, görünmeyen sekmedeki `setTimeout` zincirlerini önce saniyede bire, beş dakika sonra dakikada bire indirir.
 * Saatler sürebilen UYAP aktarımında kullanıcı başka sekmeye geçince iş durumu yoklaması dakikada bire düşer ve her adım
 * arası bir dakikaya kadar uzar. Çalışan (worker) içindeki zamanlayıcılar bu kısıtlamaya girmez; bekleme oradan yapılır.
 * Çalışan kurulamıyorsa (eski tarayıcı, içerik güvenlik kuralı, test ortamı) olağan `setTimeout` kullanılır.
 */

const SOURCE = "onmessage = (e) => setTimeout(() => postMessage(e.data.id), e.data.ms);";

let worker: Worker | null | undefined;
let nextId = 0;
const waiting = new Map<number, () => void>();

function ticker(): Worker | null {
  if (worker !== undefined) return worker;
  try {
    if (typeof Worker === "undefined" || typeof Blob === "undefined" || typeof URL === "undefined")
      throw new Error("worker yok");
    const created = new Worker(
      URL.createObjectURL(new Blob([SOURCE], { type: "text/javascript" })),
    );
    created.onmessage = (event: MessageEvent) => {
      const resolve = waiting.get(event.data as number);
      if (resolve) {
        waiting.delete(event.data as number);
        resolve();
      }
    };
    created.onerror = () => {
      // Çalışan bozulursa bekleyenler asılı kalmasın; sonraki beklemeler olağan zamanlayıcıya düşer.
      worker = null;
      for (const resolve of waiting.values()) resolve();
      waiting.clear();
    };
    worker = created;
  } catch {
    worker = null;
  }
  return worker;
}

export function steadySleep(ms: number): Promise<void> {
  const delay = Math.max(0, ms);
  const active = ticker();
  if (!active) return new Promise((resolve) => setTimeout(resolve, delay));
  return new Promise((resolve) => {
    const id = (nextId += 1);
    waiting.set(id, resolve);
    active.postMessage({ id, ms: delay });
  });
}

/**
 * Uzun iş sürerken ekranın kapanmasını/uykuya geçmesini önlemeye çalışır (yalnız sayfa görünürken ve tarayıcı
 * destekliyorsa). Dönen işlev kilidi bırakır. Kilit alınamazsa sessizce hiçbir şey yapmaz: iş yine çalışır.
 */
export function keepAwake(): () => void {
  let released = false;
  let lock: { release: () => Promise<void> } | null = null;
  const request = async () => {
    if (
      released ||
      typeof navigator === "undefined" ||
      typeof document === "undefined" ||
      document.visibilityState !== "visible"
    )
      return;
    try {
      const api = (
        navigator as unknown as {
          wakeLock?: { request: (type: "screen") => Promise<{ release: () => Promise<void> }> };
        }
      ).wakeLock;
      lock = (await api?.request("screen")) ?? null;
      if (released) void lock?.release().catch(() => undefined);
    } catch {
      lock = null;
    }
  };
  const onVisible = () => void request(); // sekme gizlenince tarayıcı kilidi bırakır; geri gelince yeniden alınır
  if (typeof document !== "undefined") document.addEventListener("visibilitychange", onVisible);
  void request();
  return () => {
    released = true;
    if (typeof document !== "undefined")
      document.removeEventListener("visibilitychange", onVisible);
    void lock?.release().catch(() => undefined);
  };
}
