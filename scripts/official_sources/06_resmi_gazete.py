"""T.C. Resmî Gazete doğrulama kaynağı için tekil kontrol girişi.

Bu kaynak ayrı korpus kopyası üretmez; mevzuat kayıtlarının tarih, sayı ve
numara künyesini resmî arşiv üzerinden doğrular.
"""
import json
from worker.adapters import get_adapter

if __name__ == "__main__":
    health = get_adapter("resmi_gazete").health_check()
    print(json.dumps({
        "source": health.source_name,
        "mode": "verification",
        "health": health.state,
        "detail": health.detail,
    }, ensure_ascii=False, indent=2))
