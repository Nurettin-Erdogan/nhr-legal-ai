from worker.adapters.mevzuat import MevzuatSourceAdapter
from worker.adapters.planned import (
    AymSourceAdapter,
    DanistaySourceAdapter,
    KdkSourceAdapter,
    ResmiGazeteSourceAdapter,
)
from worker.adapters.yargitay import YargitaySourceAdapter

ACTIVE_ADAPTERS = {
    "yargitay": YargitaySourceAdapter,
    "mevzuat": MevzuatSourceAdapter,
}

PLANNED_ADAPTERS = {
    "danistay": DanistaySourceAdapter,
    "aym": AymSourceAdapter,
    "resmi_gazete": ResmiGazeteSourceAdapter,
    "kdk": KdkSourceAdapter,
}


def get_adapter(source_name: str):
    source_name = source_name.strip().lower()
    if source_name in ACTIVE_ADAPTERS:
        return ACTIVE_ADAPTERS[source_name]()
    if source_name in PLANNED_ADAPTERS:
        return PLANNED_ADAPTERS[source_name]()
    raise KeyError(source_name)
