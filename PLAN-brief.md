# Interview brief plan

Today a pack fits one kind of interview: a corporate job application. It has three fixed text boxes
(`jd`, `profile`, `company_notes`), one interview script (`prompts/interviewer.txt`), four fixed criteria
with STAR as the structure rule, and a fixed category list (`categories.CATEGORIES`). This plan lets
the same app coach any profession. You add materials of any kind, one Claude pass turns them into an
**interview brief**, you review and edit it, and everything downstream reads the brief: the
interviewer, scoring, prep, Drill, answer lengths and History. **Build order** at the end is the
checklist to tick off.

Sizes: **XS** a few lines, **S** one module, **M** a feature across backend and frontend, **L** a new
page with its own data.

## Why, and why this shape

- A doctor preparing for specialty training sits timed stations (a clinical scenario, ethics,
  prioritisation, a portfolio review) marked against a published mark scheme. A teacher or nurse has
  their own format. New input boxes aren't enough on their own: the interview's **format** and
  **scoring** have to change too.
- Format and scoring have to stay **stable across sessions**. Otherwise History trends, previous-fixes
  tracking and Drill's attempt-by-attempt comparison stop meaning anything. So the brief is reviewed
  once, stored, frozen where it matters, and snapshotted on each session.
- The brief is a cache, built the same way as the prep sheet (`prep.py`): a `source_hash` of the
  inputs, a cleaning function, one `claude_json.ask_json` call and its own table.

## Ground rules for every item

- One commit per item, pushed as `CLAUDE.md` describes, with `README.md`, `SPEC.md` and `CLAUDE.md`
  updated in the same commit when they're affected, and the item ticked in **Build order**.
- **No brief means today's behaviour, byte for byte.** A built-in default brief reproduces today's
  prompts exactly. I0 freezes today's rendered prompts as golden files, and later items must keep those
  tests passing. Old packs, stored reports and drill attempts are never rewritten or re-scored.
- **Never invent a mark scheme or facts.** Anything the brief step guesses rather than reads from the
  materials is listed as an assumption with a question for you.
- **Nothing downstream reads the raw materials.** Only the brief step and the Whisper hint words read
  them. The single exception is a pack with no brief, which reads the legacy three-field view exactly
  as today (see 2d).
- **Every action that spends a Claude request says so on its button or confirm** before spending it.
- Schema changes go through `db.SCHEMA` and `db._EXTRA_COLUMNS`. Pure functions get unit tests in
  `backend/tests/`. All test materials are fictional; nothing from `data/` goes into the repo.
- UI: monochrome tokens, `<Dropdown>` inside `<div className="field">`, `<details className="disclosure">`
  with `<Chevron />`. Face data stays numbers only (unchanged by this plan).
- Personal, localhost use only.

## 0. Golden prompts (XS)

Before anything changes, `backend/tests/golden/` stores today's rendered prompts for two fictional
packs (an implementation consultant and a product analyst; short invented JD, CV and notes):

- Interviewer system prompt for stages `screen`, `full` and `final`, untimed and timed (`minutes: 30`),
  with and without a `history` block (a fictional `pack_report_history` result).
- Feedback system prompt with and without previous fixes. Drill system prompt. Prep system prompt.
- The feedback `REPORT_SCHEMA` and the drill `SCHEMA` as JSON.

`test_golden.py` renders each one through the public functions (`brain.build_system_prompt`,
`feedback._system_prompt`, `drill.system_prompt`, `prep.system_prompt`) and compares it byte for byte.
`python -m backend.tests.golden.make` regenerates the files, but only by hand: a golden file should
change only on purpose.

**Cost:** none.

## 1. Materials

### 1a. Data (S)

New table:

```sql
CREATE TABLE IF NOT EXISTS materials (
    id TEXT PRIMARY KEY,
    pack_id TEXT NOT NULL REFERENCES packs(id),
    position INTEGER NOT NULL,
    name TEXT NOT NULL,          -- "Job advert", "Person specification", "CV", "Mark scheme"...
    kind TEXT NOT NULL,          -- job | candidate | organisation | format | other
    source TEXT NOT NULL,        -- paste | pdf | text_file | research
    text TEXT NOT NULL,
    created_at INTEGER NOT NULL
);
```

