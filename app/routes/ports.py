"""MIDI port management — thin wrapper around midi_proxy.py."""
import json
import subprocess

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config import CORE_DIR, PYTHON

router = APIRouter()


def _run_proxy_cmd(cmd: dict) -> dict:
    """Send a single JSON command to midi_proxy.py and return its response."""
    result = subprocess.run(
        [PYTHON, str(CORE_DIR / "midi_proxy.py"), "--cmd", json.dumps(cmd)],
        capture_output=True,
        text=True,
        timeout=5,
    )
    if result.returncode != 0:
        raise HTTPException(status_code=500, detail=result.stderr[:300])
    try:
        return json.loads(result.stdout.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        return {"raw": result.stdout}


@router.get("")
def list_ports():
    """List available MIDI output ports."""
    return _run_proxy_cmd({"type": "ports"})


class SelectRequest(BaseModel):
    port: int


@router.post("/select")
def select_port(req: SelectRequest):
    """Open a MIDI output port by index."""
    return _run_proxy_cmd({"type": "select", "port": req.port})


@router.post("/panic")
def panic():
    """Send All Notes Off (CC 123) on all 16 channels."""
    return _run_proxy_cmd({"type": "all_off"})
