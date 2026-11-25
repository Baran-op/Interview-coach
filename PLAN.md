# Coaching improvements plan

Milestones 1-5 (see `SPEC.md`) built a realistic mock-interview simulator. This plan turns it into a
coach: a fast practice loop, scores you can trust over time, and transcripts accurate enough to judge
delivery. Each numbered section fixes one recommendation from the 2026-11-25 review. **Build order**
at the end puts them into commits and is the checklist to tick off.

Sizes are relative: **XS** a few lines or a prompt tweak, **S** one module or prompt change,
**M** a feature across backend and frontend, **L** a new page with its own data.

## Why: evidence from real sessions

- A session was abandoned after its first answer. The only way to redo a weak answer was to quit,
  and that one-answer score became both the "latest" and the "best" score in History.
- In the same session, one answer had about 45 s of speech (no pause longer than 1.2 s) but a
  65-word transcript: about 86 words per speaking minute, where conversation is 130-160. The report
  counted 0 filler words. Whisper is dropping words or stripping drawn-out "uhh/umm"s, so the
  delivery stats can't be trusted yet.
- Whisper's hint words for that pack were mostly capitalised sentence-start words ("Everyone, Make,
  Time, Pension, Fitness") and had nothing from the CV, which is what candidates mostly talk about.
- The report itself was good: specific, built on CV facts, with placeholders instead of invented
  numbers. The prompts are sound; the gaps are in the loop around them.

## Ground rules for every item

- One logical change per commit, pushed as `CLAUDE.md` describes. Update `README.md` (usage, API
  table, env vars), `CLAUDE.md` and `SPEC.md` in the same commit when they're affected, and tick
  the item in **Build order**.
- Keep `prompts/interviewer.txt`, `prompts/feedback.txt` and the new `prompts/drill.txt` in step:
  they share the criteria, the score anchors and the question categories.
- Schema changes: new columns go in `db._EXTRA_COLUMNS`, new tables in `db.SCHEMA`
  (`CREATE TABLE IF NOT EXISTS`), so existing databases upgrade on start.
- Anything that spends a Claude request says so in the UI before spending it (see **Cost summary**).
- Verify with unit tests for pure functions (0.1), `npx tsc -b`, and a run through the real app for
  UI flows.

## 0. Foundations

### 0.1 Test harness (XS)

- `backend/requirements-dev.txt` with `pytest`; tests in `backend/tests/`, run with
  `pytest backend/tests` (add to the Commands in `CLAUDE.md`).
- First tests: `brain.parse_tags`, `feedback.filler_words`, `feedback.normalise`, `stt.keyword_prompt`.

### 0.2 Schema-checked JSON from Claude (S, spike first)

The report, drill scoring (1) and the prep sheet (7) all need JSON. `feedback._extract_json` parsed
free text, and every field this plan adds is another chance for a malformed reply.

- Spike: call `query()` with `output_format={"type": "json_schema", "schema": {...}}` and the
  current options (`tools=[]`, `max_turns=1`), then read `ResultMessage.structured_output`. If it is
  empty or the run stops on max turns, retry with `max_turns=2`. If that fails too, drop 0.2 and
  keep `_extract_json`.
- If it works: one helper, `ask_json(system_prompt, prompt, schema, model)` in
  `backend/claude_json.py`, falling back to `_extract_json` on the reply text when
  `structured_output` is missing. `feedback._ask_claude` uses it.

## 1. Drill mode: one question, scored now, try again (M-L)

**Goal.** Practise a single question: hear it, answer out loud, get scored in seconds, try again,
and see what changed. Today the only unit of practice is a full interview with one report at the end.

**Questions offered for a pack**

- Starters, always there: "Tell me about yourself", "Why this role?", "Why {company}?",
  "Why are you looking to move now?", "What's a weakness you're working on?"
- Every main question from this pack's reports with an average of 2.5 or less, newest first.
- The prep sheet's likely questions, once 7 exists.
- A free-text "your own question".

Attempts are grouped by `question_key`: the first 12 hex characters of the SHA-1 of the question,
lower-cased, with punctuation and repeated spaces removed.

**Data** (`db.SCHEMA`):

