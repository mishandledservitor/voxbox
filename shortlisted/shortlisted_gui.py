#!/usr/bin/env python3
"""
Shortlisted Call Transcriber — Tk GUI front-end for shortlisted_stt.py.

Mirrors VoxBox's flow (mode → files → options → progress → done) but exposes
every ElevenLabs Scribe parameter relevant to client-call transcription.
"""

import os
import queue
import shutil
import signal
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext, filedialog

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
INBOX_DIR = os.path.join(SCRIPT_DIR, "inbox")
OUTPUT_DIR = os.path.join(SCRIPT_DIR, "output")
PROCESSED_DIR = os.path.join(SCRIPT_DIR, "processed")

STT_LAUNCHER = os.path.join(SCRIPT_DIR, "shortlisted-stt")

AUDIO_EXTS = {"mp3", "mp4", "wav", "m4a", "ogg", "flac",
              "aac", "webm", "mkv", "mov", "avi", "opus"}

OUTPUT_FORMATS = ["text", "srt", "vtt", "json"]
FORMAT_EXT = {"text": "txt", "srt": "srt", "vtt": "vtt", "json": "json"}

MODELS = ["scribe_v2", "scribe_v1"]
TIMESTAMP_GRANULARITY = ["word", "character", "none"]

# Common ISO-639-1 / 639-3 codes — Scribe accepts both. Empty = auto.
LANGUAGES = [
    ("", "auto-detect"),
    ("eng", "English"),
    ("afr", "Afrikaans"),
    ("zul", "Zulu"),
    ("xho", "Xhosa"),
    ("fra", "French"),
    ("spa", "Spanish"),
    ("deu", "German"),
    ("por", "Portuguese"),
    ("ita", "Italian"),
    ("nld", "Dutch"),
    ("jpn", "Japanese"),
    ("zho", "Chinese"),
    ("ara", "Arabic"),
    ("hin", "Hindi"),
]

STAGES = [
    ("stage: uploading",   10, "uploading audio..."),
    ("stage: queued",      20, "queued..."),
    ("stage: processing",  35, "transcribing (Scribe)..."),
    ("stage: finalizing",  92, "formatting transcript..."),
    ("stage: done",       100, "done"),
]


def parse_stage(line):
    for marker, pct, label in STAGES:
        if marker in line:
            return pct, label
    return None


def ensure_dirs():
    for d in (INBOX_DIR, OUTPUT_DIR, PROCESSED_DIR):
        os.makedirs(d, exist_ok=True)


def open_in_finder(path):
    if os.path.exists(path):
        subprocess.Popen(["open", path])


def scan_inbox():
    if not os.path.isdir(INBOX_DIR):
        return []
    items = []
    for name in sorted(os.listdir(INBOX_DIR)):
        if name.startswith("."):
            continue
        ext = os.path.splitext(name)[1].lower().lstrip(".")
        if ext not in AUDIO_EXTS:
            continue
        full = os.path.join(INBOX_DIR, name)
        size_mb = os.path.getsize(full) / (1024 * 1024)
        items.append((full, name, f"{size_mb:.1f} MB"))
    return items


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
    if not os.path.exists(path):
        return path
    base, ext = os.path.splitext(path)
    i = 1
    while os.path.exists(f"{base}_{i}{ext}"):
        i += 1
    return f"{base}_{i}{ext}"


# ── Worker ─────────────────────────────────────────────────────────────────

