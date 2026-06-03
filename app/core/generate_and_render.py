#!/usr/bin/env python3
"""
generate_and_render.py — Single-command pipeline for procmusic.

Steps:
  1. Generate MIDI files for all showcase compositions (showcase_compositions.py)
  2. For 'kontakt' pieces: render via REAPER + Kontakt (reaper_render.py)
  3. For 'synth' pieces:   render via Python synthesizer (render_synth.py)

Usage:
    python generate_and_render.py [options] [piece_id ...]

Options:
    --all           Generate + render everything (default)
    --midi-only     Only generate MIDI, skip rendering
    --synth-only    Only render synth pieces (no REAPER needed)
    --reaper-only   Only render kontakt pieces via REAPER
    --force         Re-render even if WAV already exists
    --ids ID [ID…]  Only process specific piece IDs
    --no-midi       Skip MIDI generation (use existing files)

Prerequisites:
    pip install python-reapy mido numpy scipy
    python -c "import reapy; reapy.configure_reaper()"
    REAPER running with BGM template loaded (Bass/Pad/Melody/Drums tracks + Kontakt)
"""

import sys
import os
import json
import time
import argparse
import subprocess
import tempfile

DASHBOARD = os.path.dirname(os.path.abspath(__file__))
MIDI_BASE  = os.path.join(DASHBOARD, 'showcase-midi')
AUDIO_OUT  = os.path.join(DASHBOARD, 'showcase-audio')
LOG_FILE   = os.path.join(DASHBOARD, 'render-progress.log')
CONFIG_DIR = DASHBOARD

PYTHON = sys.executable

# Catalog — mirrors server.js SHOWCASE_CATALOG (source: 'kontakt' or 'synth')
CATALOG = [
    {'id': 'orchestral_piece',  'bpm': 80,  'source': 'kontakt'},
    {'id': 'heroic_march',      'bpm': 120, 'source': 'kontakt'},
    {'id': 'forest_wanderer',   'bpm': 68,  'source': 'kontakt'},
    {'id': 'battle_cry',        'bpm': 145, 'source': 'synth'},
    {'id': 'tavern_jig',        'bpm': 168, 'source': 'synth'},
    {'id': 'sad_elegy',         'bpm': 52,  'source': 'kontakt'},
    {'id': 'dungeon_depths',    'bpm': 76,  'source': 'kontakt'},
    {'id': 'victory_fanfare',   'bpm': 138, 'source': 'kontakt'},
    {'id': 'peaceful_village',  'bpm': 88,  'source': 'kontakt'},
    {'id': 'dragons_lair',      'bpm': 155, 'source': 'synth'},
    {'id': 'twilight_lullaby',  'bpm': 62,  'source': 'kontakt'},
    {'id': 'celtic_dawn',       'bpm': 96,  'source': 'synth'},
    {'id': 'moonlight_reverie', 'bpm': 72,  'source': 'kontakt'},
    {'id': 'passacaglia',       'bpm': 80,  'source': 'kontakt'},
    {'id': 'midnight_blues',    'bpm': 88,  'source': 'kontakt'},
    {'id': 'silk_road',         'bpm': 80,  'source': 'synth'},
    {'id': 'haunted_manor',     'bpm': 55,  'source': 'synth'},
    {'id': 'river_street_rag',  'bpm': 104, 'source': 'kontakt'},
    {'id': 'crimson_tango',     'bpm': 116, 'source': 'synth'},
    {'id': 'neon_drift',        'bpm': 128, 'source': 'synth'},
    {'id': 'delta_blues',       'bpm': 76,  'source': 'kontakt'},
    {'id': 'bossa_nova',        'bpm': 130, 'source': 'synth'},
    {'id': 'flamenco',          'bpm': 142, 'source': 'synth'},
    {'id': 'baroque_minuet',    'bpm': 116, 'source': 'kontakt'},
    {'id': 'kingston_sunrise',  'bpm': 82,  'source': 'synth'},
    {'id': 'glory_road',        'bpm': 88,  'source': 'kontakt'},
    {'id': 'groove_engine',     'bpm': 96,  'source': 'synth'},
    {'id': 'blue_ridge_morning','bpm': 100, 'source': 'synth'},
    {'id': 'soul_searching',    'bpm': 76,  'source': 'kontakt'},
    {'id': 'swing_city',        'bpm': 152, 'source': 'kontakt'},
    {'id': 'lagos_groove',      'bpm': 116, 'source': 'synth'},
    {'id': 'sacred_chorale',    'bpm': 56,  'source': 'kontakt'},
    {'id': 'viennese_waltz',    'bpm': 126, 'source': 'kontakt'},
    {'id': 'morning_mist',      'bpm': 60,  'source': 'kontakt'},
    {'id': 'samba_carnival',    'bpm': 108, 'source': 'synth'},
    {'id': 'glass_etude',       'bpm': 84,  'source': 'kontakt'},
    {'id': 'polka_village',     'bpm': 132, 'source': 'synth'},
    {'id': 'appalachian_fire',  'bpm': 160, 'source': 'synth'},
    {'id': 'klezmer_dance',     'bpm': 134, 'source': 'synth'},
    {'id': 'urban_pulse',       'bpm': 88,  'source': 'synth'},
    {'id': 'crimson_dawn',      'bpm': 72,  'source': 'kontakt'},
    {'id': 'sakura_dreams',     'bpm': 88,  'source': 'synth'},
    {'id': 'lost_cathedral',    'bpm': 52,  'source': 'kontakt'},
    {'id': 'electric_storm',    'bpm': 140, 'source': 'synth'},
]


