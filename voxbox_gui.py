#!/usr/bin/env python3
"""
VoxBox GUI — single front door for all three voxbox tools.

Flow: pick mode (TTS / STT / Diarize) → pick files in inbox/ → process → done.
All three tools run via subprocess against their existing launchers, so the
per-tool venvs stay isolated.

Run directly:
    python3 voxbox_gui.py
Or via the parent launcher:
    ./voxbox          # no args = GUI
"""

import os
import queue
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

INBOX_DIR = os.path.join(SCRIPT_DIR, "inbox")
OUTPUT_DIR = os.path.join(SCRIPT_DIR, "output")
PROCESSED_DIR = os.path.join(SCRIPT_DIR, "processed")

AUDIO_EXTS = {"mp3", "mp4", "wav", "m4a", "ogg", "flac",
              "aac", "webm", "mkv", "mov", "avi", "opus"}
TEXT_EXTS = {"txt", "md"}

# ── Tool registry ───────────────────────────────────────────────────────────

MODES = {
    "tts": {
        "label": "Text-to-Speech",
        "emoji": "🗣",
        "description": "Convert text files in inbox/ to spoken audio",
        "launcher": os.path.join(SCRIPT_DIR, "kokoro-tts", "kokoro"),
        "input_exts": TEXT_EXTS,
        "output_ext": "mp3",
    },
    "stt": {
        "label": "Transcribe",
        "emoji": "🎤",
        "description": "Convert audio files in inbox/ to text",
        "launcher": os.path.join(SCRIPT_DIR, "whisper-stt", "whisper"),
        "input_exts": AUDIO_EXTS,
        "output_ext": "txt",
    },
    "diarize": {
        "label": "Transcribe + Identify Speakers",
        "emoji": "👥",
        "description": "Transcribe and label who said what",
        "launcher": os.path.join(SCRIPT_DIR, "whisper-diarize", "whisper-diarize"),
        "input_exts": AUDIO_EXTS,
        "output_ext": "txt",
    },
}

VOICES = {
    "American Female": ["af_alloy", "af_aoede", "af_bella", "af_heart", "af_jessica",
                        "af_kore", "af_nicole", "af_nova", "af_river", "af_sarah", "af_sky"],
    "American Male": ["am_adam", "am_echo", "am_eric", "am_fenrir",
                      "am_liam", "am_michael", "am_onyx", "am_puck"],
    "British Female": ["bf_alice", "bf_emma", "bf_lily"],
    "British Male": ["bm_daniel", "bm_fable", "bm_george", "bm_lewis"],
    "Other Languages": ["ef_dora", "em_alex", "ff_siwis",
                        "hf_alpha", "hf_beta", "hm_omega", "hm_psi",
                        "if_sara", "im_nicola",
                        "jf_alpha", "jf_gongitsune", "jf_nezumi", "jf_tebukuro", "jm_kumo",
                        "pf_dora", "pm_alex",
                        "zf_xiaobei", "zf_xiaoni", "zf_xiaoxiao", "zf_xiaoyi",
                        "zm_yunjian", "zm_yunxia", "zm_yunxi", "zm_yunyang"],
}
DEFAULT_VOICE = "af_heart"

STT_MODELS = ["tiny", "base", "small", "medium", "large-v3", "turbo"]
DIARIZE_MODELS = ["tiny", "base", "small", "medium", "large-v3"]
OUTPUT_FORMATS = ["text", "srt", "vtt", "json"]
FORMAT_EXT = {"text": "txt", "srt": "srt", "vtt": "vtt", "json": "json"}

# Regex matches the existing whisper/kokoro progress format:
#   ┃████████░░░░┃ 60% 2m30s ~1m40s left
PROGRESS_RE = re.compile(r"(\d{1,3})%\s+\S+\s+~?(\S+)\s+left")

