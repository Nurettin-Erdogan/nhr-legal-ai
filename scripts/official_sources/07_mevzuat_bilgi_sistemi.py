"""T.C. Mevzuat Bilgi Sistemi doğrulama kaynağı için tekil kontrol girişi.

Bu kaynak Bedesten'den alınan mevzuatın numara, başlık, Resmî Gazete künyesi
ve resmî konsolide PDF/DOC bağlantılarını doğrular.
"""
import json
from worker.adapters import get_adapter

if __name__ == "__main__":
    health = get_adapter("mevzuat_bilgi_sistemi").health_check()
    print(json.dumps({
        "source": health.source_name,
        "mode": "verification",
        "health": health.state,
        "detail": health.detail,
    }, ensure_ascii=False, indent=2))