def log(msg):
    print(msg, flush=True)
    try:
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(msg + '\n')
    except OSError:
        pass


def section(title):
    log(f"\n{'─' * 60}")
    log(f"  {title}")
    log(f"{'─' * 60}")


# ── Step 1: Generate MIDI ─────────────────────────────────────────────────────

def generate_midi(ids=None, force=False):
    section("Step 1: Generate MIDI files (showcase_compositions.py)")
    result = subprocess.run(
        [PYTHON, '-u', os.path.join(DASHBOARD, 'showcase_compositions.py')],
        cwd=DASHBOARD,
        capture_output=False,
    )
    if result.returncode != 0:
        log(f"WARNING: showcase_compositions.py exited {result.returncode}")
        return False

    # Verify output
    missing = []
    check_ids = ids or [c['id'] for c in CATALOG]
    for pid in check_ids:
        bass = os.path.join(MIDI_BASE, pid, 'bass.mid')
        if not os.path.exists(bass):
            missing.append(pid)
    if missing:
        log(f"WARNING: MIDI missing for: {', '.join(missing)}")
    else:
        log(f"✓ MIDI generated for {len(check_ids)} composition(s).")
    return True


# ── Step 2: Render synth pieces ───────────────────────────────────────────────

def render_synth(pieces, force=False):
    section(f"Step 2a: Render {len(pieces)} synth piece(s) via Python synthesizer")
    ids = [p['id'] for p in pieces]
    if not force:
        ids = [pid for pid in ids if not wav_exists(pid)]
        if not ids:
            log("All synth pieces already rendered. Use --force to re-render.")
            return True

    args = [PYTHON, '-u', os.path.join(DASHBOARD, 'render_synth.py')] + ids
    result = subprocess.run(args, cwd=DASHBOARD, capture_output=False)
    if result.returncode != 0:
        log(f"WARNING: render_synth.py exited {result.returncode}")
        return False
    log(f"✓ Synth render complete.")
    return True


# ── Step 3: Render kontakt pieces via REAPER ──────────────────────────────────

def render_kontakt(pieces, force=False, template='', sample_rate=44100):
    section(f"Step 2b: Render {len(pieces)} kontakt piece(s) via REAPER + Kontakt")

    # Check MIDI files exist
    jobs = []
    for p in pieces:
        pid     = p['id']
        wav_out = os.path.join(AUDIO_OUT, f"{pid}.wav")
        if not force and wav_exists(pid):
            log(f"  SKIP {pid} — already rendered")
            continue
        midi_dir = os.path.join(MIDI_BASE, pid)
        bass     = os.path.join(midi_dir, 'bass.mid')
        if not os.path.exists(bass):
            log(f"  SKIP {pid} — no MIDI (run without --no-midi to generate)")
            continue
        jobs.append({
            'name':   pid,
            'bpm':    p.get('bpm', 120),
            'midi':   {
                'Bass':   os.path.join(midi_dir, 'bass.mid'),
                'Pad':    os.path.join(midi_dir, 'pad.mid'),
                'Melody': os.path.join(midi_dir, 'melody.mid'),
                'Drums':  os.path.join(midi_dir, 'drums.mid'),
            },
            'output': wav_out,
        })

    if not jobs:
        log("No kontakt jobs to render.")
        return True

    # Resolve template path from config if not provided
    if not template:
        config_path = os.path.join(DASHBOARD, 'reaper-config.json')
        try:
            with open(config_path, encoding='utf-8') as f:
                cfg = json.load(f)
            template = cfg.get('template', '')
            sample_rate = cfg.get('sample_rate', 44100)
        except (OSError, json.JSONDecodeError):
            pass

    if not template:
        log("WARNING: No REAPER template configured. Set it in the REAPER tab or reaper-config.json.")
        log("         Continuing without template — REAPER will use its currently open project.")

    os.makedirs(AUDIO_OUT, exist_ok=True)

    # Write render config
    render_config = {
        'jobs':        jobs,
        'template':    template,
        'log':         LOG_FILE,
        'sample_rate': sample_rate,
    }
    config_file = os.path.join(CONFIG_DIR, f'_render_config_{int(time.time())}.json')
    try:
        with open(config_file, 'w', encoding='utf-8') as f:
            json.dump(render_config, f, indent=2)
    except OSError as e:
        log(f"ERROR: Cannot write render config: {e}")
        return False

    log(f"  Launching reaper_render.py for {len(jobs)} job(s)…")
    try:
        result = subprocess.run(
            [PYTHON, '-u', os.path.join(DASHBOARD, 'reaper_render.py'), config_file],
            cwd=DASHBOARD,
            capture_output=False,
        )
        ok = result.returncode == 0
    finally:
        try:
            os.remove(config_file)
        except OSError:
            pass

    if ok:
        log("✓ REAPER render complete.")
    else:
        log(f"WARNING: reaper_render.py exited {result.returncode}")
    return ok


