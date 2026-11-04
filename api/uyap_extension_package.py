"""Kullanıcıya özel UYAP eklenti paketi: indirilen zipin içine o kullanıcının bağlantı anahtarı gömülür.

Kullanıcı eklentiyi kurunca anahtarla uğraşmaz: eklenti ilk açılışta `jurisai-config.json` dosyasını okuyup anahtarı kendisi
saklar (web/public/jurisai-avukat/background.js, `applyBundledKey`). Anahtar veritabanında yalnız SHA-256 özetiyle durur
(`office_uyap_ingest_tokens`, tetikleyici düz değeri siler); düz değer yalnız bu yanıtın zipinde bulunur ve kaydedilmez.
Paket indirilince önceki etkin anahtarlar iptal edilir: tek kullanıcıya ait eski zip kopyaları çalışmaz hâle gelir.
"""

from __future__ import annotations

import io
import json
import logging
import secrets
import zipfile
from pathlib import Path
from typing import Annotated
from uuid import UUID, uuid4

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Request, Response

from api.audit import AuditContext, record_event
from api.auth.routes import current_user_id
from api.db import authenticated_database_connection

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/uyap-extension", tags=["uyap-extension"])

PACKAGE = Path(__file__).resolve().parents[1] / "web" / "public" / "jurisai-avukat.zip"
CONFIG_NAME = "jurisai-config.json"
LABEL = "Tarayıcı eklentisi (indirilen paket)"


def new_key() -> str:
    """Eklentinin kabul ettiği biçim: `jsai_` + 20-200 harf/rakam (background.js BRIDGE_SET_KEY)."""
    return "jsai_" + secrets.token_hex(24)


def personalise(package: bytes, key: str) -> bytes:
    """Genel paketin içine yalnız yapılandırma dosyasını ekler; diğer dosyalar bayt bayt aynı kalır."""
    source = zipfile.ZipFile(io.BytesIO(package))
    if CONFIG_NAME in source.namelist():
        raise ValueError("Genel pakette zaten bir anahtar dosyası var")
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as target:
        for item in source.infolist():
            target.writestr(item, source.read(item.filename))
        info = zipfile.ZipInfo(CONFIG_NAME, date_time=(1980, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        target.writestr(info, json.dumps({"apiKey": key}) + "\n")
    return out.getvalue()


@router.post("/package")
def download_package(request: Request, user_id: Annotated[UUID, Depends(current_user_id)]) -> Response:
    try:
        package = PACKAGE.read_bytes()
    except OSError as exc:
        logger.exception("Eklenti paketi okunamadı")
        raise HTTPException(status_code=503, detail="Eklenti paketi şu an hazır değil") from exc
    key = new_key()
    try:
        content = personalise(package, key)
    except (ValueError, zipfile.BadZipFile) as exc:
        logger.exception("Eklenti paketi kişiselleştirilemedi")
        raise HTTPException(status_code=503, detail="Eklenti paketi şu an hazır değil") from exc
    try:
        with authenticated_database_connection(str(user_id)) as connection:
            connection.execute("UPDATE office_uyap_ingest_tokens SET revoked = true WHERE owner_id = %s AND NOT revoked", (user_id,))
            connection.execute(
                "INSERT INTO office_uyap_ingest_tokens (id, owner_id, token, label) VALUES (%s, %s, %s, %s)",
                (uuid4(), user_id, key, LABEL),
            )
            record_event(
                connection,
                action="uyap.extension_package_download",
                actor_user_id=user_id,
                context=AuditContext.from_request(request),
                entity_type="office_uyap_ingest_token",
                metadata={"key_prefix": key[:9]},
            )
    except psycopg.Error as exc:
        logger.exception("Eklenti anahtarı kaydedilemedi")
        raise HTTPException(status_code=503, detail="Eklenti anahtarı oluşturulamadı") from exc
    return Response(
        content,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="jurisai-avukat.zip"', "Cache-Control": "no-store"},
    )
