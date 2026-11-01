"""Dava belgelerinin karşılaştırması: belirleyici metin farkı ve gerçek RLS'li uç nokta."""

from __future__ import annotations

import contextlib
import json
import time
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException

from api import document_compare as compare
from api import office
from tests.test_case_document_rag import _case, _indexed_document, db, needs_db  # noqa: F401  (fixture)

BASE = (
    "İşçi aylık net 20.000 TL ücret alır. İşveren ücreti her ayın beşinde öder. "
    "Sözleşme belirsiz süreli olarak yapılmıştır. Taraflar rekabet yasağına uymayı kabul eder."
)


def _rebuild(result, side):
    """Fark bloklarından bir tarafın cümle listesini yeniden kurar: sıra ve kapsam bozulmamış olmalı."""
    units: list[str] = []
    for block in result["blocks"]:
        if block["kind"] == "equal":
            units.extend(block["units"])
        elif block["kind"] == "changed":
            units.append(block[side])
        elif block["kind"] == ("removed" if side == "left" else "added"):
            units.append(block["text"])
    return units


# --- Saf karşılaştırma -------------------------------------------------------------------------------


def test_identical_documents_are_one_equal_block():
    result = compare.compare_texts(BASE, BASE)
    assert result["similarity"] == 1.0
    assert result["counts"] == {"equal": 4, "changed": 0, "removed": 0, "added": 0}
    assert [block["kind"] for block in result["blocks"]] == ["equal"]


def test_a_changed_amount_is_never_hidden_by_normalisation():
    """Rakam ve noktalama eşitliği bozar: "20.000" ile "2.000" aynı sayılamaz."""
    other = BASE.replace("20.000 TL", "2.000 TL")
    result = compare.compare_texts(BASE, other)
    [changed] = [block for block in result["blocks"] if block["kind"] == "changed"]
    assert {"op": "delete", "text": "20.000"} in changed["words"] and {"op": "insert", "text": "2.000"} in changed["words"]
    assert result["counts"]["changed"] == 1 and result["counts"]["equal"] == 3


def test_case_and_spacing_differences_are_not_changes():
    assert compare.compare_texts(BASE, BASE.replace(" ", "   "))["counts"]["changed"] == 0  # boşluk sayısı fark değildir
    result = compare.compare_texts("Taraflar Ağustos ayında buluşur.", "TARAFLAR AĞUSTOS AYINDA BULUŞUR.")
    assert result["counts"] == {"equal": 1, "changed": 0, "removed": 0, "added": 0}  # Türkçe büyük/küçük harf


def test_single_line_breaks_from_pdf_wrapping_are_whitespace_but_blank_lines_split_paragraphs():
    wrapped = "İşçi aylık net 20.000 TL\nücret alır. İşveren ücreti her ayın\nbeşinde öder."
    flat = "İşçi aylık net 20.000 TL ücret alır. İşveren ücreti her ayın beşinde öder."
    assert compare.compare_texts(wrapped, flat)["counts"]["changed"] == 0
    assert compare.split_units("Madde 1\n\nMadde 2 yazar") == ["Madde 1", "Madde 2 yazar"]


def test_added_and_removed_clauses_are_reported_in_document_order():
    left = BASE
    right = (
        "İşçi aylık net 20.000 TL ücret alır. İşveren ücreti her ayın beşinde öder. "
        "Sözleşme belirsiz süreli olarak yapılmıştır. Yıllık izin süresi 20 gündür."
    )
    result = compare.compare_texts(left, right)
    kinds = [block["kind"] for block in result["blocks"] if block["kind"] != "equal"]
    assert "removed" in kinds or "changed" in kinds
    assert any(block.get("text") == "Yıllık izin süresi 20 gündür." for block in result["blocks"] if block["kind"] == "added") or any(
        block.get("right") == "Yıllık izin süresi 20 gündür." for block in result["blocks"]
    )
    assert _rebuild(result, "right") == compare.split_units(right)
    assert _rebuild(result, "left") == compare.split_units(left)


