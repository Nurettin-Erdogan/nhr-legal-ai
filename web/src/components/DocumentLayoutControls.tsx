import type { DocumentLayout } from "@/lib/document-layout";
import { normalizeDocumentLayout } from "@/lib/document-layout";
export function DocumentLayoutControls({
  value,
  onChange,
}: {
  value: DocumentLayout;
  onChange: (value: DocumentLayout) => void;
}) {
  const update = (patch: Partial<DocumentLayout>) =>
    onChange(normalizeDocumentLayout({ ...value, ...patch }));
  const select = "rounded border border-border bg-background p-1.5 text-sm";
  return (
    <fieldset className="my-3 flex flex-wrap items-end gap-3 rounded-lg border border-border p-3">
      <legend className="px-1 text-sm font-medium">Sayfa düzeni</legend>
      <label className="grid gap-1 text-xs">
        Kağıt
        <select
          className={select}
          value={value.paper}
          onChange={(e) => update({ paper: e.target.value as DocumentLayout["paper"] })}
        >
          <option value="a4">A4</option>
          <option value="letter">Letter</option>
        </select>
      </label>
      <label className="grid gap-1 text-xs">
        Kenar boşluğu (mm)
        <input
          className={select}
          type="number"
          min="10"
          max="35"
          value={value.marginMm}
          onChange={(e) => update({ marginMm: Number(e.target.value) })}
        />
      </label>
      <label className="grid gap-1 text-xs">
        Yazı (punto)
        <input
          className={select}
          type="number"
          min="9"
          max="16"
          value={value.fontPt}
          onChange={(e) => update({ fontPt: Number(e.target.value) })}
        />
      </label>
      <label className="grid gap-1 text-xs">
        Satır aralığı
        <select
          className={select}
          value={value.lineHeight}
          onChange={(e) => update({ lineHeight: Number(e.target.value) })}
        >
          <option value="1">1</option>
          <option value="1.15">1,15</option>
          <option value="1.5">1,5</option>
          <option value="2">2</option>
        </select>
      </label>
      <label className="grid gap-1 text-xs">
        Hizalama
        <select
          className={select}
          value={value.alignment}
          onChange={(e) => update({ alignment: e.target.value as DocumentLayout["alignment"] })}
        >
          <option value="left">Sola</option>
          <option value="justify">İki yana</option>
        </select>
      </label>
      <label className="flex gap-2 text-sm">
        <input
          type="checkbox"
          checked={value.pageNumbers}
          onChange={(e) => update({ pageNumbers: e.target.checked })}
        />
        Sayfa numarası
      </label>
      <p className="w-full text-xs text-muted-foreground">
        Düzen önizlemeye, PDF ve Word çıktısına uygulanır. Otomatik sayfa akışı ve tablolar dışa
        aktarımda farklı görünebilir.
      </p>
    </fieldset>
  );
}
