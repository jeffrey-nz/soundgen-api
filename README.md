# soundgen-api

REST API for procedural MIDI composition and audio rendering.
Part of the [procmusic](https://github.com/jeffrey-nz/procmusic-dashboard) ecosystem.

## Overview

| Endpoint | Method | Description |
|---|---|---|
| `/catalog` | GET | Full piece catalog (id, title, genre, bpm, key…) |
| `/catalog/{id}` | GET | Single piece metadata |
| `/generate` | POST | Generate MIDI for all pieces (SSE stream) |
| `/generate/{id}` | POST | Generate MIDI for one piece (SSE stream) |
| `/render` | POST | Render all pieces to WAV (SSE stream) |
| `/render/{id}` | POST | Render one piece to WAV (SSE stream) |
| `/render/audio/{id}` | GET | Stream the rendered WAV file |
| `/ports` | GET | List MIDI output ports |
| `/ports/select` | POST | Select a MIDI port by index |
| `/ports/panic` | POST | All Notes Off on all channels |
| `/play/{id}` | POST | Live playback via loopMIDI → Kontakt (SSE) |
| `/play/stop` | POST | Stop playback |
| `/play/state` | GET | Current playback state |

Interactive docs at **http://localhost:8002/docs** when running.

## Quick start

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
copy .env.example .env
uvicorn main:app --port 8002 --reload
```

## Configuration

| Variable | Default | Description |
|---|---|---|
| `PROCMUSIC_PYTHON` | `python` | Python interpreter path |
| `MIDI_OUTPUT_DIR` | `../procmusic-dashboard/dashboard/showcase-midi` | MIDI output folder |
| `AUDIO_OUTPUT_DIR` | `../procmusic-dashboard/dashboard/showcase-audio` | WAV output folder |

## Streaming responses

`/generate`, `/render`, and `/play` return **Server-Sent Events** so you can monitor progress in real time:

```js
const source = new EventSource('/generate');
source.onmessage = e => console.log(e.data);
source.addEventListener('done', () => source.close());
```

## Related projects

- **[scoreforge-api](https://github.com/jeffrey-nz/scoreforge-api)** — Sheet music import, AI transcription, and theory validation
- **[procmusic-dashboard](https://github.com/jeffrey-nz/procmusic-dashboard)** — Web dashboard that ties everything together
