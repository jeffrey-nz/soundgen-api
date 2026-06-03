"""Piece catalog — mirrors showcase_compositions.py CATALOG."""
from fastapi import APIRouter, Query
from typing import Optional

router = APIRouter()

# Mirrors the SHOWCASE_CATALOG in dashboard/server.js / showcase_compositions.py.
# Single source of truth is kept here; the dashboard fetches it from this endpoint.
CATALOG = [
    {"id": "orchestral_piece",  "title": "Orchestral Piece",      "genre": "Orchestral",    "mood": "Majestic",     "bpm": 80,  "key": "C Major",  "bars": 8,  "source": "synth"},
    {"id": "heroic_march",      "title": "Heroic March",          "genre": "Orchestral",    "mood": "Triumphant",   "bpm": 120, "key": "C Major",  "bars": 16, "source": "synth"},
    {"id": "forest_wanderer",   "title": "Forest Wanderer",       "genre": "Ambient",       "mood": "Peaceful",     "bpm": 68,  "key": "F Major",  "bars": 16, "source": "synth"},
    {"id": "battle_cry",        "title": "Battle Cry",            "genre": "Action",        "mood": "Intense",      "bpm": 145, "key": "D Minor",  "bars": 20, "source": "synth"},
    {"id": "tavern_jig",        "title": "Tavern Jig",            "genre": "Folk",          "mood": "Lively",       "bpm": 168, "key": "G Major",  "bars": 16, "source": "synth"},
    {"id": "sad_elegy",         "title": "Sad Elegy",             "genre": "Classical",     "mood": "Melancholic",  "bpm": 52,  "key": "A Minor",  "bars": 16, "source": "synth"},
    {"id": "dungeon_depths",    "title": "Dungeon Depths",        "genre": "Ambient",       "mood": "Mysterious",   "bpm": 76,  "key": "B Minor",  "bars": 16, "source": "synth"},
    {"id": "victory_fanfare",   "title": "Victory Fanfare",       "genre": "Orchestral",    "mood": "Celebratory",  "bpm": 138, "key": "G Major",  "bars": 20, "source": "synth"},
    {"id": "peaceful_village",  "title": "Peaceful Village",      "genre": "Pastoral",      "mood": "Warm",         "bpm": 88,  "key": "C Major",  "bars": 16, "source": "synth"},
    {"id": "dragons_lair",      "title": "Dragon's Lair",         "genre": "Action",        "mood": "Fierce",       "bpm": 155, "key": "E Minor",  "bars": 16, "source": "synth"},
    {"id": "twilight_lullaby",  "title": "Twilight Lullaby",      "genre": "Classical",     "mood": "Gentle",       "bpm": 62,  "key": "D Major",  "bars": 16, "source": "synth", "timeSig": "3/4"},
    {"id": "celtic_dawn",       "title": "Celtic Dawn",           "genre": "Celtic",        "mood": "Spirited",     "bpm": 96,  "key": "E Minor",  "bars": 16, "source": "synth"},
    {"id": "moonlight_reverie", "title": "Moonlight Reverie",     "genre": "Classical",     "mood": "Romantic",     "bpm": 72,  "key": "Bb Major", "bars": 16, "source": "synth"},
    {"id": "passacaglia",       "title": "Passacaglia",           "genre": "Classical",     "mood": "Solemn",       "bpm": 80,  "key": "D Minor",  "bars": 16, "source": "synth"},
    {"id": "midnight_blues",    "title": "Midnight Blues",        "genre": "Jazz",          "mood": "Soulful",      "bpm": 88,  "key": "G Minor",  "bars": 16, "source": "synth"},
    {"id": "silk_road",         "title": "Silk Road",             "genre": "World",         "mood": "Exotic",       "bpm": 80,  "key": "A Hijaz",  "bars": 16, "source": "synth"},
    {"id": "haunted_manor",     "title": "Haunted Manor",         "genre": "Horror",        "mood": "Eerie",        "bpm": 55,  "key": "D Minor",  "bars": 16, "source": "synth"},
    {"id": "river_street_rag",  "title": "River Street Rag",      "genre": "Jazz",          "mood": "Playful",      "bpm": 104, "key": "C Major",  "bars": 16, "source": "synth"},
    {"id": "crimson_tango",     "title": "Crimson Tango",         "genre": "Latin",         "mood": "Passionate",   "bpm": 116, "key": "D Minor",  "bars": 16, "source": "synth"},
    {"id": "neon_drift",        "title": "Neon Drift",            "genre": "Electronic",    "mood": "Dreamy",       "bpm": 128, "key": "A Minor",  "bars": 16, "source": "synth"},
    {"id": "delta_blues",       "title": "Delta Blues",           "genre": "Blues",         "mood": "Soulful",      "bpm": 76,  "key": "E Minor",  "bars": 16, "source": "synth"},
    {"id": "bossa_nova",        "title": "Rio Breeze",            "genre": "Bossa Nova",    "mood": "Relaxed",      "bpm": 130, "key": "D Major",  "bars": 16, "source": "synth"},
    {"id": "flamenco",          "title": "Andalusian Night",      "genre": "Flamenco",      "mood": "Passionate",   "bpm": 142, "key": "A Minor",  "bars": 16, "source": "synth"},
    {"id": "baroque_minuet",    "title": "Garden Minuet",         "genre": "Baroque",       "mood": "Elegant",      "bpm": 116, "key": "G Major",  "bars": 24, "source": "synth", "timeSig": "3/4"},
    {"id": "kingston_sunrise",  "title": "Kingston Sunrise",      "genre": "Reggae",        "mood": "Laid-back",    "bpm": 82,  "key": "G Major",  "bars": 16, "source": "synth"},
    {"id": "glory_road",        "title": "Glory Road",            "genre": "Gospel",        "mood": "Jubilant",     "bpm": 88,  "key": "Bb Major", "bars": 16, "source": "synth"},
    {"id": "groove_engine",     "title": "Groove Engine",         "genre": "Funk",          "mood": "Driving",      "bpm": 96,  "key": "E Minor",  "bars": 16, "source": "synth"},
    {"id": "blue_ridge_morning","title": "Blue Ridge Morning",     "genre": "Country",       "mood": "Warm",         "bpm": 100, "key": "G Major",  "bars": 16, "source": "synth"},
    {"id": "soul_searching",    "title": "Soul Searching",        "genre": "Soul",          "mood": "Soulful",      "bpm": 76,  "key": "A Minor",  "bars": 16, "source": "synth"},
    {"id": "swing_city",        "title": "Swing City",            "genre": "Swing",         "mood": "Lively",       "bpm": 152, "key": "Bb Major", "bars": 24, "source": "synth"},
    {"id": "lagos_groove",      "title": "Lagos Groove",          "genre": "Afrobeat",      "mood": "Groovy",       "bpm": 116, "key": "G Minor",  "bars": 16, "source": "synth"},
    {"id": "sacred_chorale",    "title": "Sacred Chorale",        "genre": "Classical",     "mood": "Solemn",       "bpm": 56,  "key": "D Major",  "bars": 16, "source": "synth"},
    {"id": "viennese_waltz",    "title": "Viennese Waltz",        "genre": "Waltz",         "mood": "Elegant",      "bpm": 126, "key": "A Major",  "bars": 24, "source": "synth", "timeSig": "3/4"},
    {"id": "morning_mist",      "title": "Morning Mist",          "genre": "Impressionist", "mood": "Dreamy",       "bpm": 60,  "key": "Eb Major", "bars": 16, "source": "synth"},
    {"id": "samba_carnival",    "title": "Samba Carnival",        "genre": "World",         "mood": "Festive",      "bpm": 108, "key": "E Major",  "bars": 16, "source": "synth"},
    {"id": "glass_etude",       "title": "Glass Étude",           "genre": "Minimalist",    "mood": "Hypnotic",     "bpm": 84,  "key": "C Major",  "bars": 16, "source": "synth"},
    {"id": "polka_village",     "title": "Polka Village",         "genre": "Polka",         "mood": "Festive",      "bpm": 132, "key": "G Major",  "bars": 16, "source": "synth"},
    {"id": "appalachian_fire",  "title": "Appalachian Fire",      "genre": "Bluegrass",     "mood": "Joyful",       "bpm": 160, "key": "G Major",  "bars": 16, "source": "synth"},
    {"id": "klezmer_dance",     "title": "Klezmer Dance",         "genre": "Klezmer",       "mood": "Festive",      "bpm": 134, "key": "D Minor",  "bars": 16, "source": "synth"},
    {"id": "urban_pulse",       "title": "Urban Pulse",           "genre": "Hip-Hop",       "mood": "Driving",      "bpm": 88,  "key": "C Minor",  "bars": 16, "source": "synth"},
    {"id": "crimson_dawn",      "title": "Crimson Dawn",          "genre": "Cinematic",     "mood": "Epic",         "bpm": 72,  "key": "D Minor",  "bars": 20, "source": "synth"},
    {"id": "sakura_dreams",     "title": "Sakura Dreams",         "genre": "World",         "mood": "Serene",       "bpm": 88,  "key": "G Major",  "bars": 16, "source": "synth"},
    {"id": "lost_cathedral",    "title": "Lost Cathedral",        "genre": "Classical",     "mood": "Solemn",       "bpm": 52,  "key": "D Dorian", "bars": 20, "source": "synth"},
    {"id": "electric_storm",    "title": "Electric Storm",        "genre": "Electronic",    "mood": "Intense",      "bpm": 140, "key": "E Minor",  "bars": 16, "source": "synth"},
    {"id": "crimson_overture",  "title": "Crimson Overture",      "genre": "Orchestral",    "mood": "Dramatic",     "bpm": 120, "key": "D Minor",  "bars": 16, "source": "synth"},
    {"id": "silver_morning",    "title": "Silver Morning",        "genre": "Pastoral",      "mood": "Serene",       "bpm": 84,  "key": "G Major",  "bars": 16, "source": "synth"},
    {"id": "mozart_kv545",      "title": "Sonata in C, K.545",    "genre": "Classical",     "mood": "Elegant",      "bpm": 120, "key": "C Major",  "bars": 20, "source": "kontakt"},
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
