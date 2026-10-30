"""Collection-scoped acquisition plan; a registered host is not an importer.

Corpus counters are stored-record estimates, never proof of source coverage or
official text verification. No private workspace data belongs in this report.
"""
from dataclasses import dataclass
from api.ai.official_sources import SOURCES


@dataclass(frozen=True)
class CollectionPlan:
    source: str
    collection: str
    capability: str
    priority: int
    module: str | None = None


COLLECTIONS = (
    CollectionPlan('mevzuat', 'Konsolide mevzuat ve madde sürümleri', 'verification_and_refresh', 1, 'ingestion.mevzuat_bilgi_sistemi.portal'),
    CollectionPlan('resmi_gazete', 'Yayımlanan hukuki düzenlemeler ve değişiklik künyeleri', 'verification_only', 1, 'ingestion.resmi_gazete.portal'),
    CollectionPlan('tbmm', 'Kanun kabul metinleri ve yasama geçmişi', 'adapter_missing', 2),
    CollectionPlan('yargitay', 'Yayımlanan kararların tam metni ve künyesi', 'worker_adapter', 1, 'worker.adapters.yargitay'),
    CollectionPlan('danistay', 'Yayımlanan kararların tam metni ve künyesi', 'worker_adapter', 1, 'worker.adapters.danistay'),
    CollectionPlan('aym', 'Bireysel başvuru kararları', 'worker_adapter', 1, 'worker.adapters.aym'),
    CollectionPlan('aym', 'Norm denetimi kararları', 'worker_adapter', 1, 'worker.adapters.aym'),
    CollectionPlan('aym', 'Siyasi parti kararları', 'worker_adapter', 2, 'worker.adapters.aym'),
    CollectionPlan('aym', 'Yüce Divan kararları', 'worker_adapter', 2, 'worker.adapters.aym'),
    CollectionPlan('aym', 'Yasama dokunulmazlığı kararları', 'worker_adapter', 2, 'worker.adapters.aym'),
    CollectionPlan('uyap_emsal', 'Kamuya açık emsal kararlar; kişisel UYAP oturumları hariç', 'hub_adapter', 1, 'ingestion.bedesten_emsal'),
    CollectionPlan('adalet_mevzuat', 'Mevzuat ve içtihat yayınları; ana kaynaklarla tekilleştirilmiş', 'adapter_missing', 2),
    CollectionPlan('sayistay', 'Yargı kararları ve kurum karar koleksiyonları', 'portal_and_parser', 2, 'ingestion.sayistay.portal'),
    CollectionPlan('uyusmazlik', 'Yayımlanan mahkeme kararları', 'portal_and_parser', 2, 'ingestion.uyusmazlik.portal'),
    CollectionPlan('kdk', 'Yayımlanan tavsiye ve kurum kararları', 'worker_adapter', 2, 'worker.adapters.kdk'),
    CollectionPlan('kvkk', 'Yayımlanan kurul kararları ve karar özetleri ayrı türler', 'adapter_missing', 2),
    CollectionPlan('rekabet', 'Yayımlanan kurul kararları', 'portal_and_parser', 2, 'ingestion.rekabet.portal'),
    CollectionPlan('kik', 'Yayımlanan kurul kararları', 'adapter_missing', 2),
    CollectionPlan('tuik', 'Hukuki hesaplarda kullanılan tarihli resmî endeks bültenleri', 'adapter_missing', 2),
    CollectionPlan('tcmb', 'Tarihli resmî faiz, kur ve ilgili duyurular', 'adapter_missing', 2),
    CollectionPlan('csgb', 'Çalışma mevzuatı, tarihli resmî tutar ve duyurular', 'adapter_missing', 2),
    CollectionPlan('sgk', 'Sosyal güvenlik mevzuatı ve yayımlanan genelgeler', 'adapter_missing', 2),
    CollectionPlan('gib', 'Vergi mevzuatı, genelgeler ve yayımlanan özelgeler', 'adapter_missing', 2),
    CollectionPlan('hmb', 'Mali mevzuat ve tarihli resmî tutar duyuruları', 'adapter_missing', 2),
    CollectionPlan('ticaret', 'Ticaret/tüketici mevzuatı ve resmî düzenleme duyuruları', 'adapter_missing', 2),
)


def coverage_state(*, enumerated: bool = False, official_ids: int | None = None,
                   imported_ids: int | None = None, verified_ids: int | None = None,
                   unresolved: int | None = None) -> str:
    """Only a complete, collection-scoped ID inventory can establish coverage.

    Caller must count unique IDs in the SAME frozen official inventory, not
    compare a portal search estimate against all locally stored revisions.
    """
    values = (official_ids, imported_ids, verified_ids, unresolved)
    if any(v is not None and (type(v) is not int or v < 0) for v in values):
        raise ValueError('Invalid coverage counts')
    if not enumerated or any(v is None for v in values):
        return 'coverage_unknown'
    if imported_ids > official_ids or verified_ids > imported_ids:
        return 'inventory_inconsistent'
    return 'snapshot_complete' if official_ids == imported_ids == verified_ids and unresolved == 0 else 'incomplete'


def collection_report():
    by_source = {s.key: s for s in SOURCES}
    if set(by_source) != {c.source for c in COLLECTIONS}:
        raise ValueError('Every registered institution needs an explicit collection plan')
    return [dict(source=c.source, institution=by_source[c.source].institution,
        official_entry=by_source[c.source].entry_url, collection=c.collection,
        capability=c.capability, module=c.module, priority=c.priority,
        coverage=coverage_state(), official_inventory_total=None,
        verified_unique_ids_in_inventory=None, unresolved_ids=None,
        live_contract_test='not_run', terms_and_bulk_access_review='pending') for c in COLLECTIONS]
