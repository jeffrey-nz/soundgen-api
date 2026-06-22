#!/usr/bin/env python3
"""
verify_capture.py — Pre-flight check for Kontakt → BlackHole capture pipeline.

Checks:
  1. BlackHole 2ch is present as an AVFoundation device
  2. Kontakt (or any app) is routing audio to BlackHole — sends a test MIDI
     note through IAC and listens for 2 seconds to see if signal appears
  3. ffmpeg is available

Exits 0 on full pass, 1 on any failure.
Prints JSON to stdout.
"""
import sys, os, json, time, subprocess, shutil, tempfile, re

_here = os.path.dirname(os.path.abspath(__file__))
_dashboard = os.path.normpath(os.path.join(_here, '..', '..', '..', 'procmusic-dashboard', 'dashboard'))

FFMPEG_CANDIDATES = [shutil.which('ffmpeg'), '/opt/homebrew/bin/ffmpeg', '/usr/local/bin/ffmpeg']
FFMPEG = next((f for f in FFMPEG_CANDIDATES if f and os.path.isfile(f)), None)

BLACKHOLE_NAME = 'BlackHole 2ch'
SIGNAL_THRESHOLD_DB = -60.0   # anything above this = real audio


def _find_avf_device(name_hint):
    if not FFMPEG:
        return None
    r = subprocess.run(
        [FFMPEG, '-f', 'avfoundation', '-list_devices', 'true', '-i', ''],
        capture_output=True, text=True,
    )
    for line in r.stderr.splitlines():
        m = re.match(r'.*\[(\d+)\]\s+(.+)', line)
        if m and name_hint.lower() in m.group(2).lower():
            return int(m.group(1))
    return None


def _max_volume_db(wav_path):
    """Return max_volume in dB from a WAV file via ffmpeg volumedetect."""
    r = subprocess.run(
        [FFMPEG, '-i', wav_path, '-af', 'volumedetect', '-f', 'null', '/dev/null'],
        capture_output=True, text=True,
    )
    m = re.search(r'max_volume:\s*([-\d.]+)\s*dB', r.stderr)
    return float(m.group(1)) if m else -999.0


def _send_test_note(channel=0, note=60, velocity=100, duration=1.5):
    """Send a MIDI note-on then note-off via IAC Driver using rtmidi."""
    try:
        import rtmidi
        mout = rtmidi.MidiOut()
        ports = mout.get_ports()
        idx = None
        for i, p in enumerate(ports):
            if 'iac' in p.lower() or 'loop' in p.lower() or 'bus' in p.lower():
                idx = i
                break
        if idx is None and ports:
            idx = 0
        if idx is None:
            return False, 'No MIDI output port found'
        mout.open_port(idx)
        mout.send_message([0x90 | channel, note, velocity])  # note on
        time.sleep(duration)
        mout.send_message([0x80 | channel, note, 0])          # note off
        mout.close_port()
        return True, ports[idx]
    except ImportError:
        return False, 'rtmidi not installed'
    except Exception as e:
        return False, str(e)


def main():
    results = {
        'ffmpeg':    {'ok': False, 'detail': ''},
        'blackhole': {'ok': False, 'detail': '', 'deviceIndex': None},
        'audio':     {'ok': False, 'detail': '', 'maxDb': None},
        'midi':      {'ok': False, 'detail': ''},
    }

    # ── 1. ffmpeg ─────────────────────────────────────────────────────────────
    if FFMPEG:
        results['ffmpeg'] = {'ok': True, 'detail': FFMPEG}
    else:
        results['ffmpeg'] = {'ok': False, 'detail': 'ffmpeg not found — brew install ffmpeg'}
        print(json.dumps(results))
        sys.exit(1)

    # ── 2. BlackHole device ───────────────────────────────────────────────────
    device_idx = _find_avf_device(BLACKHOLE_NAME)
    if device_idx is not None:
        results['blackhole'] = {'ok': True, 'detail': f'{BLACKHOLE_NAME} at index {device_idx}', 'deviceIndex': device_idx}
    else:
        results['blackhole'] = {'ok': False, 'detail': f'{BLACKHOLE_NAME} not found — install and reboot', 'deviceIndex': None}
        print(json.dumps(results))
        sys.exit(1)

    # ── 3. Send MIDI note + record from BlackHole ─────────────────────────────
    with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tf:
        tmp_wav = tf.name

    try:
        # Start recording first, then play note so we don't miss the attack
        ffmpeg_proc = subprocess.Popen(
            [FFMPEG, '-y', '-f', 'avfoundation', '-i', f':{device_idx}',
             '-t', '3', '-ar', '44100', '-ac', '2', '-acodec', 'pcm_s16le', tmp_wav],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(0.3)  # let ffmpeg settle

        # Send on multiple channels to hit whatever instruments are loaded
        midi_ok, midi_detail = False, 'not tried'
        for ch in [0, 1, 6, 7, 9]:
            ok, detail = _send_test_note(channel=ch, note=60, velocity=100, duration=0.4)
            if ok:
                midi_ok, midi_detail = ok, detail
            time.sleep(0.1)
        results['midi'] = {'ok': midi_ok, 'detail': midi_detail}

        # Wait for ffmpeg to finish its 3-second capture
        try:
            ffmpeg_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            ffmpeg_proc.kill()

        if os.path.exists(tmp_wav) and os.path.getsize(tmp_wav) > 1000:
            max_db = _max_volume_db(tmp_wav)
            results['audio']['maxDb'] = round(max_db, 1)
            if max_db > SIGNAL_THRESHOLD_DB:
                results['audio'] = {
                    'ok': True,
                    'detail': f'Signal detected at {max_db:.1f} dB — routing is correct',
                    'maxDb': round(max_db, 1),
                }
            else:
                results['audio'] = {
                    'ok': False,
                    'detail': (
                        f'No signal from BlackHole ({max_db:.1f} dB). '
                        'Ensure Kontakt outputs to a Multi-Output Device '
                        'containing BlackHole 2ch.'
                    ),
                    'maxDb': round(max_db, 1),
                }
        else:
            results['audio'] = {'ok': False, 'detail': 'ffmpeg produced no output', 'maxDb': None}
    finally:
        try:
            os.unlink(tmp_wav)
        except Exception:
            pass

    all_ok = all(v['ok'] for v in results.values())
    print(json.dumps(results))
    sys.exit(0 if all_ok else 1)


if __name__ == '__main__':
    main()
