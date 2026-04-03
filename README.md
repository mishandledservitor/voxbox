# VoxBox — Local Voice Toolkit

Text-to-speech and speech-to-text, fully offline. No cloud, no API keys, no PyTorch.

```
voxbox/
├── kokoro-tts/    Text-to-Speech  (Kokoro-82M, ONNX Runtime)
└── whisper-stt/   Speech-to-Text  (Faster-Whisper, CTranslate2)
```

---

## Setup

```bash
git clone --recursive https://github.com/mishandledservitor/voxbox.git
cd voxbox
chmod +x setup_voxbox.sh
./setup_voxbox.sh
```

This sets up both tools: Python venvs, dependencies, and model downloads. Each tool is self-contained in its own directory.

---

## Usage

### Unified Launcher

```bash
# Interactive menu
./voxbox

# Text-to-speech
./voxbox tts "Hello, this is VoxBox!"
./voxbox tts -v bf_emma "British accent."
./voxbox tts -o greeting.mp3 "Welcome!"

# Speech-to-text
./voxbox stt recording.mp3
./voxbox stt -m medium interview.wav
./voxbox stt -o subtitles.srt podcast.mp3

# Check tool status
./voxbox --status
```

### Or Use Each Tool Directly

```bash
# Kokoro TTS
./kokoro-tts/kokoro "Hello world"
./kokoro-tts/kokoro                     # interactive mode

# Whisper STT
./whisper-stt/whisper recording.mp3
./whisper-stt/whisper                   # interactive mode
./whisper-stt/whisper --record          # record from mic
```

### Interactive Menu Commands

```
/tts              — launch Kokoro TTS (interactive)
/stt              — launch Whisper STT (interactive)
/tts "text"       — quick text-to-speech
/stt file.mp3     — quick transcription
/status           — check installed tools
/help             — show commands
/quit             — exit
```

---

## Kokoro TTS

Local text-to-speech using [Kokoro-82M](https://github.com/hexgrad/kokoro) via ONNX Runtime.

- **67 voices** across 11 languages
- Speed control (0.1-3.0x)
- WAV and MP3 output
- Interactive mode with slash commands

See [kokoro-tts/README.md](kokoro-tts/README.md) for full docs.

---

## Whisper STT

Local speech-to-text using [Faster-Whisper](https://github.com/SYSTRAN/faster-whisper) via CTranslate2.

- **10 model sizes** from tiny (75 MB) to large-v3 (2.9 GB)
- Auto language detection (99+ languages)
- Output as text, SRT, VTT, or JSON
- Microphone recording support
- Interactive mode with slash commands

See [whisper-stt/README.md](whisper-stt/README.md) for full docs.

---

## Architecture

Three independent git repos:

| Repo | Purpose | Backend |
|------|---------|---------|
| [voxbox](https://github.com/mishandledservitor/voxbox) | Parent — unified launcher + docs | Python (subprocess) |
| [kokoro-tts](https://github.com/mishandledservitor/kokoro-tts) | Text-to-Speech | kokoro-onnx (ONNX Runtime) |
| [whisper-stt](https://github.com/mishandledservitor/whisper-stt) | Speech-to-Text | faster-whisper (CTranslate2) |

Each child repo works standalone. The parent uses git submodules to bundle them together.

- No shared dependencies — each tool has its own Python venv
- No PyTorch — both tools use lightweight inference backends
- Fully offline after initial setup

---

## Uninstall

```bash
chmod +x uninstall_voxbox.sh
./uninstall_voxbox.sh
```

Runs each child's uninstaller (with confirmation prompts), then cleans up the VoxBox launcher.
