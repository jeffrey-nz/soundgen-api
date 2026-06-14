"""Live MIDI playback via play_midi.py."""
import asyncio
import time
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
_play_started_at: Optional[float] = None   # time.time() when play_midi.py confirmed ready


async def _wait_for_proc():
    """Background cleanup: clear state when process exits."""
    global _play_proc, _play_piece, _play_started_at
    if _play_proc:
        await _play_proc.wait()
    _play_proc = None
    _play_piece = None
    _play_started_at = None


async def _read_until_ready(proc: asyncio.subprocess.Process) -> bool:
    """Read stdout lines until play_midi.py prints its ready marker.

    play_midi.py prints  '[play_midi] "<id>" -> "<port>" (...)'  then
    flushes stdout right before  start = time.monotonic()  begins the event
    loop.  We use that as the ground-truth start timestamp.
    """
    try:
        async for raw in proc.stdout:
            line = raw.decode(errors='replace').strip()
            if line.startswith('[play_midi]') and '->' in line:
                return True
            # Also return on error lines so we don't wait forever
            if 'error' in line.lower() or 'not found' in line.lower():
                return False
    except Exception:
        pass
    return False


async def _drain_stdout(proc: asyncio.subprocess.Process):
    """Consume remaining stdout after the ready line to prevent pipe blocking."""
    try:
        async for _ in proc.stdout:
            pass
    except Exception:
        pass


@router.post("/launch/{piece_id}")
async def launch(piece_id: str):
    """Start MIDI playback; waits for play_midi.py to signal ready before responding.

    Returns started_at (Unix seconds float) which the dashboard uses to align
    the piano-roll wall clock with the moment MIDI events actually started.
    """
    global _play_proc, _play_piece, _play_started_at
    await _stop_current()

    _play_proc = await asyncio.create_subprocess_exec(
        PYTHON, "-u", str(CORE_DIR / "play_midi.py"), piece_id,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    _play_piece = piece_id
    _play_started_at = None
    asyncio.create_task(_wait_for_proc())

    # Wait up to 10 s for play_midi.py to open the MIDI port and begin the event loop.
    # The timestamp captured here is the ground truth for piano-roll synchronisation.
    started_at = None
    try:
        ready = await asyncio.wait_for(_read_until_ready(_play_proc), timeout=10.0)
        if ready:
            started_at = time.time()
            _play_started_at = started_at
    except asyncio.TimeoutError:
        pass

    # Drain remaining subprocess stdout in the background.
    asyncio.create_task(_drain_stdout(_play_proc))

    return {"ok": True, "playing": piece_id, "started_at": started_at}


@router.post("/{piece_id}")
async def play(piece_id: str):
    """Start live MIDI playback for a piece. Stops any currently playing piece first."""
    global _play_proc, _play_piece, _play_started_at

    await _stop_current()

    async def event_gen():
        global _play_proc, _play_piece, _play_started_at
        _play_proc = await asyncio.create_subprocess_exec(
            PYTHON, "-u", str(CORE_DIR / "play_midi.py"), piece_id,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        _play_piece = piece_id
        async for raw in _play_proc.stdout:
            line = raw.decode(errors='replace').rstrip()
            if _play_started_at is None and '->' in line:
                _play_started_at = time.time()
            yield f"data: {line}\n\n"
        await _play_proc.wait()
        _play_piece = None
        _play_started_at = None
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
    """Return the current playback state including elapsed seconds if playing."""
    running = _play_proc is not None and _play_proc.returncode is None
    result = {"playing": running, "piece_id": _play_piece if running else None}
    if running and _play_started_at is not None:
        result["elapsed_seconds"] = time.time() - _play_started_at
    return result


async def _stop_current():
    global _play_proc, _play_piece, _play_started_at
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
    _play_started_at = None
