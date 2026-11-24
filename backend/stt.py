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


def _transcribe_array(audio: np.ndarray, prompt: str | None) -> str:
    import mlx_whisper

    result = mlx_whisper.transcribe(
        audio,
        path_or_hf_repo=MODEL,
        language="en",
        initial_prompt=prompt,
        condition_on_previous_text=False,
        temperature=(0.0, 0.2, 0.4),   # fewer retries than the default: faster
        verbose=None,
    )
    return (result.get("text") or "").strip()


def transcribe(wav_bytes: bytes, prompt: str | None = None) -> str:
    """Transcribe one answer. Call on the MLX thread. Returns "" for silence."""
    audio = wav_to_float32(wav_bytes)
    if len(audio) < SAMPLE_RATE * 0.3:
        return ""
    text = _transcribe_array(audio, prompt)
    if text.lower() in _HALLUCINATIONS:
        return ""
    return text


# ------------------------------------------------------------------ prompt --- #

_STOP = {
    "The", "This", "That", "You", "Your", "We", "Our", "And", "For", "With", "Will",
    "Are", "Is", "In", "On", "To", "Of", "As", "At", "Be", "Or", "An", "A", "If",
    "It", "By", "From", "All", "About", "What", "Who", "How", "Job", "Role",
    "Requirements", "Responsibilities", "Experience", "Skills", "Team", "Work",
}


def keyword_prompt(role: str, company: str, jd: str, limit: int = 40) -> str:
    """Seed Whisper with role vocabulary from the JD (acronyms, product names...)."""
    words = re.findall(r"[A-Za-z][A-Za-z0-9+#./-]*[A-Za-z0-9+#]|[A-Z]{2,}", jd or "")
    counts: Counter[str] = Counter()
    for w in words:
        if w in _STOP:
            continue
        if w.isupper() or any(c.isdigit() for c in w) or w[0].isupper() or any(c in w for c in "+#."):
            counts[w] += 1
    # Product names that span two words, e.g. "Dynamics 365", "Power BI".
    for a, b in re.findall(r"\b([A-Z][a-zA-Z]+) ([A-Z]{2,}|\d{2,4})\b", jd or ""):
        if a not in _STOP:
            counts[f"{a} {b}"] += 2
    keywords = [w for w, _ in counts.most_common(limit)]
    # Whisper tends to drop "um"/"uh". Starting the prompt with fillers makes it
    # keep them, so the feedback report can count them.
    head = (
        "Umm, let me think, like, hmm... Okay, so, uh, here's what I did. "
        f"Job interview for {role or 'a role'}" + (f" at {company}" if company else "") + "."
    )
    prompt = head + (" Topics: " + ", ".join(keywords) + "." if keywords else "")
    return prompt[:900]
