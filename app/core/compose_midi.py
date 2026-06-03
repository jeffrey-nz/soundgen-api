"""
Compose orchestral MIDI files and import into REAPER tracks.
Key: C major, Tempo: 80 BPM, Time: 4/4, Length: 8 bars
"""
import sys, struct, os, warnings
sys.path.insert(0, r'C:\Users\Work\python312\Lib\site-packages')

# ── MIDI helpers ────────────────────────────────────────────────────────────

def var_len(n):
    """Encode non-negative integer as MIDI variable-length quantity."""
    assert n >= 0, f"var_len({n}) called with negative value"
    buf = [n & 0x7F]
    n >>= 7
    while n:
        buf.append((n & 0x7F) | 0x80)
        n >>= 7
    return bytes(reversed(buf))

def events_to_bytes(event_list):
    """
    Convert list of (abs_tick, status, d1, d2) into delta-time MIDI bytes.
    Sort by abs_tick, then convert to deltas.
    """
    event_list.sort(key=lambda e: e[0])
    result = b''
    last_tick = 0
    for abs_tick, status, d1, d2 in event_list:
        delta = abs_tick - last_tick
        assert delta >= 0, f"Negative delta: {delta} at tick {abs_tick} after {last_tick}"
        result += var_len(delta) + bytes([status, d1, d2])
        last_tick = abs_tick
    return result

def meta_event(abs_tick, meta_type, data):
    """Return (abs_tick, is_meta, data_bytes) — handled separately."""
    delta_bytes = var_len(0)  # placeholder, caller sorts
    return delta_bytes + b'\xff' + bytes([meta_type, len(data)]) + data

def make_track(events_bytes):
    """Wrap event bytes into an MTrk chunk."""
    return b'MTrk' + struct.pack('>I', len(events_bytes)) + events_bytes

def make_midi_file(track_chunks, tpb=480):
    n = len(track_chunks)
    header = b'MThd' + struct.pack('>IHHH', 6, 1, n, tpb)
    return header + b''.join(track_chunks)

# ── Musical constants ────────────────────────────────────────────────────────

TPB = 480       # ticks per beat
BPM = 80
WHOLE  = TPB * 4
HALF   = TPB * 2
QTR    = TPB
EIGHTH = TPB // 2

# MIDI note numbers
C2,D2,E2,F2,G2,A2,B2 = 36,38,40,41,43,45,47
C3,D3,E3,F3,G3,A3,B3 = 48,50,52,53,55,57,59
C4,D4,E4,F4,G4,A4,B4 = 60,62,64,65,67,69,71
C5,D5,E5,F5,G5,A5,B5 = 72,74,76,77,79,81,83

def track_header_bytes(bpm):
    """Return raw bytes: tempo + time sig meta events at tick 0."""
    us = int(60_000_000 / bpm)
    tempo_data = struct.pack('>I', us)[1:]  # 3 bytes
    tempo = b'\x00\xff\x51\x03' + tempo_data
    timesig = b'\x00\xff\x58\x04\x04\x02\x18\x08'
    return tempo + timesig

def end_track_bytes():
    return b'\x00\xff\x2f\x00'

def notes_track(ch, note_seq, bpm=BPM):
    """
    note_seq: list of (note, duration_ticks, velocity)
    Returns track bytes.
    """
    # Build absolute-time event list
    evts = []  # (abs_tick, status, d1, d2)
    tick = 0
    for note, dur, vel in note_seq:
        evts.append((tick, 0x90 | ch, note, vel))      # note on
        evts.append((tick + dur, 0x80 | ch, note, 0))  # note off
        tick += dur
    evts.sort(key=lambda e: (e[0], 1 if (e[1] & 0xf0) == 0x80 else 0))  # note-offs first at same tick
    raw = track_header_bytes(bpm) + events_to_bytes(evts) + end_track_bytes()
    return make_track(raw)

