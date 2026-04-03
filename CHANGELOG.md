# Changelog

All notable changes to VoxBox (parent repo) are documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/). Versions follow [Semantic Versioning](https://semver.org/).

For changes to individual tools, see:
- [kokoro-tts/CHANGELOG.md](kokoro-tts/CHANGELOG.md)
- [whisper-stt/CHANGELOG.md](whisper-stt/CHANGELOG.md)

---

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
