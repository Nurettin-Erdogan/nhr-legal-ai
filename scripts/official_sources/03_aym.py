"""Anayasa Mahkemesi resmî veri kaynağı için tekil çalıştırma girişi.

Gerçek toplama mantığı ingestion/aym ve worker/adapters/aym.py içindedir.
"""
from worker.runner import main

if __name__ == "__main__":
    raise SystemExit(main(["run", "--source", "aym"]))
