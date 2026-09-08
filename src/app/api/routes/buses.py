from fastapi import APIRouter, Depends

from app.api.deps import get_current_user
from app.core.config import get_settings
from app.models.user import User
from app.schemas.bus import BusSearchRequest, BusSearchResponse
from app.services.bus_service import search_buses

router = APIRouter(prefix="/buses", tags=["buses"])


@router.post("/search", response_model=BusSearchResponse)
async def search(
    payload: BusSearchRequest,
    current_user: User = Depends(get_current_user),
) -> BusSearchResponse:
    """Search buses by origin/destination city name, in the source's own order.

    Authenticated because every search costs money against the parse.bot account.
    """
    return await search_buses(get_settings(), payload)
