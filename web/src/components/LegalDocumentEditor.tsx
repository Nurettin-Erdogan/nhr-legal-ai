import { useLayoutEffect, useRef } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Button } from "@/components/ui/button";
import { editableToMarkdown } from "@/lib/document-editor";
import { documentPageStyle, type DocumentLayout } from "@/lib/document-layout";

/** Yerel biçimlendirme; kullanıcı değişiklikleri AI üretimine gerek kalmadan kaydedilir. */
export function LegalDocumentEditor({
  value,
  onChange,
  layout,
}: {
  value: string;
  onChange: (value: string) => void;
  layout?: DocumentLayout;
}) {
  const editor = useRef<HTMLDivElement>(null);
  const lastValue = useRef<string | null>(null);
  useLayoutEffect(() => {
    if (!editor.current || lastValue.current === value) return;
    editor.current.innerHTML = renderToStaticMarkup(
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          img: () => null,
          a: ({ children, href }) => <span data-link={href}>{children}</span>,
        }}
      >
        {value}
      </ReactMarkdown>,
    );
    lastValue.current = value;
  }, [value]);
  const emit = () => {
    if (!editor.current) return;
    const next = editableToMarkdown(editor.current);
    lastValue.current = next;
    onChange(next);
  };
  const format = (command: string, argument?: string) => {
    const selection = window.getSelection();
    const range =
      selection?.anchorNode &&
      editor.current?.contains(selection.anchorNode) &&
      selection.rangeCount
        ? selection.getRangeAt(0).cloneRange()
        : null;
    editor.current?.focus();
    if (selection && range) {
      selection.removeAllRanges();
      selection.addRange(range);
    }
    document.execCommand(command, false, argument);
    emit();
  };
  return (
    <div className="overflow-hidden rounded-lg border border-border">
      <div
        role="toolbar"
        aria-label="Belge biçimlendirme"
        className="flex flex-wrap gap-1 border-b border-border bg-secondary/30 p-2"
      >
        {[
          ["Kalın", "bold"],
          ["İtalik", "italic"],
          ["Başlık", "formatBlock", "h2"],
          ["Paragraf", "formatBlock", "p"],
          ["Madde listesi", "insertUnorderedList"],
          ["Numaralı liste", "insertOrderedList"],
          ["Geri al", "undo"],
          ["Yinele", "redo"],
        ].map(([label, command, argument]) => (
          <Button
            key={label}
            size="sm"
            variant="ghost"
            type="button"
            onMouseDown={(event) => event.preventDefault()}
            onClick={() => format(command, argument)}
          >
            {label}
          </Button>
        ))}
      </div>
      <div
        ref={editor}
        contentEditable
        suppressContentEditableWarning
        role="textbox"
        aria-label="Belge metni"
        aria-multiline="true"
        onInput={emit}
        onDrop={(event) => event.preventDefault()}
        onPaste={(event) => {
          event.preventDefault();
          format("insertText", event.clipboardData.getData("text/plain"));
        }}
        className="prose prose-sm min-h-80 max-h-[65vh] max-w-none overflow-y-auto p-5 outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring dark:prose-invert"
        style={layout ? documentPageStyle(layout) : undefined}
      />
    </div>
  );
}
