# Interview Coach

A local web app for practising interviews against a Claude-powered interviewer whose
questions come from a real job description, your CV and company notes. See [SPEC.md](SPEC.md).

**Status: Milestone 1 (text interviewer).** You type your answers. Voice, recording, the
feedback report and the 3D avatar come in later milestones.

Personal use only: it runs on localhost with your Claude subscription. Don't deploy it or
share it with other people.

## One-time setup (macOS, Apple Silicon)

1. Install the tools:
   ```sh
   brew install python@3.11 node
   npm install -g @anthropic-ai/claude-code
   ```
2. Create a subscription token and put it in `.env`:
   ```sh
   claude setup-token            # prints a long-lived token
   cp .env.example .env          # then paste it after CLAUDE_CODE_OAUTH_TOKEN=
   ```
   Make sure `ANTHROPIC_API_KEY` is **not** set (`echo $ANTHROPIC_API_KEY` prints nothing).
   If it is set, the backend refuses to start, because it would bill the API instead of
   your plan.
3. Backend dependencies (from the repo root):
   ```sh
   python3.11 -m venv .venv
   source .venv/bin/activate
   pip install -r backend/requirements.txt
   ```
4. Frontend dependencies:
   ```sh
   cd frontend && npm install && cd ..
   ```

## Run

Use two terminals, both started from the repo root:

```sh
# 1. backend on http://localhost:8000
source .venv/bin/activate
uvicorn backend.main:app --port 8000

# 2. frontend on http://localhost:5173
cd frontend && npm run dev
```

Open http://localhost:5173 in Chrome. If the backend can't reach Claude or finds
`ANTHROPIC_API_KEY` set, a red banner appears at the top of the page. You can also check
http://localhost:8000/health directly.

## Using it (Milestone 1)

1. On **Setup**, paste the job description, your CV and any company notes, then choose
   the type, number of questions, difficulty, style and interviewer name.
2. Click **Save pack & start interview**. The pack is saved, so you can start it again
   later from **Saved packs**. Your CV is pre-filled from the latest pack.
3. Answer in the text box and send with **Ctrl/⌘+Enter**. Vague answers get up to 2
   follow-ups. After the last question the interviewer wraps up, and the session closes by
   itself when it says `[END]`.
4. The small chips under each interviewer message show the expression tags parsed from
   the reply. The avatar will use them in Milestone 4.

Sessions, turns and packs are stored in `data/interview.db` (git-ignored).

## API (so far)

| Method | Path | Notes |
|---|---|---|
| GET | `/health` | 503 if `ANTHROPIC_API_KEY` is set or the OAuth token is missing |
| POST | `/packs` | Create a pack |
| GET | `/packs`, `/packs/{id}` | List or load packs |
| POST | `/sessions` | `{pack_id}` → opening line `{session_id, reply_text, expressions[], is_final}` |
| POST | `/sessions/{id}/turn` | `{text}` → `{transcript, reply_text, expressions[], is_final}` (text only for now) |
| POST | `/sessions/{id}/end` | Closes the Claude client |
| GET | `/sessions/{id}/turns` | Stored transcript |

`expressions` is a list of `{tag, char_index}`, where `char_index` is the position in
`reply_text` where the tagged sentence starts.

## Notes

- Each session gets its own `ClaudeSDKClient`, with all built-in tools disabled and your
  local Claude Code settings ignored (`setting_sources=[]`). The client runs in its own
  asyncio task, because the SDK client can't be shared across request tasks.
- Active sessions are kept in memory. If you restart the backend in the middle of an
  interview, that session can't continue: start a new one.
- To pin a model, set `INTERVIEWER_MODEL` in `.env`. Otherwise your plan's default model
  is used.