- Only the extracted text is stored, never the uploaded file.
- `kind` is the one piece of structure kept. It tells the brief step what each material is, and it
  lets a pack with no brief map materials back onto today's three slots (2d). Setup guesses it from
  the file name ("cv", "resume" → candidate; "mark scheme", "person spec", "station" → format; and so
  on), and you can change it with a `<Dropdown>`.
- **Legacy packs** (no materials rows) are shown as up to three read-only synthetic materials built
  from `jd` (job, "Job description"), `profile` (candidate, "CV") and `company_notes` (organisation,
  "Company notes"). `db.pack_materials(pack)` returns real rows if there are any, or else the synthetic
  ones. Nothing is written to the database until you save the pack. Saving then stores the list as
  real rows and leaves the old columns untouched, so their text is still there.
- `db.delete_pack` also deletes the pack's materials and brief.

### 1b. API (S)

- `PackIn`: `jd` is no longer required (`jd: str = ""`), and a new field
  `materials: list[MaterialIn] | None = None` is added. `None` means an old client, so the legacy
  fields are kept as they are. A list replaces the pack's materials.
  `MaterialIn = {name 1-80 chars, kind, source, text 1+ chars}`. A pack needs at least one material
  with text, or a `jd` (the 422 message says so).
- **Size caps:** 10 MB per PDF (unchanged), 30 MB per upload batch, and **150,000 characters of text per
  pack** (about 37k tokens, which fits the brief call comfortably). The pack PUT returns 413 when the
  total is over the cap. Setup shows a running total, e.g. "41,200 / 150,000 characters".
- `/extract-text` takes `files: list[UploadFile]` (one file still works) and returns
  `[{name, chars, text} | {name, error}]` per file. It reads `.pdf` with `_pdf_text` and `.txt` / `.md`
  as UTF-8. There's no OCR: a PDF with no text gets the existing "No text found in the PDF (is it a
  scan?). Paste the text instead." message, for that file only.
- `GET /packs/{id}` adds `materials` (with `synthetic: true` for legacy packs) and `brief_meta`
  (`{exists, kind, total_minutes, stations: [{name, minutes}], stale}`), so Setup and Interview don't
  need a second request.
- `POST /research` is unchanged. Setup adds its result as a material (`kind: organisation`,
  `source: research`, named "Web research: <company>", with the source links appended to the text).

### 1c. Whisper hint words (XS)

`stt.keyword_prompt(role, company, texts)` takes a list of texts in priority order: candidate
materials, then job, then format, organisation and other materials. It keeps the existing ~180-token
budget. For a legacy pack, the order is CV, JD, then company notes, so the hint starts exactly as it
does today. Company notes are new to the hint, but they only add words when the budget has room left.

### 1d. Setup (M)

- The three boxes become one **Materials** list. Each row shows the name (editable), a kind
  `<Dropdown>`, the source, the character count, a disclosure to read and edit the text, and Remove.
- Below the list: **Upload files** (`multiple`, `.pdf,.txt,.md`), **Paste text** (adds an empty row
  named "Notes"), **Draft from the web** ("1 Claude request, uses web search": the existing confirm,
  which now adds a material instead of replacing the notes).
- Each file that fails shows its own error on its row. The other files still load.
- The CV prefill keeps working: a new pack starts with copies of the latest pack's candidate materials.
- Role, company and title stay where they are. The pack summary line is unchanged until a brief exists
  (then 5c).

**Done when** an old pack opens showing its three materials, saves with no changes, and its golden
prompts are unchanged. A new pack can be made from two PDFs and a pasted note.
**Cost:** none (research as today: 1 request with web tools).

## 2. The brief

### 2a. Schema (final)

