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

## Stack and layout

- `backend/` Python 3.11, FastAPI. `main.py` routes, `brain.py` Claude Agent SDK interviewer,
  `feedback.py` report generation, `stt.py` mlx-whisper, `tts.py` Kokoro, `db.py` SQLite, `gpu.py`,
  `prompts/` (`interviewer.txt`, `feedback.txt`).
- `frontend/` Vite + React + TypeScript. `src/pages`, `src/audio` (Silero VAD, recording), `src/avatar`
  (three.js + TalkingHead behind `AvatarController.say()`), `src/api.ts`.
- `data/` SQLite db and recordings (git-ignored).

## Commands

```sh
source .venv/bin/activate && uvicorn backend.main:app --port 8000   # backend
cd frontend && npm run dev                                          # frontend, http://localhost:5173
cd frontend && npx tsc -b                                           # type-check frontend
```

## Conventions and gotchas

- `ANTHROPIC_API_KEY` must NOT be set; the backend refuses to start (would bill API instead of the plan).
  Auth is `CLAUDE_CODE_OAUTH_TOKEN` in `.env`.
- The feedback report costs one Claude request per session; filler words, answer length and overall score are computed locally.
- Keep all avatar interaction going through `AvatarController.say()`.
- Optional env: `WHISPER_MODEL`, `KOKORO_MODEL`, `KOKORO_VOICE`, `INTERVIEWER_MODEL`, `FEEDBACK_MODEL`.
- Full API table and usage docs live in `README.md`; don't duplicate them here.