def chord_track(ch, chord_seq, bpm=BPM):
    """
    chord_seq: list of (notes_list, duration_ticks, velocity)
    All notes in a chord start simultaneously.
    """
    evts = []
    tick = 0
    for notes, dur, vel in chord_seq:
        for n in notes:
            evts.append((tick, 0x90 | ch, n, vel))
            evts.append((tick + dur, 0x80 | ch, n, 0))
        tick += dur
    evts.sort(key=lambda e: (e[0], 1 if (e[1] & 0xf0) == 0x80 else 0))
    raw = track_header_bytes(bpm) + events_to_bytes(evts) + end_track_bytes()
    return make_track(raw)

def drums_track(bars_of_events, bpm=BPM):
    """
    bars_of_events: list of bars, each bar is list of (bar_tick_offset, note, vel).
    note_off sent EIGHTH//2 ticks later.
    Channel 9 = GM drums.
    """
    ch = 9
    evts = []
    abs_offset = 0
    for bar_events in bars_of_events:
        for beat_tick, note, vel in bar_events:
            at = abs_offset + beat_tick
            evts.append((at, 0x99, note, vel))                    # note on ch 9
            evts.append((at + EIGHTH // 2, 0x89, note, 0))        # note off
        abs_offset += WHOLE  # one bar = 4 beats
    evts.sort(key=lambda e: (e[0], 1 if (e[1] & 0xf0) == 0x80 else 0))
    raw = track_header_bytes(bpm) + events_to_bytes(evts) + end_track_bytes()
    return make_track(raw)

# ── Compose tracks ───────────────────────────────────────────────────────────

# Track 0: Bass (Cellos) — whole-note bass line
bass_notes = [
    (C2, WHOLE, 90), (G2, WHOLE, 85),   # bars 1-2: C maj
    (A2, WHOLE, 88), (E2, WHOLE, 82),   # bars 3-4: A min
    (F2, WHOLE, 88), (C3, WHOLE, 85),   # bars 5-6: F maj
    (G2, HALF,  90), (D3, HALF,  85),   # bar 7: G maj (two halves)
    (C2, WHOLE, 95),                    # bar 8: C root resolution
]

# Track 1: Pad (Olympus Elements) — whole-note chords
pad_chords = [
    ([E3, G3, C4], WHOLE, 68), ([E3, G3, C4], WHOLE, 65),  # bars 1-2
    ([A3, C4, E4], WHOLE, 68), ([A3, C4, E4], WHOLE, 65),  # bars 3-4
    ([F3, A3, C4], WHOLE, 68), ([F3, A3, C4], WHOLE, 65),  # bars 5-6
    ([G3, B3, D4], WHOLE, 68), ([C4, E4, G4], WHOLE, 70),  # bars 7-8
]

# Track 2: Melody (Violins 1 Essential) — quarter note melody
melody_notes = [
    # Bar 1
    (C5, QTR, 82), (E5, QTR, 85), (G5, QTR, 88), (A5, QTR, 85),
    # Bar 2
    (G5, QTR, 82), (E5, QTR, 80), (D5, QTR, 78), (E5, QTR, 80),
    # Bar 3
    (A4, QTR, 82), (C5, QTR, 85), (E5, QTR, 88), (D5, QTR, 85),
    # Bar 4
    (C5, QTR, 82), (B4, QTR, 80), (A4, QTR, 78), (G4, QTR, 75),
    # Bar 5
    (F4, QTR, 80), (A4, QTR, 82), (C5, QTR, 85), (A4, QTR, 82),
    # Bar 6
    (F4, QTR, 78), (E4, QTR, 76), (D4, QTR, 74), (C4, QTR, 72),
    # Bar 7
    (G4, QTR, 82), (B4, QTR, 85), (D5, QTR, 88), (B4, QTR, 85),
    # Bar 8
    (C5, HALF, 88), (G4, QTR, 78), (C4, QTR, 72),
]

# Track 3: Drums (Orchestral Percussion)
# GM notes: BD=36, SD=38, CHH=42, Ride=51, Crash=49, HiTom=50
BD, SD, CHH, RIDE, CRASH, HTOM = 36, 38, 42, 51, 49, 50

def standard_bar():
    return [
        (0,        BD,   78), (0,        RIDE, 58),
        (QTR,      SD,   72), (QTR,      RIDE, 55),
        (QTR*2,    BD,   75), (QTR*2,    RIDE, 58),
        (QTR*3,    SD,   70), (QTR*3,    RIDE, 55),
    ]

def crash_bar():
    return [
        (0,        CRASH,80), (0,        BD,   82),
        (QTR,      SD,   75), (QTR,      RIDE, 55),
        (QTR*2,    BD,   78), (QTR*2,    RIDE, 58),
        (QTR*3,    SD,   72), (QTR*3,    RIDE, 55),
    ]

def build_bar():
    return [
        (0,          BD,   78), (0,          RIDE, 58),
        (EIGHTH,     CHH,  45),
        (QTR,        SD,   78), (QTR,        RIDE, 55),
        (QTR+EIGHTH, CHH,  45),
        (QTR*2,      BD,   75), (QTR*2,      RIDE, 58),
        (QTR*2+EIGHTH, CHH,45),
        (QTR*3,      SD,   75), (QTR*3,      RIDE, 55),
        (QTR*3+EIGHTH, CHH,45),
    ]

drums_bars = [
    crash_bar(),    # Bar 1
    standard_bar(), # Bar 2
    standard_bar(), # Bar 3
    standard_bar(), # Bar 4
    standard_bar(), # Bar 5
    build_bar(),    # Bar 6
    build_bar(),    # Bar 7
    crash_bar(),    # Bar 8
]

# ── Build and write MIDI files ───────────────────────────────────────────────

out_dir = r'C:\Users\Work\procmusic\dashboard~'

bass_trk   = notes_track(0, bass_notes)
pad_trk    = chord_track(1, pad_chords)
melody_trk = notes_track(2, melody_notes)
drum_trk   = drums_track(drums_bars)

midi_files = {
    'bass.mid':   make_midi_file([bass_trk]),
    'pad.mid':    make_midi_file([pad_trk]),
    'melody.mid': make_midi_file([melody_trk]),
    'drums.mid':  make_midi_file([drum_trk]),
}

for fname, data in midi_files.items():
    path = os.path.join(out_dir, fname)
    with open(path, 'wb') as f:
        f.write(data)
    print(f'Written: {path} ({len(data)} bytes)')

# ── Import into REAPER ───────────────────────────────────────────────────────

with warnings.catch_warnings():
    warnings.simplefilter('ignore')
    import reapy

try:
    from reapy.tools.network import machines as _m
    if _m.CLIENT is None:
        import importlib
        from reapy.tools.network.client import Client as _C
        _port = reapy.config.REAPY_SERVER_PORT
        _c = _C(_port, 'localhost')
        _m.CLIENT = _c; _m.CLIENTS['localhost'] = _c; _m.CLIENTS[None] = _c
        importlib.reload(reapy.reascript_api)
except Exception as e:
    print(f'Connect error: {e}'); sys.exit(1)

import reapy.reascript_api as RPR
proj = reapy.Project()

# Set project BPM
RPR.SetTempoTimeSigMarker(proj.id, -1, 0, -1, -1, float(BPM), 4, 4, True)
print(f'Tempo set to {BPM} BPM')

track_files = [
    (0, 'bass.mid'),
    (1, 'pad.mid'),
    (2, 'melody.mid'),
    (3, 'drums.mid'),
]

for track_idx, fname in track_files:
    tr = RPR.GetTrack(proj.id, track_idx)
    tname = str(RPR.GetSetMediaTrackInfo_String(tr, 'P_NAME', '', False)[3]).strip()
    mid_path = os.path.join(out_dir, fname).replace('\\', '/')

    # Delete existing items on this track
    n_items = RPR.CountTrackMediaItems(tr)
    for _ in range(n_items):
        item = RPR.GetTrackMediaItem(tr, 0)
        RPR.DeleteTrackMediaItem(tr, item)
    print(f'Track {track_idx} {tname!r}: cleared {n_items} items')

    # Insert MIDI at position 0
    item = RPR.InsertMediaSection(mid_path, 0, 0, -1, 0)
    if item:
        print(f'  Inserted {fname} -> item={item}')
    else:
        # Fallback: use InsertMedia
        RPR.SetOnlyTrackSelected(tr)
        ret = RPR.InsertMedia(mid_path, 0)
        print(f'  InsertMedia({fname}) = {ret}')

RPR.Main_SaveProject(proj.id, False)
print('Project saved with MIDI tracks')
