"""Request and response models for authentication.

Note what is absent from every response model: `password` and
`password_hash`. They are not "excluded later" — they were never fields on a
response schema, so there is no code path that can leak them.
"""

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, EmailStr, Field, field_validator

# 8 characters, following the spec and current NIST guidance: length is what
# matters, and forcing symbols/digits/uppercase pushes people toward
# "Password1!" rather than a genuinely strong passphrase.
MIN_PASSWORD_LENGTH = 8

# An upper bound so a multi-megabyte "password" cannot be used to burn CPU in
# the hasher. Argon2id has no short ceiling of its own, unlike bcrypt's 72
# bytes, so this is purely a denial-of-service guard.
MAX_PASSWORD_LENGTH = 256

PasswordText = Annotated[
    str, Field(min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH)
]


class _EmailNormalisingModel(BaseModel):
    """Shared email handling for the credential models.

    Email is lowercased and trimmed so "User@Example.COM " and
    "user@example.com" are the same account. Normalising in the schema means
    it happens once, at the edge, and every layer below sees the canonical
    form — including the unique index.
    """

    email: EmailStr

    @field_validator("email", mode="before")
    @classmethod
    def normalise_email(cls, value: object) -> object:
        return value.strip().lower() if isinstance(value, str) else value


class UserRegisterRequest(_EmailNormalisingModel):
    """POST /api/auth/register"""

    password: PasswordText

    @field_validator("password")
    @classmethod
    def reject_blank_password(cls, value: str) -> str:
        """A password of eight spaces passes min_length but is not a password."""
        if not value.strip():
            raise ValueError("Password cannot be blank")
        return value

    model_config = {
        "json_schema_extra": {
            "example": {"email": "user@example.com", "password": "your-password-here"}
        }
    }


class UserLoginRequest(_EmailNormalisingModel):
    """POST /api/auth/login

    Password is only length-bounded here, not length-validated. Rejecting a
    short password at login with a different error than a wrong password
    would leak whether the stored password is short.
    """

    password: Annotated[str, Field(min_length=1, max_length=MAX_PASSWORD_LENGTH)]

    model_config = {
        "json_schema_extra": {
            "example": {"email": "user@example.com", "password": "your-password-here"}
        }
    }


class UserData(BaseModel):
    """Public representation of a user. Safe to return anywhere."""

    id: str
    email: EmailStr
    created_at: datetime


class TokenData(BaseModel):
    """Payload returned by a successful login."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int = Field(description="Token lifetime in seconds.")