# whisper-diarize doesn't print percentages — just stage markers. Map them to
# coarse progress so the bar visibly moves through the pipeline. Order matters
# (longest match first wins).
DIARIZE_STAGES = [
    ("Loading WhisperX model",        2,  "loading model..."),
    ("ASR loaded",                    5,  "model loaded"),
    ("Loading diarization pipeline",  6,  "loading diarizer..."),
    ("Diarization loaded",            8,  "diarizer loaded"),
    ("Audio duration:",              10,  "audio loaded"),
    ("[1/3]",                        12,  "transcribing..."),
    ("Loading alignment model",      45,  "loading aligner..."),
    ("Alignment loaded",             50,  "aligner loaded"),
    ("[2/3]",                        52,  "aligning timestamps..."),
    ("[3/3]",                        78,  "diarizing speakers (slow — ~5–10× audio length on CPU)..."),
    ("speaker(s) in",                97,  "finalizing..."),
    ("Done in",                     100,  "done"),
]


def parse_diarize_stage(line):
    """Return (pct, label) if the line matches a known diarize stage marker."""
    for marker, pct, label in DIARIZE_STAGES:
        if marker in line:
            return pct, label
    return None

# ── Helpers ─────────────────────────────────────────────────────────────────

def ensure_dirs():
    for d in (INBOX_DIR, OUTPUT_DIR, PROCESSED_DIR):
        os.makedirs(d, exist_ok=True)


def open_in_finder(path):
    """Open a directory in the macOS Finder."""
    if os.path.exists(path):
        subprocess.Popen(["open", path])


def scan_inbox(exts):
    """Return list of (path, display_name, size_str) for files matching exts."""
    if not os.path.isdir(INBOX_DIR):
        return []
    items = []
    for name in sorted(os.listdir(INBOX_DIR)):
        if name.startswith("."):
            continue
        ext = os.path.splitext(name)[1].lower().lstrip(".")
        if ext not in exts:
            continue
        full = os.path.join(INBOX_DIR, name)
        size_mb = os.path.getsize(full) / (1024 * 1024)
        items.append((full, name, f"{size_mb:.1f} MB"))
    return items


def tool_installed(mode):
    launcher = MODES[mode]["launcher"]
    return os.path.isfile(launcher) and os.access(launcher, os.X_OK)


def fmt_time(seconds):
    if seconds is None or seconds <= 0:
        return "—"
    if seconds < 60:
        return f"{int(seconds)}s"
    m, s = divmod(int(seconds), 60)
    if m < 60:
        return f"{m}m {s:02d}s"
    h, m = divmod(m, 60)
    return f"{h}h {m:02d}m"


def unique_path(path):
    """If path exists, append _1, _2, ... before the extension."""
    if not os.path.exists(path):
        return path
    base, ext = os.path.splitext(path)
    i = 1
    while os.path.exists(f"{base}_{i}{ext}"):
        i += 1
    return f"{base}_{i}{ext}"


# ── Subprocess worker ──────────────────────────────────────────────────────

