"""NHR Legal Data Collector — resmi hukuk kaynakları için ingestion worker."""

from __future__ import annotations

__all__ = ["ACTIVE_SOURCES", "OPTIONAL_SOURCES", "PLANNED_SOURCES"]

ACTIVE_SOURCES = ("yargitay", "danistay", "mevzuat", "kdk", "aym")
OPTIONAL_SOURCES = ("mevzuat_verify",)
PLANNED_SOURCES = ("resmi_gazete", "mevzuat_bilgi_sistemi")
