"""
Voice matching via ElevenLabs /v1/similar-voices.

This is the whole matching engine now. There is no classifier.

Two things worth knowing:

1. The endpoint returns SHARED LIBRARY voices. Those ids are not the ids your
   agent speaks with, which is why pool.py carries both.

2. The detail that identifies one voice from another lives above 4 kHz, and
   telephone audio does not carry that band. Results may be noise. Every call
   logs the full ranked list so you can check whether the same caller gets
   consistent matches before you trust it.
"""

import audioop
import io
import logging
import os
import wave

import requests

import pool

log = logging.getLogger("vm.similar")

API_KEY = os.getenv("ELEVENLABS_API_KEY", "")
ENDPOINT = "https://api.elevenlabs.io/v1/similar-voices"
TOP_K = int(os.getenv("SIMILAR_TOP_K", "40"))
TIMEOUT = float(os.getenv("SIMILAR_TIMEOUT", "8"))


def mulaw_to_wav(mulaw: bytes, sample_rate: int = 8000) -> bytes:
    pcm16 = audioop.ulaw2lin(mulaw, 2)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm16)
    return buf.getvalue()


def _extract_items(payload):
    if isinstance(payload, list):
        return payload
    for key in ("voices", "similar_voices", "results"):
        if isinstance(payload.get(key), list):
            return payload[key]
    return []


def rank(mulaw: bytes, language: str | None = None) -> dict:
    """
    Returns:
      {
        "matched": <pool entry or None>,
        "ranked":  [ {label, library_voice_id, position, name}, ... ],
        "raw_count": how many voices the API returned,
        "error": <str or None>
      }
    """
    result = {"matched": None, "ranked": [], "raw_count": 0, "error": None}

    if not API_KEY:
        result["error"] = "ELEVENLABS_API_KEY not set"
        log.warning(result["error"])
        return result

    candidates = pool.by_library_id(language)
    if not candidates:
        result["error"] = f"no pool entries with a library id for {language}"
        log.warning(result["error"])
        return result

    try:
        resp = requests.post(
            ENDPOINT,
            headers={"xi-api-key": API_KEY},
            files={"audio_file": ("sample.wav", mulaw_to_wav(mulaw),
                                  "audio/wav")},
            data={"top_k": str(TOP_K)},
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        items = _extract_items(resp.json())
    except Exception as exc:
        result["error"] = f"similar-voices call failed: {exc}"
        log.exception(result["error"])
        return result

    result["raw_count"] = len(items)

    for position, item in enumerate(items):
        lib_id = item.get("voice_id") or item.get("id")
        entry = candidates.get(lib_id)
        if entry:
            result["ranked"].append({
                "label": entry["label"],
                "library_voice_id": lib_id,
                "position": position,
                "name": item.get("name"),
            })

    if result["ranked"]:
        best = result["ranked"][0]
        result["matched"] = pool.by_label(best["label"])

    log.info("similar-voices: %d returned, %d in pool (%s), best=%s",
             result["raw_count"], len(result["ranked"]), language,
             result["matched"]["label"] if result["matched"] else None)
    return result
