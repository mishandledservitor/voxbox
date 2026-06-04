# Shortlisted Call Transcriber

Standalone GUI for transcribing client calls via ElevenLabs Scribe, with every
relevant Scribe API option exposed.

Built alongside VoxBox but launches independently — reuses the
`speech-to-text/venv` so the `elevenlabs` SDK is shared.

## Launch

```bash
./shortlisted           # GUI
./shortlisted-stt -h    # CLI
```

## Setup (one-time)

If `../speech-to-text/venv` doesn't exist yet:

```bash
cd ../speech-to-text && ./setup_elevenlabs.sh
```

Then add your API key to `../speech-to-text/.env` (or export
`ELEVENLABS_API_KEY`).

## Workflow

1. Drop call recordings in `inbox/` (or click ➕ Add file in the GUI).
2. Pick options — defaults are tuned for 2-speaker client calls:
   - Diarization on, num_speakers=2, labels `0=Simon,1=Client`
   - Audio events off (cleaner transcript)
   - Word-level timestamps, inline `[hh:mm:ss]` prefix in text mode
3. Click **Transcribe**.
4. Output lands in `output/`; the original audio moves to `processed/`.

## All Scribe options exposed in the GUI

- **model** — `scribe_v1` (stable) / `scribe_v1_experimental`
- **language** — auto-detect or pick ISO-639 code
- **diarize** — on/off
- **num_speakers** — auto or fixed (1–32)
- **diarization_threshold** — 0.10 (loose) – 0.40 (strict)
- **speaker labels** — map `0=Simon,1=Client` style
- **tag_audio_events** — `[laughter]`, `[applause]`, etc.
- **timestamps_granularity** — word / character / none
- **output format** — text / srt / vtt / json
- **inline timestamps** — prefix text lines with `[hh:mm:ss]`
