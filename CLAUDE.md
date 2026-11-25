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

Status: Milestones 1-5 built (text interviewer, voice, recording/review, 3D avatar, history/packs/timed interviews).
Next: the coaching improvements in `PLAN.md`. Work through its build order, one commit per item, and tick the
item's checkbox in `PLAN.md` in the same commit that builds it.

## Stack and layout

- `backend/` Python 3.11, FastAPI. `main.py` routes, `brain.py` Claude Agent SDK interviewer,
  `feedback.py` report generation, `categories.py` question categories (fallback from question text, also applied to older reports), `claude_json.py` schema-checked JSON helper (`ask_json`; falls back to parsing the reply text), `prep.py` prep sheet per pack (`source_hash`, `clean_sheet`, one-Claude-call `write` with `prompts/prep.txt`; stored in the `prep` table, feeds drill's `prep` source), `drill.py` drill mode (question list, one-Claude-call scoring with `prompts/drill.txt`, `question_key`), `delivery.py` per-answer delivery stats (`text_stats`, `audio_stats` from the saved answer WAVs, `answer_delivery` adds `delivery` to each report answer, `TARGET_SECONDS`), `stt.py` mlx-whisper, `tts.py` Kokoro, `db.py` SQLite, `gpu.py`,
  `prompts/` (`interviewer.txt`, `feedback.txt`, `drill.txt`, `prep.txt`).
- `backend/research.py` + `prompts/research.txt`: "Draft from the web" company notes (`POST /research`); the only call with web tools (WebSearch/WebFetch), the interviewer stays tool-less.
- `frontend/` Vite + React + TypeScript. `src/pages` (incl. `Drill.tsx`, route `#/drill/<pack id>?q=<question>`), `src/audio` (Silero VAD, recording), `src/avatar`
  (three.js + TalkingHead behind `AvatarController.say()`), `src/api.ts`.
- `scripts/` hand-run tools. `python -m scripts.rescore <session_id> --n 3` re-runs the report prompt on a stored transcript (not saved, spends n Claude requests) and prints the score spread; `feedback.txt` has 1/3/5 anchors per criterion.
- `data/` SQLite db, recordings and per-answer WAVs (`data/answers/<session>/<turn>.wav`) and drill answers (`data/answers/drill/<attempt>.wav`), git-ignored.
- `SPEC.md` the original spec and milestones; `PLAN.md` the coaching-improvements plan with its build-order checklist.

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
- Keep all avatar interaction going through `AvatarController.say()`.
- Optional env: `WHISPER_MODEL`, `KOKORO_MODEL`, `KOKORO_VOICE`, `INTERVIEWER_MODEL`, `FEEDBACK_MODEL`, `RESEARCH_MODEL`, `IDLE_TIMEOUT_MIN` (default 30).
- Sessions end three ways, all via `finish_session()` in `main.py`: End button, `pagehide` beacon, idle reaper. Ending early asks Score / Discard / Keep going; Discard sends `/end` with `score:false` then `DELETE /sessions/{id}`; the beacon and reaper always score.
  The Interview page keeps the recording blob in memory and `saveSession()` is retryable (Retry / Download buttons).
- Full API table and usage docs live in `README.md`; don't duplicate them here.
