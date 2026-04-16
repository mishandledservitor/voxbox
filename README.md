# VoxBox — Local Voice Toolkit

> Text-to-speech, speech-to-text, and speaker diarization — fully offline. No cloud, no API keys.

**Version 1.3.1** | [Changelog](CHANGELOG.md) | [License](LICENSE)

```
voxbox/
├── kokoro-tts/        Text-to-Speech            (Kokoro-82M, ONNX Runtime)
├── whisper-stt/       Speech-to-Text            (Faster-Whisper, CTranslate2)
└── whisper-diarize/   STT + Speaker Diarization (WhisperX + pyannote 3.1, optional)
```

The two core tools (`kokoro-tts`, `whisper-stt`) stay PyTorch-free. The optional `whisper-diarize` tool pulls in PyTorch 2.2.2 — it's the only practical path to high-quality speaker diarization on Intel Macs.

---

## Table of Contents

- [Quick Start](#quick-start)
- [Setup](#setup)
- [Usage](#usage)
  - [GUI](#gui-recommended)
  - [Unified Launcher (CLI)](#unified-launcher-cli)
  - [Direct Tool Access](#direct-tool-access)
  - [Interactive Menu (CLI)](#interactive-menu-cli)
  - [Inbox Workflow (Batch Transcription)](#inbox-workflow-batch-transcription)
- [Kokoro TTS](#kokoro-tts)
- [Whisper STT](#whisper-stt)
- [Whisper Diarize](#whisper-diarize)
- [Architecture](#architecture)
  - [Project Structure](#project-structure)
  - [Design Decisions](#design-decisions)
  - [Dependencies](#dependencies)
- [Requirements](#requirements)
- [Uninstall](#uninstall)
- [Troubleshooting](#troubleshooting)
- [Contributing](#contributing)
- [License](#license)
- [Versioning](#versioning)

---

## Quick Start

```bash
git clone --recursive https://github.com/mishandledservitor/voxbox.git
cd voxbox
chmod +x setup_voxbox.sh
./setup_voxbox.sh
```

Then:

```bash
./voxbox                          # Launch GUI (default)
./voxbox tts "Hello, world!"      # Speak text aloud (CLI)
./voxbox stt recording.mp3        # Transcribe audio (CLI)
./voxbox diarize interview.mp3    # Transcribe + label speakers (CLI)
./voxbox --cli                    # Old text-mode interactive menu
```

The GUI is the easiest way to use voxbox: pick a mode, drop files in `inbox/`, watch the progress bar.

---

## Setup

### Prerequisites

- **macOS** (Intel or Apple Silicon)
- **Python 3.10+** (installed automatically if missing)
- **Homebrew** (installed automatically if missing)
- **~800 MB disk space** for default models (Kokoro ~300 MB, Whisper small ~460 MB)
- **+~4 GB if installing Whisper Diarize** (PyTorch + Whisper medium + pyannote)
- Internet connection for initial setup only — everything runs offline after

### Installation

```bash
git clone --recursive https://github.com/mishandledservitor/voxbox.git
cd voxbox
chmod +x setup_voxbox.sh
./setup_voxbox.sh
```

The setup script handles everything in four steps:

1. **Initializes git submodules** — pulls kokoro-tts, whisper-stt, and whisper-diarize repos
2. **Sets up Kokoro TTS** — Python venv, kokoro-onnx, ffmpeg, model download (~300 MB)
3. **Sets up Whisper STT** — Python venv, faster-whisper, model download (~460 MB)
4. **Sets up Whisper Diarize** *(opt-in)* — Python venv, PyTorch 2.2.2, pyannote 3.1, Whisper medium (~4 GB total). You'll be prompted for a Hugging Face token.

Each tool is fully self-contained in its own directory with its own Python virtual environment.

### Verifying Installation

```bash
./voxbox --status
```

This shows whether each tool is installed and ready.

---

## Usage

### GUI (recommended)

```bash
./voxbox          # launches the GUI
```

The GUI has four screens:

1. **Mode picker** — Text-to-Speech, Transcribe, or Transcribe + Identify Speakers
2. **File picker** — scans the root `inbox/`, lets you select which files to process and tweak options (voice, model, speaker count, output format)
3. **Processing** — overall progress bar (file X of Y), per-file progress bar (parsed from tool output), elapsed/ETA timing, live subprocess log, Cancel button
4. **Done** — per-file success/failure summary, buttons to open the output folder or process more

Drop input files into `inbox/` (text for TTS, audio for STT/Diarize). Outputs land in `output/`. Originals move to `processed/` after success.

The GUI uses Tkinter (built into Python — no extra install needed). Per-tool inboxes (`whisper-stt/inbox/`, `whisper-diarize/inbox/`) still work for CLI users.

### Unified Launcher (CLI)

```bash
# Old text-mode interactive menu
./voxbox --cli

# Text-to-speech
./voxbox tts "Hello, this is VoxBox!"
./voxbox tts -v bf_emma "British accent."
./voxbox tts -o greeting.mp3 "Welcome!"
./voxbox tts --no-play -f chapter.txt -v bf_emma -s 0.9 -o chapter.mp3

# Speech-to-text
./voxbox stt recording.mp3
./voxbox stt -m medium interview.wav
./voxbox stt -o subtitles.srt podcast.mp3
./voxbox stt -l ja japanese-audio.wav

# Speech-to-text with speaker labels (requires whisper-diarize setup)
./voxbox diarize interview.mp3
./voxbox diarize --min-speakers 2 --max-speakers 2 -o call.srt call.mp3
./voxbox diarize -m large-v3 podcast.mp3

# Check tool status
./voxbox --status
```

### Direct Tool Access

Each tool works standalone without the parent launcher:

```bash
# Kokoro TTS
./kokoro-tts/kokoro "Hello world"
./kokoro-tts/kokoro                     # interactive mode
./kokoro-tts/kokoro --list-voices       # see all 67 voices

# Whisper STT
./whisper-stt/whisper recording.mp3
./whisper-stt/whisper                   # interactive mode
./whisper-stt/whisper --record          # record from mic
./whisper-stt/whisper --inbox           # batch transcribe inbox
./whisper-stt/whisper --list-models     # see all 10 models

# Whisper Diarize (STT + speaker labels)
./whisper-diarize/whisper-diarize interview.mp3
./whisper-diarize/whisper-diarize       # interactive mode
./whisper-diarize/whisper-diarize --inbox       # batch process inbox
./whisper-diarize/whisper-diarize --list-models
```

### Interactive Menu (CLI)

Launch `./voxbox --cli` to enter the text-mode interactive menu:

```
Commands:
  /tts                 — launch Kokoro TTS (interactive)
  /stt                 — launch Whisper STT (interactive)
  /diarize             — launch Whisper Diarize (interactive)
  /tts "text"          — quick text-to-speech
  /stt file.mp3        — quick transcription
  /diarize file.mp3    — quick transcription with speaker labels
  /inbox               — transcribe all files in whisper-stt/inbox/
  /diarize-inbox       — diarize all files in whisper-diarize/inbox/
  /status              — check installed tools
  /help                — show commands
  /quit                — exit
```

### Inbox Workflow (Batch Transcription)

For hands-off transcription without typing file paths:

1. **Drop** audio files into `whisper-stt/inbox/`
2. **Run** `./voxbox`
3. **Type** `/inbox`

VoxBox transcribes every file in the inbox, saves transcripts to `whisper-stt/output/`, and moves the originals to `whisper-stt/processed/`.

```
whisper-stt/
├── inbox/       Drop audio files here
├── output/      Transcripts appear here (.txt by default)
└── processed/   Originals move here after transcription
```

The inbox workflow also works directly:

```bash
./whisper-stt/whisper --inbox
```

Or from Whisper's interactive mode with `/inbox`.

---

## Kokoro TTS

Local text-to-speech using [Kokoro-82M](https://github.com/hexgrad/kokoro) via ONNX Runtime.

| Feature | Details |
|---------|---------|
| Voices | 67 across 11 languages (American, British, Spanish, French, Hindi, Italian, Japanese, Portuguese, Chinese) |
| Default voice | `af_heart` (American female) |
| Speed control | 0.1x to 3.0x |
| Output formats | WAV, MP3 (via ffmpeg) |
| Model size | ~300 MB |
| Backend | ONNX Runtime (CPU) |

See [kokoro-tts/README.md](kokoro-tts/README.md) for the full voice catalog, all CLI options, and interactive commands.

---

## Whisper STT

Local speech-to-text using [Faster-Whisper](https://github.com/SYSTRAN/faster-whisper) via CTranslate2.

| Feature | Details |
|---------|---------|
| Models | 10 sizes, from tiny (75 MB) to large-v3 (2.9 GB) |
| Default model | `small` (460 MB) — good balance of speed and accuracy |
| Languages | 99+ with auto-detection |
| Audio formats | mp3, mp4, wav, m4a, ogg, flac, aac, webm, mkv, mov, avi, opus |
| Output formats | Plain text, SRT subtitles, VTT captions, JSON |
| Microphone | Built-in recording support |
| Batch mode | Drop files in `inbox/`, transcribe all at once |
| Backend | CTranslate2 (CPU, float32) |

See [whisper-stt/README.md](whisper-stt/README.md) for all models, CLI options, output format details, and interactive commands.

---

## Whisper Diarize

Speech-to-text **with speaker identification**, using [WhisperX](https://github.com/m-bain/whisperX) (Whisper + wav2vec2 alignment) and [pyannote 3.1](https://huggingface.co/pyannote/speaker-diarization-3.1) diarization. **Optional** — install only if you need it.

| Feature | Details |
|---------|---------|
| Models | 6 sizes from tiny (75 MB) to large-v3 (2.9 GB) |
| Default model | `medium` (1.5 GB) — sweet spot for long-form audio quality |
| Diarization | pyannote 3.1 (speaker turns + clustering) |
| Alignment | wav2vec2 word-level timestamps for crisp speaker boundaries |
| Speaker count | Auto, or fix with `--min-speakers / --max-speakers` |
| Output formats | Speaker-grouped text, SRT/VTT (with `[SPEAKER_XX]` tags), JSON |
| Backend | PyTorch 2.2.2 (CPU, Intel-Mac compatible) |
| Auth | Free Hugging Face token required (gated model) |

**Why this submodule breaks the no-PyTorch rule:** pyannote.audio is the only open-source diarization library at this quality level, and it requires PyTorch. The submodule is opt-in during setup so the core voxbox install stays lean.

**Performance on Intel CPU:** budget ~3–5× audio duration with the `medium` model. Pinning the speaker count improves both accuracy and speed substantially.

See [whisper-diarize/README.md](whisper-diarize/README.md) for the HF token setup, model details, all CLI options, and troubleshooting.

---

## Architecture

### Project Structure

```
voxbox/                          # Parent repo (unified launcher)
├── voxbox_gui.py                # Tkinter GUI (default front door)
├── voxbox_cli.py                # CLI dispatcher (subcommands + --cli menu)
├── voxbox                       # Generated bash launcher
├── setup_voxbox.sh              # Master installer
├── uninstall_voxbox.sh          # Master uninstaller
├── README.md
├── CHANGELOG.md
├── VERSION
│
├── inbox/                       # GUI input drop folder (text or audio)
├── output/                      # GUI output folder
├── processed/                   # Originals moved here after GUI success
│
├── kokoro-tts/                  # Git submodule — text-to-speech
│   ├── kokoro_tts_local.py      # TTS engine (438 lines)
│   ├── kokoro                   # Generated bash launcher
│   ├── setup_kokoro.sh          # Installer
│   ├── uninstall_kokoro.sh      # Uninstaller
│   ├── kokoro-v1.0.onnx         # Model file (~300 MB, downloaded at setup)
│   ├── voices-v1.0.bin          # Voice data (downloaded at setup)
│   └── venv/                    # Isolated Python environment
│
├── whisper-stt/                 # Git submodule — speech-to-text
│   ├── whisper_stt_local.py     # STT engine (614 lines)
│   ├── whisper                  # Generated bash launcher
│   ├── setup_whisper.sh         # Installer
│   ├── uninstall_whisper.sh     # Uninstaller
│   ├── inbox/                   # Drop audio files here for batch processing
│   ├── output/                  # Transcripts saved here
│   ├── processed/               # Originals moved here after transcription
│   └── venv/                    # Isolated Python environment
│
└── whisper-diarize/             # Git submodule — STT + speaker diarization (optional)
    ├── whisper_diarize_local.py # WhisperX + pyannote pipeline (684 lines)
    ├── whisper-diarize          # Generated bash launcher
    ├── setup_whisper_diarize.sh # Installer (Python 3.10, PyTorch 2.2.2, pyannote)
    ├── uninstall_whisper_diarize.sh
    ├── .hf_token                # HuggingFace token (chmod 600, not tracked)
    ├── inbox/                   # Drop audio files here for batch processing
    ├── output/                  # Diarized transcripts saved here
    ├── processed/               # Originals moved here after success
    └── venv/                    # Isolated Python 3.10 environment (~2.5 GB)
```

### Design Decisions

**Independent repos.** The parent (`voxbox`) coordinates child repos as git submodules. Each child works completely standalone — you can clone and use any of them independently.

| Repo | Purpose | Backend |
|------|---------|---------|
| [voxbox](https://github.com/mishandledservitor/voxbox) | Unified launcher (GUI + CLI) and docs | Python stdlib + Tkinter |
| [kokoro-tts](https://github.com/mishandledservitor/kokoro-tts) | Text-to-Speech | kokoro-onnx (ONNX Runtime) |
| [whisper-stt](https://github.com/mishandledservitor/whisper-stt) | Speech-to-Text | faster-whisper (CTranslate2) |
| [whisper-diarize](https://github.com/mishandledservitor/whisper-diarize) | STT + Speaker Diarization | WhisperX + pyannote 3.1 (PyTorch 2.2.2) |

**No shared dependencies.** Each tool has its own Python venv. No version conflicts, no "it works on my machine" issues. You can update or remove one tool without affecting the others.

**No PyTorch in the core tools.** `kokoro-tts` and `whisper-stt` use lightweight inference-only backends. This matters on Intel Macs where PyTorch 2.4+ dropped support, and everywhere else where a 2 GB PyTorch install is overkill for inference. `whisper-diarize` is the deliberate exception — pyannote.audio has no comparable PyTorch-free alternative — and it's opt-in during setup.

**Fully offline.** After initial setup (model downloads), everything runs locally. No API keys, no cloud, no telemetry.

**Launcher pattern.** Each tool generates a bash launcher script (`kokoro`, `whisper`, `voxbox`) that activates the correct venv and calls the Python entry point. This means users never need to think about venvs.

### Dependencies

**Kokoro TTS:**
- `kokoro-onnx` — ONNX Runtime wrapper for Kokoro-82M
- `soundfile` — WAV file I/O
- `numpy` — array processing
- `ffmpeg` (system) — MP3 encoding

**Whisper STT:**
- `faster-whisper` — CTranslate2 wrapper for Whisper models
- `sounddevice` — microphone recording
- `soundfile` — audio file I/O
- `numpy` — array processing

**Whisper Diarize:**
- `whisperx` — Whisper + wav2vec2 alignment + diarization orchestration
- `pyannote.audio` 3.1.1 — speaker diarization
- `torch` / `torchaudio` 2.2.2 — pinned for Intel Mac compatibility
- `ffmpeg` (system) — audio decoding

---

## Requirements

| Requirement | Notes |
|-------------|-------|
| macOS | Intel or Apple Silicon |
| Python 3.10+ | Installed via Homebrew if missing |
| Homebrew | Installed automatically if missing |
| Disk space | ~800 MB for default models |
| Internet | Only needed for initial setup |

---

## Uninstall

```bash
chmod +x uninstall_voxbox.sh
./uninstall_voxbox.sh
```

This runs each tool's uninstaller with confirmation prompts (defaults to no), then removes the VoxBox launcher. You can also uninstall each tool independently:

```bash
cd kokoro-tts && chmod +x uninstall_kokoro.sh && ./uninstall_kokoro.sh
cd whisper-stt && chmod +x uninstall_whisper.sh && ./uninstall_whisper.sh
```

---

## Troubleshooting

### Setup fails at "Homebrew not found"

Homebrew is at `/usr/local/bin/brew` (Intel) or `/opt/homebrew/bin/brew` (Apple Silicon) but may not be in PATH. The setup scripts add both locations to PATH automatically, but if you're running manually:

```bash
export PATH="/usr/local/bin:/opt/homebrew/bin:$PATH"
```

### `./voxbox` says "no such file or directory"

The launcher is created by `setup_voxbox.sh`. Run the setup first, or use the Python entry point directly:

```bash
python3 voxbox_cli.py
```

### Model download is slow

Models are downloaded from GitHub (Kokoro) and HuggingFace (Whisper). First-time downloads depend on your internet connection. After that, everything is cached locally.

### Microphone not working

Allow Terminal (or your terminal app) microphone access in **System Preferences > Privacy & Security > Microphone**.

### Individual tool issues

See the troubleshooting sections in each tool's README:
- [Kokoro TTS Troubleshooting](kokoro-tts/README.md#troubleshooting)
- [Whisper STT Troubleshooting](whisper-stt/README.md#troubleshooting)
- [Whisper Diarize Troubleshooting](whisper-diarize/README.md#troubleshooting)

### GUI hangs at "starting..." with no log output (diarize)

Fixed in 1.3.1. If you're on an older voxbox, pull the latest. The fix forces the diarize subprocess to run unbuffered (`PYTHONUNBUFFERED=1`) so stage prints stream live instead of buffering until the end.

### Diarize takes much longer than expected

Diarize on Intel CPU runs at roughly 4–10× audio duration end-to-end. Verified baseline on 2018 Intel 15" MacBook Pro / macOS Sequoia: 2m 10s audio + `tiny` model + 4 speakers = **9m 05s total** (RTF 4.17×, of which the diarize step alone is 7m 54s). The `medium` model is realistically 20–40 min for the same file. Pinning the speaker count via the GUI's "Fixed:" speaker option (or `--min-speakers / --max-speakers` on the CLI) is the single biggest accuracy + speed win. See [whisper-diarize/README.md](whisper-diarize/README.md#performance-on-intel-mac-cpu-only) and [whisper-diarize/CHANGELOG.md](whisper-diarize/CHANGELOG.md) for details.

### Diarize hangs at 0% CPU forever (or segfaults at language detection)

Both symptoms come from the same root cause: torch + faster-whisper + pyannote on Intel macOS doesn't tolerate multi-threaded execution. Fixed in `whisper-diarize` 1.0.2 by forcing `OMP_NUM_THREADS=1` (and friends) at module import. **Do not override this** — `OMP_NUM_THREADS > 1` segfaults during faster-whisper's language detection. Single-threaded is slow, but on this stack it's the only configuration that works at all.

---

## Contributing

VoxBox is three repos. Changes to a specific tool should be made in the child repo. Changes to the launcher, documentation, or cross-tool features go in the parent repo.

```bash
# After making changes in a child repo:
cd kokoro-tts   # or whisper-stt
git add . && git commit -m "your change"
git push

# Then update the parent to point to the new commit:
cd ..
git add kokoro-tts   # or whisper-stt
git commit -m "Update kokoro-tts submodule"
git push
```

---

## License

MIT — see [LICENSE](LICENSE) for the full text and upstream attribution.

Each submodule carries its own LICENSE file with attribution for its specific dependencies (Kokoro-82M, Faster-Whisper, WhisperX, pyannote.audio, PyTorch, etc.). The pyannote diarization model is released under a Creative Commons license that requires attribution.

---

## Versioning

This project uses [Semantic Versioning](https://semver.org/). Each repo (parent + 3 submodules) is versioned independently:

| Repo | Current | Changelog |
|------|---------|-----------|
| voxbox | [VERSION](VERSION) | [CHANGELOG.md](CHANGELOG.md) |
| kokoro-tts | [VERSION](kokoro-tts/VERSION) | [CHANGELOG.md](kokoro-tts/CHANGELOG.md) |
| whisper-stt | [VERSION](whisper-stt/VERSION) | [CHANGELOG.md](whisper-stt/CHANGELOG.md) |
| whisper-diarize | [VERSION](whisper-diarize/VERSION) | [CHANGELOG.md](whisper-diarize/CHANGELOG.md) |

Parent-repo bumps generally happen alongside changes that affect the launcher (`voxbox_cli.py`, `voxbox_gui.py`, `setup_voxbox.sh`) or cross-tool documentation. Submodule-only changes don't necessarily trigger a parent bump — but the parent's submodule pointer is updated to track the new commit.
