from __future__ import annotations

from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=50)
    password: str = Field(..., min_length=1)
    totp_code: Optional[str] = Field(default=None, min_length=6, max_length=6)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
    user_id: str
    role: str
    lang: str


class RefreshRequest(BaseModel):
    refresh_token: str


class UserMeResponse(BaseModel):
    id: UUID
    username: str
    full_name_ar: str
    full_name_en: Optional[str]
    email: Optional[str]
    role: str
    preferred_language: str
    is_active: bool
    totp_enabled: bool
    dark_mode: bool

    model_config = {"from_attributes": True}
