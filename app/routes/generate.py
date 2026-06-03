"""MIDI generation via showcase_compositions.py — streams progress as SSE."""
import asyncio

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.config import CORE_DIR, MIDI_OUTPUT_DIR, PYTHON

router = APIRouter()


async def _stream_script(args: list[str]) -> StreamingResponse:
    import os
    env = {**os.environ, "MIDI_OUTPUT_DIR": str(MIDI_OUTPUT_DIR)}

    async def event_gen():
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=str(CORE_DIR),
            env=env,
        )
        async for raw in proc.stdout:
            line = raw.decode(errors="replace").rstrip()
            yield f"data: {line}\n\n"
        await proc.wait()
        status = "done" if proc.returncode == 0 else "error"
        yield f"event: done\ndata: {status}\n\n"

    return StreamingResponse(event_gen(), media_type="text/event-stream")


@router.post("")
async def generate_all():
    """Generate MIDI files for all pieces in the catalog."""
    return await _stream_script([
        PYTHON, "-u", str(CORE_DIR / "showcase_compositions.py"),
    ])


@router.post("/{piece_id}")
async def generate_one(piece_id: str):
    """Generate MIDI for a single piece by ID."""
    return await _stream_script([
        PYTHON, "-u", str(CORE_DIR / "showcase_compositions.py"), piece_id,
    ])
