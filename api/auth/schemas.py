from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)
    full_name: str = Field(min_length=2, max_length=150)
    # Kullanım Şartları ve Gizlilik Politikası/KVKK aydınlatma metni onayı: kayıt için zorunludur; zamanı ve gösterilen metnin
    # sürümü hesaba yazılır.
    terms_accepted: bool = False
    terms_version: str | None = Field(default=None, max_length=40)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class UserResponse(BaseModel):
    id: UUID
    email: EmailStr
    full_name: str | None
    status: str
    roles: list[str]
    created_at: datetime


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserResponse


class AuthStatusResponse(BaseModel):
    configured: bool
    registration_enabled: bool
