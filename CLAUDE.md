# CLAUDE.md — agent onboarding notes

Companion to `AGENTS.md`. That file describes the repo layout and the submodule commit/push workflow; this one captures the install gotchas we've actually hit so you don't rediscover them.

## Installing voxbox on a fresh macOS

Always start with:

```bash
git submodule update --init --recursive
./setup_voxbox.sh
```

The setup script is idempotent — re-running it is safe.

### Gotcha 1 — Homebrew Python 3.14 has no Tk

`brew install python@3.14` does **not** include `tkinter`. Launching the GUI fails with:

```
ModuleNotFoundError: No module named '_tkinter'
```

Fix:

```bash
brew install python-tk@3.14   # match your python3 minor version
```

`setup_voxbox.sh` (step 2) detects this and installs the right `python-tk@<X.Y>` automatically. If you're working around setup, install Tk manually before launching `./voxbox`.

### Gotcha 2 — the cloud STT submodules need API keys before they're useful

Two submodules ship the cloud transcription tools and both need `.env` files (gitignored — never commit):

| File | Contents |
|------|----------|
| `assemblyai-stt/.env` | `ASSEMBLYAI_API_KEY=...` |
| `speech-to-text/.env` | `ELEVENLABS_API_KEY=...` |

Step 5 of `setup_voxbox.sh` runs each submodule's setup script. The setup scripts won't fail if the `.env` is missing — they'll just print a reminder. The GUI tile for each tool is gated on the launcher binary existing, **not** on the key being present, so a missing key produces a runtime error rather than a greyed-out tile.

### Gotcha 3 — whisper-diarize needs a Hugging Face token

`whisper-diarize/setup_whisper_diarize.sh` reads `whisper-diarize/.hf_token` (chmod 600, gitignored). If the file doesn't exist, the script prompts interactively. The token must:

