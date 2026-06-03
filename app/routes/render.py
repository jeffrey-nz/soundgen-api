"""WAV rendering via render_synth.py — streams progress as SSE."""
import asyncio
from typing import Optional

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse, FileResponse
from fastapi import HTTPException

from app.config import CORE_DIR, AUDIO_OUTPUT_DIR, PYTHON

router = APIRouter()


@router.post("")
async def render_all():
    """Render every piece to WAV using the pure-Python synthesizer."""
    async def event_gen():
        proc = await asyncio.create_subprocess_exec(
            PYTHON, "-u", str(CORE_DIR / "render_synth.py"),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=str(CORE_DIR),
        )
        async for raw in proc.stdout:
            yield f"data: {raw.decode(errors='replace').rstrip()}\n\n"
        await proc.wait()
        yield f"event: done\ndata: {'done' if proc.returncode == 0 else 'error'}\n\n"

    return StreamingResponse(event_gen(), media_type="text/event-stream")


@router.post("/{piece_id}")
async def render_one(piece_id: str):
    """Render a single piece to WAV."""
    async def event_gen():
        proc = await asyncio.create_subprocess_exec(
            PYTHON, "-u", str(CORE_DIR / "render_synth.py"), piece_id,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=str(CORE_DIR),
        )
        async for raw in proc.stdout:
            yield f"data: {raw.decode(errors='replace').rstrip()}\n\n"
        await proc.wait()
        yield f"event: done\ndata: {'done' if proc.returncode == 0 else 'error'}\n\n"

    return StreamingResponse(event_gen(), media_type="text/event-stream")


@router.get("/audio/{piece_id}")
def get_audio(piece_id: str):
    """Stream the rendered WAV file for a piece."""
    wav = AUDIO_OUTPUT_DIR / f"{piece_id}.wav"
    if not wav.exists():
        raise HTTPException(status_code=404, detail="WAV not found — render it first")
    return FileResponse(str(wav), media_type="audio/wav")
