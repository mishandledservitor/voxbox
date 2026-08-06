#!/usr/bin/env python3
"""
Project STT — ElevenLabs Scribe wrapper exposing the full API surface, driven
by per-project settings (keyterms, speaker labels, diarization, ...).

Designed to be driven by projects_gui.py but also usable from the CLI. Reuses
the sibling speech-to-text venv so the `elevenlabs` SDK is shared.
"""

import argparse
import json
import os
import sys
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Reuse the speech-to-text venv's .env / env var.
PARENT_STT_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, "..", "speech-to-text"))

SUPPORTED_FORMATS = [
    "mp3", "mp4", "wav", "m4a", "ogg", "flac",
    "aac", "webm", "mkv", "mov", "avi", "opus",
]


def load_api_key():
    key = os.environ.get("ELEVENLABS_API_KEY")
    if key:
        return key.strip()
    for env_file in (os.path.join(SCRIPT_DIR, ".env"),
                     os.path.join(PARENT_STT_DIR, ".env")):
        if os.path.isfile(env_file):
            with open(env_file) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("ELEVENLABS_API_KEY="):
                        val = line.split("=", 1)[1].strip()
                        if val.startswith(('"', "'")) and val.endswith(('"', "'")):
                            val = val[1:-1]
                        return val
    return None


def fmt_time(seconds):
    if seconds < 60:
        return f"{seconds:.0f}s"
    m, s = divmod(int(seconds), 60)
    if m < 60:
        return f"{m}m {s:02d}s"
    h, m = divmod(m, 60)
    return f"{h}h {m:02d}m"