```jsonc
{
  "version": 1,
  "field": "Medicine",                 // ≤60 chars
  "role": "Specialty trainee (ST1)",   // ≤80
  "organisation": "…",                 // ≤80, "" if unknown
  "level": "Entry to specialty training", // ≤60
  "format": {
    "kind": "conversation",            // conversation | stations | panel
    "summary": "…",                    // ≤400, one paragraph you can read at a glance
    "total_minutes": 30,               // 5-180 or null; stations: sum of station minutes
    "opening": true,                   // start with "tell me about yourself"
    "candidate_questions": true,       // end with "any questions for us?"
    "panel": [{"name": "…", "role": "…", "focus": "…"}],   // panel kind only, 2-4 members
    "stations": [{                     // stations kind only, 1-8
      "key": "clinical",               // slug, unique
      "name": "Clinical scenario",
      "minutes": 10,                   // 1-60
      "category": "clinical",          // a key from categories
      "brief": "…",                    // ≤600: what the station tests and how it runs
      "scenario": "…"                  // ≤1500 or null: the prompt the interviewer reads out
    }]
  },
  "criteria": [{                       // 3-6
    "key": "relevance",                // slug, unique
    "name": "Relevance",
    "description": "…",                // what it rewards
    "anchors": {"1": "…", "3": "…", "5": "…"},
    "source": "default",               // provided | inferred | default
    "scale_note": ""                   // provided only: how the scheme's scale maps onto 1-5
  }],
  "categories": [{                     // 2-10, always includes "other"
    "key": "behavioural",
    "label": "Behavioural",
    "description": "past experience, competency questions",
    "structure_hint": "…",             // expected shape of an answer; STAR only where it fits
    "scoring_note": "",                // extra scoring rule for this category (today: roleplay, logistics)
    "target_seconds": [90, 150]        // or null
  }],
  "competencies": ["…"],               // ≤12, 2-5 words each
  "likely_questions": [{"question": "…", "category": "…", "why": "…"}],   // ≤15
  "probes": ["…"],                     // ≤8, gaps a sceptical interviewer would test
  "facts": ["…"],                      // ≤15, organisation facts from the materials only
  "candidate_summary": "…",            // ≤1,200 chars, for the interviewer prompt
  "candidate_facts": "…",              // ≤4,000 chars, for scoring, prep and better answers (see below)
  "assumptions": [{"id": "a1", "section": "criteria", "text": "…", "question": "…",
                   "answer": "", "confirmed": false}]
}
```

Changes from the starting point, and why:

- **`candidate_facts` (new).** The prep sheet's stories and the report's "better answer" are told to
  use "only facts from the CV". A 1,200-character summary would starve them, and they would either get
  vaguer or fall back to reading the raw CV, which breaks the "nothing downstream reads the materials"
  rule. So the brief keeps two versions: `candidate_summary` (short, for the voice interviewer's
  latency) and `candidate_facts` (a factual list of roles, projects, tools and numbers taken from the
  candidate materials, which you can review). Report, Drill and prep read `candidate_facts`.
- **`criteria[].source` adds `default`.** "Inferred" would wrongly suggest Claude made up the four
  defaults. `default` means "no mark scheme was provided, so these are the app's four, word for word".
  The Brief page says so.
