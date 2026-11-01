import socket
import pytest

from api.ai import official_transport as transport


@pytest.mark.parametrize('address', ['127.0.0.1', '10.0.0.2', '169.254.169.254', '::1', 'fc00::1'])
def test_private_dns_rejected(monkeypatch, address):
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *a, **k: [(0, 0, 0, '', (address, 443))])
    with pytest.raises(transport.OfficialFetchError):
        transport.public_addresses('www.mevzuat.gov.tr')


def install(monkeypatch, responses):
    calls = []
    monkeypatch.setattr(transport, 'public_addresses', lambda host: ('8.8.8.8',))

    class Connection:
        def __init__(self, host, address, timeout):
            calls.append((host, address))
        def request(self, method, target, headers):
            assert method == 'GET'
            assert 'Authorization' not in headers and 'Cookie' not in headers
        def getresponse(self):
            status, headers, body = responses.pop(0)
            class Response:
                def getheader(self, name, default=None):
                    return headers.get(name, default)
                def read(self, size):
                    return body[:size]
            result = Response()
            result.status = status
            return result
        def close(self):
            pass
    monkeypatch.setattr(transport, '_PinnedHTTPS', Connection)
    return calls


def test_external_redirect_never_connected(monkeypatch):
    calls = install(monkeypatch, [(302, {'Location': 'https://example.com/'}, b'')])
    with pytest.raises(ValueError):
        transport.fetch_public_document('https://www.mevzuat.gov.tr/')
    assert len(calls) == 1


def test_allowed_redirect_and_document(monkeypatch):
    calls = install(monkeypatch, [
        (302, {'Location': 'https://veriportali.tuik.gov.tr/'}, b''),
        (200, {'Content-Type': 'text/html; charset=utf-8'}, b'public document'),
    ])
    result = transport.fetch_public_document('https://data.tuik.gov.tr/')
    assert result.body == b'public document'
    assert len(result.redirects) == len(calls) == 2


@pytest.mark.parametrize('status,headers,body', [
    (403, {}, b'denied'), (429, {}, b'wait'), (500, {}, b'error'),
    (200, {'Content-Type': 'application/octet-stream'}, b'executable'),
    (200, {'Content-Type': 'text/html', 'Content-Encoding': 'gzip'}, b'compressed'),
    (200, {'Content-Type': 'text/html', 'Content-Length': '999'}, b'large'),
    (200, {'Content-Type': 'text/html'}, b'123456789'),
    (200, {'Content-Type': 'text/html'}, b''),
])
def test_unusable_responses_fail_closed(monkeypatch, status, headers, body):
    install(monkeypatch, [(status, headers, body)])
    with pytest.raises(transport.OfficialFetchError):
        transport.fetch_public_document('https://www.mevzuat.gov.tr/', max_bytes=8)


@pytest.mark.parametrize('url', ['https://www.mevzuat.gov.tr/login',
    'https://karararama.yargitay.gov.tr/delete', 'https://example.com/aramadetaylist'])
def test_post_is_limited_to_observed_public_search_endpoints(url):
    with pytest.raises(transport.OfficialFetchError):
        transport._request(url, body=b'{}')


def test_aym_binary_attachment_only_on_exact_public_attachment_path(monkeypatch):
    install(monkeypatch, [(200, {'Content-Type': 'application/octet-stream'}, b'PK-udf')])
    document = transport.fetch_public_document(
        'https://kararlarbilgibankasi.anayasa.gov.tr/api/core/public/files/download-attachment/123')
    assert document.body == b'PK-udf'
    install(monkeypatch, [(200, {'Content-Type': 'application/octet-stream'}, b'PK-udf')])
    with pytest.raises(transport.OfficialFetchError):
        transport.fetch_public_document('https://kararlarbilgibankasi.anayasa.gov.tr/other')