@pytest.mark.parametrize("seed", range(8))
def test_blocks_always_reconstruct_both_documents(seed):
    import random

    rng = random.Random(seed)
    sentences = [f"Madde {n}: taraflar {rng.randint(100, 999)} TL tutarında {rng.choice(['kira', 'ücret', 'ceza'])} öder." for n in range(30)]
    left = list(sentences)
    right = list(sentences)
    for _ in range(6):
        position = rng.randrange(len(right))
        action = rng.choice(["drop", "edit", "insert"])
        if action == "drop":
            right.pop(position)
        elif action == "edit":
            right[position] = right[position].replace("öder", "ödemeyi kabul eder")
        else:
            right.insert(position, f"Ek madde {rng.randint(1, 9999)}: yeni hüküm uygulanır.")
    result = compare.compare_texts(" ".join(left), " ".join(right))
    assert _rebuild(result, "left") == compare.split_units(" ".join(left))
    assert _rebuild(result, "right") == compare.split_units(" ".join(right))
    counts = result["counts"]
    assert counts["equal"] + counts["changed"] + counts["removed"] == result["left_units"]
    assert counts["equal"] + counts["changed"] + counts["added"] == result["right_units"]


def test_two_unrelated_long_documents_finish_quickly_without_pairing_everything():
    left = " ".join(f"Sol belge {n}. maddesi tamamen başka konuyu düzenler ve yalnızca bu belgede geçer." for n in range(400))
    right = " ".join(f"Sağ belge {n}. fıkrası bambaşka bir olguyu anlatır ve burada hiç geçmez." for n in range(400))
    started = time.monotonic()
    result = compare.compare_texts(left, right)
    assert time.monotonic() - started < 10
    assert result["counts"]["equal"] == 0 and result["similarity"] == 0.0


def test_empty_inputs_and_size_limits():
    assert compare.compare_texts("", "")["similarity"] == 1.0
    assert compare.compare_texts("", "Bir cümle var.")["counts"]["added"] == 1
    with pytest.raises(compare.CompareTooLarge):
        compare.compare_texts("a" * (compare.MAX_COMPARE_CHARS + 1), "b")
    many = " ".join(f"Cümle {n}." for n in range(compare.MAX_UNITS + 1))
    with pytest.raises(compare.CompareTooLarge):
        compare.compare_texts(many, "x")


# --- Gerçek RLS'li uç nokta ----------------------------------------------------------------------


@pytest.fixture
def api(db, monkeypatch):  # noqa: F811
    @contextlib.contextmanager
    def as_user(user_id: str):
        db.become(UUID(user_id))
        yield db.connection

    monkeypatch.setattr(office, "authenticated_database_connection", as_user)
    request = SimpleNamespace(client=None, headers={})

    def call(user, case, left, right):
        return office.compare_case_documents(case_id=case, left=left, right=right, user_id=user, request=request)

    db.call = call
    return db


@needs_db
def test_owner_gets_the_sentence_diff_of_two_case_documents(api):
    case = _case(api, api.alice)
    first = _indexed_document(api, api.alice, case, BASE, name="sozlesme-v1.udf")
    second = _indexed_document(api, api.alice, case, BASE.replace("20.000", "25.000"), name="sozlesme-v2.udf")

    result = api.call(api.alice, case, first, second)

    assert result["left"]["file_name"] == "sozlesme-v1.udf" and result["right"]["file_name"] == "sozlesme-v2.udf"
    assert result["left"]["ocr"] is False and result["counts"]["changed"] == 1
    [changed] = [block for block in result["blocks"] if block["kind"] == "changed"]
    assert {"op": "insert", "text": "25.000"} in changed["words"]


@needs_db
def test_other_users_and_foreign_cases_cannot_compare(api):
    case = _case(api, api.alice)
    first = _indexed_document(api, api.alice, case, BASE)
    second = _indexed_document(api, api.alice, case, BASE + " Ek hüküm.")

    with pytest.raises(HTTPException) as foreign_user:
        api.call(api.bob, case, first, second)
    assert foreign_user.value.status_code == 404  # başkasının davası ile olmayan dava ayırt edilemez

    other_case = _case(api, api.alice, "Başka dava")
    with pytest.raises(HTTPException) as wrong_case:
        api.call(api.alice, other_case, first, second)
    assert wrong_case.value.status_code == 404  # belgeler bu davaya bağlı değil


