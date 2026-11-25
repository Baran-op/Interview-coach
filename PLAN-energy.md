# Energy and presence plan

Today each answer's delivery stats cover what you said and how long you took: words, pace, fillers,
hedges, numbers and pauses. Nothing measures how your voice sounds or what you look like on camera.
This plan adds both, locally and without Claude requests: first the voice (H1-H3), then the face
(H4-H7), including when in the recording each problem happened. **Build order** at the end is the checklist to tick off.

Sizes are as in `PLAN.md`: **XS** a few lines, **S** one module, **M** a feature across backend and
frontend, **L** a new page with its own data.

## Why, and why in this order

- The target interviews are client-facing implementation roles, mostly on video calls. Sounding
  engaged and looking at the person you're talking to count for a lot there.
- The voice is the stronger energy signal, and the data is already there. Every answer's audio is
  saved (`data/answers/<session>/<turn>.wav` and `data/answers/drill/<attempt>.wav`, 16 kHz mono),
  so voice stats work on past sessions from day one and in Drill straight away.
- The face needs new data collection. The Interview page already opens the webcam for the recording
  (`SessionRecorder.camera`, in the `webcam` and `both` record modes), but nothing analyses it yet.

## Ground rules for every item

- Same as `PLAN.md`: one commit per item, pushed as `CLAUDE.md` describes, with `README.md`,
  `CLAUDE.md` and `SPEC.md` updated in the same commit when they're affected, and the item ticked
  in **Build order**.
- **Measure behaviour; never label emotions.** The UI says "flat", "trailing off", "looking down" or
  "still face". It never says "nervous", "unconfident" or "low energy". Facial expressions don't
  reliably reveal what someone feels; what you did is measurable and can be changed.
- **Compare with your own baseline.** Microphones, lighting, glasses and voices differ, so a flag
  means "different from your usual". Fixed thresholds apply only until there are enough answers to
  form a baseline.
- **Everything stays local.** No new Python dependencies (numpy only). One new frontend dependency
  for the face, pinned to an exact version. Video frames never leave the browser and are never
  stored; only a few numbers per answer are.
- Schema changes go in `db._EXTRA_COLUMNS`. Pure functions get unit tests in `backend/tests/`.

## 1. Voice energy

### 1a. Voice stats per answer (S)

`delivery.voice_stats(samples, rate) -> dict | None`, a pure function on a mono float array.
`audio_stats` and `voice_stats` share a WAV reader and the 30 ms voiced-frame mask, factored out of
`audio_stats` without changing its output.

- **Pitch range** (`pitch_range_st`): f0 per voiced frame with a YIN-style estimate in numpy
  (cumulative mean normalised difference, search 70-400 Hz), keeping only frames with clear
  periodicity. Octave errors are folded back toward the clip's median f0; anything still more than
  an octave away is dropped. The result is the 10th-90th percentile spread **in semitones**, so it
  doesn't depend on how high or low your voice is. This is the main "flat vs lively" number.
- **Loudness range** (`loudness_range_db`): the 10th-90th percentile spread of voiced-frame level in dB.
- **Trailing off** (`trail_off_pct`): split speech into phrases at gaps of 250 ms or more, keeping
  phrases of 1 s or longer. A phrase trails off when its last 300 ms is at least 6 dB quieter than
  the median of the rest of it. The value is the share of phrases that trail off.
- `voiced_s`: speaking time used. Returns None below 8 s of voiced speech, which is too little to judge.
- An answer that spans several turns (the answer plus its follow-ups) is measured on the turns'
  samples joined together, not by averaging per-turn percentiles.

**Auto gain caveat.** The answer audio comes through the VAD's mic stream with the browser's
echo cancellation, noise suppression and auto gain, which is vad-web's default. Auto gain flattens
slow loudness changes, so loudness range may come out compressed. Pitch is unaffected. Fast drops at
the end of a phrase should mostly survive, but 1b checks that.

**Tests:** a steady 150 Hz tone has a pitch range under 0.5 st; a 110-220 Hz glide comes out at about
9-10 st; a phrase whose amplitude falls off at the end counts as trailing off; silence and white
noise return None. Existing `audio_stats` tests still pass unchanged.

### 1b. Calibrate on real answers (XS, hand-run)

