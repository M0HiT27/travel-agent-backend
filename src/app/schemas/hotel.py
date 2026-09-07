from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator, model_validator

# hotels.com rejects very long stays, and a multi-year range is almost always a typo.
_MAX_NIGHTS = 30


class HotelSearchRequest(BaseModel):
    """What the client sends to POST /hotels/search.

    The caller sends a destination *name*, not a region id: resolving the name is our
    job, not theirs. Validation is strict on purpose, because a search costs two
    billable scrapes and a request that cannot possibly succeed is rejected first.
    """

    destination: str = Field(examples=["Paris"], min_length=2, max_length=100)
    start_date: date = Field(examples=["2026-10-15"])
    end_date: date = Field(examples=["2026-10-18"])
    rooms: int = Field(default=1, ge=1, le=8)
    adults: int = Field(default=2, ge=1, le=14)

    @field_validator("destination")
    @classmethod
    def _clean_destination(cls, value: str) -> str:
        cleaned = " ".join(value.split())
        if len(cleaned) < 2:
            raise ValueError("destination must be at least 2 characters")
        return cleaned

    @field_validator("start_date")
    @classmethod
    def _reject_past_check_in(cls, value: date) -> date:
        if value < date.today():
            raise ValueError("start_date cannot be in the past")
        return value

    @model_validator(mode="after")
    def _validate_stay(self) -> "HotelSearchRequest":
        if self.end_date <= self.start_date:
            raise ValueError("end_date must be after start_date")
        if self.nights > _MAX_NIGHTS:
            raise ValueError(f"stay cannot be longer than {_MAX_NIGHTS} nights")
        return self

    @property
    def nights(self) -> int:
        return (self.end_date - self.start_date).days


class Hotel(BaseModel):
    """One hotel listing, trimmed down from the scraper's row.

    Prices are Decimal, so they serialise to JSON as strings ("1661"). That is
    deliberate: money must never round-trip through a float. They are optional
    because the scraper returns them as display text ("$1,661 total") that does not
    always parse; a listing with an unreadable price is still worth showing.
    """

    hotel_id: str
    name: str
    location: str | None = None
    rating: float | None = Field(default=None, description="Guest score out of 10")
    review_summary: str | None = None
    price_per_night: Decimal | None = None
    total_price: Decimal | None = None
    currency: str | None = None
    image_url: str | None = None
    booking_url: str | None = None


class HotelSearchResponse(BaseModel):
    """The search result, wrapped rather than returned as a bare list.

    Because we resolve the destination name ourselves, the caller has to be able to
    see *which* place we picked -- "Paris" also matches Paris, Texas. Returning the
    resolved name and region id makes a wrong guess visible instead of silent.

    Hotels are returned in the order the source ranked them (its "recommended"
    order, which blends price, rating and location), not sorted by price.
    """

    destination: str = Field(examples=["Paris, France"])
    region_id: str = Field(examples=["2734"])
    nights: int
    hotels: list[Hotel]
