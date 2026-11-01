from ingestion.text import content_hash
from ingestion.yargitay.chunking import chunk_text
from scripts.repair_next_article_captions import plan_source

TEXT = "Madde 18 - Fesih için geçerli bir sebep gerekir.\nİşverenin vekilleri hakkında bu madde uygulanmaz.\n\nSözleşmenin feshinde usul"


def _source(text=TEXT, stored_hash=None):
    return {"raw_text": text, "content_hash": stored_hash or content_hash(text)}


def _chunks(text=TEXT, size=1800):
    return [{"content": chunk.content} for chunk in chunk_text(text, max_chars=size)]


def test_plan_drops_only_the_caption_and_rehashes():
    plan = plan_source(_source(), _chunks())
    assert plan["new"].endswith("uygulanmaz.")
    assert plan["removed"] == "Sözleşmenin feshinde usul"
    assert plan["new_hash"] == content_hash(plan["new"])
    assert plan["size"] == 1800


def test_clean_text_has_no_plan():
    clean = "Madde 1 - Kanunun amacı hakkında hüküm.\nİkinci cümle burada biter."
    assert plan_source(_source(clean), _chunks(clean)) is None


def test_stored_hash_mismatch_is_skipped_not_guessed():
    assert plan_source(_source(stored_hash="bozuk"), _chunks()) == {"skip": "kayıtlı özet metinle uyuşmuyor"}


def test_unreproducible_chunking_is_skipped():
    assert plan_source(_source(), [{"content": "başka bir metin"}]) == {"skip": "eski parçalama yeniden üretilemedi"}
