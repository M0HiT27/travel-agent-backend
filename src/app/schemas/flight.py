import re
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator, model_validator

_IATA_CODE_RE = re.compile(r"^[A-Z]{3}$")


class FlightSearchRequest(BaseModel):
    """What the client sends to POST /flights/search.

    Validation is strict on purpose: a Duffel call is slow and billable, so a request
    that cannot possibly succeed is rejected before we call them.
    """

    origin: str = Field(examples=["DEL"])
    destination: str = Field(examples=["GOI"])
    departure_date: date = Field(examples=["2026-09-15"])
    adults: int = Field(default=1, ge=1, le=9)

    @field_validator("origin", "destination")
    @classmethod
    def _validate_iata_code(cls, value: str) -> str:
        normalised = value.strip().upper()
        if not _IATA_CODE_RE.match(normalised):
            raise ValueError("must be a 3-letter IATA airport code, e.g. DEL")
        return normalised

    @field_validator("departure_date")
    @classmethod
    def _reject_past_dates(cls, value: date) -> date:
        if value < date.today():
            raise ValueError("departure_date cannot be in the past")
        return value

    @model_validator(mode="after")
    def _reject_identical_airports(self) -> "FlightSearchRequest":
        if self.origin == self.destination:
            raise ValueError("origin and destination must be different")
        return self


class FlightSegment(BaseModel):
    """One flown leg. A direct flight has exactly one segment."""

    origin: str
    destination: str
    departure_at: datetime
    arrival_at: datetime
    carrier_code: str | None = None
    carrier_name: str | None = None
    flight_number: str | None = None
    duration_minutes: int | None = None


class FlightOffer(BaseModel):
    """One bookable fare, trimmed down from Duffel's much larger offer object.

    `total_amount` is a Decimal, so it serialises to JSON as a string ("81.70").
    That is deliberate: money must never round-trip through a float.
    """

    offer_id: str
    airline_name: str | None = None
    airline_code: str | None = None
    total_amount: Decimal
    currency: str
    departure_at: datetime
    arrival_at: datetime
    duration_minutes: int | None = None
    stops: int
    segments: list[FlightSegment]
    expires_at: datetime | None = None