- `scripts/voice_stats.py` prints `pitch_range_st`, `loudness_range_db`, `trail_off_pct` and `voiced_s`
  for every saved answer WAV, plus each one's 10th percentile, median and 90th percentile.
- Run it, then listen to two or three answers from each end of the pitch range. Confirm the low ones
  sound flat and the high ones sound lively.
- Record the numbers and the chosen thresholds at the bottom of this file. If loudness range barely
  varies across answers (auto gain), drop it from the UI and keep only trailing off.

### 1c. Voice in the report, Drill and Review (S-M)

**Baseline:** `db.voice_baseline(limit=40, exclude_session=None)` returns the median of each voice
number over your newest 40 answers that have voice stats, from both report answers and drill
attempts, leaving out the session being scored. Below 10 answers it returns None.

**Flags** (`delivery.voice_flags(voice, baseline)`, pure, tested). The starting values below are
replaced by the 1b results:

| Flag | With a baseline | With no baseline yet |
|---|---|---|
| `flat` | pitch range under 0.75 × your usual | under 4 st |
| `lively` | pitch range over 1.25 × your usual | none |
| `trailing` | trail-off 40% or more, and at least 15 points over your usual | 40% or more |

`lively` matters: the feedback should also show when you got it right.

**Where it's computed**

- Sessions: `answer_delivery` adds `voice` (`{pitch_range_st, loudness_range_db, trail_off_pct,
  voiced_s}`), `voice_flags` and `voice_usual` (the baseline numbers, for the tooltip) to each
  answer's `delivery`. `feedback.generate` passes the baseline in.
- Drill: the attempt route already holds the WAV bytes; it adds the same three fields to
  `result["delivery"]` before `db.add_attempt`.
- `delivery_line()` appends e.g. `voice: flat` or `voice: lively, trailing off`, so the Markdown
  download gets it too.

**Backfill:** `scripts/backfill_delivery.py` recomputes `delivery` for every stored report from its
transcript and saved WAVs, and the voice fields for every drill attempt with audio. It rewrites the
stored JSON without asking Claude anything, so scores stay as they are. This gives you a baseline
on the first run.

**Frontend**

- `api.ts`: `AnswerDelivery` gains `voice`, `voice_flags` and `voice_usual`.
- Review `DeliveryLine`: the voice flags after the existing stats, highlighted the same way as a
  length flag (not red: red is for recording and errors). Hovering shows "pitch range 3.1 st (your
  usual 5.4) · trails off in 45% of phrases (usual 20%)".
- Review "Delivery" section: one session line, e.g. "Voice: flat in 3 of 7 answers, trailing off in 2".
- Drill result: the same line. The attempt history gets a pitch-range column, so you can see it move
  between attempts.

**Done when** the backfill has filled your existing reports, a new session's Review shows voice flags
on its answers with "your usual" in the tooltip, and three drill attempts of one question show their
pitch range changing in the attempt history.

**Cost:** none. **Depends on:** 1a, 1b.

## 2. Face: eye contact and expressiveness

### 2a. Face tracker in the Interview page (M)

**Setup**

- Dependency: `@mediapipe/tasks-vision`, pinned to an exact version.
- `scripts/fetch_face_model.sh` downloads `face_landmarker.task` (about 4 MB) to
  `frontend/public/models/` and copies the package's WASM files to `frontend/public/mediapipe/`, so
  it works offline. Both folders are git-ignored, like the avatar. README gets a setup step.
- If the model is missing, face stats are off and the rest works as before, the same as the avatar
  fallback. Setup shows a one-line hint.
- Setup toggle "Track eye contact and expression (stays on this computer)", saved in localStorage
  like the record mode, on by default once the model exists. It only works in the `webcam` and
  `both` record modes; with no camera it does nothing.

**`src/face/FaceTracker.ts`**

- FaceLandmarker in VIDEO mode, one face, `outputFaceBlendshapes` and
  `outputFacialTransformationMatrixes` on, GPU delegate. It reads `SessionRecorder.camera` through a
  hidden `<video>` at 8 fps (`setInterval`, like `SideBySide`).
- `startSegment("listen" | "answer")` and `endSegment()`: the Interview page marks each stretch where
  the interviewer is speaking (listen) and each answer, at the same points where the VAD is switched
  on and off.
