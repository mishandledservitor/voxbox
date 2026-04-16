#!/usr/bin/env python3
"""
VoxBox — Local Voice Toolkit (TTS + STT + Diarization)
Unified launcher for Kokoro TTS, Whisper STT, and Whisper Diarize.

Usage:
    python voxbox_cli.py                              # Launch GUI (default)
    python voxbox_cli.py --cli                        # Old text-mode interactive menu
    python voxbox_cli.py tts "Hello world"            # Quick TTS
    python voxbox_cli.py stt recording.mp3            # Quick STT
    python voxbox_cli.py diarize interview.mp3        # Quick STT + speaker labels
    python voxbox_cli.py tts --list-voices            # Pass-through to kokoro
    python voxbox_cli.py stt --list-models            # Pass-through to whisper
"""

import os
import subprocess
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

INBOX_DIR = os.path.join(SCRIPT_DIR, "whisper-stt", "inbox")
DIARIZE_INBOX_DIR = os.path.join(SCRIPT_DIR, "whisper-diarize", "inbox")
SUPPORTED_AUDIO = {"mp3", "mp4", "wav", "m4a", "ogg", "flac",
                   "aac", "webm", "mkv", "mov", "avi", "opus"}

TOOLS = {
    "tts": {
        "name": "Kokoro TTS",
        "launcher": os.path.join(SCRIPT_DIR, "kokoro-tts", "kokoro"),
        "setup": os.path.join(SCRIPT_DIR, "kokoro-tts", "setup_kokoro.sh"),
        "desc": "Text-to-Speech (67 voices, ONNX Runtime)",
    },
    "stt": {
        "name": "Whisper STT",
        "launcher": os.path.join(SCRIPT_DIR, "whisper-stt", "whisper"),
        "setup": os.path.join(SCRIPT_DIR, "whisper-stt", "setup_whisper.sh"),
        "desc": "Speech-to-Text (Faster-Whisper, CTranslate2)",
    },
    "diarize": {
        "name": "Whisper Diarize",
        "launcher": os.path.join(SCRIPT_DIR, "whisper-diarize", "whisper-diarize"),
        "setup": os.path.join(SCRIPT_DIR, "whisper-diarize", "setup_whisper_diarize.sh"),
        "desc": "STT + speaker diarization (WhisperX + pyannote 3.1)",
    },
}


def check_tool(key):
    tool = TOOLS[key]
    return os.path.isfile(tool["launcher"]) and os.access(tool["launcher"], os.X_OK)


def run_tool(key, args):
    tool = TOOLS[key]
    if not check_tool(key):
        print(f"  ⚠  {tool['name']} is not set up.")
        print(f"     Run: cd {os.path.dirname(tool['setup'])} && chmod +x {os.path.basename(tool['setup'])} && ./{os.path.basename(tool['setup'])}")
        print(f"     Or use: ./setup_voxbox.sh")
        return 1
    return subprocess.call([tool["launcher"]] + args)


def count_inbox(inbox_dir=INBOX_DIR):
    """Count audio files in the given inbox directory."""
    if not os.path.isdir(inbox_dir):
        return 0
    return sum(1 for f in os.listdir(inbox_dir)
               if os.path.splitext(f)[1].lower().lstrip(".") in SUPPORTED_AUDIO)


def print_status():
    print("\n  Tool Status:")
    for key, tool in TOOLS.items():
        installed = check_tool(key)
        icon = "✅" if installed else "❌"
        print(f"    {icon} {tool['name']:<16} — {tool['desc']}")
    stt_count = count_inbox(INBOX_DIR)
    diarize_count = count_inbox(DIARIZE_INBOX_DIR)
    if stt_count:
        print(f"\n  📬 {stt_count} file(s) in whisper-stt/inbox/ — use /inbox to transcribe")
    if diarize_count:
        print(f"  📬 {diarize_count} file(s) in whisper-diarize/inbox/ — use /diarize-inbox to process")
    print()


def interactive_mode():
    print("\n╔══════════════════════════════════════════════╗")
    print("║        🔊  VOXBOX — LOCAL VOICE TOOLKIT  🔊   ║")
    print("╚══════════════════════════════════════════════╝")

    print_status()

    _print_help()

    while True:
        try:
            text = input("  ▶ ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n\n  👋 Goodbye!\n")
            break

        if not text:
            continue

        if not text.startswith("/"):
            print("  ⚠  Use /tts, /stt, or /diarize to get started. Type /help for commands.")
            continue

        parts = text.split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1].strip() if len(parts) > 1 else ""

        if cmd in ("/quit", "/exit", "/q"):
            print("\n  👋 Goodbye!\n")
            break
        elif cmd == "/tts":
            args = arg.split() if arg else []
            run_tool("tts", args)
        elif cmd == "/stt":
            args = arg.split() if arg else []
            run_tool("stt", args)
        elif cmd == "/diarize":
            args = arg.split() if arg else []
            run_tool("diarize", args)
        elif cmd == "/inbox":
            run_tool("stt", ["--inbox"])
        elif cmd == "/diarize-inbox":
            run_tool("diarize", ["--inbox"])
        elif cmd == "/status":
            print_status()
        elif cmd == "/help":
            _print_help()
        else:
            print(f"  ⚠  Unknown command: {cmd}. Type /help for commands.")


def _print_help():
    print("  Commands:")
    print("    /tts                 — launch Kokoro TTS (interactive)")
    print("    /stt                 — launch Whisper STT (interactive)")
    print("    /diarize             — launch Whisper Diarize (interactive)")
    print('    /tts "text"          — quick text-to-speech')
    print("    /stt file.mp3        — quick transcription")
    print("    /diarize file.mp3    — quick transcription with speaker labels")
    print("    /inbox               — transcribe all files in whisper-stt/inbox/")
    print("    /diarize-inbox       — diarize all files in whisper-diarize/inbox/")
    print("    /status              — check installed tools")
    print("    /help                — show this help")
    print("    /quit                — exit\n")


def launch_gui():
    """Launch voxbox_gui.py in this same Python interpreter."""
    gui_path = os.path.join(SCRIPT_DIR, "voxbox_gui.py")
    if not os.path.isfile(gui_path):
        print(f"⚠  GUI script not found at {gui_path}")
        print("   Falling back to text-mode interactive menu...")
        interactive_mode()
        return
    try:
        sys.exit(subprocess.call([sys.executable, gui_path]))
    except KeyboardInterrupt:
        sys.exit(0)


def main():
    if len(sys.argv) < 2:
        # Default: launch GUI
        launch_gui()
        return

    cmd = sys.argv[1].lower()

    if cmd == "--status":
        print_status()
    elif cmd == "--help" or cmd == "-h":
        print(__doc__)
    elif cmd == "--cli":
        interactive_mode()
    elif cmd == "--gui":
        launch_gui()
    elif cmd in ("tts", "stt", "diarize"):
        extra_args = sys.argv[2:]
        sys.exit(run_tool(cmd, extra_args))
    else:
        print(f"⚠  Unknown command: {cmd}")
        print("   Usage: voxbox [tts|stt|diarize] [args...]")
        print("   Or:    voxbox            (launches GUI)")
        print("   Or:    voxbox --cli      (text-mode interactive menu)")
        sys.exit(1)


if __name__ == "__main__":
    main()
