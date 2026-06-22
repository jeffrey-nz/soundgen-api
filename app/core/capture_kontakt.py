#!/usr/bin/env python3
"""
capture_kontakt.py — Record a showcase piece as it plays through Kontakt.

Starts ffmpeg recording from BlackHole 2ch (the virtual loopback device that
Kontakt outputs to), launches play_midi.py to send the MIDI events to Kontakt
via IAC, waits for playback to finish, then stops the recording.

The result is saved as showcase-audio/<piece_id>.wav — same location as the
Python-synth renderer, so the existing download/export flow works unchanged.

Usage:
    python capture_kontakt.py <piece_id> [--device <avfoundation_index>]

Requirements:
    - BlackHole 2ch installed (brew install --cask blackhole-2ch)
    - Kontakt configured to output to BlackHole 2ch (or an Aggregate Device
      that includes BlackHole 2ch)
    - ffmpeg on PATH or at /opt/homebrew/bin/ffmpeg
    - play_midi.py sibling (automatically found)
"""
import sys, os, subprocess, signal, time, shutil, json

_here = os.path.dirname(os.path.abspath(__file__))
_dashboard = os.path.normpath(os.path.join(_here, '..', '..', '..', 'procmusic-dashboard', 'dashboard'))

MIDI_BASE  = os.environ.get('MIDI_OUTPUT_DIR',  os.path.join(_dashboard, 'showcase-midi'))
AUDIO_OUT  = os.environ.get('AUDIO_OUTPUT_DIR', os.path.join(_dashboard, 'showcase-audio'))
PLAY_MIDI  = os.path.join(_here, 'play_midi.py')
PYTHON     = sys.executable

FFMPEG_CANDIDATES = [
    shutil.which('ffmpeg'),
    '/opt/homebrew/bin/ffmpeg',
    '/usr/local/bin/ffmpeg',
]
FFMPEG = next((f for f in FFMPEG_CANDIDATES if f and os.path.isfile(f)), None)

BLACKHOLE_NAME = 'BlackHole 2ch'


def _log(msg):
    print(msg, flush=True)


def _find_avf_device(name_hint):
    """Return the AVFoundation audio device index matching name_hint, or None."""
    if not FFMPEG:
        return None
    result = subprocess.run(
        [FFMPEG, '-f', 'avfoundation', '-list_devices', 'true', '-i', ''],
        capture_output=True, text=True,
    )
    output = result.stderr  # ffmpeg prints device list to stderr
    idx = None
    for line in output.splitlines():
        # Lines look like: [AVFoundation indev @ ...] [0] BlackHole 2ch
        import re
        m = re.match(r'.*\[(\d+)\]\s+(.+)', line)
        if m and name_hint.lower() in m.group(2).lower():
            idx = int(m.group(1))
            break
    return idx


