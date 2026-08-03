#!/usr/bin/env python3
"""Project registry + per-project settings for the Project Transcriber.

A *project* is a named transcription context (a TTRPG campaign, a client, a
podcast, ...) that carries its own ElevenLabs Scribe settings — most usefully
its own **keyterms** (character / place / jargon names to bias recognition
toward), plus speaker labels, diarization defaults, output format, etc.

Layout on disk (all under this folder):

    projects.json            registry of projects (slug = immutable id)
    config/<slug>.json       one settings profile per project
    inbox/                   SHARED drop-folder for audio (pick project per run)
    output/<slug>/           per-project transcripts
    processed/               SHARED — audio moved here after a successful run

Mirrors bankzero-ynab's account model: the slug is the stable identity, the
display name is editable, and the registry tracks which project you used last.
"""

from __future__ import annotations

import json
import os
import re
import unicodedata
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

try:
    import fcntl  # POSIX only; the tool targets macOS.
except ImportError:  # pragma: no cover - Windows fallback
    fcntl = None

SCRIPT_DIR = Path(__file__).resolve().parent
INBOX_DIR = SCRIPT_DIR / "inbox"            # shared across projects
OUTPUT_DIR = SCRIPT_DIR / "output"          # per-project subfolders live here
PROCESSED_DIR = SCRIPT_DIR / "processed"    # shared
CONFIG_DIR = SCRIPT_DIR / "config"
PROJECTS_FILE = SCRIPT_DIR / "projects.json"

REGISTRY_VERSION = 1
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")

DEFAULT_PROJECT_NAME = "General"

# One profile per project. Keyterms is the headline field; the rest are the
# Scribe knobs the GUI exposes so switching projects restores a full setup.
DEFAULT_SETTINGS: dict = {
    "model": "scribe_v2",
    "language": "",                 # "" = auto-detect
    "speakers": True,               # diarize
    "num_speakers_mode": "auto",    # "auto" | "fixed"
    "num_speakers": 2,
    "diarization_threshold": 0.22,
    "labels": "",                   # e.g. "0=DM,1=Player 1"
    "detect_speaker_roles": False,
    "tag_audio_events": False,
    "no_verbatim": True,            # scribe_v2 only
    "keyterms": [],                 # list[str]
    "temperature_enabled": False,
    "temperature": 0.0,
    "seed_enabled": False,
    "seed": 42,
    "timestamps": "word",           # word | character | none
    "format": "text",               # text | srt | vtt | json
    "inline_timestamps": True,
}


class ConfigError(Exception):
    """User-facing configuration error (shown in a dialog)."""


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #

def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_dirs() -> None:
    for d in (INBOX_DIR, OUTPUT_DIR, PROCESSED_DIR, CONFIG_DIR):
        d.mkdir(parents=True, exist_ok=True)


def write_json_atomic(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".tmp.{os.getpid()}")
    tmp.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


@contextmanager
def _lock(path: Path):
    """Best-effort advisory lock so two open GUIs don't corrupt the registry."""
    if fcntl is None:
        yield
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(path.name + ".lock")
    fh = open(lock_path, "w")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(fh, fcntl.LOCK_UN)
        finally:
            fh.close()


def slugify(name: str) -> str:
    n = unicodedata.normalize("NFKD", name or "")
    n = "".join(c for c in n if not unicodedata.combining(c))
    n = n.encode("ascii", "ignore").decode("ascii").lower()
    n = re.sub(r"[^a-z0-9]+", "_", n).strip("_")
    return n or "project"


def assert_safe_slug(slug: str) -> None:
    """Guard against path traversal from a hand-edited/corrupted registry."""
    if not isinstance(slug, str) or not SLUG_RE.match(slug):
        raise ConfigError(f"Unsafe project id: {slug!r}")


def unique_slug(base: str, taken: set[str]) -> str:
    """base, else base-2, base-3... avoiding both live slugs and stray config
    files left behind by a keep-files delete."""
    base = base or "project"

    def in_use(candidate: str) -> bool:
        return candidate in taken or (CONFIG_DIR / f"{candidate}.json").exists()

    if not in_use(base):
        return base
    i = 2
    while in_use(f"{base}-{i}"):
        i += 1
    return f"{base}-{i}"


# --------------------------------------------------------------------------- #
# Registry (projects.json)
# --------------------------------------------------------------------------- #

def _new_registry() -> dict:
    return {"version": REGISTRY_VERSION, "last_used_slug": None, "projects": []}


