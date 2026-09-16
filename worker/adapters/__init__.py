from worker.adapters.aym import AymSourceAdapter
from worker.adapters.danistay import DanistaySourceAdapter
from worker.adapters.kdk import KdkSourceAdapter
from worker.adapters.mevzuat import MevzuatSourceAdapter
from worker.adapters.planned import (
    MevzuatBilgiSistemiSourceAdapter,
    ResmiGazeteSourceAdapter,
)
from worker.adapters.yargitay import YargitaySourceAdapter

ACTIVE_ADAPTERS = {
    "yargitay": YargitaySourceAdapter,
    "danistay": DanistaySourceAdapter,
    "mevzuat": MevzuatSourceAdapter,
    "kdk": KdkSourceAdapter,
    "aym": AymSourceAdapter,
}

PLANNED_ADAPTERS = {
    "resmi_gazete": ResmiGazeteSourceAdapter,
    "mevzuat_bilgi_sistemi": MevzuatBilgiSistemiSourceAdapter,
}


def get_adapter(source_name: str):
    source_name = source_name.strip().lower()
    if source_name in ACTIVE_ADAPTERS:
        return ACTIVE_ADAPTERS[source_name]()
    if source_name in PLANNED_ADAPTERS:
        return PLANNED_ADAPTERS[source_name]()
    raise KeyError(source_name)
