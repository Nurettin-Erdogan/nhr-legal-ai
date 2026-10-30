"""Conservative layout evidence for headings adjacent to statute articles.

The heading is never reconstructed from legal wording. It is accepted only
when the exact non-whitespace characters occur at the end of a verified
article extract and the same line is visibly bold in the matching official
PDF. Callers must bind the PDF text hash to the existing verification proof.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from io import BytesIO
import re

from pypdf import PdfReader

from ingestion.mevzuat.identity import article_headings, canonical_article
from ingestion.text import content_hash, normalize_text

_NUMBERED = re.compile(r"^\s*(?:[IVXLCDM]{1,8}\.|\d{1,3}\.|[A-Za-zÇĞİÖŞÜçğıöşü][.)])\s*")
_SENTENCE_END = re.compile(r"[.!?;](?!\s*$)")
_ARTICLE_LINE = re.compile(r"(?i)MADDE\s*(\d+(?:\s*/\s*[A-ZÇĞİÖŞÜ])?)")


@dataclass(frozen=True, slots=True)
class LayoutCaption:
    article_no: str
    caption: str


def _compact(value: str) -> str:
    return "".join(value.split())


def _eligible_caption(value: str) -> bool:
    text = normalize_text(value)
    if not text or len(text) > 500 or "MADDE" in text.upper():
        return False
    # Headings may have an enumerator such as "II." or "3." and may end in
    # a colon, but a sentence-like line is not accepted as layout evidence.
    without_number = _NUMBERED.sub("", text, count=1)
    return not _SENTENCE_END.search(without_number)


def _bold_lines(page) -> list[tuple[float, float, float, str]]:
    runs: list[tuple[float, float, float, str, float, str]] = []

    def visitor(text, _cm, tm, font, size):
        if not text.strip():
            return
        name = str((font or {}).get("/BaseFont", ""))
        runs.append((float(tm[4]), float(tm[5]), float(size or 0), name, text, 0.0))

    page.extract_text(visitor_text=visitor)
    groups: dict[float, list[tuple[float, float, str, float, str]]] = defaultdict(list)
    small_runs: list[tuple[float, float, float, str]] = []
    for x, y, size, font, text, _ in runs:
        if "bold" in font.casefold() or "black" in font.casefold():
            groups[round(y, 1)].append((x, y, font, size, text))
        elif size and size <= 9.5 and text.strip().isdigit():
            small_runs.append((x, y, size, text.strip()))
    lines = []
    for y, items in groups.items():
        items.sort(key=lambda item: item[0])
        text = "".join(item[4] for item in items).strip()
        if text:
            # Superscript footnote digits are independently small-font runs.
            # Include one only when its position is after the bold caption on
            # the same visual line; a legal number in normal-size text cannot
            # enter this path.
            x0 = min(item[0] for item in items)
            footnotes = [run for run in small_runs if 1 <= run[1] - y <= 8
                         and run[0] >= x0 + max(12, len(text) * 2.4)]
            if len(footnotes) == 1:
                text += footnotes[0][3]
            lines.append((y, min(item[0] for item in items), sum(item[3] for item in items) / len(items), text))
    return sorted(lines, key=lambda line: -line[0])


def extract_layout_captions(pdf_bytes: bytes) -> tuple[str, tuple[LayoutCaption, ...]]:
    """Return canonical PDF text and bold captions immediately before articles.

    Multiple candidate caption-line sequences are returned per article (from
    the nearest line backward); the caller must match one exactly to the
    verified stored article suffix. Ambiguous duplicate article identities
    are omitted.
    """
    reader = PdfReader(BytesIO(pdf_bytes))
    page_text: list[str] = []
    page_lines: list[list[tuple[float, float, float, str]]] = []
    for page in reader.pages:
        page_text.append(page.extract_text() or "")
        page_lines.append(_bold_lines(page))
    full_text = normalize_text("\n".join(page_text))
    headings = article_headings(full_text)
    occurrences: dict[str, list[LayoutCaption]] = defaultdict(list)

    for lines in page_lines:
        for index, (y, x, size, line) in enumerate(lines):
            marker = _ARTICLE_LINE.search(line)
            if not marker:
                continue
            article = canonical_article(marker.group(1))
            before = [item for item in lines[:index] if 0 < item[0] - y <= 54]
            # Lines are in descending y (top to bottom); immediately preceding
            # caption is the first prior bold line. Consider only a short
            # contiguous group, never arbitrary text from the body.
            sequence: list[tuple[float, float, float, str]] = []
            for prior in reversed(before[-3:]):
                if sequence and (prior[0] - sequence[-1][0] > 22 or abs(sequence[-1][1] - prior[1]) > 40):
                    break
                if abs(prior[2] - size) > 1.5 or abs(prior[1] - x) > 40:
                    break
                if not _eligible_caption(prior[3]):
                    break
                sequence.append(prior)
                caption = " ".join(item[3] for item in reversed(sequence))
                occurrences[article].append(LayoutCaption(article, normalize_text(caption)))

    unique_article_ids = {heading.identity for heading in headings}
    result = []
    for article in unique_article_ids:
        candidates = occurrences.get(article, [])
        # Duplicate PDF article headings or duplicate layout matches fail
        # closed; no caller should guess which one is the current article.
        if len([h for h in headings if h.identity == article]) != 1:
            continue
        deduped = tuple(dict.fromkeys(candidates))
        result.extend(deduped)
    return full_text, tuple(result)


def exact_suffix_for_caption(article_text: str, caption: str) -> str | None:
    """Find the literal stored-text suffix corresponding to a PDF caption."""
    target = _compact(caption)
    if not target:
        return None
    positions = [index for index, char in enumerate(article_text) if not char.isspace()]
    compact = "".join(article_text[index] for index in positions)
    if not compact.endswith(target):
        return None
    start = positions[len(compact) - len(target)]
    suffix = article_text[start:].strip()
    return suffix if _compact(suffix) == target else None


def verified_layout_caption(pdf_bytes: bytes, article_text: str, *, expected_document_hash: str,
                            expected_article_hash: str, article_no: str) -> tuple[str, str] | None:
    """Bind a visual caption to an already verified exact PDF/article snapshot."""
    full_text, captions = extract_layout_captions(pdf_bytes)
    document_hash = content_hash(full_text)
    if document_hash != expected_document_hash or content_hash(article_text) != expected_article_hash:
        return None
    wanted = canonical_article(article_no)
    matches = [item for item in captions if item.article_no == wanted
               and exact_suffix_for_caption(article_text, item.caption)]
    distinct = {exact_suffix_for_caption(article_text, item.caption) for item in matches}
    if len(distinct) != 1:
        return None
    return next(iter(distinct)), document_hash