def _read_registry_or_rebuild() -> dict:
    try:
        return json.loads(PROJECTS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        if PROJECTS_FILE.exists():
            try:
                stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
                PROJECTS_FILE.rename(PROJECTS_FILE.with_name(
                    PROJECTS_FILE.name + f".corrupt-{stamp}"))
            except OSError:
                pass
        doc = _new_registry()
        write_json_atomic(PROJECTS_FILE, doc)
        return doc


def _validate(doc: dict) -> dict:
    if not isinstance(doc, dict):
        doc = _new_registry()
    projects = doc.get("projects")
    if not isinstance(projects, list):
        projects = []
    clean: list[dict] = []
    seen: set[str] = set()
    for p in projects:
        if not isinstance(p, dict):
            continue
        slug = p.get("slug")
        if not (isinstance(slug, str) and SLUG_RE.match(slug)) or slug in seen:
            continue
        seen.add(slug)
        p.setdefault("name", slug)
        p.setdefault("created", now_utc_iso())
        p.setdefault("last_used", None)
        clean.append(p)
    doc["projects"] = clean
    slugs = {p["slug"] for p in clean}
    if doc.get("last_used_slug") not in slugs:
        doc["last_used_slug"] = clean[0]["slug"] if clean else None
    doc.setdefault("version", REGISTRY_VERSION)
    return doc


def load_registry() -> dict:
    """Load (validating), seeding a default project on very first run."""
    ensure_dirs()
    doc = _validate(_read_registry_or_rebuild())
    if not doc["projects"]:
        doc = _seed_default(doc)
    return doc


def _seed_default(doc: dict) -> dict:
    slug = unique_slug(slugify(DEFAULT_PROJECT_NAME), set())
    doc["projects"].append({
        "slug": slug,
        "name": DEFAULT_PROJECT_NAME,
        "created": now_utc_iso(),
        "last_used": None,
    })
    doc["last_used_slug"] = slug
    write_json_atomic(PROJECTS_FILE, doc)
    save_settings(slug, dict(DEFAULT_SETTINGS))
    return doc


def list_projects() -> list[dict]:
    return list(load_registry()["projects"])


def get_project(slug: str) -> dict | None:
    for p in load_registry()["projects"]:
        if p["slug"] == slug:
            return p
    return None


def last_used_slug() -> str | None:
    return load_registry().get("last_used_slug")


def add_project(name: str) -> dict:
    name = (name or "").strip()
    if not name:
        raise ConfigError("Project name cannot be empty.")
    with _lock(PROJECTS_FILE):
        doc = _validate(_read_registry_or_rebuild())
        taken = {p["slug"] for p in doc["projects"]}
        slug = unique_slug(slugify(name), taken)
        entry = {"slug": slug, "name": name,
                 "created": now_utc_iso(), "last_used": None}
        doc["projects"].append(entry)
        doc["last_used_slug"] = slug
        write_json_atomic(PROJECTS_FILE, doc)
    if not (CONFIG_DIR / f"{slug}.json").exists():
        save_settings(slug, dict(DEFAULT_SETTINGS))
    return entry


def duplicate_project(src_slug: str, name: str) -> dict:
    """New project seeded with a copy of src's settings (keyterms and all)."""
    assert_safe_slug(src_slug)
    src_settings = load_settings(src_slug)
    entry = add_project(name)
    save_settings(entry["slug"], src_settings)
    return entry


def rename_project(slug: str, new_name: str) -> None:
    assert_safe_slug(slug)
    new_name = (new_name or "").strip()
    if not new_name:
        raise ConfigError("Project name cannot be empty.")
    with _lock(PROJECTS_FILE):
        doc = _validate(_read_registry_or_rebuild())
        for p in doc["projects"]:
            if p["slug"] == slug:
                p["name"] = new_name
                write_json_atomic(PROJECTS_FILE, doc)
                return
    raise ConfigError(f"Unknown project: {slug}")


def delete_project(slug: str, *, delete_output: bool = False) -> None:
    assert_safe_slug(slug)
    with _lock(PROJECTS_FILE):
        doc = _validate(_read_registry_or_rebuild())
        before = len(doc["projects"])
        doc["projects"] = [p for p in doc["projects"] if p["slug"] != slug]
        if len(doc["projects"]) == before:
            raise ConfigError(f"Unknown project: {slug}")
        if doc["last_used_slug"] == slug:
            doc["last_used_slug"] = (doc["projects"][0]["slug"]
                                     if doc["projects"] else None)
        write_json_atomic(PROJECTS_FILE, doc)
    cfg = CONFIG_DIR / f"{slug}.json"
    if cfg.exists():
        try:
            cfg.unlink()
        except OSError:
            pass
    if delete_output:
        import shutil
        out = output_dir_for(slug)
        if out.exists():
            shutil.rmtree(out, ignore_errors=True)


def set_last_used(slug: str) -> None:
    assert_safe_slug(slug)
    with _lock(PROJECTS_FILE):
        doc = _validate(_read_registry_or_rebuild())
        found = False
        for p in doc["projects"]:
            if p["slug"] == slug:
                p["last_used"] = now_utc_iso()
                found = True
        if found:
            doc["last_used_slug"] = slug
            write_json_atomic(PROJECTS_FILE, doc)


# --------------------------------------------------------------------------- #
# Per-project settings (config/<slug>.json)
# --------------------------------------------------------------------------- #

def settings_path(slug: str) -> Path:
    assert_safe_slug(slug)
    return CONFIG_DIR / f"{slug}.json"


def load_settings(slug: str) -> dict:
    """Return the project's settings, merged over defaults (missing keys filled,
    unknown keys dropped)."""
    path = settings_path(slug)
    merged = dict(DEFAULT_SETTINGS)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            for k in DEFAULT_SETTINGS:
                if k in raw:
                    merged[k] = raw[k]
    except (OSError, json.JSONDecodeError):
        pass
    # keyterms is always a clean list[str].
    kt = merged.get("keyterms")
    if isinstance(kt, str):
        kt = re.split(r"[,\n]", kt)
    if not isinstance(kt, list):
        kt = []
    merged["keyterms"] = [str(t).strip() for t in kt if str(t).strip()]
    return merged


def save_settings(slug: str, settings: dict) -> None:
    assert_safe_slug(slug)
    clean = dict(DEFAULT_SETTINGS)
    for k in DEFAULT_SETTINGS:
        if k in settings:
            clean[k] = settings[k]
    kt = clean.get("keyterms") or []
    if isinstance(kt, str):
        kt = re.split(r"[,\n]", kt)
    clean["keyterms"] = [str(t).strip() for t in kt if str(t).strip()]
    write_json_atomic(settings_path(slug), clean)


# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #

def output_dir_for(slug: str) -> Path:
    assert_safe_slug(slug)
    return OUTPUT_DIR / slug
