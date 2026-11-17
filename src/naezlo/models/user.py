"""Users: the humans who sign in."""

from sqlalchemy import CheckConstraint, String
from sqlalchemy.orm import Mapped, mapped_column, validates

from naezlo.db import Base, TimestampMixin, UUIDPrimaryKeyMixin


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        # The model lowercases on assignment; the database refuses anything that slipped past it.
        CheckConstraint("email = lower(email)", name="email_lowercase"),
    )

    email: Mapped[str] = mapped_column(String(320), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    avatar_url: Mapped[str | None] = mapped_column(String(2048))
    # Google's stable account id; empty until the user signs in with Google.
    google_sub: Mapped[str | None] = mapped_column(String(255), unique=True)

    @validates("email")
    def _normalize_email(self, _key: str, value: str) -> str:
        return normalize_email(value)


def normalize_email(email: str) -> str:
    """The stored form of an email address. Use it for lookups too."""
    return email.strip().lower()
