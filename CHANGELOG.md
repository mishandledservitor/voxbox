# Changelog

All notable changes to VoxBox (parent repo) are documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/). Versions follow [Semantic Versioning](https://semver.org/).

For changes to individual tools, see:
- [kokoro-tts/CHANGELOG.md](kokoro-tts/CHANGELOG.md)
- [whisper-stt/CHANGELOG.md](whisper-stt/CHANGELOG.md)
- [whisper-diarize/CHANGELOG.md](whisper-diarize/CHANGELOG.md)

---

## [1.3.0] — 2026-04-16

### Added
- **`voxbox_gui.py`** — Tkinter GUI as the new default front door. Four screens: mode picker → file picker (with options) → processing (overall + per-file progress, ETA, live log, cancel) → done summary
- Root-level `inbox/`, `output/`, `processed/` folders for GUI use (per-tool inboxes still work for CLI)
- `./voxbox` (no args) now launches the GUI; `./voxbox --cli` brings back the old text-mode menu
- `--gui` flag on `voxbox_cli.py` to launch the GUI explicitly
- Worker thread + queue model for non-blocking subprocess execution; parses existing tool progress format (`60% 2m30s ~1m40s left`) for live progress bars
- Per-mode option panels: voice + speed for TTS, model + format for STT, model + speakers + format for Diarize

### Changed
- README structure — GUI is documented first; CLI demoted to "advanced"
- `.gitignore` — exclude root `inbox/*`, `output/*`, `processed/*` (with `.gitkeep` exemptions)

## [1.2.0] — 2026-04-16

### Added
- `whisper-diarize/` — third tool: speech-to-text with speaker diarization (WhisperX + pyannote 3.1)
- `/diarize` and `/diarize-inbox` commands in the interactive menu
- `./voxbox diarize file.mp3` pass-through CLI
- `setup_voxbox.sh` now offers an opt-in fourth step for installing whisper-diarize (~4 GB)
- `uninstall_voxbox.sh` now invokes the whisper-diarize uninstaller
- README updated with diarization usage, requirements, and the PyTorch trade-off

## [1.1.0] — 2026-04-03

### Added
- `/inbox` command in interactive menu — transcribe all files in `whisper-stt/inbox/` at once
- Inbox file count shown in `/status` output when files are waiting
- Comprehensive project documentation (README, CHANGELOG, VERSION)

### Fixed
- Registered `whisper-stt` submodule in `.gitmodules` (was missing, causing `git submodule update` to fail)
- `setup_voxbox.sh` now completes successfully with both submodules

## [1.0.0] — 2026-04-03

### Added
- Unified `voxbox_cli.py` launcher with interactive menu
- `/tts` and `/stt` commands to launch each tool
- `/status` command to check tool installation
- `setup_voxbox.sh` master installer (orchestrates both child setups)
- `uninstall_voxbox.sh` master uninstaller
- Git submodule integration for kokoro-tts and whisper-stt
- Pass-through CLI: `./voxbox tts "text"` and `./voxbox stt file.mp3`