```sql
CREATE TABLE IF NOT EXISTS attempts (
    id TEXT PRIMARY KEY,
    pack_id TEXT NOT NULL REFERENCES packs(id),
    question_key TEXT NOT NULL,
    question TEXT NOT NULL,
    category TEXT,              -- same values as report answers (3c)
    answer_text TEXT NOT NULL,
    seconds REAL,               -- first word to end of answer
    audio_path TEXT,            -- data/answers/drill/<id>.wav
    result_json TEXT,           -- scores, average, tips, improved, better_answer, delivery
    created_at INTEGER NOT NULL
);
```

`db.delete_pack` also deletes the pack's attempts and their audio.

**Backend** (`backend/drill.py`, routes in `main.py`)

- `GET /packs/{id}/drill` returns `{questions: [{key, question, category, source, attempts, latest, best}]}`,
  where `source` is `starter`, `report`, `prep` or `custom`.
- `POST /packs/{id}/drill/attempts`: multipart `audio` (WAV) with `question`, `category` and
  `seconds`, or JSON `{question, category, text}`. Transcribes with `stt.transcribe` and the pack's
  hint words (4a), scores with one Claude call, stores the attempt and returns `{attempt, previous}`.
- `GET /packs/{id}/drill/attempts?key=...`: that question's attempts, oldest first.
- `POST /tts` with `{text, voice}` returns `{sentences: [...]}`, each with the same fields as the
  NDJSON `sentence` event. Split with `SentenceSplitter`, voiced with `tts.synthesize` via `gpu.run`.
  It reads the question aloud.
- Scoring prompt `prompts/drill.txt`: role, company, JD, CV, company notes, the question and its
  category, this answer with its length, and the previous attempt (answer and scores) if there is
  one. Same four criteria and anchors as `feedback.txt` (3d). It returns:

  ```json
  {"scores": {"relevance": 3, "structure": 3, "specificity": 3, "evidence": 3},
   "tips": ["...", "..."],
   "improved": ["what is better than the previous attempt"],
   "better_answer": "..."}
  ```

  Clamp with `feedback._score`, average locally, and attach `delivery.text_stats` (5).

**Frontend** (`src/pages/Drill.tsx`, route `#/drill/<pack id>?q=<question>` in `App.tsx`)

- The question list (with best and latest score chips) on the left, the current question on the right.
- Play the question through the `Speaker` interface: `InterviewerPlayer`, or `AvatarController` when
  it's loaded (which speaks through `say()`). Answer with `TurnListener` in Done-only mode (S1),
  because thinking pauses are normal here. Typed answers work too.
- Result: score bars, tips, "Better than last time" (`improved`), and the stronger answer collapsed
  behind "Show a stronger answer". It appears only after the first attempt, so you try before you read.
- Attempt history for the question: time, average, and change since the previous attempt.
- Entry points: "Practise this question" on each answer in Review (passes the question as `?q=`),
  and a Drill button per pack in Setup and History.

**Done when** you can open a question from a Review answer, answer it three times by voice, get each
attempt scored in under about 15 s, see the deltas in the attempt history, and find the attempts
still there after a backend restart.

**Cost:** one Claude request per attempt (a one-shot `query()` like `feedback.py`; no `ClaudeSDKClient`).
**Depends on:** 3c (categories), 3d (anchors), 5 (text stats); S1 (Done-only mode) recommended.
**Not in scope:** redoing an answer in the middle of an interview. The SDK can rewind a session
(`resume_session_at`), but drill mode covers the need with far less moving state.

## 2. Sessions that build on each other (S)

**Goal.** Each interview of a pack re-tests what went badly last time and covers requirements not yet
tested. Each report says whether last time's fixes were addressed. Today `build_system_prompt` only
sees the pack, and the report doesn't know that earlier sessions exist.

**Backend and prompts**

- `db.pack_report_history(pack_id, limit=3)` returns the latest scored, non-partial sessions (3b),
  newest first: `[{started_at, answers: [{question, category, average}], top_fixes}]`.
- `brain.history_block(history) -> str` and `build_system_prompt(pack, history)`. `start_session`
  passes `db.pack_report_history(pack["id"])`.
- `interviewer.txt`: a `{history}` block after the company notes. For a first session it says
  "(This is the candidate's first session for this role.)". Otherwise it lists earlier questions with
  their scores and the open fixes, with these rules:
  - still open with "tell me about yourself" and motivation, because they're practised every time;
  - in the main questions, re-test the weakest earlier area with a new question, don't repeat a
    question that scored 4 or more, and prefer requirements not tested yet;
  - never mention earlier sessions or scores out loud.
