"""T.C. Resmî Gazete doğrulama kaynağı için tekil kontrol girişi.

Bu kaynak ayrı korpus kopyası üretmez; mevzuat kayıtlarının tarih, sayı ve
numara künyesini resmî arşiv üzerinden doğrular.
"""
from _entrypoint import run_verification

if __name__ == "__main__":
    raise SystemExit(run_verification("resmi_gazete"))
