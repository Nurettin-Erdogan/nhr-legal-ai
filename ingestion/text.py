"""Paylaşılan metin temizleme: HTML → düz metin, satır birleştirme, özet hash."""

from __future__ import annotations

import hashlib
import re
from html.parser import HTMLParser


_TR_FOLD = str.maketrans({"İ": "i", "I": "ı"})
_INLINE_WHITESPACE = re.compile(r"[ \t\u00a0\u200b]+")
_EXCESS_BLANK_LINES = re.compile(r"\n{3,}")


def tr_casefold(text: str) -> str:
    """Türkçe İ/I harflerini koruyarak küçük harfe çevirir."""
    return text.translate(_TR_FOLD).lower()


def normalize_text(text: str) -> str:
    """Satır sonlarını ve boşlukları tekilleştirir."""
    unified = text.replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n")
    collapsed = _INLINE_WHITESPACE.sub(" ", unified)
    stripped = "\n".join(line.strip() for line in collapsed.split("\n"))
    return _EXCESS_BLANK_LINES.sub("\n\n", stripped).strip()


def content_hash(text: str) -> str:
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()


class _TextExtractor(HTMLParser):
    block_tags = {
        "address",
        "article",
        "blockquote",
        "div",
        "footer",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "li",
        "main",
        "p",
        "section",
        "table",
        "tr",
    }
    ignored_tags = {"script", "style"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.ignored_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in self.ignored_tags:
            self.ignored_depth += 1
        elif self.ignored_depth == 0 and (tag in self.block_tags or tag == "br"):
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self.ignored_tags and self.ignored_depth:
            self.ignored_depth -= 1
        elif self.ignored_depth == 0 and tag in self.block_tags:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self.ignored_depth == 0:
            self.parts.append(data)


def html_to_text(value: str) -> str:
    parser = _TextExtractor()
    parser.feed(value)
    parser.close()
    paragraphs = []
    for line in "".join(parser.parts).splitlines():
        cleaned = " ".join(line.split())
        if cleaned:
            paragraphs.append(cleaned)
    return "\n\n".join(paragraphs)


def decode_html_bytes(data: bytes) -> str:
    """Decode Turkish UYAP HTML without losing characters in older 1254/8859-9 pages."""
    header = data[:4096].decode("ascii", errors="ignore")
    match = re.search(r"charset\s*=\s*['\"]?\s*([\w-]+)", header, re.IGNORECASE)
    declared = (match.group(1).lower() if match else "")
    if declared in {"utf-8", "utf8", "iso-8859-9", "windows-1254", "cp1254"}:
        try:
            return data.decode(declared)
        except UnicodeDecodeError:
            pass
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1254", errors="replace")
