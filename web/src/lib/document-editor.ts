/** Düzenleyicinin desteklediği biçimleri kaydedilebilir metne çevirir; HTML saklanmaz. */
export function editableToMarkdown(root: Pick<Node, "childNodes">): string {
  function visit(node: Node): string {
    if (node.nodeType === 3) return node.textContent ?? "";
    if (node.nodeType !== 1) return "";
    const element = node as Element;
    const tag = element.tagName.toLowerCase();
    if (["script", "style", "iframe", "img", "object", "input"].includes(tag)) return "";
    const content = Array.from(node.childNodes).map(visit).join("");
    const href = element.getAttribute?.("data-link");
    if (href && /^https?:\/\//i.test(href))
      return `[${content}](${href.replace(/[()\s]/g, (value) => encodeURIComponent(value))})`;
    if (tag === "br") return "\n";
    if (tag === "b" || tag === "strong") return content ? `**${content}**` : "";
    if (tag === "em" || tag === "i") return content ? `*${content}*` : "";
    if (tag === "u") return content;
    if (/^h[1-6]$/.test(tag)) return `\n\n${"#".repeat(Number(tag[1]))} ${content.trim()}\n\n`;
    if (tag === "li") {
      const parent = element.parentElement;
      const index = parent ? Array.from(parent.children).indexOf(element) + 1 : 1;
      const start = Number(parent?.getAttribute?.("start") ?? 1);
      return `${parent?.tagName.toLowerCase() === "ol" ? `${(Number.isFinite(start) ? start : 1) + index - 1}.` : "-"} ${content.trim()}\n`;
    }
    if (tag === "ul" || tag === "ol") return `\n\n${content.trim()}\n\n`;
    if (tag === "p" || tag === "div" || tag === "blockquote") return `\n\n${content.trim()}\n\n`;
    if (tag === "table") {
      const rows = Array.from(element.querySelectorAll("tr")).map((row) =>
        Array.from(row.children).map((cell) =>
          Array.from(cell.childNodes)
            .map(visit)
            .join("")
            .trim()
            .replace(/\|/g, "\\|")
            .replace(/\n+/g, " "),
        ),
      );
      if (!rows.length) return "";
      const line = (cells: string[]) => `| ${cells.join(" | ")} |`;
      return `\n\n${[line(rows[0]), line(rows[0].map(() => "---")), ...rows.slice(1).map(line)].join("\n")}\n\n`;
    }
    if (tag === "hr") return "\n\n---\n\n";
    if (tag === "del" || tag === "s") return `~~${content}~~`;
    if (tag === "tr") return `${content.trim()}\n`;
    if (tag === "td" || tag === "th") return `${content}\t`;
    return content;
  }
  return Array.from(root.childNodes)
    .map(visit)
    .join("")
    .replace(/\u00a0/g, " ")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

/** Basit belge biçimleri Word'e aktarılırken metnin içindeki tarih/tutar/numara korunur. */
export function documentInlineRuns(
  text: string,
): Array<{ text: string; bold?: boolean; italics?: boolean }> {
  const runs: Array<{ text: string; bold?: boolean; italics?: boolean }> = [];
  const pattern = /\*\*([^*]+)\*\*|\*([^*\n]+)\*|\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g;
  let previous = 0;
  for (const match of text.matchAll(pattern)) {
    if (match.index > previous) runs.push({ text: text.slice(previous, match.index) });
    runs.push({
      text: match[1] ?? match[2] ?? `${match[3]} (${match[4]})`,
      ...(match[1] ? { bold: true } : {}),
      ...(match[2] ? { italics: true } : {}),
    });
    previous = match.index + match[0].length;
  }
  if (previous < text.length) runs.push({ text: text.slice(previous) });
  return (runs.length ? runs : [{ text }]).map((run) => ({
    ...run,
    text: run.text.replace(/\\([\\`*_{}[\]<>#!|])/g, "$1"),
  }));
}
