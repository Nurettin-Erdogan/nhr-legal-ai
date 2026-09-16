"""Danıştay resmî veri kaynağı için tekil çalıştırma girişi.

Gerçek toplama mantığı ingestion/danistay ve worker/adapters/danistay.py içindedir.
"""
from worker.runner import main

if __name__ == "__main__":
    raise SystemExit(main(["run", "--source", "danistay"]))
