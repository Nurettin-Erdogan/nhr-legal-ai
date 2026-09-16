"""Bedesten/Mevzuat resmî veri kaynağı için tekil çalıştırma girişi.

Gerçek toplama mantığı ingestion/mevzuat ve worker/adapters/mevzuat.py içindedir.
Resmî Gazete ve Mevzuat Bilgi Sistemi doğrulamaları bu akışın içindedir.
"""
from _entrypoint import run_ingestion

if __name__ == "__main__":
    raise SystemExit(run_ingestion("mevzuat"))
