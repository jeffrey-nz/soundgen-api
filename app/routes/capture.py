"""Render a piece via Kontakt by recording BlackHole 2ch during live MIDI playback."""
import asyncio
import json
import os
import subprocess

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.config import CORE_DIR, AUDIO_OUTPUT_DIR, MIDI_OUTPUT_DIR, PYTHON

router = APIRouter()


@router.get("/verify")
def verify_capture():
    """Run pre-flight checks: BlackHole present, MIDI port reachable, audio signal detected."""
    result = subprocess.run(
        [PYTHON, "-u", str(CORE_DIR / "verify_capture.py")],
        capture_output=True, text=True,
        env={**os.environ, "MIDI_OUTPUT_DIR": str(MIDI_OUTPUT_DIR)},
        timeout=15,
    )
    try:
        data = json.loads(result.stdout)
    except Exception:
        data = {"error": result.stdout or result.stderr}
    data["allOk"] = result.returncode == 0
    return data

_ENV = lambda: {
    **os.environ,
    "MIDI_OUTPUT_DIR":  str(MIDI_OUTPUT_DIR),
    "AUDIO_OUTPUT_DIR": str(AUDIO_OUTPUT_DIR),
}


@router.post("/{piece_id}")
async def capture_kontakt(piece_id: str, device: int = None):
    """Record a piece through Kontakt/BlackHole and save to showcase-audio/<id>.wav.

    Streams capture_kontakt.py progress as SSE, same protocol as /render.
    Query param `device` overrides the AVFoundation audio device index.
    """
    args = [PYTHON, "-u", str(CORE_DIR / "capture_kontakt.py"), piece_id]
    if device is not None:
        args += ["--device", str(device)]

    async def event_gen():
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=_ENV(),
        )
        async for raw in proc.stdout:
            yield f"data: {raw.decode(errors='replace').rstrip()}\n\n"
        await proc.wait()
        yield f"event: done\ndata: {'done' if proc.returncode == 0 else 'error'}\n\n"

    return StreamingResponse(event_gen(), media_type="text/event-stream")
