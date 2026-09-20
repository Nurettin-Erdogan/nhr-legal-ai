from ingestion.source_errors import (
    is_rate_limited,
    is_transient_transport,
    is_verification_cooldown_error,
    should_retry_same_record,
)


def test_rate_limit_and_connection_errors_retry_same_record():
    assert is_rate_limited("Bedesten HTTP 429; kaynak hız sınırı")
    assert is_rate_limited("Yargitay HTTP 429; kaynak hiz siniri")
    assert is_transient_transport(
        "[WinError 10054] Varolan bir bağlantı uzaktaki bir ana bilgisayar tarafından zorla kapatıldı"
    )
    assert should_retry_same_record("HTTP 429")
    assert should_retry_same_record("connection reset")


def test_document_specific_errors_are_skipped():
    assert not should_retry_same_record(
        "Runtime exception:{0}:Belge alma isleminde hata olustu. pid:null"
    )
    assert not should_retry_same_record("Danıştay karar sayfasında hiddencontent bulunamadı")
    assert not should_retry_same_record("Karar metni bos veya gecersiz: 12")


def test_verification_cooldown_covers_mbs_html_and_http_5xx():
    assert is_verification_cooldown_error("MBS arama ucu JSON olmayan yanıt döndürdü")
    assert is_verification_cooldown_error("Resmî Gazete HTTP hatası: 500")
    assert is_verification_cooldown_error("MBS HTTP hatası: 429")
    assert is_verification_cooldown_error("Bedesten HTTP 429")
    assert not is_verification_cooldown_error("tekil MBS kaydı yok")
    assert not is_verification_cooldown_error(
        "MBS detay sayfasında tekil resmî PDF/DOC bağlantısı bulunamadı"
    )