# ── Helpers ───────────────────────────────────────────────────────────────────

def wav_exists(pid):
    p = os.path.join(AUDIO_OUT, f"{pid}.wav")
    return os.path.exists(p) and os.path.getsize(p) > 50_000


def filter_catalog(catalog, ids=None, source_filter=None):
    items = catalog
    if ids:
        id_set = set(ids)
        items  = [c for c in items if c['id'] in id_set]
    if source_filter:
        items = [c for c in items if c['source'] == source_filter]
    return items


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='Generate MIDI and render all showcase compositions')
    parser.add_argument('ids', nargs='*', help='Piece IDs to process (default: all)')
    parser.add_argument('--all',        action='store_true', help='Generate + render everything (default)')
    parser.add_argument('--midi-only',  action='store_true', help='Only generate MIDI, skip rendering')
    parser.add_argument('--synth-only', action='store_true', help='Only render synth pieces')
    parser.add_argument('--reaper-only',action='store_true', help='Only render kontakt pieces via REAPER')
    parser.add_argument('--no-midi',    action='store_true', help='Skip MIDI generation step')
    parser.add_argument('--force',      action='store_true', help='Re-render even if WAV exists')
    parser.add_argument('--template',   default='',          help='REAPER template .rpp path')
    parser.add_argument('--sample-rate',type=int, default=0, help='Sample rate (default: from config)')
    args = parser.parse_args()

    ids = args.ids if args.ids else None

    # Clear log
    try:
        open(LOG_FILE, 'w').close()
    except OSError:
        pass

    log(f"procmusic generate_and_render.py — {time.strftime('%Y-%m-%d %H:%M:%S')}")
    log(f"IDs: {', '.join(ids) if ids else 'all'}")
    log(f"Force: {args.force}")

    # Step 1: MIDI generation
    if not args.no_midi and not args.reaper_only and not args.synth_only:
        ok = generate_midi(ids=ids, force=args.force)
        if not ok:
            log("MIDI generation had errors — continuing anyway.")
    elif args.no_midi:
        log("Skipping MIDI generation (--no-midi).")

    if args.midi_only:
        log("\nDone (--midi-only).")
        return

    # Step 2: Render
    synth_pieces  = filter_catalog(CATALOG, ids=ids, source_filter='synth')
    kontakt_pieces = filter_catalog(CATALOG, ids=ids, source_filter='kontakt')

    if not args.reaper_only:
        if synth_pieces:
            render_synth(synth_pieces, force=args.force)
        else:
            log("No synth pieces to render.")

    if not args.synth_only:
        if kontakt_pieces:
            sr = args.sample_rate or 0
            render_kontakt(kontakt_pieces, force=args.force,
                           template=args.template, sample_rate=sr or 44100)
        else:
            log("No kontakt pieces to render.")

    # Summary
    section("Summary")
    rendered   = sum(1 for c in filter_catalog(CATALOG, ids=ids) if wav_exists(c['id']))
    total      = len(filter_catalog(CATALOG, ids=ids))
    log(f"  {rendered} / {total} WAV files present.")
    log("\n✓ Pipeline complete.")


if __name__ == '__main__':
    main()
