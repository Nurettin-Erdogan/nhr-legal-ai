"""Article identity is distinct from a portal's sometimes numeric maddeNo."""
from dataclasses import dataclass
import re

from ingestion.mevzuat.models import LegislationRecord

_NUMBER = r"\d+(?:\s*/\s*[A-ZÇĞİÖŞÜ]|[A-ZÇĞİÖŞÜ])?"
HEADING = re.compile(
    rf"(?im)^[ \t]*(?:(EK\s+GEÇİCİ|EK|GEÇİCİ|GECICI)\s+)?MADDE\s+({_NUMBER})(?=\s|[-–—.:\[])")


def canonical_article(value: str) -> str:
    value = value.upper().replace("GECICI", "GEÇİCİ").replace("GEÇICI", "GEÇİCİ")
    value = re.sub(r"\bMADDE\b", "", value)
    return re.sub(r"\s+", " ", re.sub(r"\s*/\s*", "/", value)).strip()


@dataclass(frozen=True)
class Heading:
    identity: str
    start: int
    end: int


def article_headings(text: str) -> list[Heading]:
    return [Heading(canonical_article(" ".join(filter(None, m.groups()))), m.start(), m.end())
            for m in HEADING.finditer(text)]


def primary_article(text: str) -> str | None:
    headings = article_headings(text)
    # A distant quotation is not a primary article identifier.
    return headings[0].identity if headings and headings[0].start < 300 else None


def validate_record_identity(record: LegislationRecord) -> None:
    primary = primary_article(record.raw_text)
    if primary and primary != canonical_article(record.article_no):
        raise ValueError(f"Article identity mismatch: stored={record.article_no}, heading={primary}")
