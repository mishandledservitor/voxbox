#!/usr/bin/env python3
"""
Project Transcriber — Tk GUI front-end for projects_stt.py.

Pick a project (a TTRPG campaign, a client, a podcast, ...); each project
carries its own keyterms and Scribe settings, editable right in the GUI. Drop
audio in the shared inbox/, pick a project, transcribe. Output lands in
output/<project>/.

Mirrors bankzero-ynab's account selector (top bar + Add / Manage) and VoxBox's
processing flow (files → options → progress → done).
"""

import os
import queue
import shutil
import signal
import subprocess
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext, filedialog, simpledialog

import projects_config as cfg

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
INBOX_DIR = str(cfg.INBOX_DIR)
PROCESSED_DIR = str(cfg.PROCESSED_DIR)
STT_LAUNCHER = os.path.join(SCRIPT_DIR, "projects-stt")

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
    def __init__(self, files, settings, output_dir, msg_queue, cancel_event):
        super().__init__(daemon=True)
        self.files = files
        self.settings = settings
        self.output_dir = output_dir
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
        os.makedirs(self.output_dir, exist_ok=True)

        for i, input_path in enumerate(self.files):
            if self.cancel.is_set():
                self.q.put(("cancelled",))
                return
            stem = os.path.splitext(os.path.basename(input_path))[0]
            output_path = unique_path(os.path.join(self.output_dir, f"{stem}.{ext}"))
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
                if os.path.dirname(os.path.abspath(input_path)) == os.path.abspath(INBOX_DIR):
                    dest = unique_path(os.path.join(PROCESSED_DIR, os.path.basename(input_path)))
                    try:
                        os.makedirs(PROCESSED_DIR, exist_ok=True)
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

class ProjectsGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Project Transcriber")
        self.root.minsize(860, 760)
        try:
            root.createcommand("tk::mac::Quit", self._on_quit)
        except tk.TclError:
            pass
        root.protocol("WM_DELETE_WINDOW", self._on_quit)

        self.slug = None
        self.project_slugs = []          # parallel to project combobox values
        self.selected_files = []
        self.extra_files = []            # added via "Add file..."
        self.inbox_files = []
        self.worker = None
        self.cancel_event = threading.Event()
        self.msg_q = queue.Queue()
        self.start_time = None
        self.file_durations = []
        self.results = []
        self.current_stage = None
        self.opts = {}

        style = ttk.Style()
        try:
            style.theme_use("aqua")
        except tk.TclError:
            pass
        style.configure("Header.TLabel", font=("Helvetica", 18, "bold"))
        style.configure("Sub.TLabel", font=("Helvetica", 11), foreground="#666666")
        style.configure("Section.TLabelframe.Label", font=("Helvetica", 12, "bold"))

        cfg.ensure_dirs()

        self.container = ttk.Frame(root, padding=18)
        self.container.pack(fill=tk.BOTH, expand=True)

        self.slug = cfg.last_used_slug()
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
        head.pack(fill=tk.X, pady=(0, 10))
        ttk.Label(head, text="🎙  Project Transcriber",
                  style="Header.TLabel").pack(side=tk.LEFT)
        ttk.Label(head, text="  ElevenLabs Scribe · per-project keyterms",
                  style="Sub.TLabel").pack(side=tk.LEFT, padx=8, pady=(6, 0))

        # Project bar
        pbar = ttk.Frame(self.container)
        pbar.pack(fill=tk.X, pady=(0, 10))
        ttk.Label(pbar, text="Project:").pack(side=tk.LEFT)
        self.project_cb = ttk.Combobox(pbar, state="readonly", width=30)
        self.project_cb.pack(side=tk.LEFT, padx=(6, 6))
        self.project_cb.bind("<<ComboboxSelected>>", self._on_project_change)
        ttk.Button(pbar, text="+ New project…",
                   command=self._new_project).pack(side=tk.LEFT)
        ttk.Button(pbar, text="Manage…",
                   command=self._manage_projects).pack(side=tk.LEFT, padx=(6, 0))

        # Two-column body
        body = ttk.Frame(self.container)
        body.pack(fill=tk.BOTH, expand=True)
        body.columnconfigure(0, weight=3, uniform="cols")
        body.columnconfigure(1, weight=2, uniform="cols")

        # LEFT — files
        files_frame = ttk.LabelFrame(body, text="Files (shared inbox)", padding=10,
                                     style="Section.TLabelframe")
        files_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 8))

        list_container = ttk.Frame(files_frame)
        list_container.pack(fill=tk.BOTH, expand=True)
        self.file_listbox = tk.Listbox(list_container, selectmode=tk.MULTIPLE,
                                       activestyle="none", font=("Helvetica", 12),
                                       height=10)
        sb = ttk.Scrollbar(list_container, orient=tk.VERTICAL,
                           command=self.file_listbox.yview)
        self.file_listbox.configure(yscrollcommand=sb.set)
        self.file_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)

        controls = ttk.Frame(files_frame)
        controls.pack(fill=tk.X, pady=(8, 0))
        ttk.Button(controls, text="Select all",
                   command=lambda: self.file_listbox.select_set(0, tk.END)).pack(side=tk.LEFT)
        ttk.Button(controls, text="Select none",
                   command=lambda: self.file_listbox.select_clear(0, tk.END)).pack(side=tk.LEFT, padx=4)
        ttk.Button(controls, text="🔄 Refresh",
                   command=self._refresh_file_list).pack(side=tk.LEFT, padx=4)
        ttk.Button(controls, text="➕ Add file...",
                   command=self._add_file).pack(side=tk.LEFT, padx=4)
        ttk.Button(controls, text="📁 Open inbox",
                   command=lambda: open_in_finder(INBOX_DIR)).pack(side=tk.LEFT, padx=4)

        # Keyterms — the per-project headline field.
        kt_frame = ttk.LabelFrame(files_frame, text="Keyterms (one per line — bias recognition)",
                                  padding=8, style="Section.TLabelframe")
        kt_frame.pack(fill=tk.BOTH, expand=True, pady=(10, 0))
        self.keyterms_text = scrolledtext.ScrolledText(kt_frame, height=8,
                                                       font=("Menlo", 11), wrap=tk.WORD)
        self.keyterms_text.pack(fill=tk.BOTH, expand=True)
        ttk.Label(kt_frame,
                  text="Character / place / jargon names for this project. Saved with the project.",
                  style="Sub.TLabel").pack(anchor=tk.W, pady=(4, 0))

        self._refresh_file_list()

        # RIGHT — options
        opts = ttk.LabelFrame(body, text="Scribe options (saved per project)", padding=10,
                              style="Section.TLabelframe")
        opts.grid(row=0, column=1, sticky="nsew")
        self._build_options(opts)

        # Footer
        footer = ttk.Frame(self.container)
        footer.pack(fill=tk.X, pady=(14, 0))
        self.start_btn = ttk.Button(footer, text="Transcribe →",
                                    command=self._start_processing)
        self.start_btn.pack(side=tk.RIGHT)
        ttk.Button(footer, text="💾 Save to project",
                   command=self._save_current_to_project_explicit).pack(side=tk.RIGHT, padx=(0, 8))
        ttk.Button(footer, text="📂 Open output folder",
                   command=self._open_project_output).pack(side=tk.LEFT)
        ttk.Label(footer, text="  Settings auto-save to the project on Transcribe.",
                  style="Sub.TLabel").pack(side=tk.LEFT, padx=8)

        # Populate project dropdown + load the active project's settings.
        self._reload_projects(select_slug=self.slug)

    # ── Project registry wiring ─────────────────────────────────────────────

    def _reload_projects(self, select_slug=None):
        projects = cfg.list_projects()
        names = [p["name"] for p in projects]
        labels = []
        for p in projects:
            n = p["name"]
            labels.append(n if names.count(n) == 1 else f"{n}  ({p['slug']})")
        self.project_slugs = [p["slug"] for p in projects]
        self.project_cb["values"] = labels
        if select_slug not in self.project_slugs:
            select_slug = self.project_slugs[0] if self.project_slugs else None
        if select_slug is not None:
            self.project_cb.current(self.project_slugs.index(select_slug))
        self.slug = select_slug
        if select_slug is not None:
            self._apply_settings(cfg.load_settings(select_slug))

    def _on_project_change(self, _event=None):
        idx = self.project_cb.current()
        if not (0 <= idx < len(self.project_slugs)):
            return
        new_slug = self.project_slugs[idx]
        if new_slug == self.slug:
            return
        # Keep edits to the project we're leaving.
        self._save_current_to_project(silent=True)
        self.slug = new_slug
        self._apply_settings(cfg.load_settings(new_slug))

    def _new_project(self):
        name = simpledialog.askstring("New project", "Project name:", parent=self.root)
        if name is None:
            return
        try:
            self._save_current_to_project(silent=True)
            entry = cfg.add_project(name)
        except cfg.ConfigError as e:
            messagebox.showerror("New project", str(e), parent=self.root)
            return
        self._reload_projects(select_slug=entry["slug"])

    def _manage_projects(self):
        win = tk.Toplevel(self.root)
        win.title("Manage projects")
        win.transient(self.root)
        win.geometry("460x340")
        win.columnconfigure(0, weight=1)
        win.rowconfigure(0, weight=1)

        lb = tk.Listbox(win, activestyle="dotbox")
        lb.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        slugs = []

        def refresh_list():
            lb.delete(0, tk.END)
            slugs.clear()
            for p in cfg.list_projects():
                slugs.append(p["slug"])
                lb.insert(tk.END, f"{p['name']}   ({p['slug']})")

        def selected_slug():
            sel = lb.curselection()
            return slugs[sel[0]] if sel else None

        def do_rename():
            slug = selected_slug()
            if not slug:
                return
            p = cfg.get_project(slug)
            new = simpledialog.askstring("Rename project", "New name:",
                                         initialvalue=p["name"] if p else "", parent=win)
            if new is None:
                return
            try:
                cfg.rename_project(slug, new)
            except cfg.ConfigError as e:
                messagebox.showerror("Rename", str(e), parent=win)
                return
            refresh_list()
            self._reload_projects(select_slug=self.slug)

        def do_duplicate():
            slug = selected_slug()
            if not slug:
                return
            p = cfg.get_project(slug)
            base = f"{p['name']} copy" if p else "Copy"
            new = simpledialog.askstring("Duplicate project",
                                         "Name for the copy:", initialvalue=base, parent=win)
            if new is None:
                return
            try:
                entry = cfg.duplicate_project(slug, new)
            except cfg.ConfigError as e:
                messagebox.showerror("Duplicate", str(e), parent=win)
                return
            refresh_list()
            self._reload_projects(select_slug=entry["slug"])

        def do_delete():
            slug = selected_slug()
            if not slug:
                return
            if len(cfg.list_projects()) <= 1:
                messagebox.showinfo("Delete project",
                                    "Can't delete the only project.", parent=win)
                return
            p = cfg.get_project(slug)
            nm = p["name"] if p else slug
            also = messagebox.askyesnocancel(
                "Delete project",
                f"Remove “{nm}”?\n\n"
                f"Yes = also delete its output/ transcripts folder.\n"
                f"No = remove the project but keep its transcripts on disk.\n"
                f"Cancel = do nothing.",
                parent=win)
            if also is None:
                return
            try:
                cfg.delete_project(slug, delete_output=bool(also))
            except cfg.ConfigError as e:
                messagebox.showerror("Delete", str(e), parent=win)
                return
            refresh_list()
            self._reload_projects(select_slug=cfg.last_used_slug())

        btns = ttk.Frame(win)
        btns.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 10))
        ttk.Button(btns, text="Rename…", command=do_rename).pack(side=tk.LEFT)
        ttk.Button(btns, text="Duplicate…", command=do_duplicate).pack(side=tk.LEFT, padx=6)
        ttk.Button(btns, text="Delete…", command=do_delete).pack(side=tk.LEFT)
        ttk.Button(btns, text="Close", command=win.destroy).pack(side=tk.RIGHT)

        refresh_list()
        win.grab_set()

    # ── Files ────────────────────────────────────────────────────────────────

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

    def _open_project_output(self):
        if self.slug:
            out = str(cfg.output_dir_for(self.slug))
            os.makedirs(out, exist_ok=True)
            open_in_finder(out)
        else:
            open_in_finder(str(cfg.OUTPUT_DIR))

    # ── Options panel ─────────────────────────────────────────────────────────

    def _build_options(self, parent):
        self.opts = {}

        # Model
        row = ttk.Frame(parent); row.pack(fill=tk.X, pady=4)
        ttk.Label(row, text="Model:", width=18, anchor=tk.W).pack(side=tk.LEFT)
        self.opts["model"] = tk.StringVar(value="scribe_v2")
        ttk.Combobox(row, textvariable=self.opts["model"], values=MODELS,
                     state="readonly", width=22).pack(side=tk.LEFT)
        ttk.Label(row, text="  v2 = best quality",
                  style="Sub.TLabel").pack(side=tk.LEFT)

        # Language
        row = ttk.Frame(parent); row.pack(fill=tk.X, pady=4)
        ttk.Label(row, text="Language:", width=18, anchor=tk.W).pack(side=tk.LEFT)
        lang_display = [f"{label}" + (f"  ({code})" if code else "")
                        for code, label in LANGUAGES]
        self._lang_codes = [code for code, _ in LANGUAGES]
        lang_cb = ttk.Combobox(row, values=lang_display, state="readonly", width=22)
        lang_cb.current(0)
        lang_cb.pack(side=tk.LEFT)
        self._lang_cb = lang_cb

        # Diarize
        row = ttk.Frame(parent); row.pack(fill=tk.X, pady=(10, 4))
        self.opts["speakers"] = tk.BooleanVar(value=True)
        ttk.Checkbutton(row, text="Speaker diarization (label who said what)",
                        variable=self.opts["speakers"]).pack(side=tk.LEFT)

        # Num speakers
        row = ttk.Frame(parent); row.pack(fill=tk.X, pady=2)
        ttk.Label(row, text="Speaker count:", width=18, anchor=tk.W).pack(side=tk.LEFT)
        self.opts["num_speakers_mode"] = tk.StringVar(value="auto")
        ttk.Radiobutton(row, text="Auto", value="auto",
                        variable=self.opts["num_speakers_mode"]).pack(side=tk.LEFT)
        ttk.Radiobutton(row, text="Fixed:", value="fixed",
                        variable=self.opts["num_speakers_mode"]).pack(side=tk.LEFT, padx=(8, 2))
        self.opts["num_speakers"] = tk.IntVar(value=2)
        ttk.Spinbox(row, from_=1, to=32, width=4,
                    textvariable=self.opts["num_speakers"]).pack(side=tk.LEFT)

        # Diarization threshold
        row = ttk.Frame(parent); row.pack(fill=tk.X, pady=2)
        ttk.Label(row, text="Diar. sensitivity:", width=18, anchor=tk.W).pack(side=tk.LEFT)
        self.opts["diarization_threshold"] = tk.DoubleVar(value=0.22)
        thr_lbl = ttk.Label(row, text="0.22", width=5)

        def upd_thr(_):
            thr_lbl.config(text=f"{self.opts['diarization_threshold'].get():.2f}")
        ttk.Scale(row, from_=0.10, to=0.40, orient=tk.HORIZONTAL, length=140,
                  variable=self.opts["diarization_threshold"],
                  command=upd_thr).pack(side=tk.LEFT, padx=4)
        thr_lbl.pack(side=tk.LEFT)
        self._thr_lbl = thr_lbl

        # Speaker labels
        row = ttk.Frame(parent); row.pack(fill=tk.X, pady=2)
        ttk.Label(row, text="Speaker labels:", width=18, anchor=tk.W).pack(side=tk.LEFT)
        self.opts["labels"] = tk.StringVar(value="")
        ttk.Entry(row, textvariable=self.opts["labels"], width=24).pack(side=tk.LEFT)
        row = ttk.Frame(parent); row.pack(fill=tk.X)
        ttk.Label(row, text="   e.g. 0=DM,1=Player 1,2=Player 2",
                  style="Sub.TLabel").pack(side=tk.LEFT, padx=(18, 0))

        # detect_speaker_roles
        row = ttk.Frame(parent); row.pack(fill=tk.X, pady=2)
        self.opts["detect_speaker_roles"] = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            row, text="Detect speaker roles (agent / customer) · needs diarize",
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
            row, text="Clean transcript (drop ums, false starts) — scribe_v2 only",
            variable=self.opts["no_verbatim"]).pack(side=tk.LEFT)

        # Temperature
        row = ttk.Frame(parent); row.pack(fill=tk.X, pady=(10, 4))
        ttk.Label(row, text="Temperature:", width=18, anchor=tk.W).pack(side=tk.LEFT)
        self.opts["temperature_enabled"] = tk.BooleanVar(value=False)
        ttk.Checkbutton(row, variable=self.opts["temperature_enabled"]).pack(side=tk.LEFT)
        self.opts["temperature"] = tk.DoubleVar(value=0.0)
        ttk.Spinbox(row, from_=0.0, to=2.0, increment=0.1,
                    textvariable=self.opts["temperature"], width=6).pack(side=tk.LEFT, padx=4)
        ttk.Label(row, text=" 0 = deterministic", style="Sub.TLabel").pack(side=tk.LEFT)

        # Seed
        row = ttk.Frame(parent); row.pack(fill=tk.X, pady=4)
        ttk.Label(row, text="Seed:", width=18, anchor=tk.W).pack(side=tk.LEFT)
        self.opts["seed_enabled"] = tk.BooleanVar(value=False)
        ttk.Checkbutton(row, variable=self.opts["seed_enabled"]).pack(side=tk.LEFT)
        self.opts["seed"] = tk.IntVar(value=42)
        ttk.Spinbox(row, from_=0, to=2147483647,
                    textvariable=self.opts["seed"], width=12).pack(side=tk.LEFT, padx=4)

        # Timestamps granularity
        row = ttk.Frame(parent); row.pack(fill=tk.X, pady=(10, 4))
        ttk.Label(row, text="Timestamps:", width=18, anchor=tk.W).pack(side=tk.LEFT)
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

    # ── Settings <-> widgets ─────────────────────────────────────────────────

    def _apply_settings(self, s):
        self.opts["model"].set(s.get("model", "scribe_v2"))
        code = s.get("language", "") or ""
        try:
            self._lang_cb.current(self._lang_codes.index(code))
        except ValueError:
            self._lang_cb.current(0)
        self.opts["speakers"].set(bool(s.get("speakers", True)))
        self.opts["num_speakers_mode"].set(s.get("num_speakers_mode", "auto"))
        self.opts["num_speakers"].set(int(s.get("num_speakers", 2)))
        self.opts["diarization_threshold"].set(float(s.get("diarization_threshold", 0.22)))
        self._thr_lbl.config(text=f"{self.opts['diarization_threshold'].get():.2f}")
        self.opts["labels"].set(s.get("labels", "") or "")
        self.opts["detect_speaker_roles"].set(bool(s.get("detect_speaker_roles", False)))
        self.opts["tag_audio_events"].set(bool(s.get("tag_audio_events", False)))
        self.opts["no_verbatim"].set(bool(s.get("no_verbatim", True)))
        self.opts["temperature_enabled"].set(bool(s.get("temperature_enabled", False)))
        self.opts["temperature"].set(float(s.get("temperature", 0.0)))
        self.opts["seed_enabled"].set(bool(s.get("seed_enabled", False)))
        self.opts["seed"].set(int(s.get("seed", 42)))
        self.opts["timestamps"].set(s.get("timestamps", "word"))
        self.opts["format"].set(s.get("format", "text"))
        self.opts["inline_timestamps"].set(bool(s.get("inline_timestamps", True)))
        # Keyterms editor — one per line.
        self.keyterms_text.delete("1.0", tk.END)
        self.keyterms_text.insert("1.0", "\n".join(s.get("keyterms", [])))

    def _collect_form(self):
        """Read widgets into a settings dict (persistable form: keyterms=list)."""
        kt_raw = self.keyterms_text.get("1.0", tk.END)
        keyterms = [t.strip() for t in kt_raw.replace(",", "\n").splitlines() if t.strip()]
        return {
            "model": self.opts["model"].get(),
            "language": self._lang_codes[self._lang_cb.current()] or "",
            "speakers": self.opts["speakers"].get(),
            "num_speakers_mode": self.opts["num_speakers_mode"].get(),
            "num_speakers": self.opts["num_speakers"].get(),
            "diarization_threshold": round(self.opts["diarization_threshold"].get(), 2),
            "labels": self.opts["labels"].get().strip(),
            "detect_speaker_roles": self.opts["detect_speaker_roles"].get(),
            "tag_audio_events": self.opts["tag_audio_events"].get(),
            "no_verbatim": self.opts["no_verbatim"].get(),
            "temperature_enabled": self.opts["temperature_enabled"].get(),
            "temperature": round(self.opts["temperature"].get(), 2),
            "seed_enabled": self.opts["seed_enabled"].get(),
            "seed": self.opts["seed"].get(),
            "timestamps": self.opts["timestamps"].get(),
            "format": self.opts["format"].get(),
            "inline_timestamps": self.opts["inline_timestamps"].get(),
            "keyterms": keyterms,
        }

    def _settings_for_run(self, form):
        """Translate the persisted form into the flat dict the Worker needs."""
        s = dict(form)
        s["language"] = form["language"] or None
        s["num_speakers"] = (form["num_speakers"]
                             if form["num_speakers_mode"] == "fixed" else None)
        s["no_verbatim"] = form["no_verbatim"] and form["model"] == "scribe_v2"
        s["keyterms"] = ",".join(form["keyterms"]) if form["keyterms"] else None
        s["temperature"] = form["temperature"] if form["temperature_enabled"] else None
        s["seed"] = form["seed"] if form["seed_enabled"] else None
        return s

    def _save_current_to_project(self, silent=False):
        if not self.slug or not self.opts:
            return
        try:
            cfg.save_settings(self.slug, self._collect_form())
        except Exception as e:
            if not silent:
                messagebox.showerror("Save failed", str(e), parent=self.root)

    def _save_current_to_project_explicit(self):
        self._save_current_to_project(silent=False)
        p = cfg.get_project(self.slug)
        nm = p["name"] if p else self.slug
        self.start_btn.focus_set()
        messagebox.showinfo("Saved", f"Settings saved to “{nm}”.", parent=self.root)

    # ── Processing ─────────────────────────────────────────────────────────

    def _start_processing(self):
        if not self.slug:
            messagebox.showinfo("No project", "Create a project first.")
            return
        if not self.inbox_files:
            messagebox.showinfo("No files", "Drop recordings in inbox/ or click ➕ Add file.")
            return
        sel = self.file_listbox.curselection()
        if not sel:
            messagebox.showinfo("No selection", "Select at least one file.")
            return
        self.selected_files = [self.inbox_files[i][0] for i in sel]

        form = self._collect_form()
        self._save_current_to_project(silent=True)   # persist edits to the project
        try:
            cfg.set_last_used(self.slug)
        except Exception:
            pass
        settings = self._settings_for_run(form)

        if not os.access(STT_LAUNCHER, os.X_OK):
            messagebox.showerror("Missing launcher",
                                 f"Can't find executable: {STT_LAUNCHER}\n"
                                 "Make sure ./projects-stt is present and chmod +x.")
            return

        output_dir = str(cfg.output_dir_for(self.slug))
        self.cancel_event = threading.Event()
        self.msg_q = queue.Queue()
        self.start_time = time.time()
        self.file_durations = []
        self.results = []

        self.show_processing_screen()
        self.worker = Worker(self.selected_files, settings, output_dir,
                             self.msg_q, self.cancel_event)
        self.worker.start()

    def show_processing_screen(self):
        self._clear()
        p = cfg.get_project(self.slug)
        nm = p["name"] if p else self.slug
        ttk.Label(self.container, text="🎙  Transcribing",
                  style="Header.TLabel").pack(anchor=tk.W)
        ttk.Label(self.container,
                  text=f"Project “{nm}” · {len(self.selected_files)} file(s)...",
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
        self.file_bar = ttk.Progressbar(cur, mode="determinate", length=500, maximum=100)
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
                   command=self._open_project_output).pack(side=tk.LEFT)
        ttk.Button(btns, text="🔄 Transcribe more",
                   command=self.show_main_screen).pack(side=tk.LEFT, padx=8)
        ttk.Button(btns, text="Quit", command=self._on_quit).pack(side=tk.RIGHT)

    def _on_quit(self):
        # Persist any unsaved edits if we're on the setup screen.
        try:
            if self.opts and self.keyterms_text.winfo_exists():
                self._save_current_to_project(silent=True)
        except Exception:
            pass
        self.root.destroy()


def main():
    root = tk.Tk()
    ProjectsGUI(root)
    root.update_idletasks()
    w = max(920, root.winfo_reqwidth() + 40)
    h = max(780, root.winfo_reqheight() + 40)
    root.geometry(f"{w}x{h}")
    root.mainloop()


if __name__ == "__main__":
    main()
