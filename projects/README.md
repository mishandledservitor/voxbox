# Project Transcriber

A project-selectable GUI for transcribing audio via ElevenLabs Scribe, where
**each project carries its own keyterms and Scribe settings**. Pick a project
(a TTRPG campaign, a client, a podcast…), and the GUI loads that project's
keyword list, speaker labels, diarization defaults, output format, etc.

Modelled on `bankzero-ynab`'s account selector (top bar + Add / Manage) and the
generic version of the `shortlisted/` call transcriber — but domain-agnostic, so
you can keep a distinct keyword set per game/domain/project.

## Launch

```bash
./projects           # GUI
./projects-stt -h    # CLI
```

## Setup (one-time)

Reuses the sibling `speech-to-text` venv (the `elevenlabs` SDK lives there). If
`../speech-to-text/venv` doesn't exist yet:

```bash
cd ../speech-to-text && ./setup_elevenlabs.sh
```

Then add your API key to `../speech-to-text/.env` (or export
`ELEVENLABS_API_KEY`).

## Workflow

1. Drop recordings in the shared `inbox/` (or click ➕ Add file in the GUI).
2. Pick a **project** in the top bar — its keyterms and settings load in.
   - **+ New project…** creates one; **Manage…** renames / duplicates / deletes.
   - **Duplicate** is handy for spinning off a new campaign from an existing
     keyword set.
3. Edit the **keyterms** (one per line) and any Scribe options for this project.
4. Select files → **Transcribe**. Settings auto-save to the project (there's
   also an explicit **💾 Save to project**).
5. Transcripts land in `output/<project>/`; the source audio moves to the
   shared `processed/`.

## What a project stores

Everything in the options panel plus keyterms, in `config/<slug>.json`:

- **keyterms** — comma/newline list biasing recognition (character, place,
  jargon names). ≤5 words and ≤50 chars per term. Scribe accepts up to 1000
  terms, but keep it to **100 or fewer** — over 100 triggers a 20-second
  minimum billable duration per request.
- **model** — `scribe_v2` (best) / `scribe_v1`
- **language** — auto-detect or an ISO-639 code
- **diarize** + **speaker count** (auto / fixed 1–32) + **sensitivity**
- **speaker labels** — map `0=DM,1=Player 1` style
- **detect speaker roles** — agent / customer (needs diarize)
- **tag audio events** — `[laughter]`, `[applause]`, …
- **clean transcript** (`no_verbatim`, scribe_v2 only)
- **temperature** / **seed** (both opt-in)
- **timestamps** granularity, **output format**, inline `[hh:mm:ss]` prefix

## Files & state

| Path | Tracked? | Contents |
|------|----------|----------|
| `projects.json` | no (gitignored) | project registry (slug = immutable id) |
| `config/<slug>.json` | no | per-project settings + keyterms |
| `inbox/` | dir only | shared drop-folder for audio |
| `output/<slug>/` | dir only | per-project transcripts |
| `processed/` | dir only | audio moved here after a successful run |

Registry and settings are **local state** (they can hold private campaign/client
names), so they're gitignored like `bankzero-ynab`'s `accounts.json`. A fresh
clone seeds a single default **General** project on first launch.

## Relationship to the other STT tools

- `speech-to-text/` — the original TTRPG-tuned pipelines (`transcribe.py`).
- `shortlisted/` — the fixed client-call transcriber (Simon + Client defaults).
- `projects/` (this) — the general, project-selectable version. Self-contained
  (`projects_stt.py`), but shares the `speech-to-text` venv.
