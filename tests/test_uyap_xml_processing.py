import pytest

from api.document_processing import DocumentProcessingError, process_document


def test_xml_preserves_labels_attributes_mixed_text_and_original_checksum():
    data = '<dava id="örnek"><konu>Haciz <tür>talebi</tür> hakkında</konu></dava>'.encode()
    result = process_document("dosya.xml", data)
    text = "\n".join(chunk.content for chunk in result.chunks)
    assert "dava/@id: örnek" in text and "dava/konu/tür: talebi" in text
    assert "hakkında" in text and result.mime_type == "application/xml"


@pytest.mark.parametrize("encoding", ["utf-8", "utf-16", "utf-32"])
def test_xml_rejects_dtd_and_entities_in_all_supported_encodings(encoding):
    data = '<!DOCTYPE a [<!ENTITY x SYSTEM "file:///private">]><a>&x;</a>'.encode(encoding)
    with pytest.raises(DocumentProcessingError, match="DTD"):
        process_document("dosya.xml", data)


@pytest.mark.parametrize("data", [b"<root/>", b"<broken>", b"<a>" + b"A" * 1000 + b"</a>"])
def test_xml_empty_broken_and_embedded_binary_are_not_search_ready(data):
    with pytest.raises(DocumentProcessingError):
        process_document("dosya.xml", data)


def test_legacy_type_detection_is_opt_in_and_never_assumes_unknown_is_pdf():
    data = b'<?xml version="1.0"?><dava><konu>Ornek belge</konu></dava>'
    with pytest.raises(DocumentProcessingError, match="içerik PDF değil"):
        process_document("eski.pdf", data)
    assert process_document("eski.pdf", data, detect_type=True).extension == ".xml"
    with pytest.raises(DocumentProcessingError):
        process_document("yanlis.pdf", b"unknown binary", detect_type=True)


def test_xml_structure_and_size_budgets(monkeypatch):
    from api import document_processing as processing
    with pytest.raises(DocumentProcessingError, match="yapı sınır"):
        process_document("dosya.xml", ("<a>" * 66 + "Metin" + "</a>" * 66).encode())
    monkeypatch.setattr(processing, "MAX_XML_BYTES", 5)
    with pytest.raises(DocumentProcessingError, match="boyut"):
        process_document("dosya.xml", b"<a>Metin</a>")


def test_xml_path_and_output_cannot_amplify_small_inputs(monkeypatch):
    from api import document_processing as processing
    with pytest.raises(DocumentProcessingError, match="etiket yolu"):
        process_document("dosya.xml", ("<" + "a" * 5000 + ">Metin</" + "a" * 5000 + ">").encode())
    monkeypatch.setattr(processing, "MAX_XML_OUTPUT_CHARS", 10)
    with pytest.raises(DocumentProcessingError, match="çıktı sınır"):
        process_document("dosya.xml", b"<a>Some example text here</a>")


def test_signature_bytes_are_not_legal_text_but_following_body_text_is_preserved():
    data = ('<dava xmlns:ds="http://www.w3.org/2000/09/xmldsig#">Önceki metin'
            '<ds:Signature><ds:SignatureValue>' + 'A' * 1000 +
            '</ds:SignatureValue></ds:Signature>Sonraki metin</dava>').encode()
    text = '\n'.join(chunk.content for chunk in process_document('dosya.xml', data).chunks)
    assert 'Önceki metin' in text and 'Sonraki metin' in text
    assert 'AAAA' not in text
