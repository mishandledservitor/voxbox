#!/bin/bash
# ══════════════════════════════════════════════════════════════════════════════
# VoxBox — Uninstall Script
# ══════════════════════════════════════════════════════════════════════════════

INSTALL_DIR="$(cd "$(dirname "$0")" && pwd)"

echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║       🗑  VOXBOX — UNINSTALL                             ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""
echo "   Directory: $INSTALL_DIR"
echo ""

# ── 1. Kokoro TTS ───────────────────────────────────────────────────────────
if [ -f "$INSTALL_DIR/kokoro-tts/uninstall_kokoro.sh" ]; then
    echo "🎙  Kokoro TTS"
    read -p "   Run Kokoro uninstaller? [y/N] " c
    if [[ "$c" =~ ^[Yy]$ ]]; then
        chmod +x "$INSTALL_DIR/kokoro-tts/uninstall_kokoro.sh"
        cd "$INSTALL_DIR/kokoro-tts"
        ./uninstall_kokoro.sh
        cd "$INSTALL_DIR"
    else
        echo "   ⏭  Skipped"
    fi
fi

# ── 2. Whisper STT ──────────────────────────────────────────────────────────
echo ""
if [ -f "$INSTALL_DIR/whisper-stt/uninstall_whisper.sh" ]; then
    echo "🎤  Whisper STT"
    read -p "   Run Whisper uninstaller? [y/N] " c
    if [[ "$c" =~ ^[Yy]$ ]]; then
        chmod +x "$INSTALL_DIR/whisper-stt/uninstall_whisper.sh"
        cd "$INSTALL_DIR/whisper-stt"
        ./uninstall_whisper.sh
        cd "$INSTALL_DIR"
    else
        echo "   ⏭  Skipped"
    fi
fi

# ── 3. VoxBox launcher ──────────────────────────────────────────────────────
echo ""
if [ -f "$INSTALL_DIR/voxbox" ]; then
    echo "🚀 VoxBox launcher"
    read -p "   Delete? [y/N] " c; [[ "$c" =~ ^[Yy]$ ]] && rm -f "$INSTALL_DIR/voxbox" && echo "   ✅ Removed" || echo "   ⏭  Skipped"
fi

echo ""
echo "✅ Uninstall complete."
echo ""
