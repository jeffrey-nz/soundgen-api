#!/usr/bin/env python3
"""
midi_proxy.py — persistent MIDI output proxy.
Reads JSON messages from stdin, sends MIDI via rtmidi.
Started lazily by server.js; stays alive until the server exits.

Messages in  (one JSON object per line):
  {"type":"ports"}                         -> reply with port list
  {"type":"select","port":0}              -> open port by index
  {"type":"note_on","ch":1,"note":60,"vel":80}
  {"type":"note_off","ch":1,"note":60}
  {"type":"all_off"}                       -> send CC 123 (all notes off) on all channels

Messages out (one JSON object per line):
  {"ports":[...], "selected": 0|null}
  {"selected": 0}
  {"ok":true}
  {"error":"..."}
"""
import sys, json, rtmidi

mout   = rtmidi.MidiOut()
ports  = mout.get_ports()
sel    = None   # currently open port index


def open_port(idx):
    global sel
    if sel is not None:
        try: mout.close_port()
        except: pass
        sel = None
    if idx is not None and 0 <= idx < len(ports):
        mout.open_port(idx)
        sel = idx
        # Wake Kontakt: reset all controllers then silence all notes
        for ch in range(16):
            send([0xB0 | ch, 121, 0])  # Reset All Controllers
            send([0xB0 | ch, 123, 0])  # All Notes Off


def send(msg):
    try: mout.send_message(msg)
    except: pass


def reply(obj):
    sys.stdout.write(json.dumps(obj) + '\n')
    sys.stdout.flush()


# Auto-select: prefer loopMIDI, fall back to first non-wavetable, then wavetable
def _auto_idx():
    for i, p in enumerate(ports):
        if 'loop' in p.lower(): return i
    for i, p in enumerate(ports):
        if 'wavetable' not in p.lower(): return i
    return 0 if ports else None

auto = _auto_idx()
if auto is not None:
    open_port(auto)

reply({"ports": ports, "selected": sel})

for raw in sys.stdin:
    raw = raw.strip()
    if not raw:
        continue
    try:
        msg = json.loads(raw)
        t = msg.get('type', '')

        if t == 'ports':
            reply({"ports": ports, "selected": sel})

        elif t == 'select':
            idx = msg.get('port')
            open_port(idx)
            reply({"selected": sel})

        elif t == 'note_on':
            ch  = max(0, min(15, (msg.get('ch', 1) - 1)))
            note = int(msg.get('note', 60))
            vel  = int(msg.get('vel', 80))
            send([0x90 | ch, note, vel])
            reply({"ok": True})

        elif t == 'note_off':
            ch  = max(0, min(15, (msg.get('ch', 1) - 1)))
            note = int(msg.get('note', 60))
            send([0x80 | ch, note, 0])
            reply({"ok": True})

        elif t == 'all_off':
            for ch in range(16):
                send([0xB0 | ch, 123, 0])   # All Notes Off CC
            reply({"ok": True})

    except Exception as e:
        reply({"error": str(e)})