def ts_srt(secs):
    if secs is None:
        secs = 0.0
    h = int(secs // 3600)
    m = int((secs % 3600) // 60)
    s = int(secs % 60)
    ms = int(round((secs - int(secs)) * 1000))
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def ts_human(secs):
    if secs is None:
        secs = 0.0
    h = int(secs // 3600)
    m = int((secs % 3600) // 60)
    s = int(secs % 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def _speaker_segments(words):
    segments = []
    cur_speaker = None
    cur_text = []
    cur_start = None
    cur_end = None
    for w in words:
        if w.type not in ("word", "spacing"):
            continue
        spk = w.speaker_id or "?"
        if spk != cur_speaker:
            if cur_text:
                segments.append((cur_speaker, "".join(cur_text).strip(), cur_start, cur_end))
            cur_speaker = spk
            cur_text = []
            cur_start = w.start
        cur_text.append(w.text)
        if w.end is not None:
            cur_end = w.end
    if cur_text:
        segments.append((cur_speaker, "".join(cur_text).strip(), cur_start, cur_end))
    return segments


def _label_for_speaker(spk, label_map):
    if label_map and spk in label_map:
        return label_map[spk]
    # ElevenLabs returns 'agent' / 'customer' when detect_speaker_roles=true.
    if spk in ("agent", "customer"):
        return spk.capitalize()
    return f"Speaker {spk}"


def format_text(response, speakers, label_map, timestamps):
    if speakers and response.words:
        segs = _speaker_segments(response.words)
        lines = []
        for s, t, st, _ in segs:
            if not t:
                continue
            label = _label_for_speaker(s, label_map)
            if timestamps:
                lines.append(f"[{ts_human(st)}] {label}: {t}")
            else:
                lines.append(f"{label}: {t}")
        return "\n\n".join(lines)
    return (response.text or "").strip()


def format_srt(response, speakers, label_map):
    lines = []
    if speakers and response.words:
        for i, (spk, text, start, end) in enumerate(_speaker_segments(response.words), 1):
            if not text:
                continue
            label = _label_for_speaker(spk, label_map)
            lines.append(str(i))
            lines.append(f"{ts_srt(start or 0)} --> {ts_srt(end or 0)}")
            lines.append(f"{label}: {text}")
            lines.append("")
        return "\n".join(lines)
    words = [w for w in (response.words or []) if w.type == "word"]
    for i, start in enumerate(range(0, len(words), 10), 1):
        chunk = words[start:start + 10]
        text = " ".join(w.text for w in chunk)
        t0 = chunk[0].start or 0
        t1 = chunk[-1].end or chunk[-1].start or 0
        lines.append(str(i))
        lines.append(f"{ts_srt(t0)} --> {ts_srt(t1)}")
        lines.append(text)
        lines.append("")
    if not lines:
        lines = ["1", "00:00:00,000 --> 00:00:01,000", response.text or "", ""]
    return "\n".join(lines)


def format_vtt(response, speakers, label_map):
    srt = format_srt(response, speakers, label_map)
    vtt = ["WEBVTT", ""]
    for line in srt.splitlines():
        vtt.append(line.replace(",", ".", 1) if "-->" in line else line)
    return "\n".join(vtt)


def format_json_out(response, speakers, label_map):
    data = {
        "language_code": getattr(response, "language_code", None),
        "language_probability": getattr(response, "language_probability", None),
        "text": response.text,
    }
    if speakers and response.words:
        data["segments"] = [
            {
                "speaker": s,
                "label": _label_for_speaker(s, label_map),
                "text": t,
                "start": st,
                "end": en,
            }
            for s, t, st, en in _speaker_segments(response.words)
            if t
        ]
    return json.dumps(data, indent=2, ensure_ascii=False)


def transcribe(client, audio_path, *, model_id, speakers, language, num_speakers,
               tag_audio_events, timestamps_granularity, diarization_threshold,
               no_verbatim, detect_speaker_roles, keyterms, temperature, seed):
    kwargs = {
        "model_id": model_id,
        "diarize": speakers,
        "tag_audio_events": tag_audio_events,
        "timestamps_granularity": timestamps_granularity,
    }
    if language:
        kwargs["language_code"] = language
    if speakers and num_speakers:
        kwargs["num_speakers"] = num_speakers
    if speakers and diarization_threshold is not None and not num_speakers:
        # API only accepts threshold when num_speakers is unset.
        kwargs["diarization_threshold"] = diarization_threshold
    if no_verbatim:
        kwargs["no_verbatim"] = True
    if speakers and detect_speaker_roles:
        kwargs["detect_speaker_roles"] = True
    if keyterms:
        kwargs["keyterms"] = keyterms
    if temperature is not None:
        kwargs["temperature"] = temperature
    if seed is not None:
        kwargs["seed"] = seed

    print("stage: uploading", flush=True)
    t0 = time.time()
    with open(audio_path, "rb") as f:
        try:
            response = client.speech_to_text.convert(file=f, **kwargs)
        except TypeError:
            # Older SDKs may not know newer kwargs — drop them and retry.
            for k in ("diarization_threshold", "num_speakers", "tag_audio_events",
                      "no_verbatim", "detect_speaker_roles", "keyterms",
                      "temperature", "seed"):
                kwargs.pop(k, None)
            f.seek(0)
            response = client.speech_to_text.convert(file=f, **kwargs)
    elapsed = time.time() - t0
    print(f"✅ Transcribed in {fmt_time(elapsed)}", flush=True)
    print("stage: done", flush=True)
    return response


def model_id_current():
    return os.environ.get("PROJECT_MODEL_ID", "scribe_v2")


def model_id_label():
    mid = model_id_current()
    return {"scribe_v1": "Scribe v1", "scribe_v2": "Scribe v2"}.get(mid, mid)


def process_file(client, audio_path, *, out_format, output_path, speakers, language,
                 num_speakers, tag_audio_events, timestamps_granularity,
                 diarization_threshold, no_verbatim, detect_speaker_roles,
                 keyterms, temperature, seed,
                 label_map, inline_timestamps, no_print):
    audio_path = os.path.abspath(os.path.expanduser(audio_path))
    if not os.path.isfile(audio_path):
        print(f"⚠  File not found: {audio_path}")
        return False
    ext = os.path.splitext(audio_path)[1].lower().lstrip(".")
    if ext not in SUPPORTED_FORMATS:
        print(f"⚠  Unsupported format: .{ext}")
        return False

    size_mb = os.path.getsize(audio_path) / (1024 * 1024)
    print(f"🎤 File: {os.path.basename(audio_path)} ({size_mb:.1f} MB)")
    print(f"🧠 Model: {model_id_label()}  (id={model_id_current()})")
    print(f"🌐 Language: {language or 'auto-detect'}")
    print(f"👥 Diarize: {'yes' if speakers else 'no'}"
          + (f" (num_speakers={num_speakers})" if speakers and num_speakers else ""))
    print(f"🏷  Audio events: {'tagged' if tag_audio_events else 'off'}")
    print(f"⏱  Timestamps: {timestamps_granularity}")
    if no_verbatim:
        print("🧹 no_verbatim: stripping fillers / false starts (scribe_v2 only)")
    if detect_speaker_roles:
        print("🎭 detect_speaker_roles: labelling agent vs customer")
    if keyterms:
        print(f"🔑 keyterms: {len(keyterms)} biased terms")

    try:
        response = transcribe(
            client, audio_path,
            model_id=model_id_current(),
            speakers=speakers,
            language=language,
            num_speakers=num_speakers,
            tag_audio_events=tag_audio_events,
            timestamps_granularity=timestamps_granularity,
            diarization_threshold=diarization_threshold,
            no_verbatim=no_verbatim,
            detect_speaker_roles=detect_speaker_roles,
            keyterms=keyterms,
            temperature=temperature,
            seed=seed,
        )
    except Exception as e:
        print(f"⚠  Transcription failed: {e}")
        return False

    if out_format == "json":
        result = format_json_out(response, speakers, label_map)
    elif out_format == "srt":
        result = format_srt(response, speakers, label_map)
    elif out_format == "vtt":
        result = format_vtt(response, speakers, label_map)
    else:
        result = format_text(response, speakers, label_map, inline_timestamps)

    if not no_print:
        print("─" * 50)
        print(result)
        print("─" * 50)

    if output_path:
        out_dir = os.path.dirname(output_path)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        with open(output_path, "w") as f:
            f.write(result)
        print(f"💾 Saved: {output_path}")
    return True


def parse_label_map(spec):
    if not spec:
        return None
    out = {}
    for pair in spec.split(","):
        if "=" not in pair:
            continue
        k, v = pair.split("=", 1)
        out[k.strip()] = v.strip()
    return out or None


def main():
    p = argparse.ArgumentParser(description="Project STT — ElevenLabs Scribe with full options")
    p.add_argument("audio", nargs="?")
    p.add_argument("-o", "--output")
    p.add_argument("-f", "--format", choices=["text", "srt", "vtt", "json"], default="text")
    p.add_argument("-l", "--language", help="ISO-639 language code (auto-detect if omitted)")
    p.add_argument("--speakers", action="store_true", help="Enable diarization")
    p.add_argument("--num-speakers", type=int, help="Known speaker count (1–32)")
    p.add_argument("--no-audio-events", action="store_true",
                   help="Disable [laughter] / [applause] tagging")
    p.add_argument("--timestamps", choices=["none", "word", "character"], default="word")
    p.add_argument("--diarization-threshold", type=float,
                   help="0.1 (loose) – 0.4 (strict). Default ~0.22. Only honoured if num_speakers is unset.")
    p.add_argument("--model", choices=["scribe_v1", "scribe_v2"], default="scribe_v2")
    p.add_argument("--no-verbatim", action="store_true",
                   help="Strip filler words / false starts (scribe_v2 only)")
    p.add_argument("--detect-speaker-roles", action="store_true",
                   help="Label speakers as 'agent' / 'customer' (requires diarize)")
    p.add_argument("--keyterms", help="Comma list of keyterms to bias toward (≤5 words each; keep to 100 or fewer — over 100 bills a 20s minimum per request)")
    p.add_argument("--temperature", type=float, help="0.0–2.0 (default: model default)")
    p.add_argument("--seed", type=int, help="Best-effort deterministic sampling seed")
    p.add_argument("--labels", help="Comma list mapping speaker ids: '0=DM,1=Player 1'")
    p.add_argument("--inline-timestamps", action="store_true",
                   help="Prefix each text-format line with [hh:mm:ss]")
    p.add_argument("--no-print", action="store_true")
    args = p.parse_args()

    os.environ["PROJECT_MODEL_ID"] = args.model

    api_key = load_api_key()
    if not api_key:
        print("⚠  No ELEVENLABS_API_KEY found. Set the env var or drop it in .env.")
        sys.exit(1)

    try:
        from elevenlabs import ElevenLabs
    except ImportError:
        print("⚠  elevenlabs package not installed. Run: pip install elevenlabs")
        sys.exit(1)

    client = ElevenLabs(api_key=api_key)

    if not args.audio:
        print("⚠  No audio file provided.")
        sys.exit(1)

    keyterms = [k.strip() for k in (args.keyterms or "").split(",") if k.strip()] or None

    ok = process_file(
        client, args.audio,
        out_format=args.format,
        output_path=args.output,
        speakers=args.speakers,
        language=args.language,
        num_speakers=args.num_speakers,
        tag_audio_events=not args.no_audio_events,
        timestamps_granularity=args.timestamps,
        diarization_threshold=args.diarization_threshold,
        no_verbatim=args.no_verbatim,
        detect_speaker_roles=args.detect_speaker_roles,
        keyterms=keyterms,
        temperature=args.temperature,
        seed=args.seed,
        label_map=parse_label_map(args.labels),
        inline_timestamps=args.inline_timestamps,
        no_print=args.no_print,
    )
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
