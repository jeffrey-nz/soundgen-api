"""
showcase_compositions.py
Generates MIDI files for 10 diverse orchestral compositions.
Run:  python showcase_compositions.py
Outputs to:  dashboard~/showcase-midi/<id>/{bass,pad,melody,drums}.mid
"""
import sys, struct, os, random

OUT_BASE = os.environ.get('MIDI_OUTPUT_DIR', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'showcase-midi'))

# ── MIDI encoding ─────────────────────────────────────────────────────────────

TPB = 480
WHOLE      = TPB * 4
HALF       = TPB * 2
QTR        = TPB
EIGHTH     = TPB // 2
SIXTEENTH  = TPB // 4
DOTTED_QTR = QTR + EIGHTH
DOTTED_HALF = HALF + QTR

# GM drums (channel 9)
BD, SD, CHH, OHH, RIDE, CRASH, HTOM, LTOM = 36, 38, 42, 46, 51, 49, 50, 41

def _note(name, octave):
    semis = {'C':0,'C#':1,'Db':1,'D':2,'D#':3,'Eb':3,'E':4,'F':5,
             'F#':6,'Gb':6,'G':7,'G#':8,'Ab':8,'A':9,'A#':10,'Bb':10,'B':11}
    return semis[name] + (octave + 1) * 12

def vlen(n):
    assert n >= 0
    buf = [n & 0x7F]; n >>= 7
    while n:
        buf.append((n & 0x7F) | 0x80); n >>= 7
    return bytes(reversed(buf))

def _sort_evts(evts):
    # note-offs before note-ons at same tick
    evts.sort(key=lambda e: (e[0], 0 if (e[1] & 0xF0) == 0x80 else 1))
    result = b''; last = 0
    for abs_tick, status, d1, d2 in evts:
        result += vlen(abs_tick - last) + bytes([status, d1, d2])
        last = abs_tick
    return result

def _trk(raw):
    return b'MTrk' + struct.pack('>I', len(raw)) + raw

def _header(bpm, top=4, bot=2):
    us = int(60_000_000 / bpm)
    t = b'\x00\xff\x51\x03' + struct.pack('>I', us)[1:]
    s = b'\x00\xff\x58\x04' + bytes([top, bot, 24, 8])
    return t + s

_END = b'\x00\xff\x2f\x00'

def notes_trk(ch, seq, bpm, top=4, swing=False, timing_jitter=0, rng=None):
    """seq: [(note, dur, vel)] or [(note, dur, vel, sound_dur)] — sound_dur allows staccato.
    swing=True: off-beat 8ths shifted to triplet position (jazz feel).
    timing_jitter: ±ticks of micro-timing offset per note (humanization)."""
    SWING_ON  = (QTR * 2) // 3   # 320 ticks
    SWING_OFF = QTR - SWING_ON   # 160 ticks
    rng = rng or random.Random()
    evts = []; tick = 0; orig_tick = 0
    for item in seq:
        note, dur, vel = item[0], item[1], item[2]
        sound_dur = item[3] if len(item) > 3 else dur
        if swing and dur == EIGHTH:
            orig_beat_pos = orig_tick % QTR
            actual_dur = SWING_ON if orig_beat_pos == 0 else (SWING_OFF if orig_beat_pos == EIGHTH else dur)
        else:
            actual_dur = dur
        sd = max(SIXTEENTH // 2, sound_dur)
        offset = rng.randint(-timing_jitter, timing_jitter) if timing_jitter > 0 and vel > 0 else 0
        t = max(0, tick + offset)
        evts += [(t, 0x90|ch, note, vel), (t + sd, 0x80|ch, note, 0)]
        tick += actual_dur
        orig_tick += dur
    return _trk(_header(bpm, top) + _sort_evts(evts) + _END)

def chords_trk(ch, seq, bpm, top=4):
    """seq: [([notes], dur, vel), ...]"""
    evts = []; tick = 0
    for notes, dur, vel in seq:
        for n in notes:
            evts += [(tick, 0x90|ch, n, vel), (tick+dur, 0x80|ch, n, 0)]
        tick += dur
    return _trk(_header(bpm, top) + _sort_evts(evts) + _END)

def drums_trk(bars, bpm, top=4, bar_ticks=WHOLE):
    """bars: list of [(beat_offset, note, vel), ...]"""
    evts = []; abs_off = 0
    for bar in bars:
        for off, note, vel in bar:
            at = abs_off + off
            evts += [(at, 0x99, note, vel), (at + EIGHTH//2, 0x89, note, 0)]
        abs_off += bar_ticks
    return _trk(_header(bpm, top) + _sort_evts(evts) + _END)

def piano_pad_trk(ch, lh_seq, rh_seq, bpm, top=4):
    """Piano grand-staff MIDI track: merges independent left and right hand sequences
    onto a single channel.  seq format: [(note, dur, vel[, sound_dur]), ...]."""
    evts = []
    for seq in (lh_seq, rh_seq):
        tick = 0
        for item in seq:
            note, dur, vel = item[0], item[1], item[2]
            sd = item[3] if len(item) > 3 else dur
            if vel > 0:
                evts += [(tick, 0x90|ch, note, vel), (tick + max(1, sd), 0x80|ch, note, 0)]
            tick += dur
    return _trk(_header(bpm, top) + _sort_evts(evts) + _END)

def empty_trk(bpm, top=4):
    """A MIDI track with no notes, just tempo/time-sig header."""
    return _trk(_header(bpm, top) + _END)

# ── Dynamics / humanization helpers ──────────────────────────────────────────

def _clamp_vel(v):
    return max(1, min(127, int(v)))

def humanize(seq, jitter=8, rng=None):
    """Apply ±jitter random velocity variation to a notes sequence."""
    rng = rng or random.Random()
    result = []
    for item in seq:
        note, dur, vel = item[0], item[1], item[2]
        new_vel = 0 if vel == 0 else _clamp_vel(vel + rng.randint(-jitter, jitter))
        result.append((note, dur, new_vel) + item[3:])
    return result

def humanize_chords(seq, jitter=6, rng=None):
    """Apply ±jitter to chord sequences."""
    rng = rng or random.Random()
    return [(c[0], c[1], _clamp_vel(c[2] + rng.randint(-jitter, jitter))) for c in seq]

def humanize_drums(bars, jitter=5, rng=None):
    """Apply ±jitter velocity to all drum hits."""
    rng = rng or random.Random()
    return [[(off, drum, _clamp_vel(vel + rng.randint(-jitter, jitter)))
             for off, drum, vel in bar] for bar in bars]

def articulate(seq, fast_ratio=0.55, slow_ratio=0.92, legato=False):
    """Add sound_dur: fast notes (≤EIGHTH) get staccato, longer notes get legato.
    legato=True: slow notes extend 24 ticks past their written duration to trigger
    Kontakt legato transitions (requires notes_trk to allow sd > actual_dur)."""
    LEGATO_OVERLAP = 24  # ~5% of a beat at 480 TPB — enough for legato detection
    result = []
    for item in seq:
        note, dur, vel = item[0], item[1], item[2]
        if dur <= EIGHTH:
            sound_dur = max(SIXTEENTH // 2, int(dur * fast_ratio))
        elif legato:
            sound_dur = dur + LEGATO_OVERLAP
        else:
            sound_dur = max(SIXTEENTH // 2, int(dur * slow_ratio))
        result.append((note, dur, vel, sound_dur))
    return result

def bow_accents(seq, accent=5):
    """Simulate up/down bow alternation on fast string passages.
    Even-indexed fast notes (down bow) get +accent velocity; odd (up bow) get -accent.
    Long notes reset the bow count (phrase boundary)."""
    result = []
    bow_idx = 0
    for item in seq:
        note, dur, vel = item[0], item[1], item[2]
        if dur <= EIGHTH and vel > 0:
            offset = accent if (bow_idx % 2 == 0) else -accent
            result.append((note, dur, _clamp_vel(vel + offset)) + item[3:])
            bow_idx += 1
        else:
            bow_idx = 0
            result.append(item)
    return result

def crescendo(seq, v_start_pct, v_end_pct):
    """Scale velocities from v_start_pct% to v_end_pct% across the sequence."""
    n = len(seq)
    if n == 0: return seq
    result = []
    for i, item in enumerate(seq):
        note, dur, vel = item[0], item[1], item[2]
        t = i / max(n - 1, 1)
        scale = (v_start_pct + (v_end_pct - v_start_pct) * t) / 100.0
        result.append((note, dur, _clamp_vel(int(vel * scale))) + item[3:])
    return result

def grace_before(seq, target_idx, grace_pitch_offset=1):
    """Insert a short grace note before seq[target_idx] with a semitone offset."""
    grace_dur = SIXTEENTH // 2
    note, dur, vel = seq[target_idx][0], seq[target_idx][1], seq[target_idx][2]
    grace = (note + grace_pitch_offset, grace_dur, _clamp_vel(vel - 10), grace_dur)
    shortened = (note, dur - grace_dur, vel) + seq[target_idx][3:]
    return seq[:target_idx] + [grace, shortened] + seq[target_idx+1:]

def phrase_arc(seq, phrase_ticks, v_lo_pct=88, v_hi_pct=112, peak_pos=0.65):
    """Apply bell-curve phrase dynamics: velocity rises to peak_pos then resolves.
    Works on notes_trk-style sequences [(note, dur, vel, ...)].
    Skips rest notes (vel==0). phrase_ticks is the length of one phrase in ticks."""
    if not seq:
        return seq
    # build cumulative tick positions
    result = []
    t = 0
    for item in seq:
        note, dur, vel = item[0], item[1], item[2]
        if vel == 0:
            result.append(item)
            t += dur
            continue
        phrase_t = t % phrase_ticks
        pos = phrase_t / phrase_ticks  # 0..1 within phrase
        # bell curve: rise to peak_pos, then fall
        if pos <= peak_pos:
            scale_pct = v_lo_pct + (v_hi_pct - v_lo_pct) * (pos / peak_pos)
        else:
            scale_pct = v_hi_pct - (v_hi_pct - v_lo_pct) * ((pos - peak_pos) / (1.0 - peak_pos))
        new_vel = _clamp_vel(int(vel * scale_pct / 100))
        result.append((note, dur, new_vel) + item[3:])
        t += dur
    return result

def piece_arc(seq, total_ticks, v_start_pct=93, v_peak_pct=107, peak_pos=0.72):
    """Subtle piece-level crescendo: quiet opening → climax at 72% → gentle resolve.
    Applies to the whole sequence, complementing phrase_arc."""
    if not seq or total_ticks <= 0:
        return seq
    result = []
    t = 0
    for item in seq:
        note, dur, vel = item[0], item[1], item[2]
        if vel == 0:
            result.append(item)
            t += dur
            continue
        pos = min(1.0, t / total_ticks)
        if pos <= peak_pos:
            scale_pct = v_start_pct + (v_peak_pct - v_start_pct) * (pos / peak_pos)
        else:
            # Descend only halfway back — piece ends slightly elevated for resolution feel
            scale_pct = v_peak_pct - (v_peak_pct - v_start_pct) * 0.5 * ((pos - peak_pos) / (1.0 - peak_pos))
        result.append((note, dur, _clamp_vel(int(vel * scale_pct / 100))) + item[3:])
        t += dur
    return result

def midi(tracks):
    n = len(tracks)
    return b'MThd' + struct.pack('>IHHH', 6, 1, n, TPB) + b''.join(tracks)

# ── Common drum bars ──────────────────────────────────────────────────────────

def bar_march():
    return [(0,CRASH,82),(0,BD,90),(QTR,SD,78),(QTR,RIDE,52),
            (QTR*2,BD,80),(QTR*2,RIDE,52),(QTR*3,SD,75),(QTR*3,RIDE,50)]

def bar_march_inner():
    return [(0,BD,85),(0,RIDE,52),(QTR,SD,72),(QTR,RIDE,50),
            (QTR*2,BD,80),(QTR*2,RIDE,52),(QTR*3,SD,70),(QTR*3,RIDE,50)]

def bar_heavy():
    return [(0,CRASH,88),(0,BD,95),(EIGHTH,BD,72),(QTR,SD,88),
            (QTR,CHH,58),(QTR+EIGHTH,CHH,50),(QTR*2,BD,90),(QTR*2,CHH,58),
            (QTR*2+EIGHTH,BD,68),(QTR*3,SD,85),(QTR*3,CHH,58)]

def bar_rock():
    return [(0,BD,88),(0,CHH,52),(QTR,SD,80),(QTR,CHH,50),
            (QTR*2,BD,85),(QTR*2,CHH,52),(QTR*3,SD,78),(QTR*3,CHH,50)]

def bar_sparse():
    return [(0,BD,60),(QTR*2,SD,52)]

def bar_waltz():      # bar_ticks = QTR*3
    return [(0,BD,75),(QTR,CHH,48),(QTR*2,CHH,45)]

def bar_waltz_crash():
    return [(0,CRASH,70),(0,BD,80),(QTR,CHH,48),(QTR*2,CHH,45)]

def bar_jig():
    return [(0,BD,80),(EIGHTH,CHH,50),(QTR,CHH,48),
            (QTR+EIGHTH,CHH,50),(QTR*2,BD,75),(QTR*2+EIGHTH,CHH,50),
            (QTR*3,CHH,48),(QTR*3+EIGHTH,CHH,50)]

def bar_boss():
    return [(0,CRASH,92),(0,BD,98),(EIGHTH,BD,80),(QTR,SD,90),
            (QTR,CHH,62),(QTR+EIGHTH,BD,72),(QTR+EIGHTH,CHH,55),
            (QTR*2,BD,95),(QTR*2,CHH,62),(QTR*2+EIGHTH,BD,78),
            (QTR*3,SD,88),(QTR*3,CHH,62),(QTR*3+EIGHTH,CHH,55)]

def bar_celtic():
    return [(0,CRASH,72),(0,BD,82),(EIGHTH,CHH,48),
            (QTR,SD,68),(QTR,CHH,48),(QTR+EIGHTH,CHH,45),
            (QTR*2,BD,80),(QTR*2,CHH,50),(QTR*2+EIGHTH,CHH,45),
            (QTR*3,SD,72),(QTR*3,CHH,48),(QTR*3+EIGHTH,CHH,42)]

def bar_celtic_inner():
    return [(0,BD,80),(EIGHTH,CHH,48),(QTR,SD,65),(QTR,CHH,48),
            (QTR+EIGHTH,CHH,42),(QTR*2,BD,78),(QTR*2,CHH,50),
            (QTR*2+EIGHTH,CHH,42),(QTR*3,SD,68),(QTR*3,CHH,48)]

def bar_heartbeat():
    return [(0,BD,45),(EIGHTH,BD,32)]

def bar_heartbeat_intense():
    return [(0,BD,68),(EIGHTH,BD,50),(QTR*2,BD,62),(QTR*2+EIGHTH,BD,44)]

# ── Composition 0: Orchestral Piece ──────────────────────────────────────────

def comp_orchestral_piece():
    bpm = 80
    # C Major: I-V-vi-IV-I-V-IV-I (8 majestic bars)
    C2,G2,A2,F2,E2 = _note('C',2),_note('G',2),_note('A',2),_note('F',2),_note('E',2)
    C3,E3,G3,A3,B3,D3,F3 = _note('C',3),_note('E',3),_note('G',3),_note('A',3),_note('B',3),_note('D',3),_note('F',3)
    C4,D4,E4,F4,G4 = _note('C',4),_note('D',4),_note('E',4),_note('F',4),_note('G',4)
    C5,D5,E5,G5,A5 = _note('C',5),_note('D',5),_note('E',5),_note('G',5),_note('A',5)

    bass = [
        (C2, WHOLE, 82),                   # bar 1: I
        (G2, WHOLE, 78),                   # bar 2: V
        (A2, WHOLE, 76),                   # bar 3: vi
        (F2, WHOLE, 78),                   # bar 4: IV
        (C2, HALF, 88), (E2, HALF, 82),    # bar 5: I (walking)
        (G2, HALF, 85), (D3, HALF, 80),    # bar 6: V (walking)
        (F2, HALF, 85), (G2, HALF, 90),    # bar 7: IV→V
        (C2, WHOLE, 98),                   # bar 8: I fortissimo
    ]
    pad = [
        ([E3, G3, C4], WHOLE, 72),         # bar 1: I
        ([D3, G3, B3], WHOLE, 70),         # bar 2: V
        ([C3, E3, A3], WHOLE, 68),         # bar 3: vi (Am)
        ([C3, F3, A3], WHOLE, 70),         # bar 4: IV (F)
        ([E3, G3, C4], HALF, 80), ([E3, G3, C4], HALF, 76),  # bar 5
        ([D3, G3, B3], HALF, 82), ([D3, G3, B3], HALF, 78),  # bar 6
        ([C3, F3, A3], HALF, 80), ([D3, G3, B3], HALF, 86),  # bar 7
        ([E3, G3, C4], WHOLE, 94),         # bar 8
    ]
    melody = [
        # Phrase A (bars 1-4): lyrical, p-mf
        (G5, HALF, 82),  (E5, HALF, 80),                           # bar 1
        (D5, QTR, 78),   (C5, QTR, 75), (D5, QTR, 78), (G5, QTR, 80),  # bar 2
        (A5, QTR, 78),   (G5, QTR, 75), (E5, QTR, 72), (D5, QTR, 70),  # bar 3
        (C5, HALF, 75),  (E5, HALF, 80),                           # bar 4
        # Phrase B (bars 5-8): climactic, mf-ff
        (E5, QTR, 90),   (G5, QTR, 93), (A5, HALF, 96),           # bar 5
        (G5, HALF, 90),  (D5, HALF, 85),                           # bar 6
        (C5, QTR, 88),   (E5, QTR, 91), (G5, QTR, 94), (A5, QTR, 97),  # bar 7
        (C5, WHOLE, 102),                                           # bar 8: grand cadence
    ]

    def bar_orch_open():
        return [(0, CRASH, 72), (0, BD, 82), (QTR * 2, BD, 65)]
    def bar_orch_soft():
        return [(0, BD, 68), (QTR * 2, BD, 62), (QTR * 3, SD, 55)]
    def bar_orch_swell():
        return [(0, CRASH, 80), (0, BD, 90), (QTR, SD, 68), (QTR * 2, BD, 86), (QTR * 3, SD, 74)]
    def bar_orch_grand():
        return [(0, CRASH, 95), (0, BD, 102), (QTR, SD, 82), (QTR * 2, BD, 98),
                (QTR * 2, CRASH, 85), (QTR * 3, SD, 88), (QTR * 3, BD, 90)]

    drums = [bar_orch_open(), bar_orch_soft(), bar_orch_soft(), bar_orch_soft(),
             bar_orch_open(), bar_orch_swell(), bar_orch_swell(), bar_orch_grand()]
    return bpm, bass, pad, melody, drums


# ── Composition 1: Heroic March ───────────────────────────────────────────────

def comp_heroic_march():
    bpm = 120
    # C major: C-G-Am-F (x2)
    C2,G2,A2,E2,F2,C3,D3 = _note('C',2),_note('G',2),_note('A',2),_note('E',2),_note('F',2),_note('C',3),_note('D',3)
    E3,G3,B3,C4,D4,E4,F3,A3 = _note('E',3),_note('G',3),_note('B',3),_note('C',4),_note('D',4),_note('E',4),_note('F',3),_note('A',3)
    C5,E5,G5,A5,F4,G4,A4,B4,D5 = _note('C',5),_note('E',5),_note('G',5),_note('A',5),_note('F',4),_note('G',4),_note('A',4),_note('B',4),_note('D',5)

    bass = [
        # A section (bars 1-8)
        (C2,HALF,92),(G2,HALF,88),  (G2,HALF,90),(D3,HALF,85),
        (A2,HALF,88),(E2,HALF,82),  (F2,HALF,88),(C3,HALF,85),
        (C2,HALF,92),(G2,HALF,88),  (G2,HALF,90),(D3,HALF,85),
        (F2,QTR,85),(F2,QTR,82),(G2,QTR,90),(G2,QTR,88),
        (C2,HALF,92),(C2,HALF,88),
        # B section development (bars 9-16)
        (C2,HALF,95),(G2,HALF,92),  (A2,HALF,90),(E2,HALF,88),
        (F2,HALF,92),(C3,HALF,88),  (G2,HALF,95),(D3,HALF,90),
        (F2,HALF,88),(F2,HALF,85),  (G2,HALF,92),(G2,HALF,88),
        (F2,QTR,88),(G2,QTR,92),(A2,QTR,90),(G2,QTR,88),
        (C2,WHOLE,105),
    ]
    pad = [
        # A section
        ([E3,G3,C4],HALF,80),([E3,G3,C4],HALF,75),  ([D3,G3,B3],HALF,78),([D3,G3,B3],HALF,72),
        ([A3,C4,E4],HALF,78),([A3,C4,E4],HALF,72),  ([F3,A3,C4],HALF,76),([F3,A3,C4],HALF,70),
        ([E3,G3,C4],HALF,82),([E3,G3,C4],HALF,78),  ([D3,G3,B3],HALF,80),([D3,G3,B3],HALF,75),
        ([F3,A3,C4],QTR,76),([F3,A3,C4],QTR,72),([G3,B3,D4],QTR,82),([G3,B3,D4],QTR,78),
        ([E3,G3,C4],HALF,82),([E3,G3,C4],HALF,78),
        # B section (fuller voicings)
        ([E3,G3,C4],HALF,85),([E3,G3,C4],HALF,82),  ([A3,C4,E4],HALF,82),([A3,C4,E4],HALF,78),
        ([F3,A3,C4],HALF,82),([F3,A3,C4],HALF,78),  ([D3,G3,B3],HALF,85),([D3,G3,B3],HALF,80),
        ([F3,A3,C4],HALF,80),([F3,A3,C4],HALF,75),  ([G3,B3,D4],HALF,85),([G3,B3,D4],HALF,80),
        ([F3,A3,C4],QTR,82),([G3,B3,D4],QTR,85),([E3,G3,C4],QTR,88),([G3,B3,D4],QTR,85),
        ([E3,G3,C4],WHOLE,95),
    ]
    melody = [
        # A section (bars 1-8)
        (C5,QTR,88),(E5,QTR,90),(G5,QTR,92),(E5,QTR,85),
        (G5,DOTTED_QTR,90),(A5,EIGHTH,85),(G5,HALF,88),
        (A5,QTR,82),(G5,QTR,78),(E5,QTR,75),(A4,QTR,72),
        (F4,QTR,78),(A4,QTR,80),(C5,QTR,82),(E5,QTR,85),
        (C5,DOTTED_QTR,90),(E5,EIGHTH,85),(G5,QTR,88),(A5,QTR,85),
        (G5,QTR,88),(A5,QTR,90),(B4,QTR,82),(D5,QTR,85),
        (F4,QTR,80),(A4,QTR,82),(C5,QTR,85),(D5,QTR,88),
        (C5,HALF,92),(G4,QTR,78),(C4,QTR,70),
        # B section — louder, higher register (bars 9-16)
        (E5,QTR,92),(G5,QTR,95),(A5,QTR,98),(G5,QTR,90),
        (G5,DOTTED_QTR,95),(A5,EIGHTH,90),(G5,HALF,92),
        (E5,QTR,88),(D5,QTR,85),(C5,QTR,82),(A4,QTR,78),
        (A4,QTR,82),(C5,QTR,85),(E5,QTR,88),(G5,QTR,90),
        (A5,DOTTED_QTR,95),(G5,EIGHTH,90),(E5,QTR,92),(D5,QTR,88),
        (C5,QTR,90),(E5,QTR,92),(G5,QTR,95),(A5,QTR,98),
        (G5,QTR,90),(A5,QTR,92),(G5,QTR,88),(E5,QTR,85),
        (C5,WHOLE,100),
    ]
    drums = [bar_march(),bar_march_inner(),bar_march_inner(),bar_march_inner(),
             bar_march(),bar_march_inner(),bar_march_inner(),bar_march(),
             bar_march(),bar_march_inner(),bar_march_inner(),bar_march_inner(),
             bar_march(),bar_march_inner(),bar_march_inner(),bar_march()]
    return bpm, bass, pad, melody, drums

# ── Composition 2: Forest Wanderer ────────────────────────────────────────────

def comp_forest_wanderer():
    bpm = 68
    # F major: F-Dm-Bb-C (x4 = 16 bars)
    F1,C2,D2,Bb1 = _note('F',1),_note('C',2),_note('D',2),_note('Bb',1)
    F3,A3,C4,D3,F2,A2 = _note('F',3),_note('A',3),_note('C',4),_note('D',3),_note('F',2),_note('A',2)
    Bb2,Bb3,G3,E3 = _note('Bb',2),_note('Bb',3),_note('G',3),_note('E',3)
    C3,E4,G4,A4,F4,D4,Bb4,G2 = _note('C',3),_note('E',4),_note('G',4),_note('A',4),_note('F',4),_note('D',4),_note('Bb',4),_note('G',2)
    C5,D5,E5,F5 = _note('C',5),_note('D',5),_note('E',5),_note('F',5)

    prog_bass = [F1,D2,Bb1,C2] * 4
    bass = [(n,WHOLE,70) for n in prog_bass]

    def fmaj_arp():  return [([F3,A3,C4],DOTTED_QTR,62),([F3,A3,C4],QTR,58),([F3,A3,C4],DOTTED_QTR,55)]
    def dm_arp():    return [([D3,F3,A3],DOTTED_QTR,60),([D3,F3,A3],QTR,55),([D3,F3,A3],DOTTED_QTR,52)]
    def bb_arp():    return [([Bb2,D3,F3],DOTTED_QTR,60),([Bb2,D3,F3],QTR,55),([Bb2,D3,F3],DOTTED_QTR,52)]
    def cmaj_arp():  return [([C3,E3,G3],DOTTED_QTR,62),([C3,E3,G3],QTR,58),([C3,E3,G3],DOTTED_QTR,55)]

    pad = fmaj_arp() + dm_arp() + bb_arp() + cmaj_arp() + \
          fmaj_arp() + dm_arp() + bb_arp() + cmaj_arp() + \
          fmaj_arp() + dm_arp() + bb_arp() + cmaj_arp() + \
          fmaj_arp() + dm_arp() + bb_arp() + cmaj_arp()

    melody = [
        # Bar 1 (F): lyrical rise
        (F4,HALF,70),(A4,QTR,72),(C5,QTR,75),
        # Bar 2 (Dm): gentle descent
        (A4,DOTTED_QTR,70),(G4,EIGHTH,65),(F4,HALF,68),
        # Bar 3 (Bb): stepwise
        (Bb4,QTR,68),(A4,QTR,65),(G4,QTR,62),(F4,QTR,60),
        # Bar 4 (C): resolution setup
        (E4,HALF,65),(G4,QTR,68),(A4,QTR,70),
        # Bar 5 (F): variation
        (F4,QTR,70),(A4,HALF,72),(A4,QTR,68),
        # Bar 6 (Dm): reach high
        (A4,QTR,72),(C5,HALF,75),(A4,QTR,70),
        # Bar 7 (Bb)
        (G4,QTR,68),(F4,QTR,65),(E4,QTR,62),(D4,QTR,60),
        # Bar 8 (C): build
        (E4,QTR,65),(G4,QTR,68),(A4,QTR,70),(G4,QTR,68),
        # Bar 9 (F): final phrase
        (F4,DOTTED_HALF,72),(A4,QTR,70),
        # Bar 10 (Dm)
        (D4,HALF,68),(F4,HALF,65),
        # Bar 11 (Bb)
        (Bb4,DOTTED_QTR,70),(A4,EIGHTH,65),(G4,HALF,62),
        # Bar 12 (C): long close, ready for repeat
        (F4,WHOLE,70),
        # D section — bars 13-16: upward bloom then resolving farewell
        # Bar 13 (F): ascending to high register
        (C5,QTR,74),(D5,QTR,76),(E5,QTR,78),(F5,QTR,80),
        # Bar 14 (Dm): expressive peak, gentle fall
        (F5,DOTTED_QTR,76),(E5,EIGHTH,70),(D5,HALF,72),
        # Bar 15 (Bb): stepwise warmth
        (Bb4,DOTTED_QTR,72),(A4,EIGHTH,68),(G4,QTR,65),(F4,QTR,62),
        # Bar 16 (F): final long note
        (F4,WHOLE,72),
    ]
    # Very sparse drums: just light taps
    sparse = [(0,BD,45),(QTR*2,SD,38)]
    drums = [sparse] * 16
    return bpm, bass, pad, melody, drums

# ── Composition 3: Battle Cry ─────────────────────────────────────────────────

def comp_battle_cry():
    bpm = 145
    # D minor: Dm-C-Bb-A (x2)
    D1,A1,Bb1,C2 = _note('D',1),_note('A',1),_note('Bb',1),_note('C',2)
    D2,A2,C3,Bb2 = _note('D',2),_note('A',2),_note('C',3),_note('Bb',2)
    D3,F3,A3,C4,E4,G4 = _note('D',3),_note('F',3),_note('A',3),_note('C',4),_note('E',4),_note('G',4)
    D4,F4,A4,C5,E5,F5,G5 = _note('D',4),_note('F',4),_note('A',4),_note('C',5),_note('E',5),_note('F',5),_note('G',5)
    D5,A5,Bb5 = _note('D',5),_note('A',5),_note('Bb',5)
    Bb3,E3,G3,Bb4,G2,F2 = _note('Bb',3),_note('E',3),_note('G',3),_note('Bb',4),_note('G',2),_note('F',2)
    Cs4,Cs5 = _note('C#',4),_note('C#',5)

    bass = [
        # A section (bars 1-8)
        (D1,EIGHTH,90),(D1,EIGHTH,82),(A1,EIGHTH,85),(D1,EIGHTH,88),(D1,EIGHTH,80),(A1,EIGHTH,82),(D1,EIGHTH,85),(A1,EIGHTH,78),
        (C2,HALF,85),(C2,HALF,80),
        (Bb1,EIGHTH,88),(Bb1,EIGHTH,80),(F2,EIGHTH,82),(Bb1,EIGHTH,85),(Bb1,EIGHTH,78),(F2,EIGHTH,80),(Bb1,EIGHTH,82),(F2,EIGHTH,75),
        (A1,HALF,90),(A1,HALF,85),
        (D1,EIGHTH,90),(D1,EIGHTH,82),(A1,EIGHTH,85),(D1,EIGHTH,88),(D1,EIGHTH,80),(A1,EIGHTH,82),(D1,EIGHTH,85),(A1,EIGHTH,78),
        (C2,HALF,85),(C2,HALF,80),
        (Bb1,EIGHTH,88),(Bb1,EIGHTH,80),(F2,EIGHTH,82),(Bb1,EIGHTH,85),(Bb1,EIGHTH,78),(F2,EIGHTH,80),(Bb1,EIGHTH,82),(F2,EIGHTH,75),
        (A1,HALF,90),(A1,HALF,85),
        # B section — relentless assault (bars 9-16)
        (D1,EIGHTH,95),(A1,EIGHTH,90),(D2,EIGHTH,92),(A1,EIGHTH,88),(D1,EIGHTH,90),(A1,EIGHTH,88),(D2,EIGHTH,92),(A1,EIGHTH,90),
        (C2,EIGHTH,90),(G2,EIGHTH,85),(C2,EIGHTH,88),(G2,EIGHTH,82),(C2,EIGHTH,85),(G2,EIGHTH,80),(C2,EIGHTH,82),(G2,EIGHTH,78),
        (Bb1,EIGHTH,92),(F2,EIGHTH,88),(Bb1,EIGHTH,90),(F2,EIGHTH,85),(Bb1,EIGHTH,88),(F2,EIGHTH,85),(Bb1,EIGHTH,90),(F2,EIGHTH,88),
        (A1,HALF,95),(A1,HALF,92),
        (D1,EIGHTH,95),(A1,EIGHTH,92),(D2,EIGHTH,95),(A1,EIGHTH,90),(D1,EIGHTH,92),(A1,EIGHTH,90),(D2,EIGHTH,95),(A1,EIGHTH,92),
        (C2,HALF,92),(Bb1,HALF,90),
        (F2,EIGHTH,88),(F2,EIGHTH,85),(G2,EIGHTH,90),(G2,EIGHTH,88),(A2,EIGHTH,92),(A2,EIGHTH,90),(A2,EIGHTH,95),(A2,EIGHTH,92),
        (D2,WHOLE,105),
    ]
    pad = [
        # A section
        ([D3,F3,A3],HALF,75),([D3,F3,A3],HALF,70),
        ([C3,E3,G3],HALF,72),([C3,E3,G3],HALF,68),
        ([Bb2,D3,F3],HALF,72),([Bb2,D3,F3],HALF,68),
        ([A2,Cs4,E4],HALF,78),([A2,Cs4,E4],HALF,72),
        ([D3,F3,A3],HALF,75),([D3,F3,A3],HALF,70),
        ([C3,E3,G3],HALF,72),([C3,E3,G3],HALF,68),
        ([Bb2,D3,F3],HALF,72),([Bb2,D3,F3],HALF,68),
        ([A2,Cs4,E4],HALF,78),([A2,Cs4,E4],HALF,72),
        # B section (heavier)
        ([D3,F3,A3],QTR,80),([D3,F3,A3],QTR,78),([D3,F3,A3],QTR,82),([D3,F3,A3],QTR,80),
        ([C3,E3,G3],QTR,78),([C3,E3,G3],QTR,75),([C3,E3,G3],QTR,80),([C3,E3,G3],QTR,78),
        ([Bb2,D3,F3],QTR,78),([Bb2,D3,F3],QTR,75),([Bb2,D3,F3],QTR,80),([Bb2,D3,F3],QTR,78),
        ([A2,Cs4,E4],HALF,85),([A2,Cs4,E4],HALF,82),
        ([D3,F3,A3],QTR,82),([D3,F3,A3],QTR,80),([C3,E3,G3],QTR,80),([Bb2,D3,F3],QTR,78),
        ([C3,E3,G3],HALF,80),([Bb2,D3,F3],HALF,78),
        ([A2,Cs4,E4],QTR,88),([A2,Cs4,E4],QTR,85),([A2,Cs4,E4],QTR,90),([A2,Cs4,E4],QTR,88),
        ([D3,F3,A3],WHOLE,92),
    ]
    melody = [
        # A section (bars 1-8)
        (D5,EIGHTH,88),(F5,EIGHTH,85),(A4,EIGHTH,82),(F4,EIGHTH,80),(D4,EIGHTH,85),(F4,EIGHTH,82),(A4,EIGHTH,85),(D5,EIGHTH,88),
        (C5,EIGHTH,85),(E5,EIGHTH,82),(G5,EIGHTH,88),(E5,EIGHTH,82),(C5,EIGHTH,80),(E5,EIGHTH,78),(G4,EIGHTH,75),(E4,EIGHTH,72),
        (Bb4,EIGHTH,85),(D5,EIGHTH,82),(F5,EIGHTH,85),(D5,EIGHTH,80),(Bb4,EIGHTH,78),(D4,EIGHTH,75),(F4,EIGHTH,72),(D4,EIGHTH,70),
        (A4,EIGHTH,90),(Cs5,EIGHTH,88),(E5,EIGHTH,92),(Cs5,EIGHTH,88),(A4,HALF,85),  # bar 4: 4*EIGHTH+HALF=1920
        (D5,QTR,90),(F5,QTR,88),(A4,QTR,85),(F4,QTR,82),
        (G5,DOTTED_QTR,88),(F5,EIGHTH,82),(E5,HALF,80),
        (D5,QTR,85),(C5,QTR,82),(Bb4,QTR,78),(A4,QTR,75),
        (D5,HALF,92),(A4,HALF,85),
        # B section — higher register, more intensity (bars 9-16)
        (F5,EIGHTH,92),(A5,EIGHTH,90),(D5,EIGHTH,88),(A4,EIGHTH,85),(F4,EIGHTH,88),(A4,EIGHTH,85),(D5,EIGHTH,88),(F5,EIGHTH,92),
        (E5,EIGHTH,88),(G5,EIGHTH,85),(C5,EIGHTH,82),(G4,EIGHTH,80),(E4,EIGHTH,82),(G4,EIGHTH,80),(C5,EIGHTH,82),(E5,EIGHTH,88),
        (D5,EIGHTH,90),(F5,EIGHTH,88),(Bb4,EIGHTH,85),(F4,EIGHTH,82),(D4,EIGHTH,82),(F4,EIGHTH,80),(Bb4,EIGHTH,85),(D5,EIGHTH,90),
        (A4,EIGHTH,95),(Cs5,EIGHTH,92),(E5,EIGHTH,98),(Cs5,EIGHTH,95),(A5,HALF,92),  # bar 12: 4*EIGHTH+HALF=1920
        (D5,QTR,92),(A5,QTR,95),(F5,QTR,90),(D5,QTR,88),
        (C5,HALF,90),(Bb4,HALF,88),
        (A4,QTR,92),(Cs5,QTR,95),(E5,QTR,98),(A5,QTR,100),
        (D5,WHOLE,102),
    ]
    # C section — final climax (bars 17-20)
    bass += [
        (D1,EIGHTH,98),(A1,EIGHTH,95),(D2,EIGHTH,98),(A1,EIGHTH,95),(D1,EIGHTH,98),(A1,EIGHTH,95),(D2,EIGHTH,100),(A1,EIGHTH,98),
        (C2,EIGHTH,95),(G2,EIGHTH,92),(C2,EIGHTH,95),(G2,EIGHTH,92),(C2,EIGHTH,95),(G2,EIGHTH,92),(C2,EIGHTH,95),(G2,EIGHTH,92),
        (Bb1,EIGHTH,98),(F2,EIGHTH,95),(Bb1,EIGHTH,98),(F2,EIGHTH,95),(A1,EIGHTH,100),(A1,EIGHTH,98),(A1,EIGHTH,100),(A1,EIGHTH,98),
        (D2,WHOLE,110),
    ]
    pad += [
        ([D3,F3,A3],QTR,90),([D3,F3,A3],QTR,88),([D3,F3,A3],QTR,92),([D3,F3,A3],QTR,90),
        ([C3,E3,G3],QTR,88),([C3,E3,G3],QTR,85),([C3,E3,G3],QTR,90),([C3,E3,G3],QTR,88),
        ([Bb2,D3,F3],QTR,90),([A2,Cs4,E4],QTR,92),([A2,Cs4,E4],QTR,95),([A2,Cs4,E4],QTR,98),
        ([D3,F3,A3],WHOLE,105),
    ]
    melody += [
        (D5,EIGHTH,98),(F5,EIGHTH,95),(A5,EIGHTH,100),(F5,EIGHTH,95),(D5,EIGHTH,98),(A5,EIGHTH,100),(F5,EIGHTH,95),(D5,EIGHTH,98),
        (E5,EIGHTH,95),(G5,EIGHTH,92),(C5,EIGHTH,88),(G4,EIGHTH,85),(E4,EIGHTH,82),(G4,EIGHTH,85),(C5,EIGHTH,88),(E5,EIGHTH,92),
        (A4,QTR,98),(Cs5,QTR,102),(E5,QTR,105),(A5,QTR,108),
        (D5,WHOLE,110),
    ]
    drums = [bar_heavy(),bar_rock(),bar_rock(),bar_heavy(),
             bar_heavy(),bar_rock(),bar_rock(),bar_heavy(),
             bar_heavy(),bar_rock(),bar_rock(),bar_heavy(),
             bar_heavy(),bar_rock(),bar_rock(),bar_heavy(),
             bar_boss(),bar_heavy(),bar_rock(),bar_boss()]
    return bpm, bass, pad, melody, drums

# ── Composition 4: Tavern Jig ─────────────────────────────────────────────────

def comp_tavern_jig():
    bpm = 168
    # G major: G-D-Em-C (x3)
    G1,D2,E2,C2 = _note('G',1),_note('D',2),_note('E',2),_note('C',2)
    G2,D3,E3,C3 = _note('G',2),_note('D',3),_note('E',3),_note('C',3)
    G3,B3,D4,A3,F3 = _note('G',3),_note('B',3),_note('D',4),_note('A',3),_note('F',3)
    G4,B4,D5,E5,C5,A4,F4 = _note('G',4),_note('B',4),_note('D',5),_note('E',5),_note('C',5),_note('A',4),_note('F',4)
    G5,A5,B5,F5 = _note('G',5),_note('A',5),_note('B',5),_note('F',5)
    C4,E4,A2 = _note('C',4),_note('E',4),_note('A',2)

    bass = [
        (G1,QTR,85),(D2,EIGHTH,72),(G2,EIGHTH,70),(D2,QTR,72),(G1,QTR,80),  # G bar
        (D2,QTR,85),(A2,EIGHTH,70),(D2,EIGHTH,68),(A2,QTR,70),(D2,QTR,80),  # D bar
        (E2,QTR,82),(B3,EIGHTH,65),(E2,EIGHTH,62),(B3,QTR,65),(E2,QTR,78),  # Em bar
        (C2,QTR,82),(G2,EIGHTH,68),(C2,EIGHTH,65),(G2,QTR,68),(C2,QTR,78),  # C bar
    ] * 4

    pad = [
        ([G3,B3,D4],QTR,70),([G3,B3,D4],EIGHTH,60),([G3,B3,D4],EIGHTH,58),([G3,B3,D4],HALF,65),
        ([D3,A3,D4],QTR,68),([D3,A3,D4],EIGHTH,58),([D3,A3,D4],EIGHTH,55),([D3,A3,D4],HALF,62),
        ([E3,G3,B3],QTR,68),([E3,G3,B3],EIGHTH,58),([E3,G3,B3],EIGHTH,55),([E3,G3,B3],HALF,62),
        ([C3,E3,G3],QTR,68),([C3,E3,G3],EIGHTH,58),([C3,E3,G3],EIGHTH,55),([C3,E3,G3],HALF,62),
    ] * 4

    def jig_phrase(root, s, t, u, v):
        return [
            (root,EIGHTH,88),(s,EIGHTH,82),(t,EIGHTH,85),(s,EIGHTH,78),(t,EIGHTH,82),(s,EIGHTH,78),(t,EIGHTH,80),(u,EIGHTH,75),
        ]

    melody = (
        jig_phrase(G4,A4,B4,D5,G4) +
        [B4,D5,G4,D5,B4,A4,G4,D4] and  # hack: replace
        [(G4,EIGHTH,88),(B4,EIGHTH,82),(D5,EIGHTH,85),(B4,EIGHTH,78),(D5,EIGHTH,82),(B4,EIGHTH,78),(A4,EIGHTH,80),(G4,EIGHTH,75),
         (D5,EIGHTH,85),(A4,EIGHTH,78),(B4,EIGHTH,82),(A4,EIGHTH,75),(G4,EIGHTH,78),(A4,EIGHTH,75),(B4,EIGHTH,72),(A4,EIGHTH,70),
         (E5,EIGHTH,88),(D5,EIGHTH,82),(B4,EIGHTH,85),(G4,EIGHTH,80),(A4,EIGHTH,82),(B4,EIGHTH,78),(D5,EIGHTH,80),(E5,EIGHTH,78),
         (C5,EIGHTH,85),(E5,EIGHTH,80),(G5,EIGHTH,85),(E5,EIGHTH,78),(C5,EIGHTH,80),(G4,EIGHTH,75),(E4,EIGHTH,70),(C4,EIGHTH,65),
         # bars 5-8
         (G4,EIGHTH,85),(A4,EIGHTH,80),(B4,EIGHTH,85),(D5,EIGHTH,82),(G5,EIGHTH,88),(D5,EIGHTH,82),(B4,EIGHTH,80),(A4,EIGHTH,78),
         (D5,EIGHTH,88),(F4,EIGHTH,80),(A4,EIGHTH,82),(D5,EIGHTH,85),(F4,EIGHTH,78),(A4,EIGHTH,75),(D4,EIGHTH,72),(A4,EIGHTH,70),
         (E5,QTR,85),(B4,QTR,78),(A4,QTR,75),(G4,QTR,72),
         (C5,QTR,82),(G4,QTR,78),(E4,QTR,72),(C4,QTR,68),
         # bars 9-12
         (G4,EIGHTH,88),(B4,EIGHTH,82),(D5,EIGHTH,85),(B4,EIGHTH,80),(D5,EIGHTH,82),(G5,EIGHTH,85),(D5,EIGHTH,80),(B4,EIGHTH,78),
         (D5,DOTTED_QTR,85),(A4,EIGHTH,78),(B4,HALF,82),
         (E5,DOTTED_QTR,88),(D5,EIGHTH,82),(B4,HALF,80),
         (C5,HALF,82),(G4,QTR,75),(C4,QTR,68),
         # bars 13-16: rousing finale
         # bar 13 (G): soaring 8th-note run
         (G5,EIGHTH,92),(F5,EIGHTH,88),(D5,EIGHTH,90),(B4,EIGHTH,88),(G4,EIGHTH,85),(B4,EIGHTH,82),(D5,EIGHTH,85),(G5,EIGHTH,90),
         # bar 14 (D): spirited descent
         (D5,EIGHTH,88),(B4,EIGHTH,84),(A4,EIGHTH,80),(G4,EIGHTH,78),(A4,EIGHTH,75),(B4,EIGHTH,72),(A4,EIGHTH,70),(G4,EIGHTH,68),
         # bar 15 (Em): rhythmic drive up
         (G4,EIGHTH,82),(A4,EIGHTH,85),(B4,EIGHTH,88),(D5,EIGHTH,90),(E5,EIGHTH,92),(D5,EIGHTH,90),(B4,EIGHTH,88),(G4,EIGHTH,84),
         # bar 16 (C→G): triumphant close
         (G4,QTR,92),(D5,QTR,90),(B4,QTR,88),(G4,QTR,85),]
    )

    drums = [bar_jig()] * 16
    return bpm, bass, pad, melody, drums

# ── Composition 5: Sad Elegy ──────────────────────────────────────────────────

def comp_sad_elegy():
    bpm = 52
    # A minor: Am-F-G-E (x4 = 16 bars)
    A1,E1,F1,G1 = _note('A',1),_note('E',1),_note('F',1),_note('G',1)
    A2,E2,F2,G2 = _note('A',2),_note('E',2),_note('F',2),_note('G',2)
    C3,E3,F3,G3,B2,D3 = _note('C',3),_note('E',3),_note('F',3),_note('G',3),_note('B',2),_note('D',3)
    Gs3,Cs4 = _note('G#',3),_note('C#',4)
    A4,G4,F4,E4,D4,B4 = _note('A',4),_note('G',4),_note('F',4),_note('E',4),_note('D',4),_note('B',4)
    C5,Gs4,D5 = _note('C',5),_note('G#',4),_note('D',5)

    bass = [(A1,WHOLE,62),(F1,WHOLE,58),(G1,WHOLE,60),(E1,WHOLE,65)] * 4

    # HALF chords — more harmonic breath, gentle crescendo over 4 phrases
    pad = []
    for rep, v in enumerate([50, 52, 56, 58]):
        pad += [
            ([A2,C3,E3],HALF,v),([A2,C3,E3],HALF,v-3),
            ([F2,A2,C3],HALF,v),([F2,A2,C3],HALF,v-3),
            ([G2,B2,D3],HALF,v),([G2,B2,D3],HALF,v-3),
            ([E2,Gs3,B2],HALF,v+4),([E2,Gs3,B2],HALF,v),
        ]

    melody = [
        # Phrase 1 — quiet opening (bars 1-4)
        (A4,DOTTED_HALF,70),(G4,QTR,62),
        (F4,HALF,65),(E4,HALF,60),
        (G4,QTR,62),(A4,HALF,68),(B4,QTR,65),
        (Cs4,HALF,65),(B4,DOTTED_QTR,62),(A4,EIGHTH,58),
        # Phrase 2 — growing (bars 5-8)
        (A4,WHOLE,72),
        (F4,DOTTED_QTR,65),(G4,EIGHTH,62),(A4,HALF,68),
        (D4,QTR,62),(E4,QTR,65),(G4,QTR,68),(B4,QTR,72),
        (A4,HALF,70),(Gs4,HALF,65),
        # Phrase 3 — climax (bars 9-12)
        (C5,DOTTED_HALF,75),(B4,QTR,68),
        (A4,HALF,72),(G4,HALF,65),
        (F4,QTR,68),(G4,QTR,70),(A4,DOTTED_QTR,75),(B4,EIGHTH,72),
        (C5,DOTTED_QTR,78),(B4,EIGHTH,72),(A4,QTR,70),(Gs4,QTR,65),
        # Phrase 4 — quiet resignation (bars 13-16)
        (A4,WHOLE,65),
        (F4,DOTTED_QTR,60),(G4,EIGHTH,58),(A4,HALF,62),
        (G4,QTR,58),(F4,QTR,55),(E4,DOTTED_QTR,60),(D4,EIGHTH,55),
        (A4,WHOLE,58),
    ]
    # No drums — mournful silence
    drums_bars = [[] for _ in range(16)]
    return bpm, bass, pad, melody, drums_bars

# ── Composition 6: Dungeon Depths ─────────────────────────────────────────────

def comp_dungeon_depths():
    bpm = 76
    # B minor: Bm-G-Em-F# (x4)
    B1,G1,E1,Fs1 = _note('B',1),_note('G',1),_note('E',1),_note('F#',1)
    B2,G2,E2,Fs2 = _note('B',2),_note('G',2),_note('E',2),_note('F#',2)
    B3,D3,F3,G3,A3 = _note('B',3),_note('D',3),_note('F',3),_note('G',3),_note('A',3)
    Fs3,As3,Ds3,E3,C3 = _note('F#',3),_note('A#',3),_note('D#',3),_note('E',3),_note('C',3)
    D4,F4,B4,G4,A4,E4 = _note('D',4),_note('F',4),_note('B',4),_note('G',4),_note('A',4),_note('E',4)
    Fs4,As4,Ds4,C4 = _note('F#',4),_note('A#',4),_note('D#',4),_note('C',4)
    D5,E5 = _note('D',5),_note('E',5)

    # Ostinato bass: B1 on beats 1+3, G1/E1/F#1 on 2+4
    def bass_bar(root, sub):
        return [(root,HALF,75),(sub,HALF,68)]

    bass = (
        [*bass_bar(B1,B1),*bass_bar(G1,G1),*bass_bar(E1,E1),*bass_bar(Fs1,Fs1)] * 4
    )

    # Slow sparse chords
    pad = [
        ([B2,D3,Fs3],WHOLE,52),([G2,B3,D4],WHOLE,48),
        ([E2,G2,B3],WHOLE,50),([Fs2,As3,C4],WHOLE,55),
    ] * 4

    # Eerie sparse melody with rests encoded as note 0 (silence) — use very low vel
    rest = (0, QTR, 0)  # we skip 0-vel notes actually; encode silence as gaps
    melody = [
        # Bar 1: single high B after a long rest
        (B4,HALF,55),(B4,DOTTED_QTR,48),(A4,EIGHTH,42),
        # Bar 2: descend slowly
        (G4,DOTTED_HALF,50),(Fs4,QTR,45),
        # Bar 3: eerie chromatic
        (E4,QTR,50),(Ds4,QTR,48),(E4,HALF,52),
        # Bar 4: resolve tension
        (Ds4,HALF,45),(Fs4,HALF,58),
        # Bar 5: high lonely note
        (D5,HALF,52),(C4+12,HALF,45),  # B4
        # Bar 6
        (B3+12,DOTTED_HALF,50),(A4,QTR,42),
        # Bar 7
        (G4,QTR,48),(Fs4,QTR,45),(E4,QTR,50),(D4,QTR,52),
        # Bar 8
        (Fs4,WHOLE,60),
        # Bars 9-16: more sparse
        (B4,HALF,55),(D5,HALF,48),
        (G4,DOTTED_HALF,50),(Fs4,QTR,45),
        (E5,HALF,52),(E4,HALF,45),
        (Fs4,WHOLE,58),
        (D5,QTR,50),(C4+12,QTR,45),(B4,HALF,52),
        (G4,DOTTED_HALF,50),(Fs4,QTR,45),
        (E4,QTR,52),(Ds4,QTR,48),(E4,QTR,50),(Fs4,QTR,55),
        (B3,WHOLE,62),
    ]
    # Minimal drums: just occasional BD pulse
    def dungeon_bar():
        return [(0,BD,42),(QTR*2,BD,38)]
    drums = [dungeon_bar()] * 16
    return bpm, bass, pad, melody, drums

# ── Composition 7: Victory Fanfare ────────────────────────────────────────────

def comp_victory_fanfare():
    bpm = 138
    # G major: G-C-D-G (x2)
    G1,C2,D2 = _note('G',1),_note('C',2),_note('D',2)
    G2,D3,C3,G3 = _note('G',2),_note('D',3),_note('C',3),_note('G',3)
    B3,D4,E3,A3 = _note('B',3),_note('D',4),_note('E',3),_note('A',3)
    G4,B4,D5,E5,G5,A5,C5 = _note('G',4),_note('B',4),_note('D',5),_note('E',5),_note('G',5),_note('A',5),_note('C',5)
    E4,F4,A4,C4 = _note('E',4),_note('F',4),_note('A',4),_note('C',4)

    A2,E3,B2 = _note('A',2),_note('E',3),_note('B',2)

    bass = [
        # A section (bars 1-8)
        (G1,HALF,95),(D2,HALF,90), (C2,HALF,92),(G2,HALF,88),
        (D2,HALF,95),(A2,HALF,85), (G1,WHOLE,100),
        (G1,HALF,95),(D2,HALF,90), (C2,HALF,92),(G2,HALF,88),
        (D2,QTR,95),(D2,QTR,92),(G2,QTR,98),(G2,QTR,95), (G1,WHOLE,105),
        # B section — triumphant coda (bars 9-16)
        (G1,HALF,100),(G2,HALF,95), (D2,HALF,98),(D2,HALF,92),
        (C2,HALF,95),(E3,HALF,90), (G1,WHOLE,105),
        (G1,HALF,100),(D2,HALF,95), (C2,HALF,98),(G2,HALF,95),
        (D2,QTR,100),(G2,QTR,98),(D2,QTR,105),(G2,QTR,102), (G1,WHOLE,110),
    ]
    pad = [
        # A section
        ([G3,B3,D4],HALF,85),([G3,B3,D4],HALF,80), ([C3,E3,G3],HALF,82),([C3,E3,G3],HALF,78),
        ([D3,A3,D4],HALF,85),([D3,A3,D4],HALF,80), ([G3,B3,D4],WHOLE,90),
        ([G3,B3,D4],HALF,88),([G3,B3,D4],HALF,82), ([C3,E3,G3],HALF,85),([C3,E3,G3],HALF,80),
        ([D3,A3,D4],QTR,85),([D3,A3,D4],QTR,80),([G3,B3,D4],QTR,90),([G3,B3,D4],QTR,85),
        ([G3,B3,D4],WHOLE,95),
        # B section (fuller, louder)
        ([G3,B3,D4],HALF,90),([G3,B3,D4],HALF,88), ([D3,A3,D4],HALF,88),([D3,A3,D4],HALF,85),
        ([C3,E3,G3],HALF,88),([C3,E3,G3],HALF,85), ([G3,B3,D4],WHOLE,95),
        ([G3,B3,D4],HALF,92),([G3,B3,D4],HALF,90), ([C3,E3,G3],HALF,90),([C3,E3,G3],HALF,88),
        ([D3,A3,D4],QTR,92),([G3,B3,D4],QTR,95),([D3,A3,D4],QTR,98),([G3,B3,D4],QTR,95),
        ([G3,B3,D4],WHOLE,102),
    ]
    melody = [
        # A section (bars 1-8)
        (G4,QTR,90),(D5,QTR,92),(G5,QTR,95),(D5,QTR,88),
        (C5,DOTTED_QTR,88),(E5,EIGHTH,82),(G5,HALF,90),
        (D5,QTR,90),(A4,QTR,85),(D5,QTR,88),(A4,QTR,82),
        (G4,WHOLE,92),
        (G5,QTR,95),(A5,QTR,92),(G5,QTR,88),(D5,QTR,85),
        (C5,QTR,88),(E5,QTR,90),(G5,QTR,92),(E5,QTR,85),
        (D5,QTR,90),(E5,QTR,92),(A4,QTR,85),(D5,QTR,88),
        (G5,WHOLE,100),
        # B section — grand triumphant coda (bars 9-16)
        (G5,QTR,98),(B4,QTR,90),(D5,QTR,95),(G5,QTR,100),
        (A5,DOTTED_QTR,98),(G5,EIGHTH,92),(E5,HALF,95),
        (D5,QTR,95),(A4,QTR,90),(B4,QTR,92),(D5,QTR,95),
        (C5,WHOLE,98),
        (G5,QTR,100),(A5,QTR,98),(G5,QTR,95),(E5,QTR,92),
        (C5,QTR,95),(E5,QTR,98),(G5,QTR,100),(E5,QTR,95),
        (D5,DOTTED_QTR,98),(E5,EIGHTH,95),(A4,QTR,92),(D5,QTR,95),
        (G5,WHOLE,108),
    ]
    # Grandioso finale (bars 17-20)
    bass += [
        (G1,HALF,105),(D2,HALF,102), (C2,HALF,105),(G2,HALF,100),  # bars 17+18
        (D2,QTR,108),(G2,QTR,105),(D2,QTR,110),(G2,QTR,108),       # bar 19
        (G1,WHOLE,115),                                              # bar 20
    ]
    pad += [
        ([G3,B3,D4],HALF,95),([G3,B3,D4],HALF,92), ([C3,E3,G3],HALF,92),([C3,E3,G3],HALF,90),  # bars 17+18
        ([D3,A3,D4],QTR,95),([G3,B3,D4],QTR,98),([D3,A3,D4],QTR,100),([G3,B3,D4],QTR,98),      # bar 19
        ([G3,B3,D4,G4],WHOLE,108),                                                                # bar 20
    ]
    melody += [
        (G5,QTR,105),(A5,QTR,102),(G5,QTR,98),(E5,QTR,95),
        (D5,QTR,100),(G5,QTR,105),(A5,QTR,108),(G5,QTR,102),
        (D5,DOTTED_QTR,102),(E5,EIGHTH,98),(D5,QTR,100),(C5,QTR,95),
        (G5,WHOLE,115),
    ]
    drums = [bar_march(),bar_march_inner(),bar_march_inner(),bar_march(),
             bar_march(),bar_march_inner(),bar_march_inner(),bar_march(),
             bar_march(),bar_march_inner(),bar_march_inner(),bar_march(),
             bar_march(),bar_march_inner(),bar_march_inner(),bar_march(),
             bar_march(),bar_march_inner(),bar_march_inner(),bar_march()]
    return bpm, bass, pad, melody, drums

# ── Composition 8: Peaceful Village ──────────────────────────────────────────

def comp_peaceful_village():
    bpm = 88
    # C major: C-Am-F-G (x4 = 16 bars)
    C2,A2,F2,G2 = _note('C',2),_note('A',2),_note('F',2),_note('G',2)
    E2,B2,C3    = _note('E',2),_note('B',2),_note('C',3)
    E3,G3,C4,A3,F3,D3,B3 = _note('E',3),_note('G',3),_note('C',4),_note('A',3),_note('F',3),_note('D',3),_note('B',3)
    C5,E5,G5,A5,D5,B4 = _note('C',5),_note('E',5),_note('G',5),_note('A',5),_note('D',5),_note('B',4)
    E4,G4,A4,F4,D4 = _note('E',4),_note('G',4),_note('A',4),_note('F',4),_note('D',4)

    # Walking quarter-note arpeggios — gentle, lilting
    def c_bar():  return [(C2,QTR,78),(E2,QTR,70),(G2,QTR,72),(E2,QTR,68)]
    def am_bar(): return [(A2,QTR,75),(C3,QTR,68),(E3,QTR,70),(C3,QTR,65)]
    def f_bar():  return [(F2,QTR,78),(A2,QTR,70),(C3,QTR,72),(A2,QTR,68)]
    def g_bar():  return [(G2,QTR,80),(B2,QTR,72),(D3,QTR,74),(B2,QTR,70)]

    bass = (c_bar() + am_bar() + f_bar() + g_bar()) * 3 + \
           c_bar() + am_bar() + f_bar() + [(C2,WHOLE,82)]

    pad = [
        ([E3,G3,C4],WHOLE,65),([A3,C4,E4],WHOLE,62),([F3,A3,C4],WHOLE,65),([G3,B3,D4],WHOLE,65),
        ([E3,G3,C4],WHOLE,65),([A3,C4,E4],WHOLE,62),([F3,A3,C4],WHOLE,65),([G3,B3,D4],WHOLE,65),
        ([E3,G3,C4],WHOLE,68),([A3,C4,E4],WHOLE,65),([F3,A3,C4],WHOLE,68),([G3,B3,D4],WHOLE,68),
        ([E3,G3,C4,G4],WHOLE,72),([A3,C4,E4],WHOLE,68),([F3,A3,C4],WHOLE,68),([E3,G3,C4],WHOLE,75),
    ]
    melody = [
        # A: Village morning (bars 1-4)
        (C5,QTR,80),(E5,QTR,82),(G5,QTR,85),(E5,QTR,80),
        (A5,DOTTED_QTR,80),(G5,EIGHTH,75),(E5,HALF,78),
        (F4,QTR,78),(A4,QTR,80),(C5,QTR,82),(A4,QTR,78),
        (G4,QTR,80),(B4,QTR,82),(D5,QTR,85),(B4,QTR,80),
        # A2: development (bars 5-8)
        (C5,DOTTED_QTR,82),(E5,EIGHTH,78),(G5,QTR,80),(A5,QTR,78),
        (A5,QTR,80),(G5,QTR,78),(E5,QTR,75),(A4,QTR,72),
        (F4,QTR,78),(G4,QTR,80),(A4,QTR,82),(G4,QTR,78),
        (E5,HALF,85),(C5,QTR,78),(G4,QTR,72),
        # B: meadow singing (bars 9-12)
        (E5,QTR,85),(G5,QTR,88),(A5,HALF,90),
        (G5,DOTTED_QTR,85),(E5,EIGHTH,80),(C5,HALF,82),
        (F4,QTR,80),(A4,QTR,82),(C5,QTR,85),(E5,QTR,88),
        (D5,QTR,85),(B4,QTR,80),(G4,QTR,78),(D4,QTR,75),
        # Return/coda (bars 13-16)
        (C5,QTR,82),(E5,QTR,85),(G5,QTR,88),(E5,QTR,85),
        (A5,DOTTED_QTR,85),(G5,EIGHTH,80),(E5,HALF,82),
        (F4,QTR,80),(G4,QTR,78),(A4,QTR,82),(B4,QTR,80),
        (C5,WHOLE,80),
    ]
    def gentle_bar():
        return [(0,BD,55),(QTR,RIDE,45),(QTR*2,SD,48),(QTR*3,RIDE,45)]
    drums = [gentle_bar()] * 16
    return bpm, bass, pad, melody, drums

# ── Composition 9: Dragon's Lair ──────────────────────────────────────────────

def comp_dragons_lair():
    bpm = 155
    # E minor: Em-D-C-B (x2)
    E1,D1,C1,B1 = _note('E',1),_note('D',1),_note('C',1),_note('B',1)
    E2,D2,C2,B2 = _note('E',2),_note('D',2),_note('C',2),_note('B',2)
    E3,G3,B3,D3,C3 = _note('E',3),_note('G',3),_note('B',3),_note('D',3),_note('C',3)
    Ds3,Fs3,As3 = _note('D#',3),_note('F#',3),_note('A#',3)
    E4,G4,B4,D5,E5,G5 = _note('E',4),_note('G',4),_note('B',4),_note('D',5),_note('E',5),_note('G',5)
    Ds4,Fs4,As4,C5 = _note('D#',4),_note('F#',4),_note('A#',4),_note('C',5)
    A4,F4,Ds5 = _note('A',4),_note('F',4),_note('D#',5)
    D4,C4,Gs4 = _note('D',4),_note('C',4),_note('G#',4)

    F5,A5,Fs5,B5 = _note('F',5),_note('A',5),_note('F#',5),_note('B',5)
    A3 = _note('A',3)

    # Driving bass (A section × 2 + B section)
    bass = []
    for root_pair in [(E1,E2),(D1,D2),(C1,C2),(B1,B2)]*2:
        r, r2 = root_pair
        bass += [(r,EIGHTH,95),(r,EIGHTH,80),(r2,EIGHTH,90),(r,EIGHTH,85),
                 (r,EIGHTH,92),(r,EIGHTH,78),(r2,EIGHTH,88),(r,EIGHTH,82)]
    # B section bass — relentless lower octave
    for root_pair in [(E1,E2),(D1,D2),(C1,C2),(B1,B2)]*2:
        r, r2 = root_pair
        bass += [(r,EIGHTH,100),(r2,EIGHTH,88),(r,EIGHTH,95),(r2,EIGHTH,85),
                 (r,EIGHTH,98),(r2,EIGHTH,85),(r,EIGHTH,92),(r2,EIGHTH,80)]

    pad = [
        # A section
        ([E2,G3,B3],HALF,78),([E2,G3,B3],HALF,72),
        ([D2,Fs3,C3+12],HALF,75),([D2,Fs3,C3+12],HALF,70),
        ([C2,E3,G3],HALF,75),([C2,E3,G3],HALF,70),
        ([B1+12,Ds3,Fs3],HALF,80),([B1+12,Ds3,Fs3],HALF,75),
        ([E2,G3,B3],HALF,82),([E2,G3,B3],HALF,75),
        ([D2,Fs3,C3+12],HALF,78),([D2,Fs3,C3+12],HALF,72),
        ([C2,E3,G3],HALF,78),([C2,E3,G3],HALF,72),
        ([E2,B2,E3],WHOLE,88),
        # B section — fortissimo
        ([E2,G3,B3],QTR,88),([E2,G3,B3],QTR,85),([E2,G3,B3],QTR,90),([E2,G3,B3],QTR,88),
        ([D2,Fs3,C3+12],QTR,85),([D2,Fs3,C3+12],QTR,82),([D2,Fs3,C3+12],QTR,88),([D2,Fs3,C3+12],QTR,85),
        ([C2,E3,G3],QTR,85),([C2,E3,G3],QTR,82),([C2,E3,G3],QTR,88),([C2,E3,G3],QTR,85),
        ([B1+12,Ds3,Fs3],HALF,90),([B1+12,Ds3,Fs3],HALF,88),
        ([E2,G3,B3],QTR,90),([E2,G3,B3],QTR,88),([D2,Fs3,C3+12],QTR,90),([C2,E3,G3],QTR,88),
        ([C2,E3,G3],HALF,88),([B1+12,Ds3,Fs3],HALF,90),
        ([D2,Fs3,A3],QTR,90),([D2,Fs3,A3],QTR,88),([D2,Fs3,A3],QTR,92),([D2,Fs3,A3],QTR,90),
        ([E2,G3,B3],WHOLE,98),
    ]

    melody = [
        # A section (bars 1-8)
        (E5,EIGHTH,92),(Ds5,EIGHTH,88),(D5,EIGHTH,85),(C5,EIGHTH,82),(B4,EIGHTH,88),(As4,EIGHTH,85),(A4,EIGHTH,82),(G4,EIGHTH,80),
        (Fs4,EIGHTH,85),(A4,EIGHTH,88),(C5,EIGHTH,90),(A4,EIGHTH,85),(Fs4,EIGHTH,82),(A4,EIGHTH,80),(Fs4,EIGHTH,78),(D4,EIGHTH,75),
        (E4,EIGHTH,85),(G4,EIGHTH,88),(B4,EIGHTH,90),(G4,EIGHTH,85),(E4,EIGHTH,82),(G4,EIGHTH,80),(E4,EIGHTH,78),(C4,EIGHTH,75),
        (B4,QTR,90),(Ds5,QTR,92),(Fs4,HALF,88),
        (G5,DOTTED_QTR,92),(E5,EIGHTH,85),(G5,QTR,88),(E5,QTR,82),
        (D5,EIGHTH,88),(C5,EIGHTH,85),(B4,EIGHTH,82),(As4,EIGHTH,80),(A4,EIGHTH,85),(Gs4,EIGHTH,80),(G4,EIGHTH,78),(Fs4,EIGHTH,75),
        (G4,EIGHTH,85),(A4,EIGHTH,88),(B4,EIGHTH,90),(C5,EIGHTH,92),(D5,EIGHTH,90),(E5,EIGHTH,88),(G5,EIGHTH,92),(E5,EIGHTH,88),
        (E5,WHOLE,98),
        # B section — final battle (bars 9-16)
        (B4,EIGHTH,95),(Ds5,EIGHTH,92),(Fs5,EIGHTH,98),(Ds5,EIGHTH,95),(B4,EIGHTH,92),(Ds5,EIGHTH,90),(Fs5,EIGHTH,95),(B4,EIGHTH,92),
        (A5,EIGHTH,98),(Fs5,EIGHTH,95),(D5,EIGHTH,92),(A4,EIGHTH,88),(Fs4,EIGHTH,90),(A4,EIGHTH,88),(D5,EIGHTH,90),(Fs5,EIGHTH,95),
        (G5,EIGHTH,92),(E5,EIGHTH,88),(C5,EIGHTH,85),(G4,EIGHTH,82),(E4,EIGHTH,82),(G4,EIGHTH,80),(C5,EIGHTH,85),(E5,EIGHTH,90),
        (B4,EIGHTH,95),(Ds5,EIGHTH,98),(Fs5,QTR,100),(B5,HALF,98),
        (G5,DOTTED_QTR,98),(F5,EIGHTH,95),(E5,QTR,92),(D5,QTR,90),
        (E5,EIGHTH,95),(D5,EIGHTH,92),(C5,EIGHTH,90),(B4,EIGHTH,88),(A4,EIGHTH,92),(Gs4,EIGHTH,88),(G4,EIGHTH,85),(Fs4,EIGHTH,82),
        (G4,QTR,90),(A4,QTR,92),(B4,QTR,95),(D5,QTR,98),
        (E5,WHOLE,105),
    ]
    drums = [bar_boss(),bar_heavy(),bar_rock(),bar_boss(),
             bar_heavy(),bar_rock(),bar_boss(),bar_boss(),
             bar_boss(),bar_heavy(),bar_rock(),bar_boss(),
             bar_heavy(),bar_rock(),bar_boss(),bar_boss()]
    return bpm, bass, pad, melody, drums

# ── Composition 10: Twilight Lullaby (3/4) ───────────────────────────────────

def comp_twilight_lullaby():
    bpm = 62
    BAR = QTR * 3  # 3/4 bar
    # D major: D-G-A-D (x4 = 12 bars)
    D1,G1,A1 = _note('D',1),_note('G',1),_note('A',1)
    D2,G2,A2 = _note('D',2),_note('G',2),_note('A',2)
    D3,Fs3,A3 = _note('D',3),_note('F#',3),_note('A',3)
    G3,B3,E3 = _note('G',3),_note('B',3),_note('E',3)
    A3n,Cs4,E4 = _note('A',3),_note('C#',4),_note('E',4)
    D4,Fs4,G4,A4 = _note('D',4),_note('F#',4),_note('G',4),_note('A',4)
    B4,Cs5,D5 = _note('B',4),_note('C#',5),_note('D',5)
    E5,Fs5 = _note('E',5),_note('F#',5)
    Cs3 = _note('C#',3)

    bass = []
    for n in [D1,G1,A1,D1] * 4:
        bass.append((n, BAR, 65))

    # Gentle arpeggiated chords in 3/4 — wrapped as single-note chords for chords_trk
    def arp(n1,n2,n3):
        return [([n1],QTR,60),([n2],QTR,55),([n3],QTR,52)]

    pad = (
        arp(D3,Fs3,A3) + arp(G3,B3,D4) + arp(A3n,Cs4,E4) + arp(D3,Fs3,A3) +
        arp(D3,Fs3,A3) + arp(G3,B3,D4) + arp(A3n,Cs4,E4) + arp(D3,Fs3,A3) +
        arp(D3,Fs3,A3) + arp(G3,B3,D4) + arp(A3n,Cs4,E4) + arp(D3,Fs3,A3) +
        arp(D3,Fs3,A3) + arp(G3,B3,D4) + arp(A3n,Cs4,E4) + arp(D3,Fs3,A3)
    )

    melody = [
        # Bar 1 D
        (D5,HALF,68),(Cs5,QTR,62),
        # Bar 2 G
        (B4,QTR,65),(A4,QTR,62),(G4,QTR,60),
        # Bar 3 A
        (A4,HALF,65),(Cs5,QTR,62),
        # Bar 4 D
        (D5,BAR,70),
        # Bar 5 D: variation
        (Fs5,QTR,68),(E5,QTR,65),(D5,QTR,62),
        # Bar 6 G
        (G4,HALF,65),(A4,QTR,62),
        # Bar 7 A
        (Cs5,QTR,65),(B4,QTR,62),(A4,QTR,60),
        # Bar 8 D
        (D5,BAR,65),
        # Bar 9-12: final pass, simpler
        (D5,HALF,65),(B4,QTR,60),
        (G4,HALF,62),(A4,QTR,58),
        (A4,QTR,62),(G4,QTR,58),(Fs4,QTR,55),
        (D4,BAR,65),
        # Bars 13-16: gentle farewell — reprise softly, closing cadence
        # Bar 13 D: soft reprise of opening
        (Fs5,QTR,62),(E5,QTR,58),(D5,QTR,55),
        # Bar 14 G: settling
        (G4,HALF,60),(A4,QTR,55),
        # Bar 15 A: quiet approach (DOTTED_HALF = BAR in 3/4)
        (A4,DOTTED_HALF,58),
        # Bar 16 D: final resolution
        (D4,BAR,62),
    ]

    drums = [bar_waltz_crash()] + [bar_waltz()] * 15
    return bpm, bass, pad, melody, drums, BAR  # returns BAR for 3/4


# ── Composition 12: Celtic Dawn ───────────────────────────────────────────────

def comp_celtic_dawn():
    bpm = 96
    # E minor (Aeolian) modal: Em - G - D - Am (x3)
    E1,G1,D2,A1,B1 = _note('E',1),_note('G',1),_note('D',2),_note('A',1),_note('B',1)
    E2,G2,D3,A2,B2 = _note('E',2),_note('G',2),_note('D',3),_note('A',2),_note('B',2)
    E3,G3,B3,D4,A3 = _note('E',3),_note('G',3),_note('B',3),_note('D',4),_note('A',3)
    E4,G4,A4,B4,D5 = _note('E',4),_note('G',4),_note('A',4),_note('B',4),_note('D',5)
    E5,G5,A5,B5 = _note('E',5),_note('G',5),_note('A',5),_note('B',5)
    Fs4,Cs5 = _note('F#',4),_note('C#',5)

    def bass_bar_em():
        return [(E1,QTR,82),(B1+12,EIGHTH,65),(E2,EIGHTH,70),(B1+12,QTR,68),(E1,QTR,78)]
    def bass_bar_g():
        return [(G1,QTR,80),(D2,EIGHTH,62),(G2,EIGHTH,68),(D2,QTR,65),(G1,QTR,76)]
    def bass_bar_d():
        return [(D2,QTR,80),(A2,EIGHTH,62),(D2,EIGHTH,68),(A2,QTR,65),(D2,QTR,76)]
    def bass_bar_am():
        return [(A1,QTR,78),(E2,EIGHTH,62),(A2,EIGHTH,65),(E2,QTR,62),(A1,QTR,75)]

    bass = (bass_bar_em() + bass_bar_g() + bass_bar_d() + bass_bar_am()) * 4

    def pad_em():  return [([E3,B3,E4],HALF,68),([E3,B3,E4],HALF,62)]
    def pad_g():   return [([G3,D4,G4],HALF,65),([G3,D4,G4],HALF,60)]
    def pad_d():   return [([D3,A3,D4],HALF,65),([D3,A3,D4],HALF,60)]
    def pad_am():  return [([A3,E4,A4],HALF,66),([A3,E4,A4],HALF,62)]

    pad = (pad_em() + pad_g() + pad_d() + pad_am()) * 4

    melody = [
        # A section — bars 1-4: Em G D Am
        (B4,EIGHTH,80),(E5,EIGHTH,82),(G5,EIGHTH,85),(E5,EIGHTH,80),(B4,EIGHTH,78),(A4,EIGHTH,75),(G4,EIGHTH,72),(A4,EIGHTH,70),
        (G4,EIGHTH,78),(A4,EIGHTH,80),(B4,EIGHTH,82),(D5,EIGHTH,85),(B4,EIGHTH,80),(G4,EIGHTH,75),(D4,EIGHTH,70),(G4,EIGHTH,68),
        (D5,EIGHTH,82),(E5,EIGHTH,85),(D5,EIGHTH,80),(B4,EIGHTH,78),(A4,EIGHTH,80),(B4,EIGHTH,75),(D5,EIGHTH,78),(A4,EIGHTH,72),
        (A4,EIGHTH,78),(G4,EIGHTH,75),(E4,EIGHTH,70),(D4,EIGHTH,68),(E4,EIGHTH,72),(G4,EIGHTH,75),(A4,EIGHTH,78),(E5,EIGHTH,82),
        # B section — bars 5-8: Em G D Am, higher register
        (E5,EIGHTH,85),(G5,EIGHTH,88),(B5,EIGHTH,90),(G5,EIGHTH,85),(E5,EIGHTH,82),(D5,EIGHTH,78),(B4,EIGHTH,75),(E5,EIGHTH,80),
        (D5,EIGHTH,88),(E5,EIGHTH,90),(G5,EIGHTH,92),(D5,EIGHTH,85),(B4,EIGHTH,82),(A4,EIGHTH,78),(G4,EIGHTH,75),(D5,EIGHTH,80),
        (D5,DOTTED_QTR,88),(E5,EIGHTH,82),(D5,QTR,85),(B4,QTR,80),
        (E5,QTR,85),(D5,QTR,82),(B4,QTR,78),(A4,QTR,75),
        # C section — bars 9-12: building to resolution
        (E4,EIGHTH,78),(G4,EIGHTH,80),(A4,EIGHTH,82),(B4,EIGHTH,85),(D5,EIGHTH,88),(E5,EIGHTH,90),(G5,EIGHTH,92),(E5,EIGHTH,88),
        (G5,QTR,90),(D5,QTR,85),(B4,QTR,82),(A4,QTR,78),
        (A4,EIGHTH,82),(B4,EIGHTH,85),(D5,EIGHTH,88),(B4,EIGHTH,82),(A4,EIGHTH,78),(G4,EIGHTH,75),(E4,EIGHTH,70),(G4,EIGHTH,68),
        (E5,WHOLE,88),
        # D section — bars 13-16: grand finale
        # Bar 13 Em: soaring climax run
        (E5,EIGHTH,90),(G5,EIGHTH,92),(A5,EIGHTH,95),(B5,EIGHTH,92),(A5,EIGHTH,90),(G5,EIGHTH,88),(E5,EIGHTH,85),(D5,EIGHTH,82),
        # Bar 14 G: strong rhythmic descent
        (G4,QTR,86),(B4,QTR,83),(D5,QTR,88),(B4,QTR,86),
        # Bar 15 D: final build to cadence
        (D5,DOTTED_QTR,88),(E5,EIGHTH,85),(D5,QTR,82),(B4,QTR,78),
        # Bar 16 Em: grand close
        (E5,WHOLE,92),
    ]
    drums = [bar_celtic()] + [bar_celtic_inner()] * 2 + [bar_celtic()] + \
            [bar_celtic()] + [bar_celtic_inner()] * 2 + [bar_celtic()] + \
            [bar_celtic()] + [bar_celtic_inner()] * 2 + [bar_celtic()] + \
            [bar_celtic()] + [bar_celtic_inner()] * 2 + [bar_celtic()]
    return bpm, bass, pad, melody, drums


# ── Composition 12: Moonlight Reverie ────────────────────────────────────────

def comp_moonlight_reverie():
    bpm = 72
    # Bb Major (2 flats: Bb, Eb) — I-vi-IV-V (Bbmaj7-Gm7-Ebmaj7-F7)
    Bb1 = _note('Bb',1); F1 = _note('F',1)
    D2  = _note('D',2);  F2 = _note('F',2);  G2 = _note('G',2)
    Bb2 = _note('Bb',2); Eb2 = _note('Eb',2); A2 = _note('A',2)
    C3  = _note('C',3);  D3  = _note('D',3);  F3 = _note('F',3)
    G3  = _note('G',3);  Bb3 = _note('Bb',3); Eb3 = _note('Eb',3)
    A3  = _note('A',3);  Ab3 = _note('Ab',3)
    C4  = _note('C',4);  D4  = _note('D',4);  F4 = _note('F',4)
    G4  = _note('G',4);  Bb4 = _note('Bb',4); Eb4 = _note('Eb',4)
    A4  = _note('A',4);  Ab4 = _note('Ab',4)
    C5  = _note('C',5);  D5  = _note('D',5);  F5 = _note('F',5)
    G5  = _note('G',5);  Bb5 = _note('Bb',5); Eb5 = _note('Eb',5)

    # Walking bass arpeggios — gentle, singing
    def bb_bar():  return [(Bb1,QTR,68),(D2,QTR,60),(F2,QTR,63),(D2,QTR,58)]
    def gm_bar():  return [(G2,QTR,65),(Bb2,QTR,58),(D3,QTR,60),(Bb2,QTR,55)]
    def eb_bar():  return [(Eb2,QTR,68),(G2,QTR,60),(Bb2,QTR,63),(G2,QTR,58)]
    def f7_bar():  return [(F1,QTR,70),(A2,QTR,62),(C3,QTR,65),(A2,QTR,60)]

    bass = (bb_bar() + gm_bar() + eb_bar() + f7_bar()) * 4

    # Lush 4-note 7th chords, gentle crescendo over 4 phrases
    pad = [
        ([D3,F3,Bb3,A3],WHOLE,50), ([Bb2,D3,G3,F3],WHOLE,48), ([Eb3,G3,Bb3,D4],WHOLE,50), ([F3,A3,C4,Eb4],WHOLE,52),
        ([D3,F3,Bb3,A3],WHOLE,54), ([Bb2,D3,G3,F3],WHOLE,52), ([Eb3,G3,Bb3,D4],WHOLE,54), ([F3,A3,C4,Eb4],WHOLE,56),
        ([Bb2,D3,G3,F3],WHOLE,58), ([Eb3,G3,C4],WHOLE,55),    ([Eb3,G3,Bb3,D4],WHOLE,58), ([F3,Ab3,C4,Eb4],WHOLE,60),
        ([D3,F3,Bb3,A3],WHOLE,62), ([Bb2,D3,G3,F3],WHOLE,60), ([Eb3,G3,Bb3,D4],WHOLE,62), ([Bb2,D3,F3,Bb3],WHOLE,65),
    ]

    melody = [
        # A: moonlit opening (bars 1-4) — arching lyrical phrases
        (Bb4,DOTTED_QTR,72),(C5,EIGHTH,68),(D5,HALF,75),
        (G4,QTR,68),(Bb4,QTR,72),(D5,DOTTED_QTR,75),(F5,EIGHTH,70),
        (Eb5,HALF,78),(D5,QTR,72),(C5,QTR,68),
        (F5,DOTTED_HALF,80),(Eb5,QTR,72),
        # A2: development (bars 5-8)
        (D5,QTR,75),(Bb4,QTR,70),(C5,DOTTED_QTR,72),(D5,EIGHTH,68),
        (G5,HALF,82),(F5,QTR,75),(Eb5,QTR,70),
        (Eb5,QTR,72),(D5,QTR,68),(C5,QTR,72),(Bb4,QTR,75),
        (A4,WHOLE,70),
        # B: moonlit water (bars 9-12) — Ab4 chromatic passing tone (shows ♭)
        (G5,DOTTED_QTR,80),(F5,EIGHTH,75),(Eb5,HALF,78),
        (G4,QTR,70),(Bb4,QTR,72),(Eb5,DOTTED_QTR,78),(F5,EIGHTH,75),
        (D5,QTR,75),(Ab4,QTR,68),(G4,QTR,72),(Bb4,QTR,75),
        (F5,DOTTED_HALF,72),(Eb5,QTR,65),
        # Return + coda (bars 13-16)
        (Bb4,QTR,75),(D5,QTR,78),(F5,QTR,82),(D5,QTR,78),
        (Eb5,DOTTED_QTR,80),(D5,EIGHTH,75),(C5,HALF,78),
        (G4,QTR,72),(Bb4,QTR,75),(D5,DOTTED_QTR,78),(C5,EIGHTH,72),
        (Bb4,WHOLE,75),
    ]

    rng = random.Random(sum(ord(c) for c in 'moonlight_reverie'))
    melody   = humanize(articulate(melody, fast_ratio=0.6, slow_ratio=0.95), jitter=5, rng=rng)
    bass_h   = humanize(bass, jitter=6, rng=rng)
    pad_h    = humanize_chords(pad, jitter=4, rng=rng)

    def nocturne_bar():     return [(0,BD,45),(QTR,RIDE,40),(QTR*2,RIDE,38),(QTR*3,RIDE,40)]
    def nocturne_soft():    return [(0,BD,45),(QTR,RIDE,40),(QTR*2,SD,38),(QTR*3,RIDE,35)]
    drums = ([nocturne_bar()]*2 + [nocturne_soft()]*2) * 4
    drums_h = humanize_drums(drums, jitter=4, rng=rng)

    return bpm, bass_h, pad_h, melody, drums_h


# ── Composition 14: Midnight Blues ────────────────────────────────────────────

def comp_midnight_blues():
    bpm = 88
    # G Minor jazz: Gm7-Cm7-F7-Bbmaj7-Am7b5-D7 progression, 16 bars
    # Bars 1-2 are melodically silent (intro), giving whole-bar rests in notation.

    G1,A1,Bb1,B1 = _note('G',1),_note('A',1),_note('Bb',1),_note('B',1)
    C2,D2,Eb2,F2,Fs2,G2,A2,Bb2 = (_note('C',2),_note('D',2),_note('Eb',2),
        _note('F',2),_note('F#',2),_note('G',2),_note('A',2),_note('Bb',2))
    C3,D3,Eb3,F3,Fs3,G3,A3,Bb3 = (_note('C',3),_note('D',3),_note('Eb',3),
        _note('F',3),_note('F#',3),_note('G',3),_note('A',3),_note('Bb',3))
    C4,D4,Eb4,F4,Fs4,G4,A4,Bb4 = (_note('C',4),_note('D',4),_note('Eb',4),
        _note('F',4),_note('F#',4),_note('G',4),_note('A',4),_note('Bb',4))
    C5,D5,Eb5 = _note('C',5),_note('D',5),_note('Eb',5)

    # Walking bass: quarter-note chromatic lines
    bass = [
        # Bars 1-2: intro Gm7
        (G1,QTR,72),(Bb1,QTR,68),(D2,QTR,70),(F2,QTR,68),
        (G1,QTR,70),(A1,QTR,65),(Bb1,QTR,68),(B1,QTR,65),
        # Bars 3-4: Gm7 | Cm7
        (G1,QTR,72),(Bb1,QTR,68),(D2,QTR,70),(F2,QTR,68),
        (C2,QTR,75),(Eb2,QTR,70),(G2,QTR,72),(Bb2,QTR,68),
        # Bars 5-6: F7 | Bbmaj7
        (F2,QTR,75),(A2,QTR,70),(C3,QTR,72),(Eb3,QTR,68),
        (Bb1,QTR,75),(D2,QTR,70),(F2,QTR,72),(A2,QTR,68),
        # Bars 7-8: Gm7 | Am7b5→D7
        (G1,QTR,72),(Bb1,QTR,68),(D2,QTR,70),(F2,QTR,68),
        (A1,QTR,70),(C2,QTR,68),(Eb2,QTR,65),(D2,QTR,72),
        # Bars 9-12: repeat A
        (G1,QTR,72),(Bb1,QTR,68),(D2,QTR,70),(F2,QTR,68),
        (C2,QTR,75),(Eb2,QTR,70),(G2,QTR,72),(Bb2,QTR,68),
        (F2,QTR,75),(A2,QTR,70),(C3,QTR,72),(Eb3,QTR,68),
        (Bb1,QTR,75),(D2,QTR,70),(F2,QTR,72),(A2,QTR,68),
        # Bars 13-14: Am7b5 | D7
        (A1,QTR,68),(C2,QTR,65),(Eb2,QTR,62),(G2,QTR,65),
        (D2,QTR,75),(Fs2,QTR,72),(A2,QTR,70),(C3,QTR,68),
        # Bars 15-16: Gm7 close
        (G1,QTR,72),(Bb1,QTR,68),(D2,QTR,70),(F2,QTR,68),
        (G1,WHOLE,78),
    ]

    # Jazz pad voicings (shell voicings with 7ths and extensions)
    pad = [
        ([G2,F3,Bb3,D4],WHOLE,52), ([G2,F3,Bb3,D4],WHOLE,52),  # bars 1-2 intro
        ([G2,F3,Bb3,D4],WHOLE,55), ([C3,Bb3,Eb4,G4],WHOLE,52),  # bars 3-4
        ([F2,Eb3,A3,C4],WHOLE,52), ([Bb2,A3,D4,F4],WHOLE,50),   # bars 5-6
        ([G2,F3,Bb3,D4],WHOLE,55),                               # bar 7
        ([A2,Eb3,G3,C4],HALF,50),([D2,Fs3,C4,A3],HALF,55),     # bar 8 (2 halves)
        ([G2,F3,Bb3,D4],WHOLE,55), ([C3,Bb3,Eb4,G4],WHOLE,52),  # bars 9-10
        ([F2,Eb3,A3,C4],WHOLE,52), ([Bb2,A3,D4,F4],WHOLE,50),   # bars 11-12
        ([A2,Eb3,G3,C4],WHOLE,50), ([D2,Fs3,C4,A3],WHOLE,55),   # bars 13-14
        ([G2,F3,Bb3,D4],WHOLE,55), ([G1,F2,Bb2,D3],WHOLE,48),   # bars 15-16
    ]

    # Melody: 2 silent bars (vel=0 preserved by humanize) + 14 bars jazz
    SIL = (0, WHOLE, 0)  # silent bar placeholder — vel=0 is never humanized up
    melody = [
        SIL, SIL,   # bars 1-2 silent → whole-bar rests shown in notation
        # Bar 3 (Gm7): lyrical opening motif
        (Bb4,QTR,68),(A4,EIGHTH,60),(G4,EIGHTH,62),(F4,QTR,65),(G4,QTR,70),
        # Bar 4 (Cm7): descending chord tones
        (Eb4,QTR,72),(D4,QTR,68),(C4,QTR,65),(Bb3,QTR,62),
        # Bar 5 (F7): eighth-note swing line
        (A4,EIGHTH,70),(Bb4,EIGHTH,72),(A4,QTR,68),(G4,HALF,65),
        # Bar 6 (Bbmaj7): melodic peak, floats
        (F4,QTR,68),(Eb4,EIGHTH,62),(D4,EIGHTH,60),(C4,HALF,65),
        # Bar 7 (Gm7): syncopated push
        (G4,DOTTED_QTR,72),(A4,EIGHTH,68),(Bb4,QTR,70),(A4,QTR,65),
        # Bar 8 (Am7b5→D7): Fs4 = F♯ chromatic leading tone (shows ♯ accidental)
        (G4,HALF,68),(Fs4,HALF,72),
        # Bar 9 (Gm7): high register entry
        (G4,EIGHTH,70),(A4,EIGHTH,68),(Bb4,QTR,72),(D5,HALF,75),
        # Bar 10 (Cm7): climbing phrase
        (Eb5,QTR,72),(D5,EIGHTH,68),(C5,EIGHTH,65),(Bb4,HALF,68),
        # Bar 11 (F7): jazz run with chromatic passing
        (A4,QTR,65),(Bb4,EIGHTH,68),(A4,EIGHTH,65),(G4,QTR,62),(F4,QTR,60),
        # Bar 12 (Bbmaj7): resolution phrase
        (D4,QTR,65),(Eb4,EIGHTH,62),(F4,EIGHTH,65),(G4,HALF,68),
        # Bar 13 (Am7b5): tense half-diminished color
        (Eb4,HALF,62),(D4,QTR,65),(C4,QTR,60),
        # Bar 14 (D7): dominant release with Fs4 = F♯
        (Fs4,HALF,72),(A4,QTR,68),(C5,QTR,65),
        # Bar 15 (Gm7): final long phrase
        (G4,DOTTED_HALF,72),(A4,QTR,65),
        # Bar 16 (Gm7): held close
        (G4,WHOLE,68),
    ]

    # Jazz drums: ride-led pattern (full) + lighter intro
    def jazz_bar():
        return [
            (0,        RIDE,55),(0,        BD,  60),
            (EIGHTH,   RIDE,42),
            (QTR,      RIDE,50),(QTR,      SD,  48),
            (QTR*2,    RIDE,52),(QTR*2+EIGHTH,RIDE,42),
            (QTR*3,    RIDE,50),(QTR*3,    SD,  48),
        ]
    def jazz_intro():
        return [(0,RIDE,48),(QTR,RIDE,44),(QTR*2,RIDE,46),(QTR*3,RIDE,44)]

    drums = [jazz_intro()]*2 + [jazz_bar()]*14
    return bpm, bass, pad, melody, drums


def comp_silk_road():
    bpm = 80
    # A Hijaz (Phrygian Dominant): A(1) Bb(b2) C#(3) D(4) E(5) F(b6) G(b7)
    # The hallmark: augmented 2nd between Bb and C# (3 semitones apart)
    A1,Bb1,E1,G1 = _note('A',1),_note('Bb',1),_note('E',1),_note('G',1)
    A2,Bb2,Cs2,D2,E2,F2,G2,Gs2 = (
        _note('A',2),_note('Bb',2),_note('C#',2),_note('D',2),
        _note('E',2),_note('F',2),_note('G',2),_note('G#',2))
    A3,Bb3,Cs3,D3,E3,F3,G3,Gs3,B3 = (
        _note('A',3),_note('Bb',3),_note('C#',3),_note('D',3),
        _note('E',3),_note('F',3),_note('G',3),_note('G#',3),_note('B',3))
    A4,Bb4,Cs4,D4,E4,F4,G4,Gs4,B4 = (
        _note('A',4),_note('Bb',4),_note('C#',4),_note('D',4),
        _note('E',4),_note('F',4),_note('G',4),_note('G#',4),_note('B',4))
    Cs5,D5 = _note('C#',5),_note('D',5)

    # Bass: A-pedal drone with bII (Bb) color and movement through Gm-E cadences
    bass = [
        # Bars 1-2: A drone, introduce Bb tension
        (A1,HALF,80),(A2,HALF,72),
        (Bb1,QTR,78),(A1,QTR,75),(A2,HALF,72),
        # Bars 3-4: A and Bb interplay
        (A1,HALF,82),(A2,HALF,75),
        (Bb1,QTR,80),(A1,QTR,78),(A2,HALF,75),
        # Bars 5-6: Gm (bVII) → E (dominant)
        (G1,HALF,75),(G1,HALF,72),
        (E1,HALF,80),(E2,HALF,75),
        # Bars 7-8: A pedal, cadential approach
        (A1,HALF,80),(A2,HALF,72),
        (E1,QTR,80),(A1,QTR,78),(E1,HALF,82),
        # Bars 9-10: energized — busier eighth-feel quarters
        (A1,QTR,82),(Bb1,QTR,78),(A1,QTR,82),(A2,QTR,75),
        (A1,QTR,80),(A2,QTR,72),(Bb1,QTR,78),(A1,QTR,82),
        # Bars 11-12: Gm → E again with more drive
        (G1,HALF,78),(G2,HALF,72),
        (E1,HALF,82),(E2,HALF,78),
        # Bars 13-14: climax build — push with Cs color
        (A1,QTR,85),(Bb1,QTR,82),(A1,QTR,85),(Cs2,QTR,80),
        (D2,HALF,82),(E1,HALF,80),
        # Bars 15-16: resolution
        (A1,QTR,80),(G1,QTR,75),(E1,QTR,78),(A1,QTR,80),
        (A1,WHOLE,88),
    ]

    # Pad: sustained voicings highlighting the Hijaz chord colors
    pad = [
        ([A2,Cs3,E3],WHOLE,58), ([A2,Cs3,E3],WHOLE,55),           # bars 1-2  Am (raised 3rd)
        ([Bb2,D3,F3],WHOLE,55), ([A2,Cs3,E3],WHOLE,58),           # bars 3-4  Bb → Am
        ([G2,Bb3,D4],WHOLE,52), ([E2,Gs3,B3],WHOLE,55),           # bars 5-6  Gm → E
        ([A2,Cs3,E3],WHOLE,58), ([E2,Gs3,B3],WHOLE,60),           # bars 7-8
        ([A2,Cs3,E3,A3],WHOLE,60), ([A2,Cs3,E3,A3],WHOLE,58),    # bars 9-10 fuller voicing
        ([Bb2,D3,F3],WHOLE,58), ([A2,Cs3,E3],WHOLE,60),           # bars 11-12
        ([G2,Bb3,D4],WHOLE,58), ([E2,Gs3,B3],WHOLE,62),           # bars 13-14 climax chords
        ([A2,E3,A3],HALF,62), ([E2,Gs3,B3],HALF,60),              # bar 15: suspended tension
        ([A2,Cs3,E3,A3],WHOLE,65),                                  # bar 16: resolution
    ]

    # Melody: ornamental Hijaz phrases featuring Bb-C# augmented 2nd
    melody = [
        # Bar 1: open — stepwise descent (5th-4th-raised3rd)
        (E4,QTR,68),(D4,QTR,65),(Cs4,HALF,72),
        # Bar 2: Bb-A Hijaz cadence motif
        (Bb3,QTR,70),(A3,QTR,65),(E4,HALF,72),
        # Bar 3: rise with Bb tension — oscillate around root
        (A4,QTR,68),(Bb4,QTR,72),(A4,QTR,68),(G4,QTR,65),
        # Bar 4: stepwise down through the raised 3rd
        (E4,DOTTED_QTR,70),(D4,EIGHTH,62),(Cs4,HALF,75),
        # Bar 5: high Bb then ornamental descent
        (A4,HALF,70),(G4,EIGHTH,62),(A4,EIGHTH,65),(Bb4,QTR,72),
        # Bar 6: descend through bVI-V
        (A4,QTR,68),(G4,QTR,65),(F4,QTR,62),(E4,QTR,68),
        # Bar 7: the full Hijaz descent A→Bb→(leap)C#→Bb→A
        (D4,QTR,68),(Cs4,QTR,72),(Bb3,QTR,68),(A3,QTR,70),
        # Bar 8: Bb-A cadence, quiet
        (Bb3,HALF,68),(A3,HALF,72),
        # Bar 9: energized re-entry with ornament
        (A4,EIGHTH,72),(G4,EIGHTH,65),(A4,QTR,70),(Bb4,DOTTED_QTR,75),(A4,EIGHTH,70),
        # Bar 10: descend with bVI passing
        (E4,HALF,70),(D4,QTR,65),(Cs4,QTR,72),
        # Bar 11: melodic peak approach — Bb then chromatic line
        (A4,QTR,70),(Bb4,EIGHTH,75),(A4,EIGHTH,70),(G4,QTR,65),(F4,QTR,62),
        # Bar 12: long descent through full scale
        (E4,DOTTED_QTR,72),(D4,EIGHTH,65),(Cs4,QTR,70),(A3,QTR,68),
        # Bar 13: climax — leap to C#5 (the characteristic peak)
        (A4,QTR,75),(Bb4,QTR,78),(Cs5,HALF,82),
        # Bar 14: high register with D5 peak then descend
        (D5,QTR,80),(Cs5,QTR,78),(Bb4,HALF,75),
        # Bar 15: elegant resolution phrase
        (A4,DOTTED_HALF,72),(G4,QTR,65),
        # Bar 16: final low A
        (A3,WHOLE,70),
    ]

    # Drums: Maqsum-inspired pattern (doumbek/tabla feel)
    def bar_maqsum():
        return [
            (0,       BD, 78),(0,       CHH,44),
            (EIGHTH,  CHH,38),
            (QTR,     CHH,42),(QTR,     SD, 45),
            (QTR+EIGHTH, CHH,38),
            (QTR*2,   BD, 65),(QTR*2,   CHH,42),
            (QTR*2+EIGHTH, CHH,38),
            (QTR*3,   CHH,40),(QTR*3,   SD, 42),
            (QTR*3+EIGHTH, CHH,38),
        ]
    def bar_maqsum_full():
        return [
            (0,       BD, 85),(0,       CHH,48),
            (EIGHTH,  CHH,42),(EIGHTH,  SD, 30),
            (QTR,     CHH,45),(QTR,     SD, 55),
            (QTR+EIGHTH, CHH,40),
            (QTR*2,   BD, 72),(QTR*2,   CHH,45),
            (QTR*2+EIGHTH, CHH,40),(QTR*2+EIGHTH, SD, 30),
            (QTR*3,   CHH,42),(QTR*3,   SD, 52),
            (QTR*3+EIGHTH, CHH,40),
        ]
    def bar_maqsum_accent():
        return [
            (0,       CRASH,68),(0,     BD, 90),(0,      CHH,50),
            (EIGHTH,  CHH,42),
            (QTR,     CHH,45),(QTR,     SD, 58),
            (QTR+EIGHTH, OHH,42),
            (QTR*2,   BD, 78),(QTR*2,   CHH,48),
            (QTR*2+EIGHTH, CHH,42),
            (QTR*3,   CHH,45),(QTR*3,   SD, 55),
            (QTR*3+EIGHTH, CHH,42),
        ]
    def bar_maqsum_sparse():
        return [(0,BD,62),(QTR,CHH,40),(QTR*2,CHH,38),(QTR*3,SD,40)]

    drums = (
        [bar_maqsum_sparse()]*2 +   # bars 1-2: quiet intro
        [bar_maqsum()]*6 +          # bars 3-8: standard maqsum
        [bar_maqsum_full()]*4 +     # bars 9-12: fuller feel
        [bar_maqsum_accent()] +     # bar 13: crash accent (climax entry)
        [bar_maqsum_full()]*2 +     # bars 14-15
        [bar_maqsum_sparse()]       # bar 16: quiet resolution
    )

    return bpm, bass, pad, melody, drums


# ── Composition 16: Haunted Manor ────────────────────────────────────────────

def comp_haunted_manor():
    bpm = 55
    # D natural minor: D-E-F-G-A-Bb-C; raised 7th: C#; ♭5: Ab
    D1,C1,Bb1 = _note('D',1),_note('C',1),_note('Bb',1)
    A1,Ab1,G1,E1,F1 = _note('A',1),_note('Ab',1),_note('G',1),_note('E',1),_note('F',1)
    D2,A2,C2,F2,G2,Bb2,B2,Ab2,Cs2 = (
        _note('D',2),_note('A',2),_note('C',2),_note('F',2),_note('G',2),
        _note('Bb',2),_note('B',2),_note('Ab',2),_note('C#',2))
    D3,F3,A3,Bb3,G3,B3,C3,Cs3,E3,Eb3 = (
        _note('D',3),_note('F',3),_note('A',3),_note('Bb',3),_note('G',3),
        _note('B',3),_note('C',3),_note('C#',3),_note('E',3),_note('Eb',3))
    D4,E4,F4,G4,A4,Bb4,Cs4,Ab4,Eb4 = (
        _note('D',4),_note('E',4),_note('F',4),_note('G',4),_note('A',4),
        _note('Bb',4),_note('C#',4),_note('Ab',4),_note('Eb',4))
    D5,C5 = _note('D',5),_note('C',5)

    bass = [
        # Bars 1-2: deep D pedal
        (D1,WHOLE,50), (D1,WHOLE,48),
        # Bar 3: chromatic slide down
        (D1,HALF,52), (C1,HALF,45),
        # Bar 4: return
        (D1,WHOLE,50),
        # Bars 5-6: ♭6 Bb — ominous
        (Bb1,WHOLE,50), (Bb1,WHOLE,45),
        # Bar 7: A→Ab tritone motion
        (A1,HALF,52), (Ab1,HALF,48),
        # Bar 8: G
        (G1,WHOLE,50),
        # Bars 9-10: D returning, building
        (D1,WHOLE,55), (D1,DOTTED_HALF,55),(E1,QTR,52),
        # Bar 11: ♭3 F
        (F1,WHOLE,52),
        # Bar 12: G→Ab chromatic rise
        (G1,HALF,52), (Ab1,HALF,55),
        # Bar 13: A — climax approach
        (A1,WHOLE,58),
        # Bar 14: Bb/A tension
        (Bb1,HALF,62), (A1,HALF,58),
        # Bar 15: chromatic descent
        (Bb1,QTR,65),(A1,QTR,62),(Ab1,QTR,65),(G1,QTR,60),
        # Bar 16: final deep D
        (D1,WHOLE,70),
    ]

    pad = [
        ([D3,F3,A3],WHOLE,40),  ([D3,F3,A3],WHOLE,38),  # bars 1-2: Dm
        ([B2,D3,F3],WHOLE,42),                            # bar 3:  Bdim
        ([D3,F3,A3],WHOLE,45),                            # bar 4:  Dm
        ([Bb2,D3,F3],WHOLE,42), ([Bb2,D3,F3],WHOLE,38),  # bars 5-6: Bb
        ([Ab2,B2,D3],WHOLE,42),                           # bar 7:  Ab/Bdim — tritone cluster
        ([G2,Bb2,D3],WHOLE,45),                           # bar 8:  Gm
        ([D3,F3,A3],WHOLE,48),  ([D3,F3,A3],WHOLE,45),   # bars 9-10: Dm
        ([F2,A2,C3],WHOLE,48),                            # bar 11: F (brief brightness)
        ([G2,Bb2,D3],WHOLE,50),                           # bar 12: Gm
        ([A2,C3,Eb3],WHOLE,52),                           # bar 13: Adim — max tension
        ([Bb2,D3,F3],HALF,55),([A2,Cs3,E3],HALF,58),     # bar 14: Bb → A7
        ([D3,F3,A3],WHOLE,60),                            # bar 15: Dm back
        ([D2,A2,D3],WHOLE,65),                            # bar 16: final D minor
    ]

    melody = [
        # Bar 1: silence (vel=0 = rest in MIDI)
        (D4,WHOLE,0),
        # Bar 2: faint appearance
        (D4,HALF,0),(A4,QTR,30),(Bb4,QTR,32),
        # Bar 3: rising phrase, then silence
        (C5,HALF,38),(D4,HALF,0),
        # Bar 4: silence
        (D4,WHOLE,0),
        # Bar 5: single note
        (D4,DOTTED_HALF,0),(F4,QTR,35),
        # Bar 6: short phrase
        (F4,HALF,40),(Eb4,QTR,36),(D4,QTR,32),
        # Bar 7: tritone held (Ab = ♭5 over D)
        (Ab4,WHOLE,42),
        # Bar 8: G note then silence
        (G4,HALF,40),(D4,HALF,0),
        # Bar 9: silence
        (D4,WHOLE,0),
        # Bar 10: sparse
        (D4,HALF,0),(Bb4,DOTTED_QTR,38),(A4,EIGHTH,32),
        # Bar 11: descending phrase
        (G4,HALF,42),(F4,QTR,38),(E4,QTR,32),
        # Bar 12: sustained F
        (F4,WHOLE,45),
        # Bar 13: chromatic tension
        (E4,HALF,48),(Eb4,HALF,45),
        # Bar 14: rising with chromatics
        (D4,QTR,0),(Cs4,QTR,48),(D4,QTR,0),(A4,QTR,50),
        # Bar 15: resolve downward
        (Bb4,QTR,52),(A4,QTR,50),(G4,HALF,55),
        # Bar 16: final quiet D
        (D4,WHOLE,38),
    ]

    drums = [bar_heartbeat()]*8 + [bar_heartbeat_intense()]*8
    return bpm, bass, pad, melody, drums


# ── Composition 17: River Street Rag ─────────────────────────────────────────

def bar_ragtime_hat():
    return [(QTR, CHH, 40), (QTR*3, CHH, 38)]

def comp_ragtime():
    bpm = 104
    # C major — 16-bar stride ragtime (A strain bars 1-8, B strain bars 9-16)
    # Bass: stride pattern (root on beats 1+3, chord tone on 2+4)
    # Pad:  half-note chords
    # Mel:  syncopated eighth-note figures with off-beat accents
    C1,G1,F1,D1,E1,A1 = (_note('C',1),_note('G',1),_note('F',1),
                          _note('D',1),_note('E',1),_note('A',1))
    G2,C2,F2,D2,E2,A2,B2,Bb2 = (_note('G',2),_note('C',2),_note('F',2),_note('D',2),
                                  _note('E',2),_note('A',2),_note('B',2),_note('Bb',2))
    C3,E3,G3,D3,F3,A3,B3,Bb3 = (_note('C',3),_note('E',3),_note('G',3),_note('D',3),
                                  _note('F',3),_note('A',3),_note('B',3),_note('Bb',3))
    C4,D4,E4,F4,G4,A4,B4,Bb4 = (_note('C',4),_note('D',4),_note('E',4),_note('F',4),
                                  _note('G',4),_note('A',4),_note('B',4),_note('Bb',4))
    C5,D5,E5,G5 = _note('C',5),_note('D',5),_note('E',5),_note('G',5)

    def stride(r, hi):
        return [(r,QTR,82),(hi,QTR,65),(r,QTR,80),(hi,QTR,62)]

    bass = (
        # A strain: C-G7-C-G7 / C-F-G7-C (×1)
        stride(C1,G2) + stride(G1,B2) + stride(C1,G2) + stride(G1,B2) +
        stride(C1,G2) + stride(F1,C2) + stride(G1,B2) + stride(C1,E2) +
        # B strain: F-C7-F-Dm / G7-C-G7-C
        stride(F1,C2) + stride(C1,Bb2) + stride(F1,C2) + stride(D1,A2) +
        stride(G1,B2) + stride(C1,G2) + stride(G1,B2) + stride(C1,E2)
    )

    pad = [
        # A strain
        ([C3,E3,G3],HALF,60),([C3,E3,G3],HALF,58),   # bar 1  C
        ([G3,B3,D4],HALF,60),([G3,B3,F4],HALF,58),   # bar 2  G7
        ([C3,E3,G3],HALF,62),([C3,E3,G3],HALF,60),   # bar 3  C
        ([G3,B3,D4],HALF,60),([G3,B3,F4],HALF,58),   # bar 4  G7
        ([C3,E3,G3],HALF,62),([C3,E3,G3],HALF,60),   # bar 5  C
        ([F3,A3,C4],HALF,60),([F3,A3,C4],HALF,58),   # bar 6  F
        ([G3,B3,D4],HALF,62),([G3,B3,F4],HALF,60),   # bar 7  G7
        ([C3,E3,G3],HALF,65),([C3,E3,G3],HALF,62),   # bar 8  C
        # B strain
        ([F3,A3,C4],HALF,62),([F3,A3,C4],HALF,60),   # bar 9  F
        ([C3,E3,Bb3],HALF,60),([C3,E3,Bb3],HALF,58), # bar 10 C7
        ([F3,A3,C4],HALF,62),([F3,A3,C4],HALF,60),   # bar 11 F
        ([D3,F3,A3],HALF,60),([D3,F3,A3],HALF,58),   # bar 12 Dm
        ([G3,B3,D4],HALF,62),([G3,B3,F4],HALF,60),   # bar 13 G7
        ([C3,E3,G3],HALF,65),([C3,E3,G3],HALF,62),   # bar 14 C
        ([G3,B3,D4],HALF,62),([G3,B3,F4],HALF,60),   # bar 15 G7
        ([C3,E3,G3],WHOLE,70),                        # bar 16 C (big finish)
    ]

    melody = [
        # A strain — syncopated ragtime figures
        # Bar 1 (C):  rest-E-G-E-C-E  (240+240+480+240+240+480=1920)
        (0,EIGHTH,0),(E4,EIGHTH,82),(G4,QTR,85),(E4,EIGHTH,80),(C4,EIGHTH,78),(E4,QTR,85),
        # Bar 2 (G7): D-E-D-E-rest  (480+240+240+480+480=1920)
        (D4,QTR,80),(E4,EIGHTH,82),(D4,EIGHTH,78),(E4,QTR,82),(0,QTR,0),
        # Bar 3 (C):  rest-G-A-G-E-C  (240+240+240+240+480+480=1920)
        (0,EIGHTH,0),(G4,EIGHTH,82),(A4,EIGHTH,85),(G4,EIGHTH,82),(E4,QTR,82),(C4,QTR,78),
        # Bar 4 (G7): D-F-E-D-B  (480+240+240+480+480=1920)
        (D4,QTR,80),(F4,EIGHTH,78),(E4,EIGHTH,75),(D4,QTR,80),(B3,QTR,72),
        # Bar 5 (C):  rest-E-G-A-G-E (240+240+480+240+240+480=1920)
        (0,EIGHTH,0),(E4,EIGHTH,82),(G4,QTR,85),(A4,EIGHTH,85),(G4,EIGHTH,82),(E4,QTR,85),
        # Bar 6 (F):  F-E-C-A  (480+240+240+960=1920)
        (F4,QTR,82),(E4,EIGHTH,80),(C4,EIGHTH,78),(A3,HALF,80),
        # Bar 7 (G7): rest-B-D-F-D-B (240+240+240+240+480+480=1920)
        (0,EIGHTH,0),(B3,EIGHTH,80),(D4,EIGHTH,82),(F4,EIGHTH,85),(D4,QTR,82),(B3,QTR,78),
        # Bar 8 (C):  C-G  (960+960=1920) — breath
        (C4,HALF,85),(G4,HALF,82),
        # B strain — slightly higher, more energetic
        # Bar 9 (F):  rest-A-C-A-F-A (240+240+480+240+240+480=1920)
        (0,EIGHTH,0),(A4,EIGHTH,85),(C5,QTR,88),(A4,EIGHTH,85),(F4,EIGHTH,82),(A4,QTR,85),
        # Bar 10 (C7): G-Bb-A-G-E (480+240+240+480+480=1920)
        (G4,QTR,82),(Bb4,EIGHTH,80),(A4,EIGHTH,78),(G4,QTR,82),(E4,QTR,75),
        # Bar 11 (F):  rest-A-C-A-G-F (240+240+480+240+240+480=1920)
        (0,EIGHTH,0),(A4,EIGHTH,82),(C5,QTR,88),(A4,EIGHTH,85),(G4,EIGHTH,80),(F4,QTR,82),
        # Bar 12 (Dm): D-F-A (960+480+480=1920)
        (D4,HALF,80),(F4,QTR,78),(A4,QTR,85),
        # Bar 13 (G7): rest-D-G-B-G-D (240+240+240+240+480+480=1920)
        (0,EIGHTH,0),(D4,EIGHTH,82),(G4,EIGHTH,85),(B4,EIGHTH,88),(G4,QTR,85),(D4,QTR,82),
        # Bar 14 (C):  C-E-G-E (480+480+480+480=1920)
        (C4,QTR,85),(E4,QTR,88),(G4,QTR,90),(E4,QTR,85),
        # Bar 15 (G7): D-F-D-B (480+480+480+480=1920)
        (D4,QTR,82),(F4,QTR,85),(D4,QTR,80),(B3,QTR,78),
        # Bar 16 (C):  final C (whole)
        (C4,WHOLE,92),
    ]

    drums = [bar_ragtime_hat()] * 16
    return bpm, bass, pad, melody, drums


# ── Catalog ────────────────────────────────────────────────────────────────────

# ── Composition 19: Neon Drift (Synthwave) ────────────────────────────────────

def comp_neon_drift():
    bpm = 128
    # A minor (no flats/sharps): Am-C-F-G repeating
    A1,E2,A2 = _note('A',1),_note('E',2),_note('A',2)
    C2,G2,C3 = _note('C',2),_note('G',2),_note('C',3)
    F1,F2,A2b = _note('F',1),_note('F',2),_note('A',2)
    G1,B2,D3 = _note('G',1),_note('B',2),_note('D',3)
    A3,C4,E4 = _note('A',3),_note('C',4),_note('E',4)
    C3b,E3,G3 = _note('C',3),_note('E',3),_note('G',3)
    F3,A3b = _note('F',3),_note('A',3)
    G3b,B3 = _note('G',3),_note('B',3)
    D4,E4b,F4,G4,A4,B4,C5,D5 = (_note('D',4),_note('E',4),_note('F',4),_note('G',4),
                                   _note('A',4),_note('B',4),_note('C',5),_note('D',5))

    # Arpeggio bass: 8 eighth notes per bar (2 cycles of 4-note arp)
    def arp(a,b,c,d,v=82): return [(a,EIGHTH,v),(b,EIGHTH,v-6),(c,EIGHTH,v-4),(d,EIGHTH,v-8)] * 2

    bass = (
        arp(A1,C2,E2,A2)+arp(C2,E2,G2,C3)+arp(F1,A2b,C2,F2)+arp(G1,B2,D3,G2) +
        arp(A1,C2,E2,A2,85)+arp(C2,E2,G2,C3,82)+arp(F1,A2b,C2,F2,82)+arp(G1,B2,D3,G2,85) +
        arp(A1,C2,E2,A2,88)+arp(F1,A2b,C2,F2,85)+arp(G1,B2,D3,G2,88)+[(A1,WHOLE,85)] +
        arp(A1,C2,E2,A2,90)+arp(F1,A2b,C2,F2,88)+arp(G1,B2,D3,G2,92)+[(A1,WHOLE,95)]
    )

    Am,Cmaj,Fmaj,Gmaj = [A3,C4,E4],[C3b,E3,G3],[F3,A3b,C4],[G3b,B3,D4]

    def pad_bar(ch, v1=72, v2=66):
        return [(ch, HALF, v1), (ch, HALF, v2)]

    pad_flat = (
        pad_bar(Am)+pad_bar(Cmaj,70,64)+pad_bar(Fmaj,70,64)+pad_bar(Gmaj) +
        pad_bar(Am)+pad_bar(Cmaj,70,64)+pad_bar(Fmaj,70,64)+pad_bar(Gmaj) +
        pad_bar(Am,76,70)+pad_bar(Fmaj,74,68)+pad_bar(Gmaj,76,70)+[(Am,WHOLE,70)] +
        pad_bar(Am,80,74)+pad_bar(Fmaj,78,72)+pad_bar(Gmaj,82,76)+[(Am,WHOLE,78)]
    )

    melody = [
        # A section (bars 1-8): Am-C-F-G × 2
        (A4,DOTTED_QTR,80),(A4,EIGHTH,76),(G4,QTR,78),(E4,QTR,74),           # bar 1 Am
        (G4,QTR,78),(E4,QTR,76),(G4,QTR,80),(E4,QTR,78),                     # bar 2 C
        (F4,DOTTED_QTR,78),(F4,EIGHTH,74),(E4,QTR,76),(D4,QTR,72),           # bar 3 F
        (D4,QTR,76),(E4,QTR,78),(G4,HALF,80),                                 # bar 4 G
        (A4,EIGHTH,84),(A4,EIGHTH,80),(G4,QTR,78),(E4,DOTTED_QTR,82),(F4,EIGHTH,78),  # bar 5 Am
        (G4,QTR,80),(A4,QTR,82),(G4,QTR,80),(E4,QTR,78),                     # bar 6 C
        (F4,DOTTED_QTR,80),(G4,EIGHTH,78),(A4,QTR,82),(F4,QTR,78),           # bar 7 F
        (E4,HALF,82),(D4,QTR,80),(E4,QTR,82),                                 # bar 8 G
        # B section (bars 9-16): Am-F-G-Am × 2
        (A4,EIGHTH,86),(C5,EIGHTH,84),(B4,QTR,86),(A4,DOTTED_QTR,88),(G4,EIGHTH,84),  # bar 9 Am
        (F4,QTR,84),(A4,QTR,86),(C5,QTR,88),(A4,QTR,84),                     # bar 10 F
        (D5,DOTTED_QTR,86),(C5,EIGHTH,84),(B4,HALF,88),                       # bar 11 G
        (A4,WHOLE,84),                                                         # bar 12 Am (hold)
        (A4,EIGHTH,88),(B4,EIGHTH,90),(C5,EIGHTH,92),(B4,EIGHTH,88),(A4,QTR,90),(G4,QTR,86),   # bar 13
        (F4,QTR,88),(A4,QTR,90),(C5,QTR,92),(A4,QTR,88),                     # bar 14 F
        (B4,DOTTED_QTR,90),(C5,EIGHTH,88),(D5,HALF,92),                       # bar 15 G
        (A4,WHOLE,95),                                                         # bar 16 Am
    ]

    def bar_sw():
        return [(0,BD,90),(0,CHH,55),(EIGHTH,CHH,48),(QTR,SD,82),(QTR,BD,86),(QTR,CHH,55),
                (QTR+EIGHTH,CHH,48),(HALF,BD,90),(HALF,CHH,55),(HALF+EIGHTH,CHH,48),
                (QTR*3,SD,82),(QTR*3,BD,86),(QTR*3,CHH,55),(QTR*3+EIGHTH,CHH,48)]
    def bar_sw_crash():
        return [(0,CRASH,78)] + bar_sw()

    drums = ([bar_sw_crash()]+[bar_sw()]*3 + [bar_sw_crash()]+[bar_sw()]*3 +
             [bar_sw_crash()]+[bar_sw()]*3 + [bar_sw_crash()]+[bar_sw()]*3)
    return bpm, bass, pad_flat, melody, drums


# ── Composition 18: Crimson Tango ────────────────────────────────────────────

def comp_crimson_tango():
    bpm = 116
    # D minor (1 flat: Bb)
    D1,A1,G1,C2,D2,E2 = _note('D',1),_note('A',1),_note('G',1),_note('C',2),_note('D',2),_note('E',2)
    G2,D3,F3,A3 = _note('G',2),_note('D',3),_note('F',3),_note('A',3)
    C3,E3,G3 = _note('C',3),_note('E',3),_note('G',3)
    Bb2,Cs3,A2 = _note('Bb',2),_note('C#',3),_note('A',2)
    D4,F4,G4,A4,Cs4,E4,Bb4,C5,D5 = (_note('D',4),_note('F',4),_note('G',4),_note('A',4),
                                      _note('C#',4),_note('E',4),_note('Bb',4),_note('C',5),_note('D',5))
    Dm,Cm,Gm,Am7 = [D3,F3,A3],[C3,E3,G3],[G2,Bb2,D3],[A2,Cs3,E3]

    def hab(r, h, vel=88):
        return [(r,DOTTED_QTR,vel),(h,EIGHTH,int(vel*0.80)),(r,HALF,int(vel*0.94))]

    def pad_stab(chord, v=74):
        # habanera-aligned stabs: silence(DOTTED_QTR) + stab(EIGHTH) + silence(QTR) + stab(EIGHTH) + silence(DOTTED_QTR-EIGHTH)
        return [(chord,DOTTED_QTR,0),(chord,EIGHTH,v),(chord,QTR,0),(chord,EIGHTH,int(v*0.88)),(chord,QTR-EIGHTH,0)]

    bass = (hab(D1,A1)+hab(C2,G2)+hab(G1,D2)+hab(A1,E2) +
            hab(D1,A1)+hab(C2,G2)+hab(G1,D2)+[(D1,WHOLE,90)] +
            hab(D1,A1,92)+hab(G1,D2,88)+hab(A1,E2,90)+[(D1,WHOLE,85)] +
            hab(D1,A1,95)+hab(G1,D2,92)+hab(A1,E2,95)+[(D1,WHOLE,105)])

    pad = (pad_stab(Dm)+pad_stab(Cm)+pad_stab(Gm)+pad_stab(Am7) +
           pad_stab(Dm)+pad_stab(Cm)+pad_stab(Gm,70)+[(Dm,WHOLE,65)] +
           pad_stab(Dm,78)+pad_stab(Gm,75)+pad_stab(Am7,78)+[(Dm,WHOLE,62)] +
           pad_stab(Dm,82)+pad_stab(Gm,80)+pad_stab(Am7,85)+[(Dm,WHOLE,80)])

    melody = [
        # A section (bars 1-8): i-VII-iv-V × 2
        (D4,QTR,80),(F4,QTR,83),(A4,QTR,86),(F4,QTR,80),          # bar 1 Dm
        (E4,QTR,78),(G4,QTR,80),(C5,QTR,82),(G4,QTR,76),           # bar 2 C
        (D4,QTR,78),(Bb4,QTR,80),(G4,QTR,82),(D4,QTR,75),          # bar 3 Gm
        (Cs4,QTR,80),(E4,QTR,83),(A4,QTR,86),(Cs4,QTR,78),         # bar 4 A
        (A4,DOTTED_QTR,85),(G4,EIGHTH,80),(F4,HALF,82),             # bar 5 Dm
        (G4,DOTTED_QTR,82),(F4,EIGHTH,78),(E4,HALF,80),             # bar 6 C
        (F4,DOTTED_QTR,80),(D4,EIGHTH,76),(Bb4,HALF,82),            # bar 7 Gm
        (E4,DOTTED_QTR,88),(Cs4,EIGHTH,85),(D4,HALF,90),            # bar 8 A→Dm
        # B section (bars 9-16): i-iv-V-i × 2 (louder, more intense)
        (D5,QTR,88),(C5,EIGHTH,83),(Bb4,EIGHTH,80),(A4,HALF,85),    # bar 9 Dm
        (Bb4,QTR,85),(G4,QTR,82),(F4,QTR,80),(D4,QTR,78),          # bar 10 Gm
        (A4,DOTTED_QTR,88),(G4,EIGHTH,85),(E4,HALF,82),             # bar 11 A
        (D4,WHOLE,85),                                               # bar 12 Dm (breath)
        (F4,EIGHTH,88),(G4,EIGHTH,90),(A4,QTR,92),(A4,DOTTED_QTR,95),(G4,EIGHTH,88),  # bar 13
        (Bb4,QTR,90),(A4,QTR,88),(G4,QTR,85),(F4,QTR,82),          # bar 14 Gm
        (E4,HALF,90),(Cs4,QTR,92),(E4,QTR,88),                      # bar 15 A
        (D4,WHOLE,100),                                              # bar 16 Dm (final)
    ]

    def bar_tango():
        return [(0,CRASH,72),(0,BD,92),(DOTTED_QTR,CHH,52),(HALF,BD,82),(HALF,SD,78)]
    def bar_tango_inner():
        return [(0,BD,88),(DOTTED_QTR,CHH,50),(HALF,BD,78),(HALF,SD,72),(QTR*3,CHH,45)]
    def bar_tango_climax():
        return [(0,BD,96),(0,CRASH,78),(QTR,CHH,55),(DOTTED_QTR,CHH,58),(HALF,BD,90),(HALF,SD,85),(QTR*3,SD,80)]

    drums = ([bar_tango()]+[bar_tango_inner()]*6+[bar_tango()] +
             [bar_tango()]+[bar_tango_inner()]*3+[bar_tango_climax()]*4)
    return bpm, bass, pad, melody, drums


# ── Composition 20: Delta Blues ─────────────────────────────────────────────

def comp_delta_blues():
    bpm = 76
    # E blues (E minor: 1 sharp F#) — uses minor 3rd (G natural) and flat 7th (D)
    E1,A1,B1 = _note('E',1), _note('A',1), _note('B',1)
    D2,E2,Fs2,G2,A2,B2 = (_note('D',2),_note('E',2),_note('F#',2),
                           _note('G',2),_note('A',2),_note('B',2))
    E3,G3,A3,Bb3,B3 = _note('E',3),_note('G',3),_note('A',3),_note('Bb',3),_note('B',3)
    Cs4,D4,Ds4,E4,Fs4,G4,A4,Bb4,B4 = (
        _note('C#',4),_note('D',4),_note('D#',4),_note('E',4),_note('F#',4),
        _note('G',4),_note('A',4),_note('Bb',4),_note('B',4)
    )
    D5,E5 = _note('D',5), _note('E',5)

    E7 = [E3, G3, B3, D4]      # I7  (G natural = blues minor 3rd)
    A7 = [A3, Cs4, E4, G4]     # IV7
    B7 = [B3, Ds4, Fs4, A4]    # V7

    def walk(r, a, b, c, v=80):
        return [(r,QTR,v),(a,QTR,v-6),(b,QTR,v-4),(c,QTR,v-2)]

    bass = (
        walk(E1,G2,A2,B2) + walk(E1,A1,G2,B2) +
        walk(E1,G2,A2,B2) + walk(E1,A1,B1,E2,82) +
        walk(A1,G2,E2,B1) + walk(A1,E2,B1,G2,78) +
        walk(E1,G2,A2,B2) + walk(E1,E2,B1,A1,78) +
        walk(B1,B2,A2,G2,85) +
        walk(A1,A2,G2,E2) +
        walk(E1,G2,A2,B2) + walk(E1,E1,E2,E2,76) +
        walk(B1,B2,A2,Fs2,88) +
        walk(A1,G2,E2,D2,84) +
        walk(E1,G2,A2,B2,90) +
        [(E1,WHOLE,92)]
    )

    def chord_bar(ch, v1=68, v2=62):
        return [(ch,HALF,v1),(ch,HALF,v2)]

    pad = (
        chord_bar(E7)*4 +
        chord_bar(A7)+chord_bar(A7) +
        chord_bar(E7)*2 +
        chord_bar(B7,72,66)+chord_bar(A7) +
        chord_bar(E7)*2 +
        chord_bar(B7,75,70)+chord_bar(A7,72,66) +
        chord_bar(E7,80,74)+chord_bar(E7,82,76)
    )

    melody = [
        # A section (bars 1-4): I7 E7 — call and response
        (E5,QTR,86),(D5,QTR,82),(B4,HALF,84),                          # bar 1 call
        (G4,DOTTED_QTR,78),(A4,EIGHTH,74),(B4,HALF,80),                # bar 2 response
        (E5,EIGHTH,88),(D5,EIGHTH,84),(B4,QTR,82),(G4,HALF,80),        # bar 3 run down
        (A4,QTR,82),(Bb4,QTR,84),(B4,HALF,86),                         # bar 4 blue-note push
        # Bars 5-6: IV7 A7
        (E5,QTR,84),(D5,QTR,80),(A4,HALF,82),                          # bar 5 A7 territory
        (A4,EIGHTH,80),(B4,EIGHTH,82),(A4,QTR,78),(E4,HALF,76),        # bar 6 settle back
        # Bars 7-8: I7 E7
        (B4,DOTTED_QTR,82),(A4,EIGHTH,78),(G4,HALF,80),                # bar 7 return
        (E4,HALF,80),(G4,HALF,78),                                      # bar 8 breathe
        # Bars 9-12: V7-IV7-I7-I7
        (D5,QTR,86),(B4,QTR,84),(Fs4,HALF,88),                         # bar 9 B7 (F# blue note)
        (E4,EIGHTH,84),(G4,EIGHTH,82),(A4,QTR,86),(B4,HALF,88),        # bar 10 A7
        (G4,DOTTED_QTR,86),(E4,EIGHTH,82),(B3,HALF,84),                # bar 11 low resolution
        (E4,WHOLE,82),                                                   # bar 12 held resolve
        # Bars 13-16: climax push and final
        (B4,QTR,90),(D5,QTR,92),(B4,QTR,90),(G4,QTR,88),              # bar 13 B7 climb
        (A4,DOTTED_QTR,88),(G4,EIGHTH,84),(E4,HALF,86),                # bar 14 A7 answer
        (G4,EIGHTH,90),(A4,EIGHTH,92),(Bb4,EIGHTH,94),(B4,EIGHTH,92),(G4,HALF,88),  # bar 15 chromatic run
        (E4,HALF,92),(E4,HALF,88),                                      # bar 16 final
    ]

    def bar_blues():
        sw = (QTR*2)//3  # 320 ticks — swing triplet offset
        return [
            (0,BD,90),(0,CHH,52),(sw,CHH,38),
            (QTR,SD,72),(QTR,CHH,50),(QTR+sw,CHH,36),
            (HALF,BD,84),(HALF,CHH,52),(HALF+sw,CHH,38),
            (QTR*3,SD,74),(QTR*3,CHH,50),(QTR*3+sw,CHH,36),
        ]
    def bar_blues_crash():
        return [(0,CRASH,76)] + bar_blues()

    drums = ([bar_blues_crash()]+[bar_blues()]*3 +
             [bar_blues_crash()]+[bar_blues()]+[bar_blues_crash()]+[bar_blues()] +
             [bar_blues_crash()]+[bar_blues()]+[bar_blues_crash()]+[bar_blues()] +
             [bar_blues_crash()]+[bar_blues()]*3)
    return bpm, bass, pad, melody, drums


# ── Composition 21: Rio Breeze (Bossa Nova) ──────────────────────────────────

def comp_bossa_nova():
    bpm = 130
    # D major (2 sharps: F#, C#)
    D1,A1,G1,B1 = _note('D',1), _note('A',1), _note('G',1), _note('B',1)
    D2,E2,Fs2,G2,A2,B2 = (_note('D',2),_note('E',2),_note('F#',2),
                           _note('G',2),_note('A',2),_note('B',2))
    D3,Fs3,A3,C3 = _note('D',3),_note('F#',3),_note('A',3),_note('C',3)
    E3,G3,B3,Cs4 = _note('E',3),_note('G',3),_note('B',3),_note('C#',4)
    D4,E4,Fs4,G4,A4,B4,Cs5 = (_note('D',4),_note('E',4),_note('F#',4),_note('G',4),
                               _note('A',4),_note('B',4),_note('C#',5))
    D5,E5,Fs5 = _note('D',5),_note('E',5),_note('F#',5)
    Gs4,Bf4 = _note('G#',4), _note('Bb',4)  # chromatic passing tones

    Dmaj7 = [D3, Fs3, A3, Cs4]    # I maj7
    G7    = [G3, B3, D4, E4]      # IV dominant (G7 = G,B,D,F but use E for texture)
    A7    = [A3, Cs4, E4, G4]     # V7
    Bm7   = [B3, D4, Fs4, A4]     # vi m7

    # Bossa nova bass: root on 1, 5th on 3+, syncopated feels
    def bass_d(v=80):   # bar on Dmaj7
        return [(D1,QTR,v),(D1,EIGHTH,v-6),(A1,EIGHTH,v-4),(D2,QTR,v-8),(A1,QTR,v-6)]
    def bass_g(v=76):   # bar on G7
        return [(G1,QTR,v),(G1,EIGHTH,v-6),(D2,EIGHTH,v-4),(G2,QTR,v-8),(D2,QTR,v-6)]
    def bass_a(v=80):   # bar on A7
        return [(A1,QTR,v),(A1,EIGHTH,v-6),(E2,EIGHTH,v-4),(A2,QTR,v-8),(E2,QTR,v-6)]
    def bass_b(v=76):   # bar on Bm7
        return [(B1,QTR,v),(B1,EIGHTH,v-6),(Fs2,EIGHTH,v-4),(B2,QTR,v-8),(Fs2,QTR,v-6)]

    # Verify bar_d total: QTR+EIGHTH+EIGHTH+QTR+QTR = 480+240+240+480+480 = 1920 ✓
    bass = (
        bass_d()+bass_g()+bass_a()+bass_d() +
        bass_d(78)+bass_g(74)+bass_a(78)+bass_b(74) +
        bass_d(82)+bass_g(78)+bass_a(82)+bass_d(80) +
        bass_d(86)+bass_g(82)+bass_a(88)+[(D1,WHOLE,90)]
    )

    # Chord stabs — bossa feel: stab on 2nd and 4th 8th (typical strumming position)
    # Simplified: one chord per bar as WHOLE note (pad plays sustained)
    def pad_bar(ch, v=68): return [(ch, WHOLE, v)]

    pad = (
        pad_bar(Dmaj7)+pad_bar(G7,64)+pad_bar(A7)+pad_bar(Dmaj7) +
        pad_bar(Dmaj7)+pad_bar(G7,64)+pad_bar(A7)+pad_bar(Bm7,64) +
        pad_bar(Dmaj7,72)+pad_bar(G7,68)+pad_bar(A7,72)+pad_bar(Dmaj7,70) +
        pad_bar(Dmaj7,76)+pad_bar(G7,72)+pad_bar(A7,78)+pad_bar(Dmaj7,80)
    )

    melody = [
        # A section (bars 1-8): Dmaj7-G7-A7-Dmaj7 × 2
        (Fs5,DOTTED_QTR,82),(E5,EIGHTH,78),(D5,HALF,80),               # bar 1 Dmaj7
        (B4,QTR,78),(A4,QTR,76),(G4,QTR,74),(A4,QTR,76),              # bar 2 G7
        (Cs5,DOTTED_QTR,82),(B4,EIGHTH,78),(A4,HALF,80),               # bar 3 A7
        (Fs4,HALF,78),(A4,HALF,82),                                     # bar 4 Dmaj7
        (D5,EIGHTH,84),(Cs5,EIGHTH,82),(B4,QTR,80),(A4,HALF,82),       # bar 5 Dmaj7
        (B4,DOTTED_QTR,80),(A4,EIGHTH,76),(G4,HALF,78),                # bar 6 G7
        (Gs4,EIGHTH,80),(A4,EIGHTH,82),(Cs5,QTR,84),(E5,HALF,86),      # bar 7 A7 (chromatic)
        (D5,WHOLE,84),                                                   # bar 8 Dmaj7
        # B section (bars 9-16): build intensity
        (A4,EIGHTH,86),(B4,EIGHTH,88),(D5,QTR,90),(Fs5,HALF,92),       # bar 9 Dmaj7
        (E5,DOTTED_QTR,88),(D5,EIGHTH,84),(B4,HALF,86),                # bar 10 G7
        (Cs5,QTR,88),(E5,QTR,90),(A4,HALF,86),                         # bar 11 A7
        (D5,WHOLE,86),                                                   # bar 12 Dmaj7
        (Fs5,EIGHTH,90),(E5,EIGHTH,88),(D5,EIGHTH,86),(Cs5,EIGHTH,84),(B4,HALF,88), # bar 13
        (A4,DOTTED_QTR,88),(B4,EIGHTH,90),(D5,HALF,92),                # bar 14 G7
        (Cs5,EIGHTH,92),(E5,EIGHTH,94),(A4,QTR,90),(Cs5,HALF,92),      # bar 15 A7
        (D5,WHOLE,96),                                                   # bar 16 Dmaj7
    ]

    def bar_bossa():
        # Light clave-feel: soft kick on 1, rim on 2+3, hi-hat 8ths
        return [
            (0,BD,78),(0,CHH,48),
            (EIGHTH,CHH,38),(QTR,CHH,48),(QTR,SD,58),
            (QTR+EIGHTH,CHH,38),(HALF,BD,70),(HALF,CHH,48),
            (HALF+EIGHTH,CHH,38),(QTR*3,SD,62),(QTR*3,CHH,48),
            (QTR*3+EIGHTH,CHH,38),
        ]
    def bar_bossa_crash():
        return [(0,CRASH,65)] + bar_bossa()

    drums = ([bar_bossa_crash()]+[bar_bossa()]*3 +
             [bar_bossa_crash()]+[bar_bossa()]*3 +
             [bar_bossa_crash()]+[bar_bossa()]*3 +
             [bar_bossa_crash()]+[bar_bossa()]*3)
    return bpm, bass, pad, melody, drums


# ── Composition 22: Flamenco ──────────────────────────────────────────────────

def comp_flamenco():
    bpm = 142
    A1, E1, F1, G1 = _note('A',1), _note('E',1), _note('F',1), _note('G',1)
    B1, C2, D2, E2, F2, G2, A2, B2 = (
        _note('B',1), _note('C',2), _note('D',2), _note('E',2),
        _note('F',2), _note('G',2), _note('A',2), _note('B',2)
    )
    A3, B3, C3, D3, E3, F3, G3, Gs3 = (
        _note('A',3), _note('B',3), _note('C',3), _note('D',3),
        _note('E',3), _note('F',3), _note('G',3), _note('G#',3)
    )
    A4, B4, C4, D4, E4, F4, G4, Gs4 = (
        _note('A',4), _note('B',4), _note('C',4), _note('D',4),
        _note('E',4), _note('F',4), _note('G',4), _note('G#',4)
    )
    C5, D5, E5, F5 = _note('C',5), _note('D',5), _note('E',5), _note('F',5)

    Amin = [A3, C4, E4]
    Gmaj = [G3, B3, D4]
    Fmaj = [F3, A3, C4]
    E7   = [E3, Gs3, B3, D4]   # Phrygian dominant — signature flamenco chord

    def bass_am(v=78): return [(A1,HALF,v),(E2,HALF,v-6)]
    def bass_g(v=76):  return [(G1,HALF,v),(D2,HALF,v-6)]
    def bass_f(v=74):  return [(F1,HALF,v),(C2,HALF,v-6)]
    def bass_e(v=82):  return [(E1,HALF,v),(B1,HALF,v-6)]

    bass = (bass_am() + bass_g() + bass_f() + bass_e()) * 4

    def pad_bar(ch, v=65): return [(ch, WHOLE, v)]

    pad = (
        pad_bar(Amin,65) + pad_bar(Gmaj,62) + pad_bar(Fmaj,60) + pad_bar(E7,68) +
        pad_bar(Amin,67) + pad_bar(Gmaj,64) + pad_bar(Fmaj,62) + pad_bar(E7,70) +
        pad_bar(Amin,70) + pad_bar(Gmaj,67) + pad_bar(Fmaj,64) + pad_bar(E7,74) +
        pad_bar(Amin,68) + pad_bar(Gmaj,65) + pad_bar(Fmaj,62) + pad_bar(E7,76)
    )

    melody = [
        # Cycle 1 — statement
        (A4,QTR,72),(B4,QTR,68),(C5,HALF,74),                           # bar 1  Am
        (D5,QTR,76),(C5,QTR,70),(B4,HALF,72),                           # bar 2  G
        (A4,QTR,74),(Gs4,QTR,76),(A4,QTR,74),(F4,QTR,70),               # bar 3  F (G# ornament)
        (E4,WHOLE,78),                                                   # bar 4  E7
        # Cycle 2 — tension rising
        (C5,QTR,76),(D5,QTR,74),(E5,HALF,78),                           # bar 5  Am
        (D5,DOTTED_QTR,80),(C5,EIGHTH,74),(B4,HALF,76),                  # bar 6  G
        (A4,QTR,76),(B4,QTR,78),(C5,QTR,76),(A4,QTR,72),                # bar 7  F
        (Gs4,HALF,82),(E4,HALF,78),                                      # bar 8  E7
        # Cycle 3 — climax
        (E5,QTR,84),(D5,QTR,82),(C5,HALF,80),                           # bar 9  Am
        (B4,QTR,82),(D5,QTR,84),(B4,HALF,80),                           # bar 10 G
        (A4,EIGHTH,82),(B4,EIGHTH,84),(C5,EIGHTH,86),(A4,EIGHTH,82),(F4,HALF,80), # bar 11 F
        (Gs4,DOTTED_QTR,86),(F4,EIGHTH,80),(E4,HALF,84),                 # bar 12 E7
        # Cycle 4 — resolution
        (E5,HALF,82),(C5,HALF,78),                                       # bar 13 Am
        (D5,QTR,80),(B4,QTR,76),(G4,HALF,74),                           # bar 14 G  (G natural in G major chord)
        (A4,QTR,78),(Gs4,QTR,80),(F4,HALF,76),                          # bar 15 F
        (E4,WHOLE,80),                                                   # bar 16 E7
    ]

    def bar_flamenco():
        return [
            (0,BD,90),(0,CHH,52),(EIGHTH,CHH,42),
            (QTR,SD,70),(QTR,CHH,50),(QTR+EIGHTH,CHH,42),
            (HALF,BD,84),(HALF,CHH,52),(HALF+EIGHTH,CHH,45),
            (HALF+EIGHTH,BD,68),
            (QTR*3,SD,74),(QTR*3,CHH,50),(QTR*3+EIGHTH,CHH,42),
        ]
    def bar_flamenco_crash():
        return [(0,CRASH,72)] + bar_flamenco()

    drums = (
        [bar_flamenco_crash()] + [bar_flamenco()] * 3 +
        [bar_flamenco_crash()] + [bar_flamenco()] * 3 +
        [bar_flamenco_crash()] + [bar_flamenco()] * 3 +
        [bar_flamenco_crash()] + [bar_flamenco()] * 3
    )
    return bpm, bass, pad, melody, drums


# ── Composition 23: Baroque Minuet ────────────────────────────────────────────

def comp_baroque_minuet():
    bpm = 116
    BAR = QTR * 3  # 3/4 bar = 1440 ticks

    G1 = _note('G', 1)
    C2, D2, E2, G2, A2 = (
        _note('C', 2), _note('D', 2), _note('E', 2), _note('G', 2), _note('A', 2)
    )
    C3, D3, E3, Fs3, G3, A3, B3 = (
        _note('C', 3), _note('D', 3), _note('E', 3), _note('F#', 3),
        _note('G', 3), _note('A', 3), _note('B', 3)
    )
    C4, D4, E4, Fs4, G4, A4, B4 = (
        _note('C', 4), _note('D', 4), _note('E', 4), _note('F#', 4),
        _note('G', 4), _note('A', 4), _note('B', 4)
    )
    C5, D5, E5, Fs5, G5 = (
        _note('C', 5), _note('D', 5), _note('E', 5), _note('F#', 5), _note('G', 5)
    )

    Gmaj = [G3, B3, D4]
    Dmaj = [D3, Fs3, A3]
    Cmaj = [C3, E3, G3]
    Emin = [E3, G3, B3]
    Amin = [A2, C3, E3]

    def bass_bar(root, t3, t5, v=72):
        return [(root, QTR, v), (t3, QTR, v - 14), (t5, QTR, v - 12)]

    # Section A: G D G C | G D D G
    # Section B: Em Am D G | Em C D G
    bass = (
        bass_bar(G1, B3, D3) + bass_bar(D2, Fs3, A3) +
        bass_bar(G1, B3, D3) + bass_bar(C2, E3, G3) +
        bass_bar(G1, B3, D3) + bass_bar(D2, Fs3, A3) +
        bass_bar(D2, A3, Fs3) + bass_bar(G1, D3, B3) +
        bass_bar(E2, G3, B3) + bass_bar(A2, C3, E3) +
        bass_bar(D2, Fs3, A3) + bass_bar(G1, B3, D3) +
        bass_bar(E2, G3, B3) + bass_bar(C2, E3, G3) +
        bass_bar(D2, Fs3, A3) + bass_bar(G1, D3, B3)
    )

    def pad_bar(ch, v=62):
        return [(ch, BAR, v)]

    pad = (
        pad_bar(Gmaj) + pad_bar(Dmaj) + pad_bar(Gmaj) + pad_bar(Cmaj) +
        pad_bar(Gmaj) + pad_bar(Dmaj) + pad_bar(Dmaj) + pad_bar(Gmaj) +
        pad_bar(Emin) + pad_bar(Amin) + pad_bar(Dmaj) + pad_bar(Gmaj) +
        pad_bar(Emin) + pad_bar(Cmaj) + pad_bar(Dmaj) + pad_bar(Gmaj)
    )

    GR = SIXTEENTH  # 120 ticks — grace note (acciaccatura)

    melody = [
        # Section A
        (D5, QTR, 76), (B4, QTR, 68), (G4, QTR, 65),           # bar 1  G
        (A4, QTR, 72), (Fs4, QTR, 65), (D4, QTR, 62),           # bar 2  D
        (G4, QTR, 70), (A4, QTR, 68), (B4, QTR, 72),            # bar 3  G
        (C5, DOTTED_QTR, 76), (B4, EIGHTH, 68), (A4, QTR, 65),  # bar 4  C  720+240+480=1440
        (B4, QTR, 72), (C5, QTR, 68), (D5, QTR, 74),            # bar 5  G
        (E5, QTR, 78), (D5, QTR, 72), (A4, QTR, 68),            # bar 6  D
        (Fs4, QTR, 74), (G4, QTR, 70), (A4, QTR, 72),           # bar 7  D
        (G4, BAR, 76),                                            # bar 8  G  dotted half
        # Section B
        (E5, QTR, 78), (D5, QTR, 72), (B4, QTR, 68),            # bar 9  Em
        (C5, QTR, 74), (B4, QTR, 68), (A4, QTR, 65),            # bar 10 Am
        (A4, QTR, 72), (B4, QTR, 70), (D5, QTR, 76),            # bar 11 D
        (G4, QTR, 74), (A4, QTR, 70), (B4, QTR, 72),            # bar 12 G
        (B4, QTR, 76), (G4, QTR, 68), (E4, QTR, 65),            # bar 13 Em
        (A4, QTR, 72), (B4, QTR, 74), (C5, QTR, 78),            # bar 14 C
        (D5, DOTTED_QTR, 82), (C5, EIGHTH, 74), (B4, QTR, 78),  # bar 15 D  720+240+480=1440
        (G4, BAR, 76),                                            # bar 16 G  dotted half
        # Section A' — ornamented repeat with grace notes (mordents) on key beats
        # bar 17 G: mordent E5→D5 on beat 1
        (E5, GR, 70, GR), (D5, QTR-GR, 78), (B4, QTR, 70), (G4, QTR, 66),  # 120+360+480+480=1440
        # bar 18 D: grace note B4→A4 on beat 1
        (B4, GR, 66, GR), (A4, QTR-GR, 74), (Fs4, QTR, 67), (D4, QTR, 63),  # 1440
        (G4, QTR, 72), (A4, QTR, 70), (B4, QTR, 74),            # bar 19 G  1440
        # bar 20 C: ornament D5→C5 + dotted rhythm
        (D5, GR, 72, GR), (C5, DOTTED_QTR-GR, 78), (B4, EIGHTH, 70), (A4, QTR, 67),  # 120+600+240+480=1440
        (B4, QTR, 76), (C5, QTR, 72), (D5, QTR, 78),            # bar 21 G  1440
        (E5, QTR, 82), (D5, QTR, 76), (A4, QTR, 72),            # bar 22 D  1440
        # bar 23 D: grace note G4→Fs4 on beat 1
        (G4, GR, 70, GR), (Fs4, QTR-GR, 78), (G4, QTR, 74), (A4, QTR, 76),  # 120+360+480+480=1440
        (G4, BAR, 82),                                            # bar 24 G  final cadence
    ]

    # Extend bass and pad to 24 bars (A' mirrors Section A harmonically)
    bass = (
        bass_bar(G1, B3, D3) + bass_bar(D2, Fs3, A3) +
        bass_bar(G1, B3, D3) + bass_bar(C2, E3, G3) +
        bass_bar(G1, B3, D3) + bass_bar(D2, Fs3, A3) +
        bass_bar(D2, A3, Fs3) + bass_bar(G1, D3, B3) +
        bass_bar(E2, G3, B3) + bass_bar(A2, C3, E3) +
        bass_bar(D2, Fs3, A3) + bass_bar(G1, B3, D3) +
        bass_bar(E2, G3, B3) + bass_bar(C2, E3, G3) +
        bass_bar(D2, Fs3, A3) + bass_bar(G1, D3, B3) +
        # A' (bars 17-24) — same harmony as A, slightly louder
        bass_bar(G1, B3, D3, v=78) + bass_bar(D2, Fs3, A3, v=76) +
        bass_bar(G1, B3, D3, v=76) + bass_bar(C2, E3, G3, v=78) +
        bass_bar(G1, B3, D3, v=78) + bass_bar(D2, Fs3, A3, v=76) +
        bass_bar(D2, A3, Fs3, v=78) + bass_bar(G1, D3, B3, v=82)
    )

    pad = (
        pad_bar(Gmaj) + pad_bar(Dmaj) + pad_bar(Gmaj) + pad_bar(Cmaj) +
        pad_bar(Gmaj) + pad_bar(Dmaj) + pad_bar(Dmaj) + pad_bar(Gmaj) +
        pad_bar(Emin) + pad_bar(Amin) + pad_bar(Dmaj) + pad_bar(Gmaj) +
        pad_bar(Emin) + pad_bar(Cmaj) + pad_bar(Dmaj) + pad_bar(Gmaj) +
        # A' pad (bars 17-24) — crescendo toward final cadence
        pad_bar(Gmaj, v=66) + pad_bar(Dmaj, v=64) +
        pad_bar(Gmaj, v=68) + pad_bar(Cmaj, v=70) +
        pad_bar(Gmaj, v=72) + pad_bar(Dmaj, v=70) +
        pad_bar(Dmaj, v=74) + pad_bar(Gmaj, v=78)
    )

    drums = (
        [bar_waltz_crash()] + [bar_waltz()] * 3 +
        [bar_waltz_crash()] + [bar_waltz()] * 3 +
        [bar_waltz_crash()] + [bar_waltz()] * 3 +
        [bar_waltz_crash()] + [bar_waltz()] * 3 +
        # A' drums
        [bar_waltz_crash()] + [bar_waltz()] * 3 +
        [bar_waltz_crash()] + [bar_waltz()] * 3
    )

    return bpm, bass, pad, melody, drums, BAR


# ── Passacaglia ────────────────────────────────────────────────────────────────

def comp_passacaglia():
    bpm = 80
    # D minor — descending tetrachord ostinato: D C Bb A (classic passacaglia bass)
    D1,C2,Bb1,A1 = _note('D',1),_note('C',2),_note('Bb',1),_note('A',1)
    D2,C3,Bb2,A2 = _note('D',2),_note('C',3),_note('Bb',2),_note('A',2)
    D3,F3,A3 = _note('D',3),_note('F',3),_note('A',3)
    C3n,E3,G3 = _note('C',3),_note('E',3),_note('G',3)
    Bb2n,D3n,F3n = _note('Bb',2),_note('D',3),_note('F',3)
    Cs3,E3n,Gs3 = _note('C#',3),_note('E',3),_note('G#',3)
    D4,F4,A4,C4,E4,G4 = _note('D',4),_note('F',4),_note('A',4),_note('C',4),_note('E',4),_note('G',4)
    Bb3,Cs4,Bb4 = _note('Bb',3),_note('C#',4),_note('Bb',4)
    D5,F5,A5,E5,G5 = _note('D',5),_note('F',5),_note('A',5),_note('E',5),_note('G',5)
    C5,Cs5,B4 = _note('C',5),_note('C#',5),_note('B',4)

    # Ostinato: whole-note bass D-C-Bb-A across 4 bars, repeated 4 times
    ostinato = [D1, C2, Bb1, A1]
    bass = [(n, WHOLE, 78) for n in ostinato * 4]

    Dm   = [D3, F3, A3]
    Cmaj = [C3n, E3, G3]
    Bbmaj= [Bb2n, D3n, F3n]
    A7   = [A2, Cs3, E3n, G3]

    pad = (
        [(Dm,    WHOLE, 60), (Cmaj,  WHOLE, 58), (Bbmaj, WHOLE, 60), (A7,    WHOLE, 64)] +  # Var 1
        [(Dm,    HALF,  64), (Dm,    HALF,  62), (Cmaj,  HALF,  62), (Cmaj,  HALF,  60),
         (Bbmaj, HALF,  62), (Bbmaj, HALF,  60), (A7,    HALF,  66), (A7,    HALF,  64)] +  # Var 2
        [(Dm,    HALF,  70), (Dm,    HALF,  68), (Cmaj,  HALF,  68), (Cmaj,  HALF,  66),
         (Bbmaj, HALF,  68), (Bbmaj, HALF,  66), (A7,    HALF,  74), (A7,    HALF,  72)] +  # Var 3
        [(Dm,    QTR,   78), (Dm,    QTR,   76), (Dm,    QTR,   78), (Dm,    QTR,   76),
         (Cmaj,  QTR,   76), (Cmaj,  QTR,   74), (Cmaj,  QTR,   76), (Cmaj,  QTR,   74),
         (Bbmaj, QTR,   76), (Bbmaj, QTR,   74), (Bbmaj, QTR,   76), (Bbmaj, QTR,   74),
         (A7,    QTR,   82), (A7,    QTR,   80), (A7,    QTR,   84), (A7,    QTR,   82)]   # Var 4
    )

    melody = [
        # Variation 1 — introduction: quiet, stepwise, bars 1-4
        # Bar 1 Dm: simple descent from F5
        (F5, HALF, 64), (E5, QTR, 60), (D5, QTR, 58),
        # Bar 2 C: stepwise rise
        (E5, HALF, 60), (G5, HALF, 62),
        # Bar 3 Bb: lyrical phrase
        (F5, QTR, 62), (E5, QTR, 60), (D5, QTR, 58), (C5, QTR, 55),
        # Bar 4 A: half-close
        (Cs5, DOTTED_QTR, 64), (B4, EIGHTH, 60), (A4, HALF, 62),

        # Variation 2 — motion: eighth-note movement, bars 5-8
        # Bar 5 Dm: flowing 8th descent
        (A4, EIGHTH, 68), (F4, EIGHTH, 64), (A4, EIGHTH, 68), (D5, EIGHTH, 72),
        (F5, EIGHTH, 74), (D5, EIGHTH, 70), (A4, EIGHTH, 66), (F4, EIGHTH, 62),
        # Bar 6 C: ascending E-G run
        (E4, EIGHTH, 66), (G4, EIGHTH, 68), (C5, EIGHTH, 70), (E5, EIGHTH, 73),
        (G5, EIGHTH, 75), (E5, EIGHTH, 71), (C5, EIGHTH, 68), (G4, EIGHTH, 64),
        # Bar 7 Bb: lyrical leap
        (D5, QTR, 70), (F5, QTR, 72), (D5, QTR, 68), (Bb4, QTR, 64),
        # Bar 8 A: dramatic rise to high A
        (Cs5, QTR, 72), (E5, QTR, 75), (A5, HALF, 78),

        # Variation 3 — passion: high register, bars 9-12
        # Bar 9 Dm: forte D minor run
        (D5, EIGHTH, 80), (F5, EIGHTH, 78), (A5, EIGHTH, 82), (F5, EIGHTH, 78),
        (D5, EIGHTH, 80), (A4, EIGHTH, 76), (F4, EIGHTH, 72), (D4, EIGHTH, 68),
        # Bar 10 C: sweeping arch
        (G5, DOTTED_QTR, 82), (F5, EIGHTH, 76), (E5, HALF, 80),
        # Bar 11 Bb: expressive climax
        (F5, EIGHTH, 84), (D5, EIGHTH, 80), (Bb4, EIGHTH, 76), (D5, EIGHTH, 80),
        (F5, EIGHTH, 82), (G5, EIGHTH, 84), (A5, EIGHTH, 86), (Bb4, EIGHTH, 78),
        # Bar 12 A: powerful half-close
        (Cs5, QTR, 84), (E5, QTR, 82), (A5, HALF, 88),

        # Variation 4 — grandioso finale: forte, bars 13-16
        # Bar 13 Dm: fortissimo triadic descent
        (A5, EIGHTH, 92), (F5, EIGHTH, 88), (D5, EIGHTH, 90), (A4, EIGHTH, 86),
        (F4, EIGHTH, 88), (D4, EIGHTH, 84), (F4, EIGHTH, 86), (A4, EIGHTH, 88),
        # Bar 14 C: rushing scale
        (G4, EIGHTH, 86), (A4, EIGHTH, 88), (C5, EIGHTH, 90), (E5, EIGHTH, 92),
        (G5, EIGHTH, 94), (E5, EIGHTH, 90), (C5, EIGHTH, 88), (G5, EIGHTH, 92),
        # Bar 15 Bb: majestic leaps
        (D5, QTR, 90), (F5, QTR, 92), (Bb4, QTR, 88), (D5, QTR, 90),
        # Bar 16 A→D: final resolution  A7 arpeggio → D (1920 ticks)
        (A4, EIGHTH, 92), (Cs5, EIGHTH, 94), (E5, QTR, 96), (D5, HALF, 100),
    ]

    drums = [bar_sparse()] * 4 + \
            [bar_waltz()] * 4 + \
            [bar_march_inner()] * 3 + [bar_march()] + \
            [bar_march()] * 3 + [bar_heavy()]

    return bpm, bass, pad, melody, drums


# ── Composition 24: Reggae ─────────────────────────────────────────────────────

def comp_reggae():
    bpm = 82
    # G major (1 sharp: F#)
    G1, C1, D1, E1 = _note('G',1), _note('C',1), _note('D',1), _note('E',1)
    G2, B2, C2, D2, E2, A2, Fs2 = (
        _note('G',2), _note('B',2), _note('C',2), _note('D',2),
        _note('E',2), _note('A',2), _note('F#',2)
    )
    G3, B3, C3, D3, E3, A3, Fs3 = (
        _note('G',3), _note('B',3), _note('C',3), _note('D',3),
        _note('E',3), _note('A',3), _note('F#',3)
    )
    C4, D4, E4, Fs4, G4, A4, B4 = (
        _note('C',4), _note('D',4), _note('E',4), _note('F#',4),
        _note('G',4), _note('A',4), _note('B',4)
    )
    C5, D5, E5, G5 = _note('C',5), _note('D',5), _note('E',5), _note('G',5)

    Gmaj = [G3, B3, D4]; Cmaj = [C3, E3, G3]; D7 = [D3, Fs3, A3, C4]; Emin = [E3, G3, B3]

    def bar_skank(chord, v=68):
        # Reggae skank: chord stabs on eighth-note off-beats, rests on downbeats
        s = EIGHTH
        return [(chord,s,0),(chord,s,v),(chord,s,0),(chord,s,int(v*0.88)),
                (chord,s,0),(chord,s,int(v*0.94)),(chord,s,0),(chord,s,int(v*0.88))]
        # 8 * EIGHTH = 1920 ticks ✓

    def bar_bass(root, third, fifth, v=80):
        # Root on beat 1 (HALF) + walking thirds/fifths
        return [(root, HALF, v), (third, QTR, v-12), (fifth, QTR, v-8)]
        # HALF + QTR + QTR = 1920 ticks ✓

    bass = (
        bar_bass(G1,B2,D2)    + bar_bass(C1,E2,G2)    + bar_bass(G1,B2,D2)    + bar_bass(D1,Fs2,A2) +
        bar_bass(G1,B2,D2)    + bar_bass(C1,E2,G2)    + bar_bass(E1,G2,B2)    + bar_bass(D1,Fs2,A2) +
        bar_bass(C1,E2,G2)    + bar_bass(G1,B2,D2)    + bar_bass(D1,Fs2,A2)   + bar_bass(G1,B2,D2) +
        bar_bass(G1,B2,D2)    + bar_bass(C1,E2,G2)    + bar_bass(D1,Fs2,A2)   + bar_bass(G1,D2,B2,v=72)
    )

    pad = (
        bar_skank(Gmaj)    + bar_skank(Cmaj)    + bar_skank(Gmaj)    + bar_skank(D7) +
        bar_skank(Gmaj)    + bar_skank(Cmaj)    + bar_skank(Emin,62) + bar_skank(D7) +
        bar_skank(Cmaj)    + bar_skank(Gmaj)    + bar_skank(D7)      + bar_skank(Gmaj) +
        bar_skank(Gmaj)    + bar_skank(Cmaj)    + bar_skank(D7)      + bar_skank(Gmaj,60)
    )

    melody = [
        # Cycle 1 — G C G D7
        (D5, QTR, 70), (B4, HALF, 72), (G4, QTR, 68),                          # bar 1  G
        (E5, QTR, 72), (C5, HALF, 74), (G4, QTR, 68),                          # bar 2  C
        (D5, QTR, 74), (B4, QTR, 72), (A4, HALF, 76),                          # bar 3  G
        (Fs4, DOTTED_QTR, 80), (E4, EIGHTH, 72), (D4, HALF, 74),               # bar 4  D7
        # Cycle 2 — G C Em D7 (rising)
        (G4, QTR, 72), (A4, QTR, 74), (B4, HALF, 78),                          # bar 5  G
        (C5, HALF, 80), (B4, QTR, 76), (A4, QTR, 72),                          # bar 6  C
        (B4, QTR, 78), (G4, QTR, 74), (E4, HALF, 72),                          # bar 7  Em
        (Fs4, QTR, 80), (A4, QTR, 84), (D5, HALF, 86),                         # bar 8  D7
        # Cycle 3 — C G D7 G (high-water mark)
        (E5, HALF, 84), (D5, QTR, 80), (C5, QTR, 76),                          # bar 9  C
        (B4, QTR, 80), (G4, QTR, 76), (D5, HALF, 82),                          # bar 10 G
        (A4, QTR, 82), (Fs4, QTR, 80), (E4, HALF, 78),                         # bar 11 D7
        (G4, WHOLE, 76),                                                         # bar 12 G (breath)
        # Cycle 4 — G C D7 G (climax + resolution)
        (D5, QTR, 78), (E5, QTR, 82), (G5, HALF, 86),                          # bar 13 G
        (E5, DOTTED_QTR, 84), (D5, EIGHTH, 78), (C5, HALF, 80),                # bar 14 C
        (B4, QTR, 82), (A4, QTR, 86), (Fs4, DOTTED_QTR, 88), (E4, EIGHTH, 82),# bar 15 D7
        (G4, WHOLE, 80),                                                         # bar 16 G resolve
    ]

    def bar_reggae():
        # One-drop: BD+SD land together on beat 3 only; no BD on beat 1 (the "drop")
        return [
            (0, CHH, 56), (EIGHTH, CHH, 44),
            (QTR, CHH, 52), (QTR+EIGHTH, CHH, 44),
            (HALF, BD, 92), (HALF, SD, 78), (HALF, CHH, 56), (HALF+EIGHTH, CHH, 44),
            (QTR*3, CHH, 52), (QTR*3+EIGHTH, CHH, 44),
        ]

    def bar_reggae_crash():
        return [(0, CRASH, 68)] + bar_reggae()

    drums = (
        [bar_reggae_crash()] + [bar_reggae()] * 3 +
        [bar_reggae_crash()] + [bar_reggae()] * 3 +
        [bar_reggae_crash()] + [bar_reggae()] * 3 +
        [bar_reggae_crash()] + [bar_reggae()] * 3
    )
    return bpm, bass, pad, melody, drums


# ── Composition 25: Gospel ─────────────────────────────────────────────────────

def comp_gospel():
    bpm = 88
    # Bb major (2 flats: Bb, Eb)
    Bb1, F1, G1 = _note('Bb',1), _note('F',1), _note('G',1)
    C2, D2, Eb2, F2, G2, A2, Bb2 = (
        _note('C',2), _note('D',2), _note('Eb',2), _note('F',2),
        _note('G',2), _note('A',2), _note('Bb',2)
    )
    Bb3, C3, D3, Eb3, F3, G3, A3 = (
        _note('Bb',3), _note('C',3), _note('D',3), _note('Eb',3),
        _note('F',3), _note('G',3), _note('A',3)
    )
    Bb4, C4, D4, Eb4, F4, G4, A4 = (
        _note('Bb',4), _note('C',4), _note('D',4), _note('Eb',4),
        _note('F',4), _note('G',4), _note('A',4)
    )
    C5, D5, Eb5, F5 = _note('C',5), _note('D',5), _note('Eb',5), _note('F',5)

    BbMaj = [Bb3, D4, F4]; EbMaj = [Eb3, G3, Bb3]; F7 = [F3, A3, C4, Eb4]
    Gmin  = [G3, Bb3, D4]; Cmin  = [C3, Eb3, G3]

    def bar_bass_g(root, r3, r5, v=82):
        # Gospel quarter-note walking bass
        return [(root, QTR, v), (r3, QTR, v-8), (r5, QTR, v-6), (root, QTR, v-10)]
        # 4 × QTR = 1920 ✓

    def bar_pad(chord, v=70):
        return [(chord, HALF, v), (chord, HALF, int(v*0.90))]

    bass = (
        bar_bass_g(Bb1,D2,F2)   + bar_bass_g(Bb1,D2,F2)   + bar_bass_g(Eb2,G2,Bb2)  + bar_bass_g(Eb2,G2,Bb2) +
        bar_bass_g(Bb1,D2,F2)   + bar_bass_g(F1, A2,C2)   + bar_bass_g(Bb1,D2,F2)   + bar_bass_g(F1, A2,C2) +
        bar_bass_g(Eb2,G2,Bb2)  + bar_bass_g(Bb1,D2,F2)   + bar_bass_g(C2, Eb2,G2)  + bar_bass_g(F1, A2,C2) +
        bar_bass_g(Bb1,D2,F2)   + bar_bass_g(Eb2,G2,Bb2)  + bar_bass_g(F1, A2,C2)   + bar_bass_g(Bb1,F2,D2,v=76)
    )

    pad = (
        bar_pad(BbMaj,72) + bar_pad(BbMaj,74) + bar_pad(EbMaj,72) + bar_pad(EbMaj,74) +
        bar_pad(BbMaj,74) + bar_pad(F7,76)    + bar_pad(BbMaj,72) + bar_pad(F7,76) +
        bar_pad(EbMaj,76) + bar_pad(BbMaj,74) + bar_pad(Cmin,72)  + bar_pad(F7,78) +
        bar_pad(BbMaj,78) + bar_pad(EbMaj,76) + bar_pad(F7,80)    + bar_pad(BbMaj,72)
    )

    melody = [
        # Section A — call phrase
        (F4, QTR, 72), (G4, QTR, 74), (Bb4, HALF, 80),              # bar 1  Bb
        (Bb4, QTR, 80), (C5, QTR, 82), (D5, HALF, 86),              # bar 2  Bb
        (Eb5, HALF, 88), (D5, HALF, 84),                             # bar 3  Eb
        (C5, QTR, 82), (A4, QTR, 78), (F4, HALF, 74),               # bar 4  F7
        (Bb4, HALF, 78), (F4, HALF, 72),                             # bar 5  Bb
        (G4, QTR, 76), (Bb4, QTR, 80), (Eb5, HALF, 84),             # bar 6  F7
        (C5, DOTTED_QTR, 86), (Bb4, EIGHTH, 80), (A4, HALF, 82),    # bar 7  F7 tension
        (Bb4, WHOLE, 80),                                             # bar 8  Bb (breath)
        # Section B — response phrase, building intensity
        (F5, QTR, 86), (Eb5, QTR, 84), (D5, HALF, 88),              # bar 9  Eb
        (Bb4, HALF, 84), (D5, HALF, 88),                             # bar 10 Bb
        (Eb5, QTR, 88), (D5, QTR, 86), (C5, HALF, 84),              # bar 11 Cm
        (A4, DOTTED_QTR, 86), (C5, EIGHTH, 82), (F4, HALF, 80),     # bar 12 F7 descent
        (Bb4, QTR, 84), (D5, QTR, 88), (F5, HALF, 92),              # bar 13 Bb climax
        (Eb5, HALF, 88), (Bb4, HALF, 84),                            # bar 14 Eb
        (C5, DOTTED_QTR, 90), (A4, EIGHTH, 86), (F4, HALF, 88),     # bar 15 F7 final
        (Bb4, WHOLE, 82),                                             # bar 16 Bb resolution
    ]

    def bar_gospel():
        return [
            (0, BD, 90), (0, CHH, 56), (EIGHTH, CHH, 42),
            (QTR, SD, 80), (QTR, CHH, 52), (QTR+EIGHTH, CHH, 42),   # beat 2 backbeat
            (HALF, BD, 86), (HALF, CHH, 56), (HALF+EIGHTH, CHH, 42),
            (QTR*3, SD, 82), (QTR*3, CHH, 52), (QTR*3+EIGHTH, CHH, 42),  # beat 4 backbeat
        ]

    def bar_gospel_crash():
        return [(0, CRASH, 72)] + bar_gospel()

    drums = (
        [bar_gospel_crash()] + [bar_gospel()] * 3 +
        [bar_gospel_crash()] + [bar_gospel()] * 3 +
        [bar_gospel_crash()] + [bar_gospel()] * 3 +
        [bar_gospel_crash()] + [bar_gospel()] * 3
    )
    return bpm, bass, pad, melody, drums


def comp_country():
    bpm = 100
    # G major (2 sharps: F#, C#)
    G1, D2, C2, E2, B2, A2 = (
        _note('G',1), _note('D',2), _note('C',2),
        _note('E',2), _note('B',2), _note('A',2)
    )
    G2 = _note('G',2)
    G3, A3, B3, C3, D3, E3, Fs3 = (
        _note('G',3), _note('A',3), _note('B',3), _note('C',3),
        _note('D',3), _note('E',3), _note('F#',3)
    )
    G4, A4, B4, C4, D4, E4, Fs4 = (
        _note('G',4), _note('A',4), _note('B',4), _note('C',4),
        _note('D',4), _note('E',4), _note('F#',4)
    )
    G5, A5, B5, C5, D5, E5 = (
        _note('G',5), _note('A',5), _note('B',5), _note('C',5),
        _note('D',5), _note('E',5)
    )

    Gmaj = [G3, B3, D3]
    Dmaj = [D3, Fs3, A3]
    Cmaj = [C3, E3, G3]
    Emin = [E3, G3, B3]

    # "Boom-chick" alternating root/5th bass — 4 QTRs per bar = 1920 ✓
    def bar_bass_G(v=85):
        return [(G1, QTR, v), (D2, QTR, v-10), (G1, QTR, v-4), (D2, QTR, v-12)]
    def bar_bass_D(v=83):
        return [(D2, QTR, v), (A2, QTR, v-10), (D2, QTR, v-4), (A2, QTR, v-12)]
    def bar_bass_C(v=83):
        return [(C2, QTR, v), (G2, QTR, v-10), (C2, QTR, v-4), (G2, QTR, v-12)]
    def bar_bass_Em(v=82):
        return [(E2, QTR, v), (B2, QTR, v-10), (E2, QTR, v-4), (B2, QTR, v-12)]

    bass = (
        # Section A (I-V-IV-I × 2)
        bar_bass_G() + bar_bass_D() + bar_bass_C() + bar_bass_G() +
        bar_bass_G() + bar_bass_D() + bar_bass_C() + bar_bass_D() +
        # Section B (vi-IV-I-V — bridge)
        bar_bass_Em() + bar_bass_C() + bar_bass_G() + bar_bass_D() +
        # Final (I-IV-V-I)
        bar_bass_G() + bar_bass_C() + bar_bass_D() + bar_bass_G()
    )

    # Chick: chord stab on beats 2 and 4 — [] = rest, 4 × QTR = 1920 ✓
    def bar_chick(chord, v=68):
        return [
            ([], QTR, 0),           # beat 1 (rest — "boom" is in bass)
            (chord, QTR, v),        # beat 2 (chick)
            ([], QTR, 0),           # beat 3 (rest)
            (chord, QTR, int(v*0.9)),  # beat 4 (chick, softer)
        ]

    pad = (
        bar_chick(Gmaj) + bar_chick(Dmaj) + bar_chick(Cmaj) + bar_chick(Gmaj) +
        bar_chick(Gmaj) + bar_chick(Dmaj) + bar_chick(Cmaj) + bar_chick(Dmaj) +
        bar_chick(Emin) + bar_chick(Cmaj) + bar_chick(Gmaj) + bar_chick(Dmaj) +
        bar_chick(Gmaj) + bar_chick(Cmaj) + bar_chick(Dmaj) + bar_chick(Gmaj)
    )

    # Pentatonic/diatonic G major melody — every bar = 1920 ticks verified
    # Templates: A=QTR+QTR+HALF, B=DOTTED_QTR+EIGHTH+HALF, C=HALF+QTR+QTR,
    #            D=QTR+EIGHTH+DOTTED_QTR+QTR, E=WHOLE
    melody = (
        # Section A
        [(D5, QTR, 84),   (B4, QTR, 80),    (G4, HALF, 82)] +            # bar 1 G: A=1920
        [(Fs4, DOTTED_QTR, 86), (E4, EIGHTH, 82), (D4, HALF, 80)] +      # bar 2 D: B=1920
        [(E4, HALF, 82),  (D4, QTR, 80),    (C4, QTR, 78)] +             # bar 3 C: C=1920
        [(D4, QTR, 82),   (G4, QTR, 86),    (G4, HALF, 88)] +            # bar 4 G: A=1920
        [(G4, QTR, 84),   (A4, EIGHTH, 82), (B4, DOTTED_QTR, 86), (D5, QTR, 84)] +  # bar 5 G: D=1920
        [(D5, QTR, 88),   (A4, QTR, 84),    (Fs4, HALF, 82)] +           # bar 6 D: A=1920
        [(G4, DOTTED_QTR, 84), (E4, EIGHTH, 80), (C4, HALF, 78)] +       # bar 7 C: B=1920
        [(D4, WHOLE, 82)] +                                               # bar 8 D: E=1920
        # Section B — bridge (Em)
        [(E4, QTR, 82),   (G4, EIGHTH, 84), (A4, DOTTED_QTR, 86), (B4, QTR, 84)] +  # bar 9 Em: D=1920
        [(C5, QTR, 86),   (B4, QTR, 84),    (A4, HALF, 82)] +            # bar 10 C: A=1920
        [(G4, DOTTED_QTR, 84), (A4, EIGHTH, 82), (B4, HALF, 86)] +       # bar 11 G: B=1920
        [(D5, HALF, 88),  (B4, QTR, 84),    (A4, QTR, 80)] +             # bar 12 D: C=1920
        # Final section
        [(G4, QTR, 86),   (B4, EIGHTH, 84), (D5, DOTTED_QTR, 88), (G4, QTR, 84)] +  # bar 13 G: D=1920
        [(E5, QTR, 90),   (D5, QTR, 88),    (C5, HALF, 86)] +            # bar 14 C: A=1920
        [(Fs4, DOTTED_QTR, 86), (E4, EIGHTH, 82), (D4, HALF, 80)] +      # bar 15 D: B=1920
        [(G4, WHOLE, 86)]                                                  # bar 16 G: E=1920
    )

    def bar_country():
        return [
            (0, BD, 88), (0, CHH, 52),
            (EIGHTH, CHH, 42),
            (QTR, SD, 78), (QTR, CHH, 52),
            (QTR+EIGHTH, CHH, 42),
            (HALF, BD, 84), (HALF, CHH, 52),
            (HALF+EIGHTH, CHH, 42),
            (QTR*3, SD, 76), (QTR*3, CHH, 52),
            (QTR*3+EIGHTH, CHH, 42),
        ]

    def bar_country_crash():
        return [(0, CRASH, 70)] + bar_country()

    drums = (
        [bar_country_crash()] + [bar_country()] * 3 +
        [bar_country_crash()] + [bar_country()] * 3 +
        [bar_country_crash()] + [bar_country()] * 3 +
        [bar_country_crash()] + [bar_country()] * 3
    )
    return bpm, bass, pad, melody, drums


def comp_funk():
    bpm = 96
    # E minor (1 sharp: F#)
    E1, A1, B1 = _note('E',1), _note('A',1), _note('B',1)
    E2, Fs2, G2, A2, B2, Ds2 = (
        _note('E',2), _note('F#',2), _note('G',2), _note('A',2),
        _note('B',2), _note('D#',2)
    )
    E3, Fs3, G3, A3, B3, C3, D3, Ds3 = (
        _note('E',3), _note('F#',3), _note('G',3), _note('A',3),
        _note('B',3), _note('C',3), _note('D',3), _note('D#',3)
    )
    E4, Fs4, G4, A4, B4, Ds4 = (
        _note('E',4), _note('F#',4), _note('G',4), _note('A',4),
        _note('B',4), _note('D#',4)
    )
    E5, Fs5, G5, A5, B5, Ds5, D5 = (
        _note('E',5), _note('F#',5), _note('G',5), _note('A',5),
        _note('B',5), _note('D#',5), _note('D',5)
    )

    Emin = [E3, G3, B3]
    Amin = [A2, C3, E3]
    Gmaj = [G2, B2, D3]
    B7   = [B2, Ds3, Fs3, A3]   # V7 of E minor; D# is sharp-spelled (E minor = 1 sharp)

    # Funk bass: DOTTED_QTR + EIGHTH + DOTTED_QTR + EIGHTH = 720+240+720+240 = 1920 ✓ per bar
    def bar_bass_em(v=88):
        return [
            (E2, DOTTED_QTR, v),     (E3, EIGHTH, v-16),
            (E2, DOTTED_QTR, v-6),   (E3, EIGHTH, v-20),
        ]
    def bar_bass_am(v=85):
        return [
            (A1, DOTTED_QTR, v),     (A2, EIGHTH, v-16),
            (A1, DOTTED_QTR, v-6),   (A2, EIGHTH, v-20),
        ]
    def bar_bass_g(v=85):
        return [
            (G2, DOTTED_QTR, v),     (G3, EIGHTH, v-16),
            (G2, DOTTED_QTR, v-6),   (G3, EIGHTH, v-20),
        ]
    def bar_bass_b7(v=86):
        return [
            (B1, DOTTED_QTR, v),     (Ds2, EIGHTH, v-14),  # D# chromatic color
            (B1, DOTTED_QTR, v-6),   (Fs2, EIGHTH, v-18),  # F# the fifth
        ]

    bass = (
        bar_bass_em() + bar_bass_am() + bar_bass_g() + bar_bass_b7() +
        bar_bass_em() + bar_bass_am() + bar_bass_g() + bar_bass_b7() +
        bar_bass_em() + bar_bass_am() + bar_bass_g() + bar_bass_b7() +
        bar_bass_em() + bar_bass_am() + bar_bass_g() + bar_bass_b7()
    )

    # Off-beat chord stabs — [] = rest (no MIDI events), real chord = upbeat stab
    # 8 × EIGHTH = 1920 ✓ per bar
    def bar_pad_stabs(chord, v=72):
        return [
            ([], EIGHTH, 0),              # beat 1 (rest)
            (chord, EIGHTH, v),           # beat 1+ stab
            ([], EIGHTH, 0),              # beat 2
            (chord, EIGHTH, int(v*0.85)), # beat 2+
            ([], EIGHTH, 0),              # beat 3
            (chord, EIGHTH, int(v*0.90)), # beat 3+
            ([], EIGHTH, 0),              # beat 4
            (chord, EIGHTH, int(v*0.82)), # beat 4+
        ]

    pad = (
        bar_pad_stabs(Emin) + bar_pad_stabs(Amin) +
        bar_pad_stabs(Gmaj) + bar_pad_stabs(B7) +
        bar_pad_stabs(Emin) + bar_pad_stabs(Amin) +
        bar_pad_stabs(Gmaj) + bar_pad_stabs(B7) +
        bar_pad_stabs(Emin) + bar_pad_stabs(Amin) +
        bar_pad_stabs(Gmaj) + bar_pad_stabs(B7) +
        bar_pad_stabs(Emin) + bar_pad_stabs(Amin) +
        bar_pad_stabs(Gmaj) + bar_pad_stabs(B7)
    )

    # Pentatonic E minor melody — every bar = 1920 ticks verified
    # Templates: A=QTR+QTR+HALF, B=DOTTED_QTR+EIGHTH+HALF, C=HALF+QTR+QTR,
    #            D=QTR+EIGHTH+DOTTED_QTR+QTR
    melody = (
        # Section A — call phrases (bars 1-8)
        [(E5, DOTTED_QTR, 86), (D5, EIGHTH, 82), (B4, HALF, 80)] +         # bar 1 Em: 720+240+960=1920
        [(A4, QTR, 84), (G4, QTR, 80), (E4, HALF, 76)] +                   # bar 2 Am: 480+480+960=1920
        [(G4, HALF, 82), (B4, QTR, 86), (D5, QTR, 84)] +                   # bar 3 G:  960+480+480=1920
        [(Fs4, DOTTED_QTR, 88), (Ds4, EIGHTH, 84), (B3, HALF, 80)] +       # bar 4 B7: 720+240+960=1920
        [(E5, QTR, 90), (G5, EIGHTH, 88), (E5, DOTTED_QTR, 86), (D5, QTR, 82)] +  # bar 5 Em: 480+240+720+480=1920
        [(A4, DOTTED_QTR, 86), (G4, EIGHTH, 82), (E4, HALF, 78)] +         # bar 6 Am: 720+240+960=1920
        [(G4, QTR, 84), (A4, QTR, 86), (B4, HALF, 88)] +                   # bar 7 G:  480+480+960=1920
        [(B4, HALF, 86), (Fs4, QTR, 84), (Ds4, QTR, 82)] +                 # bar 8 B7: 960+480+480=1920
        # Section B — response phrases, higher register (bars 9-16)
        [(G5, QTR, 92), (E5, EIGHTH, 90), (G5, DOTTED_QTR, 88), (B5, QTR, 86)] +  # bar 9 Em: 480+240+720+480=1920
        [(A5, DOTTED_QTR, 90), (G5, EIGHTH, 86), (E5, HALF, 84)] +         # bar 10 Am: 720+240+960=1920
        [(G5, HALF, 88), (D5, QTR, 84), (B4, QTR, 80)] +                   # bar 11 G:  960+480+480=1920
        [(Ds5, QTR, 92), (Fs5, EIGHTH, 90), (B4, DOTTED_QTR, 88), (Fs4, QTR, 84)] +  # bar 12 B7: 480+240+720+480=1920
        [(E5, QTR, 90), (G5, QTR, 92), (E5, HALF, 88)] +                   # bar 13 Em: 480+480+960=1920
        [(A4, HALF, 86), (G4, QTR, 82), (E4, QTR, 78)] +                   # bar 14 Am: 960+480+480=1920
        [(B4, QTR, 88), (D5, EIGHTH, 86), (G4, DOTTED_QTR, 84), (B4, QTR, 82)] +  # bar 15 G: 480+240+720+480=1920
        [(E5, WHOLE, 92)]                                                    # bar 16 Em: 1920
    )

    # Funk drums — tight 16th-note hi-hat grid with syncopated kicks and ghost snare
    def bar_funk():
        return [
            (0,                    BD,  96), (0,                    CHH, 60),
            (SIXTEENTH,            CHH, 46),
            (EIGHTH,               CHH, 54), (EIGHTH,               SD,  38),  # ghost snare 1+
            (EIGHTH+SIXTEENTH,     CHH, 44),
            (QTR,                  CHH, 58),
            (QTR+SIXTEENTH,        CHH, 44),
            (QTR+EIGHTH,           BD,  88), (QTR+EIGHTH,           CHH, 54),  # synco kick 2+
            (QTR+EIGHTH+SIXTEENTH, CHH, 44),
            (HALF,                 SD,  84), (HALF,                 CHH, 60),  # backbeat 3
            (HALF+SIXTEENTH,       CHH, 46),
            (HALF+EIGHTH,          CHH, 54),
            (HALF+EIGHTH+SIXTEENTH,CHH, 44),
            (QTR*3,                CHH, 58), (QTR*3,                BD,  82),  # kick 4
            (QTR*3+SIXTEENTH,      CHH, 44),
            (QTR*3+EIGHTH,         SD,  80), (QTR*3+EIGHTH,         CHH, 54),  # snare 4+
            (QTR*3+EIGHTH+SIXTEENTH, CHH, 44),
        ]

    def bar_funk_crash():
        return [(0, CRASH, 72)] + bar_funk()

    drums = (
        [bar_funk_crash()] + [bar_funk()] * 3 +
        [bar_funk_crash()] + [bar_funk()] * 3 +
        [bar_funk_crash()] + [bar_funk()] * 3 +
        [bar_funk_crash()] + [bar_funk()] * 3
    )
    return bpm, bass, pad, melody, drums


# ── Composition 28: Soul/R&B ──────────────────────────────────────────────────

def comp_soul():
    bpm = 76
    # A natural minor — no key sig; G# appears only in E7 bars as accidental
    A1, C1, D1, E1 = _note('A',1), _note('C',1), _note('D',1), _note('E',1)
    A2, B2, C2, D2, E2, F2, G2, Gs2 = (
        _note('A',2), _note('B',2), _note('C',2), _note('D',2),
        _note('E',2), _note('F',2), _note('G',2), _note('G#',2)
    )
    A3, B3, C3, D3, E3, F3, G3, Gs3 = (
        _note('A',3), _note('B',3), _note('C',3), _note('D',3),
        _note('E',3), _note('F',3), _note('G',3), _note('G#',3)
    )
    A4, B4, C4, D4, E4, F4, G4, Gs4 = (
        _note('A',4), _note('B',4), _note('C',4), _note('D',4),
        _note('E',4), _note('F',4), _note('G',4), _note('G#',4)
    )
    A5, B5, C5, D5, E5, F5, G5 = (
        _note('A',5), _note('B',5), _note('C',5), _note('D',5),
        _note('E',5), _note('F',5), _note('G',5)
    )

    Am7   = [A2, C3, E3, G3]
    Dm7   = [D3, F3, A3, C4]
    Cmaj7 = [C3, E3, G3, B3]
    E7    = [E3, Gs3, B3, D4]   # G# = raised 3rd (Phrygian dominant chromaticism)

    # Soul bass: root(QTR) + walk(DOTTED_QTR) + color(EIGHTH) + root(QTR) = 480+720+240+480 = 1920 ✓
    def bar_bass_am(v=85):
        return [(A1, QTR, v), (E2, DOTTED_QTR, v-12), (G2, EIGHTH, v-18), (A1, QTR, v-8)]
    def bar_bass_dm(v=83):
        return [(D1, QTR, v), (A2, DOTTED_QTR, v-12), (F2, EIGHTH, v-18), (D1, QTR, v-8)]
    def bar_bass_c(v=82):
        return [(C1, QTR, v), (G2, DOTTED_QTR, v-12), (E2, EIGHTH, v-18), (C1, QTR, v-8)]
    def bar_bass_e7(v=86):
        return [(E1, QTR, v), (B2, DOTTED_QTR, v-10), (Gs2, EIGHTH, v-14), (E1, QTR, v-8)]

    bass = (
        bar_bass_am(v=80) + bar_bass_dm(v=78) + bar_bass_c(v=78) + bar_bass_e7(v=82) +
        bar_bass_am() + bar_bass_dm() + bar_bass_c() + bar_bass_e7() +
        bar_bass_am(v=90) + bar_bass_dm(v=88) + bar_bass_c(v=88) + bar_bass_e7(v=92) +
        bar_bass_am(v=88) + bar_bass_dm(v=86) + bar_bass_c(v=86) + bar_bass_e7(v=82)
    )

    # Soul pad comping: DOTTED_QTR + EIGHTH + QTR(rest) + QTR = 720+240+480+480 = 1920 ✓
    def bar_pad(chord, v=70):
        return [
            (chord, DOTTED_QTR, v),
            (chord, EIGHTH, int(v * 0.88)),
            ([], QTR, 0),
            (chord, QTR, int(v * 0.92)),
        ]

    pad = (
        bar_pad(Am7, v=65) + bar_pad(Dm7, v=65) + bar_pad(Cmaj7, v=63) + bar_pad(E7, v=68) +
        bar_pad(Am7) + bar_pad(Dm7) + bar_pad(Cmaj7) + bar_pad(E7, v=74) +
        bar_pad(Am7, v=74) + bar_pad(Dm7, v=74) + bar_pad(Cmaj7, v=72) + bar_pad(E7, v=76) +
        bar_pad(Am7, v=72) + bar_pad(Dm7, v=72) + bar_pad(Cmaj7, v=70) + bar_pad(E7, v=65)
    )

    # A minor blues melody — every bar = 1920 ticks verified
    # Template key: A=QTR+QTR+HALF, B=DOTTED_QTR+EIGHTH+HALF,
    #               C=HALF+QTR+QTR, E=QTR+EIGHTH+DOTTED_QTR+QTR, F=WHOLE
    melody = (
        # Cycle 1 — Am7 Dm7 Cmaj7 E7 (call, intro level)
        [(A4, DOTTED_QTR, 80), (C5, EIGHTH, 78), (E5, HALF, 82)] +            # bar 1  Am7: B=1920
        [(F4, QTR, 76), (A4, QTR, 78), (D5, HALF, 80)] +                      # bar 2  Dm7: A=1920
        [(E5, HALF, 82), (D5, QTR, 78), (C5, QTR, 75)] +                      # bar 3  Cmaj7: C=1920
        [(B4, DOTTED_QTR, 84), (Gs4, EIGHTH, 80), (A4, HALF, 86)] +           # bar 4  E7: B=1920
        # Cycle 2 — response phrases, higher
        [(E5, DOTTED_QTR, 84), (D5, EIGHTH, 80), (A4, HALF, 82)] +            # bar 5  Am7: B=1920
        [(A4, QTR, 78), (C5, EIGHTH, 82), (D5, DOTTED_QTR, 86), (F5, QTR, 84)] + # bar 6 Dm7: E=1920
        [(G5, HALF, 88), (E5, QTR, 84), (C5, QTR, 80)] +                     # bar 7  Cmaj7: C=1920
        [(Gs4, DOTTED_QTR, 86), (A4, EIGHTH, 84), (E5, HALF, 90)] +           # bar 8  E7: B=1920
        # Cycle 3 — high energy (climax building)
        [(A5, QTR, 92), (G5, EIGHTH, 88), (E5, DOTTED_QTR, 90), (D5, QTR, 86)] + # bar 9 Am7: E=1920
        [(F5, DOTTED_QTR, 90), (E5, EIGHTH, 88), (D5, HALF, 86)] +            # bar 10 Dm7: B=1920
        [(E5, QTR, 88), (G5, QTR, 90), (E5, HALF, 86)] +                     # bar 11 Cmaj7: A=1920
        [(Gs4, QTR, 90), (B4, DOTTED_QTR, 92), (Gs4, EIGHTH, 88), (E5, QTR, 94)] + # bar 12 E7: E=1920
        # Cycle 4 — resolution
        [(A5, HALF, 92), (G5, QTR, 88), (E5, QTR, 84)] +                     # bar 13 Am7: C=1920
        [(D5, DOTTED_QTR, 86), (C5, EIGHTH, 84), (A4, HALF, 82)] +            # bar 14 Dm7: B=1920
        [(C5, QTR, 84), (E5, QTR, 86), (G5, HALF, 88)] +                     # bar 15 Cmaj7: A=1920
        [(A4, WHOLE, 85)]                                                       # bar 16 Am7: F=1920
    )

    # Soul/R&B drums: 2+4 backbeat with ghost snares before main hits, syncopated kick
    def bar_soul():
        return [
            (0,                BD,  88), (0,                CHH, 56),
            (EIGHTH,           CHH, 44),
            (QTR,              CHH, 50), (QTR,              SD,  35),   # ghost snare on 2
            (QTR+EIGHTH,       SD,  90), (QTR+EIGHTH,       OHH, 62),   # main snare 2+
            (HALF,             BD,  82), (HALF,             CHH, 54),
            (HALF+EIGHTH,      BD,  62), (HALF+EIGHTH,      CHH, 42),   # ghost kick 3+
            (QTR*3,            CHH, 52), (QTR*3,            SD,  34),   # ghost snare on 4
            (QTR*3+EIGHTH,     SD,  88), (QTR*3+EIGHTH,     CHH, 58),   # main snare 4+
        ]

    def bar_soul_crash():
        return [(0, CRASH, 70)] + bar_soul()

    drums = (
        [bar_soul_crash()] + [bar_soul()] * 3 +
        [bar_soul_crash()] + [bar_soul()] * 3 +
        [bar_soul_crash()] + [bar_soul()] * 3 +
        [bar_soul_crash()] + [bar_soul()] * 3
    )
    return bpm, bass, pad, melody, drums


# ── Composition 29: Swing Jazz / Big Band ─────────────────────────────────────

def comp_swing():
    bpm = 152  # Authentic big-band swing tempo (slightly slowed for better feel)
    # Bb major (2 flats: Bb, Eb)
    F1, G1, A1, Bb1 = (
        _note('F',1), _note('G',1), _note('A',1), _note('Bb',1)
    )
    Bb2, C2, D2, Eb2, F2, G2, A2 = (
        _note('Bb',2), _note('C',2), _note('D',2), _note('Eb',2),
        _note('F',2), _note('G',2), _note('A',2)
    )
    Bb3, C3, D3, Eb3, F3, G3, A3 = (
        _note('Bb',3), _note('C',3), _note('D',3), _note('Eb',3),
        _note('F',3), _note('G',3), _note('A',3)
    )
    Bb4, C4, D4, Eb4, F4, G4, A4 = (
        _note('Bb',4), _note('C',4), _note('D',4), _note('Eb',4),
        _note('F',4), _note('G',4), _note('A',4)
    )
    Bb5, C5, D5, Eb5, F5, G5, A5 = (
        _note('Bb',5), _note('C',5), _note('D',5), _note('Eb',5),
        _note('F',5), _note('G',5), _note('A',5)
    )

    # 7th chord voicings for authentic jazz comping
    Bbmaj7 = [Bb2, D3, F3, A3]
    Gm7    = [G2, Bb2, D3, F3]
    Cm7    = [C3, Eb3, G3, Bb3]
    F7     = [F2, A2, C3, Eb3]
    Ebmaj7 = [Eb3, G3, Bb3, D4]

    # Walking quarter-note bass — approach notes target next chord root
    # 4 × QTR = 1920 ✓ per bar
    def walk_bb_to_gm(v=84):
        return [(Bb1, QTR, v), (D2, QTR, v-8), (F2, QTR, v-6), (G2, QTR, v-10)]
    def walk_gm_to_cm(v=82):
        return [(G1, QTR, v), (Bb1, QTR, v-8), (D2, QTR, v-6), (C2, QTR, v-10)]
    def walk_cm_to_f7(v=82):
        return [(C2, QTR, v), (Eb2, QTR, v-8), (G2, QTR, v-6), (F1, QTR, v-10)]
    def walk_f7_to_bb(v=86):
        return [(F1, QTR, v), (A1, QTR, v-8), (C2, QTR, v-6), (Bb1, QTR, v-10)]
    def walk_bb_to_eb(v=88):
        return [(Bb1, QTR, v), (C2, QTR, v-8), (D2, QTR, v-6), (Eb2, QTR, v-10)]
    def walk_eb_to_cm(v=86):
        return [(Eb2, QTR, v), (F2, QTR, v-8), (G2, QTR, v-6), (C2, QTR, v-10)]

    bass = (
        # A section (bars 1-8): Bb-Gm-Cm-F7 x2
        walk_bb_to_gm() + walk_gm_to_cm() + walk_cm_to_f7() + walk_f7_to_bb() +
        walk_bb_to_gm() + walk_gm_to_cm() + walk_cm_to_f7() + walk_f7_to_bb() +
        # B section (bars 9-16): climb
        walk_bb_to_gm(v=88) + walk_gm_to_cm(v=86) + walk_cm_to_f7(v=86) + walk_f7_to_bb(v=90) +
        walk_bb_to_gm(v=86) + walk_gm_to_cm(v=84) + walk_cm_to_f7(v=82) + walk_f7_to_bb(v=80) +
        # Bridge (bars 17-20): Bb-Eb-Cm-F7 (IV sub)
        walk_bb_to_eb(v=84) + walk_eb_to_cm(v=82) + walk_cm_to_f7(v=84) + walk_f7_to_bb(v=86) +
        # Shout chorus (bars 21-24): fortissimo I-vi-ii-V
        walk_bb_to_gm(v=94) + walk_gm_to_cm(v=92) + walk_cm_to_f7(v=92) + walk_f7_to_bb(v=96)
    )

    # Backbeat comping: chord stabs on beats 2 and 4
    # [(rest, QTR), (chord, QTR), (rest, QTR), (chord, QTR)] = 4 × QTR = 1920 ✓
    def bar_comp(chord, v=70):
        return [
            ([], QTR, 0),
            (chord, QTR, v),
            ([], QTR, 0),
            (chord, QTR, int(v * 0.88)),
        ]

    pad = (
        # A section
        bar_comp(Bbmaj7) + bar_comp(Gm7) + bar_comp(Cm7) + bar_comp(F7) +
        bar_comp(Bbmaj7) + bar_comp(Gm7) + bar_comp(Cm7) + bar_comp(F7) +
        # B section
        bar_comp(Bbmaj7, v=76) + bar_comp(Gm7, v=74) + bar_comp(Cm7, v=74) + bar_comp(F7, v=78) +
        bar_comp(Bbmaj7, v=72) + bar_comp(Gm7, v=70) + bar_comp(Cm7, v=68) + bar_comp(F7, v=66) +
        # Bridge: Bb-Eb-Cm-F7
        bar_comp(Bbmaj7, v=74) + bar_comp(Ebmaj7, v=76) + bar_comp(Cm7, v=78) + bar_comp(F7, v=82) +
        # Shout chorus: fortissimo
        bar_comp(Bbmaj7, v=88) + bar_comp(Gm7, v=86) + bar_comp(Cm7, v=86) + bar_comp(F7, v=90)
    )

    # Swing 8th melody in Bb major — all bars = 1920 ticks verified
    # (swing=True shifts off-beat 8ths to triplet position in notes_trk)
    # Templates: A=QTR+QTR+HALF, B=DOTTED_QTR+EIGHTH+HALF, C=HALF+QTR+QTR,
    #            E=QTR+EIGHTH+DOTTED_QTR+QTR, F=WHOLE
    melody = (
        # Section A — call phrases (bars 1-8)
        [(D5, DOTTED_QTR, 86), (C5, EIGHTH, 82), (Bb4, HALF, 84)] +          # bar 1 Bb: B=1920
        [(G4, QTR, 80), (A4, EIGHTH, 82), (Bb4, DOTTED_QTR, 86), (G4, QTR, 84)] + # bar 2 Gm: E=1920
        [(Eb5, QTR, 88), (D5, EIGHTH, 84), (C5, DOTTED_QTR, 86), (Bb4, QTR, 82)] + # bar 3 Cm: E=1920
        [(F5, HALF, 90), (Eb5, QTR, 86), (D5, QTR, 84)] +                    # bar 4 F7: C=1920
        [(Bb4, QTR, 84), (D5, QTR, 86), (F5, HALF, 88)] +                    # bar 5 Bb: A=1920
        [(D5, QTR, 86), (Bb4, QTR, 82), (G4, HALF, 80)] +                    # bar 6 Gm: A=1920
        [(G4, QTR, 82), (Bb4, QTR, 86), (C5, HALF, 88)] +                    # bar 7 Cm: A=1920
        [(A4, DOTTED_QTR, 90), (G4, EIGHTH, 86), (F4, HALF, 84)] +           # bar 8 F7: B=1920
        # Section B — response phrases (bars 9-16), climbing to G5
        [(D5, QTR, 90), (F5, EIGHTH, 88), (G5, DOTTED_QTR, 92), (F5, QTR, 88)] + # bar 9 Bb: E=1920
        [(G5, HALF, 90), (F5, QTR, 86), (D5, QTR, 82)] +                     # bar 10 Gm: C=1920
        [(G4, QTR, 86), (Eb5, QTR, 90), (C5, HALF, 88)] +                    # bar 11 Cm: A=1920
        [(A4, QTR, 88), (C5, EIGHTH, 86), (Eb5, DOTTED_QTR, 90), (D5, QTR, 86)] + # bar 12 F7: E=1920
        [(Bb4, QTR, 84), (C5, QTR, 86), (D5, HALF, 90)] +                    # bar 13 Bb: A=1920
        [(Bb4, DOTTED_QTR, 88), (A4, EIGHTH, 84), (G4, HALF, 82)] +          # bar 14 Gm: B=1920
        [(G4, QTR, 84), (F4, EIGHTH, 82), (Eb4, DOTTED_QTR, 86), (D4, QTR, 84)] + # bar 15 Cm: E=1920
        [(Bb4, WHOLE, 88)] +                                                   # bar 16 Bb: F=1920
        # Bridge (bars 17-20): Bb-Eb-Cm-F7, lyrical upper register
        [(D5, QTR, 86), (F5, EIGHTH, 88), (Bb5, DOTTED_QTR, 90), (A5, QTR, 86)] + # bar 17 Bb: E=1920
        [(G5, HALF, 88), (Eb5, QTR, 84), (D5, QTR, 82)] +                    # bar 18 Eb: C=1920
        [(C5, QTR, 84), (Eb5, QTR, 88), (G5, HALF, 90)] +                    # bar 19 Cm: A=1920
        [(F5, DOTTED_QTR, 92), (Eb5, EIGHTH, 88), (D5, QTR, 90), (C5, QTR, 86)] + # bar 20 F7: E=1920
        # Shout chorus (bars 21-24): fortissimo, peak energy
        [(Bb4, EIGHTH, 94), (D5, EIGHTH, 92), (F5, QTR, 96), (Bb5, HALF, 98)] +  # bar 21 Bb: 240+240+480+960=1920
        [(Bb5, QTR, 96), (A5, EIGHTH, 92), (G5, DOTTED_QTR, 94), (D5, QTR, 90)] + # bar 22 Gm: E=1920
        [(Eb5, QTR, 92), (G5, QTR, 94), (Bb5, HALF, 96)] +                   # bar 23 Cm: A=1920
        [(F5, DOTTED_QTR, 94), (Eb5, EIGHTH, 90), (D5, QTR, 92), (Bb4, QTR, 88)]  # bar 24 F7: E=1920
    )

    # Big band swing drums: ride on every quarter, SD backbeat on 2+4, kick on 1 and 3
    def bar_swing_drums():
        return [
            (0,         RIDE, 72), (0,       BD,  80),
            (EIGHTH,    RIDE, 48),
            (QTR,       RIDE, 65), (QTR,     SD,  90),
            (QTR+EIGHTH, RIDE, 46),
            (HALF,      RIDE, 68), (HALF,    BD,  68),
            (HALF+EIGHTH, RIDE, 46),
            (QTR*3,     RIDE, 65), (QTR*3,   SD,  88),
            (QTR*3+EIGHTH, RIDE, 44),
        ]

    def bar_swing_crash():
        return [(0, CRASH, 70)] + bar_swing_drums()

    def bar_swing_crash_ff():  # fortissimo crash for shout section
        return [(0, CRASH, 88), (0, BD, 95)] + bar_swing_drums()

    drums = (
        [bar_swing_crash()] + [bar_swing_drums()] * 3 +   # A1
        [bar_swing_crash()] + [bar_swing_drums()] * 3 +   # A2
        [bar_swing_crash()] + [bar_swing_drums()] * 3 +   # B1
        [bar_swing_crash()] + [bar_swing_drums()] * 3 +   # B2
        [bar_swing_crash()] + [bar_swing_drums()] * 3 +   # Bridge
        [bar_swing_crash_ff()] + [bar_swing_drums()] * 3  # Shout
    )
    return bpm, bass, pad, melody, drums


# ── Composition 30: Afrobeat ──────────────────────────────────────────────────

def comp_afrobeat():
    bpm = 116
    # G minor (2 flats: Bb, Eb)
    G1, Bb1, C1, D1, F1 = (
        _note('G',1), _note('Bb',1), _note('C',1), _note('D',1), _note('F',1)
    )
    G2, A2, Bb2, C2, D2, Eb2, F2 = (
        _note('G',2), _note('A',2), _note('Bb',2), _note('C',2),
        _note('D',2), _note('Eb',2), _note('F',2)
    )
    G3, A3, Bb3, C3, D3, Eb3, F3 = (
        _note('G',3), _note('A',3), _note('Bb',3), _note('C',3),
        _note('D',3), _note('Eb',3), _note('F',3)
    )
    G4, A4, Bb4, C4, D4, Eb4, F4 = (
        _note('G',4), _note('A',4), _note('Bb',4), _note('C',4),
        _note('D',4), _note('Eb',4), _note('F',4)
    )
    G5, A5, Bb5, C5, D5, Eb5, F5 = (
        _note('G',5), _note('A',5), _note('Bb',5), _note('C',5),
        _note('D',5), _note('Eb',5), _note('F',5)
    )

    Gmin  = [G2, Bb2, D3]
    Bbmaj = [Bb2, D3, F3]
    Fmaj  = [F2, A2, C3]
    Cmin  = [C3, Eb3, G3]

    # Syncopated Afrobeat bass: root-jump groove with octave leaps
    # QTR + EIGHTH + EIGHTH + DOTTED_QTR + EIGHTH = 480+240+240+720+240 = 1920 ✓
    def bar_bass_gm(v=86):
        return [(G1, QTR, v), (D2, EIGHTH, v-8), (G2, EIGHTH, v-10), (G1, DOTTED_QTR, v-4), (D2, EIGHTH, v-8)]
    def bar_bass_bb(v=82):
        return [(Bb1, QTR, v), (F2, EIGHTH, v-8), (Bb2, EIGHTH, v-10), (Bb1, DOTTED_QTR, v-4), (F2, EIGHTH, v-8)]
    def bar_bass_f(v=82):
        return [(F1, QTR, v), (C2, EIGHTH, v-8), (F2, EIGHTH, v-10), (F1, DOTTED_QTR, v-4), (C2, EIGHTH, v-8)]
    def bar_bass_cm(v=84):
        return [(C1, QTR, v), (G2, EIGHTH, v-8), (C2, EIGHTH, v-10), (C1, DOTTED_QTR, v-4), (G2, EIGHTH, v-8)]

    bass = (
        bar_bass_gm() + bar_bass_bb() + bar_bass_f() + bar_bass_cm() +
        bar_bass_gm() + bar_bass_bb() + bar_bass_f() + bar_bass_cm() +
        bar_bass_gm(v=90) + bar_bass_bb(v=86) + bar_bass_f(v=86) + bar_bass_cm(v=88) +
        bar_bass_gm(v=88) + bar_bass_bb(v=84) + bar_bass_f(v=82) + bar_bass_gm(v=80)
    )

    # Highlife-style guitar chops: stabs on 1+/2 and 3+/4 (off-beat pocket)
    # 8 × EIGHTH = 1920 ✓
    def bar_afro(chord, v=68):
        return [
            ([], EIGHTH, 0),
            (chord, EIGHTH, v),
            (chord, EIGHTH, int(v * 0.88)),
            ([], EIGHTH, 0),
            ([], EIGHTH, 0),
            (chord, EIGHTH, v),
            (chord, EIGHTH, int(v * 0.88)),
            ([], EIGHTH, 0),
        ]

    pad = (
        bar_afro(Gmin) + bar_afro(Bbmaj) + bar_afro(Fmaj) + bar_afro(Cmin) +
        bar_afro(Gmin) + bar_afro(Bbmaj) + bar_afro(Fmaj) + bar_afro(Cmin) +
        bar_afro(Gmin, v=74) + bar_afro(Bbmaj, v=74) + bar_afro(Fmaj, v=72) + bar_afro(Cmin, v=76) +
        bar_afro(Gmin, v=72) + bar_afro(Bbmaj, v=70) + bar_afro(Fmaj, v=68) + bar_afro(Gmin, v=65)
    )

    # G minor pentatonic + Dorian melody — every bar = 1920 ticks verified
    # Templates: A=QTR+QTR+HALF, B=DOTTED_QTR+EIGHTH+HALF, C=HALF+QTR+QTR,
    #            E=QTR+EIGHTH+DOTTED_QTR+QTR, F=WHOLE
    melody = (
        # Cycle 1 — call (bars 1-4)
        [(G4, DOTTED_QTR, 84), (F4, EIGHTH, 80), (D4, HALF, 82)] +            # bar 1 Gm: B=1920
        [(Bb4, QTR, 86), (A4, QTR, 82), (G4, HALF, 80)] +                     # bar 2 Bb: A=1920
        [(F4, HALF, 82), (G4, QTR, 86), (A4, QTR, 84)] +                      # bar 3 F: C=1920
        [(G4, QTR, 80), (Eb4, EIGHTH, 78), (D4, DOTTED_QTR, 82), (C4, QTR, 80)] + # bar 4 Cm: E=1920
        # Cycle 2 — response, higher register (bars 5-8)
        [(D5, DOTTED_QTR, 88), (C5, EIGHTH, 84), (Bb4, HALF, 86)] +           # bar 5 Gm: B=1920
        [(D5, QTR, 84), (C5, QTR, 82), (Bb4, HALF, 80)] +                     # bar 6 Bb: A=1920
        [(C5, HALF, 86), (Bb4, QTR, 84), (A4, QTR, 80)] +                     # bar 7 F: C=1920
        [(G4, DOTTED_QTR, 82), (F4, EIGHTH, 78), (Eb4, HALF, 76)] +           # bar 8 Cm: B=1920
        # Cycle 3 — high energy (bars 9-12)
        [(G5, QTR, 92), (F5, EIGHTH, 88), (D5, DOTTED_QTR, 90), (C5, QTR, 86)] + # bar 9 Gm: E=1920
        [(Bb4, HALF, 86), (D5, QTR, 88), (F5, QTR, 90)] +                     # bar 10 Bb: C=1920
        [(F5, DOTTED_QTR, 92), (Eb5, EIGHTH, 88), (C5, HALF, 86)] +           # bar 11 F: B=1920
        [(G4, QTR, 88), (C5, QTR, 90), (G4, HALF, 86)] +                      # bar 12 Cm: A=1920
        # Cycle 4 — resolution (bars 13-16)
        [(D5, QTR, 88), (Bb4, QTR, 86), (G4, HALF, 84)] +                     # bar 13 Gm: A=1920
        [(Bb4, DOTTED_QTR, 86), (A4, EIGHTH, 82), (G4, HALF, 80)] +           # bar 14 Bb: B=1920
        [(A4, QTR, 82), (Bb4, QTR, 84), (C5, HALF, 86)] +                     # bar 15 F: A=1920
        [(G4, WHOLE, 84)]                                                        # bar 16 Gm: F=1920
    )

    # Afrobeat drums: kick on 1, cross-stick+snare on 2+ and 4+, low-tom clave
    def bar_afrobeat():
        return [
            (0,                BD,  90), (0,                CHH, 60),
            (EIGHTH,           CHH, 48),
            (QTR,              CHH, 56), (QTR,              SD,  68),   # beat 2: light snare
            (QTR+EIGHTH,       SD,  86), (QTR+EIGHTH,       OHH, 58),   # 2+: main snare
            (HALF,             BD,  76), (HALF,             CHH, 56),   # beat 3: synco kick
            (HALF+EIGHTH,      CHH, 46),
            (QTR*3,            CHH, 56), (QTR*3,            LTOM, 64), # beat 4: low-tom clave
            (QTR*3+EIGHTH,     SD,  88), (QTR*3+EIGHTH,     CHH, 52),  # 4+: main snare
        ]

    def bar_afrobeat_crash():
        return [(0, CRASH, 70)] + bar_afrobeat()

    drums = (
        [bar_afrobeat_crash()] + [bar_afrobeat()] * 3 +
        [bar_afrobeat_crash()] + [bar_afrobeat()] * 3 +
        [bar_afrobeat_crash()] + [bar_afrobeat()] * 3 +
        [bar_afrobeat_crash()] + [bar_afrobeat()] * 3
    )
    return bpm, bass, pad, melody, drums


# ── Composition: Sacred Chorale ──────────────────────────────────────────────

def comp_sacred_chorale():
    bpm = 56  # slow, stately
    A1 = _note('A', 1)
    D2,E2,Fs2,G2,A2,B2,Cs3 = (
        _note('D',2),_note('E',2),_note('F#',2),_note('G',2),
        _note('A',2),_note('B',2),_note('C#',3)
    )
    D3,Fs3,G3,A3,B3,Cs4,D4 = [_note(n,3) for n in ['D','F#','G','A','B','C#','D']]
    E3 = _note('E',3)
    E4,Fs4,G4,A4,B4,Cs5,D5,E5 = [_note(n,4) for n in ['E','F#','G','A','B','C#','D','E']]

    melody = [
        # Phrase 1 (bars 1-4): opening arch
        (D5,  HALF,68), (Cs5, HALF,64),
        (B4,  HALF,65), (A4,  HALF,62),
        (G4,  HALF,66), (Fs4, HALF,63),
        (G4,  WHOLE,70),
        # Phrase 2 (bars 5-8): ascent to climax
        (A4,  HALF,68), (B4,  HALF,70),
        (Cs5, HALF,72), (D5,  HALF,75),
        (E5,  HALF,73), (D5,  HALF,70),
        (D5,  WHOLE,72),
        # Phrase 3 (bars 9-12): relative minor inflection
        (Fs4, HALF,65), (G4,  HALF,67),
        (A4,  HALF,70), (B4,  HALF,72),
        (A4,  HALF,68), (G4,  HALF,65),
        (Fs4, WHOLE,67),
        # Phrase 4 (bars 13-16): final resolution
        (D5,  HALF,70), (Cs5, HALF,68),
        (B4,  HALF,66), (A4,  HALF,63),
        (G4,  QTR,68),  (Fs4, QTR,66), (E4, QTR,64), (D4, QTR,62),
        (D4,  WHOLE,72),
    ]

    bass = [
        (D2,WHOLE,68),(G2,WHOLE,65),(D2,WHOLE,66),(G2,WHOLE,68),   # bars 1-4
        (D2,WHOLE,67),(A2,WHOLE,68),(A2,WHOLE,70),(D2,WHOLE,68),   # bars 5-8
        (B2,WHOLE,66),(E2,WHOLE,65),(A2,WHOLE,67),(A2,WHOLE,65),   # bars 9-12
        (D2,WHOLE,68),(A2,WHOLE,65),(G2,WHOLE,66),(D2,WHOLE,70),   # bars 13-16
    ]

    D_I   = [D3, Fs3, A3, D4]
    G_IV  = [G2, B2,  D3, G3]
    A_V   = [A2, Cs3, E3, A3]
    A7_V7 = [A2, Cs3, G3, E4]
    Bm_vi = [B2, D3,  Fs3,B3]
    Em_ii = [E2, G3,  B3, E4]

    pad = [
        (D_I,  WHOLE,58),(G_IV, WHOLE,58),(D_I,  WHOLE,58),(G_IV, WHOLE,60),
        (D_I,  WHOLE,58),(A_V,  WHOLE,60),(A7_V7,WHOLE,62),(D_I,  WHOLE,62),
        (Bm_vi,WHOLE,58),(Em_ii,WHOLE,58),(A_V,  WHOLE,60),(A7_V7,WHOLE,60),
        (D_I,  WHOLE,60),(A7_V7,WHOLE,58),(G_IV, WHOLE,60),(D_I,  WHOLE,62),
    ]

    def bar_chorale_brush():
        return [(0, CHH, 18), (QTR*2, CHH, 16)]

    drums = [bar_chorale_brush()] * 16
    return bpm, bass, pad, melody, drums


# ── Composition 33: Viennese Waltz ───────────────────────────────────────────

def comp_viennese_waltz():
    bpm = 126
    BAR = QTR * 3  # 3/4

    A1,E1,D1,B1 = _note('A',1),_note('E',1),_note('D',1),_note('B',1)
    Fs1 = _note('F#',1)
    A2,E2,D2 = _note('A',2),_note('E',2),_note('D',2)
    A3,B3,Cs4,D3,E3,Fs3,Gs3 = (
        _note('A',3),_note('B',3),_note('C#',4),_note('D',3),
        _note('E',3),_note('F#',3),_note('G#',3)
    )
    D4,E4,Fs4,Gs4,A4,B4,Cs5 = (
        _note('D',4),_note('E',4),_note('F#',4),_note('G#',4),
        _note('A',4),_note('B',4),_note('C#',5)
    )
    D5,E5,Fs5,Gs5,A5 = _note('D',5),_note('E',5),_note('F#',5),_note('G#',5),_note('A',5)

    # Bass: root on beat 1, sustain full bar
    bass = [
        # A section bars 1-8: I-V7-I-V7 / IV-I-V7-I
        (A1,BAR,70),(E1,BAR,66),(A1,BAR,70),(E1,BAR,66),
        (D2,BAR,67),(A1,BAR,70),(E1,BAR,66),(A1,BAR,72),
        # B section bars 9-16: vi-IV-I-V7 / vi-ii-V7-I
        (Fs1,BAR,66),(D2,BAR,64),(A1,BAR,68),(E1,BAR,66),
        (Fs1,BAR,64),(B1,BAR,62),(E1,BAR,68),(A1,BAR,74),
        # Reprise bars 17-24 (softer)
        (A1,BAR,62),(E1,BAR,58),(A1,BAR,62),(E1,BAR,58),
        (D2,BAR,60),(A1,BAR,62),(E1,BAR,64),(A1,BAR,72),
    ]

    # Pad: silence beat 1, chord beats 2+3 (pah-pah)
    def wp(ch, v=52):   return [([], QTR, 0), (ch, QTR, v), (ch, QTR, v - 5)]
    A_I   = [A3, Cs4, E4]
    E_V   = [Gs3, B3, E4]
    D_IV  = [D3, Fs3, A3]
    Fs_vi = [Fs3, A3, Cs4]
    Bm_ii = [B3, D4, Fs4]
    E7_V7 = [Gs3, B3, D4]

    pad = (
        wp(A_I) + wp(E7_V7) + wp(A_I) + wp(E7_V7) +
        wp(D_IV) + wp(A_I) + wp(E7_V7) + wp(A_I) +
        wp(Fs_vi) + wp(D_IV) + wp(A_I) + wp(E7_V7) +
        wp(Fs_vi) + wp(Bm_ii) + wp(E7_V7) + wp(A_I) +
        wp(A_I, 44) + wp(E7_V7, 42) + wp(A_I, 44) + wp(E7_V7, 42) +
        wp(D_IV, 42) + wp(A_I, 44) + wp(E7_V7, 46) + wp(A_I, 50)
    )

    melody = [
        # A section bars 1-8
        (E5, QTR, 68), (Cs5, QTR, 65), (A4, QTR, 62),         # bar 1 I
        (Gs4, HALF, 64), (Fs4, QTR, 60),                        # bar 2 V
        (A4, QTR, 68), (B4, QTR, 70), (Cs5, QTR, 68),          # bar 3 I
        (B4, HALF, 66), (Gs4, QTR, 62),                         # bar 4 V7
        (Fs5, QTR, 70), (E5, QTR, 68), (D5, QTR, 65),          # bar 5 IV
        (Cs5, HALF, 70), (A4, QTR, 65),                         # bar 6 I
        (B4, QTR, 68), (Cs5, QTR, 70), (B4, QTR, 65),          # bar 7 V7
        (A4, BAR, 74),                                           # bar 8 I
        # B section bars 9-16 (higher register)
        (A5, QTR, 72), (Gs5, QTR, 70), (Fs5, QTR, 68),         # bar 9 vi
        (E5, HALF, 68), (Cs5, QTR, 65),                         # bar 10 IV
        (D5, QTR, 70), (E5, QTR, 68), (Fs5, QTR, 70),          # bar 11 I
        (Gs5, HALF, 72), (E5, QTR, 65),                         # bar 12 V7
        (A5, QTR, 72), (Fs5, QTR, 68), (E5, QTR, 65),          # bar 13 vi
        (D5, HALF, 67), (B4, QTR, 62),                          # bar 14 ii
        (Cs5, QTR, 68), (B4, QTR, 70), (Gs4, QTR, 68),         # bar 15 V7
        (A4, BAR, 76),                                           # bar 16 I
        # Reprise bars 17-24 (soft, ornamental)
        (E5, QTR, 60), (Cs5, QTR, 57), (A4, QTR, 54),          # bar 17
        (Gs4, HALF, 57), (Fs4, QTR, 53),                        # bar 18
        (A4, QTR, 60), (B4, QTR, 62), (Cs5, QTR, 60),          # bar 19
        (B4, HALF, 58), (Gs4, QTR, 54),                         # bar 20
        (Fs5, QTR, 62), (E5, QTR, 60), (D5, QTR, 57),          # bar 21
        (Cs5, HALF, 62), (A4, QTR, 58),                         # bar 22
        (B4, QTR, 60), (Cs5, QTR, 62), (B4, QTR, 58),          # bar 23
        (A4, BAR, 68),                                           # bar 24 final
    ]

    drums = ([bar_waltz_crash()] + [bar_waltz()] * 7 +
             [bar_waltz_crash()] + [bar_waltz()] * 7 +
             [bar_waltz_crash()] + [bar_waltz()] * 7)
    return bpm, bass, pad, melody, drums, BAR


# ── Composition 34: Morning Mist ─────────────────────────────────────────────

def comp_morning_mist():
    bpm = 60

    # Eb major (3 flats: Bb, Eb, Ab)
    Eb1,Ab1,Bb1 = _note('Eb',1),_note('Ab',1),_note('Bb',1)
    Eb2,F2 = _note('Eb',2),_note('F',2)
    Eb3,F3,G3,Ab3,Bb3 = _note('Eb',3),_note('F',3),_note('G',3),_note('Ab',3),_note('Bb',3)
    C4,D4,Eb4,F4,G4,Ab4,Bb4 = (
        _note('C',4),_note('D',4),_note('Eb',4),_note('F',4),
        _note('G',4),_note('Ab',4),_note('Bb',4)
    )
    C5,D5,Eb5,F5,G5,Ab5,Bb5 = (
        _note('C',5),_note('D',5),_note('Eb',5),_note('F',5),
        _note('G',5),_note('Ab',5),_note('Bb',5)
    )

    # Slow-moving bass — mostly pedal tones
    bass = [
        (Eb1,WHOLE,58),(Ab1,WHOLE,55),(Bb1,WHOLE,56),(Eb1,WHOLE,58),
        (Ab1,WHOLE,55),(Eb1,WHOLE,56),(Bb1,WHOLE,58),(Eb1,WHOLE,60),
        (Eb1,WHOLE,56),(Ab1,WHOLE,55),(Bb1,WHOLE,57),(Eb1,WHOLE,58),
        (Ab1,WHOLE,55),(F2, WHOLE,56),(Bb1,WHOLE,60),(Eb1,WHOLE,62),
    ]

    # Arpeggiated pad — 4 notes per bar (whole bar = 4 QTR)
    def arp4(n1, n2, n3, n4, v=46):
        return [([n1],QTR,v),([n2],QTR,v-4),([n3],QTR,v-2),([n4],QTR,v-5)]

    EbM7  = (Eb3, G3,  Bb3, D4)
    AbM7  = (Ab3, C4,  Eb4, G4)
    Cm7   = (C4,  Eb4, G4,  Bb4)
    Fm7   = (F3,  Ab3, C4,  Eb4)
    Bb7   = (Bb3, D4,  F4,  Ab4)
    AbM9  = (Ab3, C4,  Eb4, Bb4)
    Gm7   = (G3,  Bb3, D4,  F4)

    pad = (
        arp4(*EbM7) + arp4(*AbM7) + arp4(*Fm7) + arp4(*Bb7) +
        arp4(*AbM9) + arp4(*EbM7) + arp4(*Gm7) + arp4(*Cm7) +
        arp4(*EbM7, 44) + arp4(*AbM7, 44) + arp4(*Fm7, 44) + arp4(*Bb7, 44) +
        arp4(*EbM7, 44) + arp4(*AbM9, 44) + arp4(*Bb7, 46) + arp4(*EbM7, 50)
    )

    melody = [
        # Phrase 1 (bars 1-4): Ebmaj7 → Abmaj7 → Fm7 → Bb7
        (Eb5, HALF, 64), (D5, QTR, 60), (C5, QTR, 58),          # bar 1
        (Bb4, DOTTED_HALF, 62), (C5, QTR, 58),                   # bar 2
        (Ab4, HALF, 60), (Bb4, HALF, 62),                         # bar 3
        (F5, WHOLE, 66),                                           # bar 4
        # Phrase 2 (bars 5-8): Ab → Eb → Gm7 → Cm
        (Eb5, QTR, 64), (F5, QTR, 66), (G5, HALF, 68),           # bar 5
        (F5, HALF, 65), (Eb5, HALF, 62),                           # bar 6
        (D5, HALF, 63), (Bb4, HALF, 60),                          # bar 7
        (C5, WHOLE, 65),                                           # bar 8
        # Phrase 3 (bars 9-12): slight variation — reaches Ab5 at peak
        (Eb5, HALF, 62), (D5, QTR, 58), (C5, QTR, 56),           # bar 9
        (Bb4, QTR, 58), (C5, QTR, 60), (Eb5, HALF, 63),          # bar 10
        (F5, QTR, 64), (G5, QTR, 66), (Ab5, HALF, 68),           # bar 11  climax
        (G5, WHOLE, 66),                                           # bar 12
        # Phrase 4 (bars 13-16): gentle descent back to Eb
        (F5, HALF, 64), (Eb5, HALF, 62),                          # bar 13
        (D5, HALF, 60), (C5, HALF, 58),                            # bar 14
        (Bb4, HALF, 60), (F4, HALF, 56),                           # bar 15
        (Eb4, WHOLE, 62),                                           # bar 16 final
    ]

    # Very sparse drums — just gentle hi-hat pulse
    def bar_mist():
        return [(0,RIDE,32),(HALF,RIDE,28),(QTR*2,RIDE,30),(DOTTED_HALF,RIDE,26)]

    drums = [bar_mist()] * 16
    return bpm, bass, pad, melody, drums


# ── Composition 35: Samba Carnival ────────────────────────────────────────────

def comp_samba_carnival():
    bpm = 108

    # E major (4 sharps: F#, C#, G#, D#)
    E1,B1,A1,Cs1 = _note('E',1),_note('B',1),_note('A',1),_note('C#',1)
    E2,B2,A2,Fs1 = _note('E',2),_note('B',2),_note('A',2),_note('F#',1)
    E3,Fs3,Gs3,A3,B3,Cs4,Ds4 = (
        _note('E',3),_note('F#',3),_note('G#',3),_note('A',3),
        _note('B',3),_note('C#',4),_note('D#',4)
    )
    E4,Fs4,Gs4,A4,B4,Cs5,Ds5,E5 = (
        _note('E',4),_note('F#',4),_note('G#',4),_note('A',4),
        _note('B',4),_note('C#',5),_note('D#',5),_note('E',5)
    )
    Fs5,Gs5,A5 = _note('F#',5),_note('G#',5),_note('A',5)

    # Bass: tresillo-style surdo — DOTTED_QTR+EIGHTH+DOTTED_QTR+EIGHTH = 1920 ticks
    def sbass(root_lo, root_hi):
        return [
            (root_lo, DOTTED_QTR, 78),
            (root_hi, EIGHTH, 70),
            (root_lo, DOTTED_QTR, 72),
            (root_hi, EIGHTH, 68),
        ]

    bass = (
        sbass(E1, E2) * 4 +
        sbass(A1, A2) * 2 + sbass(B1, B2) * 2 +
        sbass(E1, E2) + sbass(A1, A2) + sbass(B1, B2) + sbass(E1, E2) +
        sbass(Cs1, E2) + sbass(A1, A2) + sbass(B1, B2) + sbass(E1, E2)
    )

    # Pad: off-beat chord stabs (samba "violão" style — on upbeats)
    def spah(chord):
        # upbeat stabs on the e's and a's of beats 1, 2, 3
        return [([],DOTTED_QTR,0),(chord,EIGHTH,55),(chord,DOTTED_QTR,52),(chord,EIGHTH,50)]

    E_I   = [E3, Gs3, B3]
    A_IV  = [A3, Cs4, E4]
    B7_V7 = [B3, Ds4, Fs4]
    Csm   = [Cs4, E4, Gs4]

    pad = (
        spah(E_I) * 4 +
        spah(A_IV) * 2 + spah(B7_V7) * 2 +
        spah(E_I) + spah(A_IV) + spah(B7_V7) + spah(E_I) +
        spah(Csm) + spah(A_IV) + spah(B7_V7) + spah(E_I)
    )

    melody = [
        # A section (bars 1-4): bright, short, staccato phrases
        (E5,EIGHTH,72),(Ds5,EIGHTH,68),(Cs5,QTR,70),(B4,DOTTED_QTR,65),(Gs4,EIGHTH,60),
        (A4,EIGHTH,70),(B4,EIGHTH,68),(Cs5,QTR,72),(E5,HALF,74),
        (Fs5,EIGHTH,72),(E5,EIGHTH,70),(Cs5,DOTTED_QTR,68),(A4,EIGHTH,65),(B4,QTR,62),
        (E5,WHOLE,74),
        # B section (bars 5-8): climb and syncopate
        (Gs5,EIGHTH,74),(Fs5,EIGHTH,72),(E5,QTR,70),(Ds5,DOTTED_QTR,68),(Cs5,EIGHTH,65),
        (B4,EIGHTH,66),(Cs5,EIGHTH,68),(Ds5,QTR,70),(E5,HALF,72),
        (Fs5,DOTTED_QTR,72),(E5,EIGHTH,70),(Ds5,DOTTED_QTR,68),(B4,EIGHTH,65),
        (Cs5,WHOLE,70),
        # C section (bars 9-12): call-response pattern
        (E5,QTR,74),(Ds5,EIGHTH,70),(Cs5,EIGHTH,68),(B4,EIGHTH,66),(A4,QTR,62),(Gs4,EIGHTH,60),
        (A4,HALF,64),(B4,HALF,68),
        (Cs5,EIGHTH,70),(E5,EIGHTH,72),(Gs5,DOTTED_QTR,74),(Fs5,EIGHTH,70),(E5,QTR,68),
        (B4,WHOLE,66),
        # D section (bars 13-16): final drive
        (Cs5,DOTTED_QTR,72),(B4,EIGHTH,68),(A4,DOTTED_QTR,70),(Gs4,EIGHTH,66),
        (A4,HALF,68),(B4,HALF,70),
        (E5,QTR,74),(Fs5,EIGHTH,76),(Gs5,EIGHTH,78),(A5,EIGHTH,80),(Gs5,QTR,76),(E5,EIGHTH,72),
        (E4,WHOLE,76),
    ]

    def bar_samba():
        return [(0,BD,85),(EIGHTH,CHH,55),(QTR,SD,70),(QTR,CHH,52),(QTR+EIGHTH,CHH,55),
                (HALF,BD,78),(HALF,CHH,52),(HALF+EIGHTH,CHH,50),(QTR*3,SD,75),(QTR*3,CHH,52),
                (QTR*3+EIGHTH,CHH,50)]
    def bar_samba_crash():
        return [(0,CRASH,80),(0,BD,92)] + bar_samba()[2:]

    drums = [bar_samba_crash()] + [bar_samba()] * 3 + \
            [bar_samba_crash()] + [bar_samba()] * 3 + \
            [bar_samba_crash()] + [bar_samba()] * 3 + \
            [bar_samba_crash()] + [bar_samba()] * 3
    return bpm, bass, pad, melody, drums


# ── Composition 36: Glass Etude ───────────────────────────────────────────────

def comp_glass_etude():
    bpm = 84  # steady, hypnotic

    # C major (no accidentals): I-IV-I-IV-vi-IV-V-I arc
    C1,F1,G1,A1 = _note('C',1),_note('F',1),_note('G',1),_note('A',1)
    C3,E3,G3,A3,F3,B3,D3 = [_note(n,3) for n in ['C','E','G','A','F','B','D']]
    C4,E4,G4,A4,F4,B4,D4 = [_note(n,4) for n in ['C','E','G','A','F','B','D']]
    C5,E5,G5,A5,F5,D5    = [_note(n,5) for n in ['C','E','G','A','F','D']]

    # Pedal bass: slow whole-note movement (ppp)
    bass = [
        (C1,WHOLE,50),(C1,WHOLE,48),
        (F1,WHOLE,48),(F1,WHOLE,46),
        (C1,WHOLE,50),(C1,WHOLE,48),
        (F1,WHOLE,48),(F1,WHOLE,50),
        (A1,WHOLE,52),(A1,WHOLE,50),
        (F1,WHOLE,50),(F1,WHOLE,48),
        (G1,WHOLE,52),(G1,WHOLE,54),
        (C1,WHOLE,58),(C1,WHOLE,60),
    ]

    # Pad: sustained whole-note chords (very soft, background colour)
    pad = [
        ([C3,E3,G3],WHOLE,32),([C3,E3,G3],WHOLE,30),
        ([F3,A3,C4],WHOLE,30),([F3,A3,C4],WHOLE,28),
        ([C3,E3,G3],WHOLE,32),([C3,E3,G3],WHOLE,30),
        ([F3,A3,C4],WHOLE,30),([F3,A3,C4],WHOLE,32),
        ([A3,C4,E4],WHOLE,34),([A3,C4,E4],WHOLE,32),
        ([F3,A3,C4],WHOLE,32),([F3,A3,C4],WHOLE,30),
        ([G3,B3,D4],WHOLE,34),([G3,B3,D4],WHOLE,36),
        ([C3,E3,G3],WHOLE,40),([C3,E3,G3],WHOLE,44),
    ]

    # Glass-style melody: 8th-note cycling arpeggios with additive process.
    # Each bar = 8 eighths. Pattern mutates one note every 2 bars (Glass's additive process).
    def bar_arp(pat, v):
        return [(n, EIGHTH, v) for n in pat]

    # C (I) — 8-note cycle: up + partial down + restart
    c1 = [C4,E4,G4,C5, G4,E4,C4,E4]
    c2 = [C4,E4,G4,C5, G4,E4,G4,C5]   # shift: last 2 step up
    # F (IV)
    f1 = [F4,A4,C5,F5, C5,A4,F4,A4]
    f2 = [F4,A4,C5,F5, C5,A4,C5,F5]
    # C (I) — higher register variant
    c3 = [E4,G4,C5,E5, C5,G4,E4,G4]
    c4 = [E4,G4,C5,E5, C5,G4,C5,E5]
    # F (IV) — with upper register
    f3 = [A4,C5,F5,A5, F5,C5,A4,C5]
    f4 = [A4,C5,F5,A5, F5,C5,F5,A5]
    # Am (vi)
    am1 = [A4,C5,E5,A5, E5,C5,A4,C5]
    am2 = [A4,C5,E5,A5, E5,C5,E5,A5]
    # F (IV) — building
    f5 = [F4,A4,C5,F5, A5,F5,C5,A4]
    f6 = [F4,A4,C5,F5, A5,F5,A5,C5]
    # G (V) — tension
    g1 = [G4,B4,D5,G5, D5,B4,G4,B4]
    g2 = [G4,B4,D5,G5, D5,B4,D5,G5]
    # C (I) — final cadence, retrograde feel
    cad1 = [C4,E4,G4,C5, E5,C5,G4,E4]
    cad2 = [C4,G4,E4,C4, E4,G4,C5,G4]

    melody = (bar_arp(c1,52)   + bar_arp(c1,54)  +   # bars 1-2:  I (pp)
              bar_arp(f1,54)   + bar_arp(f2,56)  +   # bars 3-4:  IV
              bar_arp(c3,56)   + bar_arp(c4,58)  +   # bars 5-6:  I higher
              bar_arp(f3,58)   + bar_arp(f4,60)  +   # bars 7-8:  IV upper
              bar_arp(am1,62)  + bar_arp(am2,64) +   # bars 9-10: vi (mf)
              bar_arp(f5,64)   + bar_arp(f6,66)  +   # bars 11-12:IV build
              bar_arp(g1,68)   + bar_arp(g2,70)  +   # bars 13-14:V tension
              bar_arp(cad1,68) + bar_arp(cad2,65))   # bars 15-16:I cadence

    # Almost no drums — just a soft ride on beats 1 and 3
    def bar_glass():
        return [(0,RIDE,20),(HALF,RIDE,18)]

    drums = [bar_glass()] * 16
    return bpm, bass, pad, melody, drums


# ── Composition 37: Polka Village ────────────────────────────────────────────

def comp_polka_village():
    bpm = 132

    # G major (1 sharp: F#)
    G1,D1,C1 = _note('G',1),_note('D',1),_note('C',1)
    G2,D2,C2,A2 = _note('G',2),_note('D',2),_note('C',2),_note('A',2)
    G3,A3,B3,C4,D4,E4,Fs4 = (_note('G',3),_note('A',3),_note('B',3),_note('C',4),
                               _note('D',4),_note('E',4),_note('F#',4))
    G4,A4,B4,C5,D5,E5,Fs5,G5 = (_note('G',4),_note('A',4),_note('B',4),_note('C',5),
                                   _note('D',5),_note('E',5),_note('F#',5),_note('G',5))

    # Bass: "oom-pah" — root on beats 1+3, 5th on beats 2+4
    def pbass(r, f):
        return [(r, QTR, 78), (f, QTR, 62), (r, QTR, 74), (f, QTR, 60)]

    bass = (
        pbass(G1, D2) * 4 +                         # I   (bars 1-4)
        pbass(D1, A2) * 2 + pbass(C1, G2) * 2 +     # V IV (bars 5-8)
        pbass(G1, D2) * 4 +                         # I   (bars 9-12)
        pbass(D1, A2) * 2 + pbass(G1, D2) * 2       # V I  (bars 13-16)
    )

    # Pad: off-beat stabs on beats 2 and 4 only
    def ppad(chord):
        return [([], QTR, 0), (chord, QTR, 52), ([], QTR, 0), (chord, QTR, 49)]

    G_I  = [G3, B3, D4]
    D_V  = [D4, Fs4, A4]
    C_IV = [C4, E4, G4]

    pad = (
        ppad(G_I)  * 4 +
        ppad(D_V)  * 2 + ppad(C_IV) * 2 +
        ppad(G_I)  * 4 +
        ppad(D_V)  * 2 + ppad(G_I)  * 2
    )

    melody = [
        # A section (bars 1-4): bouncy stepwise runs
        (D5,QTR,72),(C5,EIGHTH,68),(B4,EIGHTH,70),(A4,QTR,72),(G4,QTR,68),
        (B4,EIGHTH,70),(A4,EIGHTH,68),(G4,QTR,72),(D4,QTR,65),(G4,QTR,70),
        (E5,EIGHTH,74),(D5,EIGHTH,70),(C5,EIGHTH,68),(B4,EIGHTH,70),(A4,QTR,68),(G4,QTR,72),
        (D5,HALF,75),(G4,HALF,68),
        # B section (bars 5-8): syncopated jumps with dotted rhythms
        (B4,EIGHTH,72),(C5,EIGHTH,68),(D5,QTR,72),(Fs4,DOTTED_QTR,70),(G4,EIGHTH,65),
        (A4,EIGHTH,68),(B4,EIGHTH,70),(C5,QTR,72),(D5,DOTTED_QTR,74),(E5,EIGHTH,76),
        (Fs4,EIGHTH,70),(G4,EIGHTH,68),(A4,QTR,72),(B4,DOTTED_QTR,74),(C5,EIGHTH,72),
        (D5,HALF,78),(D4,HALF,65),
        # A section (bars 9-12): repeat with higher dynamics
        (D5,QTR,74),(C5,EIGHTH,70),(B4,EIGHTH,72),(A4,QTR,74),(G4,QTR,70),
        (B4,EIGHTH,72),(A4,EIGHTH,70),(G4,QTR,74),(D4,QTR,68),(G4,QTR,72),
        (E5,EIGHTH,76),(D5,EIGHTH,72),(C5,EIGHTH,70),(B4,EIGHTH,72),(A4,QTR,70),(G4,QTR,74),
        (D5,HALF,78),(G4,HALF,70),
        # B-final (bars 13-16): big finish, rapid run to G5
        (B4,EIGHTH,74),(C5,EIGHTH,70),(D5,QTR,74),(Fs4,DOTTED_QTR,72),(G4,EIGHTH,68),
        (A4,EIGHTH,70),(B4,EIGHTH,72),(C5,QTR,74),(D5,DOTTED_QTR,76),(E5,EIGHTH,78),
        (G5,EIGHTH,80),(Fs5,EIGHTH,78),(E5,EIGHTH,76),(D5,EIGHTH,74),(C5,EIGHTH,72),(B4,EIGHTH,70),(A4,EIGHTH,68),(G4,EIGHTH,66),
        (G4,WHOLE,78),
    ]

    def bar_polka():
        return [(0,BD,82),(0,CHH,50),(QTR,SD,68),(QTR,CHH,46),
                (HALF,BD,78),(HALF,CHH,44),(QTR*3,SD,66),(QTR*3,CHH,42)]

    def bar_polka_crash():
        return [(0,CRASH,85),(0,BD,92),(QTR,SD,70),(QTR,CHH,50),
                (HALF,BD,80),(HALF,CHH,46),(QTR*3,SD,68),(QTR*3,CHH,44)]

    drums = (
        [bar_polka_crash()] + [bar_polka()] * 3 +
        [bar_polka_crash()] + [bar_polka()] * 3 +
        [bar_polka_crash()] + [bar_polka()] * 3 +
        [bar_polka_crash()] + [bar_polka()] * 3
    )
    return bpm, bass, pad, melody, drums


# ── Composition 38: Appalachian Fire ──────────────────────────────────────────

def comp_appalachian_fire():
    bpm = 160
    # G major (1 sharp: F#)
    G1, D2, A2, C2, G2 = _note('G',1), _note('D',2), _note('A',2), _note('C',2), _note('G',2)
    C3, D3, E3, Fs3, G3 = _note('C',3), _note('D',3), _note('E',3), _note('F#',3), _note('G',3)
    A3, B3, C4, D4, E4 = _note('A',3), _note('B',3), _note('C',4), _note('D',4), _note('E',4)
    Fs4, G4, A4, B4 = _note('F#',4), _note('G',4), _note('A',4), _note('B',4)
    C5, D5, E5, G5 = _note('C',5), _note('D',5), _note('E',5), _note('G',5)

    # Boom-chick bass: root QTR + fifth QTR × 2 per bar
    def bg(r, f): return [(r, QTR, 85), (f, QTR, 62), (r, QTR, 80), (f, QTR, 58)]
    bass = (
        bg(G1,D2)*2 + bg(D2,A2)*2 + bg(G1,D2)*2 + bg(D2,A2) + bg(G1,D2) +
        bg(C2,G2)*2 + bg(G1,D2)*2 + bg(D2,A2)*2 + bg(G1,D2)*2
    )

    # Bluegrass chop: silence on beat, chord on upbeat (mandolin-style)
    G_I  = [G3, B3, D4]
    D_V  = [D3, Fs3, A3]
    C_IV = [C3, E3, G3]
    def achop(chord, v=70):
        return [([], EIGHTH, 0), (chord, EIGHTH, v)] * 4
    pad = (
        achop(G_I)*2 + achop(D_V)*2 + achop(G_I)*2 + achop(D_V) + achop(G_I) +
        achop(C_IV)*2 + achop(G_I)*2 + achop(D_V)*2 + achop(G_I)*2
    )

    melody = [
        # A section (bars 1-4): fast pentatonic fiddle runs
        (G4,EIGHTH,85),(B4,EIGHTH,80),(D5,EIGHTH,85),(B4,EIGHTH,80),(A4,EIGHTH,82),(G4,EIGHTH,80),(A4,EIGHTH,82),(B4,EIGHTH,80),
        (B4,EIGHTH,82),(D5,EIGHTH,88),(D5,EIGHTH,85),(B4,EIGHTH,80),(A4,EIGHTH,82),(G4,EIGHTH,80),(Fs4,EIGHTH,78),(G4,EIGHTH,82),
        (A4,EIGHTH,82),(Fs4,EIGHTH,80),(D4,EIGHTH,78),(E4,EIGHTH,80),(Fs4,EIGHTH,82),(G4,EIGHTH,80),(A4,EIGHTH,82),(Fs4,EIGHTH,80),
        (A4,EIGHTH,85),(B4,EIGHTH,88),(A4,EIGHTH,85),(Fs4,EIGHTH,82),(A4,EIGHTH,82),(Fs4,EIGHTH,80),(D4,EIGHTH,78),(A4,EIGHTH,80),
        # A' section (bars 5-8): repeat with bloom to E5
        (G4,EIGHTH,85),(A4,EIGHTH,80),(B4,EIGHTH,85),(D5,EIGHTH,88),(E5,EIGHTH,90),(D5,EIGHTH,85),(B4,EIGHTH,82),(A4,EIGHTH,80),
        (G4,EIGHTH,82),(B4,EIGHTH,80),(D5,EIGHTH,85),(B4,EIGHTH,80),(G4,EIGHTH,82),(E4,EIGHTH,78),(G4,EIGHTH,80),(A4,EIGHTH,82),
        (Fs4,EIGHTH,82),(A4,EIGHTH,85),(Fs4,EIGHTH,82),(A4,EIGHTH,88),(D5,EIGHTH,90),(A4,EIGHTH,85),(Fs4,EIGHTH,82),(D4,EIGHTH,78),
        (G4,HALF,90),(B4,QTR,85),(G4,QTR,88),
        # B section (bars 9-12): C-chord material, higher register
        (E5,EIGHTH,85),(D5,EIGHTH,82),(C5,EIGHTH,80),(B4,EIGHTH,78),(A4,EIGHTH,82),(G4,EIGHTH,80),(A4,EIGHTH,82),(B4,EIGHTH,80),
        (C5,EIGHTH,85),(E5,EIGHTH,88),(C5,EIGHTH,85),(E5,EIGHTH,88),(D5,EIGHTH,82),(C5,EIGHTH,80),(B4,EIGHTH,78),(A4,EIGHTH,80),
        (B4,EIGHTH,82),(D5,EIGHTH,85),(B4,EIGHTH,82),(G4,EIGHTH,80),(A4,EIGHTH,82),(B4,EIGHTH,85),(D5,EIGHTH,82),(B4,EIGHTH,80),
        (G4,HALF,88),(D5,QTR,82),(B4,QTR,80),
        # B' finale (bars 13-16): build to blazing G5 finish
        (A4,EIGHTH,82),(Fs4,EIGHTH,80),(A4,EIGHTH,85),(D5,EIGHTH,88),(A4,EIGHTH,85),(Fs4,EIGHTH,82),(A4,EIGHTH,82),(D5,EIGHTH,85),
        (D5,EIGHTH,88),(E5,EIGHTH,90),(D5,EIGHTH,88),(B4,EIGHTH,85),(A4,EIGHTH,82),(Fs4,EIGHTH,80),(A4,EIGHTH,82),(Fs4,EIGHTH,80),
        (G4,EIGHTH,85),(A4,EIGHTH,85),(B4,EIGHTH,88),(C5,EIGHTH,88),(D5,EIGHTH,90),(E5,EIGHTH,92),(D5,EIGHTH,90),(B4,EIGHTH,88),
        (G5,QTR,95),(D5,EIGHTH,85),(B4,EIGHTH,82),(G4,QTR,90),(G4,QTR,92),
    ]

    def bar_hoedown():
        return [(0,BD,85),(0,CHH,55),(EIGHTH,CHH,45),(QTR,SD,78),(QTR,CHH,55),
                (QTR+EIGHTH,CHH,45),(QTR*2,BD,82),(QTR*2,CHH,55),(QTR*2+EIGHTH,CHH,45),
                (QTR*3,SD,75),(QTR*3,CHH,55),(QTR*3+EIGHTH,CHH,45)]
    def bar_hoedown_crash():
        return [(0,CRASH,88),(0,BD,95),(0,CHH,58),(EIGHTH,CHH,48),(QTR,SD,85),(QTR,CHH,58),
                (QTR+EIGHTH,CHH,48),(QTR*2,BD,88),(QTR*2,CHH,58),(QTR*2+EIGHTH,CHH,48),
                (QTR*3,SD,80),(QTR*3,CHH,58),(QTR*3+EIGHTH,CHH,48)]
    drums = (
        [bar_hoedown_crash()] + [bar_hoedown()] * 3 +
        [bar_hoedown_crash()] + [bar_hoedown()] * 3 +
        [bar_hoedown_crash()] + [bar_hoedown()] * 3 +
        [bar_hoedown_crash()] + [bar_hoedown()] * 3
    )
    return bpm, bass, pad, melody, drums


# ── Composition 39: Klezmer Dance ─────────────────────────────────────────────

def comp_klezmer_dance():
    bpm = 134
    # D minor (1 flat: Bb); uses Phrygian Eb and raised-7th C# for klezmer character
    D1, A1, G1 = _note('D',1), _note('A',1), _note('G',1)
    D2, E2 = _note('D',2), _note('E',2)
    D3, F3, A3 = _note('D',3), _note('F',3), _note('A',3)
    G3, Bb3 = _note('G',3), _note('Bb',3)
    A3_, C4, E4 = _note('A',3), _note('C',4), _note('E',4)
    D4, Eb4, E4_, F4 = _note('D',4), _note('Eb',4), _note('E',4), _note('F',4)
    G4, A4, Bb4, Cs4 = _note('G',4), _note('A',4), _note('Bb',4), _note('C#',4)
    C5, D5, Eb5, E5 = _note('C',5), _note('D',5), _note('Eb',5), _note('E',5)

    # Oompah bass: root on beats 1&3, fifth on 2&4
    def om(r, f): return [(r, QTR, 85), (f, QTR, 60), (r, QTR, 82), (f, QTR, 58)]
    bass = (
        om(D1,A1) + om(D1,A1) + om(G1,D2) + om(G1,D2) +
        om(D1,A1) + om(A1,E2) + om(D1,A1) + om(D1,A1) +
        om(G1,D2) + om(G1,D2) + om(D1,A1) + om(D1,A1) +
        om(A1,E2) + om(A1,E2) + om(D1,A1) + om(D1,A1)
    )  # 16 bars ✓

    Dm = [D3,  F3,  A3_]
    Gm = [G3,  Bb3, D4 ]
    Am = [A3_, C4,  E4 ]
    def bch(ch, v=68): return [(ch, WHOLE, v)]
    pad = (
        bch(Dm) + bch(Dm) + bch(Gm) + bch(Gm) +
        bch(Dm) + bch(Am) + bch(Dm) + bch(Dm) +
        bch(Gm) + bch(Gm) + bch(Dm) + bch(Dm) +
        bch(Am) + bch(Am) + bch(Dm) + bch(Dm)
    )  # 16 bars ✓

    E = EIGHTH
    Q = QTR
    H = HALF
    melody = [
        # A section (bars 1–4): fast 8th-note runs, D minor scale
        (D4,E,82),(E4_,E,78),(F4,E,84),(G4,E,80),(A4,E,86),(G4,E,80),(F4,E,82),(E4_,E,76),   # bar 1
        (A4,E,88),(Bb4,E,85),(A4,E,82),(G4,E,78),(F4,E,80),(E4_,E,76),(D4,E,82),(C4,E,78),   # bar 2
        (G4,E,80),(A4,E,82),(Bb4,E,85),(C5,E,88),(Bb4,E,85),(A4,E,80),(G4,E,78),(F4,E,76),   # bar 3
        (D5,Q,90),(C5,Q,85),(Bb4,Q,82),(A4,Q,78),                                             # bar 4
        # A' section (bars 5–8): arpeggio pattern + chromatic approach (C#/Eb)
        (D4,E,80),(F4,E,82),(A4,E,85),(D5,E,88),(A4,E,85),(F4,E,80),(D4,E,78),(F4,E,80),     # bar 5
        (A4,E,85),(Bb4,E,82),(A4,E,80),(G4,E,78),(F4,E,82),(E4_,E,78),(Cs4,E,82),(D4,E,88),  # bar 6
        (D4,E,80),(Eb4,E,82),(E4_,E,84),(F4,E,86),(G4,E,88),(A4,E,90),(Bb4,E,88),(A4,E,85),  # bar 7
        (D5,DOTTED_HALF,90),(A4,Q,80),                                                         # bar 8
        # B section (bars 9–12): higher register, Phrygian Eb flavour
        (G4,E,82),(A4,E,84),(Bb4,E,86),(D5,E,90),(Eb5,E,88),(D5,E,85),(Bb4,E,82),(A4,E,78),  # bar 9
        (G4,E,82),(D5,E,88),(E5,E,90),(D5,E,86),(C5,E,84),(Bb4,E,80),(A4,E,78),(G4,E,76),    # bar 10
        (D5,E,85),(C5,E,80),(A4,E,82),(G4,E,78),(F4,E,80),(E4_,E,76),(D4,E,80),(A3_,E,78),   # bar 11
        (D4,E,80),(F4,E,83),(A4,E,86),(D5,E,90),(C5,E,85),(A4,E,82),(F4,E,78),(D4,E,75),     # bar 12
        # B' section (bars 13–16): climactic finale
        (A4,E,85),(G4,E,80),(F4,E,82),(E4_,E,80),(D4,E,78),(E4_,E,80),(F4,E,82),(G4,E,84),   # bar 13
        (A4,H,90),(G4,Q,82),(Eb4,Q,85),                                                        # bar 14
        (D4,E,82),(F4,E,85),(A4,E,88),(D5,E,92),(E5,E,94),(D5,E,90),(A4,E,86),(F4,E,82),      # bar 15
        (D5,Q,90),(A4,Q,85),(F4,Q,80),(D4,Q,88),                                               # bar 16
    ]  # 16 bars = 30720 ticks ✓

    def bar_klez():
        return [(0,BD,85),(0,CHH,58),(EIGHTH,CHH,45),
                (QTR,SD,75),(QTR,CHH,55),(QTR+EIGHTH,CHH,42),
                (QTR*2,BD,80),(QTR*2,CHH,55),(QTR*2+EIGHTH,CHH,42),
                (QTR*3,SD,72),(QTR*3,CHH,55),(QTR*3+EIGHTH,CHH,42)]
    def bar_klez_accent():
        return [(0,CRASH,88),(0,BD,92),(0,CHH,60),(EIGHTH,CHH,48),
                (QTR,SD,82),(QTR,CHH,58),(QTR+EIGHTH,CHH,45),
                (QTR*2,BD,85),(QTR*2,CHH,58),(QTR*2+EIGHTH,CHH,45),
                (QTR*3,SD,78),(QTR*3,CHH,58),(QTR*3+EIGHTH,CHH,45)]
    drums = (
        [bar_klez_accent()] + [bar_klez()] * 3 +
        [bar_klez_accent()] + [bar_klez()] * 3 +
        [bar_klez_accent()] + [bar_klez()] * 3 +
        [bar_klez_accent()] + [bar_klez()] * 3
    )  # 16 bars ✓
    return bpm, bass, pad, melody, drums


# ── Composition 40: Urban Pulse (Hip-Hop) ─────────────────────────────────────

def comp_urban_pulse():
    bpm = 88
    # C minor (3 flats: Bb, Eb, Ab)
    C1, G1, Ab1, Bb1, F1 = _note('C',1), _note('G',1), _note('Ab',1), _note('Bb',1), _note('F',1)
    C2, Eb2 = _note('C',2), _note('Eb',2)
    C3, Eb3, F3, G3, Ab3, Bb3 = (_note('C',3), _note('Eb',3), _note('F',3),
                                   _note('G',3), _note('Ab',3), _note('Bb',3))
    C4, D4, Eb4, F4, G4, Bb4 = (_note('C',4), _note('D',4), _note('Eb',4),
                                   _note('F',4), _note('G',4), _note('Bb',4))
    C5, Eb5, G5 = _note('C',5), _note('Eb',5), _note('G',5)

    # Bass: heavy syncopated groove — Q+E+E+Q+Q = 1920 per bar
    def bas_cm(): return [(C1,QTR,90),(0,EIGHTH,0),(G1,EIGHTH,72),(C1,QTR,78),(Bb1,QTR,82)]
    def bas_ab(): return [(Ab1,QTR,86),(0,EIGHTH,0),(Eb2,EIGHTH,70),(Ab1,QTR,76),(C2,QTR,80)]
    def bas_bb(): return [(Bb1,QTR,88),(0,EIGHTH,0),(F1,EIGHTH,72),(Bb1,QTR,78),(Eb2,QTR,82)]
    def bas_fm(): return [(F1,QTR,86),(0,EIGHTH,0),(C2,EIGHTH,70),(Ab1,QTR,76),(Eb2,QTR,80)]
    bass = (
        bas_cm() + bas_ab() + bas_bb() + bas_fm() +  # bars 1-4
        bas_cm() + bas_ab() + bas_bb() + bas_fm() +  # bars 5-8
        bas_cm() + bas_ab() + bas_bb() + bas_fm() +  # bars 9-12
        bas_cm() + bas_ab() + bas_bb() + bas_cm()    # bars 13-16 (resolves to Cm)
    )  # 16 bars ✓

    Cm_ch = [C3, Eb3, G3]
    Ab_ch = [Ab3, C4, Eb4]   # Ab major: Ab-C-Eb
    Bb_ch = [Bb3, D4, F4]    # Bb major: Bb-D-F
    Fm_ch = [F3, Ab3, C4]    # F minor: F-Ab-C
    def bch(ch, v): return [(ch, WHOLE, v)]
    pad = (
        bch(Cm_ch,62) + bch(Ab_ch,60) + bch(Bb_ch,62) + bch(Fm_ch,60) +
        bch(Cm_ch,66) + bch(Ab_ch,64) + bch(Bb_ch,66) + bch(Fm_ch,64) +
        bch(Cm_ch,72) + bch(Ab_ch,70) + bch(Bb_ch,72) + bch(Fm_ch,70) +
        bch(Cm_ch,78) + bch(Ab_ch,76) + bch(Bb_ch,78) + bch(Cm_ch,82)
    )  # 16 bars ✓

    E = EIGHTH; Q = QTR; H = HALF
    melody = [
        # A section (bars 1-4): main pentatonic hook C-Eb-F-G-Bb
        (C4,Q,85),(Eb4,E,80),(G4,E,84),(Bb4,Q,88),(0,Q,0),           # bar 1 Q+E+E+Q+Q ✓
        (G4,Q,82),(0,E,0),(C4,E,78),(Eb4,Q,80),(F4,Q,82),             # bar 2 ✓
        (Bb4,Q,86),(G4,E,82),(Eb4,E,78),(F4,Q,82),(0,Q,0),            # bar 3 ✓
        (Eb4,Q,80),(G4,Q,84),(Bb4,H,88),                               # bar 4 Q+Q+H ✓
        # A' section (bars 5-8): upper octave
        (Eb5,Q,88),(0,E,0),(C5,E,84),(Bb4,Q,86),(G4,Q,82),            # bar 5 ✓
        (C5,Q,90),(0,E,0),(Eb5,E,86),(G4,Q,82),(F4,Q,80),             # bar 6 ✓
        (Bb4,Q,85),(G4,E,80),(Eb4,E,76),(C4,Q,78),(0,Q,0),            # bar 7 ✓
        (Eb4,H,82),(G4,Q,84),(Bb4,Q,86),                               # bar 8 H+Q+Q ✓
        # B section (bars 9-12): development phrase
        (G4,Q,82),(Bb4,E,85),(C5,E,88),(Eb5,Q,90),(0,Q,0),            # bar 9 ✓
        (C5,Q,88),(Bb4,E,84),(G4,E,80),(F4,Q,78),(Eb4,Q,76),          # bar 10 ✓
        (Bb4,Q,86),(G4,Q,82),(F4,E,78),(Eb4,E,76),(C4,Q,80),          # bar 11 Q+Q+E+E+Q ✓
        (G4,Q,82),(Bb4,Q,86),(C5,H,90),                                # bar 12 Q+Q+H ✓
        # B' section (bars 13-16): climax and resolution
        (Eb5,Q,92),(C5,E,88),(Bb4,E,84),(G4,Q,82),(F4,Q,80),          # bar 13 ✓
        (Eb4,Q,78),(G4,E,82),(Bb4,E,86),(C5,Q,88),(Eb5,Q,92),         # bar 14 ✓
        (G5,Q,94),(0,E,0),(Eb5,E,90),(C5,Q,88),(Bb4,Q,85),            # bar 15 ✓
        (G4,H,80),(C4,Q,85),(0,Q,0),                                   # bar 16 H+Q+Q ✓
    ]  # 16 bars ✓

    def bar_hip():
        return [(0,BD,90),(EIGHTH,CHH,50),(QTR,SD,82),(QTR+EIGHTH,CHH,46),
                (QTR*2,CHH,55),(QTR*2+EIGHTH,CHH,46),(QTR*3,SD,85),(QTR*3+EIGHTH,CHH,50)]
    def bar_hip_heavy():
        return [(0,BD,92),(EIGHTH,CHH,52),(QTR,SD,84),(QTR+EIGHTH,CHH,48),
                (QTR*2,BD,78),(QTR*2+EIGHTH,CHH,50),(QTR*3,SD,88),(QTR*3+EIGHTH,CHH,52)]
    def bar_hip_break():
        return [(0,BD,94),(EIGHTH,CHH,50),(DOTTED_QTR,BD,72),(QTR,SD,84),
                (QTR+EIGHTH,CHH,46),(QTR*2,BD,80),(QTR*2+EIGHTH,CHH,50),
                (QTR*3,SD,88),(QTR*3+EIGHTH,CHH,52)]
    drums = (
        [bar_hip()]*2 + [bar_hip_heavy()] + [bar_hip_break()] +
        [bar_hip()]*2 + [bar_hip_heavy()] + [bar_hip_break()] +
        [bar_hip()]*2 + [bar_hip_heavy()] + [bar_hip_break()] +
        [bar_hip()]*2 + [bar_hip_heavy()] + [bar_hip_break()]
    )  # 16 bars ✓
    return bpm, bass, pad, melody, drums


# ── Composition 41: Crimson Dawn (Cinematic) ──────────────────────────────────

def comp_crimson_dawn():
    bpm = 72
    # D minor (1 flat: Bb)
    D1, F1, G1, A1, Bb1, C2 = (_note('D',1), _note('F',1), _note('G',1),
                                  _note('A',1), _note('Bb',1), _note('C',2))
    D3, F3, G3, A3, Bb3 = (_note('D',3), _note('F',3), _note('G',3),
                              _note('A',3), _note('Bb',3))
    C4, D4, E4, F4, G4, A4, Bb4 = (_note('C',4), _note('D',4), _note('E',4), _note('F',4),
                                      _note('G',4), _note('A',4), _note('Bb',4))
    C5, D5, E5, F5, A5 = _note('C',5), _note('D',5), _note('E',5), _note('F',5), _note('A',5)

    # Bass: Dm→Bb→F→C progression, building from whole notes to quarters
    def b_wh(n, v):       return [(n, WHOLE, v)]
    def b_hh(n1, n2, v):  return [(n1, HALF, v), (n2, HALF, v-5)]
    def b_qt(n1,n2,n3,v): return [(n1,QTR,v),(n2,QTR,v-4),(n3,QTR,v-2),(n1,QTR,v-6)]
    bass = (
        b_wh(D1,62)+b_wh(Bb1,60)+b_wh(F1,62)+b_wh(C2,64) +           # bars 1-4: quiet
        b_hh(D1,A1,74)+b_hh(Bb1,F1,72)+b_hh(F1,C2,74)+b_hh(C2,G1,76) +  # bars 5-8: building
        b_qt(D1,F1,A1,82)+b_qt(Bb1,D1,F1,80)+b_qt(F1,A1,C2,82)+b_qt(C2,G1,C2,84) +  # bars 9-12
        b_qt(D1,F1,A1,90)+b_qt(Bb1,D1,F1,88)+b_qt(F1,A1,C2,90)+b_qt(C2,G1,C2,92) +  # bars 13-16 climax
        b_hh(D1,A1,84)+b_hh(D1,A1,76)+b_wh(D1,70)+b_wh(D1,62)        # bars 17-20: coda
    )  # 20 bars ✓

    Dm_ch = [D3, F3, A3]
    Bb_ch = [Bb3, D4, F4]
    F_ch  = [F3, A3, C4]
    C_ch  = [C4, E4, G4]
    def bch(ch, v): return [(ch, WHOLE, v)]
    pad = (
        bch(Dm_ch,55)+bch(Bb_ch,53)+bch(F_ch,55)+bch(C_ch,57) +
        bch(Dm_ch,68)+bch(Bb_ch,66)+bch(F_ch,68)+bch(C_ch,70) +
        bch(Dm_ch,78)+bch(Bb_ch,76)+bch(F_ch,78)+bch(C_ch,80) +
        bch(Dm_ch,90)+bch(Bb_ch,88)+bch(F_ch,90)+bch(C_ch,92) +
        bch(Dm_ch,84)+bch(Dm_ch,76)+bch(Dm_ch,68)+bch(Dm_ch,60)
    )  # 20 bars ✓

    H = HALF; Q = QTR
    melody = [
        # Section 1: Quiet intro, D minor (bars 1-4)
        (D4,H,55),(F4,H,52),                                  # bar 1 H+H ✓
        (A4,WHOLE,58),                                         # bar 2 ✓
        (G4,H,55),(F4,H,52),                                  # bar 3 ✓
        (E4,H,58),(D4,H,55),                                  # bar 4 ✓
        # Section 2: Building, mid-range (bars 5-8)
        (F4,H,68),(A4,H,70),                                  # bar 5 ✓
        (C5,WHOLE,74),                                         # bar 6 ✓
        (Bb4,H,70),(A4,H,68),                                 # bar 7 ✓
        (G4,H,70),(F4,H,66),                                  # bar 8 ✓
        # Section 3: Rising, upper range (bars 9-12)
        (A4,Q,80),(Bb4,Q,82),(C5,Q,84),(D5,Q,86),            # bar 9 Q*4 ✓
        (F5,H,90),(D5,H,86),                                  # bar 10 ✓
        (C5,Q,84),(Bb4,Q,80),(A4,Q,78),(G4,Q,76),            # bar 11 Q*4 ✓
        (F4,H,76),(A4,H,80),                                  # bar 12 ✓
        # Section 4: Climax (bars 13-16)
        (D5,Q,86),(F5,Q,90),(A5,H,94),                        # bar 13 Q+Q+H ✓
        (A5,H,95),(F5,H,90),                                  # bar 14 ✓
        (D5,Q,88),(C5,Q,84),(Bb4,Q,80),(A4,Q,76),            # bar 15 Q*4 ✓
        (D5,WHOLE,88),                                         # bar 16 ✓
        # Section 5: Coda, descending resolution (bars 17-20)
        (F5,H,82),(E5,H,78),                                  # bar 17 ✓
        (D5,Q,74),(C5,Q,70),(Bb4,H,68),                       # bar 18 Q+Q+H ✓
        (A4,H,65),(F4,H,62),                                  # bar 19 ✓
        (D4,WHOLE,60),                                         # bar 20 ✓
    ]  # 20 bars ✓

    def bar_cin_pulse():
        return [(0,RIDE,42),(QTR*2,RIDE,38)]
    def bar_cin_build():
        return [(0,RIDE,52),(QTR,RIDE,46),(QTR*2,SD,55),(QTR*2,RIDE,48),(QTR*3,RIDE,44)]
    def bar_cin_strong():
        return [(0,BD,80),(0,RIDE,62),(QTR,RIDE,52),
                (QTR*2,SD,74),(QTR*2,RIDE,56),(QTR*3,BD,68),(QTR*3,RIDE,50)]
    def bar_cin_climax():
        return [(0,CRASH,95),(0,BD,92),(QTR,BD,76),(QTR,RIDE,65),
                (QTR*2,SD,88),(QTR*2,BD,80),(QTR*3,SD,82),(QTR*3,RIDE,58)]
    drums = (
        [bar_cin_pulse()]*4 +
        [bar_cin_build()]*4 +
        [bar_cin_strong()]*4 +
        [bar_cin_climax()]*4 +
        [bar_cin_strong()] + [bar_cin_build()] + [bar_cin_pulse()]*2
    )  # 20 bars ✓
    return bpm, bass, pad, melody, drums


# ── Composition 44: Sakura Dreams ────────────────────────────────────────────

def comp_sakura_dreams():
    """Japanese pentatonic — G major pentatonic, gentle and flowing, 16 bars."""
    bpm = 88
    # G major pentatonic: G A B D E
    G1,D2,G2 = _note('G',1),_note('D',2),_note('G',2)
    E2,A2,B2 = _note('E',2),_note('A',2),_note('B',2)
    D3,E3,G3,A3,B3 = _note('D',3),_note('E',3),_note('G',3),_note('A',3),_note('B',3)
    D4,E4,G4,A4,B4 = _note('D',4),_note('E',4),_note('G',4),_note('A',4),_note('B',4)
    D5,E5,G5       = _note('D',5),_note('E',5),_note('G',5)

    # Chords: G, Bm, Em, D (pentatonic-friendly)
    Gmaj  = [G3,B3,D4]
    Bmin  = [B2,D3,G3]   # Bm in root pos
    Emin  = [E3,G3,B3]
    Dmaj  = [D3,G3,D4]   # D5 omitted, open 5th feel

    def bas_g():  return [(G1,QTR,80),(D2,QTR,72),(G2,QTR,76),(D2,QTR,70)]
    def bas_bm(): return [(B2,QTR,78),(D2,QTR,70),(G2,QTR,74),(D2,QTR,68)]
    def bas_em(): return [(E2,QTR,78),(G2,QTR,72),(E2,QTR,76),(B2,QTR,68)]
    def bas_d():  return [(D2,QTR,80),(A2,QTR,72),(D2,QTR,76),(A2,QTR,68)]

    bass = (
        bas_g()+bas_bm()+bas_em()+bas_d() +   # bars 1-4
        bas_g()+bas_em()+bas_d()+bas_g() +     # bars 5-8
        bas_g()+bas_bm()+bas_em()+bas_d() +   # bars 9-12
        bas_g()+bas_em()+bas_d()+              # bars 13-15
        [(G1,WHOLE,82)]                         # bar 16
    )

    def pw(ch,v=66): return [(ch,WHOLE,v)]
    pad = (
        pw(Gmaj)+pw(Bmin,62)+pw(Emin,62)+pw(Dmaj) +
        pw(Gmaj)+pw(Emin,62)+pw(Dmaj)+pw(Gmaj,70) +
        pw(Gmaj,70)+pw(Bmin,66)+pw(Emin,66)+pw(Dmaj,68) +
        pw(Gmaj,72)+pw(Emin,68)+pw(Dmaj,70)+pw(Gmaj,74)
    )

    melody = [
        # Section A (bars 1-4): introductory pentatonic phrase
        (D4,QTR,68),(G4,QTR,72),(A4,HALF,76),                   # bar 1 G
        (B4,QTR,78),(A4,QTR,76),(G4,HALF,74),                   # bar 2 Bm
        (G4,QTR,74),(E4,QTR,70),(D4,DOTTED_QTR,72),(E4,EIGHTH,68), # bar 3 Em
        (D4,HALF,72),(E4,QTR,70),(D4,QTR,68),                   # bar 4 D
        # Section A2 (bars 5-8): ascending phrase
        (G4,QTR,78),(A4,QTR,80),(B4,QTR,82),(A4,QTR,78),        # bar 5 G
        (G4,DOTTED_QTR,80),(A4,EIGHTH,76),(G4,HALF,78),          # bar 6 Em
        (A4,QTR,80),(B4,QTR,82),(D5,QTR,86),(B4,QTR,80),        # bar 7 D
        (G4,WHOLE,82),                                             # bar 8 G
        # Section B (bars 9-12): high-register phrase with leaps
        (D5,HALF,84),(B4,HALF,80),                                # bar 9 G
        (G4,QTR,78),(A4,QTR,80),(B4,QTR,82),(D5,QTR,86),        # bar 10 Bm
        (E5,HALF,88),(D5,HALF,84),                                # bar 11 Em
        (B4,QTR,82),(A4,QTR,80),(G4,HALF,78),                    # bar 12 D
        # Section A' (bars 13-16): return to theme, resolving
        (G4,QTR,80),(A4,QTR,82),(B4,QTR,84),(D5,QTR,86),        # bar 13 G
        (E5,DOTTED_QTR,88),(D5,EIGHTH,84),(B4,HALF,82),          # bar 14 Em
        (A4,QTR,80),(G4,QTR,78),(D4,HALF,76),                    # bar 15 D
        (G4,WHOLE,78),                                             # bar 16 G (resolve)
    ]

    def bar_koto():  # sparse, gamelan-inspired
        return [(0,RIDE,38),(QTR*2,RIDE,32)]
    def bar_koto2():
        return [(0,RIDE,42),(QTR,CHH,32),(QTR*2,RIDE,38),(QTR*3,CHH,28)]
    def bar_koto_crash():
        return [(0,CRASH,52)] + bar_koto()

    drums = (
        [bar_koto_crash()]+[bar_koto()]*3 +
        [bar_koto()]*3+[bar_koto2()] +
        [bar_koto_crash()]+[bar_koto()]*3 +
        [bar_koto()]*2+[bar_koto2()]+[bar_koto()]
    )
    return bpm, bass, pad, melody, drums


# ── Composition 45: Lost Cathedral ───────────────────────────────────────────

def comp_lost_cathedral():
    """Dorian-mode sacred piece — D Dorian (D minor with B natural), 20 bars."""
    bpm = 52
    # D Dorian: D E F G A B C (= D natural minor but B♮ instead of Bb)
    D1,A1 = _note('D',1),_note('A',1)
    D2,C2,E2,G2,A2,B2 = _note('D',2),_note('C',2),_note('E',2),_note('G',2),_note('A',2),_note('B',2)
    C3,D3,E3,F3,G3,A3,B3 = (_note('C',3),_note('D',3),_note('E',3),_note('F',3),
                              _note('G',3),_note('A',3),_note('B',3))
    C4,D4,E4,F4,G4,A4,B4 = (_note('C',4),_note('D',4),_note('E',4),_note('F',4),
                              _note('G',4),_note('A',4),_note('B',4))
    C5,D5,E5,F5,A5 = _note('C',5),_note('D',5),_note('E',5),_note('F',5),_note('A',5)

    # Dorian chords: Dm, C (VII), Gm (iv), Am (v), Bm° (vi°)
    Dmin  = [D3,F3,A3]
    Cmaj  = [C3,E3,G3]
    Gmin  = [G2,B2,D3]    # in Dorian: Gm uses B natural (Gm with natural 6th)
    Amaj  = [A2,C3,E3]    # Am in Dorian
    Bbmaj = [G2,C3,E3]    # C chord in root position

    def bw(n,v=72): return [(n,WHOLE,v)]
    def bh(n1,n2,v=72): return [(n1,HALF,v),(n2,HALF,v-6)]

    bass = (
        bw(D1,70)+bw(A1,66)+bw(G2,66)+bw(A1,70) +           # bars 1-4 quiet
        bh(D1,C2,75)+bh(G2,A1,72)+bh(A1,C2,75)+bw(D1,72) +  # bars 5-8
        bw(D1,80)+bw(A1,76)+bw(G2,76)+bh(A1,E2,80) +        # bars 9-12
        bw(D1,86)+bh(G2,A1,82)+bh(A1,C2,84)+bw(D1,90) +     # bars 13-16 climax
        bw(D1,82)+bh(A1,D2,78)+bw(G2,74)+bw(D1,70)          # bars 17-20 coda
    )

    def pw(ch,v=60): return [(ch,WHOLE,v)]
    def ph(c1,v1,c2,v2): return [(c1,HALF,v1),(c2,HALF,v2)]

    pad = (
        pw(Dmin,58)+pw(Cmaj,54)+pw(Gmin,54)+pw(Amaj,58) +
        pw(Dmin,64)+pw(Cmaj,60)+pw(Gmin,60)+pw(Dmin,66) +
        pw(Dmin,72)+pw(Amaj,68)+pw(Gmin,68)+pw(Cmaj,72) +
        pw(Dmin,80)+pw(Gmin,76)+pw(Amaj,80)+pw(Dmin,84) +
        ph(Dmin,76,Cmaj,72)+ph(Gmin,70,Amaj,74)+pw(Dmin,68)+pw(Dmin,62)
    )

    melody = [
        # Section 1: Quiet intro, stepwise descent (bars 1-4)
        (D4,HALF,52),(F4,HALF,50),                             # bar 1
        (A4,WHOLE,56),                                          # bar 2
        (G4,HALF,52),(F4,HALF,50),                             # bar 3
        (E4,HALF,54),(D4,HALF,52),                             # bar 4
        # Section 2: Rising phrase (bars 5-8)
        (F4,HALF,65),(A4,HALF,68),                             # bar 5
        (C5,WHOLE,72),                                          # bar 6
        (B4,HALF,68),(A4,HALF,66),                             # bar 7 — B natural (Dorian!)
        (G4,HALF,68),(F4,HALF,64),                             # bar 8
        # Section 3: High arch (bars 9-12)
        (A4,QTR,78),(B4,QTR,80),(C5,QTR,82),(D5,QTR,84),     # bar 9
        (E5,HALF,88),(D5,HALF,84),                             # bar 10
        (C5,QTR,82),(B4,QTR,78),(A4,QTR,76),(G4,QTR,74),     # bar 11 — B natural
        (F4,HALF,74),(A4,HALF,78),                             # bar 12
        # Section 4: Climax (bars 13-16)
        (D5,QTR,84),(F5,QTR,88),(A5,HALF,92),                 # bar 13
        (A5,HALF,94),(F5,HALF,90),                             # bar 14
        (D5,QTR,86),(C5,QTR,82),(B4,QTR,78),(A4,QTR,74),     # bar 15 — B natural
        (D5,WHOLE,88),                                          # bar 16
        # Section 5: Resolve (bars 17-20)
        (F5,HALF,80),(E5,HALF,76),                             # bar 17
        (D5,QTR,72),(C5,QTR,68),(B4,HALF,66),                 # bar 18 — B natural
        (A4,HALF,62),(F4,HALF,58),                             # bar 19
        (D4,WHOLE,58),                                          # bar 20
    ]

    def bar_sparse(): return [(0,RIDE,34)]
    def bar_mid():    return [(0,RIDE,45),(QTR*2,RIDE,38)]
    def bar_full():   return [(0,CRASH,68),(0,BD,75),(QTR*2,SD,65),(QTR*2,RIDE,50)]
    def bar_climax(): return [(0,CRASH,85),(0,BD,88),(QTR,RIDE,60),(QTR*2,SD,80),(QTR*3,BD,72),(QTR*3,RIDE,55)]

    drums = (
        [bar_sparse()]*4 +
        [bar_mid()]*4 +
        [bar_mid()]*2+[bar_full()]*2 +
        [bar_full()]*2+[bar_climax()]*2 +
        [bar_full()]*2+[bar_mid()]*2
    )
    return bpm, bass, pad, melody, drums


# ── Composition 46: Electric Storm ────────────────────────────────────────────

def comp_electric_storm():
    """Synthwave/Electronic — E minor, 140 BPM, driving arpeggios, 16 bars."""
    bpm = 140
    # E minor: E F# G A B C D
    E1,B1,E2 = _note('E',1),_note('B',1),_note('E',2)
    G1,C2,D2 = _note('G',1),_note('C',2),_note('D',2)
    A1,F2    = _note('A',1),_note('F#',2)
    B2,D3,E3,F3,G3 = _note('B',2),_note('D',3),_note('E',3),_note('F#',3),_note('G',3)
    A3,B3,C4,D4,E4,F4,G4 = (_note('A',3),_note('B',3),_note('C',4),_note('D',4),
                              _note('E',4),_note('F#',4),_note('G',4))
    A4,B4,C5,D5,E5,G5 = (_note('A',4),_note('B',4),_note('C',5),_note('D',5),
                           _note('E',5),_note('G',5))

    Emin  = [E3,G3,B3]
    Cmaj  = [C4,E4,G4]
    Gmaj  = [G3,B3,D4]
    Dmaj  = [D3,F3,A3]
    Amaj  = [A3,C4,E4]

    # Arpeggio bass: 8ths driving pulse
    def arp_em(v=86): return [(E1,EIGHTH,v),(B1,EIGHTH,v-8),(E2,EIGHTH,v-4),(B1,EIGHTH,v-8)] * 2
    def arp_c(v=82):  return [(C2,EIGHTH,v),(G1,EIGHTH,v-8),(E2,EIGHTH,v-4),(G1,EIGHTH,v-8)] * 2
    def arp_g(v=84):  return [(G1,EIGHTH,v),(D2,EIGHTH,v-8),(B1,EIGHTH,v-4),(D2,EIGHTH,v-8)] * 2
    def arp_d(v=82):  return [(D2,EIGHTH,v),(A1,EIGHTH,v-8),(F2,EIGHTH,v-4),(A1,EIGHTH,v-8)] * 2

    bass = (
        arp_em()+arp_c()+arp_g()+arp_d() +    # bars 1-4
        arp_em()+arp_c()+arp_g()+arp_em() +   # bars 5-8
        arp_em(90)+arp_c(86)+arp_g(88)+arp_d(90) +  # bars 9-12 louder
        arp_em(95)+arp_c(90)+arp_g(94)+[(E1,WHOLE,98)]  # bars 13-16 climax
    )

    # Staccato stab chords (8th-note pulse)
    def stab(ch, v=70): return [(ch,EIGHTH,v),(ch,EIGHTH,0)]*4  # on/off 8ths
    def pad_hold(ch, v=66): return [(ch,HALF,v),(ch,HALF,v-8)]

    pad = (
        stab(Emin,68)+stab(Cmaj,64)+stab(Gmaj,66)+stab(Dmaj,64) +
        stab(Emin,70)+stab(Cmaj,66)+stab(Gmaj,68)+pad_hold(Emin,72) +
        stab(Emin,74)+stab(Cmaj,70)+stab(Gmaj,72)+stab(Dmaj,74) +
        stab(Emin,80)+stab(Cmaj,76)+stab(Gmaj,78)+pad_hold(Emin,80)
    )

    melody = [
        # Section A (bars 1-4): arpeggiated synth riff
        (E4,EIGHTH,82),(G4,EIGHTH,80),(B4,EIGHTH,84),(G4,EIGHTH,80),
        (E4,EIGHTH,82),(D4,EIGHTH,78),(E4,QUARTER,84) if False else
        (E4,EIGHTH,82),(G4,EIGHTH,80),(B4,EIGHTH,84),(G4,EIGHTH,80),
        (E4,EIGHTH,82),(D4,EIGHTH,78),(E4,QTR,84),               # bar 1 ← will be wrong length, fix below
    ]
    # Rewrite melody properly:
    melody = [
        # bar 1 Em: 8+8+8+8+8+8+q = 6×EIGHTH+QTR = 3QTR+QTR = WHOLE ✓
        (E4,EIGHTH,82),(G4,EIGHTH,80),(B4,EIGHTH,84),(G4,EIGHTH,80),(E4,EIGHTH,82),(D4,EIGHTH,78),(E4,QTR,84),
        # bar 2 C: stepwise ascent
        (G4,EIGHTH,80),(A4,EIGHTH,82),(B4,EIGHTH,84),(A4,EIGHTH,80),(G4,EIGHTH,78),(F4,EIGHTH,76),(E4,QTR,78),
        # bar 3 G: G-B leap
        (D4,EIGHTH,80),(G4,EIGHTH,82),(B4,EIGHTH,86),(D5,EIGHTH,88),(B4,EIGHTH,84),(G4,EIGHTH,80),(D4,QTR,78),
        # bar 4 D: descend
        (F4,EIGHTH,80),(E4,EIGHTH,78),(D4,EIGHTH,76),(C4,EIGHTH,74),(D4,EIGHTH,76),(E4,EIGHTH,78),(D4,QTR,80),
        # bar 5 Em: repeat A with variation
        (E4,EIGHTH,84),(G4,EIGHTH,82),(B4,EIGHTH,86),(D5,EIGHTH,88),(B4,EIGHTH,84),(G4,EIGHTH,80),(E4,QTR,82),
        # bar 6 C
        (C5,DOTTED_QTR,86),(B4,EIGHTH,82),(A4,HALF,84),
        # bar 7 G
        (B4,DOTTED_QTR,84),(D5,EIGHTH,86),(G4,HALF,82),
        # bar 8 Em (hold)
        (E4,WHOLE,80),
        # Section B (bars 9-12): rising energy
        (E5,EIGHTH,88),(D5,EIGHTH,86),(B4,EIGHTH,84),(A4,EIGHTH,82),(G4,EIGHTH,80),(F4,EIGHTH,78),(E4,QTR,82),
        (G4,EIGHTH,84),(A4,EIGHTH,86),(B4,EIGHTH,88),(C5,EIGHTH,90),(B4,EIGHTH,86),(A4,EIGHTH,84),(G4,QTR,82),
        (D5,DOTTED_QTR,90),(E5,EIGHTH,92),(B4,HALF,88),
        (A4,QTR,86),(G4,QTR,84),(F4,QTR,82),(E4,QTR,80),
        # Section C (bars 13-16): climax
        (E5,EIGHTH,90),(G5,EIGHTH,92),(E5,EIGHTH,90),(B4,EIGHTH,88),(G4,EIGHTH,86),(B4,EIGHTH,88),(E5,QTR,92),
        (D5,DOTTED_QTR,94),(E5,EIGHTH,96),(G5,HALF,98),
        (E5,QTR,96),(D5,QTR,94),(B4,QTR,92),(A4,QTR,90),
        (E4,WHOLE,95),
    ]

    def bar_edm():
        return [(0,BD,96),(0,CRASH,68),(EIGHTH,CHH,52),(QTR,BD,78),(QTR,CHH,55),
                (QTR+EIGHTH,CHH,50),(HALF,BD,90),(HALF,CHH,55),(HALF+EIGHTH,CHH,48),
                (QTR*3,SD,85),(QTR*3,CHH,55),(QTR*3+EIGHTH,CHH,50)]
    def bar_edm_inner():
        return [(0,BD,92),(EIGHTH,CHH,50),(QTR,BD,76),(QTR,CHH,52),(QTR+EIGHTH,CHH,47),
                (HALF,BD,88),(HALF,CHH,52),(HALF+EIGHTH,CHH,46),(QTR*3,SD,82),(QTR*3,CHH,52)]
    def bar_edm_break():
        return [(0,CRASH,92),(0,BD,98),(EIGHTH,BD,74),(QTR,SD,90),(QTR+EIGHTH,CHH,58),
                (HALF,BD,94),(HALF+EIGHTH,CHH,54),(QTR*3,SD,88),(QTR*3,BD,80),(QTR*3,CHH,56)]

    drums = (
        [bar_edm()]+[bar_edm_inner()]*3 +
        [bar_edm()]+[bar_edm_inner()]*3 +
        [bar_edm()]+[bar_edm_inner()]*2+[bar_edm_break()] +
        [bar_edm_break()]*3+[bar_edm()]
    )
    return bpm, bass, pad, melody, drums


# ── Composition: Crimson Overture ────────────────────────────────────────────
def comp_crimson_overture():
    """Dramatic fanfare in D minor — ascending brass triads, sustained woodwind
    chords, driving string bass, and orchestral march percussion."""
    bpm = 120
    # D natural minor: D–E–F–G–A–Bb–C  |  i–VI–III–VII (Dm–Bb–F–C)
    Bb1 = _note('Bb',1)
    C2  = _note('C', 2);  D2  = _note('D', 2);  F2  = _note('F', 2)
    G2  = _note('G', 2);  A2  = _note('A', 2)
    C3  = _note('C', 3);  D3  = _note('D', 3);  E3  = _note('E', 3)
    F3  = _note('F', 3);  G3  = _note('G', 3);  A3  = _note('A', 3)
    Bb2 = _note('Bb',2)
    C4  = _note('C', 4);  D4  = _note('D', 4)
    C5  = _note('C', 5);  D5  = _note('D', 5);  E5  = _note('E', 5)
    F5  = _note('F', 5);  G5  = _note('G', 5);  A5  = _note('A', 5)

    bass = [
        # A section (bars 1–8): 2× Dm–Bb–F–C
        (D2,HALF,90),(A2,HALF,85),                              # bar 1  (i)
        (Bb1,WHOLE,88),                                          # bar 2  (VI)
        (F2,HALF,85),(C2,HALF,80),                              # bar 3  (III)
        (C2,WHOLE,88),                                           # bar 4  (VII)
        (D2,HALF,90),(A2,HALF,85),                              # bar 5  (i)
        (Bb1,WHOLE,88),                                          # bar 6  (VI)
        (F2,QTR,85),(G2,QTR,82),(A2,QTR,85),(F2,QTR,80),      # bar 7  (III–VII movement)
        (D2,WHOLE,96),                                           # bar 8  (i cadence)
        # B section (bars 9–16): development
        (D2,QTR,95),(D2,QTR,90),(A2,QTR,88),(A2,QTR,85),      # bar 9  (i, driving)
        (Bb1,HALF,90),(D2,HALF,86),                              # bar 10 (VI)
        (F2,HALF,88),(C2,HALF,84),                               # bar 11 (III)
        (C2,HALF,90),(G2,HALF,86),                               # bar 12 (VII)
        (D2,QTR,92),(F2,QTR,88),(A2,QTR,90),(D3,QTR,88),      # bar 13 (ascending i)
        (Bb1,HALF,90),(G2,HALF,85),                              # bar 14 (VI)
        (A2,HALF,92),(C3,HALF,88),                               # bar 15 (V7 of i)
        (D2,WHOLE,102),                                          # bar 16 (final i)
    ]

    pad = [
        # A section — half-note chords, building intensity
        ([D3,F3,A3],HALF,78),([D3,F3,A3],HALF,72),             # bar 1  (Dm)
        ([Bb2,D3,F3],WHOLE,76),                                  # bar 2  (Bb)
        ([F3,A3,C4],HALF,74),([F3,A3,C4],HALF,68),             # bar 3  (F)
        ([C3,E3,G3],WHOLE,76),                                   # bar 4  (C)
        ([D3,F3,A3],HALF,82),([D3,F3,A3],HALF,76),             # bar 5  (Dm)
        ([Bb2,D3,F3],WHOLE,80),                                  # bar 6  (Bb)
        ([F3,A3,C4],QTR,76),([F3,A3,C4],QTR,72),([C3,E3,G3],HALF,78),  # bar 7
        ([D3,F3,A3],WHOLE,88),                                   # bar 8  (A-section peak)
        # B section — fuller voicings
        ([D3,F3,A3],HALF,86),([D3,A3,D4],HALF,82),             # bar 9  (Dm + octave)
        ([Bb2,D3,F3],HALF,84),([Bb2,D3,F3],HALF,78),           # bar 10 (Bb)
        ([F3,A3,C4],HALF,82),([F3,A3,C4],HALF,76),             # bar 11 (F)
        ([C3,G3,C4],HALF,84),([C3,E3,G3],HALF,80),             # bar 12 (C open-fifth → triad)
        ([D3,F3,A3],QTR,88),([D3,F3,A3],QTR,84),([D3,A3,D4],HALF,88),  # bar 13
        ([Bb2,D3,F3],HALF,84),([Bb2,G3,D4],HALF,80),           # bar 14 (Bb add6)
        ([A2,E3,A3],WHOLE,90),                                   # bar 15 (Am, dominant of Dm)
        ([D3,F3,A3],WHOLE,96),                                   # bar 16 (final Dm)
    ]

    melody = [
        # A section (bars 1–8)
        # Bar 1 (Dm): ascending triad fanfare
        (D5,QTR,88),(F5,QTR,90),(A5,QTR,92),(G5,QTR,88),
        # Bar 2 (Bb): lyrical resolution
        (F5,DOTTED_QTR,86),(E5,EIGHTH,82),(D5,HALF,85),
        # Bar 3 (F): ascending figure
        (C5,QTR,82),(D5,QTR,84),(E5,QTR,86),(F5,QTR,85),
        # Bar 4 (C): held peaks
        (G5,HALF,88),(A5,HALF,90),
        # Bar 5 (Dm): stepwise descent (answer phrase)
        (A5,QTR,88),(G5,QTR,84),(F5,QTR,82),(E5,QTR,78),
        # Bar 6 (Bb): rocking
        (D5,HALF,82),(C5,QTR,78),(D5,QTR,80),
        # Bar 7 (F→C): stepwise close
        (F5,QTR,84),(E5,QTR,80),(D5,QTR,82),(C5,QTR,78),
        # Bar 8 (Dm): A-section resolution
        (D5,WHOLE,90),
        # B section (bars 9–16) — more intense, rhythmically active
        # Bar 9 (Dm): energetic upbeat fanfare
        (D5,EIGHTH,90),(F5,EIGHTH,92),(A5,QTR,95),(A5,HALF,92),
        # Bar 10 (Bb): peak then fall
        (F5,QTR,90),(G5,QTR,92),(F5,QTR,88),(D5,QTR,85),
        # Bar 11 (F): soaring
        (G5,HALF,90),(A5,HALF,92),
        # Bar 12 (C): dramatic descent from highest point
        (A5,QTR,95),(G5,QTR,90),(F5,QTR,86),(E5,QTR,82),
        # Bar 13 (Dm): building tension
        (D5,QTR,88),(E5,QTR,85),(F5,QTR,88),(G5,QTR,90),
        # Bar 14 (Bb): sustained high
        (F5,HALF,88),(G5,HALF,90),
        # Bar 15 (Am): climactic peak
        (A5,DOTTED_QTR,95),(G5,EIGHTH,90),(A5,HALF,92),
        # Bar 16 (Dm): grand final note
        (D5,WHOLE,100),
    ]

    drums = [
        bar_march(),        # bar 1  (crash opening)
        bar_march_inner(),  # bar 2
        bar_march_inner(),  # bar 3
        bar_march_inner(),  # bar 4
        bar_march(),        # bar 5  (repeat crash)
        bar_march_inner(),  # bar 6
        bar_march_inner(),  # bar 7
        bar_march(),        # bar 8  (A-section close)
        bar_march(),        # bar 9  (B section opens)
        bar_march_inner(),  # bar 10
        bar_march_inner(),  # bar 11
        bar_march_inner(),  # bar 12
        bar_march(),        # bar 13 (inner climax)
        bar_march_inner(),  # bar 14
        bar_march_inner(),  # bar 15
        bar_march(),        # bar 16 (final crash)
    ]

    return bpm, bass, pad, melody, drums


# ── Composition: Silver Morning ──────────────────────────────────────────────
def comp_silver_morning():
    """Gentle pastoral piece in G major — flowing woodwind arpeggios, warm
    lyrical brass melody, sustained string bass, whisper-soft percussion."""
    bpm = 84
    # G major: G–A–B–C–D–E–F#  |  I–vi–IV–V (G–Em–C–D) × 4
    C2  = _note('C', 2);  D2  = _note('D', 2)
    E2  = _note('E', 2);  G2  = _note('G', 2)
    C3  = _note('C', 3);  D3  = _note('D', 3);  E3  = _note('E', 3)
    Fs3 = _note('F#',3);  G3  = _note('G', 3)
    A3  = _note('A', 3);  B3  = _note('B', 3)
    D4  = _note('D', 4)
    Fs4 = _note('F#',4);  G4  = _note('G', 4);  A4  = _note('A', 4)
    B4  = _note('B', 4);  C5  = _note('C', 5)
    D5  = _note('D', 5);  E5  = _note('E', 5)

    # Whole-note bass — one root per bar, cycling I–vi–IV–V × 4
    prog = [G2, E2, C2, D2] * 4
    bass = [(n, WHOLE, 68) for n in prog]

    # Woodwind arpeggios (DOTTED_QTR + QTR + DOTTED_QTR = 1 bar in 4/4)
    def garp(): return [([G3,B3,D4],DOTTED_QTR,60),([G3,B3,D4],QTR,55),([G3,B3,D4],DOTTED_QTR,52)]
    def earp(): return [([E3,G3,B3],DOTTED_QTR,58),([E3,G3,B3],QTR,53),([E3,G3,B3],DOTTED_QTR,50)]
    def carp(): return [([C3,E3,G3],DOTTED_QTR,58),([C3,E3,G3],QTR,53),([C3,E3,G3],DOTTED_QTR,50)]
    def darp(): return [([D3,Fs3,A3],DOTTED_QTR,60),([D3,Fs3,A3],QTR,55),([D3,Fs3,A3],DOTTED_QTR,52)]
    pad = (garp() + earp() + carp() + darp()) * 4

    melody = [
        # Phrase A (bars 1–4): G–Em–C–D
        # Bar 1 (G): gentle rise
        (G4,HALF,70),(B4,QTR,72),(D5,QTR,74),
        # Bar 2 (Em): expressive arc
        (E5,DOTTED_QTR,72),(D5,EIGHTH,68),(B4,HALF,70),
        # Bar 3 (C): stepwise descent
        (C5,QTR,68),(B4,QTR,66),(A4,QTR,64),(G4,QTR,62),
        # Bar 4 (D): open cadence
        (A4,HALF,66),(B4,HALF,68),

        # Phrase A' (bars 5–8): variation
        # Bar 5 (G): rhythmic warmth
        (G4,QTR,70),(A4,QTR,72),(B4,QTR,74),(A4,QTR,72),
        # Bar 6 (Em): linger up
        (B4,HALF,74),(C5,QTR,76),(B4,QTR,74),
        # Bar 7 (C): settling
        (A4,HALF,72),(G4,HALF,70),
        # Bar 8 (D): leading tone
        (Fs4,HALF,68),(A4,HALF,72),

        # Phrase B (bars 9–12): development, brighter
        # Bar 9 (G): climbing
        (D5,QTR,74),(E5,QTR,76),(D5,QTR,74),(B4,QTR,72),
        # Bar 10 (Em): expressive peak
        (E5,HALF,76),(D5,QTR,74),(C5,QTR,72),
        # Bar 11 (C): warm flowing
        (C5,HALF,72),(B4,QTR,70),(A4,QTR,68),
        # Bar 12 (D): motion
        (B4,QTR,70),(A4,QTR,68),(B4,QTR,70),(A4,QTR,66),

        # Phrase A'' (bars 13–16): return and close
        # Bar 13 (G): peaceful reprise
        (G4,HALF,70),(B4,HALF,72),
        # Bar 14 (Em): warm descent
        (B4,DOTTED_QTR,70),(A4,EIGHTH,66),(G4,HALF,68),
        # Bar 15 (C): closing steps
        (A4,QTR,66),(G4,QTR,64),(Fs4,QTR,62),(G4,QTR,66),
        # Bar 16 (G): final long note
        (G4,WHOLE,70),
    ]

    # Whisper-soft percussion — only heartbeat-quiet hits
    soft_tap = [(0, BD, 40), (QTR * 2, SD, 30)]
    drums = [soft_tap] * 16

    return bpm, bass, pad, melody, drums


def comp_mozart_kv545():
    """Score-based piano arrangement of Mozart K.545 first movement, bars 1-20.
    LH: Alberti bass (8th notes) throughout; RH: 16th-note passage work after opening theme.
    Bars 1-4:  Opening theme (C5-D5-E5-F5 | E5-D5-C5½ | G4-A4-B4-C5 | D5-B4-C5½).
    Bars 5-7:  16th-note scalar passage work in C major (I-I-V7).
    Bar 8:     C5 whole note — perfect authentic cadence in C major.
    Bars 9-11: 16th-note bridge modulating toward G dominant (I-V-vi).
    Bar 12:    E5-D5 half notes — brief structural pause.
    Bars 13-14: 16th-note runs in G dominant area.
    Bars 15-16: G5-D5 halfs then G5 whole — G major arrival (half cadence).
    Bars 17-18: 16th-note G major passage work.
    Bars 19-20: G5-F5-E5-D5 quarters then G5 whole — cadential landing.
    """
    BPM = 120

    # ── Left hand: Alberti bass bar templates (8 eighth notes each) ──────────
    def lh_bar(root, fifth, third, vel_r=64, vel_x=50):
        e = EIGHTH
        return [
            (root,e,vel_r),(fifth,e,vel_x),(third,e,vel_x),(fifth,e,vel_x),
            (root,e,vel_r),(fifth,e,vel_x),(third,e,vel_x),(fifth,e,vel_x),
        ]

    LH_C  = lh_bar(48,55,52)  # C3-G3-E3-G3  (C major / I)
    LH_G  = lh_bar(43,50,47)  # G2-D3-B2-D3  (G major / V)
    LH_F  = lh_bar(41,48,45)  # F2-C3-A2-C3  (F major / IV)
    LH_Am = lh_bar(45,52,48)  # A2-E3-C3-E3  (A minor / vi)
    LH_G7 = [                  # G2-D3-F3-D3  (G dominant 7th)
        (43,EIGHTH,64),(50,EIGHTH,50),(53,EIGHTH,50),(50,EIGHTH,50),
        (43,EIGHTH,64),(50,EIGHTH,50),(53,EIGHTH,50),(50,EIGHTH,50),
    ]

    lh_bars = [
        LH_C,  LH_C,  LH_G,  LH_G,   # bars 1-4  (I-I-V-V)  opening theme
        LH_C,  LH_C,  LH_G7, LH_C,   # bars 5-8  (I-I-V7-I) PAC in C
        LH_C,  LH_G,  LH_Am, LH_G7,  # bars 9-12 (I-V-vi-V7) transition
        LH_G,  LH_G,  LH_G7, LH_G,   # bars 13-16 (V area, establishing G dominant)
        LH_G,  LH_G,  LH_G7, LH_G,   # bars 17-20 (G major second theme)
    ]
    lh_seq = [note for bar in lh_bars for note in bar]

    # ── Right hand melody ─────────────────────────────────────────────────────
    # MIDI: G4=67 A4=69 B4=71 C5=72 D5=74 E5=76 F5=77 G5=79 A5=81
    Q, H, W = QTR, HALF, WHOLE
    S = SIXTEENTH
    V = 72  # base melody velocity

    rh_seq = (
        # ── Bars 1-4: Opening "Thema" ─────────────────────────────────────────
        [(72,Q,V),(74,Q,V),(76,Q,V),(77,Q,V)]    +  # Bar 1: C5 D5 E5 F5
        [(76,Q,V),(74,Q,V),(72,H,V)]              +  # Bar 2: E5 D5 C5(h)
        [(67,Q,V),(69,Q,V),(71,Q,V),(72,Q,V)]    +  # Bar 3: G4 A4 B4 C5
        [(74,Q,V),(71,Q,V),(72,H,V)]              +  # Bar 4: D5 B4 C5(h)

        # ── Bars 5-7: 16th-note passage work over I-I-V7 in C major ──────────
        # Bar 5 (I): ascending then descending C major scale in 16ths
        [(72,S,V),(74,S,V),(76,S,V),(77,S,V),(79,S,V),(77,S,V),(76,S,V),(74,S,V),
         (72,S,V),(74,S,V),(76,S,V),(77,S,V),(79,S,V),(81,S,V),(79,S,V),(77,S,V)] +
        # Bar 6 (I): A5 descent to B4 then climb — ~1 octave range
        [(81,S,V),(79,S,V),(77,S,V),(76,S,V),(74,S,V),(72,S,V),(71,S,V),(72,S,V),
         (76,S,V),(77,S,V),(79,S,V),(77,S,V),(76,S,V),(74,S,V),(72,S,V),(71,S,V)] +
        # Bar 7 (V7): G5 descending to G4 over dominant, approach to PAC
        [(79,S,V),(77,S,V),(76,S,V),(74,S,V),(72,S,V),(71,S,V),(69,S,V),(67,S,V),
         (69,S,V),(71,S,V),(69,S,V),(67,S,V),(69,S,V),(71,S,V),(72,S,V),(74,S,V)] +
        # Bar 8 (I): C5 whole note — perfect authentic cadence
        [(72,W,V+4)]                              +

        # ── Bars 9-11: 16th-note bridge sequences toward G major ──────────────
        # Bar 9 (I): E5 ascending run C5→A5 then back down
        [(76,S,V),(77,S,V),(79,S,V),(81,S,V),(79,S,V),(77,S,V),(76,S,V),(74,S,V),
         (72,S,V),(74,S,V),(76,S,V),(77,S,V),(79,S,V),(77,S,V),(76,S,V),(74,S,V)] +
        # Bar 10 (V): G5 down to G4 then back up — 1 octave range
        [(79,S,V),(77,S,V),(76,S,V),(74,S,V),(72,S,V),(71,S,V),(69,S,V),(67,S,V),
         (69,S,V),(71,S,V),(69,S,V),(67,S,V),(69,S,V),(71,S,V),(72,S,V),(74,S,V)] +
        # Bar 11 (vi): ascending Am run A4→A5 and back to A4
        [(69,S,V),(71,S,V),(72,S,V),(74,S,V),(76,S,V),(77,S,V),(79,S,V),(81,S,V),
         (79,S,V),(77,S,V),(76,S,V),(74,S,V),(72,S,V),(71,S,V),(69,S,V),(71,S,V)] +
        # Bar 12 (V7): E5(h) D5(h) — settling on D5 before G major area
        [(76,H,V),(74,H,V)]                       +

        # ── Bars 13-16: G major dominant region — 16th runs then cadential landing
        # Bar 13 (V): ascending G major run D5→A5 and back in 16ths
        [(74,S,V),(76,S,V),(77,S,V),(79,S,V),(81,S,V),(79,S,V),(77,S,V),(76,S,V),
         (74,S,V),(76,S,V),(77,S,V),(79,S,V),(77,S,V),(76,S,V),(74,S,V),(72,S,V)] +
        # Bar 14 (V): B4→G5 ascending then back down to A4 — ~1 octave
        [(71,S,V),(72,S,V),(74,S,V),(76,S,V),(77,S,V),(79,S,V),(77,S,V),(76,S,V),
         (74,S,V),(72,S,V),(71,S,V),(69,S,V),(71,S,V),(72,S,V),(74,S,V),(76,S,V)] +
        # Bar 15 (V7): G5(h) D5(h) — landing on half notes, cadential approach
        [(79,H,V),(74,H,V)]                       +
        # Bar 16 (V): G5 whole — G major firmly established (half cadence)
        [(79,W,V+4)]                              +

        # ── Bars 17-20: G major passage work → cadential landing ────────────
        # Bar 17 (V): ascending D5→A5 then back — G major scalar run in 16ths
        [(74,S,V),(76,S,V),(77,S,V),(79,S,V),(81,S,V),(79,S,V),(77,S,V),(76,S,V),
         (74,S,V),(72,S,V),(71,S,V),(69,S,V),(67,S,V),(69,S,V),(71,S,V),(72,S,V)] +
        # Bar 18 (V): ascending B4→A5 then back to G4 — continuing G major run
        [(71,S,V),(72,S,V),(74,S,V),(76,S,V),(77,S,V),(79,S,V),(81,S,V),(79,S,V),
         (77,S,V),(76,S,V),(74,S,V),(72,S,V),(71,S,V),(69,S,V),(67,S,V),(69,S,V)] +
        # Bar 19 (V7): G5 F5 E5 D5 — quarters, settling into final cadence
        [(79,Q,V),(77,Q,V),(76,Q,V),(74,Q,V)]    +
        # Bar 20 (V): G5 whole — G major arrival, end of excerpt
        [(79,W,V+6)]
    )

    return lh_seq, rh_seq, BPM


CATALOG = {
    'orchestral_piece': {
        'title': 'Orchestral Piece',
        'genre': 'Orchestral',
        'mood': 'Majestic',
        'bpm': 80,
        'key': 'C Major',
        'bars': 8,
        'description': 'A full 8-bar orchestral arrangement — lyrical strings open softly and build to a grand tutti cadence in C Major.',
        'fn': comp_orchestral_piece,
    },
    'heroic_march': {
        'title': 'Heroic March',
        'genre': 'Orchestral',
        'mood': 'Triumphant',
        'bpm': 120,
        'key': 'C Major',
        'bars': 16,
        'description': 'A bold fanfare march with driving bass, full chords, and a soaring fanfare melody in two acts.',
        'fn': comp_heroic_march,
    },
    'forest_wanderer': {
        'title': 'Forest Wanderer',
        'genre': 'Ambient',
        'mood': 'Peaceful',
        'bpm': 68,
        'key': 'F Major',
        'bars': 16,
        'description': 'A gentle 16-bar journey through an ancient forest — flowing arpeggios, lyrical melody with an upper-register bloom in the final phrase.',
        'fn': comp_forest_wanderer,
    },
    'battle_cry': {
        'title': 'Battle Cry',
        'genre': 'Action',
        'mood': 'Intense',
        'bpm': 145,
        'key': 'D Minor',
        'bars': 20,
        'description': 'Relentless eighth-note drive, power chords, heavy drums — three escalating waves of D minor fury with a final fortissimo climax.',
        'fn': comp_battle_cry,
    },
    'tavern_jig': {
        'title': 'Tavern Jig',
        'genre': 'Folk',
        'mood': 'Lively',
        'bpm': 168,
        'key': 'G Major',
        'bars': 16,
        'description': 'A lively 16-bar jig for dancing — fast 8th-note bass, staccato chords, playful melody building to a rousing triumphant finale.',
        'fn': comp_tavern_jig,
    },
    'sad_elegy': {
        'title': 'Sad Elegy',
        'genre': 'Classical',
        'mood': 'Melancholic',
        'bpm': 52,
        'key': 'A Minor',
        'bars': 16,
        'description': 'A slow, deeply emotional elegy — half-note chords with a 4-phrase dynamic arc from quiet resignation to cathartic climax.',
        'fn': comp_sad_elegy,
    },
    'dungeon_depths': {
        'title': 'Dungeon Depths',
        'genre': 'Ambient',
        'mood': 'Mysterious',
        'bpm': 76,
        'key': 'B Minor',
        'bars': 16,
        'description': 'Dark and eerie — ostinato bass, sparse dissonant chords, lonely high melody with long rests.',
        'fn': comp_dungeon_depths,
    },
    'victory_fanfare': {
        'title': 'Victory Fanfare',
        'genre': 'Orchestral',
        'mood': 'Celebratory',
        'bpm': 138,
        'key': 'G Major',
        'bars': 20,
        'description': 'A triumphant fanfare — bold bass, crash-heavy march drums, ascending fanfare figure into a grand coda and a blazing grandioso finale on G5.',
        'fn': comp_victory_fanfare,
    },
    'peaceful_village': {
        'title': 'Peaceful Village',
        'genre': 'Pastoral',
        'mood': 'Warm',
        'bpm': 88,
        'key': 'C Major',
        'bars': 16,
        'description': 'A warm village theme — walking quarter-note arpeggios (C-Am-F-G), structured A/A2/B/return melody.',
        'fn': comp_peaceful_village,
    },
    'dragons_lair': {
        'title': "Dragon's Lair",
        'genre': 'Action',
        'mood': 'Fierce',
        'bpm': 155,
        'key': 'E Minor',
        'bars': 16,
        'description': 'Final boss energy — driving bass ostinato, power chords, chromatic descents, blasting drums. Two brutal acts.',
        'fn': comp_dragons_lair,
    },
    'twilight_lullaby': {
        'title': 'Twilight Lullaby',
        'genre': 'Classical',
        'mood': 'Gentle',
        'bpm': 62,
        'key': 'D Major',
        'bars': 16,
        'timeSig': '3/4',
        'description': 'A tender 3/4 waltz — gentle arpeggios, stepwise melody, soft waltz drums, closing with a hushed farewell passage.',
        'fn': comp_twilight_lullaby,
    },
    'celtic_dawn': {
        'title': 'Celtic Dawn',
        'genre': 'Celtic',
        'mood': 'Spirited',
        'bpm': 96,
        'key': 'E Minor',
        'bars': 16,
        'description': 'A spirited 16-bar Celtic piece — modal Em-G-D-Am, pentatonic 8th-note runs, bodhran drums, soaring to a grand finale.',
        'fn': comp_celtic_dawn,
    },
    'moonlight_reverie': {
        'title': 'Moonlight Reverie',
        'genre': 'Classical',
        'mood': 'Romantic',
        'bpm': 72,
        'key': 'Bb Major',
        'bars': 16,
        'description': 'A nocturne in Bb Major — lush 7th chords, singing melody with chromatic Ab passing tones, gentle brushed percussion.',
        'fn': comp_moonlight_reverie,
    },
    'passacaglia': {
        'title': 'Passacaglia',
        'genre': 'Classical',
        'mood': 'Solemn',
        'bpm': 80,
        'key': 'D Minor',
        'bars': 16,
        'description': 'A baroque passacaglia — descending D-C-Bb-A tetrachord bass repeated four times, each variation building from quiet introduction through flowing 8th-note motion to a fortissimo grandioso finale.',
        'fn': comp_passacaglia,
    },
    'midnight_blues': {
        'title': 'Midnight Blues',
        'genre': 'Jazz',
        'mood': 'Soulful',
        'bpm': 88,
        'key': 'G Minor',
        'bars': 16,
        'description': 'A jazz nocturne in G Minor — walking bass, lush 7th-chord comping, bluesy melody with chromatic F♯ leading tones and a two-bar silent intro.',
        'fn': comp_midnight_blues,
    },
    'silk_road': {
        'title': 'Silk Road',
        'genre': 'World',
        'mood': 'Exotic',
        'bpm': 80,
        'key': 'A Hijaz',
        'bars': 16,
        'description': 'Ancient trade routes in sound — Hijaz-scale drone bass, lush suspended chords, an ornamental melody featuring the characteristic Bb–C♯ augmented-second tension.',
        'fn': comp_silk_road,
    },
    'haunted_manor': {
        'title': 'Haunted Manor',
        'genre': 'Horror',
        'mood': 'Eerie',
        'bpm': 55,
        'key': 'D Minor',
        'bars': 16,
        'description': 'Shadows and silence — deep chromatic bass descent through D minor, dim7 chord clusters, a heartbeat pulse, and sparse eerie melodic fragments with tritone tensions.',
        'fn': comp_haunted_manor,
    },
    'river_street_rag': {
        'title': 'River Street Rag',
        'genre': 'Jazz',
        'mood': 'Playful',
        'bpm': 104,
        'key': 'C Major',
        'bars': 16,
        'description': 'A lively stride-piano ragtime in C major — syncopated melody with off-beat accents, stride bass, and a classic A/B strain form with a rousing finish.',
        'fn': comp_ragtime,
    },
    'crimson_tango': {
        'title': 'Crimson Tango',
        'genre': 'Latin',
        'mood': 'Passionate',
        'bpm': 116,
        'key': 'D Minor',
        'bars': 16,
        'description': 'A dramatic Argentine tango in D minor — driving habanera bass, staccato chord stabs, and a passionate melody that builds to an intense climax.',
        'fn': comp_crimson_tango,
    },
    'neon_drift': {
        'title': 'Neon Drift',
        'genre': 'Electronic',
        'mood': 'Dreamy',
        'bpm': 128,
        'key': 'A Minor',
        'bars': 16,
        'description': 'A synthwave journey in A minor — pulsing arpeggio bass, held pad chords, a soaring synth melody, and a driving 4-on-the-floor drum machine.',
        'fn': comp_neon_drift,
    },
    'delta_blues': {
        'title': 'Delta Blues',
        'genre': 'Blues',
        'mood': 'Soulful',
        'bpm': 76,
        'key': 'E Minor',
        'bars': 16,
        'description': 'A slow Delta Blues in E — shuffling swing hi-hats, walking quarter-note bass, dominant-7th chord stabs, and a call-and-response melody built on the blues scale.',
        'fn': comp_delta_blues,
    },
    'bossa_nova': {
        'title': 'Rio Breeze',
        'genre': 'Bossa Nova',
        'mood': 'Relaxed',
        'bpm': 130,
        'key': 'D Major',
        'bars': 16,
        'description': 'A smooth Bossa Nova in D major — syncopated bass, jazzy Dmaj7/G7/A7 chord stabs, a flowing melody with chromatic passing tones, and a light clave-inspired rhythm.',
        'fn': comp_bossa_nova,
    },
    'flamenco': {
        'title': 'Andalusian Night',
        'genre': 'Flamenco',
        'mood': 'Passionate',
        'bpm': 142,
        'key': 'A Minor',
        'bars': 16,
        'description': 'A fiery Flamenco in A minor — the iconic Andalusian descending cadence (Am–G–F–E), Phrygian dominant E7 chord stabs with raised G♯, and a spirited melody with characteristic chromatic ornaments.',
        'fn': comp_flamenco,
    },
    'baroque_minuet': {
        'title': 'Garden Minuet',
        'genre': 'Baroque',
        'mood': 'Elegant',
        'bpm': 116,
        'key': 'G Major',
        'bars': 24,
        'timeSig': '3/4',
        'description': 'A stately Baroque minuet in G major — crisp oom-pah-pah bass, block chords, and a three-section dance with characteristic dotted rhythms and ornamental grace notes in the final repeat.',
        'fn': comp_baroque_minuet,
    },
    'kingston_sunrise': {
        'title': 'Kingston Sunrise',
        'genre': 'Reggae',
        'mood': 'Laid-back',
        'bpm': 82,
        'key': 'G Major',
        'bars': 16,
        'description': 'A sunny reggae groove in G major — authentic one-drop drumming where the kick and snare land together on beat 3, melodic off-beat skank chords, and a singable melody with F♯ leading tones over I–IV–V7 changes.',
        'fn': comp_reggae,
    },
    'glory_road': {
        'title': 'Glory Road',
        'genre': 'Gospel',
        'mood': 'Jubilant',
        'bpm': 88,
        'key': 'Bb Major',
        'bars': 16,
        'description': 'A jubilant gospel anthem in B♭ major — strong backbeat snare on beats 2 and 4, rich Bb/Eb/F7 harmony, and a soaring two-section melody that builds from a call phrase to a triumphant high-note climax.',
        'fn': comp_gospel,
    },
    'groove_engine': {
        'title': 'Groove Engine',
        'genre': 'Funk',
        'mood': 'Driving',
        'bpm': 96,
        'key': 'E Minor',
        'bars': 16,
        'description': 'A tight funk groove in E minor — 16th-note hi-hat feel, syncopated dotted-eighth bass ostinato, off-beat chord stabs on every upbeat, and a pentatonic melody with D♯ leading tones over the V7 chord.',
        'fn': comp_funk,
    },
    'blue_ridge_morning': {
        'title': 'Blue Ridge Morning',
        'genre': 'Country',
        'mood': 'Warm',
        'bpm': 100,
        'key': 'G Major',
        'bars': 16,
        'description': 'A warm country piece in G major — boom-chick bass with alternating root and 5th, crisp beats-2-and-4 chord stabs, and a singable diatonic melody through a I–V–IV–I verse, a vi–IV–I–V bridge, and a I–IV–V–I finale.',
        'fn': comp_country,
    },
    'soul_searching': {
        'title': 'Soul Searching',
        'genre': 'Soul',
        'mood': 'Soulful',
        'bpm': 76,
        'key': 'A Minor',
        'bars': 16,
        'description': 'A deeply expressive Soul/R&B piece in A minor — syncopated bass groove, lush Am7–Dm7–Cmaj7–E7 chord comping with a signature dotted-eighth feel, a wide-interval melody built on the A minor blues scale, and a strong backbeat with ghost snare pops on every upbeat.',
        'fn': comp_soul,
    },
    'swing_city': {
        'title': 'Swing City',
        'genre': 'Swing',
        'mood': 'Lively',
        'bpm': 152,
        'key': 'Bb Major',
        'bars': 24,
        'description': 'A big-band swing number in B♭ major — walking quarter-note bass through I–vi–ii–V changes, backbeat chord comping on beats 2 and 4, ride cymbal groove, a lyrical bridge, and a blazing 4-bar shout chorus that climbs to B♭5.',
        'fn': comp_swing,
    },
    'lagos_groove': {
        'title': 'Lagos Groove',
        'genre': 'Afrobeat',
        'mood': 'Groovy',
        'bpm': 116,
        'key': 'G Minor',
        'bars': 16,
        'description': 'A pulsing Afrobeat groove in G minor — syncopated bass with octave jumps, highlife-style off-beat guitar chops, low-tom clave accents, and a call-and-response melody over a Gm–B♭–F–Cm vamp.',
        'fn': comp_afrobeat,
    },
    'sacred_chorale': {
        'title': 'Sacred Chorale',
        'genre': 'Classical',
        'mood': 'Solemn',
        'bpm': 56,
        'key': 'D Major',
        'bars': 16,
        'description': 'A Bach-style SATB chorale in D major — four-voice block harmony, cantus firmus soprano melody rising to E5 at the climax, with relative-minor coloring through Bm and Em before the final Amen cadence.',
        'fn': comp_sacred_chorale,
    },
    'viennese_waltz': {
        'title': 'Viennese Waltz',
        'genre': 'Waltz',
        'mood': 'Elegant',
        'bpm': 126,
        'key': 'A Major',
        'bars': 24,
        'description': 'A spirited Viennese waltz in A major — classic oom-pah-pah bass with two-chord pah pattern, a singing melody through I–V7 and vi–ii–V7–I progressions, rising to a triumphant B-section peak at A5 before a soft ornamental reprise.',
        'fn': comp_viennese_waltz,
    },
    'morning_mist': {
        'title': 'Morning Mist',
        'genre': 'Impressionist',
        'mood': 'Dreamy',
        'bpm': 60,
        'key': 'Eb Major',
        'bars': 16,
        'description': 'A Debussy-inspired impressionist piece in Eb major — slow pedal-tone bass, shimmering arpeggiated maj7/9 chords (Ebmaj7, Abmaj9, Fm7, Gm7), and a floating pentatonic melody that rises to Ab5 at the central climax before drifting gently home.',
        'fn': comp_morning_mist,
    },
    'samba_carnival': {
        'title': 'Samba Carnival',
        'genre': 'World',
        'mood': 'Festive',
        'bpm': 108,
        'key': 'E Major',
        'bars': 16,
        'description': 'A high-energy samba in E major — surdo-style syncopated bass with offbeat bounces, violão chord stabs on the upbeats, bright staccato melody climbing to A5, and a driving batucada drum pattern.',
        'fn': comp_samba_carnival,
    },
    'glass_etude': {
        'title': 'Glass Étude',
        'genre': 'Minimalist',
        'mood': 'Hypnotic',
        'bpm': 84,
        'key': 'C Major',
        'bars': 16,
        'description': 'A Philip Glass-inspired minimalist étude in C major — slow pedal-tone bass over shifting I–IV–V–vi harmony, hypnotic additive arpeggios cycling through 8-note patterns, and a sparse long-note melody floating above.',
        'fn': comp_glass_etude,
    },
    'polka_village': {
        'title': 'Polka Village',
        'genre': 'Polka',
        'mood': 'Festive',
        'bpm': 132,
        'key': 'G Major',
        'bars': 16,
        'description': 'A lively Czech polka in G major — oom-pah bass with root–5th alternation, crisp off-beat chord stabs, and a melody with stepwise 8th-note runs, dotted rhythms, and a rousing final bar of cascading 8ths down to G4.',
        'fn': comp_polka_village,
    },
    'appalachian_fire': {
        'title': 'Appalachian Fire',
        'genre': 'Bluegrass',
        'mood': 'Joyful',
        'bpm': 160,
        'key': 'G Major',
        'bars': 16,
        'description': 'A blistering bluegrass hoedown in G major — boom-chick walking bass with root–fifth alternation, crisp off-beat mandolin chops, and a breakneck fiddle melody burning through pentatonic runs up to G5.',
        'fn': comp_appalachian_fire,
    },
    'klezmer_dance': {
        'title': 'Klezmer Dance',
        'genre': 'Klezmer',
        'mood': 'Festive',
        'bpm': 134,
        'key': 'D Minor',
        'bars': 16,
        'description': 'A freylekhs-style klezmer dance in D minor — oompah bass with root–fifth alternation, whole-note Dm/Gm/Am block chords, and a clarinet melody weaving chromatic Eb (Phrygian 2nd) and C# (raised 7th) into fast 8th-note runs with a rousing finale.',
        'fn': comp_klezmer_dance,
    },
    'urban_pulse': {
        'title': 'Urban Pulse',
        'genre': 'Hip-Hop',
        'mood': 'Driving',
        'bpm': 88,
        'key': 'C Minor',
        'bars': 16,
        'description': 'A dark hip-hop groove in C minor — heavy syncopated kick, Cm/Ab/Bb/Fm harmonic changes, and a pentatonic hook that builds from a mid-range call to a blazing upper-register finale.',
        'fn': comp_urban_pulse,
    },
    'crimson_dawn': {
        'title': 'Crimson Dawn',
        'genre': 'Cinematic',
        'mood': 'Epic',
        'bpm': 72,
        'key': 'D Minor',
        'bars': 20,
        'description': 'A sweeping cinematic build in D minor — the Dm/Bb/F/C progression rises from hushed half-note strings through to a fortissimo orchestral climax at bar 13, then resolves with a quiet, noble coda.',
        'fn': comp_crimson_dawn,
    },
    'sakura_dreams': {
        'title': 'Sakura Dreams',
        'genre': 'World',
        'mood': 'Serene',
        'bpm': 88,
        'key': 'G Major',
        'bars': 16,
        'description': 'A Japanese-inspired pentatonic journey in G major — sparse koto-style percussion, flowing arpeggiated bass, and a melody that leaps freely through G–A–B–D–E, evoking cherry blossoms drifting in still air.',
        'fn': comp_sakura_dreams,
    },
    'lost_cathedral': {
        'title': 'Lost Cathedral',
        'genre': 'Classical',
        'mood': 'Solemn',
        'bpm': 52,
        'key': 'D Dorian',
        'bars': 20,
        'description': 'A hauntingly beautiful piece in D Dorian — the raised 6th degree (B♮) gives it an ancient, sacred quality as the melody climbs from whispered half notes to a resonant fortissimo arch, then fades into quiet mystery.',
        'fn': comp_lost_cathedral,
    },
    'electric_storm': {
        'title': 'Electric Storm',
        'genre': 'Electronic',
        'mood': 'Intense',
        'bpm': 140,
        'key': 'E Minor',
        'bars': 16,
        'description': 'A pounding synthwave storm in E minor — relentless arpeggio bass, staccato chord stabs, a soaring synth melody cutting through the noise, and a four-on-the-floor kick that drives everything forward.',
        'fn': comp_electric_storm,
    },
    'crimson_overture': {
        'title': 'Crimson Overture',
        'genre': 'Orchestral',
        'mood': 'Dramatic',
        'bpm': 120,
        'key': 'D Minor',
        'bars': 16,
        'description': 'A dramatic D-minor fanfare — brass triads surge upward, woodwinds sustain dark harmonies, strings drive the march bass, and the orchestra builds to a blazing fortissimo close.',
        'fn': comp_crimson_overture,
    },
    'silver_morning': {
        'title': 'Silver Morning',
        'genre': 'Pastoral',
        'mood': 'Serene',
        'bpm': 84,
        'key': 'G Major',
        'bars': 16,
        'description': 'A gentle G-major pastoral — woodwinds weave flowing arpeggios, brass sings a warm lyrical melody across four phrases, and strings hold the harmonic ground beneath a whisper of percussion.',
        'fn': comp_silver_morning,
    },
    'mozart_kv545': {
        'title': 'Sonata in C, K.545',
        'genre': 'Classical',
        'mood': 'Elegant',
        'bpm': 120,
        'key': 'C Major',
        'bars': 20,
        'piano': True,
        'description': 'Mozart\'s Sonata facile — 20 bars of the famous Allegro first movement, with Alberti bass in the left hand and a simple, singing melody in the right.',
        'fn': comp_mozart_kv545,
    },
}

# ── Generate all MIDI files ────────────────────────────────────────────────────

# Pieces where the melody is played by strings/orchestral instruments.
# These get legato note overlap (triggers Kontakt legato engine) and bow accents.
STRING_PIECES = {
    'heroic_march', 'forest_wanderer', 'battle_cry', 'sad_elegy',
    'dungeon_depths', 'victory_fanfare', 'peaceful_village', 'dragons_lair',
    'twilight_lullaby', 'celtic_dawn', 'moonlight_reverie', 'silk_road',
    'haunted_manor', 'crimson_tango', 'baroque_minuet', 'flamenco',
    'blue_ridge_morning', 'appalachian_fire', 'soul_searching', 'passacaglia', 'sacred_chorale',
    'viennese_waltz', 'morning_mist', 'glass_etude',
    'crimson_dawn',       # cinematic: soaring string melody with legato
    'lost_cathedral',     # dorian modal: sustained legato strings
    'sakura_dreams',      # japanese: flowing lyrical melody
    'crimson_overture',   # D-minor fanfare: legato brass melody
    'silver_morning',     # G-major pastoral: lyrical melody with legato
}

# Maps each genre to the Albion ONE BGM template with the best matching timbre.
GENRE_TEMPLATE = {
    'Orchestral':  'BGM_Orchestral',
    'Electronic':  'BGM_Orchestral',
    'Classical':   'BGM_Strings',
    'Baroque':     'BGM_Strings',
    'Ambient':     'BGM_Strings',
    'Jazz':        'BGM_Strings',
    'Soul':        'BGM_Strings',
    'Gospel':      'BGM_Strings',
    'Swing':       'BGM_Strings',
    'Bossa Nova':  'BGM_Strings',
    'Folk':        'BGM_Woodwinds',
    'Celtic':      'BGM_Woodwinds',
    'Pastoral':    'BGM_Woodwinds',
    'Country':     'BGM_Woodwinds',
    'Action':      'BGM_Brass',
    'Horror':      'BGM_Brass',
    'Latin':       'BGM_Brass',
    'World':       'BGM_World',
    'Flamenco':    'BGM_World',
    'Blues':       'BGM_World',
    'Reggae':      'BGM_World',
    'Funk':        'BGM_World',
    'Afrobeat':    'BGM_World',
    'Waltz':       'BGM_Strings',
    'Impressionist': 'BGM_Strings',
    'Minimalist':  'BGM_Strings',
    'Polka':       'BGM_Woodwinds',
    'Bluegrass':   'BGM_Woodwinds',
    'Klezmer':     'BGM_Woodwinds',
    'Hip-Hop':     'BGM_World',
    'Cinematic':   'BGM_Orchestral',
}

def generate_all():
    os.makedirs(OUT_BASE, exist_ok=True)
    for piece_id, meta in CATALOG.items():
        if meta['fn'] is None:
            print(f'  [skip] {piece_id} (already rendered)')
            continue
        print(f'  [{piece_id}] generating...')
        try:
            # ── Piano pieces: both hands on channel 6 (piano slot), in pad.mid ──
            if meta.get('piano'):
                lh_seq, rh_seq, bpm_val = meta['fn']()
                seed = sum(ord(c) for c in piece_id)
                rng = random.Random(seed)
                # Light humanization: Alberti bass slightly detached, melody near-legato
                lh_hum = humanize(lh_seq, jitter=4, rng=rng)
                rh_hum = humanize(rh_seq, jitter=6, rng=rng)
                lh_art = [(n, d, v, max(1, int(d * 0.72))) for n, d, v in lh_hum]
                rh_art = [(n, d, v, max(1, int(d * 0.96))) for n, d, v in rh_hum]
                pad_trk = piano_pad_trk(6, lh_art, rh_art, bpm_val)  # ch 6 = piano slot
                sil = empty_trk(bpm_val)
                out_dir = os.path.join(OUT_BASE, piece_id)
                os.makedirs(out_dir, exist_ok=True)
                files = {
                    'bass.mid':   midi([sil]),
                    'pad.mid':    midi([pad_trk]),
                    'melody.mid': midi([sil]),
                    'drums.mid':  midi([sil]),
                }
                for fname, data in files.items():
                    with open(os.path.join(out_dir, fname), 'wb') as f: f.write(data)
                print(f'    OK (piano): {sum(len(d) for d in files.values())} bytes total')
                continue

            result = meta['fn']()
            # handle 3/4 (twilight_lullaby returns extra bar_ticks)
            if len(result) == 6:
                bpm, bass, pad, melody, drums_bars, bar_ticks = result
                top = 3
            else:
                bpm, bass, pad, melody, drums_bars = result
                bar_ticks = WHOLE
                top = 4

            # Deterministic humanization per piece (same seed → same render each time)
            seed = sum(ord(c) for c in piece_id)
            rng = random.Random(seed)

            use_strings = piece_id in STRING_PIECES
            bass   = humanize(articulate(bass, slow_ratio=0.92 if use_strings else 0.90), jitter=7, rng=rng)
            pad    = humanize_chords(pad, jitter=5, rng=rng)
            melody = humanize(articulate(melody, fast_ratio=0.55, slow_ratio=0.92, legato=use_strings), jitter=9, rng=rng)
            if use_strings:
                melody = bow_accents(melody)
            drums_bars = humanize_drums(drums_bars, jitter=6, rng=rng)

            # Piece-level dynamic arc: subtle crescendo from opening to climax (all pieces)
            total_ticks = bar_ticks * meta['bars']
            bass   = piece_arc(bass,   total_ticks)
            pad    = piece_arc(pad,    total_ticks)
            melody = piece_arc(melody, total_ticks)

            # Phrase-level dynamics (4-bar bell curve) — most melodic/expressive pieces
            PHRASE_ARC_PIECES = {
                'sad_elegy', 'forest_wanderer', 'moonlight_reverie', 'twilight_lullaby',
                'delta_blues', 'glory_road', 'dungeon_depths', 'peaceful_village',
                'haunted_manor', 'celtic_dawn', 'midnight_blues', 'blue_ridge_morning',
                'bossa_nova', 'silk_road', 'soul_searching', 'swing_city', 'lagos_groove',
                'crimson_tango', 'flamenco', 'baroque_minuet', 'tavern_jig',
                'river_street_rag', 'kingston_sunrise', 'heroic_march', 'passacaglia',
                'sacred_chorale', 'viennese_waltz', 'morning_mist', 'glass_etude',
                'polka_village', 'appalachian_fire', 'klezmer_dance',
                'crimson_dawn',       # cinematic: phrase arcs essential for build/release arc
                'lost_cathedral',     # dorian: long phrases need breath + swell shaping
                'sakura_dreams',      # japanese: meditative phrase arc
                'crimson_overture',   # D-minor fanfare: 4-bar phrase arcs shape the build
                'silver_morning',     # G-major pastoral: gentle bell-curve dynamics per phrase
            }
            if piece_id in PHRASE_ARC_PIECES:
                phrase_t = bar_ticks * 4
                melody = phrase_arc(melody, phrase_t, v_lo_pct=86, v_hi_pct=114, peak_pos=0.65)

            out_dir = os.path.join(OUT_BASE, piece_id)
            os.makedirs(out_dir, exist_ok=True)

            swing = piece_id in {'midnight_blues', 'river_street_rag', 'delta_blues', 'swing_city'}
            # Timing jitter (micro-timing humanization): 12 ticks ≈ 2.5% of a beat at 480 TPB
            # Stronger for jazz/blues (feel-based genres), lighter for strict genres
            TIGHT_TIMING = {'baroque_minuet', 'heroic_march', 'victory_fanfare', 'tavern_jig',
                            'neon_drift', 'groove_engine', 'battle_cry', 'dragons_lair',
                            'polka_village', 'appalachian_fire', 'klezmer_dance',
                            'electric_storm'}
            t_jitter = 6 if piece_id in TIGHT_TIMING else 14
            bass_trk   = notes_trk(0, bass, bpm, top, timing_jitter=t_jitter // 2, rng=rng)
            pad_trk    = chords_trk(1, pad, bpm, top)
            melody_trk = notes_trk(2, melody, bpm, top, swing=swing, timing_jitter=t_jitter, rng=rng)
            drum_trk   = drums_trk(drums_bars, bpm, top, bar_ticks)

            files = {
                'bass.mid':   midi([bass_trk]),
                'pad.mid':    midi([pad_trk]),
                'melody.mid': midi([melody_trk]),
                'drums.mid':  midi([drum_trk]),
            }
            for fname, data in files.items():
                fp = os.path.join(out_dir, fname)
                with open(fp, 'wb') as f:
                    f.write(data)
            total = sum(len(d) for d in files.values())
            print(f'    OK: 4 MIDI files, {total} bytes total')
        except Exception as e:
            import traceback
            print(f'    ERROR: {e}')
            traceback.print_exc()

if __name__ == '__main__':
    print('Generating showcase MIDI files...')
    generate_all()
    print(f'\nDone. Files in: {OUT_BASE}')