1. Have **Read** access ([huggingface.co/settings/tokens](https://huggingface.co/settings/tokens))
2. Be associated with an account that has accepted the pyannote license at [huggingface.co/pyannote/speaker-diarization-3.1](https://huggingface.co/pyannote/speaker-diarization-3.1)

Pre-create the token file when scripting an unattended install:

```bash
echo "hf_xxxxxxxx" > whisper-diarize/.hf_token
chmod 600 whisper-diarize/.hf_token
```

### Gotcha 4 — the parent `./voxbox` launcher is generated, not tracked

`setup_voxbox.sh` writes `./voxbox` at the end. If setup exits early (e.g. submodule install fails) the launcher won't exist. After fixing the underlying issue, either re-run setup or create it manually:

```bash
cat > voxbox <<'LAUNCHER'
#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
exec python3 "$SCRIPT_DIR/voxbox_cli.py" "$@"
LAUNCHER
chmod +x voxbox
```

### Gotcha 5 — the `speech-to-text` submodule has two surfaces

- `transcribe.py` / `transcribe_generic.py` — higher-level pipelines (config files, post-processing, language overrides) intended for direct human use
- `elevenlabs_stt.py` + the `./elevenlabs` launcher — thin SDK wrapper with a CLI matching `assemblyai-stt/assemblyai` (`-f`, `-o`, `--speakers`, etc.). This is what `voxbox_gui.py` calls.

When fixing GUI behaviour for ElevenLabs, edit `elevenlabs_stt.py`. When changing the TTRPG transcription workflow, edit `transcribe.py`.

## GUI quirks

- **macOS aqua ttk theme ignores `padding` on `ttk.Button`.** Mode-picker tiles use plain `tk.Button` with `padx`/`pady` instead. Other buttons in the GUI can stay as `ttk.Button` since their content fits.
- **Window auto-sizes in `main()`** via `update_idletasks()` + `winfo_reqheight()`. Don't hardcode `root.geometry(...)` in `__init__` — different DPI / font scales produce different content heights and a hardcoded value cuts off the last mode tile.

## Commit checklist

See `AGENTS.md` for the full submodule push workflow. Quick reminders:

- Push the submodule first, then the parent (so the parent's gitlink points at a SHA that exists on the remote).
- `git submodule update` leaves submodules on detached HEAD — `git checkout main && git pull --ff-only` inside the submodule before committing.
- Never `git add -A` at the repo root without scanning `git status` first; the data dirs (`inbox/`, `output/`, `processed/`, `transcripts/`) catch real audio + transcripts you don't want in the repo.
- `.env` files are gitignored; double-check before adding anything from a submodule root.

<!-- SYNCED FROM vl-templates/repo-template/CLAUDE.md — DO NOT EDIT BY HAND (run tools/sync_rules.py) -->
## Standing rules

Binding on any agent working in this repo, from day one — these are process rules, not project
conventions, so unlike the section above they ship filled in. **This file is the only source of
truth for them.** They survive into every repo made from this template; delete one only
deliberately, never because it looks like unused scaffolding. This section is synced from
`vl-templates/repo-template/CLAUDE.md` by `tools/sync_rules.py` — edit the template, not a copy of
it, and re-run the sync so the edit reaches every repo that has one. Everything outside the two
HTML comment markers bounding this section is local to this repo and is never touched by a sync.

1. **No agent memory.** Never rely on assistant-side memory, per-project memory files, or recall
   from a previous session. Everything durable lives in the repo: this file, `CHANGELOG.md`, and
   (once Spec Kit is initialized) `.specify/memory/constitution.md` and `specs/`. If something is
   worth remembering, write it here in the same turn you learn it. If a memory and the repo
   disagree, the repo wins.
2. **Spec Kit governs all development.** Every feature flows through
   `/speckit-specify` → (`/speckit-clarify` as needed) → `/speckit-plan` → `/speckit-tasks` →
   (`/speckit-analyze` / `/speckit-checklist` as needed) → `/speckit-implement`. No production code
   is written outside a spec'd, planned, tasked feature. If Spec Kit isn't initialized yet, that is
   the first development step — it is not optional:

   ```bash
   specify init --here --integration claude
   ```

   Then ratify a constitution with `/speckit-constitution` before the first feature. The
   constitution outranks this file on anything about the code itself; these standing rules govern
   process and agent behaviour.
3. **All development happens on a worktree.** Never write code, tests, specs, or plans on a
   checkout of the main branch. Create a worktree with its own branch and work there. Only *repo
   management* belongs outside a worktree: opening and merging PRs, reviewing, tagging, releases,
   branch cleanup, and reading. If you notice you are about to edit a file on main, stop and make a
   worktree first.
4. **Commit every round.** Each round — one user request plus its completion — ends with a git
   commit of whatever that round changed, without waiting to be asked. This includes work that
   isn't a natural "please commit" moment, such as Spec Kit artifacts (`spec.md`, `plan.md`,
   `tasks.md`). Stage specific paths, never `-A`; review what's staged first; new commits only (no
   `--amend` unless asked); no force-push. A pure Q&A round that changes no files has nothing to
   commit.
5. **Refresh `Current status` before each commit.** Update the "Current status" section below —
   including its `Last updated:` date — to match reality as part of the same commit, so the summary
   can never drift from the repo. Check it every round rather than assuming it still holds.
6. **Context & delegation.** Use the `context-preservation` skill to keep long sessions clean, and
   dispatch a **worktree** subagent per phase whenever a phase is self-contained enough to run
   independently (its own branch, its own test run). Typical split: one worktree per Spec Kit phase,
   or per independent task group in `tasks.md`. Judgement call — skip it when the phase is a few
   lines, or when phases touch the same files and would conflict on merge.
7. **Don't narrate no-ops.** A check that came back empty doesn't need a line of output. Report
   what you did and what the user has to decide, not the scaffolding you looked at on the way.
   The recurring offender is Spec Kit's extension-hook check: with no `.specify/extensions.yml`
   — the default — every `/speckit-*` command's hook check is a guaranteed no-op, and the skills
   already say to skip it silently. Do that; don't announce "no hooks configured". If that file
   is ever added, the hooks become real and this rule stops covering them.
8. **CodeGraph is mandatory.** Every repo made from this template runs
   [CodeGraph](https://github.com/colbymchenry/codegraph) — an MCP server that indexes the
   codebase into a knowledge graph so agents get call paths and impact analysis in one tool call
   instead of grepping the tree by hand. Part of first-time repo setup, alongside Spec Kit init:
   install the CLI if missing (`curl -fsSL https://raw.githubusercontent.com/colbymchenry/codegraph/main/install.sh | sh`
   or `npm i -g @colbymchenry/codegraph`), run `codegraph install` once to wire this agent's MCP
   config, then `codegraph init` in the repo root to build the index. It watches files and
   auto-syncs in the background; use `codegraph sync` if it ever needs a manual nudge. Once a
   `.codegraph/` index exists, use the `codegraph_explore` tool for architecture, call-flow, or
   impact-analysis questions instead of manual exploration.
9. **True TDD — red, green, refactor.** No production code without a failing test first. For
   every unit of work: write a test that fails for the right reason (red), write the minimum
   code to make it pass (green), then clean up with the tests still green (refactor). This is
   not a separate phase bolted onto Spec Kit — it happens inside `/speckit-implement`: each
   task's test is written and shown failing before that task's implementation is written.
9b. **Rules 9 and Spec Kit apply whatever door the work came in by.** Board instruction 2026-08-22: *"always spec kit and test driven development even when and even when I'm emailing you and even when I'm driving the session directly from the Claude code desktop interface"*. Work dispatched from a queue item arrives with a spec; work that arrives as an email, a chat message, or the board typing at a session in person does not, and that was never a decision — it is just what happened when work skipped the queue. A rule that binds the slow path and not the fast one binds nothing, because urgent work takes the fast path by definition. A human watching a session is not a substitute for a test: they catch what they happen to look at. Act on what is genuinely urgent, then spec and test the build rather than implementing straight out of an inbox. The exception is the small reversible non-shipping change — a typo, a comment, a note; if a user can see the behaviour change, it is spec'd and tested. See `vl-management/decisions/2026-08-22-spec-kit-and-tdd-are-not-conditional.md`.
10. **Never hard-wrap text meant for a human to read.** No fixed-column line breaks in email bodies, UI copy, generated reports, chat messages, docs prose, or commit-message bodies — one paragraph is one line, and the device does the wrapping. A 72-column break is invisible on the machine that wrote it and looks broken on every phone. Board ruling, 2026-08-17, on receiving a hard-wrapped company email. This does not touch code: source lines, `<pre>` blocks, ASCII tables, and fixed-width terminal output are wrapped for the machine, not the reader, and stay as they are.
11. **Never touch a `.env` file without asking the board.** Not to untrack it, delete it, move it, or rewrite it — bring it to the board and let the board decide, the same standing rule vl-management CLAUDE.md rule 14 states company-wide. The replacement, in the same breath: report what you found, say what reads the file, and post the ask; reading one to classify a key is allowed, changing one is not, and no value ever appears in a report, a commit message, or a prompt. Several repos track a `.env` on purpose — a Vite build inlines publishable keys into the browser bundle at build time, so the tracked file is the only configuration such a build has, and removing it ships a blank page. This is not hypothetical: a security-shaped `.env` change blacked out a live company site for five hours seventeen minutes on 2026-08-26. Before removing a file to satisfy a guard, ask what reads it; if the answer is the build, the removal is an outage.
12. **This file is synced, not just copied.** `tools/sync_rules.py` in `vl-templates` propagates the managed block above (between the two HTML comment markers) into downstream repos' `CLAUDE.md` on demand — creating the file where one doesn't exist, or updating only the managed block where local content exists alongside it. A sync never touches a byte outside the markers. Marker: template-sync-mechanism-2026-09-01. Being synced is not automatic: a repo carries the current rules only once someone has actually run the tool against it since the last template edit, and most of the portfolio has not yet — that rollout is separate, later work, tracked on the queue rather than assumed to have happened.
<!-- END SYNCED BLOCK -->
