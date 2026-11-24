"""Text-to-speech with Kokoro-82M via mlx-audio, plus word timings for lip-sync.

Word timings come from Kokoro's own duration predictions (exposed on the
pipeline's tokens). If they are missing, they are estimated by spreading the
audio duration over the words in proportion to their length.
"""

from __future__ import annotations

import base64
import io
import logging
import os
import re
import time
import wave

import numpy as np

log = logging.getLogger("interview-coach.tts")

MODEL = os.environ.get("KOKORO_MODEL") or "mlx-community/Kokoro-82M-bf16"
DEFAULT_VOICE = os.environ.get("KOKORO_VOICE") or "af_heart"
SAMPLE_RATE = 24000

VOICES = [
    "af_heart", "af_bella", "af_nicole", "af_sarah", "af_sky",
    "am_michael", "am_adam", "am_eric", "am_liam", "am_onyx",
    "bf_emma", "bf_isabella", "bm_george", "bm_daniel", "bm_lewis",
]

state = {"status": "not loaded", "error": None}
_model = None
_pipelines: dict = {}


# ----------------------------------------------------------- G2P fallback --- #

class SpellingFallback:
    """Pronounce words missing from misaki's dictionary.

    Without espeak-ng, misaki has no fallback and crashes on unknown words such
    as company names. This splits the word into parts (camelCase, digits) and
    says the known parts, spelling out any part it can't pronounce.
    If espeak-ng is installed, misaki's own espeak fallback is used instead.
    """

    def __init__(self, g2p):
        self.g2p = g2p
        self._busy = False

    def _known(self, text: str) -> str | None:
        try:
            ps, _ = self.g2p(text)
        except Exception:
            return None
        return None if (not ps or "❓" in ps) else ps

    def __call__(self, token):
        if self._busy:
            return "", 0
        self._busy = True
        saved, self.g2p.fallback = self.g2p.fallback, None
        try:
            parts = re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+", token.text) or [token.text]
            phrase = []
            for part in parts:
                if self._known(part) is not None:
                    phrase.append(part)
                else:
                    phrase.extend(c.upper() for c in part if c.isalnum())
            ps = self._known(" ".join(phrase)) if phrase else None
            return (ps or ""), 1
        finally:
            self.g2p.fallback = saved
            self._busy = False


# ------------------------------------------------------------------ model --- #

def _pipeline(lang_code: str):
    if lang_code not in _pipelines:
        # Same construction as KokoroModel.generate(); we use the pipeline
        # directly because it exposes per-word timestamps.
        pipe = _model._get_pipeline(lang_code)
        g2p = getattr(pipe, "g2p", None)
        if g2p is not None and getattr(g2p, "fallback", "missing") is None:
            g2p.fallback = SpellingFallback(g2p)
        _pipelines[lang_code] = pipe
    return _pipelines[lang_code]


def load() -> None:
    """Load Kokoro and warm it up. Call on the MLX thread."""
    global _model
    state.update(status="loading", error=None)
    try:
        from mlx_audio.tts.utils import load as load_tts

        t0 = time.perf_counter()
        _model = load_tts(MODEL)
        synthesize("Hello.", DEFAULT_VOICE)
        state.update(status="loaded")
        log.info("Kokoro %s ready in %.1fs", MODEL, time.perf_counter() - t0)
    except Exception as exc:
        _model = None
        state.update(status="unavailable", error=f"{type(exc).__name__}: {exc}")
        log.warning("Kokoro unavailable: %s", exc)


def is_ready() -> bool:
    return state["status"] == "loaded"


# -------------------------------------------------------------- synthesis --- #

def _clean(text: str) -> str:
    # misaki reads [word](/phonemes/) as markup; drop brackets and markdown.
    text = re.sub(r"[\[\]*_`#]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def estimate_timings(text: str, start_s: float, duration_s: float) -> list[dict]:
    """Spread duration_s across the words of text, weighted by word length."""
    words = [w for w in text.split() if re.search(r"\w", w)]
    if not words or duration_s <= 0:
        return []
    weights = [len(re.sub(r"\W", "", w)) + 1 for w in words]
    total = sum(weights)
    out, t = [], start_s
    for w, wt in zip(words, weights):
        d = duration_s * wt / total
        out.append({"word": re.sub(r"^\W+|\W+$", "", w), "start_ms": round(t * 1000), "end_ms": round((t + d) * 1000)})
        t += d
    return out


def to_wav_base64(audio: np.ndarray, sample_rate: int = SAMPLE_RATE) -> str:
    pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm.tobytes())
    return base64.b64encode(buf.getvalue()).decode("ascii")


def synthesize(text: str, voice: str | None = None, speed: float = 1.0) -> dict:
    """Speak one sentence. Call on the MLX thread.

    Returns {audio_wav_base64, duration_ms, word_timings:[{word, start_ms, end_ms}]}.
    """
    import mlx.core as mx

    if _model is None:
        raise RuntimeError("Kokoro is not loaded")
    voice = voice or DEFAULT_VOICE
    lang_code = voice[0] if voice[:1] in ("a", "b") else "a"
    text = _clean(text)
    chunks: list[np.ndarray] = []
    words: list[dict] = []
    offset = 0.0
    for result in _pipeline(lang_code)(text, voice=voice, speed=speed, split_pattern=r"\n+"):
        if result.audio is None:
            continue
        audio = np.array(result.audio.astype(mx.float32)).reshape(-1)
        dur = len(audio) / SAMPLE_RATE
        tokens = [t for t in (result.tokens or []) if re.search(r"\w", t.text)]
        if tokens and all(t.start_ts is not None and t.end_ts is not None for t in tokens):
            for t in tokens:
                words.append({
                    "word": t.text,
                    "start_ms": round((offset + t.start_ts) * 1000),
                    "end_ms": round((offset + t.end_ts) * 1000),
                })
        else:
            words.extend(estimate_timings(result.graphemes or "", offset, dur))
        chunks.append(audio)
        offset += dur
    if not chunks:
        raise RuntimeError("Kokoro produced no audio")
    audio = np.concatenate(chunks)
    return {
        "audio_wav_base64": to_wav_base64(audio),
        "duration_ms": round(len(audio) / SAMPLE_RATE * 1000),
        "word_timings": words,
    }
