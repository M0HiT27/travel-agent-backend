from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator, model_validator


class BusSearchRequest(BaseModel):
    """What the client sends to POST /buses/search.

    The caller sends city *names*, not the numeric ids the redbus scraper expects:
    resolving the names is our job, not theirs. Validation is strict on purpose,
    because a search costs two billable scrapes and a request that cannot possibly
    succeed is rejected before we call them.
    """

    origin: str = Field(examples=["Mumbai"], min_length=2, max_length=100)
    destination: str = Field(examples=["Pune"], min_length=2, max_length=100)
    departure_date: date = Field(examples=["2026-09-15"])

    @field_validator("origin", "destination")
    @classmethod
    def _clean_city(cls, value: str) -> str:
        cleaned = " ".join(value.split())
        if len(cleaned) < 2:
            raise ValueError("must be at least 2 characters")
        return cleaned

    @field_validator("departure_date")
    @classmethod
    def _reject_past_dates(cls, value: date) -> date:
        if value < date.today():
            raise ValueError("departure_date cannot be in the past")
        return value

    @model_validator(mode="after")
    def _reject_identical_cities(self) -> "BusSearchRequest":
        if self.origin.casefold() == self.destination.casefold():
            raise ValueError("origin and destination must be different")
        return self


class Bus(BaseModel):
    """One bus service, trimmed down from the scraper's row.

    Verified against a real search_buses response (2026-09-08): `route_id` and
    `operator_id` arrive as integers and are converted to strings for consistency
    with the rest of the API; `fare` is a Decimal, so it serialises to JSON as a
    string ("333.33") -- money must never round-trip through a float. It is the
    lowest fare across seat classes, since that is the number a traveller comparing
    buses wants first. `rating` is redBus's own `totalRatings`, out of 5.
    """

    route_id: str
    operator_id: str | None = None
    travels_name: str
    bus_type: str | None = None
    departure_time: datetime | None = None
    arrival_time: datetime | None = None
    duration_minutes: int | None = None
    available_seats: int | None = None
    fare: Decimal | None = None
    rating: float | None = Field(default=None, description="Guest rating out of 5")


class BusSearchResponse(BaseModel):
    """The search result, wrapped rather than returned as a bare list.

    Because we resolve both city names ourselves, the caller has to be able to see
    *which* place we picked for each -- returning the resolved names and ids makes a
    wrong guess visible instead of silent.

    Buses are returned in the order the source ranked them, not sorted by price.
    """

    origin: str = Field(examples=["Mumbai"])
    origin_city_id: str
    destination: str = Field(examples=["Pune"])
    destination_city_id: str
    departure_date: date
    buses: list[Bus]