- Per frame it keeps head yaw and pitch (from the matrix), the eye-gaze blendshapes (`eyeLookDown`,
  `eyeLookOut`, `eyeLookIn`, `eyeLookUp`) and an expression vector of the upper-face and smile shapes
  (`browInnerUp`, `browOuterUp*`, `browDown*`, `cheekSquint*`, `mouthSmile*`). Jaw and lip shapes
  are left out because they move with speech anyway.

**Calibration from listening.** While the interviewer is speaking, you're looking at the screen, so
the median head pose over the listen segments is "looking at the screen" for this session. That
handles camera position and screen layout with no calibration step. The intro gives enough listen
frames (at least 3 s) before the first answer.

**Per-answer stats**

- `on_screen_pct`: frames with head pose within ±12° yaw and ±10° pitch of the listen centre and
  no strong look-away gaze. "On screen" counts as eye contact, because in a real video interview you
  look at the interviewer's face, not the lens.
- `looked_down_pct`: frames well below centre (head pitch or `eyeLookDown`). This is the actionable
  one: it usually means reading notes.
- `expressiveness`: the mean standard deviation of the expression shapes across the answer, times 100.
- `face_found_pct` and `frames`. If the face was found in under half the frames, the stats are null.

**When it happened.** The totals say something is off; the timing lets you watch it. The tracker
also records:

- `away_spans`: `[{start_ms, end_ms, kind}]` on the session clock (Interview's `clockNow()`, the same
  clock as the turn ▶ markers in Review), so a span lines up with the recording.
  - `kind: "down"`: off screen and below centre for **3 s or more**. This is the reading-notes signal.
  - `kind: "away"`: off screen to the side or above for **5 s or more**. Brief glances up or sideways
    while thinking are normal and good speakers do it too, so shorter ones are never flagged.
    Flagging every glance would teach you to stare at the screen.
  - Dips under 0.5 s are bridged so one look doesn't split into several. At most 20 spans per answer.
- `expr_windows`: `{start_ms, values}`, the expressiveness of each 5 s window of the answer. The
  backend compares them with your baseline to find long still stretches (2b), because the browser
  doesn't know your baseline.

**Storage**

- Interview posts `face` (JSON) with each answer: a form field next to `audio`, or a key in the typed
  JSON body.
