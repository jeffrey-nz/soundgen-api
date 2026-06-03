#!/usr/bin/env python3
"""
reaper_render.py — Drive REAPER to render procmusic MIDI tracks via Kontakt.

Usage:
    python reaper_render.py <config.json>

Config schema (written by server.js / generate_and_render.py):
{
  "jobs": [
    {
      "name":   "orchestral_piece",
      "bpm":    80,
      "midi":   {
        "Bass":   "C:\\...\\showcase-midi\\orchestral_piece\\bass.mid",
        "Pad":    "C:\\...\\showcase-midi\\orchestral_piece\\pad.mid",
        "Melody": "C:\\...\\showcase-midi\\orchestral_piece\\melody.mid",
        "Drums":  "C:\\...\\showcase-midi\\orchestral_piece\\drums.mid"
      },
      "output": "C:\\...\\showcase-audio\\orchestral_piece.wav"
    }
  ],
  "template":    "C:\\...\\reaper-template.rpp",
  "log":         "C:\\...\\render-progress.log",
  "sample_rate": 44100
}

Requirements:
    pip install python-reapy

REAPER setup (one-time):
    1. Open REAPER
    2. Options > Preferences > Plug-ins > ReaScript — enable Python
    3. pip install python-reapy
    4. python -c "import reapy; reapy.configure_reaper()"
    5. Restart REAPER

Template setup (one-time):
    The template .rpp must have exactly 4 tracks named:
        Bass, Pad, Melody, Drums
    Each track needs Kontakt loaded with the appropriate NI instrument.

Progress is emitted as JSON-lines on stdout AND written to config["log"].
"""
import sys
import os
import json
import time
import argparse


# ── Helpers ───────────────────────────────────────────────────────────────────

def emit(type_, **kw):
    line = json.dumps({"type": type_, **kw})
    print(line, flush=True)
    return line


def log_to_file(log_path, msg):
    if log_path:
        try:
            with open(log_path, 'a', encoding='utf-8') as f:
                f.write(msg + '\n')
        except OSError:
            pass


def progress(msg, log_path=''):
    emit("progress", msg=msg)
    log_to_file(log_path, msg)


def error(msg, log_path=''):
    emit("error", msg=msg)
    log_to_file(log_path, f"ERROR: {msg}")


# ── Connection helpers ─────────────────────────────────────────────────────────

def connect_reapy(log_path='', retries=5, delay=2.0):
    """Connect to running REAPER via reapy, with retry on transient failures."""
    import reapy

    for attempt in range(1, retries + 1):
        try:
            # reapy lazily connects on first API call; ping the project to verify
            proj = reapy.Project()
            name = proj.name or '(untitled)'
            progress(f"Connected to REAPER — project: {name}", log_path)
            return reapy, proj
        except Exception as exc:
            if attempt < retries:
                progress(f"Connection attempt {attempt}/{retries} failed: {exc} — retrying in {delay}s…", log_path)
                time.sleep(delay)
                delay = min(delay * 1.5, 10.0)
            else:
                raise RuntimeError(
                    f"Cannot connect to REAPER after {retries} attempts: {exc}\n\n"
                    "Make sure REAPER is running with the reapy server enabled.\n"
                    "One-time setup:\n"
                    "  1. pip install python-reapy\n"
                    "  2. python -c \"import reapy; reapy.configure_reaper()\"\n"
                    "  3. Restart REAPER"
                ) from exc


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='Render procmusic MIDI via REAPER + Kontakt')
    parser.add_argument('config', nargs='?', help='Path to render config JSON')
    args = parser.parse_args()

    if not args.config:
        error("Usage: reaper_render.py <config.json>")
        sys.exit(1)

    config_path = args.config
    if not os.path.exists(config_path):
        error(f"Config not found: {config_path}")
        sys.exit(1)

    with open(config_path, 'r', encoding='utf-8') as f:
        config = json.load(f)

    jobs      = config.get("jobs", [])
    template  = config.get("template", "")
    log_path  = config.get("log", "")
    sr        = config.get("sample_rate", 44100)

    if log_path:
        try:
            open(log_path, 'w').close()
        except OSError:
            pass

    progress(f"procmusic REAPER renderer — {len(jobs)} job(s)", log_path)

    if not jobs:
        error("No jobs in config — nothing to render.", log_path)
        sys.exit(0)

    # ── Import reapy ──────────────────────────────────────────────────────────
    try:
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            import reapy
    except ImportError:
        error(
            "reapy is not installed. Run:\n"
            "  pip install python-reapy\n\n"
            "Then configure REAPER (one-time):\n"
            "  python -c \"import reapy; reapy.configure_reaper()\"\n"
            "  Restart REAPER",
            log_path
        )
        sys.exit(1)

    # ── Connect ───────────────────────────────────────────────────────────────
    try:
        reapy_mod, proj = connect_reapy(log_path)
    except RuntimeError as exc:
        error(str(exc), log_path)
        sys.exit(1)

    # ── Process jobs ──────────────────────────────────────────────────────────
    done = 0
    failed = []
    for i, job in enumerate(jobs):
        name = job.get("name", f"track_{i}")
        progress(f"[{i+1}/{len(jobs)}] {name}", log_path)
        try:
            ok = render_job(reapy_mod, job, template, sr, log_path)
            if ok:
                done += 1
            else:
                failed.append(name)
        except Exception as exc:
            progress(f"  ERROR: {exc}", log_path)
            failed.append(name)

    progress(f"Finished: {done}/{len(jobs)} rendered.", log_path)
    if failed:
        progress(f"Failed: {', '.join(failed)}", log_path)
    emit("done", n=done, total=len(jobs), failed=failed)


