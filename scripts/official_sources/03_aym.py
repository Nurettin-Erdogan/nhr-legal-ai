"""Anayasa Mahkemesi resmî veri kaynağı için tekil çalıştırma girişi.

Gerçek toplama mantığı ingestion/aym ve worker/adapters/aym.py içindedir.
"""
from _entrypoint import run_ingestion

if __name__ == "__main__":
    raise SystemExit(run_ingestion("aym"))
