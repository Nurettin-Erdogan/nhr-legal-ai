"""Kamu Denetçiliği Kurumu resmî veri kaynağı için tekil çalıştırma girişi.

Gerçek toplama mantığı ingestion/kdk ve worker/adapters/kdk.py içindedir.
"""
from _entrypoint import run_ingestion

if __name__ == "__main__":
    raise SystemExit(run_ingestion("kdk"))
