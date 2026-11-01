"""Recover complete verified provisions without joining guessed chunk tails.

The stored canonical text must belong to the exact same official revision and
contain the retrieved fragment verbatim (whitespace aside). No legal text is
invented, and an incomplete canonical text still fails the ordinary gates.
"""
from dataclasses import replace
import re

from api.ai.rag import RAGContext
from ingestion.mevzuat.identity import canonical_article
from ingestion.mevzuat.pdf_layout import exact_suffix_for_caption

_CHAPTER = re.compile(
    r"(?m)^\s*(?:BİRİNCİ|İKİNCİ|ÜÇÜNCÜ|DÖRDÜNCÜ|BEŞİNCİ|ALTINCI|YEDİNCİ|SEKİZİNCİ|DOKUZUNCU|ONUNCU)"
    r"\s+(?:BÖLÜM|KISIM)\s*$")
_ARTICLE = re.compile(r"(?im)^\s*(?:GEÇİCİ\s+|EK\s+)?MADDE\s+(\d+(?:/[A-ZÇĞİÖŞÜ])?)\s*[-–—]")


def _next_article(article_no: str | None) -> str | None:
    if not article_no:
        return None
    if re.fullmatch(r"\d{1,5}", article_no):
        return str(int(article_no) + 1)
    match = re.fullmatch(r"(\d{1,3})/([A-Y])", article_no, re.I)
    if match:
        return match.group(1) + "/" + chr(ord(match.group(2).upper()) + 1)
    return None


def _verified_layout_caption(row, context: RAGContext) -> str | None:
    """Accept only a suffix caption tied to the exact official PDF + article."""
    proof = row.get('layout_proof')
    text_proof = row.get('text_proof')
    raw_text = row.get('raw_text')
    if not isinstance(proof, dict) or not isinstance(text_proof, dict) or not isinstance(raw_text, str):
        return None
    caption = proof.get('caption')
    if (proof.get('verified') is not True
            or proof.get('method') != 'pypdf_bold_caption_exact_suffix_v1'
            or canonical_article(str(proof.get('article_no', ''))) != canonical_article(context.article_no or '')
            or canonical_article(str(proof.get('following_article_no', ''))) != canonical_article(_next_article(context.article_no) or '')
            or proof.get('article_hash') != row.get('content_hash')
            or text_proof.get('article_hash') != row.get('content_hash')
            or proof.get('document_text_hash') != text_proof.get('document_text_hash')
            or not re.fullmatch(r'[0-9a-f]{64}', str(proof.get('document_text_hash', '')))
            or proof.get('url') != row.get('source_url')
            or not isinstance(caption, str) or not 1 <= len(caption) <= 500):
        return None
    return caption if exact_suffix_for_caption(raw_text, caption) == caption.strip() else None


def complete_provision(context: RAGContext, canonical: str, *, following_title: str | None = None) -> RAGContext | None:
    if (context.source_type != 'legislation' or context.verification != 'official'
            or not isinstance(canonical, str) or not 1 <= len(canonical) <= 16000):
        return None
    # Check the whole raw text before removing a next-section heading.
    if ' '.join(context.content.split()) not in ' '.join(canonical.split()):
        return None
    markers = list(_ARTICLE.finditer(canonical))
    if len(markers) != 1 or markers[0][1].casefold() != (context.article_no or '').casefold():
        return None
    chapter = _CHAPTER.search(canonical)
    if chapter:
        # Only a formally delimited next chapter may be removed, never an
        # unfinished condition/exception inside this provision.
        canonical = canonical[:chapter.start()].rstrip()
    restored = replace(context, content=canonical, following_article_title=following_title)
    from api.ai.free_answer import _usable
    return restored if _usable(restored, 16000) is not None else None


def restore_provisions(contexts: list[RAGContext], connection) -> list[RAGContext]:
    from api.ai.free_answer import _usable
    from api.ai.retrieval import _VERIFIED_SOURCE_FILTER
    result, cache = [], {}
    for context in contexts:
        if (context.source_type != 'legislation' or context.verification != 'official'
                or _usable(context, 36000) is not None):
            result.append(context)
            continue
        key = (context.source_id, context.source_version, context.revision)
        if key not in cache:
            with connection.transaction():
                connection.execute("SET LOCAL statement_timeout = '3s'")
                row = connection.execute(f"""
                    SELECT ls.raw_text, ls.content_hash, ls.source_url,
                      ls.metadata->'mbs_text_verification' AS text_proof,
                      ls.metadata->'mbs_pdf_layout' AS layout_proof,
                      (SELECT CASE WHEN count(*) = 1 THEN min(next_detail.article_title) END
                       FROM legislation_details next_detail
                       JOIN legal_sources next_source ON next_source.id = next_detail.legal_source_id
                       WHERE next_detail.law_no = legislation.law_no
                         AND next_detail.legislation_type = legislation.legislation_type
                         AND next_detail.article_no = CASE
                           WHEN legislation.article_no ~ '^[0-9]{{1,5}}$'
                             THEN (legislation.article_no::integer + 1)::text
                           WHEN legislation.article_no ~ '^[0-9]{{1,3}}/[A-Y]$'
                             THEN left(legislation.article_no, -1) || chr(ascii(right(legislation.article_no, 1)) + 1)
                           ELSE NULL END
                         AND next_source.is_current AND next_source.deleted_at IS NULL
                         AND next_source.ingest_status = 'ready'
                         AND next_source.source_type = 'legislation'
                         AND next_source.source_url = ls.source_url
                         AND ls.metadata->'mbs_text_verification'->>'verified' = 'true'
                         AND next_source.metadata->'mbs_text_verification'->>'verified' = 'true'
                         AND ls.metadata->'mbs_text_verification'->>'article_hash' = ls.content_hash
                         AND next_source.metadata->'mbs_text_verification'->>'article_hash' = next_source.content_hash
                         AND length(ls.metadata->'mbs_text_verification'->>'document_text_hash') = 64
                         AND next_source.metadata->'mbs_text_verification'->>'document_text_hash'
                           = ls.metadata->'mbs_text_verification'->>'document_text_hash'
                      ) AS following_title
                    FROM legal_sources ls
                    JOIN legislation_details legislation ON legislation.legal_source_id = ls.id
                    WHERE ls.id = %(id)s AND ls.source_type = 'legislation'
                      AND ls.deleted_at IS NULL AND ls.is_current
                      AND ls.source_version IS NOT DISTINCT FROM %(version)s
                      AND ls.revision IS NOT DISTINCT FROM %(revision)s
                      AND legislation.law_no = %(law)s AND legislation.article_no = %(article)s
                      AND {_VERIFIED_SOURCE_FILTER}
                      AND length(ls.raw_text) <= 16000
                    """, dict(id=context.source_id, version=context.source_version,
                              revision=context.revision, law=context.law_no, article=context.article_no)).fetchone()
            cache[key] = row
        row = cache[key]
        title = (_verified_layout_caption(row, context) if row else None) or (row.get('following_title') if row else None)
        restored = complete_provision(context, row['raw_text'], following_title=title) if row else None
        result.append(restored or context)
    return result
