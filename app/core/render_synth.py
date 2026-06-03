"""
render_synth.py — Batch render all showcase pieces using midi_synth.py.

Renders every piece whose MIDI files exist into showcase-audio/<id>.wav.
Much faster and more reliable than the REAPER/Kontakt approach — no external
tools required, pure Python + numpy synthesis.

Usage:
    python render_synth.py                  # render all missing pieces
    python render_synth.py --force          # re-render all pieces
    python render_synth.py heroic_march     # render specific piece(s)
    python render_synth.py --force heroic_march tavern_jig
"""
import sys, os, time

DASHBOARD = os.path.dirname(os.path.abspath(__file__))
MIDI_BASE  = os.environ.get('MIDI_OUTPUT_DIR',  os.path.join(DASHBOARD, 'showcase-midi'))
AUDIO_OUT  = os.environ.get('AUDIO_OUTPUT_DIR', os.path.join(DASHBOARD, 'showcase-audio'))

sys.path.insert(0, DASHBOARD)


def _scan_imported_pieces(skip_ids):
    """Scan showcase-midi/<id>/catalog.json for OMR-imported pieces not in
    showcase_compositions.CATALOG.  Returns {id: meta_dict}."""
    import json, glob
    imported = {}
    for cat_path in glob.glob(os.path.join(MIDI_BASE, '*', 'catalog.json')):
        pid = os.path.basename(os.path.dirname(cat_path))
        if pid in skip_ids:
            continue
        try:
            with open(cat_path, encoding='utf-8') as fh:
                imported[pid] = json.load(fh)
        except Exception:
            pass
    return imported


def main():
    from showcase_compositions import CATALOG, generate_all
    from midi_synth import synth_piece

    args = sys.argv[1:]
    force = '--force' in args
    if force:
        args = [a for a in args if a != '--force']
    requested = set(args)

    # Generate MIDI files first (only procedural pieces; imports are pre-baked)
    print('Step 1: Generating MIDI files...')
    generate_all()
    print()

    # Pick up OMR-imported pieces that aren't in the hardcoded catalog
    imported = _scan_imported_pieces(skip_ids=set(CATALOG.keys()))
    if imported:
        print(f'Found {len(imported)} imported piece(s): {", ".join(imported)}\n')

    os.makedirs(AUDIO_OUT, exist_ok=True)

    # Build render list (procedural + imported)
    full_catalog = {**CATALOG, **imported}
    to_render = [
        (pid, meta) for pid, meta in full_catalog.items()
        if not requested or pid in requested
    ]

    total = len(to_render)
    print(f'Step 2: Synthesizing {total} piece(s)...\n')

    results = {}
    t0_all = time.time()

    for i, (pid, meta) in enumerate(to_render):
        out_wav = os.path.join(AUDIO_OUT, f'{pid}.wav')
        midi_dir = os.path.join(MIDI_BASE, pid)

        # Skip if already rendered and not forced
        if not force and os.path.exists(out_wav) and os.path.getsize(out_wav) > 50_000:
            # Check it's not all-zero silence
            import wave as wv
            try:
                with wv.open(out_wav, 'r') as wf:
                    frames = wf.readframes(4096)
                has_audio = any(b != 0 for b in frames)
            except Exception:
                has_audio = False
            if has_audio:
                dur = os.path.getsize(out_wav) / (44100 * 2 * 2)
                print(f'  [{i+1}/{total}] [skip] {pid} ({dur:.1f}s, has audio)')
                results[pid] = True
                continue
            else:
                print(f'  [{i+1}/{total}] {pid} — existing file is silent, re-rendering')

        if not os.path.isdir(midi_dir):
            # If the WAV file already exists and has audio, keep it
            if os.path.exists(out_wav) and os.path.getsize(out_wav) > 50_000:
                import wave as wv
                try:
                    with wv.open(out_wav, 'r') as wf:
                        frames = wf.readframes(4096)
                    has_audio = any(b != 0 for b in frames)
                except Exception:
                    has_audio = False
                if has_audio:
                    print(f'  [{i+1}/{total}] [skip] {pid} — no MIDI but existing WAV has audio')
                    results[pid] = True
                    continue
            print(f'  [{i+1}/{total}] [skip] {pid} — no MIDI dir')
            results[pid] = False
            continue

        bass   = os.path.join(midi_dir, 'bass.mid')
        pad    = os.path.join(midi_dir, 'pad.mid')
        melody = os.path.join(midi_dir, 'melody.mid')
        drums  = os.path.join(midi_dir, 'drums.mid')

        print(f'  [{i+1}/{total}] {pid} ({meta["title"]}, {meta["bpm"]} BPM)...')
        t0 = time.time()
        try:
            written = synth_piece(bass, pad, melody, drums, out_wav, style=meta.get('genre', ''))
            elapsed = time.time() - t0
            if written:
                wav_path = written if isinstance(written, str) else out_wav
                sz = os.path.getsize(wav_path) // 1024
                tag = '' if wav_path == out_wav else f' (locked -> {os.path.basename(wav_path)})'
                print(f'    OK: {sz} KB in {elapsed:.1f}s{tag}')
            else:
                print(f'    FAILED after {elapsed:.1f}s')
            results[pid] = bool(written)
        except Exception as exc:
            import traceback
            print(f'    ERROR: {exc}')
            traceback.print_exc()
            results[pid] = False

    elapsed_total = time.time() - t0_all
    ok_count = sum(1 for v in results.values() if v)
    print(f'\n=== Results: {ok_count}/{len(results)} OK in {elapsed_total:.0f}s ===')
    for pid, ok in results.items():
        print(f'  [{"OK" if ok else "FAIL"}] {pid}')

    sys.exit(0 if all(results.values()) else 1)


if __name__ == '__main__':
    main()