class Worker(threading.Thread):
    """Runs the selected files through the chosen tool, posts progress to a queue."""

    def __init__(self, mode, files, settings, msg_queue, cancel_event):
        super().__init__(daemon=True)
        self.mode = mode
        self.files = files  # list of input paths
        self.settings = settings  # dict of mode-specific options
        self.q = msg_queue
        self.cancel = cancel_event
        self.proc = None  # current subprocess

    def build_command(self, input_path, output_path):
        m = self.mode
        s = self.settings
        launcher = MODES[m]["launcher"]
        if m == "tts":
            return [launcher, "--no-play",
                    "-v", s["voice"], "-s", str(s["speed"]),
                    "-o", output_path, "-f", input_path]
        elif m == "stt":
            return [launcher, "-m", s["model"],
                    "-f", s["format"], "-o", output_path,
                    "--no-print", input_path]
        elif m == "diarize":
            cmd = [launcher, "-m", s["model"],
                   "-f", s["format"], "-o", output_path,
                   "--no-print"]
            if s.get("fixed_speakers"):
                n = s["fixed_speakers"]
                cmd += ["--min-speakers", str(n), "--max-speakers", str(n)]
            cmd += [input_path]
            return cmd
        raise ValueError(f"Unknown mode: {m}")

    def run(self):
        total = len(self.files)
        results = []
        ext = FORMAT_EXT.get(self.settings.get("format", "text"), "txt") \
            if self.mode != "tts" else MODES[self.mode]["output_ext"]

        for i, input_path in enumerate(self.files):
            if self.cancel.is_set():
                self.q.put(("cancelled",))
                return

            stem = os.path.splitext(os.path.basename(input_path))[0]
            output_path = unique_path(os.path.join(OUTPUT_DIR, f"{stem}.{ext}"))
            cmd = self.build_command(input_path, output_path)

            self.q.put(("file_start", i, total, os.path.basename(input_path)))
            t0 = time.time()
            success = False
            err_tail = []
            # Force unbuffered output from the child Python so we see stage
            # prints in real time instead of one big dump at the end.
            env = os.environ.copy()
            env["PYTHONUNBUFFERED"] = "1"

            try:
                self.proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    env=env,
                    # Start in a new process group so we can kill child threads cleanly
                    preexec_fn=os.setsid if os.name != "nt" else None,
                )
                # Read line-by-line; PROGRESS_RE-matching lines update the bar
                for raw_line in self.proc.stdout:
                    if self.cancel.is_set():
                        self._terminate_proc()
                        self.q.put(("cancelled",))
                        return
                    line = raw_line.rstrip("\r\n")
                    if not line.strip():
                        continue
                    # Strip terminal CR-progress redraws into separate lines
                    for piece in line.split("\r"):
                        piece = piece.strip()
                        if not piece:
                            continue
                        m = PROGRESS_RE.search(piece)
                        if m:
                            pct = int(m.group(1))
                            eta = m.group(2)
                            self.q.put(("progress", pct, eta))
                        elif self.mode == "diarize":
                            stage = parse_diarize_stage(piece)
                            if stage:
                                pct, label = stage
                                self.q.put(("stage", pct, label))
                        self.q.put(("log", piece))
                        err_tail.append(piece)
                        if len(err_tail) > 30:
                            err_tail.pop(0)
                rc = self.proc.wait()
                success = (rc == 0 and os.path.isfile(output_path))
            except Exception as e:
                self.q.put(("log", f"⚠  {e}"))
                err_tail.append(str(e))

            elapsed = time.time() - t0

            if success:
                # Move input to processed/
                dest = unique_path(os.path.join(PROCESSED_DIR, os.path.basename(input_path)))
                try:
                    shutil.move(input_path, dest)
                except Exception as e:
                    self.q.put(("log", f"⚠  Could not move to processed/: {e}"))
                results.append({
                    "input": os.path.basename(input_path),
                    "output": output_path,
                    "elapsed": elapsed,
                    "ok": True,
                })
            else:
                results.append({
                    "input": os.path.basename(input_path),
                    "output": None,
                    "elapsed": elapsed,
                    "ok": False,
                    "error": "\n".join(err_tail[-10:]),
                })

            self.q.put(("file_done", i, total, success, elapsed))
            self.proc = None

        self.q.put(("all_done", results))

    def _terminate_proc(self):
        if self.proc and self.proc.poll() is None:
            try:
                if os.name == "nt":
                    self.proc.terminate()
                else:
                    os.killpg(os.getpgid(self.proc.pid), signal.SIGTERM)
            except Exception:
                pass


# ── GUI ────────────────────────────────────────────────────────────────────

class VoxBoxGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("VoxBox")
        self.root.geometry("760x600")
        self.root.minsize(640, 480)

        # State
        self.mode = None
        self.selected_files = []  # list of paths
        self.worker = None
        self.cancel_event = threading.Event()
        self.msg_q = queue.Queue()
        self.start_time = None
        self.file_durations = []  # completed file elapsed times for ETA
        self.results = []
        # Tracks (label, started_at) for the current pipeline stage. Used to
        # show "in <stage> for 5m 12s" so silent stages still tick visibly.
        self.current_stage = None

        # Try to use a slightly nicer ttk theme on macOS
        style = ttk.Style()
        try:
            style.theme_use("aqua")
        except tk.TclError:
            pass
        style.configure("Mode.TButton", font=("Helvetica", 14), padding=12)
        style.configure("Header.TLabel", font=("Helvetica", 16, "bold"))
        style.configure("Sub.TLabel", font=("Helvetica", 11), foreground="#666666")

        ensure_dirs()

        self.container = ttk.Frame(root, padding=20)
        self.container.pack(fill=tk.BOTH, expand=True)

        self.show_mode_screen()

        # Begin queue polling
        self.root.after(100, self._poll_queue)

    # ── Frame management ────────────────────────────────────────────────────

    def _clear(self):
        for child in self.container.winfo_children():
            child.destroy()

    # ── Screen 1: Mode selection ────────────────────────────────────────────

    def show_mode_screen(self):
        self.mode = None
        self.selected_files = []
        self._clear()

        ttk.Label(self.container, text="VoxBox",
                  font=("Helvetica", 24, "bold")).pack(pady=(10, 4))
        ttk.Label(self.container, text="What do you want to do?",
                  style="Sub.TLabel").pack(pady=(0, 24))

        for key, m in MODES.items():
            installed = tool_installed(key)
            btn_text = f"{m['emoji']}  {m['label']}"
            if not installed:
                btn_text += "   (not installed)"
            btn = ttk.Button(
                self.container, text=btn_text,
                style="Mode.TButton", width=46,
                command=lambda k=key: self.show_file_screen(k),
            )
            if not installed:
                btn.state(["disabled"])
            btn.pack(pady=6)
            ttk.Label(self.container, text=m["description"],
                      style="Sub.TLabel").pack(pady=(0, 12))

        # Footer
        footer = ttk.Frame(self.container)
        footer.pack(side=tk.BOTTOM, fill=tk.X, pady=(20, 0))
        ttk.Button(footer, text="📁 Open inbox folder",
                   command=lambda: open_in_finder(INBOX_DIR)).pack(side=tk.LEFT)
        ttk.Button(footer, text="📂 Open output folder",
                   command=lambda: open_in_finder(OUTPUT_DIR)).pack(side=tk.LEFT, padx=8)
        ttk.Label(footer, text="v1.3.0", style="Sub.TLabel").pack(side=tk.RIGHT)

    # ── Screen 2: File selection ────────────────────────────────────────────

    def show_file_screen(self, mode_key):
        self.mode = mode_key
        m = MODES[mode_key]
        self._clear()

        # Header
        header = ttk.Frame(self.container)
        header.pack(fill=tk.X, pady=(0, 12))
        ttk.Button(header, text="← Back", command=self.show_mode_screen).pack(side=tk.LEFT)
        ttk.Label(header, text=f"  {m['emoji']}  {m['label']}",
                  style="Header.TLabel").pack(side=tk.LEFT, padx=8)

        # File list
        files_frame = ttk.LabelFrame(self.container, text="Files in inbox/", padding=8)
        files_frame.pack(fill=tk.BOTH, expand=True)

        list_container = ttk.Frame(files_frame)
        list_container.pack(fill=tk.BOTH, expand=True)

        self.file_listbox = tk.Listbox(list_container, selectmode=tk.MULTIPLE,
                                       activestyle="none", font=("Helvetica", 12),
                                       height=8)
        scrollbar = ttk.Scrollbar(list_container, orient=tk.VERTICAL,
                                  command=self.file_listbox.yview)
        self.file_listbox.configure(yscrollcommand=scrollbar.set)
        self.file_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.inbox_files = []
        self._refresh_file_list()

        # Selection controls
        sel_row = ttk.Frame(files_frame)
        sel_row.pack(fill=tk.X, pady=(8, 0))
        ttk.Button(sel_row, text="Select all",
                   command=lambda: self.file_listbox.select_set(0, tk.END)).pack(side=tk.LEFT)
        ttk.Button(sel_row, text="Select none",
                   command=lambda: self.file_listbox.select_clear(0, tk.END)).pack(side=tk.LEFT, padx=6)
        ttk.Button(sel_row, text="🔄 Refresh",
                   command=self._refresh_file_list).pack(side=tk.LEFT, padx=6)
        ttk.Button(sel_row, text="📁 Open inbox",
                   command=lambda: open_in_finder(INBOX_DIR)).pack(side=tk.LEFT, padx=6)

        # Options panel (mode-specific)
        self.options = self._build_options(self.container, mode_key)

        # Footer
        footer = ttk.Frame(self.container)
        footer.pack(fill=tk.X, pady=(12, 0))
        self.start_btn = ttk.Button(footer, text="Start processing →",
                                     command=self._start_processing)
        self.start_btn.pack(side=tk.RIGHT)
        ttk.Label(footer, text=(
            f"Accepted: {', '.join(sorted(m['input_exts']))}"
        ), style="Sub.TLabel").pack(side=tk.LEFT)

    def _refresh_file_list(self):
        self.file_listbox.delete(0, tk.END)
        self.inbox_files = scan_inbox(MODES[self.mode]["input_exts"])
        if not self.inbox_files:
            self.file_listbox.insert(tk.END, "  (no compatible files in inbox/)")
            self.file_listbox.itemconfigure(0, foreground="#999999")
            self.file_listbox.config(state=tk.DISABLED)
        else:
            self.file_listbox.config(state=tk.NORMAL)
            for _, name, size in self.inbox_files:
                self.file_listbox.insert(tk.END, f"  {name}    ({size})")
            # Auto-select all by default
            self.file_listbox.select_set(0, tk.END)

    def _build_options(self, parent, mode_key):
        """Build mode-specific options panel. Returns a dict of getter callables."""
        opts_frame = ttk.LabelFrame(parent, text="Options", padding=10)
        opts_frame.pack(fill=tk.X, pady=(12, 0))

        getters = {}

        if mode_key == "tts":
            # Voice
            row = ttk.Frame(opts_frame); row.pack(fill=tk.X, pady=4)
            ttk.Label(row, text="Voice:", width=12, anchor=tk.W).pack(side=tk.LEFT)
            voice_var = tk.StringVar(value=DEFAULT_VOICE)
            flat_voices = []
            for cat, vs in VOICES.items():
                flat_voices.extend(vs)
            voice_cb = ttk.Combobox(row, textvariable=voice_var,
                                    values=flat_voices, state="readonly", width=20)
            voice_cb.pack(side=tk.LEFT)
            getters["voice"] = lambda: voice_var.get()

            # Speed
            row = ttk.Frame(opts_frame); row.pack(fill=tk.X, pady=4)
            ttk.Label(row, text="Speed:", width=12, anchor=tk.W).pack(side=tk.LEFT)
            speed_var = tk.DoubleVar(value=1.0)
            speed_label = ttk.Label(row, text="1.0x", width=6)
            def upd_speed(_):
                speed_label.config(text=f"{speed_var.get():.2f}x")
            scale = ttk.Scale(row, from_=0.5, to=2.0, orient=tk.HORIZONTAL,
                              variable=speed_var, command=upd_speed, length=200)
            scale.pack(side=tk.LEFT, padx=4)
            speed_label.pack(side=tk.LEFT)
            getters["speed"] = lambda: round(speed_var.get(), 2)

        elif mode_key == "stt":
            row = ttk.Frame(opts_frame); row.pack(fill=tk.X, pady=4)
            ttk.Label(row, text="Model:", width=12, anchor=tk.W).pack(side=tk.LEFT)
            model_var = tk.StringVar(value="small")
            ttk.Combobox(row, textvariable=model_var, values=STT_MODELS,
                         state="readonly", width=14).pack(side=tk.LEFT)
            ttk.Label(row, text="  (smaller = faster, larger = better quality)",
                      style="Sub.TLabel").pack(side=tk.LEFT)
            getters["model"] = lambda: model_var.get()

            row = ttk.Frame(opts_frame); row.pack(fill=tk.X, pady=4)
            ttk.Label(row, text="Output format:", width=12, anchor=tk.W).pack(side=tk.LEFT)
            fmt_var = tk.StringVar(value="text")
            for fmt in OUTPUT_FORMATS:
                ttk.Radiobutton(row, text=fmt, value=fmt,
                                variable=fmt_var).pack(side=tk.LEFT, padx=4)
            getters["format"] = lambda: fmt_var.get()

        elif mode_key == "diarize":
            row = ttk.Frame(opts_frame); row.pack(fill=tk.X, pady=4)
            ttk.Label(row, text="Model:", width=12, anchor=tk.W).pack(side=tk.LEFT)
            model_var = tk.StringVar(value="medium")
            ttk.Combobox(row, textvariable=model_var, values=DIARIZE_MODELS,
                         state="readonly", width=14).pack(side=tk.LEFT)
            ttk.Label(row, text="  (medium recommended for long audio)",
                      style="Sub.TLabel").pack(side=tk.LEFT)
            getters["model"] = lambda: model_var.get()

            row = ttk.Frame(opts_frame); row.pack(fill=tk.X, pady=4)
            ttk.Label(row, text="Speakers:", width=12, anchor=tk.W).pack(side=tk.LEFT)
            spk_mode_var = tk.StringVar(value="auto")
            spk_n_var = tk.IntVar(value=2)
            ttk.Radiobutton(row, text="Auto-detect", value="auto",
                            variable=spk_mode_var).pack(side=tk.LEFT)
            ttk.Radiobutton(row, text="Fixed:", value="fixed",
                            variable=spk_mode_var).pack(side=tk.LEFT, padx=(12, 2))
            ttk.Spinbox(row, from_=1, to=20, textvariable=spk_n_var,
                        width=4).pack(side=tk.LEFT)
            ttk.Label(row, text=" (huge speed/accuracy win when known)",
                      style="Sub.TLabel").pack(side=tk.LEFT)
            getters["fixed_speakers"] = lambda: (
                spk_n_var.get() if spk_mode_var.get() == "fixed" else None
            )

            row = ttk.Frame(opts_frame); row.pack(fill=tk.X, pady=4)
            ttk.Label(row, text="Output format:", width=12, anchor=tk.W).pack(side=tk.LEFT)
            fmt_var = tk.StringVar(value="text")
            for fmt in OUTPUT_FORMATS:
                ttk.Radiobutton(row, text=fmt, value=fmt,
                                variable=fmt_var).pack(side=tk.LEFT, padx=4)
            getters["format"] = lambda: fmt_var.get()

        return getters

    # ── Screen 3: Processing ────────────────────────────────────────────────

    def _start_processing(self):
        if not self.inbox_files:
            messagebox.showinfo("No files", "Drop some files in inbox/ first.")
            return
        sel = self.file_listbox.curselection()
        if not sel:
            messagebox.showinfo("No selection", "Select at least one file to process.")
            return

        self.selected_files = [self.inbox_files[i][0] for i in sel]
        settings = {k: g() for k, g in self.options.items()}

        self.cancel_event = threading.Event()
        self.msg_q = queue.Queue()
        self.start_time = time.time()
        self.file_durations = []
        self.results = []

        self.show_processing_screen()

        self.worker = Worker(self.mode, self.selected_files, settings,
                             self.msg_q, self.cancel_event)
        self.worker.start()

    def show_processing_screen(self):
        self._clear()
        m = MODES[self.mode]

        ttk.Label(self.container, text=f"{m['emoji']}  {m['label']}",
                  style="Header.TLabel").pack(anchor=tk.W)
        ttk.Label(self.container, text=f"Processing {len(self.selected_files)} file(s)...",
                  style="Sub.TLabel").pack(anchor=tk.W, pady=(0, 12))

        self.current_label = ttk.Label(self.container, text="Starting...",
                                       font=("Helvetica", 13, "bold"))
        self.current_label.pack(anchor=tk.W, pady=(0, 4))

        # Overall progress
        overall = ttk.Frame(self.container); overall.pack(fill=tk.X, pady=4)
        ttk.Label(overall, text="Overall:", width=10).pack(side=tk.LEFT)
        self.overall_bar = ttk.Progressbar(overall, mode="determinate",
                                            length=400, maximum=len(self.selected_files))
        self.overall_bar.pack(side=tk.LEFT, padx=4)
        self.overall_status = ttk.Label(overall, text=f"0 / {len(self.selected_files)}")
        self.overall_status.pack(side=tk.LEFT, padx=8)

        # Current-file progress
        cur = ttk.Frame(self.container); cur.pack(fill=tk.X, pady=4)
        ttk.Label(cur, text="This file:", width=10).pack(side=tk.LEFT)
        self.file_bar = ttk.Progressbar(cur, mode="determinate",
                                         length=400, maximum=100)
        self.file_bar.pack(side=tk.LEFT, padx=4)
        self.file_status = ttk.Label(cur, text="—")
        self.file_status.pack(side=tk.LEFT, padx=8)

        # ETA + elapsed
        self.timing_label = ttk.Label(self.container, text="Elapsed: 0s   ETA: —",
                                      style="Sub.TLabel")
        self.timing_label.pack(anchor=tk.W, pady=(8, 8))

        # Log
        ttk.Label(self.container, text="Log:", style="Sub.TLabel").pack(anchor=tk.W)
        self.log = scrolledtext.ScrolledText(self.container, height=12,
                                              font=("Menlo", 10), wrap=tk.WORD,
                                              state=tk.DISABLED)
        self.log.pack(fill=tk.BOTH, expand=True, pady=(2, 8))

        # Controls
        controls = ttk.Frame(self.container); controls.pack(fill=tk.X)
        self.cancel_btn = ttk.Button(controls, text="Cancel",
                                     command=self._on_cancel)
        self.cancel_btn.pack(side=tk.RIGHT)

        # Periodic timer for elapsed/ETA refresh
        self._timer_after = self.root.after(500, self._tick_timer)

    def _tick_timer(self):
        if self.start_time is None:
            return
        elapsed = time.time() - self.start_time
        # ETA: based on average completed-file time
        done = len(self.file_durations)
        total = len(self.selected_files)
        if done > 0 and done < total:
            avg = sum(self.file_durations) / done
            eta_seconds = avg * (total - done)
            eta_str = fmt_time(eta_seconds)
        elif done == total:
            eta_str = "done"
        else:
            eta_str = "estimating..."
        self.timing_label.config(text=f"Elapsed: {fmt_time(elapsed)}    ETA: {eta_str}")
        # If we're in a named stage with no per-line progress (diarize), keep
        # the per-file status ticking so the user can see the stage isn't
        # wedged — silent stages would otherwise look frozen for minutes.
        if self.current_stage is not None:
            label, started_at = self.current_stage
            in_stage = time.time() - started_at
            # Read current pct off the bar rather than re-stashing it.
            try:
                pct = int(self.file_bar.cget("value"))
            except Exception:
                pct = 0
            self.file_status.config(
                text=f"{pct}%  {label}  ({fmt_time(in_stage)})")
        # Reschedule
        self._timer_after = self.root.after(500, self._tick_timer)

    def _append_log(self, line):
        self.log.config(state=tk.NORMAL)
        self.log.insert(tk.END, line + "\n")
        self.log.see(tk.END)
        # Cap log at ~2000 lines to avoid runaway memory
        if int(self.log.index("end-1c").split(".")[0]) > 2000:
            self.log.delete("1.0", "500.0")
        self.log.config(state=tk.DISABLED)

    def _on_cancel(self):
        if not messagebox.askyesno("Cancel?", "Stop processing? The current file will be aborted."):
            return
        self.cancel_event.set()
        self.cancel_btn.config(state=tk.DISABLED, text="Cancelling...")

    def _poll_queue(self):
        try:
            while True:
                msg = self.msg_q.get_nowait()
                self._handle_message(msg)
        except queue.Empty:
            pass
        self.root.after(100, self._poll_queue)

    def _handle_message(self, msg):
        kind = msg[0]
        if kind == "file_start":
            _, idx, total, name = msg
            self.current_label.config(text=f"📄  {name}")
            self.overall_status.config(text=f"{idx} / {total}")
            self.file_bar.config(value=0)
            self.file_status.config(text="starting...")
            self.current_stage = None
            self._append_log(f"\n── [{idx + 1}/{total}] {name} ──")
        elif kind == "log":
            self._append_log(msg[1])
        elif kind == "progress":
            _, pct, eta = msg
            self.file_bar.config(value=pct)
            self.file_status.config(text=f"{pct}%  ~{eta} left")
            self.current_stage = None
        elif kind == "stage":
            _, pct, label = msg
            self.file_bar.config(value=pct)
            self.current_stage = (label, time.time())
            self.file_status.config(text=f"{pct}%  {label}")
        elif kind == "file_done":
            _, idx, total, success, elapsed = msg
            self.overall_bar.config(value=idx + 1)
            self.overall_status.config(text=f"{idx + 1} / {total}")
            self.file_durations.append(elapsed)
            mark = "✅" if success else "❌"
            self._append_log(f"{mark} done in {fmt_time(elapsed)}")
        elif kind == "cancelled":
            self._append_log("\n⛔ Cancelled by user.")
            self._stop_timer()
            self.show_done_screen(cancelled=True)
        elif kind == "all_done":
            _, results = msg
            self.results = results
            self._stop_timer()
            self.show_done_screen()

    def _stop_timer(self):
        if hasattr(self, "_timer_after") and self._timer_after:
            try:
                self.root.after_cancel(self._timer_after)
            except Exception:
                pass
            self._timer_after = None

    # ── Screen 4: Done ──────────────────────────────────────────────────────

    def show_done_screen(self, cancelled=False):
        self._clear()

        if cancelled:
            ttk.Label(self.container, text="⛔ Cancelled",
                      style="Header.TLabel").pack(anchor=tk.W)
        else:
            ok_count = sum(1 for r in self.results if r["ok"])
            fail_count = len(self.results) - ok_count
            ttk.Label(self.container, text=f"✅ Done — {ok_count} succeeded"
                      + (f", {fail_count} failed" if fail_count else ""),
                      style="Header.TLabel").pack(anchor=tk.W)
            elapsed = time.time() - self.start_time
            ttk.Label(self.container, text=f"Total time: {fmt_time(elapsed)}",
                      style="Sub.TLabel").pack(anchor=tk.W, pady=(0, 12))

        # Per-file summary (if we have results)
        if self.results:
            summary = ttk.LabelFrame(self.container, text="Results", padding=8)
            summary.pack(fill=tk.BOTH, expand=True, pady=(8, 12))

            sframe = ttk.Frame(summary); sframe.pack(fill=tk.BOTH, expand=True)
            sb = ttk.Scrollbar(sframe, orient=tk.VERTICAL)
            sb.pack(side=tk.RIGHT, fill=tk.Y)
            txt = tk.Text(sframe, height=10, wrap=tk.WORD, font=("Menlo", 10),
                          yscrollcommand=sb.set)
            sb.config(command=txt.yview)
            txt.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            for r in self.results:
                mark = "✅" if r["ok"] else "❌"
                line = f"{mark}  {r['input']}  ({fmt_time(r['elapsed'])})\n"
                if r["ok"]:
                    line += f"     → {os.path.relpath(r['output'], SCRIPT_DIR)}\n"
                else:
                    last = (r.get("error") or "").splitlines()[-3:]
                    for l in last:
                        line += f"     {l}\n"
                txt.insert(tk.END, line)
            txt.config(state=tk.DISABLED)

        # Buttons
        btns = ttk.Frame(self.container); btns.pack(fill=tk.X, pady=(8, 0))
        ttk.Button(btns, text="📂 Open output folder",
                   command=lambda: open_in_finder(OUTPUT_DIR)).pack(side=tk.LEFT)
        ttk.Button(btns, text="🔄 Process more",
                   command=self.show_mode_screen).pack(side=tk.LEFT, padx=8)
        ttk.Button(btns, text="Quit",
                   command=self.root.destroy).pack(side=tk.RIGHT)


def main():
    root = tk.Tk()
    VoxBoxGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
