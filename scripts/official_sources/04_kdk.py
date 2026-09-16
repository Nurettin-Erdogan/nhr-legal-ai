"""Kamu Denetçiliği Kurumu resmî veri kaynağı için tekil çalıştırma girişi.

Gerçek toplama mantığı ingestion/kdk ve worker/adapters/kdk.py içindedir.
"""
from worker.runner import main

if __name__ == "__main__":
    raise SystemExit(main(["run", "--source", "kdk"]))
