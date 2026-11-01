from types import SimpleNamespace

from api.ai.relevance import missing_document_references


def _document(title: str):
    return SimpleNamespace(source_type="document", title=title, content="Kiraya veren Ali Veli, kiracı Ayşe Kaya.")


def test_ascii_file_name_satisfies_accented_document_kind():
    question = "Sözleşmedeki aylık kira bedeli ne kadar?"
    assert missing_document_references(question, [_document("kira_sozlesmesi.txt")]) == set()
    assert missing_document_references(question, [_document("Kira Sözleşmesi.pdf")]) == set()


def test_different_kind_of_document_is_still_reported_missing():
    assert missing_document_references("Sözleşmedeki kira bedeli ne kadar?", [_document("ihtarname.pdf")])