- **`scale_note`.** When a scheme scores 1-4 or uses words (e.g. "unsatisfactory / borderline /
  satisfactory / good / excellent"), this says how it maps onto 1-5, so you can check the mapping.
  Criteria stay equally weighted. If the scheme weights its domains, that becomes an assumption ("the
  scheme weights X double; the app averages equally").
- **`categories[].scoring_note`.** Today's prompts have special scoring paragraphs for roleplay and
  logistics. They become those categories' `scoring_note`, which is how the default brief reproduces
  them (2d).
- **`stations[].key` and `panel`.** Stations need stable keys for the report and History. The panel
  kind needs named members. There's still one avatar and one voice: the interviewer hands over in
  speech ("I'll pass you to Dr Shah, who leads on teaching").
- **`assumptions[].answer` / `confirmed`.** Your reply to each question is stored with it, and
  Regenerate sends those replies along (2c).

`brief.clean_brief(raw, frozen=None)` (pure, tested) coerces the JSON. It trims and caps every string,
slugifies keys and removes duplicate keys, clamps minutes, makes sure `other` exists, maps a station's
unknown category to `other`, removes `stations` unless kind is stations and `panel` unless kind is
panel, and sets `total_minutes` to the station sum for stations. It keeps 3-6 criteria: with fewer than
3, the default four are used, and an assumption is added that says so. The caps keep the brief's
rendered block under 8,000 characters (tested on a maximum-size brief), which is about the size of a
typical JD + CV + notes today.

### 2b. Generation (M)

- `brief.py`: `SCHEMA`, `clean_brief`, `source_hash(materials)` (SHA-1 over each material's kind,
  name and stripped text, in order), `default_brief(pack)`, `criteria_hash(criteria)`,
  `system_prompt(materials, answers)`, `async write(pack, materials)`.
- `prompts/brief.txt` tells Claude:
  - Read every material by its name and kind.
  - Quote a provided mark scheme's wording in the criteria. Map its scale onto 1-5 in `scale_note`.
  - **With no mark scheme, return the default criteria exactly as given in the prompt** (they're
    pasted into it from `default_brief`), with `source: default`.
  - Only use a structure such as STAR in `structure_hint` where it fits the category. Don't name
    domain frameworks unless the materials name them.
  - `facts` come only from the materials.
  - List as an assumption everything not read directly from the materials: format, timings, number of
    stations, `opening` / `candidate_questions`, criteria (when inferred) and level.
- Table:

```sql
CREATE TABLE IF NOT EXISTS briefs (
    pack_id TEXT PRIMARY KEY REFERENCES packs(id),
    brief_json TEXT NOT NULL,
    source_hash TEXT NOT NULL,     -- materials hash when last generated
    criteria_hash TEXT NOT NULL,
    origin TEXT NOT NULL,          -- generated | edited
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);
```

- Routes:
  - `GET /packs/{id}/brief` returns `{brief, is_default, stale, frozen, origin, updated_at}`. With no
    saved brief, it returns `default_brief(pack)` with `is_default: true`.
  - `POST /packs/{id}/brief` (re)generates the brief: **1 Claude request**. Body
    `{replace_criteria: bool = false}`.
  - `PUT /packs/{id}/brief` saves your edits, with no Claude request. Body `{brief, fresh_start: bool}`.
  - `DELETE /packs/{id}/brief` goes back to the default brief.
- Model: `BRIEF_MODEL`, falling back to `FEEDBACK_MODEL`, then `INTERVIEWER_MODEL`.

### 2c. Your answers feed regeneration (XS)

Your answers to assumptions (`answer`, `confirmed`) are passed to the next `POST` as an extra block,
"The candidate's answers to your earlier questions". Claude must follow them. That lets you correct
"I assumed 3 stations of 10 minutes" with a sentence instead of editing the format by hand.

### 2d. The default brief (S)

`default_brief(pack)` is the brief that reproduces today exactly:

- `format`: `kind: conversation`, `opening: true`, `candidate_questions: true`,
  `total_minutes: options.minutes`.
- `criteria`: today's four. Their `description` and `anchors` hold the exact text from today's
  `feedback.txt` (the description line and the 1/3/5 line), `source: default`.
- `categories`: today's eight, in today's order, with `description` set to the words in today's
  category sentence ("intro (tell me about yourself)" → `description: "tell me about yourself"`),
  `target_seconds` from today's `TARGET_SECONDS` (intro 60-90, motivation 45-90, behavioural 90-150,
  the rest null), and `scoring_note` set to today's roleplay and logistics paragraphs word for word.
- `competencies`, `likely_questions`, `probes`, `facts` and `assumptions` are empty.
  `candidate_summary` and `candidate_facts` are empty: the default brief never replaces the raw-text
  slots.
- **Default mode** (`is_default`): prompts render the legacy template slots `{jd}`, `{profile}` and
  `{company_notes}` from the materials, mapped by kind: `jd` = job + format + other materials,
  `profile` = candidate, `company_notes` = organisation. One material per slot is inserted as is (so a
  legacy pack is byte-identical). With several, each one gets a `### <name>` header. This is the one
  place downstream that reads materials, and only because no brief exists.

**How the prompts become renderable (the core of I4/I5).** Each prompt keeps its wording but swaps
the hard-coded blocks for slots that render functions in `brief.py` fill:

| Prompt | Slot | Rendered from |
|---|---|---|
| feedback, drill | `{criteria_block}` | `criteria` (one shared `render_criteria` produces the exact lines `  - relevance: …\n    1 = … 3 = … 5 = …`) |
| feedback, drill | `{json_scores}` | criteria keys, for the example JSON |
| feedback | `{category_sentence}` | `categories` (`"one of intro (tell me about yourself), …"`) |
| feedback | `{category_notes}` | categories with a `scoring_note` |
| feedback | `{entries_rule}` | format: today's "one entry per MAIN question …" sentence, or one entry per station |
| interviewer | `{context}` | default: today's JD / CV / notes block. Brief: the rendered brief block (2e) |
| interviewer | `{script}` | conversation: today's five steps word for word. Stations / panel: 5b |
| interviewer | `{category_list}` | the "The report files each main question under one category: …" sentence |
| prep | `{context}`, `{sections}` | default: today's text. Brief: brief block + per-section rules (6a) |

The golden tests from I0 are the proof. With the default brief, every rendered prompt and schema is
byte-identical to today's.

### 2e. What the interviewer sees with a brief (S)

The `{context}` block is about the same size as today and is built only from the brief: field, role,
organisation and level; the format summary; competencies; up to 8 likely questions (as ideas, not a
script); probes ("what a sceptical interviewer would probe", replacing the instruction to derive them
from CV vs JD); facts (for answering the candidate's questions); and `candidate_summary`. Criteria are
not included: the interviewer doesn't score.

**Done when** a fictional pack's brief generates, cleans and saves; `GET` on a legacy pack returns the
default brief; tests cover `clean_brief` (caps, slugs, missing `other`, too few criteria, stations sum),
`source_hash` (order, kind and whitespace), `criteria_hash` and `default_brief` (texts equal the
golden prompts' criteria lines).
**Cost:** 1 request per generate or regenerate.

## 3. Brief page (L)

Route `#/brief/<pack id>`, reached from Setup ("Interview brief" next to Prep) and from the save
flow: after a new pack is saved, Setup offers "Write the interview brief (1 Claude request)" or
"Skip: use the standard interview".

- **Header:** origin (generated / edited / standard), last updated, and a **stale notice** when the
  materials hash no longer matches: "Your materials changed since this brief was written.
  Regenerate (1 Claude request) or keep it."
- **To confirm** (top, highlighted with the existing flag style, not red): each assumption with its
  question, an answer box and Confirm. The count shows in Setup ("3 assumptions to confirm"). Starting
  an interview with unconfirmed ones is allowed.
- **Sections** as `<details className="disclosure">`: Format (kind `<Dropdown>`, minutes, opening and
  candidate-questions toggles, an editable station list), Criteria (name, description, anchors, source
  badge, scale note), Categories (label, description, structure hint, target seconds), What they'll
  probe (competencies, probes, likely questions), Organisation facts, About you (summary and facts).
- **Freeze warning:** when the pack has a scored session and you change criteria or categories, Save
  asks: "This pack has N scored sessions. Changing criteria or categories starts History comparisons
  fresh: earlier sessions stay as they were, but trends and 'since last time' only compare sessions
  scored the same way." Confirming sends `fresh_start: true`.
- **Regenerate** says "1 Claude request. Your unsaved edits are lost; your answers to the questions
  above are sent along." On a frozen pack, a checkbox "Also replace criteria and categories (History
  starts fresh)" is off by default (section 4).
- **Use the standard interview** (DELETE) goes back to the default brief, with a confirm.

**Done when** a brief can be generated, edited and saved; assumptions confirm; a materials edit shows
the stale notice; editing criteria on a pack with a scored session warns first.
**Cost:** 1 request per regenerate; editing is free.

## 4. Criteria freezing and per-report rubrics

### The rule

- A pack's **rubric** is its criteria plus its categories. `criteria_hash` is the SHA-1 of the
  canonical JSON of `[(key, name, description, anchors)]`. `rubric_hash` adds `[(key, description)]`
  of the categories.
- The rubric is **frozen** once the pack has a ready report. The frozen rubric is the one on the latest
  ready report, or the default rubric for reports that don't carry one.
- `PUT /packs/{id}/brief` with a different rubric returns 409 unless `fresh_start: true`.
- `POST /packs/{id}/brief` on a frozen pack keeps the frozen criteria and categories (`clean_brief`
  overwrites them and adds an assumption saying so), unless `replace_criteria: true`.
- **Every session snapshots its brief.** `sessions.brief_json` (new column) is written at session
  start, or left null for the default brief. The report step, including "Regenerate report", scores
  with the session's snapshot. Editing the brief later never changes how an old session is scored.
  Null means the default brief, which is exactly today.

### On each new report (and drill attempt)

- The report JSON gets `criteria: [{key, name}]`, `criteria_hash`, `categories: [{key, label,
  target_seconds}]` and, for stations, `station` on each answer. These are new keys only.
- Drill results get `criteria` and `criteria_hash` too.
- **Reports and attempts without them mean the default four and the default eight.**
  `brief.report_rubric(report)` returns the stored rubric or the default, so every reader goes through
  one function. Nothing is migrated.

### Readers that change

- `feedback`: `REPORT_SCHEMA` is built from the session's criteria and category keys (a
  `report_schema(brief)` function; the default output equals today's schema, which is golden-tested).
  `normalise` scores the brief's criteria and resolves categories against the brief's keys.
- `categories.resolve_category(category, question, allowed=CATEGORIES)` falls back to the question text
  only when `intro` / `motivation` are among the allowed keys, and otherwise to `other`.
  `db.get_report` resolves against the report's own categories.
- **`db._session_summary`** today reads `a["scores"][c] for c in db.CRITERIA` and would raise a
  KeyError on a report scored with other criteria. It reads the report's criteria instead and adds
  `criteria_hash` and `criteria_names`.
- `db.pack_report_history` (interviewer history and previous fixes) is unchanged: fixes are text, and
  the questions keep their averages.
- `delivery.answer_delivery` takes target seconds from the report's categories. `TARGET_SECONDS`
  remains as the default brief's values. `scripts/backfill_delivery` uses `report_rubric(report)`, so
  old reports get the same targets as today.
- `scripts/rescore` uses the session's rubric.

### Frontend

- `api.ts`: `Criterion` becomes `string`, and reports and attempts carry `criteria: {key, name}[]`
  (filled with the default four by `reportCriteria(report)` when missing). `CATEGORY_LABEL` stays for
  the known keys. `categoryLabel(key, report)` prefers the report's label.
- Review, Drill and History render criteria from the report or attempt, never from a hard-coded list.
- **History** only compares sessions with the same `criteria_hash` as the latest one. Older ones are
  listed under "Scored with earlier criteria" without trend lines. The Review delta ("vs last
  session") skips sessions with a different hash.
- Category chart: known categories keep their colours (fixed by their position in `CATEGORY_LABEL`,
  not by sort order). Unknown categories are drawn in `--muted` with a dashed line and labelled from the
  report.

## 5. Interview format from the brief

### 5a. Conversation (S)

The conversation script is today's five steps. With the default brief, the prompt is byte-identical
(golden). With a generated conversation brief, the script is the same, but:
- the `{context}` block is the brief (2e);
- step 1 drops "Tell me about yourself" when `opening` is false;
- step 4 is skipped when `candidate_questions` is false;
- the probes come from `probes` instead of "silently note what a sceptical hiring manager would probe".

Stage and interview type still apply.

### 5b. Stations (M)

- The `{script}` for stations: a short welcome; then for each station in order, announce it, starting
  with the tag `[station N]` (stripped like the expression tags, never spoken); read the scenario (or
  set it up from the station brief); question and follow up for the station's time; then say time is
  up and move on, finished or not. Close after the last station with `[END]`. With
  `candidate_questions` on, the candidate may ask questions before the close.
- **Tracking:** `parse_tags` returns `station` when the tag is present. The server keeps
  `live.station` and when it started. `turns.station` (new column) records it on every turn.
- **Time notes:** `time_note(opts, started, now, station=None, plan=None)` becomes
  "(Time: station 2 of 3, 7 of 8 min used; 18 of 30 min overall.)". If the interviewer forgets the tag,
  the station is inferred from the clock and the plan (pure function `station_at(plan, elapsed)`,
  tested).
- **Report:** the `{entries_rule}` for stations says one entry per station reached, in order, with
  `question` = the station name and the first line of its scenario, `category` = the station's category,
  `question_turn` = the turn that opened it, and `station` = its key. A station that wasn't reached gets
  no entry, and the summary says so. `normalise` keeps `station` when it is one of the brief's station
  keys.
- **Setup:** with a stations brief, the type, stage and question-count options are hidden, and the
  length shows "3 stations, 30 min (from the brief)". The pack summary reads
  "stations · 3 × 10 min · medium · neutral". The Interview timer uses `brief_meta.total_minutes`.

### 5c. Panel (S)

The script is today's conversation, plus: introduce the panel members at the start, have each member
lead the questions in their focus area (announced by name, e.g. "Dr Shah here, on teaching..."), and
keep one voice and one avatar. Scoring is the same as for a conversation.

**Done when** the golden tests pass, a stations brief's interview announces each station, stays on
time within a minute per station, the report has one entry per station tagged with its key, and Setup
hides the irrelevant options.
**Cost:** as today (one request per interviewer turn, one per report).

## 6. Prep, Drill and lengths from the brief

### 6a. Prep (S)

- With a brief, `prep.txt` gets the brief block plus `candidate_facts`, with these rules:
  - `likely_questions` start from the brief's likely questions, using its category keys. The opening
    and motivation questions are included only when `opening` is true.
  - `gaps` are built from the brief's competencies against `candidate_facts`.
  - `stories` (STAR) are written only when some category's `structure_hint` mentions STAR. Otherwise
    the list is empty, and the Prep page hides that section.
  - `questions_to_ask` are written only when `candidate_questions` is true.
- The prep sheet's `source_hash`: with no brief it's today's function, unchanged, so existing sheets
  aren't marked stale. With a brief it's the SHA-1 of the brief JSON, so editing the brief marks the
  sheet stale.
- `clean_sheet` resolves categories against the brief's keys.

### 6b. Drill (S)

- Starter questions with a brief: "Tell me about yourself." when `opening` is true, then the first
  likely question of each category (up to 5), source `brief`. With a stations brief, one starter per
  station, which practises its scenario. With no brief, `STARTERS` is used as today.
- Drill scoring uses the pack's current brief rubric. The attempt history only compares attempts with
  the same `criteria_hash` (older ones are greyed out and labelled "earlier criteria").
- `drill.system_prompt` gets the brief block plus `candidate_facts`, and the shared `{criteria_block}`.

### 6c. Target answer lengths (XS)

`answer_delivery` and Drill's `length` flag read `target_seconds` from the rubric's categories. A
station uses its category's target, or none when it's a scenario longer than 5 minutes.

**Cost:** as today (1 per prep sheet, 1 per drill attempt).

## 7. Docs and end-to-end check (S)

- README: materials, brief, the new routes in the API table, and the size caps. SPEC: the brief and
  the format kinds. CLAUDE.md: layout (`brief.py`, `prompts/brief.txt`, `materials`/`briefs` tables,
  `sessions.brief_json`, `turns.station`), conventions (the golden tests, the freeze rule,
  `report_rubric`), and `BRIEF_MODEL`.
- **End-to-end check (asks before spending requests):** two fictional packs:
  - (a) a client-facing implementation consultant: an invented JD, CV and company notes;
  - (b) a UK specialty-training interview: three stations (clinical scenario, ethics, portfolio) and a
    short invented mark scheme on a 1-4 scale.

  For each pack: generate the brief, show its format, criteria and assumptions, run one short
  interview and one drill attempt. Then check that your existing packs open, show the default brief,
  render golden-identical prompts, and that History and Review look as before.

## 8 (optional). Station card on the Interview page (S)

With a stations brief, a card above the transcript shows the current station's name, the time left
and the scenario text (from `[station N]` via the stream's new `station` event). It collapses to one
line while you answer.

## Cost summary

| Action | Claude requests |
|---|---|
| Upload or paste materials, edit the brief, confirm assumptions | 0 |
| Draft from the web (research) | 1 (with web tools, up to 10 tool turns), as today |
| Write or regenerate the brief | 1 |
| Interview | 1 per interviewer turn, as today |
| Report | 1 per session, as today |
| Prep sheet | 1, as today |
| Drill attempt | 1, as today |
| I7 end-to-end check | about 2 × (1 brief + ~10 interview turns + 1 report + 1 drill) ≈ 26, after you approve |

No new dependencies. No new local models.

## Risks and decisions to flag

1. **`candidate_facts` added to the brief** (2a). Without it, prep stories and better answers lose CV
   detail, or have to read the raw CV again.
2. **Sessions snapshot their brief** (section 4). Otherwise "Regenerate report" after a brief edit would
   re-score an old session with new criteria.
3. **The "byte-identical conversation script" holds for the default brief.** A generated conversation
   brief has to change the context block (brief instead of raw JD/CV), so its snapshot can't match
   today's. The script steps themselves stay the same.
4. **Stations are tracked by a `[station N]` tag**, with the clock as a fallback, rather than by the
   clock alone. That is what makes per-station time notes and one report entry per station reliable.
5. **The panel kind has one voice.** Members are distinguished in speech only.
6. **Legacy Whisper hints** now include company notes after the CV and JD. This only matters when the
   token budget has room left, and it doesn't affect scoring.
7. **The criteria list is capped at 3-6.** Mark schemes with more domains are merged in the brief, and
   the merge is listed as an assumption.

## Build order

- [x] I0. Golden prompts: today's rendered interviewer, feedback, drill and prep prompts and the two
      JSON schemas for fictional packs, with `test_golden.py`.
- [x] I1. Materials: table, multi-file upload and paste, the size cap, legacy packs shown as three
      synthetic materials (no data rewrite), `PackIn` without a required `jd`, Setup's materials list,
      research result as a material, Whisper hints from all materials, default-mode slot mapping by kind.
- [x] I2. Brief backend: `brief.py`, `prompts/brief.txt`, schema, `clean_brief`, `source_hash`,
      `criteria_hash`, `default_brief`, `briefs` table, GET/POST/PUT/DELETE `/packs/{id}/brief`,
      `BRIEF_MODEL`. Tests for cleaning, hashing and the default brief.
- [x] I3. Brief page: sections, assumptions to confirm (answers fed to Regenerate), stale notice,
      Regenerate with its cost shown, freeze warning, "use the standard interview".
- [x] I4. Rubric from the brief: `render_criteria` shared by feedback and drill, dynamic schemas,
      `sessions.brief_json` snapshot, criteria and categories stored on new reports and attempts,
      `report_rubric`, `_session_summary` fix, frontend rendering from the report, History and the
      Review delta comparing like criteria only, neutral style for unknown categories. Golden tests
      still pass.
- [ ] I5. Format from the brief: `{context}` and `{script}` slots, conversation flags, stations
      (`[station N]` tag, `turns.station`, per-station time notes, one report entry per station),
      panel, Setup hiding irrelevant options, Interview timer from the brief. Golden tests still pass.
- [ ] I6. Prep, Drill starters and target lengths from the brief, with today's values as the fallback;
      STAR stories only when a category's hint uses STAR.
- [ ] I7. Docs (README, SPEC, CLAUDE.md) and the end-to-end check with two fictional packs (after you
      approve the requests).
- [ ] I8 (optional). Station card on the Interview page.
