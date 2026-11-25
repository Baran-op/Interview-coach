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
Phase I in `PLAN-brief.md` (materials in, interview brief out, so any profession works) is built: I0-I6 and I8,
plus I7's docs. I7's end-to-end check with two fictional packs (about 26 Claude requests) waits for the user's
approval; tick I7 once it has run.
Next: `PLAN-voice.md` (Voice tab in Review: pitch over time, flat stretches, advice in the same report request).
Planned only, nothing built yet (V0-V13).

## Stack and layout

- `backend/` Python 3.11, FastAPI. `main.py` routes, `brain.py` Claude Agent SDK interviewer,
  `feedback.py` report generation, `categories.py` question categories (fallback from question text, also applied to older reports), `claude_json.py` schema-checked JSON helper (`ask_json`; falls back to parsing the reply text), `prep.py` prep sheet per pack (`source_hash(pack, brief)`: today's slot hash with no brief, the brief JSON's SHA-1 with one; `clean_sheet(raw, allowed)`, `wants_stories` (a category hint says STAR), one-Claude-call `write` with `prompts/prep.txt` + `prep_sections.txt` (default) or `prep_sections_brief.txt`; stored in the `prep` table, feeds drill's `prep` source), `drill.py` drill mode (question list with `starter_questions(pack, brief)`, one-Claude-call scoring with `prompts/drill.txt` and the pack's current brief rubric, `build_result` adds the category's target length and a short/long flag, `question_key`), `segments.py` `clean_segments` (validates the posted speech segments; `turns.segments_json`), `delivery.py` per-answer delivery stats (`words_at`/`moment_quote`/`add_quotes` quote what you were saying at a face moment via the turn's segments and `turns.words_json`; word offsets come from `stt.words_from_wav` in the report step (`feedback._fill_words`), not at transcription: word timestamps cost about 0.75 s on a 41 s clip, over the 0.5 s budget), `text_stats`, `audio_stats` from the saved answer WAVs, `read_wav`/`voiced_frames` (shared WAV reader and voiced-frame mask), `voice_stats(samples, rate)` (pitch range in semitones, loudness range, trail-off share, voiced seconds), `voice_flags(voice, baseline)` (flat / lively / trailing against your own usual, fixed thresholds until `db.voice_baseline` has 10 answers), `combine_face` (an answer's turn face stats, frame-weighted), `face_flags(face, baseline)` (looking_down >=30% down, low_eye_contact on-screen <60%, still <0.7x usual with a baseline), `face_moments` (away spans plus 20 s+ still stretches under half your usual), `answer_delivery` adds `delivery` incl. `voice`, `voice_flags`, `voice_usual`, `face` (with `moments`), `face_flags`, `face_usual` to each report answer (the Drill attempt route adds the same, plus `face` from the posted `face`/`segments` with times counted from the start of the answer; quotes via `stt.words_from_wav` only when there are moments), `TARGET_SECONDS`, `session_delivery`: per-session medians for History's "Delivery over time" table), `face.py` (`clean_face`: validates the per-answer `face` the browser posts with a turn, stored in `turns.face_json`), `stt.py` mlx-whisper, `tts.py` Kokoro, `db.py` SQLite (`voice_baseline`, `face_baseline` on expressiveness), `gpu.py`,
  `prompts/` (`interviewer.txt` + `script_conversation.txt` / `script_stations.txt`, `feedback.txt`, `drill.txt`, `prep.txt` + `prep_sections.txt` / `prep_sections_brief.txt`, `brief.txt`).
