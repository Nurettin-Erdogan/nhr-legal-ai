"""NHR Legal Data Collector — resmi hukuk kaynakları için ingestion worker."""

from __future__ import annotations

__all__ = ["ACTIVE_SOURCES", "PLANNED_SOURCES"]

ACTIVE_SOURCES = ("yargitay", "danistay", "mevzuat", "kdk")
PLANNED_SOURCES = ("aym", "resmi_gazete")
