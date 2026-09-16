"""FastAPI routes for durable watchlist management."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from config.settings import settings
from data.watchlist import WatchlistItem, WatchlistStore


class WatchlistItemDTO(BaseModel):
    symbol: str
    timeframe: str
    scope: str
    added_at: str

    @classmethod
    def from_item(cls, item: WatchlistItem) -> "WatchlistItemDTO":
        return cls(
            symbol=item.symbol,
            timeframe=item.timeframe,
            scope=item.scope,
            added_at=item.added_at,
        )


class WatchlistResponse(BaseModel):
    items: list[WatchlistItemDTO]
    count: int


class WatchlistAddRequest(BaseModel):
    symbol: str = Field(min_length=1, description="Instrument symbol (e.g. 'FX Vol 20' or 'R_75')")
    timeframe: str = Field(default="H1", description="Observation timeframe (e.g. 'H1')")


class WatchlistDeleteResponse(BaseModel):
    deleted: bool
    symbol: str
    timeframe: str | None = None


router = APIRouter(prefix="/api/v1/watchlist", tags=["watchlist"])


def get_watchlist_store() -> WatchlistStore:
    return WatchlistStore(settings.watchlist_store_path)


@router.get("", response_model=WatchlistResponse)
@router.get("/", response_model=WatchlistResponse)
def get_watchlist(
    store: WatchlistStore = Depends(get_watchlist_store),
) -> WatchlistResponse:
    """Return all active instruments in the persisted watchlist."""
    items = store.get_items()
    dtos = [WatchlistItemDTO.from_item(i) for i in items]
    return WatchlistResponse(items=dtos, count=len(dtos))


@router.post("", response_model=WatchlistItemDTO)
@router.post("/", response_model=WatchlistItemDTO)
def add_to_watchlist(
    request: WatchlistAddRequest,
    store: WatchlistStore = Depends(get_watchlist_store),
) -> WatchlistItemDTO:
    """Add a new instrument to the persisted watchlist."""
    try:
        item = store.add_item(request.symbol, request.timeframe)
        return WatchlistItemDTO.from_item(item)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/{symbol}", response_model=WatchlistDeleteResponse)
def delete_from_watchlist_path(
    symbol: str,
    timeframe: str | None = Query(default=None, description="Optional timeframe filter"),
    store: WatchlistStore = Depends(get_watchlist_store),
) -> WatchlistDeleteResponse:
    """Remove an instrument from the persisted watchlist by path symbol."""
    try:
        deleted = store.remove_item(symbol, timeframe)
        return WatchlistDeleteResponse(deleted=deleted, symbol=symbol, timeframe=timeframe)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("", response_model=WatchlistDeleteResponse)
@router.delete("/", response_model=WatchlistDeleteResponse)
def delete_from_watchlist_query(
    symbol: str = Query(..., description="Instrument symbol to remove"),
    timeframe: str | None = Query(default=None, description="Optional timeframe filter"),
    store: WatchlistStore = Depends(get_watchlist_store),
) -> WatchlistDeleteResponse:
    """Remove an instrument from the persisted watchlist by query parameter."""
    try:
        deleted = store.remove_item(symbol, timeframe)
        return WatchlistDeleteResponse(deleted=deleted, symbol=symbol, timeframe=timeframe)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