class Worker(threading.Thread):
    def __init__(self, files, settings, msg_queue, cancel_event):
        super().__init__(daemon=True)
        self.files = files
        self.settings = settings
        self.q = msg_queue
        self.cancel = cancel_event
        self.proc = None

    def build_command(self, input_path, output_path):
        s = self.settings
        cmd = [STT_LAUNCHER,
               "-f", s["format"],
               "-o", output_path,
               "--model", s["model"],
               "--timestamps", s["timestamps"],
               "--no-print"]
        if s.get("language"):
            cmd += ["-l", s["language"]]
        if s.get("speakers"):
            cmd += ["--speakers"]
            if s.get("num_speakers"):
                cmd += ["--num-speakers", str(s["num_speakers"])]
            if s.get("diarization_threshold") is not None:
                cmd += ["--diarization-threshold", f"{s['diarization_threshold']:.2f}"]
        if not s.get("tag_audio_events", True):
            cmd += ["--no-audio-events"]
        if s.get("no_verbatim"):
            cmd += ["--no-verbatim"]
        if s.get("speakers") and s.get("detect_speaker_roles"):
            cmd += ["--detect-speaker-roles"]
        if s.get("keyterms"):
            cmd += ["--keyterms", s["keyterms"]]
        if s.get("temperature") is not None:
            cmd += ["--temperature", f"{s['temperature']:.2f}"]
        if s.get("seed") is not None:
            cmd += ["--seed", str(s["seed"])]
        if s.get("labels"):
            cmd += ["--labels", s["labels"]]
        if s.get("inline_timestamps"):
            cmd += ["--inline-timestamps"]
        cmd += [input_path]
        return cmd

    def run(self):
        total = len(self.files)
        results = []
        ext = FORMAT_EXT.get(self.settings.get("format", "text"), "txt")

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
            env = os.environ.copy()
            env["PYTHONUNBUFFERED"] = "1"

            try:
                self.proc = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, bufsize=1, env=env,
                    preexec_fn=os.setsid if os.name != "nt" else None,
                )
                for raw_line in self.proc.stdout:
                    if self.cancel.is_set():
                        self._terminate_proc()
                        self.q.put(("cancelled",))
                        return
                    line = raw_line.rstrip("\r\n")
                    if not line.strip():
                        continue
                    stage = parse_stage(line)
                    if stage:
                        pct, label = stage
                        self.q.put(("stage", pct, label))
                    self.q.put(("log", line))
                    err_tail.append(line)
                    if len(err_tail) > 30:
                        err_tail.pop(0)
                rc = self.proc.wait()
                success = (rc == 0 and os.path.isfile(output_path))
            except Exception as e:
                self.q.put(("log", f"⚠  {e}"))
                err_tail.append(str(e))

            elapsed = time.time() - t0
            if success:
                # Move input into processed/ — but only if it lived in inbox/.
                if os.path.dirname(os.path.abspath(input_path)) == INBOX_DIR:
                    dest = unique_path(os.path.join(PROCESSED_DIR, os.path.basename(input_path)))
                    try:
                        shutil.move(input_path, dest)
                    except Exception as e:
                        self.q.put(("log", f"⚠  Could not move to processed/: {e}"))
                results.append({"input": os.path.basename(input_path),
                                "output": output_path, "elapsed": elapsed, "ok": True})
            else:
                results.append({"input": os.path.basename(input_path),
                                "output": None, "elapsed": elapsed, "ok": False,
                                "error": "\n".join(err_tail[-10:])})
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

class ShortlistedGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Shortlisted — Client Call Transcriber")
        self.root.minsize(820, 700)

        self.selected_files = []
        self.extra_files = []  # added via "Add file..."
        self.worker = None
        self.cancel_event = threading.Event()
        self.msg_q = queue.Queue()
        self.start_time = None
        self.file_durations = []
        self.results = []
        self.current_stage = None

        style = ttk.Style()
        try:
            style.theme_use("aqua")
        except tk.TclError:
            pass
        style.configure("Header.TLabel", font=("Helvetica", 18, "bold"))
        style.configure("Sub.TLabel", font=("Helvetica", 11), foreground="#666666")
        style.configure("Section.TLabelframe.Label", font=("Helvetica", 12, "bold"))

        ensure_dirs()

        self.container = ttk.Frame(root, padding=18)
        self.container.pack(fill=tk.BOTH, expand=True)

        self.show_main_screen()
        self.root.after(100, self._poll_queue)

    def _clear(self):
        for c in self.container.winfo_children():
            c.destroy()

    # ── Main / setup screen ────────────────────────────────────────────────

    def show_main_screen(self):
        self._clear()

        # Header
        head = ttk.Frame(self.container)
        head.pack(fill=tk.X, pady=(0, 12))
        ttk.Label(head, text="🎙  Shortlisted Call Transcriber",
                  style="Header.TLabel").pack(side=tk.LEFT)
        ttk.Label(head, text="  ElevenLabs Scribe · full options",
                  style="Sub.TLabel").pack(side=tk.LEFT, padx=8, pady=(6, 0))

        # Two-column body
        body = ttk.Frame(self.container)
        body.pack(fill=tk.BOTH, expand=True)
        body.columnconfigure(0, weight=3, uniform="cols")
        body.columnconfigure(1, weight=2, uniform="cols")

        # LEFT — files
        files_frame = ttk.LabelFrame(body, text="Files", padding=10,
                                     style="Section.TLabelframe")
        files_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 8))

        list_container = ttk.Frame(files_frame)
        list_container.pack(fill=tk.BOTH, expand=True)
        self.file_listbox = tk.Listbox(list_container, selectmode=tk.MULTIPLE,
                                       activestyle="none", font=("Helvetica", 12),
                                       height=14)
        sb = ttk.Scrollbar(list_container, orient=tk.VERTICAL,
                          command=self.file_listbox.yview)
        self.file_listbox.configure(yscrollcommand=sb.set)
        self.file_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self._refresh_file_list()

        controls = ttk.Frame(files_frame); controls.pack(fill=tk.X, pady=(8, 0))
        ttk.Button(controls, text="Select all",
                   command=lambda: self.file_listbox.select_set(0, tk.END)).pack(side=tk.LEFT)
        ttk.Button(controls, text="Select none",
                   command=lambda: self.file_listbox.select_clear(0, tk.END)).pack(side=tk.LEFT, padx=4)
        ttk.Button(controls, text="🔄 Refresh inbox",
                   command=self._refresh_file_list).pack(side=tk.LEFT, padx=4)
        ttk.Button(controls, text="➕ Add file...",
                   command=self._add_file).pack(side=tk.LEFT, padx=4)
        ttk.Button(controls, text="📁 Open inbox",
                   command=lambda: open_in_finder(INBOX_DIR)).pack(side=tk.LEFT, padx=4)

        # RIGHT — options
        opts = ttk.LabelFrame(body, text="ElevenLabs Scribe options", padding=10,
                              style="Section.TLabelframe")
        opts.grid(row=0, column=1, sticky="nsew")
        self._build_options(opts)

        # Footer
        footer = ttk.Frame(self.container); footer.pack(fill=tk.X, pady=(14, 0))
        self.start_btn = ttk.Button(footer, text="Transcribe →",
                                     command=self._start_processing)
        self.start_btn.pack(side=tk.RIGHT)
        ttk.Button(footer, text="📂 Open output folder",
                   command=lambda: open_in_finder(OUTPUT_DIR)).pack(side=tk.LEFT)
        ttk.Label(footer, text="  Drop recordings in inbox/, or add files directly.",
                  style="Sub.TLabel").pack(side=tk.LEFT, padx=8)

    def _refresh_file_list(self):
        self.file_listbox.delete(0, tk.END)
        self.inbox_files = scan_inbox() + [(p, os.path.basename(p), "added") for p in self.extra_files]
        if not self.inbox_files:
            self.file_listbox.insert(tk.END, "  (no audio files — drop some in inbox/ or click ➕ Add file)")
            self.file_listbox.itemconfigure(0, foreground="#999999")
        else:
            for _, name, tag in self.inbox_files:
                self.file_listbox.insert(tk.END, f"  {name}    ({tag})")
            self.file_listbox.select_set(0, tk.END)

    def _add_file(self):
        paths = filedialog.askopenfilenames(
            title="Select audio file(s)",
            filetypes=[("Audio/video", " ".join(f"*.{e}" for e in sorted(AUDIO_EXTS))),
                       ("All files", "*.*")])
        for p in paths:
            if p not in self.extra_files:
                self.extra_files.append(p)
        self._refresh_file_list()

    def _build_options(self, parent):
        self.opts = {}

        # Model
        row = ttk.Frame(parent); row.pack(fill=tk.X, pady=4)
        ttk.Label(row, text="Model:", width=18, anchor=tk.W).pack(side=tk.LEFT)
        self.opts["model"] = tk.StringVar(value="scribe_v2")
        ttk.Combobox(row, textvariable=self.opts["model"], values=MODELS,
                     state="readonly", width=24).pack(side=tk.LEFT)
        ttk.Label(row, text="  v2 = best quality + extra features",
                  style="Sub.TLabel").pack(side=tk.LEFT)

        # Language
        row = ttk.Frame(parent); row.pack(fill=tk.X, pady=4)
        ttk.Label(row, text="Language:", width=18, anchor=tk.W).pack(side=tk.LEFT)
        lang_display = [f"{label}" + (f"  ({code})" if code else "")
                        for code, label in LANGUAGES]
        self._lang_display = lang_display
        self._lang_codes = [code for code, _ in LANGUAGES]
        self.opts["language_idx"] = tk.IntVar(value=0)
        lang_cb = ttk.Combobox(row, values=lang_display, state="readonly", width=24)
        lang_cb.current(0)
        lang_cb.pack(side=tk.LEFT)
        self._lang_cb = lang_cb

        # Diarize
        row = ttk.Frame(parent); row.pack(fill=tk.X, pady=(10, 4))
        self.opts["speakers"] = tk.BooleanVar(value=True)
        ttk.Checkbutton(row, text="Speaker diarization (label who said what)",
                        variable=self.opts["speakers"],
                        command=self._toggle_diarize_widgets).pack(side=tk.LEFT)

        # Num speakers
        row = ttk.Frame(parent); row.pack(fill=tk.X, pady=2)
        ttk.Label(row, text="Known speaker count:", width=18, anchor=tk.W).pack(side=tk.LEFT)
        self.opts["num_speakers_mode"] = tk.StringVar(value="fixed")
        ttk.Radiobutton(row, text="Auto", value="auto",
                        variable=self.opts["num_speakers_mode"]).pack(side=tk.LEFT)
        ttk.Radiobutton(row, text="Fixed:", value="fixed",
                        variable=self.opts["num_speakers_mode"]).pack(side=tk.LEFT, padx=(8, 2))
        self.opts["num_speakers"] = tk.IntVar(value=2)
        self._num_speakers_spin = ttk.Spinbox(row, from_=1, to=32, width=4,
                                               textvariable=self.opts["num_speakers"])
        self._num_speakers_spin.pack(side=tk.LEFT)
        ttk.Label(row, text="(2 = Simon + client)", style="Sub.TLabel").pack(side=tk.LEFT, padx=4)

        # Diarization threshold
        row = ttk.Frame(parent); row.pack(fill=tk.X, pady=2)
        ttk.Label(row, text="Diarization sensitivity:", width=18, anchor=tk.W).pack(side=tk.LEFT)
        self.opts["diarization_threshold"] = tk.DoubleVar(value=0.22)
        thr_lbl = ttk.Label(row, text="0.22", width=5)
        def upd_thr(_):
            thr_lbl.config(text=f"{self.opts['diarization_threshold'].get():.2f}")
        ttk.Scale(row, from_=0.10, to=0.40, orient=tk.HORIZONTAL, length=160,
                  variable=self.opts["diarization_threshold"],
                  command=upd_thr).pack(side=tk.LEFT, padx=4)
        thr_lbl.pack(side=tk.LEFT)
        ttk.Label(row, text=" loose ← → strict", style="Sub.TLabel").pack(side=tk.LEFT, padx=4)

        # Speaker labels
        row = ttk.Frame(parent); row.pack(fill=tk.X, pady=2)
        ttk.Label(row, text="Speaker labels:", width=18, anchor=tk.W).pack(side=tk.LEFT)
        self.opts["labels"] = tk.StringVar(value="0=Simon,1=Client")
        ttk.Entry(row, textvariable=self.opts["labels"], width=28).pack(side=tk.LEFT)
        ttk.Label(row, text=" e.g. 0=Simon,1=Client",
                  style="Sub.TLabel").pack(side=tk.LEFT, padx=4)

        # detect_speaker_roles
        row = ttk.Frame(parent); row.pack(fill=tk.X, pady=2)
        self.opts["detect_speaker_roles"] = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            row,
            text="Detect speaker roles (agent / customer)  +10% cost · needs diarize",
            variable=self.opts["detect_speaker_roles"]).pack(side=tk.LEFT)

        # Audio events
        row = ttk.Frame(parent); row.pack(fill=tk.X, pady=(10, 4))
        self.opts["tag_audio_events"] = tk.BooleanVar(value=False)
        ttk.Checkbutton(row, text="Tag audio events ([laughter], [applause], etc.)",
                        variable=self.opts["tag_audio_events"]).pack(side=tk.LEFT)

        # no_verbatim
        row = ttk.Frame(parent); row.pack(fill=tk.X, pady=2)
        self.opts["no_verbatim"] = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            row,
            text="Clean transcript (drop ums, false starts) — scribe_v2 only",
            variable=self.opts["no_verbatim"]).pack(side=tk.LEFT)

        # Keyterms
        row = ttk.Frame(parent); row.pack(fill=tk.X, pady=4)
        ttk.Label(row, text="Keyterms:", width=18, anchor=tk.W).pack(side=tk.LEFT)
        self.opts["keyterms"] = tk.StringVar(value="")
        ttk.Entry(row, textvariable=self.opts["keyterms"], width=28).pack(side=tk.LEFT)
        ttk.Label(row, text=" comma list, biases recognition (+20%)",
                  style="Sub.TLabel").pack(side=tk.LEFT)

        # Temperature
        row = ttk.Frame(parent); row.pack(fill=tk.X, pady=4)
        ttk.Label(row, text="Temperature:", width=18, anchor=tk.W).pack(side=tk.LEFT)
        self.opts["temperature_enabled"] = tk.BooleanVar(value=False)
        ttk.Checkbutton(row, variable=self.opts["temperature_enabled"]).pack(side=tk.LEFT)
        self.opts["temperature"] = tk.DoubleVar(value=0.0)
        ttk.Spinbox(row, from_=0.0, to=2.0, increment=0.1,
                    textvariable=self.opts["temperature"], width=6).pack(side=tk.LEFT, padx=4)
        ttk.Label(row, text=" 0 = deterministic, 2 = chaotic",
                  style="Sub.TLabel").pack(side=tk.LEFT)

        # Seed
        row = ttk.Frame(parent); row.pack(fill=tk.X, pady=4)
        ttk.Label(row, text="Seed:", width=18, anchor=tk.W).pack(side=tk.LEFT)
        self.opts["seed_enabled"] = tk.BooleanVar(value=False)
        ttk.Checkbutton(row, variable=self.opts["seed_enabled"]).pack(side=tk.LEFT)
        self.opts["seed"] = tk.IntVar(value=42)
        ttk.Spinbox(row, from_=0, to=2147483647,
                    textvariable=self.opts["seed"], width=12).pack(side=tk.LEFT, padx=4)
        ttk.Label(row, text=" for reproducibility",
                  style="Sub.TLabel").pack(side=tk.LEFT)

        # Timestamps granularity
        row = ttk.Frame(parent); row.pack(fill=tk.X, pady=4)
        ttk.Label(row, text="Timestamp granularity:", width=18, anchor=tk.W).pack(side=tk.LEFT)
        self.opts["timestamps"] = tk.StringVar(value="word")
        for v in TIMESTAMP_GRANULARITY:
            ttk.Radiobutton(row, text=v, value=v,
                            variable=self.opts["timestamps"]).pack(side=tk.LEFT, padx=2)

        # Output format
        row = ttk.Frame(parent); row.pack(fill=tk.X, pady=4)
        ttk.Label(row, text="Output format:", width=18, anchor=tk.W).pack(side=tk.LEFT)
        self.opts["format"] = tk.StringVar(value="text")
        for fmt in OUTPUT_FORMATS:
            ttk.Radiobutton(row, text=fmt, value=fmt,
                            variable=self.opts["format"]).pack(side=tk.LEFT, padx=2)

        # Inline timestamps in text mode
        row = ttk.Frame(parent); row.pack(fill=tk.X, pady=4)
        self.opts["inline_timestamps"] = tk.BooleanVar(value=True)
        ttk.Checkbutton(row, text="Prefix text lines with [hh:mm:ss]",
                        variable=self.opts["inline_timestamps"]).pack(side=tk.LEFT)

        self._toggle_diarize_widgets()

    def _toggle_diarize_widgets(self):
        # Visual cue only — the worker checks the flag itself.
        pass

    def _collect_settings(self):
        s = {}
        s["model"] = self.opts["model"].get()
        s["language"] = self._lang_codes[self._lang_cb.current()] or None
        s["speakers"] = self.opts["speakers"].get()
        s["num_speakers"] = (self.opts["num_speakers"].get()
                             if self.opts["num_speakers_mode"].get() == "fixed" else None)
        s["diarization_threshold"] = round(self.opts["diarization_threshold"].get(), 2)
        s["tag_audio_events"] = self.opts["tag_audio_events"].get()
        s["timestamps"] = self.opts["timestamps"].get()
        s["format"] = self.opts["format"].get()
        s["labels"] = self.opts["labels"].get().strip() or None
        s["inline_timestamps"] = self.opts["inline_timestamps"].get()
        s["no_verbatim"] = self.opts["no_verbatim"].get() and s["model"] == "scribe_v2"
        s["detect_speaker_roles"] = self.opts["detect_speaker_roles"].get()
        s["keyterms"] = self.opts["keyterms"].get().strip() or None
        s["temperature"] = (round(self.opts["temperature"].get(), 2)
                            if self.opts["temperature_enabled"].get() else None)
        s["seed"] = self.opts["seed"].get() if self.opts["seed_enabled"].get() else None
        return s

    # ── Processing ─────────────────────────────────────────────────────────

    def _start_processing(self):
        if not self.inbox_files:
            messagebox.showinfo("No files", "Drop recordings in inbox/ or click ➕ Add file.")
            return
        sel = self.file_listbox.curselection()
        if not sel:
            messagebox.showinfo("No selection", "Select at least one file.")
            return
        self.selected_files = [self.inbox_files[i][0] for i in sel]
        settings = self._collect_settings()

        if not os.access(STT_LAUNCHER, os.X_OK):
            messagebox.showerror("Missing launcher",
                                 f"Can't find executable: {STT_LAUNCHER}\n"
                                 "Run ./setup.sh first.")
            return

        self.cancel_event = threading.Event()
        self.msg_q = queue.Queue()
        self.start_time = time.time()
        self.file_durations = []
        self.results = []

        self.show_processing_screen()
        self.worker = Worker(self.selected_files, settings, self.msg_q, self.cancel_event)
        self.worker.start()

    def show_processing_screen(self):
        self._clear()
        ttk.Label(self.container, text="🎙  Transcribing",
                  style="Header.TLabel").pack(anchor=tk.W)
        ttk.Label(self.container, text=f"Processing {len(self.selected_files)} file(s)...",
                  style="Sub.TLabel").pack(anchor=tk.W, pady=(0, 12))

        self.current_label = ttk.Label(self.container, text="Starting...",
                                       font=("Helvetica", 13, "bold"))
        self.current_label.pack(anchor=tk.W, pady=(0, 4))

        overall = ttk.Frame(self.container); overall.pack(fill=tk.X, pady=4)
        ttk.Label(overall, text="Overall:", width=10).pack(side=tk.LEFT)
        self.overall_bar = ttk.Progressbar(overall, mode="determinate",
                                            length=500, maximum=len(self.selected_files))
        self.overall_bar.pack(side=tk.LEFT, padx=4)
        self.overall_status = ttk.Label(overall, text=f"0 / {len(self.selected_files)}")
        self.overall_status.pack(side=tk.LEFT, padx=8)

        cur = ttk.Frame(self.container); cur.pack(fill=tk.X, pady=4)
        ttk.Label(cur, text="This file:", width=10).pack(side=tk.LEFT)
        self.file_bar = ttk.Progressbar(cur, mode="determinate",
                                         length=500, maximum=100)
        self.file_bar.pack(side=tk.LEFT, padx=4)
        self.file_status = ttk.Label(cur, text="—")
        self.file_status.pack(side=tk.LEFT, padx=8)

        self.timing_label = ttk.Label(self.container, text="Elapsed: 0s   ETA: —",
                                      style="Sub.TLabel")
        self.timing_label.pack(anchor=tk.W, pady=(8, 8))

        ttk.Label(self.container, text="Log:", style="Sub.TLabel").pack(anchor=tk.W)
        self.log = scrolledtext.ScrolledText(self.container, height=14,
                                              font=("Menlo", 10), wrap=tk.WORD,
                                              state=tk.DISABLED)
        self.log.pack(fill=tk.BOTH, expand=True, pady=(2, 8))

        controls = ttk.Frame(self.container); controls.pack(fill=tk.X)
        self.cancel_btn = ttk.Button(controls, text="Cancel", command=self._on_cancel)
        self.cancel_btn.pack(side=tk.RIGHT)
        self._timer_after = self.root.after(500, self._tick_timer)

    def _tick_timer(self):
        if self.start_time is None:
            return
        elapsed = time.time() - self.start_time
        done = len(self.file_durations)
        total = len(self.selected_files)
        if done > 0 and done < total:
            avg = sum(self.file_durations) / done
            eta = fmt_time(avg * (total - done))
        elif done == total:
            eta = "done"
        else:
            eta = "estimating..."
        self.timing_label.config(text=f"Elapsed: {fmt_time(elapsed)}    ETA: {eta}")
        if self.current_stage is not None:
            label, started_at = self.current_stage
            in_stage = time.time() - started_at
            try:
                pct = int(self.file_bar.cget("value"))
            except Exception:
                pct = 0
            self.file_status.config(text=f"{pct}%  {label}  ({fmt_time(in_stage)})")
        self._timer_after = self.root.after(500, self._tick_timer)

    def _append_log(self, line):
        self.log.config(state=tk.NORMAL)
        self.log.insert(tk.END, line + "\n")
        self.log.see(tk.END)
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

    def show_done_screen(self, cancelled=False):
        self._clear()
        if cancelled:
            ttk.Label(self.container, text="⛔ Cancelled",
                      style="Header.TLabel").pack(anchor=tk.W)
        else:
            ok = sum(1 for r in self.results if r["ok"])
            fail = len(self.results) - ok
            ttk.Label(self.container,
                      text=f"✅ Done — {ok} succeeded" + (f", {fail} failed" if fail else ""),
                      style="Header.TLabel").pack(anchor=tk.W)
            elapsed = time.time() - self.start_time
            ttk.Label(self.container, text=f"Total time: {fmt_time(elapsed)}",
                      style="Sub.TLabel").pack(anchor=tk.W, pady=(0, 12))

        if self.results:
            sf = ttk.LabelFrame(self.container, text="Results", padding=8)
            sf.pack(fill=tk.BOTH, expand=True, pady=(8, 12))
            inner = ttk.Frame(sf); inner.pack(fill=tk.BOTH, expand=True)
            sb = ttk.Scrollbar(inner, orient=tk.VERTICAL); sb.pack(side=tk.RIGHT, fill=tk.Y)
            txt = tk.Text(inner, height=12, wrap=tk.WORD, font=("Menlo", 10),
                          yscrollcommand=sb.set)
            sb.config(command=txt.yview)
            txt.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            for r in self.results:
                mark = "✅" if r["ok"] else "❌"
                line = f"{mark}  {r['input']}  ({fmt_time(r['elapsed'])})\n"
                if r["ok"]:
                    line += f"     → {os.path.relpath(r['output'], SCRIPT_DIR)}\n"
                else:
                    for l in (r.get("error") or "").splitlines()[-3:]:
                        line += f"     {l}\n"
                txt.insert(tk.END, line)
            txt.config(state=tk.DISABLED)

        btns = ttk.Frame(self.container); btns.pack(fill=tk.X, pady=(8, 0))
        ttk.Button(btns, text="📂 Open output folder",
                   command=lambda: open_in_finder(OUTPUT_DIR)).pack(side=tk.LEFT)
        ttk.Button(btns, text="🔄 Transcribe more",
                   command=self.show_main_screen).pack(side=tk.LEFT, padx=8)
        ttk.Button(btns, text="Quit", command=self.root.destroy).pack(side=tk.RIGHT)


def main():
    root = tk.Tk()
    ShortlistedGUI(root)
    root.update_idletasks()
    w = max(900, root.winfo_reqwidth() + 40)
    h = max(720, root.winfo_reqheight() + 40)
    root.geometry(f"{w}x{h}")
    root.mainloop()


if __name__ == "__main__":
    main()
