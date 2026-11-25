# Voice analysis plan

Today the report can say an answer's voice is "flat" (`delivery.voice_flags`), but it only gives one number
per answer (`pitch_range_st`) and no way to see or hear why. This plan adds a **Voice** tab to Review. It shows
each question's answer audio with a waveform and a pitch line, marks the flat stretches, plays them back with
the exact words, and gives specific advice from the same single report request. **Build order** at the end is
the checklist to tick off.

Sizes: **XS** a few lines, **S** one module, **M** a feature across backend and frontend, **L** a new
component or page with its own interaction model.

Your decisions (asked before writing): the view is a **tab inside Review**; older sessions get advice through
the existing **Write report again** (1 request, scores may shift); you'll record a **guided calibration set**
in Drill; follow-ups are **stacked graphs**, one per turn.

## What the code does today (checked)

Each assumption in the request, checked against the code on `main` (e2308a7):

1. **Pitch per 30 ms frame, reduced to one number: confirmed.** `delivery._pitch_range_st` runs YIN (`_f0`)
   on each voiced 30 ms frame and keeps only the 10th-90th percentile spread. Measured on your three real
   answers: about 0.09 s per 80 s answer. Only **about 25% of frames get a pitch value** (YIN threshold 0.15;
   the RMS "voiced" mask also covers unvoiced consonants and breaths). A 10 s window of steady speech
   therefore has about 80 pitched frames, not 333. The flat-section rules below are built around that.
