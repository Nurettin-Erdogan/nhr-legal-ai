"""Bounded, credential-free HTTPS transport for official public documents.

Downloaded bytes are NOT verified legal evidence. Adapters must check document
identity, extract the full text and persist its provenance before citation.
"""
from dataclasses import dataclass
import http.client
import ipaddress
import socket
import ssl
from urllib.parse import urljoin, urlsplit

from api.ai.official_sources import require_official_url


class OfficialFetchError(ValueError):
    pass


@dataclass(frozen=True)
class PublicDocument:
    url: str
    content_type: str
    body: bytes
    redirects: tuple[str, ...]


def public_addresses(host: str) -> tuple[str, ...]:
    addresses = tuple(dict.fromkeys(
        row[4][0] for row in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    ))
    if not addresses or any(not ipaddress.ip_address(ip).is_global for ip in addresses):
        raise OfficialFetchError('Official host did not resolve exclusively to public addresses')
    return addresses


class _PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, host, address, timeout):
        super().__init__(host, timeout=timeout, context=ssl.create_default_context())
        self._address = address

    def connect(self):
        # DNS is not resolved a second time between validation and connection.
        sock = socket.create_connection((self._address, 443), self.timeout)
        try:
            self.sock = self._context.wrap_socket(sock, server_hostname=self.host)
        except BaseException:
            sock.close()
            raise


def fetch_public_document(url: str, *, timeout: float = 30,
                          max_bytes: int = 12 * 1024 * 1024) -> PublicDocument:
    """GET only. No cookies, auth, ambient proxy, compression or automatic retries.

    Each redirect is allowlisted and freshly DNS checked. CAPTCHA, rate limits,
    access denial and non-document responses stop the request, never bypass it.
    """
    return _request(url, timeout=timeout, max_bytes=max_bytes)


def _request(url, *, timeout=30, max_bytes=12 * 1024 * 1024, body=None):
    if not 0 < timeout <= 120 or not 0 < max_bytes <= 32 * 1024 * 1024:
        raise OfficialFetchError('Invalid transport limits')
    if body is not None:
        parsed = urlsplit(url)
        allowed = {
            ('www.mevzuat.gov.tr', '/anasayfa/MevzuatDatatable'),
            ('karararama.yargitay.gov.tr', '/detayliArama'),
            ('karararama.yargitay.gov.tr', '/aramadetaylist'),
            ('kararlarbilgibankasi.anayasa.gov.tr', '/api/core/public/search'),
        }
        if (parsed.hostname, parsed.path) not in allowed or parsed.query or len(body) > 16384:
            raise OfficialFetchError('Unsupported public search request')
    chain = []
    for _ in range(6):
        require_official_url(url)
        if url in chain:
            raise OfficialFetchError('Redirect loop')
        chain.append(url)
        parsed = urlsplit(url)
        addresses = public_addresses(parsed.hostname)
        connection = _PinnedHTTPS(parsed.hostname, addresses[0], timeout)
        try:
            target = parsed.path or '/'
            if parsed.query:
                target += '?' + parsed.query
            headers = {
                'User-Agent': 'JurisAI/0.1 (official-public-document-research)',
                'Accept': 'text/html, application/pdf, text/plain, application/json',
                'Accept-Encoding': 'identity',
            }
            if body is not None:
                headers['Content-Type'] = 'application/json; charset=utf-8'
                connection.request('POST', target, body=body, headers=headers)
            else:
                connection.request('GET', target, headers=headers)
            response = connection.getresponse()
            if response.status in (301, 302, 303, 307, 308):
                if body is not None:
                    raise OfficialFetchError('Public search POST redirect refused')
                location = response.getheader('Location')
                if not location:
                    raise OfficialFetchError('Missing redirect destination')
                url = urljoin(url, location)
                continue
            if response.status != 200:
                raise OfficialFetchError(f'Official source HTTP {response.status}')
            if response.getheader('Content-Encoding', 'identity').lower() != 'identity':
                raise OfficialFetchError('Unsupported content encoding')
            content_type = response.getheader('Content-Type', '').split(';')[0].strip().lower()
            aym_attachment = (parsed.hostname == 'kararlarbilgibankasi.anayasa.gov.tr'
                and parsed.path.startswith('/api/core/public/files/download-attachment/'))
            attachment_type = aym_attachment and content_type in (
                'application/octet-stream', 'application/zip', 'application/x-zip-compressed',
                'application/xml', 'text/xml')
            if content_type not in ('text/html', 'application/pdf', 'text/plain', 'application/json') and not attachment_type:
                raise OfficialFetchError('Unsupported document content type')
            length = response.getheader('Content-Length')
            if length is not None:
                try:
                    size = int(length)
                except ValueError:
                    raise OfficialFetchError('Invalid document length') from None
                if size < 0 or size > max_bytes:
                    raise OfficialFetchError('Document exceeds size limit')
            body = response.read(max_bytes + 1)
            if not body or len(body) > max_bytes:
                raise OfficialFetchError('Empty or oversized document')
            return PublicDocument(url, content_type, body, tuple(chain))
        finally:
            connection.close()
    raise OfficialFetchError('Too many redirects')


class OfficialOpener:
    """Injectable bridge for existing official portal parsers; no ambient state.

    Only adapter-generated numeric law IDs or controlled legal vocabulary may
    reach this bridge. Never give it a user's raw question or uploaded text.
    """
    def open(self, request, timeout=30):
        from io import BytesIO
        if request.get_method() not in ('GET', 'POST'):
            raise OfficialFetchError('Unsupported method')
        document = _request(request.full_url, timeout=timeout, body=request.data)
        return BytesIO(document.body)
