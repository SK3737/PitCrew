from typing import Literal

from pydantic import BaseModel, Field

Role = Literal["admin", "mechanic", "owner", "demo"]


class RegisterRequest(BaseModel):
    email: str = Field(..., min_length=3, examples=["owner@example.com"])
    password: str = Field(..., min_length=8, examples=["correct horse battery staple"])
    role: Role = Field("owner", description="Defaults to 'owner' - the least-privileged self-serve role")


class LoginRequest(BaseModel):
    email: str
    password: str


class UserPublic(BaseModel):
    id: int
    email: str
    role: Role


class AccessTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
