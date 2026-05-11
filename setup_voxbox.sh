#!/bin/bash
# ══════════════════════════════════════════════════════════════════════════════
# VoxBox — Setup Script
# Sets up both Kokoro TTS and Whisper STT
# ══════════════════════════════════════════════════════════════════════════════

set -e

INSTALL_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$INSTALL_DIR"

echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║       🔊  VOXBOX — LOCAL VOICE TOOLKIT SETUP  🔊         ║"
echo "║       Kokoro TTS + Whisper STT (+ optional Diarize)      ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""
echo "   Install directory: $INSTALL_DIR"
echo ""

# ── 1. Init submodules ──────────────────────────────────────────────────────
echo "🔍 Step 1/6: Initializing submodules..."
if [ -f "$INSTALL_DIR/.gitmodules" ]; then
    git submodule update --init --recursive
    echo "   ✅ Submodules ready"
else
    echo "   ⚠  No .gitmodules found — checking for local directories..."
    if [ ! -d "$INSTALL_DIR/kokoro-tts" ]; then
        echo "   ⚠  kokoro-tts/ not found. Clone it manually:"
        echo "      git clone https://github.com/mishandledservitor/kokoro-tts.git"
    fi
    if [ ! -d "$INSTALL_DIR/whisper-stt" ]; then
        echo "   ⚠  whisper-stt/ not found. Clone it manually:"
        echo "      git clone https://github.com/mishandledservitor/whisper-stt.git"
    fi
fi

# ── 2. Ensure Tkinter is available (the GUI needs it) ──────────────────────
echo ""
echo "═══════════════════════════════════════════════════════════"
echo "🪟  Step 2/6: Checking Tkinter (required for the GUI)..."
echo "═══════════════════════════════════════════════════════════"
echo ""
if python3 -c "import tkinter" 2>/dev/null; then
    echo "   ✅ tkinter available"
else
    echo "   ⚠  tkinter missing — the voxbox GUI will fail to launch."
    if command -v brew &>/dev/null; then
        PY_MM=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
        TK_FORMULA="python-tk@${PY_MM}"
        echo "   📦 Installing ${TK_FORMULA} via Homebrew..."
        if brew install "$TK_FORMULA"; then
            echo "   ✅ ${TK_FORMULA} installed"
        else
            echo "   ⚠  Could not install ${TK_FORMULA}. The GUI will not work until you"
            echo "      install Tk for your Python (e.g. 'brew install python-tk@${PY_MM}')."
            echo "      The CLI (./voxbox --cli, ./voxbox tts/stt …) will still work."
        fi
    else
        echo "   ⚠  Homebrew not found — please install Tk for your Python manually."
    fi
fi

# ── 3. Set up Kokoro TTS ───────────────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════════════"
echo "🎙  Step 3/6: Setting up Kokoro TTS..."
echo "═══════════════════════════════════════════════════════════"
echo ""

if [ -f "$INSTALL_DIR/kokoro-tts/setup_kokoro.sh" ]; then
    chmod +x "$INSTALL_DIR/kokoro-tts/setup_kokoro.sh"
    cd "$INSTALL_DIR/kokoro-tts"
    ./setup_kokoro.sh
    cd "$INSTALL_DIR"
else
    echo "   ⚠  kokoro-tts/setup_kokoro.sh not found — skipping"
fi

# ── 4. Set up Whisper STT ──────────────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════════════"
echo "🎤  Step 4/6: Setting up Whisper STT..."
echo "═══════════════════════════════════════════════════════════"
echo ""

if [ -f "$INSTALL_DIR/whisper-stt/setup_whisper.sh" ]; then
    chmod +x "$INSTALL_DIR/whisper-stt/setup_whisper.sh"
    cd "$INSTALL_DIR/whisper-stt"
    ./setup_whisper.sh
    cd "$INSTALL_DIR"
else
    echo "   ⚠  whisper-stt/setup_whisper.sh not found — skipping"
fi