- `turns.face_json TEXT` in `_EXTRA_COLUMNS`. `take_turn` validates it (known keys only, numbers
  clamped to range, spans inside the turn's time range, lists and size capped) and stores it after
  `db.add_turn`.

**Performance check.** The 8 GB M1 is also running Whisper, Kokoro and the avatar. Log the tracker's
frame time. If it averages over 40 ms or the avatar visibly stutters, drop to 5 fps; if that's still
not enough, use the CPU delegate.

**Done when** a session with the camera on stores `face_json` for each spoken answer, a session in
audio mode stores nothing and behaves as before, and the avatar runs as smoothly as without the tracker.

**Cost:** none.

### 2b. Face in the report and Review (S)

- `answer_delivery` combines the face stats of an answer's turns, weighted by frames, into
  `delivery.face`.
- `db.face_baseline()` works like `voice_baseline`, on `expressiveness` (eye contact has absolute
  meaning, so it doesn't need one).
- Flags (`delivery.face_flags`, pure, tested):
  - `looking_down`: looked down 30% or more of the answer;
  - `low_eye_contact`: on screen under 60%;
  - `still`: expressiveness under 0.7 × your usual (no flag until there's a baseline).
- `delivery_line()` and Review: e.g. `eye contact 58% · mostly looking down · still face`, with the
  same tooltip and highlighting as the voice flags. The Review "Delivery" section gets a session line.

**Where it went wrong** (`delivery.face_moments`, pure, tested)

- `delivery.face.moments`: the answer's `away_spans`, plus `still` stretches: 20 s or more of
  consecutive `expr_windows` under half your usual expressiveness. A still face is a stretch across
  a whole story, not a single moment, so it's only marked when it's long. With no baseline yet,
  there are no still moments.
- Review player: each moment is a shaded band on the recording's timeline, under the existing turn
  markers, in the neutral highlight tone (not red). Hovering shows its label.
- Under each answer: a list such as "Looked down 0:42–0:51 (9 s) ▶" or "Still face 2:10–2:38 ▶".
  Clicking ▶ seeks the recording there, the way the turn markers already do (`seek()` in `Review.tsx`).
- `to_markdown()` lists the moments with their times under each answer.
- You need the webcam in the recording to watch yourself. In the `avatar` record mode the moments
  are still listed, but the video shows the avatar; Review says so once, above the list.

**Done when** a session recorded with the camera shows eye contact on every answer in Review and the
Markdown download, and an answer where you deliberately read from notes for about 10 s is flagged
`looking_down`, with a band at that point in the recording. Clicking it plays that moment, and a 2 s
glance away elsewhere isn't marked.

**Cost:** none. **Depends on:** 2a.

### 2c. What you were saying at that moment (S-M)

Each moment shows the words you were saying, e.g. "Looked down 0:42–0:51, while saying: *the go-live
slipped by two weeks because…*". Patterns show up quickly this way, such as always looking down
when you get to numbers or to the outcome.

- `stt.transcribe` asks mlx-whisper for word timestamps (`word_timestamps=True`) and also returns the
  words with their offsets in the WAV. Stored in `turns.words_json`. Measure the extra transcription
  time on a 60 s answer; if it's over about 0.5 s, compute the words in the report step instead,
  from the saved WAVs.
- The turn audio isn't continuous: for a held turn the VAD drops long pauses, so a WAV offset isn't a
  session time. `TurnListener` records the session-clock start and end of each speech segment it
  keeps, and Interview posts them as `segments` with the answer. Stored in `turns.segments_json`.
- `delivery.words_at(turn, start_ms, end_ms)` (pure, tested) maps the span through the segments to
  WAV offsets and returns those words, capped at about 15 with "…". If a turn has no segments
  (typed answers, older sessions), there's no quote.
- Review and `to_markdown()` show the quote under each moment.

**Done when** the moments in a new session show the words you were saying, checked against the
recording for three moments, and a typed answer or an older session still renders without quotes.

**Cost:** none. **Depends on:** 2b.

### 2d. Face in Drill (S)

- Drill opens the camera only when the Setup toggle is on and the model exists, with a small
  self-view so you can check framing.
- The same `FaceTracker`: the question being read out is a listen segment, and your answer is an
  answer segment. `face` is posted with the attempt and added to the attempt's `delivery`.
- The attempt history gets an eye-contact column next to pitch range.
- Drill doesn't record video, so the moments are listed with their time into the answer (and the
  quote, from 2c) but have no ▶.

**Done when** three drill attempts of one question show eye contact and pitch range in the attempt
history, and the camera is off whenever the toggle is off.

**Cost:** none. **Depends on:** 2b; 2c for quotes.

## 3. Trends over time (S, optional)

History gets a small "Delivery over time" table per pack: session date, median pitch range,
trailing-off share and median eye contact. Partial sessions are left out, as they are in the score trend.

## Not in scope

- Emotion or confidence labels, or any single "energy score".
- Smile counts, blink rate and posture. These are noisy and hard to act on.
- Sending audio, video frames or these stats to Claude. These items are local only. Giving the
  flags to the report prompt, so the top fixes can mention them, is worth revisiting after a few
  weeks of data.
- Storing video frames or landmarks. Only the per-answer numbers and moment times are kept.
- Timeline moments for the voice flags (flat stretches, trailing off). The `segments` from 2c make
  them possible later; they're left out for now to keep the first version small.

## Cost summary

| Item | Claude requests |
|---|---|
| Everything in this plan | none |

## Build order

One commit per line. The voice items come first: they work on existing data and need no new
dependency.

**Phase H: energy and presence**

- [x] H1. 1a `delivery.voice_stats` with tests, and `scripts/voice_stats.py` (from 1b)
- [x] H2. 1b Run the calibration on real answers; record thresholds below (no per-answer WAVs existed yet: starting thresholds kept, rerun once data exists)
- [x] H3. 1c Voice baseline, flags, report, Drill, Review, and `scripts/backfill_delivery.py`
- [x] H4. 2a Face tracker, model fetch script, Setup toggle, `turns.face_json` (built; camera and performance check still to verify by hand, see "H4 still to verify")
- [x] H5. 2b Face stats in the report and Review, with timed moments on the recording (built; needs real camera data to verify, see "H5 still to verify")
- [x] H6. 2c What you were saying at each moment (word timestamps, VAD segments) (built; the quotes need a real webcam session to check, see "H6 still to verify")
- [ ] H7. 2d Face stats in Drill
- [ ] H8. 3 Delivery trends in History (optional)

## Calibration results

H2 run (`python -m scripts.voice_stats`): **0 answers measured, 0 skipped.** `data/answers/` does not
exist yet; `data/` holds only `interview.db` and two full-session recordings in `data/recordings/`
(.webm, not per-answer WAVs). So there is no distribution (p10, median and p90 are all unavailable).

Decisions, because the data is far below the ~10 answers needed:

- Keep the starting thresholds from 1c: `flat` under 0.75 x your usual (4 st with no baseline),
  `lively` over 1.25 x your usual, `trailing` at 40% or more and 15 points over your usual.
- Loudness range stays in for now. With no data there is no evidence either way on the auto-gain
  caveat, so rerun this and drop it from the UI if its p10 to p90 spread is only a few dB.
- No bug found in `voice_stats`; nothing could be exercised on real audio beyond the unit tests.

Still to do by the user:

1. Record some answers (Interview or Drill) so `data/answers/` fills up, until there are 10 or more.
2. Rerun `python -m scripts.voice_stats` and paste the p10 / median / p90 per number here.
3. By-ear check: listen to 2-3 WAVs at each end of the pitch range (the script prints each file's
   `pitch_range_st`; take the lowest and highest ones), confirm the low ones sound flat and the high
   ones lively, then adjust the thresholds above. Not done: it cannot be done without the audio.

## H4 still to verify

Built and type-checked, but never run with a real camera:

1. `scripts/fetch_face_model.sh` has been run (model and WASM present, git-ignored). Start an interview in
   *Webcam + audio* with the Setup toggle on; the console should log `[face] N ms/frame` every 10 s. If it
   averages over 40 ms or the avatar stutters, drop `FPS` in `FaceTracker.ts` to 5, then try the CPU delegate.
2. Finish a session and check `turns.face_json` is filled for each spoken answer, and empty in audio mode.
3. Head pitch sign and thresholds (`LIMITS` in `src/face/stats.ts`) are starting values: read from notes for
   10 s and confirm a `down` span appears; a 2 s glance sideways must not. The pure functions were only
   exercised with synthetic frames (no frontend test runner exists, so `stats.ts` has no committed tests).
4. `expr_windows` entries are `{start_ms, value}` (one number per 5 s window), not a `values` list.

## H5 still to verify

Built, unit-tested on synthetic numbers and type-checked, never seen with real camera data:

1. Record a webcam session, finish it, and check each answer's Review row shows `eye contact N%`, with the tooltip
   ("on screen ..., looked down ..., expressiveness ... (your usual ...)").
2. Read from notes for about 10 s: that answer should be flagged `mostly looking down`, show a `Looked down` moment
   with a working ▶, and a band at that point under the player. A 2 s glance away must not appear.
3. `still` flags and `Still face` moments need `db.face_baseline` (10 answers with expressiveness); run
   `python -m scripts.backfill_delivery` after collecting them. The 0.7x and half-of-usual thresholds are starting values.
4. Avatar-mode note: Review decides from the current Setup record-mode preference (the mode used is not stored per
   session), so it can be wrong for an older session.
5. The timeline bands sit just above the turn markers, not below them.

## H6 still to verify

Built and unit-tested (`words_at`, `clean_segments`), type-checked, never seen with a real session:

1. Word timestamps measured with `mlx_whisper` on this machine (41 s synthetic speech, warm): 4.5 s without, 5.3 s with,
   so about +0.75 s (roughly 1 s per minute). That is over the 0.5 s budget, so words are NOT taken in `stt.transcribe`;
   `feedback._fill_words` gets them from the saved WAVs in the report step (only for turns with segments and face data)
   and stores them in `turns.words_json`. Adds a few seconds per answer to report time.
2. `TurnListener` times each segment as "now minus its audio length" when vad-web hands it over (end = callback time,
   including the redemption silence and the 300 ms pre-pad). Check by hand that a quote matches the recording for three
   moments; if quotes are consistently early or late, the offset is here.
3. Run `python -m scripts.backfill_delivery` to add quotes to sessions recorded after this change (older ones have no segments).
