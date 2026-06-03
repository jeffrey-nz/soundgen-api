#!/usr/bin/env python3
"""
play_midi.py — Play a showcase composition in real-time via MIDI output.

Reads all 4 MIDI files (bass/pad/melody/drums) for the given piece, merges
their events by absolute time, then sends them to the loopMIDI port so
Kontakt plays back with the real instrument patches.

Usage:
    python play_midi.py <piece_id>
    python play_midi.py --panic     # emergency all-notes-off on all channels
"""
import sys, os, json, time, signal, threading

DASHBOARD = os.path.dirname(os.path.abspath(__file__))
MIDI_BASE = os.path.join(DASHBOARD, 'showcase-midi')


def get_port_hint():
    try:
        with open(os.path.join(DASHBOARD, 'kontakt-setup.json')) as f:
            return json.load(f).get('midiPortName', 'loop')
    except Exception:
        return 'loop'


def open_midi_out(hint):
    import rtmidi
    mout = rtmidi.MidiOut()
    ports = mout.get_ports()
    for i, p in enumerate(ports):
        if hint.lower() in p.lower():
            mout.open_port(i)
            return mout, p
    # fallback: prefer any port with 'loop' in name
    for i, p in enumerate(ports):
        if 'loop' in p.lower():
            mout.open_port(i)
            return mout, p
    if ports:
        mout.open_port(0)
        return mout, ports[0]
    raise RuntimeError('No MIDI output ports found')


def send_all_notes_off(mout):
    """Send all-notes-off, sustain release, and pitch-bend reset on all 16 channels."""
    for ch in range(16):
        try:
            mout.send_message([0xB0 | ch, 123, 0])   # all notes off
            mout.send_message([0xB0 | ch, 121, 0])   # reset all controllers
            mout.send_message([0xB0 | ch,  64, 0])   # sustain pedal off
            mout.send_message([0xE0 | ch,   0, 64])  # pitch bend center
        except Exception:
            pass


def panic_mode():
    """Open MIDI port and immediately send all-notes-off, then exit."""
    hint = get_port_hint()
    try:
        import rtmidi
        mout = rtmidi.MidiOut()
        ports = mout.get_ports()
        opened = False
        for i, p in enumerate(ports):
            if hint.lower() in p.lower() or 'loop' in p.lower():
                mout.open_port(i)
                opened = True
                break
        if not opened and ports:
            mout.open_port(0)
            opened = True
        if opened:
            send_all_notes_off(mout)
            mout.close_port()
            print('[play_midi] MIDI panic sent — all notes off on all channels')
        else:
            print('[play_midi] No MIDI port found for panic', file=sys.stderr)
    except Exception as e:
        print(f'[play_midi] Panic error: {e}', file=sys.stderr)


def main():
    if len(sys.argv) > 1 and sys.argv[1] == '--panic':
        panic_mode()
        return

    piece_id = sys.argv[1] if len(sys.argv) > 1 else None
    if not piece_id:
        print('[play_midi] Usage: play_midi.py <piece_id>', file=sys.stderr)
        sys.exit(1)

    midi_dir = os.path.join(MIDI_BASE, piece_id)
    if not os.path.isdir(midi_dir):
        print(f'[play_midi] MIDI directory not found: {midi_dir}', file=sys.stderr)
        sys.exit(1)

    import mido

    events = []   # (abs_sec, raw_bytes)
    tempo = 500000  # default 120 BPM — overridden by set_tempo messages

    for tname in ('bass', 'pad', 'melody', 'drums'):
        path = os.path.join(midi_dir, f'{tname}.mid')
        if not os.path.exists(path):
            continue
        mf = mido.MidiFile(path)
        tpb = mf.ticks_per_beat
        abs_ticks = 0
        cur_tempo = tempo
        for msg in mf.merged_track:
            abs_ticks += msg.time
            if msg.type == 'set_tempo':
                cur_tempo = msg.tempo
                tempo = cur_tempo
                continue
            if msg.is_meta:
                continue
            t_sec = mido.tick2second(abs_ticks, tpb, cur_tempo)
            events.append((t_sec, bytes(msg.bytes())))

    events.sort(key=lambda x: x[0])

    if not events:
        print(f'[play_midi] No MIDI events for "{piece_id}"', file=sys.stderr)
        sys.exit(1)

    hint = get_port_hint()
    try:
        mout, port_name = open_midi_out(hint)
    except RuntimeError as e:
        print(f'[play_midi] {e}', file=sys.stderr)
        sys.exit(1)

    duration = events[-1][0]
    print(f'[play_midi] "{piece_id}" -> "{port_name}" ({len(events)} events, {duration:.1f}s)')
    sys.stdout.flush()

    running = [True]

    # ── Graceful stop via stdin (server writes "stop\n") ──────────────────────
    # This is the primary stop mechanism on Windows where SIGTERM is a hard kill.
    def _watch_stdin():
        try:
            for line in sys.stdin:
                if line.strip() in ('stop', 'panic'):
                    running[0] = False
                    break
        except Exception:
            pass
        running[0] = False

    stdin_thread = threading.Thread(target=_watch_stdin, daemon=True)
    stdin_thread.start()

    # ── Signal handlers (fallback — may not run on Windows hard-kill) ─────────
    def _on_signal(sig, frame):
        running[0] = False

    try:
        signal.signal(signal.SIGTERM, _on_signal)
        signal.signal(signal.SIGINT,  _on_signal)
    except Exception:
        pass

    start = time.monotonic()
    for t_sec, raw in events:
        if not running[0]:
            break
        wait = t_sec - (time.monotonic() - start)
        if wait > 0.001:
            time.sleep(wait)
        if not running[0]:
            break
        try:
            mout.send_message(list(raw))
        except Exception:
            pass

    # ── Clean shutdown ─────────────────────────────────────────────────────────
    send_all_notes_off(mout)
    mout.close_port()
    print('[play_midi] Done')


if __name__ == '__main__':
    main()
