# Changelog

All notable changes to VoxBox (parent repo) are documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/). Versions follow [Semantic Versioning](https://semver.org/).

For changes to individual tools, see:
- [kokoro-tts/CHANGELOG.md](kokoro-tts/CHANGELOG.md)
- [whisper-stt/CHANGELOG.md](whisper-stt/CHANGELOG.md)
- [whisper-diarize/CHANGELOG.md](whisper-diarize/CHANGELOG.md)

---

## [1.4.0] — 2026-05-11

### Added
- **ElevenLabs Scribe — generic CLI + GUI integration.** The `speech-to-text` submodule now ships an `elevenlabs` launcher that mirrors the `assemblyai-stt/assemblyai` interface (`-f text/srt/vtt/json`, `-o`, `-l`, `--speakers`, `--inbox`, `--no-print`), backed by a new `elevenlabs_stt.py`. The previously-greyed-out "Transcribe (Cloud · ElevenLabs)" tile in the GUI is now functional out of the box.
- **`speech-to-text/setup_elevenlabs.sh`** — first-class setup script for the submodule (creates venv, installs `requirements.txt`, writes the `./elevenlabs` launcher, prompts for the API key).
- **CLAUDE.md** at the repo root — onboarding notes for AI agents and humans, with the install gotchas we hit on Python 3.14 / fresh macOS.

### Fixed
- **GUI buttons no longer cramped on macOS.** The aqua ttk theme ignored `padding` on `Mode.TButton`, so the five mode buttons rendered with the text jammed against the borders. Switched the mode buttons to plain `tk.Button` with explicit `padx=20, pady=12`, which aqua honours.
- **GUI window no longer cuts off the ElevenLabs tile.** Replaced the hardcoded 760×600 geometry with `update_idletasks()` + `winfo_reqheight()` so the window auto-sizes to its content at whatever DPI/font scale the system uses. Minimum size raised to 700×560.
- **Setup now installs Tk for the running Python.** Python 3.14 from Homebrew does **not** include `tkinter`; the GUI failed with `ModuleNotFoundError: No module named '_tkinter'`. `setup_voxbox.sh` now probes for `tkinter` and `brew install python-tk@<X.Y>` for the active Python if it's missing (graceful fallback if Homebrew isn't around — CLI remains usable).
- **Stale GUI footer.** The mode picker footer was still showing `v1.3.0` after the 1.3.1 release — now reads from the bumped version and will be kept in sync going forward.

### Changed
- **`setup_voxbox.sh`** restructured from 4 steps to 6: submodule init → Tkinter check → Kokoro TTS → Whisper STT → cloud STT (AssemblyAI + ElevenLabs, runs both submodule setup scripts) → optional Whisper Diarize. Cloud setup is no longer something you have to remember to run by hand.
- `voxbox_gui.py` mode button font dropped from 14pt to 13pt with explicit internal padding for visual balance.

## [1.3.1] — 2026-04-16

### Fixed
- **GUI: live progress for `whisper-diarize`.** The diarize subprocess was buffering its stdout (no TTY), so stage prints (`Loading model...`, `[1/3] Transcribing...`, etc.) sat in the buffer for many minutes before flushing — leaving the GUI stuck at "starting..." with no log output. Setting `PYTHONUNBUFFERED=1` in the subprocess environment makes output stream in real time.
- **GUI: progress bar now moves during diarize.** `whisper-diarize` prints stage markers, not percentages, so the existing `PROGRESS_RE` never matched and the bar stayed at 0% for the entire run. Added a stage-marker → progress map (loading 5–8% → transcribing 12% → aligning 52% → diarizing 78% → finalizing 97% → done 100%) with friendly stage labels.
- **GUI: silent stages no longer look frozen.** The diarize step is genuinely slow (5–10× audio duration on Intel Mac CPU) and emits no per-line output. The status label now shows in-stage elapsed time (`78%  diarizing speakers (slow — ~5–10× audio length on CPU)…  (4m 12s)`) ticking every 500ms, so the user can tell the process is working rather than wedged.

### Added
- LICENSE file (MIT) at the repo root with upstream attribution.
- License footers on all submodule READMEs.

### Changed
- `.gitignore` expanded to cover IDE/editor files (`.vscode/`, `.idea/`, swap files), local env files (`.env`, `.envrc`), and Python build artifacts.
- All three submodules bumped: kokoro-tts → 1.0.2, whisper-stt → 1.1.1, whisper-diarize → 1.0.2 (each picks up LICENSE + .gitignore polish; whisper-diarize also fixes the Intel-Mac threading deadlock + segfault and quietens the Lightning checkpoint-upgrade log noise).

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
