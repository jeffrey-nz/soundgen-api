"""Piece catalog — mirrors showcase_compositions.py CATALOG."""
from fastapi import APIRouter, Query
from typing import Optional

router = APIRouter()

# Mirrors the SHOWCASE_CATALOG in dashboard/server.js / showcase_compositions.py.
# Single source of truth is kept here; the dashboard fetches it from this endpoint.
CATALOG = [
    {"id": "evening_prelude",  "title": "Evening Prelude", "genre": "Classical", "mood": "Romantic",  "bpm": 66, "key": "E Minor", "bars": 16, "source": "kontakt"},
    {"id": "orchestral_demo",  "title": "Aurora",          "genre": "Classical", "mood": "Cinematic", "bpm": 80, "key": "D Major", "bars": 10, "source": "kontakt"},
]


@router.get("")
def list_catalog(
    genre: Optional[str] = Query(default=None, description="Filter by genre"),
    source: Optional[str] = Query(default=None, description="Filter by source: synth or kontakt"),
):
    items = CATALOG
    if genre:
        items = [c for c in items if c["genre"].lower() == genre.lower()]
    if source:
        items = [c for c in items if c["source"] == source]
    return items


@router.get("/{piece_id}")
def get_piece(piece_id: str):
    for item in CATALOG:
        if item["id"] == piece_id:
            return item
    from fastapi import HTTPException
    raise HTTPException(status_code=404, detail="Piece not found")
