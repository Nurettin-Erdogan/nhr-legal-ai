"""Shared CLI glue for the seven independent official-source entry points.

The actual ingestion and verification clients remain in worker/ and ingestion/.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


# Direct execution (`python scripts/official_sources/01_yargitay.py`) otherwise
# puts only this directory on sys.path, not the repository root.
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def run_ingestion(source: str) -> int:
    from worker.runner import main

    return main(["run", "--source", source, *sys.argv[1:]])


def run_verification(source: str) -> int:
    parser = argparse.ArgumentParser(
        description=(
            f"{source}: resmî portal erişimi için örnek mevzuat künyesiyle smoke kontrolü. "
            "Bağımsız korpus aktarımı yapmaz."
        )
    )
    parser.parse_args()

    from worker.adapters import get_adapter

    health = get_adapter(source).health_check()
    print(
        json.dumps(
            {
                "source": health.source_name,
                "mode": "verification_smoke",
                "health": health.state,
                "detail": health.detail,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if health.state == "healthy" else 1
