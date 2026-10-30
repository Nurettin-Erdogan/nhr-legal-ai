import pytest

from api.ai.official_sources import SOURCES, require_official_url, source_for_url, validate_redirect_chain


@pytest.mark.parametrize('source', SOURCES, ids=lambda s: s.key)
def test_registry_entry_urls_and_exact_hosts_match(source):
    assert source_for_url(source.entry_url) == source
    for host in source.hosts:
        assert source_for_url('https://' + host + '/example.pdf') == source


@pytest.mark.parametrize('url', [
    'http://www.mevzuat.gov.tr/', 'https://www.mevzuat.gov.tr.attacker.com/',
    'https://attacker.mevzuat.gov.tr/', 'https://another.gov.tr/',
    'https://www.mevzuat.gov.tr@attacker.com/', 'https://user@www.mevzuat.gov.tr/',
    'https://127.0.0.1/', 'https://[::1]/', 'file:///etc/passwd',
    'https://www.mevzuat.gov.tr:444/', 'https://www.mevzuat.gov.tr./',
    'https://www.mevzuat.gov.tr%2eattacker.com/', 'https://www.mevzuat.gov.tr\\@attacker.com/',
    'https://www.mevzuat.gov.tr/\n', '//www.mevzuat.gov.tr/',
    'https://www.mevzuat.gov.tr:invalid/', 'https://mеvzuat.gov.tr/',
    'https://avukat.example/', 'https://www.google.com/search?q=kanun',
    'https://vatandas.uyap.gov.tr/', 'https://avukat.uyap.gov.tr/',
])
def test_no_wildcard_or_private_portal_or_url_parser_bypass(url):
    assert source_for_url(url) is None
    with pytest.raises(ValueError):
        require_official_url(url)


def test_tuik_redirect_is_explicit_but_external_redirect_is_not_allowed():
    assert len(validate_redirect_chain(('https://data.tuik.gov.tr/', 'https://veriportali.tuik.gov.tr/'))) == 2
    with pytest.raises(ValueError):
        validate_redirect_chain(('https://www.tuik.gov.tr/', 'https://attacker.com/', 'https://www.tuik.gov.tr/'))
    with pytest.raises(ValueError):
        validate_redirect_chain(())


def test_https_default_port_and_case_are_unambiguous():
    assert source_for_url('https://WWW.MEVZUAT.GOV.TR:443/') is not None
    assert source_for_url('https://www.mevzuat.gov.tr/İş-Kanunu') is not None
