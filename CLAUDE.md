# CLAUDE.md

Guidance for Claude Code when working in this repo. **Keep this file current** (see "Standing rules").

## Standing rules

1. **After every change, update this file** if anything it describes changed: commands, structure,
   conventions, env vars, API routes, milestones. Also update `README.md` / `SPEC.md` when behaviour they describe changes.
2. **After every change, commit and push to GitHub `main`:**
   ```sh
   git add -A
   git commit -m "<short, imperative summary>"   # end with the Co-Authored-By line given by the harness
   git push origin HEAD:main
   ```
   - Remote: `origin` = https://github.com/Baran-op/Interview-coach.- (branch `main`).
   - One logical change per commit. Include the CLAUDE.md update in the same commit.
   - Never commit `.env`, `data/`, `*.glb` avatars or anything else in `.gitignore`.
   - If the push is rejected (non-fast-forward), `git pull --rebase origin main`, resolve, push again.
     Never force-push unless the user explicitly says so.

## Project

Local web app for mock interviews: a talking 3D interviewer (Claude-powered) asks questions drawn from a
job description, the user's CV and company notes; the session is recorded and scored afterwards.
Personal use only, localhost, uses the user's Claude subscription (never an API key). See `SPEC.md`.

Status: Milestones 1-5 built (text interviewer, voice, recording/review, 3D avatar, history/packs/timed interviews),
plus the coaching improvements and the voice and face delivery stats (Phase H, H1-H8). Their plans (`PLAN.md`,
`PLAN-energy.md`) are finished and removed; they're in git history. Code comments citing them refer to that history.

## Stack and layout

- `backend/` Python 3.11, FastAPI. `main.py` routes, `brain.py` Claude Agent SDK interviewer,
  `feedback.py` report generation, `categories.py` question categories (fallback from question text, also applied to older reports), `claude_json.py` schema-checked JSON helper (`ask_json`; falls back to parsing the reply text), `prep.py` prep sheet per pack (`source_hash`, `clean_sheet`, one-Claude-call `write` with `prompts/prep.txt`; stored in the `prep` table, feeds drill's `prep` source), `drill.py` drill mode (question list, one-Claude-call scoring with `prompts/drill.txt`, `question_key`), `segments.py` `clean_segments` (validates the posted speech segments; `turns.segments_json`), `delivery.py` per-answer delivery stats (`words_at`/`moment_quote`/`add_quotes` quote what you were saying at a face moment via the turn's segments and `turns.words_json`; word offsets come from `stt.words_from_wav` in the report step (`feedback._fill_words`), not at transcription: word timestamps cost about 0.75 s on a 41 s clip, over the 0.5 s budget), `text_stats`, `audio_stats` from the saved answer WAVs, `read_wav`/`voiced_frames` (shared WAV reader and voiced-frame mask), `voice_stats(samples, rate)` (pitch range in semitones, loudness range, trail-off share, voiced seconds), `voice_flags(voice, baseline)` (flat / lively / trailing against your own usual, fixed thresholds until `db.voice_baseline` has 10 answers), `combine_face` (an answer's turn face stats, frame-weighted), `face_flags(face, baseline)` (looking_down >=30% down, low_eye_contact on-screen <60%, still <0.7x usual with a baseline), `face_moments` (away spans plus 20 s+ still stretches under half your usual), `answer_delivery` adds `delivery` incl. `voice`, `voice_flags`, `voice_usual`, `face` (with `moments`), `face_flags`, `face_usual` to each report answer (the Drill attempt route adds the same, plus `face` from the posted `face`/`segments` with times counted from the start of the answer; quotes via `stt.words_from_wav` only when there are moments), `TARGET_SECONDS`, `session_delivery`: per-session medians for History's "Delivery over time" table), `face.py` (`clean_face`: validates the per-answer `face` the browser posts with a turn, stored in `turns.face_json`), `stt.py` mlx-whisper, `tts.py` Kokoro, `db.py` SQLite (`voice_baseline`, `face_baseline` on expressiveness), `gpu.py`,
  `prompts/` (`interviewer.txt`, `feedback.txt`, `drill.txt`, `prep.txt`).
