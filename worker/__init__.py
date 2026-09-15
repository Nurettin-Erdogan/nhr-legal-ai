"""NHR Legal Data Collector — resmi hukuk kaynakları için ingestion worker."""

from __future__ import annotations

__all__ = ["ACTIVE_SOURCES", "PLANNED_SOURCES"]

ACTIVE_SOURCES = ("yargitay", "mevzuat")
PLANNED_SOURCES = ("danistay", "aym", "resmi_gazete")
