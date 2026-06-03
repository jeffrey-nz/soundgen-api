"""
midi_synth.py — Pure Python MIDI-to-WAV synthesizer.

Reads 4 MIDI files (bass, pad, melody, drums) and mixes them into a single
stereo WAV using additive synthesis.  No external tools required — only
numpy, scipy (for filtering), mido, and Python's built-in wave module.

Usage (standalone):
    python midi_synth.py --out output.wav --bpm 120 --bass bass.mid \
                         --pad pad.mid --melody melody.mid --drums drums.mid

Or import and call synth_piece() directly.
"""
import wave, struct, math, argparse, os, time
import numpy as np
import mido

SR = 44100   # sample rate
MAX_AMP = 0.90  # peak amplitude (headroom)

# ── Note/frequency helpers ────────────────────────────────────────────────────

def midi_freq(note):
    return 440.0 * (2.0 ** ((note - 69) / 12.0))

# ── Envelope ──────────────────────────────────────────────────────────────────

def adsr(n_samples, attack, decay, sustain_level, release, sr=SR):
    a = max(1, int(attack * sr))
    d = max(1, int(decay  * sr))
    r = max(1, int(release * sr))
    s = max(0, n_samples - a - d - r)
    if a + d + r > n_samples:
        # Compress to fit
        total = a + d + r
        a = max(1, a * n_samples // total)
        d = max(1, d * n_samples // total)
        r = max(1, r * n_samples // total)
        s = max(0, n_samples - a - d - r)
    env = np.concatenate([
        np.linspace(0.0, 1.0, a),
        np.linspace(1.0, sustain_level, d),
        np.full(s, sustain_level),
        np.linspace(sustain_level, 0.0, r),
    ])
    return env[:n_samples]

# ── Waveform generators ───────────────────────────────────────────────────────

def saw(freq, n, sr=SR):
    t = np.arange(n) / sr
    return 2.0 * (t * freq % 1.0) - 1.0

def sine(freq, n, sr=SR):
    t = np.arange(n) / sr
    return np.sin(2 * math.pi * freq * t)

def square(freq, n, sr=SR):
    t = np.arange(n) / sr
    return np.sign(np.sin(2 * math.pi * freq * t)).astype(float)

def triangle(freq, n, sr=SR):
    t = np.arange(n) / sr
    return 2.0 * np.abs(2.0 * (t * freq % 1.0) - 1.0) - 1.0

# ── Instrument voices ─────────────────────────────────────────────────────────

def voice_bass(note, n, velocity, sr=SR):
    """Bass: warm bandlimited saw + sub, filtered for low-end weight."""
    f = midi_freq(note)
    v = velocity / 127.0
    t = np.arange(n) / sr
    # Bandlimited saw: first 5 harmonics
    buf = np.zeros(n)
    for k in range(1, 6):
        buf += (1.0 / k) * np.sin(2 * math.pi * f * k * t)
    buf *= 2.0 / math.pi
    # Sub octave for weight
    buf += 0.5 * np.sin(2 * math.pi * f * 0.5 * t)
    # Low-pass filter — remove harshness above ~800 Hz
    from scipy.signal import lfilter
    cutoff_norm = min(0.98, 800.0 * 2 / sr)
    alpha = 1.0 - math.exp(-2 * math.pi * cutoff_norm)
    buf = lfilter([alpha], [1, -(1 - alpha)], buf)
    # Velocity affects tightness: louder = slightly faster attack
    atk = max(0.004, 0.015 - 0.007 * v)
    env = adsr(n, atk, 0.07, 0.70, 0.14, sr)
    return buf * env * v * 0.58

def voice_bass_808(note, n, velocity, sr=SR):
    """808-style sub-bass: sine with pitch sweep and long sustain."""
    f = midi_freq(note)
    v = velocity / 127.0
    t = np.arange(n) / sr
    # Pitch sweep: start 1.5x, decay down to fundamental over ~80ms
    freq_t = f * (1.0 + 0.5 * np.exp(-10 * t))
    phase = np.cumsum(freq_t) / sr
    buf = np.sin(2 * math.pi * phase)
    # Add slight harmonic for presence
    buf += 0.12 * np.sin(2 * math.pi * 2 * phase)
    # Long sustain decay
    env = adsr(n, 0.003, 0.05, 0.88, 0.25, sr)
    # Transient click
    click = np.exp(-300 * t) * 0.3
    return (buf * env + click) * v * 0.82

def voice_bass_pizz(note, n, velocity, sr=SR):
    """Pizzicato-style plucked bass: fast attack, exponential decay."""
    f = midi_freq(note)
    v = velocity / 127.0
    t = np.arange(n) / sr
    buf = np.zeros(n)
    for k in range(1, 7):
        amp = 1.0 / (k ** 1.3)
        buf += amp * np.sin(2 * math.pi * f * k * t) * np.exp(-k * 3.5 * t)
    buf *= 2.0 / math.pi
    env = np.exp(-4.0 * t)
    return buf * env * v * 0.62

def voice_pad(note, n, velocity, sr=SR):
    """Pad: 6 detuned sines + gentle tremolo → lush string ensemble with warmth."""
    f = midi_freq(note)
    v = velocity / 127.0
    t = np.arange(n) / sr
    # 6 voices: wider stereo spread and richer chorus
    detunes = [(0.0, 0.30), (0.021, 0.22), (-0.015, 0.18),
               (0.009, 0.14), (-0.028, 0.10), (0.034, 0.06)]
    buf = sum(a * np.sin(2 * math.pi * f * (1 + d) * t) for d, a in detunes)
    # Gentle tremolo: 3.2 Hz, ±2% amplitude
    tremolo = 1.0 + 0.02 * np.sin(2 * math.pi * 3.2 * t)
    buf *= tremolo
    # Mild low-pass: roll off brightness for warmth
    from scipy.signal import lfilter
    alpha = 0.55
    buf = lfilter([alpha], [1, -(1 - alpha)], buf)
    env = adsr(n, 0.22, 0.12, 0.80, 0.32, sr)
    return buf * env * v * 0.48

def voice_pad_synth(note, n, velocity, sr=SR):
    """Synthwave supersaw pad: 7 detuned saw voices for EDM/electronic tone."""
    f = midi_freq(note)
    v = velocity / 127.0
    t = np.arange(n) / sr
    # Supersaw: 7 slightly detuned sawtooth waves for that classic synth chord sound
    detunes = [(0.0, 0.20), (0.014, 0.16), (-0.011, 0.16),
               (0.028, 0.12), (-0.022, 0.12), (0.040, 0.08), (-0.036, 0.08)]
    buf = np.zeros(n)
    for d, a in detunes:
        fd = f * (1 + d)
        saw = 2.0 * (t * fd % 1.0) - 1.0
        # First 5 harmonics only (bandlimited to reduce aliasing)
        bl_saw = np.zeros(n)
        for k in range(1, 6):
            bl_saw += (1.0 / k) * np.sin(2 * math.pi * fd * k * t)
        bl_saw *= 2.0 / math.pi
        buf += a * bl_saw
    # Tone control: mild low-pass for warmth
    from scipy.signal import lfilter
    lp_alpha = 0.50
    buf = lfilter([lp_alpha], [1, -(1 - lp_alpha)], buf)
    # Snappy ADSR for punchy stabs, smooth for held chords
    if n < int(0.45 * sr):  # short stab
        env = adsr(n, 0.004, 0.06, 0.75, 0.10, sr)
    else:                    # sustained chord
        env = adsr(n, 0.06, 0.10, 0.84, 0.18, sr)
    return buf * env * v * 0.44

def voice_melody(note, n, velocity, sr=SR):
    """Melody: saw + harmonics with delayed vibrato for natural woodwind feel."""
    f = midi_freq(note)
    v = velocity / 127.0
    t = np.arange(n) / sr

    # Vibrato: starts after 0.12s attack, 5 Hz, ±14 cents depth
    vib_rate = 5.2
    vib_depth_cents = 14.0
    vib_onset = 0.12  # seconds before vibrato fades in
    vib_env = np.clip((t - vib_onset) / 0.06, 0.0, 1.0)
    vib_lfo = np.sin(2 * math.pi * vib_rate * t)
    freq_mod = f * 2.0 ** (vib_depth_cents / 1200.0 * vib_lfo * vib_env)

    # Phase accumulation with modulated frequency
    phase = np.cumsum(freq_mod) / sr
    fund = np.sin(2 * math.pi * phase)
    # Add harmonics (simple, without modulating them — keeps it fast)
    buf = (0.50 * fund +
           0.28 * np.sin(2 * math.pi * 2 * phase) +
           0.12 * np.sin(2 * math.pi * 3 * phase) +
           0.06 * np.sin(2 * math.pi * 4 * phase))

    # Velocity-sensitive attack: louder = snappier
    atk = max(0.003, 0.012 - 0.006 * (v - 0.5))
    env = adsr(n, atk, 0.06, 0.78, 0.14, sr)
    return buf * env * v * 0.52

def voice_melody_bright(note, n, velocity, sr=SR):
    """Bright brass/fanfare melody: more harmonics, snappy attack, strong presence."""
    f = midi_freq(note)
    v = velocity / 127.0
    t = np.arange(n) / sr
    # Richer harmonic stack (brass-like)
    buf = (0.40 * np.sin(2 * math.pi * f * t) +
           0.30 * np.sin(2 * math.pi * 2 * f * t) +
           0.18 * np.sin(2 * math.pi * 3 * f * t) +
           0.08 * np.sin(2 * math.pi * 4 * f * t) +
           0.04 * np.sin(2 * math.pi * 5 * f * t))
    # Mild pitch vibrato (faster, more pronounced — brass style)
    vib_rate = 5.8; vib_cents = 10.0; vib_onset = 0.08
    vib_env = np.clip((t - vib_onset) / 0.05, 0.0, 1.0)
    vib = 2.0 ** (vib_cents / 1200.0 * np.sin(2 * math.pi * vib_rate * t) * vib_env) - 1.0
    buf = buf * (1.0 + vib * 0.3)
    # Snappy attack, moderate release
    atk = max(0.005, 0.018 - 0.01 * v)
    env = adsr(n, atk, 0.04, 0.82, 0.10, sr)
    return buf * env * v * 0.58

def voice_melody_sax(note, n, velocity, sr=SR):
    """Saxophone-style melody: reedy square-wave mix, breathy noise layer."""
    f = midi_freq(note)
    v = velocity / 127.0
    t = np.arange(n) / sr
    # Odd harmonics (clarinet/reed character)
    buf = (0.42 * np.sin(2 * math.pi * f * t) +
           0.26 * np.sin(2 * math.pi * 3 * f * t) +
           0.14 * np.sin(2 * math.pi * 5 * f * t) +
           0.08 * np.sin(2 * math.pi * 7 * f * t))
    # Breath noise layer (low-level band-limited noise for reedy texture)
    from scipy.signal import lfilter
    noise = _rng.standard_normal(n) * 0.04
    alpha_n = 0.15  # narrow band
    noise = lfilter([alpha_n], [1, -(1 - alpha_n)], noise)
    buf += noise
    # Slower vibrato onset — sax players add vibrato mid-note
    vib_rate = 5.5; vib_cents = 16.0; vib_onset = 0.15
    vib_env = np.clip((t - vib_onset) / 0.07, 0.0, 1.0)
    freq_mod = f * 2.0 ** (vib_cents / 1200.0 * np.sin(2 * math.pi * vib_rate * t) * vib_env)
    phase = np.cumsum(freq_mod) / sr
    fund_mod = np.sin(2 * math.pi * phase)
    buf = buf * 0.4 + fund_mod * 0.6  # blend static + modulated
    atk = max(0.008, 0.025 - 0.012 * v)
    env = adsr(n, atk, 0.05, 0.80, 0.18, sr)
    return buf * env * v * 0.54

# GM drum mapping → synthesis parameters
_DRUM_PARAMS = {
    # Kick drums
    36: dict(kind='kick',   dur=0.30, freq0=90,  freq1=40,  sweep=14, noiseratio=0.18),
    35: dict(kind='kick',   dur=0.28, freq0=80,  freq1=38,  sweep=12, noiseratio=0.18),
    # Snare drums
    38: dict(kind='snare',  dur=0.22, freq=185,  noiseratio=0.65),
    40: dict(kind='snare',  dur=0.18, freq=225,  noiseratio=0.68),
    # Hi-hats
    42: dict(kind='hihat',  dur=0.07, decay=60),
    44: dict(kind='hihat',  dur=0.07, decay=60),
    46: dict(kind='ohihat', dur=0.38, decay=8),
    # Crashes + rides
    49: dict(kind='crash',  dur=1.2,  decay=2.5),
    51: dict(kind='ride',   dur=0.70, decay=6.0),
    53: dict(kind='ride',   dur=0.55, decay=8.0),
    55: dict(kind='crash',  dur=0.85, decay=3.8),
    57: dict(kind='crash',  dur=0.75, decay=4.2),
    # Toms
    41: dict(kind='tom',    dur=0.28, freq0=82,  freq1=55,  sweep=8),
    43: dict(kind='tom',    dur=0.28, freq0=90,  freq1=62,  sweep=8),
    45: dict(kind='tom',    dur=0.25, freq0=110, freq1=78,  sweep=9),
    47: dict(kind='tom',    dur=0.24, freq0=130, freq1=92,  sweep=10),
    48: dict(kind='tom',    dur=0.22, freq0=155, freq1=110, sweep=11),
    50: dict(kind='tom',    dur=0.22, freq0=185, freq1=130, sweep=12),
    # Misc
    39: dict(kind='clap',   dur=0.18),
    56: dict(kind='cowbell',dur=0.38, freq=562),
    37: dict(kind='rimshot',dur=0.12, freq=330),
    54: dict(kind='tamb',   dur=0.18),
    69: dict(kind='tamb',   dur=0.16),
    70: dict(kind='tamb',   dur=0.16),
}

_rng = np.random.default_rng(42)  # seeded RNG for repeatable drum noise

def voice_drum(note, velocity, sr=SR):
    p = _DRUM_PARAMS.get(note, dict(kind='hihat', dur=0.10, decay=40))
    v = velocity / 127.0
    kind = p['kind']
    n = int(p.get('dur', 0.10) * sr)
    t = np.arange(n) / sr

    if kind == 'kick':
        f0, f1 = p['freq0'], p['freq1']
        sweep = p['sweep']
        freq_t = f0 * np.exp(-sweep * t)
        phase = np.cumsum(freq_t) / sr
        tone = np.sin(2 * math.pi * phase)
        noise = _rng.standard_normal(n) * p['noiseratio']
        env = np.exp(-10 * t)
        click = np.exp(-150 * t) * 0.6  # transient click
        return (tone + noise + click) * env * v * 0.90

    elif kind == 'snare':
        noise = _rng.standard_normal(n)
        tone = np.sin(2 * math.pi * p['freq'] * t)
        env = np.exp(-18 * t)
        return (p['noiseratio'] * noise + (1 - p['noiseratio']) * tone) * env * v * 0.70

    elif kind == 'hihat':
        noise = _rng.standard_normal(n)
        env = np.exp(-p['decay'] * t)
        return noise * env * v * 0.35

    elif kind == 'ohihat':
        noise = _rng.standard_normal(n)
        env = np.exp(-p['decay'] * t)
        return noise * env * v * 0.38

    elif kind == 'crash':
        noise = _rng.standard_normal(n)
        # Bright shimmer: mix of high-frequency tones
        shimmer = (np.sin(2*math.pi*6000*t)*0.3 + np.sin(2*math.pi*8500*t)*0.2 +
                   np.sin(2*math.pi*11000*t)*0.15)
        env = np.exp(-p['decay'] * t)
        return (0.7 * noise + 0.3 * shimmer) * env * v * 0.45

    elif kind == 'clap':
        noise = _rng.standard_normal(n)
        # Two short bursts
        env = (np.exp(-80 * t) + 0.5 * np.exp(-80 * np.maximum(0, t - 0.012)))
        return noise * env * v * 0.55

    elif kind == 'cowbell':
        tone = np.sin(2*math.pi*p['freq']*t) + 0.4*np.sin(2*math.pi*p['freq']*1.47*t)
        env = np.exp(-9 * t)
        return tone * env * v * 0.45

    elif kind == 'rimshot':
        tone = np.sin(2*math.pi*p['freq']*t)
        noise = _rng.standard_normal(n) * 0.3
        env = np.exp(-40 * t)
        return (tone + noise) * env * v * 0.50

    elif kind == 'tom':
        f0, f1 = p['freq0'], p['freq1']
        sweep = p.get('sweep', 8)
        freq_t = f0 * np.exp(-sweep * t) + f1 * (1 - np.exp(-sweep * t))
        phase = np.cumsum(freq_t) / SR
        tone = np.sin(2 * math.pi * phase)
        noise = _rng.standard_normal(n) * 0.12
        env = np.exp(-12 * t)
        return (tone + noise) * env * v * 0.75

    elif kind == 'ride':
        noise = _rng.standard_normal(n)
        shimmer = np.sin(2*math.pi*4000*t)*0.3 + np.sin(2*math.pi*6200*t)*0.2
        env = np.exp(-p['decay'] * t)
        return (0.5 * noise + 0.5 * shimmer) * env * v * 0.32

    elif kind == 'tamb':
        noise = _rng.standard_normal(n)
        jingle = np.sin(2*math.pi*7800*t) + 0.5*np.sin(2*math.pi*11200*t)
        env = np.exp(-28 * t)
        return (0.4 * noise + 0.6 * jingle) * env * v * 0.28

    else:
        noise = _rng.standard_normal(n)
        env = np.exp(-30 * t)
        return noise * env * v * 0.30

# ── Reverb (vectorised early-reflection delay network) ───────────────────────

def apply_reverb(buf, room=0.18, sr=SR):
    """All-numpy reverb: early reflections + diffuse late tail."""
    if room <= 0:
        return buf
    n = len(buf)
    from scipy.signal import lfilter

    # Early reflections (first 80ms)
    early_taps = [(0.0113, 0.60), (0.0237, 0.50), (0.0371, 0.42),
                  (0.0431, 0.35), (0.0593, 0.26), (0.0743, 0.18),
                  (0.0893, 0.12), (0.1071, 0.08)]
    early = np.zeros(n)
    for d_sec, g in early_taps:
        d = int(d_sec * sr)
        if d < n:
            early[d:] += buf[:n - d] * (g * room)

    # Late diffuse tail: two longer echoes with decay
    late = np.zeros(n)
    for d_sec, g in [(0.18, 0.06), (0.28, 0.04)]:
        d = int(d_sec * sr)
        if d < n:
            late[d:] += buf[:n - d] * (g * room)

    out = early + late
    # Air absorption low-pass on reverb (damps highs in tail)
    alpha = 0.30
    out = lfilter([alpha], [1, -(1 - alpha)], out)
    return buf * 0.80 + out * 0.20

# ── MIDI reader ───────────────────────────────────────────────────────────────

def read_midi_events(mid_path, track_type):
    """Parse a MIDI file, return list of (time_sec, note, duration_sec, velocity)."""
    mid = mido.MidiFile(mid_path)
    tempo = 500000  # default 120 BPM
    ticks_per_beat = mid.ticks_per_beat

    # Collect all messages with absolute tick times
    events = []
    abs_tick = 0
    for track in mid.tracks:
        abs_tick = 0
        for msg in track:
            abs_tick += msg.time
            if msg.type == 'set_tempo':
                tempo = msg.tempo
            elif msg.type in ('note_on', 'note_off'):
                events.append((abs_tick, msg.type, msg.note,
                               msg.velocity if msg.type == 'note_on' else 0))

    if not events:
        return []

    events.sort(key=lambda e: e[0])

    def ticks_to_sec(ticks):
        return ticks * tempo / (ticks_per_beat * 1_000_000)

    # Build (start, note, dur, vel) — handle note_off via note_on(vel=0)
    if track_type == 'drums':
        # Drums: each note_on fires immediately (no duration needed)
        result = []
        for tick, mtype, note, vel in events:
            if mtype == 'note_on' and vel > 0:
                t = ticks_to_sec(tick)
                result.append((t, note, 0.0, vel))  # dur unused for drums
        return result
    else:
        # Melodic: pair note_on with note_off
        active = {}  # note → (tick, vel)
        result = []
        for tick, mtype, note, vel in events:
            if mtype == 'note_on' and vel > 0:
                active[note] = (tick, vel)
            elif mtype == 'note_off' or (mtype == 'note_on' and vel == 0):
                if note in active:
                    start_tick, start_vel = active.pop(note)
                    dur = ticks_to_sec(tick - start_tick)
                    if dur > 0.001:
                        result.append((ticks_to_sec(start_tick), note, dur, start_vel))
        # Handle notes that never got a note_off
        if events:
            end_tick = events[-1][0]
        for note, (start_tick, start_vel) in active.items():
            dur = ticks_to_sec(end_tick - start_tick)
            if dur > 0.001:
                result.append((ticks_to_sec(start_tick), note, dur, start_vel))
        return result

# ── Mix rendering ─────────────────────────────────────────────────────────────

TRACK_GAINS = {'bass': 0.88, 'pad': 0.70, 'melody': 0.95, 'drums': 0.78}
TRACK_REVERB = {'bass': 0.05, 'pad': 0.22, 'melody': 0.14, 'drums': 0.08}

# Stereo pan (L, R gains) per track
TRACK_PAN = {
    'bass':   (0.85, 0.85),   # centre-ish
    'pad':    (0.72, 0.82),   # slight right
    'melody': (0.82, 0.72),   # slight left
    'drums':  (0.80, 0.80),   # centre
}

# Style profiles: map genre/style name → (bass_fn, melody_fn, pad_fn)
_STYLE_VOICES = {
    'hiphop':     ('bass_808',  'default', 'default'),
    'blues':      ('default',   'sax',     'default'),
    'jazz':       ('default',   'sax',     'default'),
    'swing':      ('default',   'sax',     'default'),
    'action':     ('default',   'bright',  'default'),
    'orchestral': ('default',   'bright',  'default'),
    'fanfare':    ('default',   'bright',  'default'),
    'cinematic':  ('default',   'bright',  'default'),
    'reggae':     ('pizz',      'default', 'default'),
    'folk':       ('pizz',      'default', 'default'),
    'country':    ('pizz',      'default', 'default'),
    'bluegrass':  ('pizz',      'default', 'default'),
    'electronic': ('default',   'default', 'synth'),
}

# Genre-specific reverb: ambient/classical get more room; electronic/hip-hop get less
_STYLE_REVERB = {
    'ambient':    {'bass': 0.04, 'pad': 0.36, 'melody': 0.26, 'drums': 0.06},
    'classical':  {'bass': 0.06, 'pad': 0.28, 'melody': 0.20, 'drums': 0.08},
    'orchestral': {'bass': 0.08, 'pad': 0.30, 'melody': 0.22, 'drums': 0.10},
    'cinematic':  {'bass': 0.08, 'pad': 0.32, 'melody': 0.24, 'drums': 0.10},
    'baroque':    {'bass': 0.06, 'pad': 0.24, 'melody': 0.18, 'drums': 0.07},
    'impressionist': {'bass': 0.05, 'pad': 0.34, 'melody': 0.26, 'drums': 0.06},
    'minimalist': {'bass': 0.05, 'pad': 0.35, 'melody': 0.28, 'drums': 0.06},
    'electronic': {'bass': 0.03, 'pad': 0.12, 'melody': 0.08, 'drums': 0.04},
    'hiphop':     {'bass': 0.02, 'pad': 0.12, 'melody': 0.10, 'drums': 0.03},
    'funk':       {'bass': 0.04, 'pad': 0.14, 'melody': 0.12, 'drums': 0.05},
}

def _get_reverb(style_key):
    return _STYLE_REVERB.get(style_key, TRACK_REVERB)

def _pick_bass_fn(style_key):
    profile = _STYLE_VOICES.get(style_key, ('default', 'default', 'default'))
    bk = profile[0]
    if bk == 'bass_808': return voice_bass_808
    if bk == 'pizz':     return voice_bass_pizz
    return voice_bass

def _pick_melody_fn(style_key):
    profile = _STYLE_VOICES.get(style_key, ('default', 'default', 'default'))
    mk = profile[1]
    if mk == 'bright': return voice_melody_bright
    if mk == 'sax':    return voice_melody_sax
    return voice_melody

def _pick_pad_fn(style_key):
    profile = _STYLE_VOICES.get(style_key, ('default', 'default', 'default'))
    pk = profile[2] if len(profile) > 2 else 'default'
    if pk == 'synth': return voice_pad_synth
    return voice_pad

def render_track(events, track_type, total_samples, sr=SR,
                 bass_fn=None, melody_fn=None, pad_fn=None):
    """Render all events of one track type into a mono buffer.
    bass_fn / melody_fn / pad_fn override the default voice functions for genre variation."""
    buf = np.zeros(total_samples)
    _bass   = bass_fn   or voice_bass
    _melody = melody_fn or voice_melody
    _pad    = pad_fn    or voice_pad

    for evt in events:
        if track_type == 'drums':
            t_sec, note, _, vel = evt
            start = int(t_sec * sr)
            grain = voice_drum(note, vel, sr)
        else:
            t_sec, note, dur_sec, vel = evt
            start = int(t_sec * sr)
            n = max(1, int(dur_sec * sr))
            if track_type == 'bass':
                grain = _bass(note, n, vel, sr)
            elif track_type == 'pad':
                grain = _pad(note, n, vel, sr)
            else:  # melody
                grain = _melody(note, n, vel, sr)

        end = min(start + len(grain), total_samples)
        if end > start:
            buf[start:end] += grain[:end - start]

    return buf

def synth_piece(bass_mid, pad_mid, melody_mid, drums_mid, out_wav, sr=SR,
                style=None):
    """Render 4 MIDI files → stereo WAV at out_wav.
    style: optional genre/style key (e.g. 'hiphop', 'jazz') for voice selection."""
    files = {
        'bass':   bass_mid,
        'pad':    pad_mid,
        'melody': melody_mid,
        'drums':  drums_mid,
    }

    style_key = (style or '').lower().replace('-', '').replace(' ', '')
    bass_fn   = _pick_bass_fn(style_key)
    melody_fn = _pick_melody_fn(style_key)
    pad_fn    = _pick_pad_fn(style_key)
    reverb    = _get_reverb(style_key)

    # Determine total duration from MIDI file lengths
    total_sec = 0.0
    for ttype, path in files.items():
        if not os.path.exists(path):
            print(f'  WARNING: {path} not found, skipping')
            continue
        mid = mido.MidiFile(path)
        total_sec = max(total_sec, mid.length)

    if total_sec < 0.5:
        print('  ERROR: MIDI files too short or missing')
        return False

    # Add 2s tail for reverb decay
    total_samples = int((total_sec + 2.0) * sr)
    print(f'  Duration: {total_sec:.2f}s -> {total_samples} samples')

    mix_l = np.zeros(total_samples)
    mix_r = np.zeros(total_samples)

    for ttype, path in files.items():
        if not os.path.exists(path):
            continue
        print(f'  Rendering {ttype}...', end='', flush=True)
        evts = read_midi_events(path, ttype)
        if not evts:
            print(' (empty)')
            continue
        raw = render_track(evts, ttype, total_samples, sr,
                           bass_fn=bass_fn, melody_fn=melody_fn, pad_fn=pad_fn)
        # Apply genre-adjusted reverb
        room = reverb.get(ttype, TRACK_REVERB[ttype])
        if room > 0:
            raw = apply_reverb(raw, room=room, sr=sr)
        raw *= TRACK_GAINS[ttype]
        pan_l, pan_r = TRACK_PAN[ttype]
        mix_l += raw * pan_l
        mix_r += raw * pan_r
        peak = max(np.abs(raw).max(), 1e-9)
        print(f' {len(evts)} events, peak={peak:.3f}')

    # Normalise + master limiter
    peak = max(np.abs(mix_l).max(), np.abs(mix_r).max(), 1e-9)
    if peak > MAX_AMP:
        mix_l *= MAX_AMP / peak
        mix_r *= MAX_AMP / peak
    else:
        gain = min(MAX_AMP / peak, 2.0)
        mix_l *= gain
        mix_r *= gain

    # Soft-knee limiter pass
    threshold = 0.85
    for arr in (mix_l, mix_r):
        over = np.abs(arr) > threshold
        arr[over] = threshold + (arr[over] - np.sign(arr[over]) * threshold) * 0.25

    # Write 16-bit stereo WAV. Write to a unique temp file first, then move it
    # into place — the target may be momentarily locked by the dashboard
    # serving the old audio to a browser, so a direct write can fail.
    out_dir = os.path.dirname(out_wav)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    tmp_wav = f'{out_wav}.{os.getpid()}.tmp'
    with wave.open(tmp_wav, 'w') as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        stereo = np.empty(total_samples * 2, dtype=np.float64)
        stereo[0::2] = mix_l
        stereo[1::2] = mix_r
        int16 = (np.clip(stereo, -1.0, 1.0) * 32767).astype(np.int16)
        wf.writeframes(int16.tobytes())

    # Free the target name. An old WAV may be held open by the dashboard
    # serving it to a browser; renaming it aside succeeds even while it is
    # being read (Windows allows it for share-delete handles) and leaves the
    # name free for the fresh file. Direct overwrite of a locked file fails.
    aside = None
    if os.path.exists(out_wav):
        aside = f'{out_wav}.old{os.getpid()}'
        try:
            os.replace(out_wav, aside)
        except OSError:
            aside = None

    last_err = None
    for attempt in range(6):
        try:
            os.replace(tmp_wav, out_wav)
            last_err = None
            break
        except PermissionError as e:           # name still pinned — retry
            last_err = e
            time.sleep(0.5)

    if last_err is not None:
        # The target name is pinned (delete-pending on Windows because a
        # browser still holds the old audio). Write to a fresh versioned
        # name instead — the dashboard resolves the newest <id>*.wav — so
        # the render never fails on a lock.
        stem, ext = os.path.splitext(out_wav)
        out_wav = f'{stem}.{int(time.time())}{ext}'
        try:
            os.replace(tmp_wav, out_wav)
        except OSError as e:
            try:
                os.unlink(tmp_wav)
            except OSError:
                pass
            if aside:
                try:
                    os.unlink(aside)
                except OSError:
                    pass
            raise e

    if aside:                                  # best-effort cleanup
        try:
            os.unlink(aside)
        except OSError:
            pass

    size_kb = os.path.getsize(out_wav) // 1024
    print(f'  Wrote {out_wav} ({size_kb} KB)')
    return out_wav

# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description='MIDI → WAV synthesizer')
    p.add_argument('--out',    required=True, help='Output WAV path')
    p.add_argument('--bass',   required=True)
    p.add_argument('--pad',    required=True)
    p.add_argument('--melody', required=True)
    p.add_argument('--drums',  required=True)
    args = p.parse_args()
    ok = synth_piece(args.bass, args.pad, args.melody, args.drums, args.out)
    import sys; sys.exit(0 if ok else 1)

if __name__ == '__main__':
    main()