- `backend/research.py` + `prompts/research.txt`: "Draft from the web" company notes (`POST /research`); the only call with web tools (WebSearch/WebFetch), the interviewer stays tool-less.
- `frontend/` Vite + React + TypeScript. `src/pages` (incl. `Drill.tsx`, route `#/drill/<pack id>?q=<question>`), `src/components` (`Dropdown.tsx`:
  shared listbox + `Chevron`), `src/audio` (Silero VAD, recording), `src/face` (`FaceTracker.ts` MediaPipe face landmarker at 8 fps on the recording camera, `stats.ts` pure per-answer stats; model via `scripts/fetch_face_model.sh`, git-ignored), `src/avatar`
  (three.js + TalkingHead behind `AvatarController.say()`), `src/api.ts`, `src/index.css` (the whole design system).
- `scripts/` hand-run tools. `python -m scripts.backfill_delivery` recomputes delivery (incl. voice and face) for stored reports and drill attempts from the saved WAVs (no Claude calls, idempotent). `python -m scripts.rescore <session_id> --n 3` re-runs the report prompt on a stored transcript (not saved, spends n Claude requests) and prints the score spread; `python -m scripts.voice_stats` prints voice stats for every saved answer WAV (calibration, H2); `feedback.txt` has 1/3/5 anchors per criterion.
- `data/` SQLite db, recordings and per-answer WAVs (`data/answers/<session>/<turn>.wav`) and drill answers (`data/answers/drill/<attempt>.wav`), git-ignored.
- `SPEC.md` the original spec and milestones.

## Commands

```sh
source .venv/bin/activate && uvicorn backend.main:app --port 8000   # backend
cd frontend && npm run dev                                          # frontend, http://localhost:5173
cd frontend && npx tsc -b                                           # type-check frontend
pip install -r backend/requirements-dev.txt && pytest backend/tests  # backend unit tests (pure functions only)
```

## Conventions and gotchas

- `ANTHROPIC_API_KEY` must NOT be set; the backend refuses to start (would bill API instead of the plan).
  Auth is the Claude Code login (`claude login`, browser flow); `CLAUDE_CODE_OAUTH_TOKEN` in `.env` is an optional override.
- The feedback report costs one Claude request per session; filler words, answer length and overall score are computed locally.
- `prompts/interviewer.txt` scripts the whole interview (its `{stage}` block comes from `STAGES` in `brain.py`: screen/full/final, old packs default to full): intro, "tell me about yourself", motivation, main questions by type, candidate questions, close with `[END]`. `prompts/feedback.txt` scores the first two as answers too; keep the two files in step (including the category list), and keep the criteria and anchors in `prompts/drill.txt` identical to `feedback.txt` (a test checks this).
- Session history: `db.pack_report_history` feeds `brain.history_block` (`{history}` in `interviewer.txt`); `feedback._system_prompt` gets the previous session's fixes (`{previous_fixes}`) and the report carries `previous_fixes` statuses. Keep the two prompt files in step.
- Face tracking (Phase H): numbers only, never send or store video frames, never label emotions in UI text. Off when the model is missing, the Setup toggle (`localStorage.faceTracking`) is off, or there is no camera in the recording. Drill opens its own camera (self-view) only when the toggle is on and the model exists, and stops it on leaving the page.
- Keep all avatar interaction going through `AvatarController.say()`.
- UI is monochrome: colours are CSS tokens on `:root` in `index.css` (light + dark via `prefers-color-scheme`);
  red (`--danger`) is reserved for recording and errors, and the per-type History chart keeps its categorical colours.
  Use `<Dropdown>` instead of native `<select>`, inside a `<div className="field">` (not a `<label>`: a label
  re-forwards option clicks to the button). Collapsible sections are `<details className="disclosure">` with a
  `<Chevron />` in the summary.
- Optional env: `WHISPER_MODEL`, `KOKORO_MODEL`, `KOKORO_VOICE`, `INTERVIEWER_MODEL`, `FEEDBACK_MODEL`, `RESEARCH_MODEL`, `IDLE_TIMEOUT_MIN` (default 30).
- Sessions end three ways, all via `finish_session()` in `main.py`: End button, `pagehide` beacon, idle reaper. Ending early asks Score / Discard / Keep going; Discard sends `/end` with `score:false` then `DELETE /sessions/{id}`; the beacon and reaper always score.
  The Interview page keeps the recording blob in memory and `saveSession()` is retryable (Retry / Download buttons).
- Full API table and usage docs live in `README.md`; don't duplicate them here.