- `feedback.txt` and `feedback._system_prompt`: a `{previous_fixes}` block (the previous non-partial
  session's `top_fixes`, or "none") and a new output field:

  ```json
  "previous_fixes": [{"fix": "...", "status": "improved | partly | not_yet | not_tested",
                      "evidence": "one sentence citing the turn"}]
  ```

  `normalise()` keeps at most 3 and maps unknown statuses to `not_tested`.

**Frontend:** Review shows "Since last time" above the top 3 fixes (✓ improved, ~ partly, ✗ not yet,
– not tested, each with its evidence). `to_markdown()` adds the same section.

**Done when** a second session of a pack doesn't repeat a question that scored 4 or more, asks about
the weakest earlier area in a new form, and its report gives a status for each of last time's fixes.

**Cost:** none extra (slightly longer prompts). **Depends on:** 3b.

## 3. Progress you can trust (S-M)

### 3a. Score or discard when ending early

- `Interview.tsx`: if End is pressed before the interviewer's closing `[END]`, ask "Score it (one
  Claude request)", "Discard it" or "Keep going" in a small inline dialog. A natural ending is unchanged.
- Discard: `/end` with `score: false`, skip the recording upload, then `DELETE /sessions/{id}` and
  go back to Setup.
- `main.py`: `EndIn.score: bool = True`; `finish_session(..., score=True)` skips `start_report`
  when it's false. The `pagehide` beacon and the idle reaper keep scoring, since they can't ask.

### 3b. Partial sessions

- `db.MIN_SCORED_ANSWERS = 3`; `_session_summary` adds `partial` (fewer scored answers than that).
- History: partial sessions get a "partial" chip and a hollow point in the chart, and are left out
  of the latest, best and "since first session" stats in `History.tsx`.
- Review: the "previous attempt" comparison skips partial sessions, and a partial session's own
  Review says it isn't counted in trends.

### 3c. Question categories

- `feedback.txt`: each answer gets `"category"` (`intro`, `motivation`, `behavioural`, `technical`,
  `case`, `roleplay`, `logistics` or `other`) and `"competency"` (2-4 words, such as
  "stakeholder management").
- `normalise()`: an unknown category falls back on the question text ("about yourself" is `intro`;
  "why" plus the company or role is `motivation`; anything else is `other`). Apply the same fallback
  when reading older reports.
- `db.pack_history`: each session gets `by_category: {category: average}`.
- History: a "By question type" table per pack (type, answers, first, latest, best), and the chart
  can switch to one line per type. "Tell me about yourself" is asked every session, so its line is
  the most comparable number in the app.
- Review: a category chip on each answer.

### 3d. Score anchors

- `feedback.txt`: replace "1 = missing or poor, 3 = adequate, 5 = excellent" with one short line
  for 1, 3 and 5 per criterion. For evidence, for example: 1 = no outcome or numbers; 3 = an outcome,
  but vague or unmeasured; 5 = measured results clearly caused by the candidate's own actions.
- `scripts/rescore.py <session_id> --n 3` re-runs the report prompt on a stored transcript without
  saving it and prints the spread per answer and criterion. Run it before and after adding the
  anchors. Aim for an overall spread of 0.3 or less, and 0.5 or less per answer.

**Done when** an early End offers score or discard, a one-answer session shows as partial and doesn't
move latest, best or the trend, History has the by-type table, and the rescore spread meets the targets.

**Cost:** none extra. The rescore script spends n requests and is only run by hand.

## 4. Transcripts you can trust

### 4a. Better hint words for Whisper (XS)

- `stt.keyword_prompt(role, company, jd, profile)`:
  - skip a capitalised word that starts a sentence or line (after `.`, `!`, `?`, `:` or a bullet)
    unless it's an acronym or contains a digit or `+#.`;
  - take CV terms first (employers, schools, tools, products), then JD terms, de-duplicated
    ignoring case;
  - keep two-word names ("Power BI", "Customer Success");
  - cap at about 180 Whisper tokens, counted with `mlx_whisper.tokenizer` when it imports, otherwise
    about 600 characters. Whisper keeps only the last 223 prompt tokens, so a long list would push
    out the filler seed at the start.
- In `start_session` (`main.py`), pass `pack.get("profile", "")` where `stt_prompt` is built.
- Tests: sentence-start words are dropped, CV names are kept, and the cap holds.

