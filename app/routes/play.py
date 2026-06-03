"""Live MIDI playback via play_midi.py."""
import asyncio
import os
import signal
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.config import CORE_DIR, PYTHON

router = APIRouter()

# Track the currently running playback process.
_play_proc: Optional[asyncio.subprocess.Process] = None
_play_piece: Optional[str] = None


@router.post("/{piece_id}")
async def play(piece_id: str):
    """Start live MIDI playback for a piece. Stops any currently playing piece first."""
    global _play_proc, _play_piece

    await _stop_current()

    async def event_gen():
        global _play_proc, _play_piece
        _play_proc = await asyncio.create_subprocess_exec(
            PYTHON, "-u", str(CORE_DIR / "play_midi.py"), piece_id,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        _play_piece = piece_id
        async for raw in _play_proc.stdout:
            yield f"data: {raw.decode(errors='replace').rstrip()}\n\n"
        await _play_proc.wait()
        _play_piece = None
        yield f"event: done\ndata: stopped\n\n"

    return StreamingResponse(event_gen(), media_type="text/event-stream")


@router.post("/stop")
async def stop():
    """Stop the currently playing piece."""
    stopped = _play_piece
    await _stop_current()
    return {"stopped": stopped}


@router.get("/state")
def state():
    """Return the current playback state."""
    running = _play_proc is not None and _play_proc.returncode is None
    return {"playing": running, "piece_id": _play_piece if running else None}


async def _stop_current():
    global _play_proc, _play_piece
    if _play_proc and _play_proc.returncode is None:
        try:
            _play_proc.terminate()
            await asyncio.wait_for(_play_proc.wait(), timeout=2.0)
        except Exception:
            try:
                _play_proc.kill()
            except Exception:
                pass
    _play_proc = None
    _play_piece = None
