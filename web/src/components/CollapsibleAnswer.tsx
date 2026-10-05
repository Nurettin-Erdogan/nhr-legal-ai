import { useState, type ReactNode } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";

/** Bu uzunluğun üstündeki cevaplar görsel olarak kısaltılır (metin DOM'da tam durur; kopyalama ve erişilebilirlik bozulmaz). */
export const LONG_ANSWER_CHARS = 1400;

/**
 * Kanun maddesi cevapları çoğu zaman çok uzundur ve kaynak kuralı gereği kısaltılmaz (istisnalar düşmesin diye). Okunabilirlik için
 * yalnız gösterim daraltılır; kullanıcı tek tıkla tamamını açar ve daraltılmış görünümde istisna uyarısı görür.
 */
export function CollapsibleAnswer({ length, children }: { length: number; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  if (length <= LONG_ANSWER_CHARS) return <>{children}</>;
  return (
    <div data-testid="collapsible-answer">
      <div className={open ? "" : "relative max-h-72 overflow-hidden"} data-collapsed={!open}>
        {children}
        {!open && <div aria-hidden className="pointer-events-none absolute inset-x-0 bottom-0 h-16 bg-gradient-to-t from-muted/90 to-transparent" />}
      </div>
      {!open && <p className="mt-1 text-xs text-muted-foreground">Cevap uzun ({length.toLocaleString("tr-TR")} karakter); madde istisnaları ve şartları devamında olabilir, tamamını okuyun.</p>}
      <button type="button" className="mt-1 inline-flex items-center gap-1 text-xs underline" aria-expanded={open} onClick={() => setOpen((value) => !value)}>
        {open ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
        {open ? "Cevabı daralt" : "Cevabın tamamını göster"}
      </button>
    </div>
  );
}