### 4b. Keep each answer's audio (XS)

- `take_turn`: after `db.add_turn`, write the uploaded WAV to `data/answers/<session_id>/<turn_idx>.wav`
  in a thread. Typed answers have no audio.
- Deleting a session or a pack removes its folder (`_remove_files` handles files; add the folder).
- About 2 MB per answered minute (16 kHz mono 16-bit). `data/` is already git-ignored.

### 4c. Pick the Whisper model with data (S)

- `scripts/stt_bench.py <model> ...` transcribes every WAV in `data/answers/` with each model and
  prints words, words per speaking minute, filler count, time per answer and peak MLX memory.
- Run it with the backend stopped, for `mlx-community/whisper-small.en-mlx`,
  `mlx-community/whisper-large-v3-turbo-q4` and `mlx-community/whisper-large-v3-turbo`.
- Rule: if a larger model adds less than about 1.5 s for a 60 s answer and leaves memory headroom on
  the 8 GB M1 with Chrome open, make it the default `WHISPER_MODEL` (in `stt.py`, `README.md` and
  `.env.example`). Otherwise do 4d.

### 4d. Re-transcribe for the report (only if 4c says live is too slow) (S)

- New env var `REPORT_WHISPER_MODEL`. Before asking Claude, `feedback.generate` re-transcribes each
  saved answer with it on the MLX thread. The result replaces `turns.text`; the live text moves to a
  new `turns.text_live` column.
- mlx-whisper caches one model (`ModelHolder`) and swaps it when another is requested, so the next
  live answer reloads small.en, which takes a few seconds. That's fine after an interview; log it.

**Done when** a real pack's hint words include CV names and no sentence-start words, answers are saved
and deleted with their session, and the benchmark has run with the chosen model and its numbers
recorded in `README.md`.

**Cost:** none.

## 5. Per-answer delivery stats (S-M)

**Goal.** Measure delivery for each answer, locally and consistently like the filler count, instead
of one average for the whole session.

- `backend/delivery.py` (pure functions, unit-tested):
  - `text_stats(text)` returns `{words, fillers, hedges, i_count, we_count, numbers}`:
    - fillers: reuse `feedback.filler_words`;
    - hedges: "I think", "I guess", "I suppose", "maybe", "perhaps", "probably", "hopefully",
      "I feel like", kept in one list with no overlap with the fillers;
    - I vs we: `I, I'm, I've, I'd, me, my` against `we, we're, we've, we'd, us, our`;
    - numbers: digits, %, £/$/€, k/m/bn, and number words (one to twenty, hundred, thousand,
      million, billion, percent, half, double).
  - `audio_stats(wav_path, span_s)` returns `{speaking_s, pause_s, pauses_over_1s, longest_pause_s}`
    from 30 ms RMS frames compared with the clip's own noise floor. When a turn is held (Space or
    Done-only), the VAD drops pauses longer than the silence window from the audio, so total pause
    time is `span_s - speaking_s`, using the turn's timeline span.
  - `TARGET_SECONDS = {"intro": (60, 90), "motivation": (45, 90), "behavioural": (90, 150)}`;
    other types have no target.
  - Optional: time to first word. Send `t_listen_ms` (when the mic opened) in the `/end` timeline
    (`TurnTiming`, plus a new `turns.t_listen_ms` column); thinking time is `t_start_ms - t_listen_ms`.
- `feedback.generate`, after `normalise()`: give each answer a `delivery` object, built from the
  candidate turns between its `question_turn` and the next answer's (the answer plus its follow-ups):
  `{seconds, first_answer_seconds, wpm, fillers, hedges, i_count, we_count, numbers, pauses_over_1s,
  target, flag}`, where `flag` is `"short"`, `"long"` or `null`. Keep the top-level `filler_words`
  and `avg_answer_seconds`, which History reads.
- Review: one line under each answer's score bars, such as
  `1:12 (aim 1:00-1:30) · 138 wpm · I 6 / we 2 · 3 numbers · 2 fillers · 1 hedge`, with values
  outside the target highlighted. `to_markdown()` adds the same line.

**Done when** unit tests cover each counter and a new report shows the line for every answer, both in
the app and in the Markdown download.

**Cost:** none. **Depends on:** 3c (targets by category); 4b for the audio stats.

