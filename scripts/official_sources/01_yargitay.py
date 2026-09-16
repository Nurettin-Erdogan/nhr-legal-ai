"""Yargıtay resmî veri kaynağı için tekil çalıştırma girişi.

Gerçek toplama mantığı ingestion/yargitay ve worker/adapters/yargitay.py içindedir.
"""
from worker.runner import main

if __name__ == "__main__":
    raise SystemExit(main(["run", "--source", "yargitay"]))
