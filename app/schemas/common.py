from decimal import Decimal

from pydantic import BaseModel, Field


class Money(BaseModel):
    amount: Decimal = Field(ge=0)
    currency: str = Field(default="KRW", pattern=r"^[A-Z]{3}$")


class SourceMetadata(BaseModel):
    source_name: str
    source_url: str | None = None
    effective_date: str
    version: str

