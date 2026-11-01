"""Yargıtay resmî veri kaynağı için tekil çalıştırma girişi.

Gerçek toplama mantığı ingestion/yargitay ve worker/adapters/yargitay.py içindedir.
"""
from _entrypoint import run_ingestion

if __name__ == "__main__":
    raise SystemExit(run_ingestion("yargitay"))
