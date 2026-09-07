from fastapi import APIRouter, Depends

from app.api.deps import get_current_user
from app.core.config import get_settings
from app.models.user import User
from app.schemas.hotel import HotelSearchRequest, HotelSearchResponse
from app.services.hotel_service import search_hotels

router = APIRouter(prefix="/hotels", tags=["hotels"])


@router.post("/search", response_model=HotelSearchResponse)
async def search(
    payload: HotelSearchRequest,
    current_user: User = Depends(get_current_user),
) -> HotelSearchResponse:
    """Search hotels by destination name, in the source's recommended order.

    Authenticated because every search costs money against the parse.bot account.
    """
    return await search_hotels(get_settings(), payload)