## 6. Practice that matches the real interview

### 6a. Company notes in the report (XS)

`feedback.txt` has no company notes, so a "why this company" answer can't be checked against the
research the candidate was given. Add a "Company notes" block to `feedback.txt` and its value in
`feedback._system_prompt`.

**Done when** a unit test shows the notes in the report prompt.

### 6b. Draft company notes from the web (S-M)

- `POST /research` with `{company, role, jd}` returns `{notes, sources}`. It makes one `query()` with
  `tools=["WebSearch", "WebFetch"]`, `allowed_tools=["WebSearch", "WebFetch"]`, `setting_sources=[]`
  and `max_turns=10`, using `prompts/research.txt`: 150-300 words of plain notes that an interviewer
  there would know. That covers what the company does and for whom, its products, scale and business
  model, recent news with dates, its values, and what this team does. Cite sources, and write
  "unknown" rather than guess. The interviewer itself stays tool-less.
- Setup: a "Draft from the web" button next to Company notes, enabled once there's a company name.
  It fills the textarea for editing, lists the sources, and says it uses Claude usage.

**Done when** the button fills the notes for a real company in under about 90 s with sources, and
nothing is saved until the pack is saved.

**Cost:** one query with several web-search turns.

### 6c. Interview stage and role-play (S-M)

