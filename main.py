"""
soundgen-api — MIDI composition and audio rendering API.

Endpoints:
  GET  /catalog              Full piece catalog (id, title, genre, bpm, key…)
  POST /generate             Generate MIDI for all pieces
  POST /generate/{id}        Generate MIDI for one piece
  POST /render               Render all pieces to WAV (pure-Python synth)
  POST /render/{id}          Render one piece to WAV
  GET  /ports                List available MIDI output ports
  POST /ports/select         Select a MIDI port by index
  POST /ports/panic          Send All Notes Off on all channels
  POST /play/{id}            Stream piece live via loopMIDI → Kontakt
  POST /stop                 Stop live playback
  GET  /state                Current playback state

Run:
  uvicorn main:app --port 8002 --reload
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routes import catalog, generate, render, play, ports, capture

app = FastAPI(
    title="SoundGen API",
    description="Procedural MIDI composition and audio rendering.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(catalog.router,  prefix="/catalog",  tags=["Catalog"])
app.include_router(generate.router, prefix="/generate", tags=["MIDI Generation"])
app.include_router(render.router,   prefix="/render",   tags=["Audio Rendering"])
app.include_router(ports.router,    prefix="/ports",    tags=["MIDI Ports"])
app.include_router(play.router,     prefix="/play",     tags=["Playback"])
app.include_router(capture.router,  prefix="/capture",  tags=["Kontakt Capture"])


@app.get("/", tags=["Health"])
def root():
    return {"service": "soundgen-api", "status": "ok"}
