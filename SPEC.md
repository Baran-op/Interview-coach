# Interview Coach — Spec

## Overview

A local web app on my Mac that runs realistic mock interviews: a talking 3D interviewer asks questions tailored to a job description, my profile and the company, records the session, and scores my answers afterwards.

## Goals

- Practise interviews out loud with a face on screen, not a chat box
- Questions grounded in the real job description, my CV and company notes
- A recording plus written feedback after every session

## Constraints

- Runs on a MacBook M1 with 8 GB RAM, offline except for Claude
- No paid voice or avatar services: open-source models only
- The brain is my Claude subscription through the Claude Agent SDK, not a pay-as-you-go API key
- Personal use only: runs on localhost, no other users, never deployed publicly (subscription credentials can't be used on behalf of other people)

Out of scope for v1: user accounts, cloud hosting, photoreal video avatars, voice cloning, mobile app.

## Architecture

Each turn: VAD cuts my answer, Whisper transcribes it, Claude writes the next line with expression tags, Kokoro voices it, and the avatar speaks it while the recorder captures both sides. When the interview ends, one more Claude call turns the transcript into the feedback report.

## Tech stack

Everything except Claude runs locally and costs nothing; memory budget for the models is about 1.5 GB.

| Layer | Choice | Why | Approx. RAM |
|---|---|---|---|
| Frontend | Vite + React + TypeScript | Simple local dev server, good for audio/3D | Browser |
| Backend | Python 3.11 + FastAPI + uvicorn | Runs the Agent SDK, Whisper and Kokoro in one process | ~200 MB |
| Brain | Claude Agent SDK (`claude-agent-sdk`), signed in with my subscription via `claude setup-token` | Uses my plan, not API credits | Negligible (runs the Claude Code CLI) |
| Speech-to-text | mlx-whisper, model whisper-small.en (upgrade to large-v3-turbo if accuracy is poor) | Runs on the M1 GPU via MLX | ~500 MB |
| Text-to-speech | Kokoro-82M via mlx-audio | Natural voice, tiny, Apache 2.0, Metal GPU path | ~400 MB |
| Avatar | three.js + TalkingHead library, a .glb head from Avaturn with ARKit blendshapes + visemes | Real-time lip-sync, moods, gestures, free | GPU / browser |
| Recording | Browser MediaRecorder (webcam + mic + interviewer audio mixed) | No extra software | Browser |
| Storage | SQLite (sqlite3) + files in `data/` | Zero setup | Negligible |
| Voice activity detection | @ricky0123/vad-web (Silero VAD in browser) | Detects when I stop talking | Browser |

## Features and user flow

A session has three screens: Setup, Interview and Review.

1. **Setup screen**
   - Materials: any number of named texts, each with a kind (job, about me, organisation, format, other), uploaded (PDF, .txt, .md, several at once), pasted or drafted from the web. Up to 150,000 characters per pack. (Before Phase I there were three fixed boxes: job description, CV, company notes; packs from then show as three materials.)
   - My CV is reused: a new pack starts with the latest pack's "about me" materials
   - Options: interview type (behavioural, technical, mixed, case, roleplay), stage (screening call, full, final round; default full), length (number of questions or minutes), difficulty, interviewer style (friendly, neutral, tough)
   - Saved as a reusable "interview pack" so I can re-run the same role
2. **Interview screen**
   - The 3D interviewer greets me, then asks one question at a time with lip-sync and expressions
   - Mic is live while I answer; silence of about 2 seconds ends my turn (plus a manual "Done" button and spacebar push-to-talk as backup)
   - The interviewer follows up on vague answers, asks for numbers and the STAR structure, and moves on after at most 2 follow-ups
   - Live caption of what it says and what I said; a small timer; buttons for Pause, Repeat question, End interview
   - Whole session recorded from start to end
3. **Review screen**
   - Playback of the recording with clickable question markers
   - Full transcript
   - Feedback report: overall score, score per answer (1–5) on relevance, structure (STAR), specificity and evidence, a stronger model answer for each, filler-word count, average answer length, top 3 things to fix
   - Download the recording (.webm) and the report (Markdown)
4. **History**
   - List of past sessions per interview pack with scores, so I can see progress

## Component specs

### Backend API (FastAPI, localhost:8000)

| Method | Path | Does |
|---|---|---|
| POST | `/packs` | Create an interview pack (JD, profile, company notes, options) |
| GET | `/packs`, `/packs/{id}` | List or load packs |
| POST | `/sessions` | Start a session for a pack; creates a Claude SDK client with the interviewer system prompt; returns the opening line as audio + text |
| POST | `/sessions/{id}/turn` | Body: my answer audio (webm/wav). Transcribes with Whisper, sends text to Claude, returns `{transcript, reply_text, expressions[], audio_wav_base64, word_timings[], is_final}` |
| POST | `/sessions/{id}/end` | Closes the Claude client; triggers feedback generation |
| POST | `/sessions/{id}/recording` | Upload the recorded .webm |
| GET | `/sessions/{id}/report` | Feedback report JSON + Markdown |
| GET | `/packs/{id}/drill`, `/packs/{id}/drill/attempts?key=` | Drill mode: the question list; one question's attempts |
| POST | `/packs/{id}/drill/attempts` | Transcribe (audio) or take text, score with one Claude request, store the attempt (optional `face`/`segments` add face stats to its `delivery`) |
| POST | `/research` | Draft company notes from the web (`{notes, sources}`) |
| POST | `/tts` | Voice a short text as `sentence` objects |
| GET | `/health` | Checks Claude auth, Whisper and Kokoro are loaded |

Models (Whisper, Kokoro) load once at startup and stay in memory. Stream where possible: start TTS on the first full sentence of Claude's reply instead of waiting for the whole reply.

### Brain (Claude Agent SDK)

- Auth: the Claude Code login (`claude login`); optionally `CLAUDE_CODE_OAUTH_TOKEN` from `claude setup-token` in `.env`; `ANTHROPIC_API_KEY` must NOT be set (it would bill the API instead). `/health` warns if it is.
- One `ClaudeSDKClient` per session so the conversation keeps context; no tools allowed (`allowed_tools=[]`), `max_turns=1` per call.
- System prompt (template, filled from the pack):

  ```
  You are {interviewer_name}, a {style} interviewer at {company} hiring for {role}.
  Job description: {jd}
  Candidate profile: {profile}
  Company notes: {company_notes}
  Interview type: {type}. Ask {n} main questions.
  Rules:
  - Ask ONE question at a time. Speak naturally, max 3 sentences per turn.
  - Ground questions in the JD requirements and the candidate's real experience.
  - If an answer is vague, ask at most 2 follow-ups (numbers, their own role, outcome).
  - Never give feedback or coaching during the interview.
  - Start every sentence with one expression tag: [neutral] [smile] [thinking] [nod] [curious] [serious].
  - After the last question, thank them, invite their questions, answer briefly, then end with [END].
  ```

- Feedback call: after `/end`, a separate one-shot `query()` with the full transcript, JD and a rubric; it must return JSON matching the report schema below.

### Expression tags

The backend strips tags from the text before TTS and returns them with the character position where each starts. The frontend applies them when that sentence starts playing.

| Tag | TalkingHead action |
|---|---|
| `[neutral]` | `setMood('neutral')` |
| `[smile]` | `setMood('happy')` |
| `[thinking]` | Look up/away briefly, neutral mood |
| `[nod]` | Head nod gesture |
| `[curious]` | Raised brows, slight head tilt |
| `[serious]` | Neutral mood, steady eye contact, no smile |
| `[END]` | Not spoken; ends the interview after the audio finishes |

### Speech-to-text

- mlx-whisper with whisper-small.en, language fixed to English, `initial_prompt` seeded with role keywords from the JD (improves jargon like "API", "Dynamics 365").
- Input: the audio chunk of my turn, cut by VAD in the browser.

### Text-to-speech

- Kokoro-82M via mlx-audio, one fixed voice per interviewer (configurable), 24 kHz WAV.
- Word timings for lip-sync: use Kokoro's timestamps if the library exposes them; otherwise estimate by spreading the audio duration across words in proportion to their length.

### Avatar (frontend)

- three.js scene with TalkingHead; one .glb avatar (Avaturn export with ARKit blendshapes and Oculus visemes) in `frontend/public/avatars/`.
- `say(audio, words, timings, expressions)` plays the audio with lip-sync and fires expression changes at the right moments.
- Idle behaviour while I talk: blinking, small head motion, occasional nod.
- Camera framed head-and-shoulders, soft light, plain office background.

### Recorder (frontend)

- Mix my mic and the interviewer's audio with the Web Audio API into one stream, combine with the webcam video track, record with MediaRecorder (`video/webm;codecs=vp9,opus`).
- Store a timestamp for the start of each question so Review can show markers.
- Option: record the avatar canvas instead of the webcam (`canvas.captureStream()`), or both side by side.

### Storage

```
packs(id, title, role, company, jd, profile, company_notes, options_json, created_at)   -- jd/profile/company_notes: legacy packs only
materials(id, pack_id, position, name, kind, source, text, created_at)
briefs(pack_id, brief_json, source_hash, criteria_hash, origin, created_at, updated_at)
sessions(id, pack_id, started_at, ended_at, recording_path, overall_score, brief_json)
turns(id, session_id, idx, speaker, text, expressions_json, t_start_ms, t_end_ms, t_listen_ms, face_json, segments_json, words_json)
reports(session_id, report_json, report_md)
attempts(id, pack_id, question_key, question, category, answer_text, seconds, audio_path, result_json, created_at)
```

Report JSON: `{overall_score, summary, answers:[{question, answer_summary, scores:{relevance, structure, specificity, evidence}, better_answer, tips[]}], filler_words:{count, examples[]}, avg_answer_seconds, top_fixes[3]}`.

## Project structure and setup

```
interview-coach/
  backend/
    main.py            # FastAPI app + routes
    brain.py           # Agent SDK client, prompts, tag parsing
    stt.py             # mlx-whisper wrapper
    tts.py             # Kokoro wrapper + word timings
    feedback.py        # report generation
    claude_json.py     # ask_json(): schema-checked JSON via the SDK output_format
    db.py              # SQLite helpers
    prompts/           # interviewer.txt, feedback.txt
    requirements.txt
  frontend/
    src/
      pages/Setup.tsx, Interview.tsx, Review.tsx, History.tsx, Drill.tsx
      avatar/Avatar.tsx      # three.js + TalkingHead, say()
      audio/vad.ts, recorder.ts
      api.ts
    public/avatars/interviewer.glb
  data/                # sqlite db, recordings, reports (git-ignored)
  .env                 # CLAUDE_CODE_OAUTH_TOKEN (git-ignored)
  README.md
```

### One-time setup

1. Install Homebrew, Python 3.11, Node 20+, and Claude Code; run `claude login` (a token in `.env` is optional).
2. `pip install fastapi uvicorn claude-agent-sdk mlx-whisper mlx-audio python-multipart` (in a venv).
3. Create the avatar on Avaturn, export .glb with ARKit blendshapes, save to `frontend/public/avatars/`.
4. `npm create vite@latest frontend -- --template react-ts`, then add three, the TalkingHead library and @ricky0123/vad-web.
5. Run `uvicorn backend.main:app` and `npm run dev`; open localhost:5173 in Chrome (best support for mic, WebGL and MediaRecorder).

## Build milestones

Build in this order; each milestone is usable on its own, and the avatar comes last because it's the hardest part.

1. **Text interviewer** — Setup screen + `/sessions` + `/turn` with typed answers only.
   - Done when: a 5-question interview grounded in a real JD runs in the browser, with follow-ups, using my subscription (not an API key).
2. **Voice in and out** — Whisper + Kokoro + VAD.
   - Done when: I can answer by speaking, hear the reply, and the gap from finishing my answer to hearing the interviewer's voice is under 4 seconds.
3. **Recording + Review** — MediaRecorder, transcript, feedback report.
   - Done when: after ending, I can replay the session with question markers and read a scored report.
4. **Avatar** — TalkingHead with lip-sync and expression tags.
   - Done when: the face lip-syncs to every reply, changes expression on tags, and idles naturally while I talk.
5. **Polish** — History, interview packs, difficulty and style options, downloads.
   - Done when: I can re-run a saved pack and compare scores across sessions.

## Performance, risks and rules of use

| Risk | Mitigation |
|---|---|
| Slow replies (Agent SDK starts the Claude Code CLI; Whisper + Kokoro on 8 GB) | Keep one SDK client open per session; load models once; stream Claude's text and start TTS on the first sentence; short interviewer turns (max 3 sentences) |
| Memory pressure on 8 GB | Use whisper-small.en; close other heavy apps; avoid models above ~1B parameters |
| Subscription usage limits | Long sessions use plan usage; keep the feedback call to one request per session |
| Billing the wrong account | `/health` refuses to start if `ANTHROPIC_API_KEY` is set |
| Avatar looks game-like | Acceptable for v1; the avatar layer is isolated behind `say()` so a photoreal option can replace it later |
| Lip-sync drift with estimated timings | Use real Kokoro timestamps if available; otherwise tune the estimate |
| Echo (mic picks up the interviewer) | Use headphones; enable echoCancellation in getUserMedia; mute mic while the interviewer speaks |

Rules of use: runs only on my machine for my own practice. Subscription sign-in can't be offered to other users, so sharing or deploying this needs an API key instead. Recordings stay local in `data/`.
