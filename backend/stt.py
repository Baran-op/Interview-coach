"""Speech-to-text with mlx-whisper (whisper-small.en by default).

The browser sends 16 kHz mono WAV cut by the VAD. It is decoded here with the
standard library, so ffmpeg is not needed.
"""

from __future__ import annotations

import io
import logging
import os
import re
import time
import wave
from collections import Counter

import numpy as np

log = logging.getLogger("interview-coach.stt")

MODEL = os.environ.get("WHISPER_MODEL") or "mlx-community/whisper-small.en-mlx"
SAMPLE_RATE = 16000

state = {"status": "not loaded", "error": None}

# Whisper likes to "hear" these in silence or noise.
_HALLUCINATIONS = {
    "", "you", "thank you.", "thanks for watching!", "thank you for watching.",
    "bye.", ".", "thank you very much.",
}


def load() -> None:
    """Load the model and run one tiny warm-up pass. Call on the MLX thread."""
    state.update(status="loading", error=None)
    try:
        import mlx_whisper  # noqa: F401

        t0 = time.perf_counter()
        _transcribe_array(np.zeros(SAMPLE_RATE // 2, dtype=np.float32), None)
        state.update(status="loaded")
        log.info("Whisper %s ready in %.1fs", MODEL, time.perf_counter() - t0)
    except Exception as exc:  # e.g. not on Apple Silicon, or no network on first run
        state.update(status="unavailable", error=f"{type(exc).__name__}: {exc}")
        log.warning("Whisper unavailable: %s", exc)


def is_ready() -> bool:
    return state["status"] == "loaded"


def wav_to_float32(data: bytes) -> np.ndarray:
    """Decode a PCM WAV file to mono float32 at 16 kHz."""
    with wave.open(io.BytesIO(data), "rb") as w:
        channels, width, rate = w.getnchannels(), w.getsampwidth(), w.getframerate()
        frames = w.readframes(w.getnframes())
    if width == 2:
        audio = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
    elif width == 4:
        audio = np.frombuffer(frames, dtype="<i4").astype(np.float32) / 2147483648.0
    elif width == 1:
        audio = (np.frombuffer(frames, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    else:
        raise ValueError(f"Unsupported WAV sample width: {width} bytes")
    if channels > 1:
        audio = audio.reshape(-1, channels).mean(axis=1)
    if rate != SAMPLE_RATE and len(audio):
        n = int(round(len(audio) * SAMPLE_RATE / rate))
        audio = np.interp(
            np.linspace(0, len(audio) - 1, n), np.arange(len(audio)), audio
        ).astype(np.float32)
    return audio


def _transcribe_array(audio: np.ndarray, prompt: str | None, words: bool = False) -> dict:
    import mlx_whisper

    return mlx_whisper.transcribe(
        audio,
        path_or_hf_repo=MODEL,
        language="en",
        initial_prompt=prompt,
        condition_on_previous_text=False,
        temperature=(0.0, 0.2, 0.4),   # fewer retries than the default: faster
        verbose=None,
        word_timestamps=words,
    )


def transcribe(wav_bytes: bytes, prompt: str | None = None) -> str:
    """Transcribe one answer. Call on the MLX thread. Returns "" for silence."""
    audio = wav_to_float32(wav_bytes)
    if len(audio) < SAMPLE_RATE * 0.3:
        return ""
    text = (_transcribe_array(audio, prompt).get("text") or "").strip()
    if text.lower() in _HALLUCINATIONS:
        return ""
    return text


def clean_words(result: dict) -> list[dict]:
    """``[{"w": "slipped", "start_ms": 1200, "end_ms": 1560}, ...]`` from a word-timestamp result, offsets in the WAV."""
    out = []
    for seg in result.get("segments") or []:
        for w in seg.get("words") or []:
            text = str(w.get("word") or "").strip()
            a, b = w.get("start"), w.get("end")
            if text and a is not None and b is not None:
                out.append({"w": text, "start_ms": int(round(float(a) * 1000)), "end_ms": int(round(float(b) * 1000))})
    return out


def words_from_wav(wav_path) -> list[dict]:
    """Word offsets for one saved answer WAV. Call on the MLX thread. [] for audio too short to transcribe.

    Measured on a 41 s clip, word timestamps add about 0.75 s to a transcription (1 s per minute), over the
    0.5 s budget, so this runs in the report step from the saved WAVs instead of inside `transcribe`.
    """
    audio = wav_to_float32(open(wav_path, "rb").read())
    if len(audio) < SAMPLE_RATE * 0.3:
        return []
    return clean_words(_transcribe_array(audio, None, words=True))


# ------------------------------------------------------------------ prompt --- #

_STOP = {
    "The", "This", "That", "You", "Your", "We", "Our", "And", "For", "With", "Will",
    "Are", "Is", "In", "On", "To", "Of", "As", "At", "Be", "Or", "An", "A", "If",
    "It", "By", "From", "All", "About", "What", "Who", "How", "Job", "Role",
    "Requirements", "Responsibilities", "Experience", "Skills", "Team", "Work",
}


_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9+#./-]*[A-Za-z0-9+#]|[A-Z]{2,}|[A-Za-z]")
_SENTENCE_END = set(".!?:")
_BULLETS = set("-*\u2022\u2013\u2014\u25cf\u25aa>")
MAX_PROMPT_TOKENS = 180
MAX_PROMPT_CHARS = 600


def _is_special(w: str) -> bool:
    return w.isupper() and len(w) > 1 or any(c.isdigit() for c in w) or any(c in w for c in "+#.")


def _starts_sentence(text: str, pos: int) -> bool:
    """True if the word at pos opens a sentence, line or bullet."""
    i = pos - 1
    while i >= 0 and text[i] in " \t":
        i -= 1
    if i < 0:
        return True
    c = text[i]
    return c in "\r\n" or c in _SENTENCE_END or c in _BULLETS


def extract_terms(text: str) -> list[str]:
    """Names, tools and acronyms from free text, most frequent first.

    A capitalised word that merely starts a sentence or line is skipped unless it is an
    acronym or contains a digit or one of +#. Two-word names are kept whole.
    """
    text = text or ""
    counts: Counter[str] = Counter()
    first: dict[str, str] = {}
    toks = [(m.group(), m.start(), m.end()) for m in _TOKEN.finditer(text)]
    prev_name: tuple[str, int] | None = None   # capitalised word right before this one
    for w, start, end in toks:
        if len(w) < 2 or w in _STOP:
            prev_name = None
            continue
        special = _is_special(w)
        capital = w[0].isupper()
        opener = _starts_sentence(text, start)
        if not (special or capital):
            prev_name = None
            continue
        if opener and not special:
            # Could still head a name like "Customer Success"; remember it but don't count it alone.
            prev_name = (w, end)
            continue
        key = w.lower()
        counts[key] += 1
        first.setdefault(key, w)
        # Two-word name: previous capitalised word + this one, only when adjacent.
        if prev_name and text[prev_name[1]:start].strip(" ") == "" and "\n" not in text[prev_name[1]:start]:
            pair = f"{prev_name[0]} {w}"
            counts[pair.lower()] += 2
            first.setdefault(pair.lower(), pair)
        prev_name = (w, end) if capital and not special else None
    # Product names like "Dynamics 365" or "Power BI" count even at a sentence start.
    for a, b in re.findall(r"\b([A-Z][a-zA-Z]+) ([A-Z]{2,}|\d{2,4})\b", text):
        if a not in _STOP:
            pair = f"{a} {b}"
            counts[pair.lower()] += 2
            first.setdefault(pair.lower(), pair)
    return [first[k] for k, _ in counts.most_common()]


def _within_budget(prompt: str) -> bool:
    try:
        from mlx_whisper.tokenizer import get_tokenizer

        tok = get_tokenizer(multilingual=False)
        return len(tok.encode(" " + prompt)) <= MAX_PROMPT_TOKENS
    except Exception:
        return len(prompt) <= MAX_PROMPT_CHARS


def keyword_prompt(role: str, company: str, texts: list[str]) -> str:
    """Seed Whisper with vocabulary from the pack's materials (acronyms, product names...).

    `texts` are in priority order (materials.hint_texts: candidate, job, format, organisation,
    other; for a legacy pack CV, JD, company notes). Whisper keeps only the last 223 prompt
    tokens, so the list is capped (about 180 tokens) to avoid pushing out the filler seed.
    """
    terms: list[str] = []
    seen: set[str] = set()
    for t in [t for text in texts for t in extract_terms(text)]:
        if t.lower() not in seen:
            seen.add(t.lower())
            terms.append(t)
    # Whisper tends to drop "um"/"uh". Starting the prompt with fillers makes it
    # keep them, so the feedback report can count them.
    head = (
        "Umm, let me think, like, hmm... Okay, so, uh, here's what I did. "
        f"Job interview for {role or 'a role'}" + (f" at {company}" if company else "") + "."
    )
    chosen: list[str] = []
    prompt = head
    for t in terms:
        cand = head + " Topics: " + ", ".join(chosen + [t]) + "."
        if not _within_budget(cand):
            break
        chosen.append(t)
        prompt = cand
    return prompt