# ── Job renderer ─────────────────────────────────────────────────────────────

def render_job(reapy, job, template, sample_rate, log_path):
    import reapy.reascript_api as RPR

    name   = job.get("name", "track")
    midi_m = job.get("midi", {})
    output = job.get("output", "")
    bpm    = job.get("bpm", None)

    proj = reapy.Project()
    progress(f"  Project: {proj.name or '(untitled)'}", log_path)
    RPR.SetEditCurPos(0.0, False, False)

    # ── Set project BPM if provided ───────────────────────────────────────────
    if bpm and bpm > 0:
        RPR.SetTempoTimeSigMarker(proj.id, -1, 0, -1, -1, float(bpm), 0, 0, False)
        progress(f"  BPM set to {bpm}", log_path)

    # ── Set project sample rate ───────────────────────────────────────────────
    if sample_rate:
        RPR.GetSetProjectInfo_String(proj.id, "RENDER_SRATE", str(sample_rate), True)

    # ── Clear all existing media items ────────────────────────────────────────
    all_count = RPR.CountMediaItems(proj.id)
    if all_count > 0:
        progress(f"  Clearing {all_count} existing item(s)…", log_path)
        RPR.SelectAllMediaItems(proj.id, True)
        RPR.Main_OnCommand(40006, 0)   # Edit: Remove selected media items

    # ── Import MIDI per track ─────────────────────────────────────────────────
    loaded = []
    n_tracks = RPR.CountTracks(proj.id)
    for ti in range(n_tracks):
        tr    = RPR.GetTrack(proj.id, ti)
        tname = str(RPR.GetSetMediaTrackInfo_String(tr, "P_NAME", "", False)[3]).strip()

        midi_path = (midi_m.get(tname)
                     or midi_m.get(tname.capitalize())
                     or midi_m.get(tname.lower()))
        if not midi_path:
            continue
        if not os.path.exists(midi_path):
            progress(f"  WARNING: MIDI not found: {midi_path}", log_path)
            continue

        RPR.SetOnlyTrackSelected(tr)
        RPR.InsertMedia(midi_path, 0)
        loaded.append(tname)
        progress(f"  '{tname}' ← {os.path.basename(midi_path)}", log_path)

    if not loaded:
        progress(
            f"  WARNING: No tracks loaded. Verify template has tracks named "
            f"Bass, Pad, Melody, Drums (got {n_tracks} tracks).",
            log_path
        )
        return False

    # ── Configure render output ───────────────────────────────────────────────
    if output:
        out_dir  = os.path.dirname(output)
        out_stem = os.path.splitext(os.path.basename(output))[0]
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
            RPR.GetSetProjectInfo_String(proj.id, "RENDER_FILE",    out_dir,  True)
            RPR.GetSetProjectInfo_String(proj.id, "RENDER_PATTERN", out_stem, True)

        # Set render bounds to "entire project" (time selection)
        RPR.GetSetProjectInfo(proj.id, "RENDER_STARTPOS", 0.0, True)

        # Delete existing file so REAPER doesn't show "file already exists" dialog
        if os.path.exists(output):
            try:
                os.remove(output)
                progress(f"  Removed previous: {os.path.basename(output)}", log_path)
            except OSError as e:
                progress(f"  WARNING: Could not remove previous file: {e}", log_path)

    # ── Trigger render: action 41824 = render + auto-close ───────────────────
    RPR.Main_OnCommand(41824, 0)
    progress(f"  Render triggered — waiting for output…", log_path)

    # ── Poll for WAV output ───────────────────────────────────────────────────
    if output:
        for tick in range(240):     # up to 4 minutes
            time.sleep(1.0)
            if os.path.exists(output) and os.path.getsize(output) > 4096:
                kb = os.path.getsize(output) // 1024
                progress(f"  ✓ Done → {os.path.basename(output)} ({kb} KB)", log_path)
                return True
            if tick > 0 and tick % 30 == 0:
                progress(f"  Still waiting… ({tick}s)", log_path)

        progress(
            f"  TIMEOUT — {os.path.basename(output)} not produced after 240s.\n"
            f"  Check REAPER's render dialog or template configuration.",
            log_path
        )
        return False

    return True


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    main()