# ── 5. Set up cloud STT (AssemblyAI + ElevenLabs) ──────────────────────────
echo ""
echo "═══════════════════════════════════════════════════════════"
echo "☁️   Step 5/6: Setting up cloud STT (AssemblyAI + ElevenLabs)..."
echo "═══════════════════════════════════════════════════════════"
echo ""

if [ -f "$INSTALL_DIR/assemblyai-stt/setup_assemblyai.sh" ]; then
    chmod +x "$INSTALL_DIR/assemblyai-stt/setup_assemblyai.sh"
    cd "$INSTALL_DIR/assemblyai-stt"
    ./setup_assemblyai.sh
    cd "$INSTALL_DIR"
else
    echo "   ⚠  assemblyai-stt/setup_assemblyai.sh not found — skipping"
fi

if [ -f "$INSTALL_DIR/speech-to-text/setup_elevenlabs.sh" ]; then
    chmod +x "$INSTALL_DIR/speech-to-text/setup_elevenlabs.sh"
    cd "$INSTALL_DIR/speech-to-text"
    ./setup_elevenlabs.sh
    cd "$INSTALL_DIR"
else
    echo "   ⚠  speech-to-text/setup_elevenlabs.sh not found — skipping"
fi

echo ""
echo "   ℹ  Cloud tools need API keys in .env files (gitignored):"
echo "      assemblyai-stt/.env    →  ASSEMBLYAI_API_KEY=..."
echo "      speech-to-text/.env    →  ELEVENLABS_API_KEY=..."

# ── 6. Optionally set up Whisper Diarize ───────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════════════"
echo "👥  Step 6/6: Whisper Diarize (optional, ~4 GB disk)"
echo "═══════════════════════════════════════════════════════════"
echo ""
echo "   Adds speaker identification using WhisperX + pyannote 3.1."
echo "   Requires PyTorch (~2 GB) + Whisper medium (~1.5 GB) + a free"
echo "   Hugging Face account & token."
echo ""

if [ -f "$INSTALL_DIR/whisper-diarize/setup_whisper_diarize.sh" ]; then
    read -p "   Set up Whisper Diarize now? [y/N] " c
    if [[ "$c" =~ ^[Yy]$ ]]; then
        chmod +x "$INSTALL_DIR/whisper-diarize/setup_whisper_diarize.sh"
        cd "$INSTALL_DIR/whisper-diarize"
        ./setup_whisper_diarize.sh
        cd "$INSTALL_DIR"
    else
        echo "   ⏭  Skipped — run later with:"
        echo "      ./whisper-diarize/setup_whisper_diarize.sh"
    fi
else
    echo "   ⚠  whisper-diarize/setup_whisper_diarize.sh not found — skipping"
fi

# ── Create launcher ─────────────────────────────────────────────────────────
cat > "$INSTALL_DIR/voxbox" << LAUNCHER
#!/bin/bash
SCRIPT_DIR="$INSTALL_DIR"
exec python3 "\$SCRIPT_DIR/voxbox_cli.py" "\$@"
LAUNCHER

chmod +x "$INSTALL_DIR/voxbox"

# ── Done! ────────────────────────────────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║              ✅  VOXBOX SETUP COMPLETE!                  ║"
echo "╠══════════════════════════════════════════════════════════╣"
echo "║                                                          ║"
echo "║  Unified launcher:                                       ║"
echo "║    ./voxbox                    Interactive menu           ║"
echo "║    ./voxbox tts \"Hello!\"       Quick text-to-speech      ║"
echo "║    ./voxbox stt recording.mp3  Quick transcription       ║"
echo "║    ./voxbox diarize call.mp3   Transcribe + label        ║"
echo "║                                                          ║"
echo "║  Or use each tool directly:                              ║"
echo "║    ./kokoro-tts/kokoro \"Hello!\"                          ║"
echo "║    ./whisper-stt/whisper recording.mp3                   ║"
echo "║    ./whisper-diarize/whisper-diarize interview.mp3       ║"
echo "║                                                          ║"
echo "║  Everything runs offline after setup.                    ║"
echo "║                                                          ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""
