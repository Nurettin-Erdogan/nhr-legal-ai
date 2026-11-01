"""T.C. Mevzuat Bilgi Sistemi doğrulama kaynağı için tekil kontrol girişi.

Bu kaynak Bedesten'den alınan mevzuatın numara, başlık, Resmî Gazete künyesi
ve resmî konsolide PDF/DOC bağlantılarını doğrular.
"""
from _entrypoint import run_verification

if __name__ == "__main__":
    raise SystemExit(run_verification("mevzuat_bilgi_sistemi"))
