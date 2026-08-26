"""
Optional second layer: ElevenLabs /v1/similar-voices.

Only runs when USE_SIMILAR_VOICES=true and the chosen cell has more than one
candidate. It never decides the cell, only which voice inside it.

Two things worth knowing:

1. The endpoint returns shared-library voices. Those ids are not the ids your
   agent uses. That is why each candidate carries library_voice_id separately
   from key.

2. The identifying detail it works on lives above 4kHz, and telephone audio
   does not carry that band. This layer may return noise. Compare its picks
   against the cell default on real calls before trusting it.
"""

import audioop
import io
import logging
import os
import wave

import requests

log = logging.getLogger("vm.similar")

API_KEY = os.getenv("ELEVENLABS_API_KEY", "")
ENDPOINT = "https://api.elevenlabs.io/v1/similar-voices"
TOP_K = int(os.getenv("SIMILAR_TOP_K", "20"))
TIMEOUT = float(os.getenv("SIMILAR_TIMEOUT", "6"))


def mulaw_to_wav_bytes(mulaw: bytes, sample_rate: int = 8000) -> bytes:
    """Wrap mu-law as a 16-bit PCM WAV in memory."""
    pcm16 = audioop.ulaw2lin(mulaw, 2)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm16)
    return buf.getvalue()


def similar_voices_rank(mulaw: bytes, candidates: list[dict]) -> list[dict]:
    """
    Returns the candidates that appeared in the API response, ordered best
    first. Candidates the API did not mention are dropped. An empty list
    means keep the cell default.
    """
    if not API_KEY:
        log.warning("ELEVENLABS_API_KEY not set, skipping similar-voices")
        return []

    by_lib_id = {
        c["library_voice_id"]: c["key"]
        for c in candidates
        if c.get("library_voice_id")
    }
    if not by_lib_id:
        log.info("no library_voice_id on any candidate, skipping")
        return []

    wav = mulaw_to_wav_bytes(mulaw)

    resp = requests.post(
        ENDPOINT,
        headers={"xi-api-key": API_KEY},
        files={"audio_file": ("sample.wav", wav, "audio/wav")},
        data={"top_k": str(TOP_K)},
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    payload = resp.json()

    # The response shape has moved around between versions, so accept a few.
    items = payload if isinstance(payload, list) else (
        payload.get("voices") or payload.get("similar_voices") or []
    )

    ranked = []
    for position, item in enumerate(items):
        lib_id = item.get("voice_id") or item.get("id")
        if lib_id in by_lib_id:
            ranked.append({
                "key": by_lib_id[lib_id],
                "library_voice_id": lib_id,
                "position": position,
                "name": item.get("name"),
            })

    log.info("similar-voices matched %d of %d candidates",
             len(ranked), len(by_lib_id))
    return ranked
