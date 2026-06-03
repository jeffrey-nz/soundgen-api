"""Runtime configuration — all values can be overridden by environment variables."""
import os
from pathlib import Path

# Python interpreter used to spawn core scripts.
import sys as _sys
PYTHON = os.environ.get("PROCMUSIC_PYTHON", _sys.executable)

# MIDI output directory — each piece lands at $MIDI_OUTPUT_DIR/<id>/{bass,pad,melody,drums}.mid
# Defaults to ../procmusic/dashboard/showcase-midi (sibling repo layout on dev machine).
_here = Path(__file__).parent.parent  # soundgen-api/
_default_midi = _here.parent / "procmusic" / "dashboard" / "showcase-midi"
MIDI_OUTPUT_DIR = Path(os.environ.get("MIDI_OUTPUT_DIR", str(_default_midi)))

# Audio (WAV) output directory — each render lands at $AUDIO_OUTPUT_DIR/<id>.wav
_default_audio = _here.parent / "procmusic" / "dashboard" / "showcase-audio"
AUDIO_OUTPUT_DIR = Path(os.environ.get("AUDIO_OUTPUT_DIR", str(_default_audio)))

# Core scripts directory
CORE_DIR = Path(__file__).parent / "core"