- `PackOptions.stage`: `"screen"`, `"full"` or `"final"`, defaulting to `"full"` (today's behaviour).
  `interview_type` gains `"roleplay"`. Mirror both in `api.ts` and Setup; `packSummary` shows the stage.
- `brain.py`: a `STAGES` dict fills a `{stage}` block in `interviewer.txt`:
  - screen: a 15-20 minute recruiter call: intro, motivation, why move now, what they're looking
    for, salary expectations, notice period and availability, two or three light competency
    questions, then the candidate's questions;
  - full: today's shape;
  - final: a senior or founder conversation: motivation and values in depth, the first 90 days,
    "why you over the other candidates", and where they want to be in a few years.
- `interviewer.txt`, under the main questions: "roleplay: run one or two realistic scenarios from the
  job, for a customer-facing role an unhappy customer whose launch slipped, or training a nervous
  non-technical user. Say who you're playing, stay in character for 3-6 exchanges, react to what
  they actually do, then step out of the role and ask one reflection question."
- `feedback.txt`: what good structure looks like in a role-play (acknowledge, clarify, plan, agree
  next steps) and in logistics answers (a clear, researched salary range; an honest notice period).
  Uses the `roleplay` and `logistics` categories from 3c.

**Done when** a screen interview asks about salary and notice period, and a role-play interview stays
in character for several exchanges and is scored with the role-play guidance.

**Cost:** none extra.

### 6d. Probe like a real interviewer (XS)

- `interviewer.txt`: "Before you start, note silently what a sceptical hiring manager would probe when
  comparing this CV with this job: career or industry switches, short tenures or gaps, requirements
  the CV doesn't show, and claims without numbers. Ask about at least two of them during the main
  questions, politely but directly. Never read the list out."
- `feedback.txt`, in step: when the interviewer probed a gap or a switch, score how convincingly the
  candidate addressed it.

**Done when**, with a test pack whose CV shows an industry switch, the interviewer asks about the switch.

## 7. Prep sheet per pack (M)

**Goal.** One page to prepare from before practising: likely questions, gaps between the CV and the
job, STAR stories built from the CV, and questions to ask. It also feeds drill mode.

- `db.SCHEMA`: `prep(pack_id TEXT PRIMARY KEY REFERENCES packs(id), source_hash TEXT, prep_json TEXT,
  created_at INTEGER)`. `source_hash` is the SHA-1 of the JD, CV and company notes, so the page can
  say when the pack has changed since the sheet was written. Deleting a pack deletes its prep sheet.
- `GET /packs/{id}/prep`, and `POST /packs/{id}/prep` to write it (one Claude request, no tools,
  `prompts/prep.txt`):

  ```json
  {
    "likely_questions": [{"question": "...", "category": "...", "why": "what they're testing"}],
    "gaps": [{"requirement": "...", "cv_evidence": "... or null", "how_to_address": "..."}],
    "stories": [{"title": "...", "competencies": ["..."], "situation": "...", "task": "...",
                 "action": "...", "result": "...", "numbers": ["..."]}],
    "questions_to_ask": ["..."]
  }
  ```

  Rules: 10-15 likely questions, including the intro, motivation and the probes from 6d; every
  requirement mapped to CV evidence or marked missing; 6-8 stories built only from CV facts, with
  `[placeholders]` for anything missing, as in `feedback.txt`; 4-6 questions to ask.
- `src/pages/Prep.tsx` at `#/prep/<pack id>`, linked from Setup's pack list and from History: the four
  sections, a "Practise" button on each likely question (opens drill mode with source `prep`), a
  Markdown download, and a "Rewrite" button that says it costs a request.

**Done when** a pack's prep sheet shows all four sections, warns when the pack has changed, and each
likely question opens in drill mode.

**Cost:** one request per write.

## S. Small fixes

### S1. More time to think mid-answer (XS)

- `Interview.tsx`: `SILENCE_OPTIONS` becomes `[1500, 2000, 2500, 3000, 4000, 5000, 0]`, where `0` means
  "only when I press Done". `readSilence()` must treat a missing value as 2000: `Number(null)` is 0,
  which would otherwise turn Done-only on by default.
- `vad.ts`: `TurnListener` gets a manual mode in which `listen()` sets `held = true`.
  `setSilenceMs(0)` turns it on and keeps the VAD's `redemptionMs` at 2000 for segmenting. Done and
  releasing Space finish the turn as they do now. Update the hint text.

**Done when** a 6 s pause in Done-only mode doesn't end the answer, and Done sends all of it.

### S2. Timestamps for a reply cut short (XS)

Ending the interview while the interviewer's reply is still arriving loses that turn's timestamps:
`runReply` returns before writing its timeline entry, and the frontend never learns the turn's index.

- `speak()` in `main.py`: work out the reply's turn index up front with `db.next_turn_idx(session_id)`
  (the current turn count; the session lock prevents races) and include `turn_idx` in every
  `sentence` event.
- `Interview.tsx`: keep `currentReply = {idx, start}`, set when the reply's first sentence starts
  playing. While the reply is unfinished, `timelineList()` adds `{start, end: clockNow()}` for it, so
  End, the `pagehide` beacon and normal endings all carry it.

**Done when** ending while the interviewer is speaking still gives that turn a ▶ marker in Review.

## Cost summary

| Item | Claude requests |
|---|---|
| 1 Drill mode | 1 per attempt |
| 6b Draft company notes | 1 query with several web-search turns |
| 7 Prep sheet | 1 per write |
| 3d `rescore.py` | n per run, by hand only |
| Everything else | none (some prompts get a little longer) |

## Build order

One commit per line. If a real interview is close, pull 6d and 6c forward: they're prompt changes.

**Phase A: fix the data the scores are based on**

- [x] A1. 0.1 Test harness
- [x] A2. 6a Company notes in the report prompt
- [x] A3. 4a Whisper hint words from the CV, without sentence-start words
- [x] A4. 4b Save each answer's audio (starts collecting data for 4c)
- [x] A5. S1 Longer silence options and Done-only mode
- [x] A6. S2 Timestamps for a reply cut short

**Phase B: progress you can trust**

- [x] B1. 0.2 Schema-checked JSON (spike worked: `output_format` json_schema with `max_turns=1` returns `structured_output`)
- [x] B2. 3a Score or discard on early end
- [x] B3. 3b Partial sessions
- [x] B4. 3c Question categories
- [x] B5. 3d Score anchors and `rescore.py`

**Phase C: memory across sessions**

- [x] C1. 2 Interviewer history and the previous-fixes check

**Phase D: drill mode**

- [x] D1. 5 Text stats (`delivery.text_stats`)
- [x] D2. 1 Drill backend (`attempts` table, routes, `drill.txt`, `/tts`)
- [x] D3. 1 Drill page and entry points from Review, Setup and History

**Phase E: transcripts and delivery**

- [ ] E1. 4c Benchmark and pick the Whisper model
- [ ] E2. 4d Re-transcribe for the report (only if E1 says so)
- [x] E3. 5 Audio stats and per-answer delivery in the report and Review

**Phase F: realism**

- [x] F1. 6d Probe like a real interviewer
- [x] F2. 6c Interview stage and role-play
- [ ] F3. 6b Draft company notes from the web

**Phase G: prep**

- [ ] G1. 7 Prep sheet, with its likely questions added to the drill list