def _piece_duration(piece_id):
    """Compute the duration of the MIDI files for piece_id in seconds."""
    try:
        import mido
    except ImportError:
        return None

    midi_dir = os.path.join(MIDI_BASE, piece_id)
    max_dur = 0.0
    for tname in ('bass', 'pad', 'melody', 'drums'):
        path = os.path.join(midi_dir, f'{tname}.mid')
        if not os.path.exists(path):
            continue
        try:
            mf = mido.MidiFile(path)
            dur = mf.length
            if dur > max_dur:
                max_dur = dur
        except Exception:
            pass
    return max_dur if max_dur > 0 else None


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('piece_id')
    parser.add_argument('--device', type=int, default=None,
                        help='AVFoundation audio device index for BlackHole')
    args = parser.parse_args()

    piece_id = args.piece_id
    midi_dir = os.path.join(MIDI_BASE, piece_id)

    if not os.path.isdir(midi_dir):
        _log(f'[capture] ERROR: MIDI directory not found: {midi_dir}')
        sys.exit(1)

    if not FFMPEG:
        _log('[capture] ERROR: ffmpeg not found — install via: brew install ffmpeg')
        sys.exit(1)

    # ── Find BlackHole device ─────────────────────────────────────────────────
    device_idx = args.device
    if device_idx is None:
        _log(f'[capture] Scanning AVFoundation devices for "{BLACKHOLE_NAME}"…')
        device_idx = _find_avf_device(BLACKHOLE_NAME)

    if device_idx is None:
        _log(f'[capture] ERROR: "{BLACKHOLE_NAME}" not found in AVFoundation device list.')
        _log('[capture] Make sure BlackHole 2ch is installed and Kontakt outputs to it.')
        _log('[capture] Install: brew install --cask blackhole-2ch  (then reboot)')
        sys.exit(1)

    _log(f'[capture] Using BlackHole at AVFoundation device index {device_idx}')

    # ── Estimate duration ─────────────────────────────────────────────────────
    duration = _piece_duration(piece_id)
    tail_pad = 4.0   # seconds of silence to capture after MIDI ends (reverb tail)
    if duration:
        _log(f'[capture] Piece duration: {duration:.1f}s  (+{tail_pad}s tail)')
    else:
        _log('[capture] Could not determine piece duration — will stop on MIDI end')

    os.makedirs(AUDIO_OUT, exist_ok=True)
    out_wav = os.path.join(AUDIO_OUT, f'{piece_id}.wav')
    tmp_wav = out_wav + '.tmp.wav'

    # ── Start ffmpeg capture ──────────────────────────────────────────────────
    ffmpeg_cmd = [
        FFMPEG, '-y',
        '-f', 'avfoundation',
        '-i', f':{device_idx}',      # audio-only: ":N" selects audio device N
        '-ar', '48000',   # match BlackHole's native rate to avoid resampling artifacts
        '-ac', '2',
        '-acodec', 'pcm_s16le',
        tmp_wav,
    ]
    _log(f'[capture] Starting ffmpeg recording from device :{device_idx}…')
    ffmpeg_proc = subprocess.Popen(
        ffmpeg_cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # Brief pre-roll so ffmpeg is definitely buffering before MIDI starts
    time.sleep(0.5)

    # ── Start MIDI playback ───────────────────────────────────────────────────
    _log(f'[capture] Launching play_midi.py for "{piece_id}"…')
    midi_env = {**os.environ, 'MIDI_OUTPUT_DIR': MIDI_BASE}
    midi_proc = subprocess.Popen(
        [PYTHON, '-u', PLAY_MIDI, piece_id],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=midi_env,
    )

    # Stream play_midi output so caller sees progress
    for line in midi_proc.stdout:
        _log(f'[play_midi] {line.rstrip()}')

    midi_proc.wait()

    if midi_proc.returncode != 0:
        _log(f'[capture] play_midi.py exited with code {midi_proc.returncode} — aborting')
        ffmpeg_proc.stdin.write(b'q')
        ffmpeg_proc.stdin.flush()
        ffmpeg_proc.wait()
        if os.path.exists(tmp_wav):
            os.remove(tmp_wav)
        sys.exit(1)

    # ── Capture reverb tail, then stop ffmpeg ─────────────────────────────────
    _log(f'[capture] MIDI done — capturing {tail_pad}s reverb tail…')
    time.sleep(tail_pad)

    # Send 'q' to ffmpeg stdin for a clean stop (avoids truncation)
    try:
        ffmpeg_proc.stdin.write(b'q')
        ffmpeg_proc.stdin.flush()
    except Exception:
        pass
    try:
        ffmpeg_proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        ffmpeg_proc.kill()
        ffmpeg_proc.wait()

    if not os.path.exists(tmp_wav) or os.path.getsize(tmp_wav) < 1000:
        _log('[capture] ERROR: ffmpeg produced no output — check BlackHole routing')
        sys.exit(1)

    # ── Validate signal level ─────────────────────────────────────────────────
    # If the recording is silent (-91 dB noise floor) Kontakt is not routing to
    # BlackHole. Fail early with a clear message instead of saving a silent file.
    _log('[capture] Checking audio signal level…')
    vol_result = subprocess.run(
        [FFMPEG, '-i', tmp_wav, '-af', 'volumedetect', '-f', 'null', '/dev/null'],
        capture_output=True, text=True,
    )
    import re as _re
    m = _re.search(r'max_volume:\s*([-\d.]+)\s*dB', vol_result.stderr)
    max_db = float(m.group(1)) if m else -999.0
    _log(f'[capture] Peak level: {max_db:.1f} dB')

    if max_db < -60.0:
        if os.path.exists(tmp_wav):
            os.remove(tmp_wav)
        _log(f'[capture] ERROR: Recording is silent ({max_db:.1f} dB) — Kontakt is not routing to BlackHole 2ch.')
        _log('[capture] Fix: In Audio MIDI Setup, create a Multi-Output Device that includes')
        _log('[capture]      both your speakers AND BlackHole 2ch. Set Kontakt\'s output to that device.')
        sys.exit(1)

    # Atomic replace
    os.replace(tmp_wav, out_wav)
    size_kb = os.path.getsize(out_wav) // 1024
    _log(f'[capture] Wrote {out_wav} ({size_kb} KB)')
    _log(f'[capture] Done.')


if __name__ == '__main__':
    main()
