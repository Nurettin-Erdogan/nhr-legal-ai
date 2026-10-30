"""Explicit Turkish public-source registry for the future web research lane.

Exact HTTPS hosts only; no *.gov.tr or implicit subdomain permission. This is
an origin policy, NOT a network fetcher, SSRF resolver or evidence verifier.
Every redirect must be checked again by the transport. Public institutional
pages are not automatically legislation/holdings or current legal evidence.
"""
from dataclasses import dataclass
import re
from urllib.parse import urlsplit


@dataclass(frozen=True)
class OfficialSource:
    key: str
    institution: str
    category: str
    hosts: tuple[str, ...]
    entry_url: str


SOURCES = (
    OfficialSource('mevzuat', 'Mevzuat Bilgi Sistemi', 'legislation',
                   ('mevzuat.gov.tr', 'www.mevzuat.gov.tr'), 'https://www.mevzuat.gov.tr/'),
    OfficialSource('resmi_gazete', 'Resmî Gazete', 'official_publication',
                   ('resmigazete.gov.tr', 'www.resmigazete.gov.tr'), 'https://resmigazete.gov.tr/'),
    OfficialSource('tbmm', 'Türkiye Büyük Millet Meclisi', 'legislative_history',
                   ('tbmm.gov.tr', 'www.tbmm.gov.tr'), 'https://www.tbmm.gov.tr/kanun-ve-karar-bilgi-sistemi'),
    OfficialSource('yargitay', 'Yargıtay', 'court_decisions',
                   ('yargitay.gov.tr', 'www.yargitay.gov.tr', 'karararama.yargitay.gov.tr'), 'https://karararama.yargitay.gov.tr/'),
    OfficialSource('danistay', 'Danıştay', 'court_decisions',
                   ('danistay.gov.tr', 'www.danistay.gov.tr', 'karararama.danistay.gov.tr'), 'https://karararama.danistay.gov.tr/'),
    OfficialSource('aym', 'Anayasa Mahkemesi', 'court_decisions',
                   ('anayasa.gov.tr', 'www.anayasa.gov.tr', 'kararlarbilgibankasi.anayasa.gov.tr',
                    'normkararlarbilgibankasi.anayasa.gov.tr'), 'https://kararlarbilgibankasi.anayasa.gov.tr/kbb/'),
    OfficialSource('uyap_emsal', 'Adalet Bakanlığı / UYAP Emsal', 'court_decisions',
                   ('emsal.uyap.gov.tr', 'kyb.uyap.gov.tr'), 'https://emsal.uyap.gov.tr/'),
    OfficialSource('adalet_mevzuat', 'Adalet Bakanlığı Mevzuat ve İçtihat Programı', 'mixed_legal',
                   ('mevzuat.adalet.gov.tr',), 'https://mevzuat.adalet.gov.tr/'),
    OfficialSource('sayistay', 'Sayıştay', 'institution_decisions',
                   ('sayistay.gov.tr', 'www.sayistay.gov.tr'), 'https://www.sayistay.gov.tr/'),
    OfficialSource('uyusmazlik', 'Uyuşmazlık Mahkemesi', 'court_decisions',
                   ('uyusmazlik.gov.tr', 'www.uyusmazlik.gov.tr'), 'https://www.uyusmazlik.gov.tr/'),
    OfficialSource('kdk', 'Kamu Denetçiliği Kurumu', 'institution_decisions',
                   ('ombudsman.gov.tr', 'www.ombudsman.gov.tr'), 'https://www.ombudsman.gov.tr/'),
    OfficialSource('kvkk', 'Kişisel Verileri Koruma Kurumu', 'institution_decisions',
                   ('kvkk.gov.tr', 'www.kvkk.gov.tr'), 'https://www.kvkk.gov.tr/'),
    OfficialSource('rekabet', 'Rekabet Kurumu', 'institution_decisions',
                   ('rekabet.gov.tr', 'www.rekabet.gov.tr'), 'https://www.rekabet.gov.tr/'),
    OfficialSource('kik', 'Kamu İhale Kurumu', 'institution_decisions',
                   ('ihale.gov.tr', 'www.ihale.gov.tr', 'ekapv2.kik.gov.tr'), 'https://www.ihale.gov.tr/'),
    OfficialSource('tuik', 'Türkiye İstatistik Kurumu', 'official_statistics',
                   ('tuik.gov.tr', 'www.tuik.gov.tr', 'data.tuik.gov.tr', 'veriportali.tuik.gov.tr'), 'https://veriportali.tuik.gov.tr/'),
    OfficialSource('tcmb', 'Türkiye Cumhuriyet Merkez Bankası', 'official_financial_data',
                   ('tcmb.gov.tr', 'www.tcmb.gov.tr', 'evds3.tcmb.gov.tr'), 'https://www.tcmb.gov.tr/'),
    OfficialSource('csgb', 'Çalışma ve Sosyal Güvenlik Bakanlığı', 'official_guidance',
                   ('csgb.gov.tr', 'www.csgb.gov.tr'), 'https://www.csgb.gov.tr/'),
    OfficialSource('sgk', 'Sosyal Güvenlik Kurumu', 'official_guidance',
                   ('sgk.gov.tr', 'www.sgk.gov.tr'), 'https://www.sgk.gov.tr/'),
    OfficialSource('gib', 'Gelir İdaresi Başkanlığı', 'official_guidance',
                   ('gib.gov.tr', 'www.gib.gov.tr'), 'https://www.gib.gov.tr/'),
    OfficialSource('hmb', 'Hazine ve Maliye Bakanlığı', 'official_financial_data',
                   ('hmb.gov.tr', 'www.hmb.gov.tr'), 'https://www.hmb.gov.tr/'),
    OfficialSource('ticaret', 'Ticaret Bakanlığı', 'official_guidance',
                   ('ticaret.gov.tr', 'www.ticaret.gov.tr'), 'https://www.ticaret.gov.tr/'),
)

_BY_HOST = {host: source for source in SOURCES for host in source.hosts}
if len(_BY_HOST) != sum(len(source.hosts) for source in SOURCES):
    raise ValueError('Official source registry has duplicate hosts')


def source_for_url(url: str) -> OfficialSource | None:
    """Reject ambiguous authorities rather than normalizing them into permission."""
    if (not isinstance(url, str) or not url
            or re.search(r'[\x00-\x20\x7f\\]', url)):
        return None
    try:
        parsed = urlsplit(url)
        if (parsed.scheme.lower() != 'https' or parsed.username is not None
                or parsed.password is not None or parsed.port not in (None, 443)
                or not parsed.hostname or not parsed.netloc.isascii() or '%' in parsed.netloc
                or parsed.hostname.endswith('.')):
            return None
        return _BY_HOST.get(parsed.hostname.lower())
    except ValueError:
        return None


def require_official_url(url: str) -> OfficialSource:
    source = source_for_url(url)
    if source is None:
        raise ValueError('URL is outside the explicit official-source policy')
    return source


def validate_redirect_chain(urls: tuple[str, ...]) -> tuple[OfficialSource, ...]:
    """Validate each observed hop, not just its original or final URL.

    Future transport must ALSO resolve/recheck public destination IPs, enforce
    TLS/content limits, disable ambient credentials and exclude private queries.
    """
    if not urls or len(urls) > 6:
        raise ValueError('Missing or excessive redirect chain')
    return tuple(require_official_url(url) for url in urls)
