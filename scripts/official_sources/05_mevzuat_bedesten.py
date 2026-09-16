"""Bedesten/Mevzuat resmî veri kaynağı için tekil çalıştırma girişi.

Gerçek toplama mantığı ingestion/mevzuat ve worker/adapters/mevzuat.py içindedir.
Resmî Gazete ve Mevzuat Bilgi Sistemi doğrulamaları bu akışın içindedir.
"""
from worker.runner import main

if __name__ == "__main__":
    raise SystemExit(main(["run", "--source", "mevzuat"]))
