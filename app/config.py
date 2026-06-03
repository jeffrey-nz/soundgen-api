"""Runtime configuration — all values can be overridden by environment variables."""
import os
from pathlib import Path

# Python interpreter used to spawn core scripts.
PYTHON = os.environ.get("PROCMUSIC_PYTHON", "python")

# MIDI output directory — each piece lands at $MIDI_OUTPUT_DIR/<id>/{bass,pad,melody,drums}.mid
_default_midi = Path(__file__).parent.parent.parent.parent / "procmusic-dashboard" / "dashboard" / "showcase-midi"
MIDI_OUTPUT_DIR = Path(os.environ.get("MIDI_OUTPUT_DIR", str(_default_midi)))

# Audio (WAV) output directory — each render lands at $AUDIO_OUTPUT_DIR/<id>.wav
_default_audio = Path(__file__).parent.parent.parent.parent / "procmusic-dashboard" / "dashboard" / "showcase-audio"
AUDIO_OUTPUT_DIR = Path(os.environ.get("AUDIO_OUTPUT_DIR", str(_default_audio)))

# Core scripts directory
CORE_DIR = Path(__file__).parent / "core"
