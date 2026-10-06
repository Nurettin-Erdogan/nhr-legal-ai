"""Bir hesap için tek kullanımlık şifre sıfırlama bağlantısı üretir (yönetici aracı).

E-posta (SMTP) yapılandırılmamış kurulumlarda "Şifremi unuttum" isteği bağlantıyı e-postayla gönderemez. Yönetici, kullanıcının
kimliğini başka yoldan doğruladıktan sonra bu betikle bağlantı üretir ve kullanıcıya güvenli bir kanaldan iletir. Bağlantı 60 dakika
geçerlidir ve bir kez kullanılabilir; anahtarın yalnız özeti veritabanına yazılır. Önceki açık bağlantılar geçersiz olur.

    .venv\\Scripts\\python.exe scripts\\create_password_reset_link.py kullanici@ornek.com
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> int:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    sys.stdout.reconfigure(encoding="utf-8")
    if len(sys.argv) != 2 or "@" not in sys.argv[1]:
        print("Kullanım: create_password_reset_link.py <e-posta>")
        return 2
    from api import account
    from api.audit import record_event
    from api.db import admin_database_connection

    email = sys.argv[1].strip().lower()
    with admin_database_connection() as connection, connection.transaction():
        row = connection.execute("SELECT id FROM users WHERE email = %s AND deleted_at IS NULL AND status = 'active'", (email,)).fetchone()
        if row is None:
            print("Bu e-postayla etkin bir hesap bulunamadı.")
            return 1
        token = account.create_reset_token(connection, row["id"])
        record_event(connection, action=account.PASSWORD_RESET_REQUEST, actor_user_id=None, entity_type="user", entity_id=row["id"],
                     metadata={"delivery": "admin_script"}, strict=False)
    print(f"Sıfırlama bağlantısı ({account.RESET_TOKEN_MINUTES} dakika geçerli, tek kullanımlık):")
    print(account.reset_link(token))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
