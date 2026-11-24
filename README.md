# Interview Coach

A local web app for practising interviews against a Claude-powered interviewer whose
questions come from a real job description, your CV and company notes. See [SPEC.md](SPEC.md).

**Status: Milestone 3 (recording and review).** The interviewer speaks (Kokoro) and you
answer out loud (Silero VAD in the browser, then Whisper). The session is recorded, and
afterwards you get a Review page: playback with question markers, the transcript and a
scored feedback report. The 3D avatar comes in Milestone 4.

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
   python -m spacy download en_core_web_sm
   ```
   Note that `mlx-whisper` installs PyTorch as a dependency (used only by its
   model-conversion scripts). It takes disk space but is never loaded.
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

**First start:** the backend downloads whisper-small.en and Kokoro-82M (a few hundred MB
in total) from Hugging Face into `~/.cache/huggingface`, then loads them in the background.
`/health` shows `"voice_ready": true` once both are loaded. Later starts need no internet except for Claude. If you start an interview
before voice is ready, that session runs in text mode.

Use headphones: the mic is switched off while the interviewer talks, but speakers can
still bleed into your answer.

## Using it

1. On **Setup**, paste the job description, your CV and any company notes, then choose
   the type, number of questions, difficulty, style, interviewer name and **voice**
   (US or UK English, female or male).
2. Click **Save pack & start interview**. Chrome asks for the microphone the first time.
   The pack is saved, so you can start it again later from **Saved packs**. Your CV is
   pre-filled from the latest pack.
3. The interviewer greets you and asks the first question. When the dot turns blue it's
   your turn: answer out loud. Your turn ends when:
   - you stay silent for 2 s (adjustable: 1.5-3 s), or
   - you press **Done**, or
   - you **hold Space** while talking (pauses don't end the turn) and release it to send.
4. **Pause** freezes the interviewer or your answer (what you said so far is kept).
   **Repeat question** replays the last thing the interviewer said. **End interview**
   stops at any time. You can still type an answer in the box (Ctrl/⌘+Enter).
5. Under the controls, *Last reply* shows how long it took from when you stopped talking
   until the interviewer's voice started, split into the silence window and processing.
   The Milestone 2 target is under 4 s.

The chips under each interviewer message show the expression tags parsed from the reply.
The avatar will use them in Milestone 4.

### Recording and review

- Choose **Record the session** on Setup: *Webcam + audio* (default), *Audio only* or
  *Don't record*. The recording mixes your mic with the interviewer's voice. While
  recording, a **● REC** badge and a small self-view are shown. Pausing the interview also
  pauses the recording.
- When the interview ends (the interviewer says goodbye, or you press **End interview**),
  the recording is uploaded and the **Review** page opens at `#/review/<session id>`. You
  can bookmark it, and recent sessions are listed on the Setup page.
- **Review** has:
  - the recording, with Q1, Q2… markers that jump to each question;
  - the transcript (click a line to jump there);
  - the feedback report: overall score, the top 3 things to fix, filler words, average
    answer length, and for each main question scores from 1 to 5 on relevance, structure
    (STAR), specificity and evidence, with tips and a stronger model answer;
  - downloads of the recording (.webm) and the report (.md).
- **The report takes one Claude request per session.** Claude does the judging (scores, tips,
  model answers). Filler words, answer length and the overall score are computed locally, so
  they're consistent between sessions. The overall score is the average of the answer scores.
  Model answers use only facts from your answers and CV: anything missing appears as a
  placeholder like `[% improvement]`. If a report fails, the Review page has a **Try again**
  button, which costs one more request.
- To help count fillers, Whisper is prompted to keep "um"/"uh" instead of cleaning them up.

Packs, sessions, turns (with timings) and reports are stored in `data/interview.db`, and
recordings in `data/recordings/` (git-ignored). A webcam recording is roughly 7-8 MB per
minute.

### Tuning

Optional `.env` settings:

| Variable | Default | |
|---|---|---|
| `WHISPER_MODEL` | `mlx-community/whisper-small.en-mlx` | Try `mlx-community/whisper-large-v3-turbo` if accuracy is poor (slower, uses more memory) |
| `KOKORO_MODEL` | `mlx-community/Kokoro-82M-bf16` | |
| `KOKORO_VOICE` | `af_heart` | Default voice for packs that don't set one |
| `INTERVIEWER_MODEL` | your plan's default | Pin the Claude model |
| `FEEDBACK_MODEL` | same as the interviewer | Model for the feedback report |

Words missing from Kokoro's dictionary (often company names) are spelled out letter by
letter. For proper pronunciation, `brew install espeak-ng`: Kokoro then uses espeak for
those words automatically.

## API (so far)

| Method | Path | Notes |
|---|---|---|
| GET | `/health` | Claude auth plus the Whisper/Kokoro load state. 503 if `ANTHROPIC_API_KEY` is set or the token is missing |
| GET | `/voices` | Kokoro voices offered in Setup |
| POST | `/packs` | Create a pack |
| GET | `/packs`, `/packs/{id}` | List or load packs |
| POST | `/sessions` | `{pack_id}` → streams the opening line (see below) |
| POST | `/sessions/{id}/turn` | Multipart `audio` (WAV) or JSON `{text}` → streams the reply |
| POST | `/sessions/{id}/end` | `{timeline:[{turn_idx,t_start_ms,t_end_ms}]}`: closes the Claude client, stores turn timings, starts the report |
| POST | `/sessions/{id}/recording` | Multipart `recording` (.webm) |
| GET | `/sessions/{id}/recording` | The recording (range requests supported for seeking; `?download=1` to save) |
| GET | `/sessions/{id}/report` | `{status: pending/ready/error, report, report_md, error}` |
| POST | `/sessions/{id}/report` | Write the report again (one more Claude request) |
| GET | `/sessions/{id}/report.md` | Report as a Markdown download |
| GET | `/sessions`, `/sessions/{id}` | Recent sessions; one session with its pack, turns and report status |
| GET | `/sessions/{id}/turns` | Stored transcript |

`/sessions` and `/turn` respond with NDJSON (one JSON object per line), so the first
sentence can play while Claude is still writing the rest:

```
{"type":"session","session_id":"…"}                          /sessions only
{"type":"transcript","text":"…","stt_ms":412,"turn_idx":1}    /turn only
{"type":"sentence","index":0,"text":"…","expressions":[{"tag":"smile","char_index":0}],
 "audio_wav_base64":"…","duration_ms":2280,"word_timings":[{"word":"Hi","start_ms":0,"end_ms":228}],"tts_error":null}
{"type":"done","turn_idx":2,"reply_text":"…","expressions":[…],"is_final":false,"timings":{"first_sentence_ms":1650,"total_ms":2900}}
{"type":"error","message":"…"}                                instead of done
```

In `sentence` events, `char_index` is relative to that sentence. In `done`, it's relative
to the whole `reply_text`. `word_timings` come from Kokoro's own duration predictions, and
are estimated from word length only when those are missing.

## Notes

- Each session gets its own `ClaudeSDKClient`, with all built-in tools disabled and your
  local Claude Code settings ignored (`setting_sources=[]`). The client runs in its own
  asyncio task, because the SDK client can't be shared across request tasks.
- Whisper and Kokoro run on a single worker thread, one job at a time, so they never compete
  for the GPU. While Claude writes sentence 2, Kokoro is already voicing sentence 1.
- The voice activity detector's files (Silero model, onnxruntime WASM) are served by a small
  Vite plugin from `node_modules` at `/vad/`, so nothing is fetched from a CDN.
- Active sessions are kept in memory. If you restart the backend in the middle of an
  interview, that session can't continue: start a new one.
- To pin a model, set `INTERVIEWER_MODEL` in `.env`. Otherwise your plan's default model
  is used.