2. **Answer WAVs drop long silences: partly.** `data/answers/<session>/<turn>.wav` holds one candidate turn's
   VAD speech segments joined in the browser (`TurnListener.deliver`). Pauses shorter than the silence
   timeout stay *inside* a segment. Silence is cut only between segments, which happens when the turn was held
   (Space, Done-only mode, or pause/resume). Your three answers are each one segment, the segment lengths add
   up to the WAV length to the millisecond, and each WAV ends with about 2 s of silence (the VAD's tail).
3. **Turns spanning several files: a turn never does, an answer does.** One candidate turn is one WAV. A report
   answer is the main answer plus its follow-ups (`delivery.answer_turns`), so it is several WAVs.
4. **No route serves answer WAVs: confirmed.** Only `GET /sessions/{id}/recording` (the webm). Drill attempts
   expose only `has_audio`. Starlette 1.10's `FileResponse` already handles byte ranges, so seeking works.
5. **Word timestamps only with face data: confirmed.** `feedback.turns_needing_words` requires `face` and
   `segments`. Drill calls `_drill_words` only when there are face moments. They are already never computed in
   `POST /sessions/{id}/turn` (they run in the report step), so interview replies aren't slowed today.
6. **Delivery after the Claude call: confirmed, with a catch.** `feedback.generate` calls Claude, then
   `_fill_words`, then `answer_delivery`. `answer_delivery` groups turns into answers using Claude's
   `question_turn`, so evidence computed *before* the call has to be **per turn**, not per answer (V6).
7. **Data you have:** 4 sessions and 5 candidate turns. Only one session (3 turns, about 3.7 min) has WAVs,
   segments and words. There are 0 drill attempts with audio. That's too little for calibration or the
   10-answer baseline (`db.VOICE_BASELINE_MIN`).
8. **Found along the way (not fixed here):** in `Interview.tsx` the recorder starts (`rec.start()`) before
   `clock.startedAt` is set, with `FaceTracker.create` awaited in between. So the webm can run ahead of the
   session clock by the face model's load time. The Voice tab plays the answer WAVs, so it isn't affected. The
   existing seek-to-question buttons are. This is worth a separate one-line fix.

## Shape

- **Turn-level measurements, computed locally before the report request.** Pitch track → flat sections →
  word quotes, per candidate turn. These go into the transcript Claude already gets, so the advice comes from
  the **same single request**.
- **Pitch track: computed on demand, not stored.** It's cheap (0.09 s per 80 s answer), it's derived entirely
  from the WAV, and storing 2,700 frames per turn in SQLite would add up for no gain. A small in-memory cache
  covers repeated views. **Flat sections *are* stored in the report**, because the advice refers to them and
  they must not move if the thresholds change later.
- **Playback uses the answer WAVs, not the session recording.** Word offsets from Whisper are already in WAV
  time, so the playhead and the highlighted word share one clock with no mapping. The turn's segments map WAV
  time to session time for labels only ("12:41 in the interview") and mark where silence was cut.
- **Plain canvas, no new dependency** (see V9 for the comparison).

## Ground rules for every item

- One commit per item, pushed as `CLAUDE.md` describes, with `README.md`, `SPEC.md` and `CLAUDE.md` updated in
  the same commit when they're affected, and the item ticked in **Build order**.
- **Today's numbers don't move.** Refactoring the pitch code must leave `voice_stats` output identical
  (V0 pins it). Changing the YIN threshold is allowed only as an explicit V3 decision, followed by
  `scripts.backfill_delivery`.
- **Golden prompts stay byte-identical with no voice evidence.** New prompt text sits behind an empty-by-default
  slot, and the new goldens cover the voice case (V6).
- **Nothing is added to `POST /sessions/{id}/turn`.** All new audio work runs in the report step, in Drill's
  result step or when you open the Voice tab.
- **Behaviour, never emotions or confidence.** UI text and advice say "flat", "same pitch", "trailing off",
  "stressed". They never say nervous, bored, confident or similar. `normalise` enforces this (V6).
- No new Python dependencies (numpy and the standard library only). No new frontend dependencies.
- Monochrome tokens from `index.css`. Every mark is told apart by shade, pattern or a text label, never by
  colour alone. Red only for errors.
- Pure functions get unit tests in `backend/tests/` with synthetic audio. Nothing from `data/` goes into the
  repo.
- Every action that spends a Claude request says so on its button.

## V0. Pin today's voice numbers (XS)

Before touching the pitch code, `test_delivery_audio.py` records `voice_stats` for its synthetic tones (steady,
glide, trailing phrases, octave-jump case) as exact expected dicts. `scripts/voice_stats.py --json` writes the
current numbers for your real WAVs to the scratchpad, and V1 is checked against that file by hand (not committed).

**Done when** the pinned tests pass on today's code. **Cost:** none.

## V1. Pitch track and time mapping (S)

`delivery.py`:
- `pitch_track(x, rate) -> {"frame_ms": 30, "f0_hz": np.ndarray (nan where unpitched), "voiced": bool array,
  "rms_db": np.ndarray}`. This is the per-frame loop pulled out of `_pitch_range_st`, unchanged. Then
  `_pitch_range_st` becomes "track → semitones → percentiles", so both share one code path.
- `to_semitones(f0_hz, center_hz)`: `12·log2(f0/center)` with today's octave fold (±9 st → ∓12) and the
  ±12 st cut.

New `backend/voice.py` (pure, imports `delivery`):
- `wav_to_session(ms, segments)` / `session_to_wav(ms, segments)`: walks the segments as `_words_in` does
  today. Times outside any segment snap to the nearest edge.
- `joins(segments) -> [{wav_ms, cut_ms}]`: where silence was cut, and for how long.

**Tests:** `_pitch_range_st` unchanged (V0). Round-trip mapping. Several segments with gaps. Times in a
gap. No segments (returns None and the caller falls back to WAV time).
**Done when** V0's pins and your real-WAV numbers are identical. **Cost:** none.

## V2. Flat sections (S)

`voice.flat_sections(track, joins, baseline) -> [{id, start_ms, end_ms, range_st, pitched_s}]`, in WAV time.

| Choice | Proposal | Why |
|---|---|---|
| Window | **10 s of WAV time** (333 frames) | Long enough to hear as "the same note", short enough to point at one sentence or two. |
| Hop | **2.5 s (75% overlap)** | Section edges land within 2.5 s. The cost is trivial (about 30 windows per 80 s). |
| Measure | 10th-90th percentile spread of the window's pitched frames, in semitones | The same definition as the answer's `pitch_range_st`, so the numbers read alike. |
| Enough speech | at least **60 pitched frames (1.8 s)** in the window, else the window is skipped | Only about 25% of frames are pitched (finding 1). Pauses and breaths reduce the count and never make a window flat. |
| Threshold (provisional) | with a baseline: spread **< 0.6 × your usual window spread**. Without: **< 2.5 st** | On your 3 answers, 10 s window spreads ran 1.5-8 st, with per-answer medians of 3.2-6.2. Answer-level ranges are wider than window ranges, so the threshold is compared with window spreads, not with `pitch_range_st`. V3 sets the real values. |
| Merging | overlapping flat windows join into one section. Edges are trimmed to the first and last pitched frame, then snapped to word edges when words exist | One stretch, one card. |
| Pauses | windows run on WAV time, so cut silence uses no window time. A window never straddles a join whose cut pause was **≥ 2 s**: windows restart after it | A long pause is a reset for the listener. It isn't part of a monotone run. |
| Short answers | no sections under **12 s of WAV or 8 s voiced** (`MIN_VOICED_S`). The answer-level range is still shown from 8 s voiced | Under one full window plus margin there's nothing to compare. |
| Caps | at most **2 sections per turn and 6 per session go to Claude**, flattest first. The rest are still drawn, marked "no advice (lower priority)" | Bounds the prompt and keeps the advice focused. |

IDs are `T<turn>.<n>` (for example `T5.1`), unique in the session, so Claude can refer to them.

**Tests:** a steady 150 Hz tone of 20 s gives one section covering it. A glide gives none. A steady tone with
a 3 s cut join (two segments) gives two sections, not one. 30% pitched frames still counts. Under 60 pitched
frames per window gives none. Under 12 s gives none. The caps and the order work. Baseline vs fallback
threshold.
**Cost:** none.

## V3. Calibration on your recordings (S, plus your listening)

**Recording the set (you, any time, even before V1, since Drill already saves WAVs):** 12 Drill answers of
60-90 s on questions from your implementation-consultant pack: 4 spoken normally, 4 deliberately monotone
and 4 deliberately varied (stress results, numbers and contrasts). Note which is which in the attempt's first
words ("normal one", "flat two", ...) or just tell me the order.

**`python -m scripts.voice_windows`** (no Claude):
- Reads every WAV under `data/answers/**` (sessions and drill). Prints the window-spread percentiles over all
  windows, per answer and per labelled group.
- Lists the 10 flattest and 10 liveliest windows. Writes each as a WAV clip to `data/calibration/`
  (git-ignored, under `data/`) with a CSV `clip, file, start, end, spread, pitched_frames, flat_heard`.
- You listen and fill `flat_heard` (y/n). Run it again with `--score` and it reports agreement for candidate
  thresholds (2.0 / 2.5 / 3.0 st absolute; 0.5 / 0.6 / 0.7 × usual) and the false-flag rate on your "varied"
  group.
- `--yin 0.15,0.20` also reports pitched-frame coverage and window agreement at a looser YIN threshold. If
  0.20 clearly helps, changing it is a separate decision: it moves stored `pitch_range_st`, so it ships with
  a backfill and a note in History.

**Decide:** the thresholds, the minimum pitched frames and the YIN threshold. Write them into `voice.py`
constants with a comment that cites the calibration date and numbers. Until this item is ticked, the UI labels
flat sections "provisional" and V6 doesn't ship.

**Done when** the deliberately monotone answers are flagged and at most 1 in 10 windows of the varied answers
is flagged. **Cost:** about 12 Claude requests (Drill scores each answer). You've approved this.

## V4. Word timestamps for every spoken turn, before the report request (S)

- `turns_needing_words`: any candidate turn with a saved WAV and `words is None`. No face or segments needed.
  Segments only matter for session-clock labels.
- `feedback.generate` calls `_fill_words` **before** `_ask_claude`.
- **Measure first:** time `stt.words_from_wav` (a full transcription with word timestamps) on your three WAVs
  and the calibration set. Estimate: 2-4 s per 80 s answer, so 30-45 s for a 12-answer session, added to a
  report that takes about a minute today.
- Interview replies are unaffected: the session has ended by then. Only a *new* interview started within that
  window can wait behind one word job (one turn at a time on the single MLX thread, at most a few seconds). If
  the measurement says the report step is too slow (over 45 s added), the fallback is a prefetch: after each
  reply has finished speaking, run the previous turn's words while you're answering. That's opt-in in code
  behind a constant, and never added inside `take_turn`.
- Drill (V11): run words alongside `drill.score` (`asyncio.gather`) for every audio attempt, not only with
  face moments.

**Tests:** the `turns_needing_words` cases (typed answer, no WAV, already filled, no face). A fake
`_ask_claude` sees words already filled.
**Done when** the timing is written into the `stt.words_from_wav` docstring and a new session's turns all have
`words_json`. **Cost:** none.

## V5. Usual-range baseline (XS)

`voice_stats` gains `center_hz` (median f0), `p10_st` and `p90_st` (relative to this answer's median) and
`window_range_st` (median 10 s window spread). `db.voice_baseline` returns their medians too.
`voice_fields.voice_usual` carries them. The existing keys and values are untouched.

- The graph shades **your usual band**: `p10_st..p90_st` around `center_hz`. The y axis is semitones relative
  to your usual centre, or relative to this answer's median until a baseline exists.
- V2's relative threshold uses `window_range_st`.
- `scripts.backfill_delivery` fills the new keys for stored reports and attempts.

**Tests:** new keys on synthetic tones. The baseline medians skip missing keys (old reports).
**Cost:** none.

## V6. Voice evidence and advice in the single report request (M)

**Before the call** (`feedback.generate`, after V4): `voice.turn_evidence(turns, audio_dir, baseline)` →
`{turn_idx: {stats, flags, sections: [{id, start_ms, end_ms, range_st, words}]}}`. `words` are the exact
words inside the section (up to 40), from the turn's word offsets.

**Prompt, golden-safe:**
- `_transcript(turns, evidence=None)`: with `None` it returns today's text exactly (a test pins this). With
  evidence, each spoken candidate turn gets one extra indented line:
  ```
  [#5 Candidate, 78 s] So when we moved the finance team ...
    (voice, measured: pitch range 3.1 st, your usual 5.4; flat stretch T5.1 at 0:21-0:33 of this answer,
     range 1.6 st over 12 s, words: "so we moved the finance team onto the new ledger in three weeks and then we")
  ```
- `feedback.txt` gets a `{voice_rules}` slot at the start of an existing line, the pattern `{category_notes}`
  already uses. It renders `""` when no turn has sections, so today's goldens stay byte-identical. With
  sections it renders the rules: for each listed flat stretch, add a `voice_advice` item to the answer that
  contains it, with:
  - `section`: the stretch ID.
  - `stress`: 1-3 words taken from that stretch's words that carry the point (a result, a number, a contrast,
    the action you took).
  - `say_it`: the same sentence as you said it, lightly tidied, with the stressed words in capitals.
  - `why`: one sentence that ties the measurement to the words, for example "the result 'three weeks' got the
    same pitch as the setup around it".

  The rules also say: describe how the voice behaved, never feelings or confidence. Voice never changes the
  scores (they stay content-only, so History stays comparable).
- `report_schema(brief, voice=False)`: unchanged. With `voice=True`, answers get an optional
  `voice_advice: [{section, stress[], say_it, why}]`.
- **New goldens:** `consultant-feedback-voice.txt` and `report_schema_voice.json`, rendered by `make.py` with a
  fictional evidence block. The existing goldens don't change.

**After the call** (`normalise`): keep an advice item only if its `section` exists in that answer's turns and
each stress word appears in the section's words (casefolded, punctuation stripped). Cap `say_it` and `why` at
300 characters. Drop any item matching `_STATE_RE` (confiden-, nervous, anxious, bored, unsure, shy,
enthusias-, passion-, excited, insecure, timid; logged). `answer_delivery` takes the evidence instead of
recomputing it, and stores `delivery.voice.sections`, each with its `advice` (if any), `wav_ms` and
`session_ms` edges, and its `turn_idx`.

**Also:** `scripts.rescore` builds the same evidence, so re-scores see what the report saw. `to_markdown` adds
"Flat 0:21-0:33, while saying: “…”. Stress *three weeks*: “…”" under each answer.
`scripts.backfill_delivery` fills words and sections for old reports but **never adds advice**, and leaves
sections that already have advice untouched.

**Tests:** `_transcript` unchanged with no evidence. The evidence line format. The `{voice_rules}` slot is
empty with no sections (goldens) and filled with them. Schema with and without voice. `normalise` drops an
unknown section, stress words not in the quote, and state words, and keeps valid items. A session with only
typed answers renders today's prompt.
**Done when** `pytest backend/tests` passes, including `test_golden.py`, and one real session's report has
advice for its flat stretches. **Cost:** no new requests. The prompt grows by about 60 tokens per flat stretch
(at most 6), and the output by about 80 tokens per advice item.

## V7. Routes: answer audio and voice track (S)

- `GET /sessions/{id}/turns/{idx}/audio`: `FileResponse(audio/wav)` from `ANSWERS_DIR/<id>/<idx>.wav`, with
  ranges supported. 404 if the session, the turn or the file is missing. `idx` is an int, and the path is
  built from the db row, never from the URL text.
- `GET /sessions/{id}/turns/{idx}/voice` returns:
  ```jsonc
  { "duration_ms": 81728, "frame_ms": 30,
    "pitch_st": [null, null, -1.2, ...],     // relative to usual centre (or this turn's median), 1 decimal
    "center_hz": 104.0, "usual": {"p10_st": -3.1, "p90_st": 2.6} | null,
    "segments": [{start_ms, end_ms}] | null, "joins": [{wav_ms, cut_ms}],
    "words": [{w, start_ms, end_ms}] | null, "words_pending": false,
    "sections": [...], "sections_stored": true,   // stored ones from the report when present
    "stats": {pitch_range_st, voiced_s, ...}, "reason": null | "typed" | "no_audio" | "too_short" }
  ```
  The pitch track comes from an in-memory LRU of 32 entries keyed by `(path, mtime)`. If words are missing
  and no interview is live, they're filled on the MLX thread and saved (older sessions). If an interview is
  live, `words_pending: true` and the UI shows the graph without word sync. Payload: about 15 KB for an 80 s
  turn.
- `api.ts`: `turnAudioUrl`, `getTurnVoice`, and the types.

**Tests:** route tests with a temp `DATA_DIR` and a synthetic WAV (200, range request 206, 404s, typed turn
gives `reason: "typed"`).
**Cost:** none.

## V8. Review: Voice tab, question list and empty states (M)

- Router: `#/review/<id>?tab=voice&q=<answer index>` (the review regex accepts a query string, as drill's
  does). Tabs **Feedback** (today's page, unchanged) and **Voice**. Each answer card in Feedback gets a
  "Voice ▸" button that opens that question.
- **Question list** (left, a `<Dropdown>` on narrow screens). Built from the report's answers through
  `answer_turns`, mirrored in TS. Each row shows the number, the question, `3.1 st · usual 5.4`, a flag label
  ("flat", "trailing off") and the flat count. Follow-up turns show indented under their question as
  "└ follow-up 1".
- **Detail:** the question text, the summary line (range, usual, flags, "2 flat stretches"), then one
  **turn block** per turn (main answer, then "Follow-up 1: <the interviewer's follow-up question>"). Each block
  has its own graph (V9), its transcript with word highlight, and its flat cards (V10). Only the selected
  question's blocks are mounted.
- Starting playback in the Voice tab pauses the Feedback tab's video, and the other way round.

**Empty states** (each a short muted line in place of the graph, never a blank box):

| Case | Shows |
|---|---|
| Typed answer | "You typed this answer, so there's no audio to analyse." |
| WAV missing | "No audio was saved for this answer." |
| Under 8 s voiced | Graph and playback; "Too short to measure pitch range (under 8 s of speech)." No sections. |
| No segments (older session) | Graph on audio time, labelled "audio time"; no session-clock labels or cut markers. |
| No words / words pending | Graph works; "Word timings aren't available" / "Finding word timings… (after the interview ends)". |
| No baseline (< 10 answers) | No shaded band; "Your usual range appears after 10 measured answers (n so far)." |
| Report pending / failed | List grouped by turn ("grouped by turn until the report is ready"), sections without advice. |
| Report written before this feature | Sections without advice, and "Write report again for voice advice: 1 Claude request, scores may shift." |
| Session with no audio at all | The tab shows one line: "This session has no saved answer audio." |

**Cost:** none (the rewrite button is 1 request, labelled).

## V9. VoiceGraph component (L)

**Library or plain canvas.** The data is small: 2,700 pitch points and about 1.3 M samples per 80 s turn.

| Option | Gains | Costs |
|---|---|---|
| wavesurfer.js + regions plugin | Waveform, regions, drag select | Its own audio pipeline and styling model. The pitch track, usual band, cut markers and keyboard model would still be custom on top. About 40 KB gz. |
| uPlot | Fast time series, `null` gaps | Drag means zoom by default and conflicts with select. A waveform would need a custom series. About 50 KB gz. |
| Recharts / SVG libs | Familiar | SVG with thousands of points is slow on an M1 8 GB, and it's heavy. |
| **Plain canvas (chosen)** | Full control of patterns, tokens, pointer and keyboard. 0 KB of deps. Two small layers | About 500 lines to write and own. |

**Design.** A `VoiceGraph.tsx` folder under `src/voice/` with pure helpers (`scale.ts`, `peaks.ts`,
`pitchPath.ts`, `selection.ts`).
- **Two tracks, one x scale:** a waveform (min/max peaks per pixel column, computed from the decoded
  `AudioBuffer` and cached per zoom level) and a pitch line. Speech regions on the waveform are drawn in
  `--fg` at full strength and silence at 30%. Cut joins are dashed verticals labelled "⋮ 4 s cut".
- **Pitch line:** semitones on the y axis, auto range from the 1st-99th percentile ± 2 st, gridlines every
  2 st. A 5-frame median filter for display only. Gaps of 2 frames (60 ms) or less are bridged. Longer
  unpitched runs **break the line** (never drawn at zero). Isolated pitched runs under 3 frames are dropped
  from the drawing.
- **Marks without colour:** the usual band is a light `--muted` fill with a "your usual" label. Flat stretches
  are a diagonal hatch across both tracks with a "Flat 1" tag. The selection is an inverted outline with
  handles. The playhead is a 2 px `--fg` line. A legend sits below.
- **Interaction** (Pointer Events: mouse, touch and pen alike):
  - A press that moves under 4 px seeks.
  - A drag of 4 px or more selects a range.
  - Shift+click extends the selection.
  - Two-pointer pinch, or ctrl/⌘+wheel, zooms around the pointer.
  - Wheel or horizontal swipe pans when zoomed.
  - `touch-action: pan-y` keeps vertical page scrolling.
- **Keyboard:** the tracks are one focusable `role="slider"` with `aria-valuetext` ("0:21, saying 'ledger'").
  - ←/→ 1 s, Shift+←/→ 5 s, Home/End.
  - Space play/pause.
  - Shift+arrow extends the selection.
  - L toggles loop, Esc clears.
  - +/− zoom, 0 fits.
- **Zoom:** from fit-to-turn down to 5 s visible. When zoomed, an overview strip shows the visible window as a
  draggable box.
- **Selection readout:** "0:21.0-0:33.5 (12.5 s) · pitch range 1.6 st · 74 pitched frames", or "too little
  voiced speech to measure" under 30 pitched frames. The same percentile definition as numpy (linear), in
  `selection.ts`.
- **Playback:** one shared `AudioContext`. Each turn's WAV is fetched and decoded once (80 s at 16 kHz is
  5 MB of float) and played with `AudioBufferSourceNode`, so loops (`loop`, `loopStart`, `loopEnd`) are
  sample-accurate. `<audio>` with `timeupdate` (about 4 Hz) is too coarse for loops. Buttons: Play/Pause,
  Play selection, Loop, ◀◀ 5 s.
- **Sync:** a `requestAnimationFrame` loop reads `ctx.currentTime` and redraws only the overlay canvas
  (playhead and selection). React state changes only when the current word index changes, and the
  transcript then underlines and bolds that word. Clicking a word seeks there.
- **Smooth on M1 8 GB:** a static layer redrawn only on resize, zoom or data change (ResizeObserver,
  devicePixelRatio). Peaks are cached per zoom level. No per-frame React renders. Buffers are released when
  you switch question.

**Done when** an 80 s turn scrubs, selects, loops and zooms at 60 fps in Chrome on the M1, works with
keyboard only, and works with touch in the responsive view. **Cost:** none.

## V10. Flat-section cards: play, quote, advice (S)

Under each turn's graph, one card per section:
- The header: "Flat 1 · 0:21-0:33 · 1.6 st (usual 4.2)", plus "12:41 in the interview" when segments exist.
- **▶ Hear it** (plays the section, selected on the graph; clicking the hatch does the same).
- **Exactly what you said:** all words in the section, from the word offsets, not the 15-word quote.
- **Advice** (when present): Stress *three weeks* · Say it: "We moved finance onto the new ledger in THREE
  WEEKS." · Why: the measured reason.
- Sections without advice say why ("provisional", "lower priority", or "report written before voice advice").

**Cost:** none.

## V11. Try again in Drill, with comparison (M)

- Each card and question header gets "Try again in Drill ↗". The link is
  `#/drill/<pack>?q=<question>&from=<session>~<turn>~<section>`.
- Drill reads `from`, fetches that session's report and shows a "Last time" box: "In the interview: pitch
  range 3.1 st (usual 5.4); Flat 1 at 0:21-0:33: “…”. Try stressing *three weeks*."
- The drill attempt computes voice sections on its WAV (V2) with words gathered alongside scoring (V4), and
  stores them in `result.delivery.voice.sections`.
- After the attempt: "Pitch range 3.1 → 5.0 st (usual 5.4) · flat stretches 2 → 0", next to the existing
  score delta. The comparison is behaviour only, with no verdict words.

**Tests:** drill route stores sections for an audio attempt. Router parses `from`.
**Cost:** none beyond the normal Drill request (1 per attempt, as today).

## V12 (later). Drill graphs (S)

`GET /packs/{pack}/drill/attempts/{id}/audio` and `/voice`, and `VoiceGraph` in Drill. When there's a `from`,
the old interview turn and the new attempt are stacked on the same y scale.

**Cost:** none.

## V13. Docs and end-to-end check (S)

`README.md` (the Voice tab, new routes in the API table, `scripts.voice_windows`), `SPEC.md` (the voice
analysis behaviour) and `CLAUDE.md` (`voice.py`, `src/voice/`, the conventions: behaviour words only,
sections stored and track on demand). Then run one real 20-30 minute interview and check the Voice tab
against the listening notes from V3.

**Cost:** 1 interview plus 1 report, which you'd run anyway.

## Wireframe (Voice tab)

```
┌ Session review · Implementation consultant ─────────────────── [Download…] ┐
│  [ Feedback ]  [▌Voice ]                                                    │
└─────────────────────────────────────────────────────────────────────────────┘
┌ Questions ──────────────┐ ┌ 3 · Behavioural ───────────────────────────────┐
│ 1 Tell me about yourself│ │ "Tell me about a go-live that slipped."         │
│   5.8 st · usual 5.4    │ │ Pitch range 3.1 st · your usual 5.4 · flat      │
│ 2 Why this role?        │ │ 2 flat stretches        [Try again in Drill ↗]  │
│   4.9 st                │ │                                                 │
│▌3 A go-live that slipped│ │ MAIN ANSWER · 12:41–14:02 in the interview      │
│   3.1 st · flat ×2      │ │ ▁▃▅▇▅▃▁ ▂▅▇▆▃▁ ⋮4 s cut⋮ ▃▆▇▅▂▁ ▁▃▅▆▄▂ ░░░░      │
│   └ follow-up 1         │ │ +4┤ ░░░░░░░░░░░░░░░░░░░ your usual ░░░░░░░░░    │
│ 4 Stakeholder conflict  │ │  0┤╱╲_╱‾╲  ╱╲╱‾ │▨▨▨ Flat 1 ▨▨▨▨│  ╱╲_╱  ╱‾╲    │
│   typed · no audio      │ │ -4┤ ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░    │
│ 5 Questions for us      │ │   0:00     0:20  ┃   0:40     1:00     1:20     │
│   too short             │ │                playhead                         │
└─────────────────────────┘ │ [◀◀5s] [▶ Play] [▶ Selection] [⟲ Loop]  [−][+][Fit]│
                            │ Selection 0:21.0–0:33.5 (12.5 s) · 1.6 st        │
                            │ legend: ▮ speech  ░ your usual  ▨ flat  ⋮ cut   │
                            │                                                 │
                            │ So when we moved the finance team onto the new  │
                            │ ledger in __three__ weeks and then we ...        │
                            │                                                 │
                            │ ┌ ▨ Flat 1 · 0:21–0:33 · 1.6 st (usual 4.2) ──┐ │
                            │ │ [▶ Hear it]                                   │ │
                            │ │ "so we moved the finance team onto the new    │ │
                            │ │  ledger in three weeks and then we"           │ │
                            │ │ Stress: three weeks                           │ │
                            │ │ Say it: "We moved finance onto the new ledger │ │
                            │ │  in THREE WEEKS."                             │ │
                            │ │ Why: the result got the same pitch as the     │ │
                            │ │  setup around it (1.6 st over 12 s).          │ │
                            │ │                       [Try again in Drill ↗]  │ │
                            │ └───────────────────────────────────────────────┘ │
                            │                                                 │
                            │ FOLLOW-UP 1 · "What would you do differently?"  │
                            │ (same block: graph, transcript, cards)          │
                            └─────────────────────────────────────────────────┘
```

On narrow screens the question list becomes a `<Dropdown>` above the detail, and the controls wrap onto two
rows.

## Cost summary

| Action | Claude requests |
|---|---|
| A new session's report, now with voice advice | 1 (unchanged) |
| Opening the Voice tab, graphs, playback, selection | 0 |
| Backfilling words and sections for old sessions | 0 |
| Advice for an older session ("Write report again") | 1 per session, on demand (scores may shift) |
| Calibration set (V3) | about 12 (Drill scoring) |
| Try again in Drill | 1 per attempt (as today) |

## Risks and decisions to flag

- **Sparse pitch (25% of frames)** makes the line choppy and window measures noisy. V3 checks a looser YIN
  threshold. Changing it moves stored numbers, so it needs a backfill and a History note.
- **Report latency** grows by the word-timestamp step (V4). It's measured first, with a guarded prefetch as
  the fallback. `take_turn` is never touched.
- **Advice quality** depends on the stress words being real words from the stretch. `normalise` enforces
  that, and drops state or emotion words.
- **Thresholds from one speaker.** That's intended (personal use). Relative thresholds take over once
  10 answers exist.
- **Rewriting old reports** can shift scores and fixes slightly. The button says so.
- **Recording/clock offset** (finding 8) affects today's seek buttons, not this view. It's worth its own
  small fix.

## Build order

- [x] V0. Pin today's `voice_stats` numbers (synthetic tests, plus a real-WAV snapshot kept outside the repo).
- [x] V1. `delivery.pitch_track` (shared with `_pitch_range_st`), `to_semitones`, and `voice.py`
      WAV↔session mapping and joins.
- [ ] V2. `voice.flat_sections` (10 s window, 2.5 s hop, ≥ 60 pitched frames, provisional thresholds, joins
      ≥ 2 s split, caps).
- [ ] V3. Calibration: you record 12 Drill answers; `scripts.voice_windows` gives clips, a CSV and agreement
      scores; set the constants (about 12 Claude requests).
- [ ] V4. Word timestamps for every spoken turn, filled before the report call; timing measured; Drill words
      gathered alongside scoring.
- [ ] V5. Usual-range baseline keys (`center_hz`, `p10_st`, `p90_st`, `window_range_st`) plus backfill.
- [ ] V6. Voice evidence in the transcript, `{voice_rules}` slot, `voice_advice` schema, `normalise`
      checks, new goldens, rescore/markdown/backfill.
- [ ] V7. Routes: turn audio (ranges) and turn voice track (on demand, LRU, lazy words).
- [ ] V8. Review Voice tab: tabs and routing, question list, turn blocks, empty states.
- [ ] V9. `VoiceGraph` canvas: waveform plus pitch, seek/select/loop/zoom, keyboard and touch, word sync.
- [ ] V10. Flat-section cards: hear it, exact words, advice.
- [ ] V11. Try again in Drill with "Last time" box and old-vs-new pitch comparison.
- [ ] V12 (later). Drill graphs.
- [ ] V13. Docs (README, SPEC, CLAUDE.md) and an end-to-end check on one real interview.
