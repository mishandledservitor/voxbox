# CLAUDE.md — agent onboarding notes

Companion to `AGENTS.md`. That file describes the repo layout and the submodule commit/push workflow; this one captures the install gotchas we've actually hit so you don't rediscover them.

## Installing voxbox on a fresh macOS

Always start with:

```bash
git submodule update --init --recursive
./setup_voxbox.sh
```

The setup script is idempotent — re-running it is safe.

### Gotcha 1 — Homebrew Python 3.14 has no Tk

`brew install python@3.14` does **not** include `tkinter`. Launching the GUI fails with:

```
ModuleNotFoundError: No module named '_tkinter'
```

Fix:

```bash
brew install python-tk@3.14   # match your python3 minor version
```

`setup_voxbox.sh` (step 2) detects this and installs the right `python-tk@<X.Y>` automatically. If you're working around setup, install Tk manually before launching `./voxbox`.

### Gotcha 2 — the cloud STT submodules need API keys before they're useful

Two submodules ship the cloud transcription tools and both need `.env` files (gitignored — never commit):

| File | Contents |
|------|----------|
| `assemblyai-stt/.env` | `ASSEMBLYAI_API_KEY=...` |
| `speech-to-text/.env` | `ELEVENLABS_API_KEY=...` |

Step 5 of `setup_voxbox.sh` runs each submodule's setup script. The setup scripts won't fail if the `.env` is missing — they'll just print a reminder. The GUI tile for each tool is gated on the launcher binary existing, **not** on the key being present, so a missing key produces a runtime error rather than a greyed-out tile.

### Gotcha 3 — whisper-diarize needs a Hugging Face token

`whisper-diarize/setup_whisper_diarize.sh` reads `whisper-diarize/.hf_token` (chmod 600, gitignored). If the file doesn't exist, the script prompts interactively. The token must:

1. Have **Read** access ([huggingface.co/settings/tokens](https://huggingface.co/settings/tokens))
2. Be associated with an account that has accepted the pyannote license at [huggingface.co/pyannote/speaker-diarization-3.1](https://huggingface.co/pyannote/speaker-diarization-3.1)

Pre-create the token file when scripting an unattended install:

```bash
echo "hf_xxxxxxxx" > whisper-diarize/.hf_token
chmod 600 whisper-diarize/.hf_token
```

### Gotcha 4 — the parent `./voxbox` launcher is generated, not tracked

`setup_voxbox.sh` writes `./voxbox` at the end. If setup exits early (e.g. submodule install fails) the launcher won't exist. After fixing the underlying issue, either re-run setup or create it manually:

```bash
cat > voxbox <<'LAUNCHER'
#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
exec python3 "$SCRIPT_DIR/voxbox_cli.py" "$@"
LAUNCHER
chmod +x voxbox
```

### Gotcha 5 — the `speech-to-text` submodule has two surfaces

- `transcribe.py` / `transcribe_generic.py` — higher-level pipelines (config files, post-processing, language overrides) intended for direct human use
- `elevenlabs_stt.py` + the `./elevenlabs` launcher — thin SDK wrapper with a CLI matching `assemblyai-stt/assemblyai` (`-f`, `-o`, `--speakers`, etc.). This is what `voxbox_gui.py` calls.

When fixing GUI behaviour for ElevenLabs, edit `elevenlabs_stt.py`. When changing the TTRPG transcription workflow, edit `transcribe.py`.

## GUI quirks

- **macOS aqua ttk theme ignores `padding` on `ttk.Button`.** Mode-picker tiles use plain `tk.Button` with `padx`/`pady` instead. Other buttons in the GUI can stay as `ttk.Button` since their content fits.
- **Window auto-sizes in `main()`** via `update_idletasks()` + `winfo_reqheight()`. Don't hardcode `root.geometry(...)` in `__init__` — different DPI / font scales produce different content heights and a hardcoded value cuts off the last mode tile.

## Commit checklist

See `AGENTS.md` for the full submodule push workflow. Quick reminders:

- Push the submodule first, then the parent (so the parent's gitlink points at a SHA that exists on the remote).
- `git submodule update` leaves submodules on detached HEAD — `git checkout main && git pull --ff-only` inside the submodule before committing.
- Never `git add -A` at the repo root without scanning `git status` first; the data dirs (`inbox/`, `output/`, `processed/`, `transcripts/`) catch real audio + transcripts you don't want in the repo.
- `.env` files are gitignored; double-check before adding anything from a submodule root.
