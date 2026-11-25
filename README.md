# Interview Coach

A local web app for practising interviews against a Claude-powered interviewer whose
questions come from a real job description, your CV and company notes. See [SPEC.md](SPEC.md).

**Status: all five milestones built.** A 3D interviewer (three.js + TalkingHead) speaks with
Kokoro's voice, lip-synced and with facial expressions. You answer out loud (Silero VAD in
the browser, then Whisper). The session is recorded, and afterwards you get a Review page:
playback with question markers, the transcript and a scored feedback report. History tracks
your scores across re-runs of each interview pack.

Personal use only: it runs on localhost with your Claude subscription. Don't deploy it or
share it with other people.

## One-time setup (macOS, Apple Silicon)

1. Install the tools:
   ```sh
   brew install python@3.11 node
   npm install -g @anthropic-ai/claude-code
   ```
2. Sign in with your Claude subscription (opens the browser; skip if you already use Claude Code):
   ```sh
   claude login
   ```
   No token is needed. If you can't use the browser login, run `claude setup-token`, copy
   `.env.example` to `.env` and set `CLAUDE_CODE_OAUTH_TOKEN=` to the token it prints.
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
5. The avatar (optional; without it you get a plain "speaking" indicator):
   - Create an avatar at [avaturn.me](https://avaturn.me) (free for personal use). Use a
     **Type-2 (T2)** avatar and export it as **.glb**. T2 exports include the ARKit
     blendshapes and Oculus visemes that TalkingHead needs. A Ready Player Me avatar
     exported with `morphTargets=ARKit,Oculus Visemes` also works.
   - Save it as `frontend/public/avatars/interviewer.glb`. Avatar files are git-ignored
     because they're built from your photo.
   - The avatar's body type (for gestures) follows the gender of the voice chosen in Setup.
6. Face tracking (optional; eye contact and expressiveness per answer, computed in the browser):
   ```sh
   scripts/fetch_face_model.sh
   ```
   Downloads the MediaPipe face model (about 4 MB) to `frontend/public/models/` and copies the WASM
   runtime to `frontend/public/mediapipe/`, so it works offline. Both folders are git-ignored. Without
   them the Setup toggle "Track eye contact and expression" is greyed out and everything else works.
   It needs the webcam in the recording (*Webcam + audio* or *Avatar and webcam side by side*). Video
   frames never leave the browser and are never stored; only a few numbers per answer are (`turns.face_json`). The listening step also stores the session-clock times of each speech segment kept for an answer (`turns.segments_json`), so moments can quote what you were saying.
   The browser console logs the tracker's ms per frame every 10 s.

## Run

From the repo root, one terminal:

```sh
npm run dev
```

This starts the frontend on http://localhost:5173 and the backend on http://localhost:8000, using
`.venv` (no need to activate it). Backend log lines are prefixed `[backend]`. Ctrl+C stops both.
If something is already listening on :8000 (for example a backend you started by hand), it is left
alone and only the frontend starts. `NO_BACKEND=1 npm run dev` starts the frontend only.
`cd frontend && npm run dev` does the same as the root command.

To run them separately instead:

```sh
source .venv/bin/activate && uvicorn backend.main:app --port 8000   # backend
cd frontend && NO_BACKEND=1 npm run dev                              # frontend
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

1. On **Setup**, add your **materials**: upload files (.pdf, .txt or .md, several at once), paste text, or
   draft company notes from the web. Anything goes: the job advert, your CV, company notes, a person
   specification or mark scheme, a description of the interview format. Each material has a name and a
   **kind** (job, about you, organisation, format, other), guessed from the file name; change it if the
   guess is wrong. A pack holds up to 150,000 characters of text (the running total is shown); only the
   extracted text is kept, never the file. Then choose the type, number of questions, difficulty, style,
   interviewer name and **voice** (US or UK English, female or male).
2. Click **Save pack**. For a new pack Setup then offers **Write the interview brief (1 Claude request)**
   or **Skip: use the standard interview** (see "The interview brief" below). Chrome asks for the microphone the first time.
   The pack is saved, so you can start it again later from **Saved packs**. A new pack starts
   with copies of the latest pack's "about you" materials (your CV).
3. The interviewer greets you and asks the first question. When the dot turns blue it's
   your turn: answer out loud. Your turn ends when:
   - you stay silent for 2 s (adjustable: 1.5-5 s, or "only when I press Done"), or
   - you press **Done**, or
   - you **hold Space** while talking (pauses don't end the turn) and release it to send.
4. **Pause** freezes the interviewer or your answer (what you said so far is kept).
   **Repeat question** replays the last thing the interviewer said. **End interview**
   stops at any time. You can still type an answer in the box (Ctrl/⌘+Enter).
5. Under the controls, *Last reply* shows how long it took from when you stopped talking
   until the interviewer's voice started, split into the silence window and processing.
   The Milestone 2 target is under 4 s.

The chips under each interviewer message show the expression tags parsed from the reply.

### The avatar

- It is framed head-and-shoulders against a plain wall. It lip-syncs every sentence using
  Kokoro's own word timings, and each expression tag fires when its sentence starts:

  | Tag | Avatar |
  |---|---|
  | `[neutral]` | neutral mood |
  | `[smile]` | happy mood |
  | `[thinking]` | brief look up/away (🤔), neutral mood |
  | `[nod]` | head nod |
  | `[curious]` | raised brows, slight head tilt |
  | `[serious]` | neutral mood, steady eye contact |

- While you talk, it blinks, moves a little, keeps eye contact and nods now and then.
- **Pause** freezes the avatar and its audio together, so lip-sync stays aligned.
- Everything goes through one `AvatarController.say()` (`frontend/src/avatar/Avatar.tsx`),
  so a different avatar technology can replace it later without touching the rest.

### Recording and review

- Choose **Record the session** on Setup: *Webcam + audio* (default), *Avatar + audio*,
  *Avatar and webcam side by side*, *Audio only* or *Don't record*. If the avatar or
  camera is missing, it falls back to whatever is available and tells you. The recording mixes your mic with the interviewer's voice. While
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
    (STAR), specificity and evidence, a delivery line (length against the target for the question type, words per minute, I vs we, numbers, fillers, hedges, long pauses, and voice flags: flat, lively or trailing off, against your own usual) with tips and a stronger model answer;
  - downloads of the recording (.webm) and the report (.md).
- **The report takes one Claude request per session.** Claude does the judging (scores, tips,
  model answers). Filler words, answer length and the overall score are computed locally, so
  they're consistent between sessions. The overall score is the average of the answer scores.
  Model answers use only facts from your answers and CV: anything missing appears as a
  placeholder like `[% improvement]`. If a report fails, the Review page has a **Try again**
  button, which costs one more request.
- **Sessions build on each other.** A new session of a pack is told (privately) what earlier non-partial sessions asked and scored, so it re-tests your weakest area with a new question and doesn't repeat questions that scored 4 or more. The report has a "Since last time" section saying whether the previous session's top fixes improved, partly, not yet or weren't tested. No extra requests.
- To help count fillers, Whisper is prompted to keep "um"/"uh" instead of cleaning them up.

Packs, sessions, turns (with timings) and reports are stored in `data/interview.db`, and
recordings in `data/recordings/` and spoken answers as WAVs in `data/answers/<session>/<turn>.wav`
(about 2 MB per answered minute; both git-ignored). A webcam recording is roughly 7-8 MB per
minute.

### The interview brief

A pack's **interview brief** (**Interview brief** next to Prep on a saved pack, `#/brief/<pack id>`) says what
the interview is and how it is scored, so the app works for any profession, not only corporate job interviews.
One Claude request reads your materials and writes:

- **Format**: a conversation, timed **stations** (each with its minutes, category and an optional scenario the
  interviewer reads out) or a **panel** (2 to 4 named members, all played by the one avatar and voice); total
  minutes; whether it opens with "tell me about yourself" and ends with your questions.
- **Criteria** (3 to 6, each scored 1 to 5 with 1/3/5 anchors): from your mark scheme when you added one
  (with how its scale maps onto 1-5), otherwise the app's standard four, word for word.
- **Categories** of question, each with the expected shape of an answer, an optional extra scoring rule and
  a target answer length.
- What they'll probe (competencies, likely questions, gaps), organisation facts from your materials, and
  a summary and a factual list of your background.

How the format runs:

- **Conversation**: today's interview (opening, motivation, main questions by type, your questions, close).
  With a brief, the interviewer reads the brief instead of your raw materials, skips "tell me about
  yourself" or your questions when the brief turns them off, and probes the brief's listed gaps.
- **Stations**: a welcome, then each station in order. The interviewer opens each one with a hidden
  `[station N]` tag (never spoken), reads its scenario out (or sets one up), follows up for the station's
  time, then says time is up and moves on. Each of your answers carries a hidden note such as
  "(Time: station 2 of 3, 7 of 8 min used; 18 of 30 min overall.)"; if the interviewer forgets a tag the
  station comes from the clock. The report has one entry per station reached. Setup hides type, stage and
  length (the brief sets them) and the timer counts to the stations' total.
- **Panel**: the conversation, with the members introduced at the start and each leading the questions
  in their focus area, all in the one voice.

Anything Claude guessed rather than read is listed under **To confirm** with a question. Answer it (your
answers are sent along when you regenerate) or confirm it; the count shows on the pack in Setup. Everything
is editable and saving is free. When your materials change, the page says so: **Regenerate** (1 request) or
**Keep it**. Once a pack has a scored session its criteria and categories are frozen: changing them asks
first, because History then only compares sessions scored the same way. **Use the standard interview**
deletes the brief and goes back to today's standard interview.

### Packs and history

- An **interview pack** is a saved role: its materials (job description, CV, company notes and anything
  else) and options (type, stage, length, difficulty, style, interviewer name, voice). You can run the same
  pack as often as you like.
- **Length** is either a number of main questions or a number of minutes. In a timed
  interview the timer shows `elapsed / total`. Each of your answers reaches the interviewer
  with a hidden time note, so it can pace itself and wrap up on time; the note isn't saved
  in your transcript.
- **History** (top right) lists each pack with:
  - your number of sessions, latest and best score, and change since the first session
    (sessions with fewer than 3 scored answers are marked "partial" and left out of these stats);
  - a chart of the overall score per session (hover for the per-criterion breakdown,
    click a point to open that review), which can switch to one line per question type;
  - a "By question type" table (type, answers, first, latest and best score; partial sessions
    left out). Each scored answer carries a category (intro, motivation, behavioural, technical,
    case, role-play, logistics, other) and a competency, shown as a chip on the Review page;
  - a collapsed "Delivery over time" table (median pitch range, trailing-off share and eye contact per session;
    partial sessions left out, a dash where a session has no voice or face data);
  - a table of every session: overall score, each criterion, filler words and average
    answer length.
  - Each report and drill attempt stores the criteria and categories it was scored with. History, the
    Review page's "compared with your previous attempt" and Drill's attempt list only compare sessions
    scored with the same criteria as the latest one; older ones are listed under "Scored with earlier
    criteria" (greyed out as "earlier criteria" in Drill). A brief's own question types are drawn as muted
    dashed lines in the chart. Every session snapshots the brief it ran with, so editing the brief later
    never changes how an old session is scored (Regenerate report uses the snapshot).

  From there you can **Run again**, **Edit** or **Delete** a pack, and open or delete
  sessions. Deleting also removes the recordings.
- The Review page compares each report with your **previous attempt** at the same pack
  (overall score, each criterion, filler words; partial sessions are skipped), and has **Run this pack again**.
- **Prep sheet** (`#/prep/<pack id>`, **Prep** button in Setup's saved packs and History): likely questions, CV against the job (every requirement with CV evidence or marked missing), 6-8 STAR stories built only from your CV (with [placeholders]) and questions to ask. Each likely question has a **Practise** button that opens Drill, and the questions also join the Drill list. Writing or rewriting costs one Claude request; the page warns when the pack changed since the sheet was written. Download as Markdown.
- **Drill** (`#/drill/<pack id>?q=<question>`): practise one question at a time. Open it with the
  **Drill** button in Setup (saved packs) or History, or **Practise this question** under an answer
  in Review. The left list has starter questions, weak questions from your reports (marked "weak")
  and your own, each with best and latest score chips. Hear the question, then answer by voice
  (Done-only: pauses never end it, press Done) or typed. **Each attempt uses one Claude request**
  (the page says so). The result shows score bars, tips, "Better than last time" (from the second
  attempt) and a collapsed "Show a stronger answer", which appears only after you have attempted.
  The attempt list shows each average, its change since the previous attempt, pitch range and eye contact.
  With the Setup face toggle on and the face model installed, Drill opens the camera (small self-view for framing; released when you leave the page) and
  adds eye contact, flags and timed moments (time into the answer plus what you were saying, no play button: Drill records no video) to spoken attempts. If the camera is denied, Drill carries on without it.
- The Markdown report download ends with the full, timestamped transcript.

### Tuning

Optional `.env` settings:

| Variable | Default | |
|---|---|---|
| `WHISPER_MODEL` | `mlx-community/whisper-small.en-mlx` | Try `mlx-community/whisper-large-v3-turbo` if accuracy is poor (slower, uses more memory) |
| `KOKORO_MODEL` | `mlx-community/Kokoro-82M-bf16` | |
| `KOKORO_VOICE` | `af_heart` | Default voice for packs that don't set one |
| `INTERVIEWER_MODEL` | your plan's default | Pin the Claude model |
| `RESEARCH_MODEL` | your plan's default | Model for "Draft from the web" |
| `IDLE_TIMEOUT_MIN` | `30` | Interviews idle this long are ended and scored automatically (`0` disables) |
| `FEEDBACK_MODEL` | same as the interviewer | Model for the feedback report |
| `BRIEF_MODEL` | `FEEDBACK_MODEL`, then the interviewer's | Model for writing the interview brief |

To check how steady the report's scores are, run `python -m scripts.rescore <session_id> --n 3`
(from the repo root, venv active). It re-runs the report on a stored transcript without saving
anything and prints the spread per answer and criterion (targets: 0.3 overall, 0.5 per answer).
Each run is one Claude request, so use it sparingly.

Voice flags (flat, lively, trailing off) compare each answer with your own usual, taken from your newest
40 answers once there are 10; until then fixed thresholds apply. After upgrading, run
`python -m scripts.backfill_delivery` once to add voice stats to existing reports and drill attempts from
their saved answer audio and stored face stats. It never calls Claude and can be re-run.

Face flags (mostly looking down, low eye contact, still face) show in Review next to each answer's eye contact
percentage and in the Markdown download. Looking down and low eye contact use fixed limits (30% and 60%); still
face compares with your own usual expressiveness once 10 answers have it. Long look-aways and still stretches are
listed under each answer with a play button and the words you were saying at that point (typed answers and older sessions have no quote), and shaded on the recording's timeline. Face data exists only for
sessions recorded with the camera tracking on; other sessions show no face line.

Words missing from Kokoro's dictionary (often company names) are spelled out letter by
letter. For proper pronunciation, `brew install espeak-ng`: Kokoro then uses espeak for
those words automatically.

## API (so far)

| Method | Path | Notes |
|---|---|---|
| GET | `/health` | Claude auth plus the Whisper/Kokoro load state. 503 if `ANTHROPIC_API_KEY` is set or the token is missing |
| GET | `/voices` | Kokoro voices offered in Setup |
| POST | `/extract-text` | Multipart `files` (several; `file` also works): `.pdf`, `.txt`, `.md`, max 10 MB each and 30 MB per batch. Returns `[{name, chars, text} or {name, error}]`, one per file (no OCR) |
| POST | `/packs` | Create a pack: `{title, role, company, materials: [{name, kind, source, text}], options}` (`kind` job/candidate/organisation/format/other, `source` paste/pdf/text_file/research). An old client may send `jd`/`profile`/`company_notes` instead. 422 without any text, 413 over 150,000 characters |
| GET | `/packs`, `/packs/{id}` | List or load packs. `/packs/{id}` adds `materials` (a pack saved before materials existed shows its old fields as up to three `synthetic: true` materials) and `brief_meta` (`{exists, kind, total_minutes, stations: [{name, minutes}], stale, to_confirm}`) |
| POST | `/sessions` | `{pack_id}` → streams the opening line (see below) |
| POST | `/sessions/{id}/turn` | Multipart `audio` (WAV) or JSON `{text}`, plus optional `face` (JSON string / key: per-answer face stats, validated and stored in `turns.face_json`) and, with audio, `segments` (JSON list of `{start_ms, end_ms}` speech segments on the session clock, validated and stored in `turns.segments_json`) → streams the reply |
| POST | `/sessions/{id}/end` | `{timeline:[{turn_idx,t_start_ms,t_end_ms,t_listen_ms?}], score?:true}`: closes the Claude client, stores turn timings, starts the report (not with `score:false`, used before discarding). Also sent by the browser on tab close, and by the server for idle interviews |
| POST | `/sessions/{id}/recording` | Multipart `recording` (.webm) |
| GET | `/sessions/{id}/recording` | The recording (range requests supported for seeking; `?download=1` to save) |
| GET | `/sessions/{id}/report` | `{status: pending/ready/error, report, report_md, error}` |
| POST | `/sessions/{id}/report` | Write the report again (one more Claude request) |
| GET | `/sessions/{id}/report.md` | Report as a Markdown download |
| GET | `/sessions`, `/sessions/{id}` | Recent sessions; one session with its pack, turns and report status |
| DELETE | `/sessions/{id}` | Delete a session with its transcript, report and recording |
| PUT, DELETE | `/packs/{id}` | Edit a pack (same body as POST; `materials` replaces the pack's materials and leaves the old text columns untouched); delete it with all its sessions, materials and recordings |
| GET | `/packs/{id}/brief` | The interview brief: `{brief, is_default, stale, frozen, scored_sessions, origin, updated_at}`. With none saved, the default brief (today's standard interview) with `is_default: true`. `stale`: the materials changed since it was generated; `frozen`: the pack has scored sessions, so its criteria and categories are locked |
| POST | `/packs/{id}/brief` | Write or rewrite the brief from the materials (one Claude request, no tools). Body `{replace_criteria?: bool}`; on a frozen pack the criteria and categories are kept unless it is true. Your answers to the previous brief's questions are sent along |
| PUT | `/packs/{id}/brief` | Save your edits (no Claude request). Body `{brief, fresh_start?: bool}`; 409 when the criteria or categories of a frozen pack change without `fresh_start: true` |
| DELETE | `/packs/{id}/brief` | Back to the standard interview (the default brief) |
| GET | `/packs/{id}/history`, `/history` | Finished sessions with overall and per-criterion scores (`criteria`, plus `criteria_hash`, `criteria_names` and `category_labels` from each report's own rubric), fillers and answer length |
| GET | `/sessions/{id}/turns` | Stored transcript |
| GET | `/packs/{id}/drill` | Drill questions: `{questions:[{key, question, category, source: starter/report/prep/custom, attempts, latest, best}]}` (starters, report questions averaging 2.5 or less, the prep sheet's likely questions, then your own) |
| GET | `/packs/{id}/prep` | The pack's prep sheet: `{prep: {likely_questions, gaps, stories, questions_to_ask} or null, created_at, stale}`; `stale` is true when the JD, CV or company notes changed since it was written |
| POST | `/packs/{id}/prep` | Write or rewrite the prep sheet (one Claude request, no tools); returns the same shape |
| POST | `/packs/{id}/drill/attempts` | Score one answer (one Claude request): multipart `audio` (WAV) + `question`, `category`, `seconds`, or JSON `{question, category, text, seconds?}`. Returns `{attempt, previous}`; the attempt's `result` has `scores`, `average`, `tips`, `improved`, `better_answer`, `delivery` (with `voice`, `voice_flags`, `voice_usual` when audio was sent, and `face`, `face_flags`, `face_usual` when the multipart also has `face`; optional `segments` give the quotes. Times in `face` and `segments` count from the start of the answer) |
| GET | `/packs/{id}/drill/attempts?key=` | That question's attempts, oldest first |
| POST | `/research` | `{company, role?, jd?}` -> `{notes, sources}`: one Claude request with WebSearch/WebFetch drafts company notes (nothing saved; ~45 s). Setup adds the result as an organisation material "Web research: <company>" with the sources appended |
| POST | `/tts` | `{text, voice?}` -> `{sentences:[...]}`, each shaped like the NDJSON `sentence` event (reads a question aloud) |

`/sessions` and `/turn` respond with NDJSON (one JSON object per line), so the first
sentence can play while Claude is still writing the rest:

```
{"type":"session","session_id":"…"}                          /sessions only
{"type":"transcript","text":"…","stt_ms":412,"turn_idx":1}    /turn only
{"type":"sentence","index":0,"turn_idx":2,"text":"…","expressions":[{"tag":"smile","char_index":0}],
 "audio_wav_base64":"…","duration_ms":2280,"word_timings":[{"word":"Hi","start_ms":0,"end_ms":228}],"tts_error":null}
{"type":"done","turn_idx":2,"reply_text":"…","expressions":[…],"is_final":false,"timings":{"first_sentence_ms":1650,"total_ms":2900}}
{"type":"error","message":"…"}                                instead of done
{"type":"station","index":1,"number":2,"of":3,"key":"ethics","name":"Ethics","minutes":8,"scenario":"…"}
                                                              stations briefs: before the sentence that opens a station
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
- The avatar's lip-sync module is imported directly (TalkingHead's own runtime `import()`
  doesn't survive bundling). A dev-only `window.__avatar` hook helps with debugging.
- The voice activity detector's files (Silero model, onnxruntime WASM) are served by a small
  Vite plugin from `node_modules` at `/vad/`, so nothing is fetched from a CDN.
- Active sessions are kept in memory. If you restart the backend in the middle of an
  interview, that session can't continue: start a new one.
- To pin a model, set `INTERVIEWER_MODEL` in `.env`. Otherwise your plan's default model
  is used.