@needs_db
def test_comparing_a_document_with_itself_is_refused(api):
    case = _case(api, api.alice)
    only = _indexed_document(api, api.alice, case, BASE)
    with pytest.raises(HTTPException) as error:
        api.call(api.alice, case, only, only)
    assert error.value.status_code == 422


@needs_db
def test_unreadable_and_unprocessed_documents_are_reported_not_compared(api):
    case = _case(api, api.alice)
    good = _indexed_document(api, api.alice, case, BASE, name="iyi.udf")
    bad, pending = uuid4(), uuid4()
    api.become(None)
    api.files[f"{api.alice}/{bad}"] = b"II*\x00"
    for document, name in ((bad, "tarama.tif"), (pending, "bekleyen.pdf")):
        api.connection.execute(
            "INSERT INTO office_case_documents (id, owner_id, case_id, file_name, storage_path, size_bytes) "
            "VALUES (%s, %s, %s, %s, %s, 4)",
            (document, api.alice, case, name, f"{api.alice}/{document}"),
        )
    from api import document_indexing

    document_indexing.index_office_document(api.alice, bad)

    with pytest.raises(HTTPException) as failed:
        api.call(api.alice, case, good, bad)
    assert failed.value.status_code == 409 and "tarama.tif" in failed.value.detail and "OCR" in failed.value.detail
    with pytest.raises(HTTPException) as waiting:
        api.call(api.alice, case, pending, good)
    assert waiting.value.status_code == 409 and "henüz işlenmedi" in waiting.value.detail


@needs_db
def test_trashed_documents_are_not_compared(api):
    case = _case(api, api.alice)
    first = _indexed_document(api, api.alice, case, BASE)
    second = _indexed_document(api, api.alice, case, BASE + " Ek hüküm.")
    api.become(None)
    api.connection.execute("UPDATE office_case_documents SET deleted_at = NOW() WHERE id = %s", (second,))
    with pytest.raises(HTTPException) as error:
        api.call(api.alice, case, first, second)
    assert error.value.status_code == 404


@needs_db
def test_the_audit_event_records_ids_only_never_names_or_content(api):
    case = _case(api, api.alice)
    first = _indexed_document(api, api.alice, case, BASE, name="gizli-muvekkil-adi.udf")
    second = _indexed_document(api, api.alice, case, BASE + " Ek hüküm.", name="ikinci.udf")

    api.call(api.alice, case, first, second)

    api.become(None)
    [event] = api.connection.execute(
        "SELECT entity_id, metadata FROM activity_logs WHERE action = 'office.case_document_compare' AND entity_id = %s", (first,)
    ).fetchall()
    metadata = event["metadata"] if isinstance(event["metadata"], dict) else json.loads(event["metadata"])
    assert metadata == {"case_id": str(case), "right_document_id": str(second)}
    assert "gizli" not in json.dumps(metadata)


def test_abbreviations_and_numbering_do_not_split_sentences():
    text = (
        "MADDE 1 - İşveren ABC Ltd. Şti. ile işçi anlaştı. Av. Ayşe Yılmaz vekildir. "
        "Karar TBK m. 14 uyarınca verildi. 1. Taraflar anlaştı. A.Ş. kabul etti. Son cümle."
    )
    assert compare.split_units(text) == [
        "MADDE 1 - İşveren ABC Ltd. Şti. ile işçi anlaştı.",
        "Av. Ayşe Yılmaz vekildir.",
        "Karar TBK m. 14 uyarınca verildi.",
        "1. Taraflar anlaştı.",
        "A.Ş. kabul etti.",
        "Son cümle.",
    ]
    # Cümle sonundaki sıradan bir nokta (kısaltma değil) yine bölme yapar.
    assert compare.split_units("Davacı haklıdır. Davalı itiraz etmiştir.") == ["Davacı haklıdır.", "Davalı itiraz etmiştir."]
