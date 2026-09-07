from fastapi import APIRouter, Depends

from app.api.deps import get_current_user
from app.core.config import get_settings
from app.models.user import User
from app.schemas.flight import FlightOffer, FlightSearchRequest
from app.services.flight_service import search_flights

router = APIRouter(prefix="/flights", tags=["flights"])


@router.post("/search", response_model=list[FlightOffer])
async def search(
    payload: FlightSearchRequest,
    current_user: User = Depends(get_current_user),
) -> list[FlightOffer]:
    """Search one-way flights, cheapest first.

    Authenticated because every search costs money against the Duffel account.
    """
    return await search_flights(get_settings(), payload)