- `backend/materials.py` pack materials (Phase I1): `KINDS`, `guess_kind`, `synthetic` (a legacy pack's `jd`/`profile`/`company_notes` as up to three read-only materials), `legacy_slots` (default-mode mapping by kind: jd = job+format+other, profile = candidate, company_notes = organisation; one material as is, several with `### <name>` headers; every prompt renderer and `prep.source_hash` read the three slots through it), `hint_texts` (Whisper hint order), `MAX_PACK_CHARS` (150,000). Stored in the `materials` table; `db.get_pack` attaches `materials` (stored rows, [] for a legacy pack), `db.pack_materials` falls back to the synthetic ones.
- `backend/brief.py` + `prompts/brief.txt`: the interview brief (Phase I2). `clean_brief(raw, frozen)` (pure: caps, slugs, `other` always present, 3-6 criteria else the default four, stations sum to `total_minutes`), `source_hash(materials)`, `criteria_hash`, `rubric_hash`/`rubric_of`, `default_brief(pack)` (today's four criteria, eight categories, scoring notes and target seconds, word for word), `render_criteria`, `category_sentence`, `render_context` (the interviewer's view, under 8,000 chars), `meta` (`brief_meta`), one-Claude-call `write`. Stored in the `briefs` table (`origin` generated/edited). `db.frozen_rubric(pack_id)`: once a pack has a ready report its rubric is the latest scored session's (`sessions.brief_json` snapshot, null = default).
- `backend/voice.py` (PLAN-voice.md): pure voice analysis over `delivery.pitch_track(x, rate)` (per-30 ms f0, voiced mask, rms dB; `to_semitones` folds octave errors) and a turn's speech segments: `wav_to_session` / `session_to_wav` / `joins` (V1). Flat sections, evidence and routes land here as the plan's items are built.
- `backend/research.py` + `prompts/research.txt`: "Draft from the web" company notes (`POST /research`); the only call with web tools (WebSearch/WebFetch), the interviewer stays tool-less.
- `frontend/` Vite + React + TypeScript. `src/pages` (incl. `Drill.tsx`, route `#/drill/<pack id>?q=<question>`; `Brief.tsx`, route `#/brief/<pack id>[?generate=1]`: the brief editor, assumptions to confirm, stale notice, Regenerate, freeze warning on a 409), `src/components` (`Dropdown.tsx`:
  shared listbox + `Chevron`; `Materials.tsx`: Setup's materials list), `src/audio` (Silero VAD, recording), `src/face` (`FaceTracker.ts` MediaPipe face landmarker at 8 fps on the recording camera, `stats.ts` pure per-answer stats; model via `scripts/fetch_face_model.sh`, git-ignored), `src/avatar`
  (three.js + TalkingHead behind `AvatarController.say()`), `src/api.ts`, `src/index.css` (the whole design system).
- `scripts/` hand-run tools. `python -m scripts.backfill_delivery` recomputes delivery (incl. voice and face) for stored reports and drill attempts from the saved WAVs (no Claude calls, idempotent). `python -m scripts.rescore <session_id> --n 3` re-runs the report prompt on a stored transcript (not saved, spends n Claude requests) and prints the score spread; `python -m scripts.voice_stats [--json FILE]` prints voice stats for every saved answer WAV (calibration, H2; `--json` writes a before/after snapshot); `feedback.txt` has 1/3/5 anchors per criterion.
- `data/` SQLite db, recordings and per-answer WAVs (`data/answers/<session>/<turn>.wav`) and drill answers (`data/answers/drill/<attempt>.wav`), git-ignored.
- `SPEC.md` the original spec and milestones. `PLAN-brief.md` the interview-brief plan (Phase I) with its build-order checklist. `PLAN-voice.md` the voice-analysis plan with its build-order checklist.

## Commands

```sh
npm run dev                                                         # repo root: frontend :5173 + backend :8000 (Vite plugin in vite.config.ts spawns .venv uvicorn; skipped if :8000 is taken or NO_BACKEND=1)
source .venv/bin/activate && uvicorn backend.main:app --port 8000   # backend on its own
cd frontend && npx tsc -b                                           # type-check frontend
pip install -r backend/requirements-dev.txt && pytest backend/tests  # backend unit tests (pure functions only)
python -m backend.tests.golden.make                                 # regenerate golden prompts (by hand, only on purpose)
```

## Conventions and gotchas

- `ANTHROPIC_API_KEY` must NOT be set; the backend refuses to start (would bill API instead of the plan).
  Auth is the Claude Code login (`claude login`, browser flow); `CLAUDE_CODE_OAUTH_TOKEN` in `.env` is an optional override.
- The feedback report costs one Claude request per session; filler words, answer length and overall score are computed locally.
- `prompts/interviewer.txt` is the frame (`{context}`, `{history}`, `{script}`, how to behave); `{script}` is
  `prompts/script_conversation.txt` (default and conversation/panel briefs: opening/candidate-question flags,
  `{probe_rule}`, `{category_list}`, `{panel}`) or `prompts/script_stations.txt` (stations), rendered in `brain.py`.
  Stations: the interviewer tags the turn opening station N with `[station N]` (stripped by `parse_tags`, like the
  expression tags); `LiveSession` keeps the plan and current station (`brain.current_station`: the tag wins unless
  it overran by 2+ min, else `station_at` from the clock), `turns.station` stores the key, time notes become
  per-station, and the stream emits a `station` event (the Interview page's `StationCard` shows it).
- The default conversation script (its `{stage}` block comes from `STAGES` in `brain.py`: screen/full/final, old packs default to full): intro, "tell me about yourself", motivation, main questions by type, candidate questions, close with `[END]`. `prompts/feedback.txt` scores the first two as answers too; keep the two files in step (including the category list). The criteria and anchors in `prompts/feedback.txt` and `prompts/drill.txt` both come from `brief.render_criteria` (a test checks this).
- Session history: `db.pack_report_history` feeds `brain.history_block` (`{history}` in `interviewer.txt`); `feedback._system_prompt` gets the previous session's fixes (`{previous_fixes}`) and the report carries `previous_fixes` statuses. Keep the two prompt files in step.
- Face tracking (Phase H): numbers only, never send or store video frames, never label emotions in UI text. Off when the model is missing, the Setup toggle (`localStorage.faceTracking`) is off, or there is no camera in the recording. Drill opens its own camera (self-view) only when the toggle is on and the model exists, and stops it on leaving the page.
- Keep all avatar interaction going through `AvatarController.say()`.
- UI is monochrome: colours are CSS tokens on `:root` in `index.css` (light + dark via `prefers-color-scheme`);
  red (`--danger`) is reserved for recording and errors, and the per-type History chart keeps its categorical colours.
  Use `<Dropdown>` instead of native `<select>`, inside a `<div className="field">` (not a `<label>`: a label
  re-forwards option clicks to the button). Collapsible sections are `<details className="disclosure">` with a
  `<Chevron />` in the summary.
- Optional env: `WHISPER_MODEL`, `KOKORO_MODEL`, `KOKORO_VOICE`, `INTERVIEWER_MODEL`, `FEEDBACK_MODEL`, `RESEARCH_MODEL`, `BRIEF_MODEL`, `IDLE_TIMEOUT_MIN` (default 30).
- Sessions end three ways, all via `finish_session()` in `main.py`: End button, `pagehide` beacon, idle reaper. Ending early asks Score / Discard / Keep going; Discard sends `/end` with `score:false` then `DELETE /sessions/{id}`; the beacon and reaper always score.
  The Interview page keeps the recording blob in memory and `saveSession()` is retryable (Retry / Download buttons).
- Rubric (Phase I4): reports and drill results store `criteria`, `criteria_hash` and (reports) `categories`;
  read them only through `brief.report_rubric(report)`, which gives the default four/eight for older ones (nothing is
  migrated). `feedback.txt`/`drill.txt` render their criteria, categories and context from `brief.scoring_values` /
  `scoring_context` (default brief: `legacy_context`, byte-identical). Sessions snapshot their brief in
  `sessions.brief_json` at start (`feedback.session_brief`); the report and `scripts/rescore` score with it. A pack's
  rubric freezes once it has a ready report (`db.frozen_rubric`): PUT 409s without `fresh_start`, POST keeps it unless
  `replace_criteria`. History/Review/Drill compare only equal `criteria_hash` (`DEFAULT_CRITERIA_HASH` is mirrored in
  `frontend/src/api.ts`; a test checks it). `categories.resolve_category(..., allowed)` falls back to `other` when
  intro/motivation aren't allowed; `delivery.answer_delivery(targets=...)` reads the report's category targets.
- Golden prompts: `backend/tests/golden/` holds today's rendered interviewer/feedback/drill/prep prompts and the
  report/drill JSON schemas for two fictional packs (`fixtures.py`); `test_golden.py` compares byte for byte. With no
  brief nothing may change; regenerate with `python -m backend.tests.golden.make` only when a change is intended.
- Full API table and usage docs live in `README.md`; don't duplicate them here.
