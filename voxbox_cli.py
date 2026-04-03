#!/usr/bin/env python3
"""
VoxBox — Local Voice Toolkit (TTS + STT)
Unified launcher for Kokoro TTS and Whisper STT.

Usage:
    python voxbox_cli.py                              # Interactive menu
    python voxbox_cli.py tts "Hello world"            # Quick TTS
    python voxbox_cli.py stt recording.mp3            # Quick STT
    python voxbox_cli.py tts --list-voices            # Pass-through to kokoro
    python voxbox_cli.py stt --list-models            # Pass-through to whisper
"""

import os
import subprocess
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

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


def print_status():
    print("\n  Tool Status:")
    for key, tool in TOOLS.items():
        installed = check_tool(key)
        icon = "✅" if installed else "❌"
        print(f"    {icon} {tool['name']:<16} — {tool['desc']}")
    print()


def interactive_mode():
    print("\n╔══════════════════════════════════════════════╗")
    print("║        🔊  VOXBOX — LOCAL VOICE TOOLKIT  🔊   ║")
    print("╚══════════════════════════════════════════════╝")

    print_status()

    print("  Commands:")
    print("    /tts              — launch Kokoro TTS (interactive)")
    print("    /stt              — launch Whisper STT (interactive)")
    print('    /tts "text"       — quick text-to-speech')
    print("    /stt file.mp3     — quick transcription")
    print("    /status           — check installed tools")
    print("    /help             — show this help")
    print("    /quit             — exit\n")

    while True:
        try:
            text = input("  ▶ ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n\n  👋 Goodbye!\n")
            break

        if not text:
            continue

        if not text.startswith("/"):
            print("  ⚠  Use /tts or /stt to get started. Type /help for commands.")
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
        elif cmd == "/status":
            print_status()
        elif cmd == "/help":
            print("\n  Commands:")
            print("    /tts              — launch Kokoro TTS (interactive)")
            print("    /stt              — launch Whisper STT (interactive)")
            print('    /tts "text"       — quick text-to-speech')
            print("    /stt file.mp3     — quick transcription")
            print("    /status           — check installed tools")
            print("    /help             — show this help")
            print("    /quit             — exit\n")
        else:
            print(f"  ⚠  Unknown command: {cmd}. Type /help for commands.")


def main():
    if len(sys.argv) < 2:
        interactive_mode()
        return

    cmd = sys.argv[1].lower()

    if cmd == "--status":
        print_status()
    elif cmd == "--help" or cmd == "-h":
        print(__doc__)
    elif cmd in ("tts", "stt"):
        extra_args = sys.argv[2:]
        sys.exit(run_tool(cmd, extra_args))
    else:
        print(f"⚠  Unknown command: {cmd}")
        print("   Usage: voxbox [tts|stt] [args...]")
        print("   Or just: ./voxbox  (for interactive mode)")
        sys.exit(1)


if __name__ == "__main__":
    main()
