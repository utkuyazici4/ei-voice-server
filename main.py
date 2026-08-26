"""
Voice matching server for Estetik International.

Two doors:

  DOOR 1  WS  /twilio-stream    Twilio Media Streams sends the caller's audio
                                here. We buffer it, classify it, and remember
                                the result against the call id.

  DOOR 2  POST /assignment      ElevenLabs asks "which voice for this call".
                                We answer from what door 1 worked out.

Everything is in memory. A call's result is dropped once the call ends.
Nothing about the caller is persisted.
"""

import asyncio
import base64
import json
import logging
import os
import time

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from classifier import classify
from pool import lookup, POOL
from similar import similar_voices_rank

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("vm")

# ---------------------------------------------------------------- settings

# Turn similar-voices on or off without touching code. Default off.
USE_SIMILAR = os.getenv("USE_SIMILAR_VOICES", "false").lower() == "true"

# How much caller speech we want before we classify.
MIN_SPEECH_MS = int(os.getenv("MIN_SPEECH_MS", "4000"))
MAX_SPEECH_MS = int(os.getenv("MAX_SPEECH_MS", "15000"))

# Below this we do not trust the classifier and fall back.
MIN_CONFIDENCE = float(os.getenv("MIN_CONFIDENCE", "0.60"))

# Forget a call this long after we last heard from it.
RESULT_TTL_SECS = int(os.getenv("RESULT_TTL_SECS", "1800"))

app = FastAPI(title="EI voice matching")

# call_sid -> result dict
RESULTS: dict[str, dict] = {}


def _sweep() -> None:
    """Drop anything older than the TTL. Called on every write."""
    now = time.time()
    stale = [k for k, v in RESULTS.items() if now - v["at"] > RESULT_TTL_SECS]
    for k in stale:
        RESULTS.pop(k, None)
    if stale:
        log.info("swept %d stale result(s)", len(stale))


# ------------------------------------------------------------------ door 1


@app.websocket("/twilio-stream")
async def twilio_stream(ws: WebSocket) -> None:
    """
    Twilio Media Streams protocol.

    Frames arrive as JSON. We care about three events:
      start   carries streamSid and callSid
      media   carries base64 mu-law 8kHz mono, 20ms per frame
      stop    call ended
    """
    await ws.accept()

    call_sid: str | None = None
    frames: list[bytes] = []
    classified = False

    try:
        while True:
            raw = await ws.receive_text()
            msg = json.loads(raw)
            event = msg.get("event")

            if event == "start":
                start = msg.get("start", {})
                call_sid = start.get("callSid") or start.get("streamSid")
                custom = start.get("customParameters") or {}
                log.info("stream start call_sid=%s params=%s", call_sid, custom)

                # Language may be passed in from TwiML if you already know it.
                if call_sid and custom.get("language"):
                    RESULTS.setdefault(call_sid, {}).update(
                        {"hint_language": custom["language"], "at": time.time()}
                    )

            elif event == "media":
                payload = msg["media"]["payload"]
                frames.append(base64.b64decode(payload))

                # Each frame is 20ms of mu-law at 8kHz.
                ms = len(frames) * 20
                if not classified and ms >= MIN_SPEECH_MS:
                    await _classify_and_store(call_sid, frames)
                    classified = True

                # Keep buffering a little past the first pass so a later
                # re-classify has more to work with, then stop growing.
                if ms >= MAX_SPEECH_MS and classified:
                    frames = frames[: MAX_SPEECH_MS // 20]

            elif event == "stop":
                log.info("stream stop call_sid=%s", call_sid)
                break

    except WebSocketDisconnect:
        log.info("stream disconnected call_sid=%s", call_sid)
    except Exception:
        log.exception("stream error call_sid=%s", call_sid)
    finally:
        # One last attempt if the call was too short to hit MIN_SPEECH_MS.
        if call_sid and not classified and frames:
            await _classify_and_store(call_sid, frames)


async def _classify_and_store(call_sid: str | None, frames: list[bytes]) -> None:
    if not call_sid:
        return

    mulaw = b"".join(frames)
    existing = RESULTS.get(call_sid, {})
    language = existing.get("hint_language") or existing.get("language") or "en"

    # Classification is CPU bound, keep it off the event loop.
    result = await asyncio.to_thread(classify, mulaw)

    gender = result["gender"]
    age_band = result["age_band"]
    confidence = result["confidence"]

    if confidence < MIN_CONFIDENCE:
        log.info(
            "call_sid=%s low confidence %.2f, will fall back", call_sid, confidence
        )
        RESULTS[call_sid] = {
            "voice_key": None,
            "language": language,
            "gender": gender,
            "age_band": age_band,
            "confidence": confidence,
            "source": "low_confidence",
            "at": time.time(),
        }
        _sweep()
        return

    cell = lookup(language, gender, age_band)
    voice_key = cell["default_key"] if cell else None
    source = "classifier"
    similar_debug = None

    # Optional second layer. Ranks the candidates inside the chosen cell.
    if USE_SIMILAR and cell and len(cell["candidates"]) > 1:
        try:
            ranked = await asyncio.to_thread(
                similar_voices_rank, mulaw, cell["candidates"]
            )
            similar_debug = ranked
            if ranked:
                voice_key = ranked[0]["key"]
                source = "classifier+similar"
        except Exception:
            log.exception("similar-voices failed, keeping cell default")

    RESULTS[call_sid] = {
        "voice_key": voice_key,
        "language": language,
        "gender": gender,
        "age_band": age_band,
        "confidence": confidence,
        "source": source,
        "similar": similar_debug,
        "at": time.time(),
    }
    _sweep()

    log.info(
        "call_sid=%s -> %s (%s/%s conf=%.2f source=%s)",
        call_sid,
        voice_key,
        gender,
        age_band,
        confidence,
        source,
    )


# ------------------------------------------------------------------ door 2


class AssignmentRequest(BaseModel):
    call_sid: str | None = None
    language: str | None = None


FALLBACK = {
    "matched_voice_key": "fallback",
    "match_language": "fallback",
    "consultant_name": "your consultant",
}


@app.post("/assignment")
async def assignment(req: AssignmentRequest) -> JSONResponse:
    """
    Never errors. If we do not know, we say fallback and the workflow
    carries on in the house voice.
    """
    if not req.call_sid:
        log.info("assignment with no call_sid -> fallback")
        return JSONResponse(FALLBACK)

    res = RESULTS.get(req.call_sid)

    # ElevenLabs knows the spoken language better than we do. If it sent one,
    # prefer it and re-read the cell.
    if res and req.language and req.language != res.get("language"):
        cell = lookup(req.language, res.get("gender"), res.get("age_band"))
        if cell:
            res = dict(res)
            res["language"] = req.language
            res["voice_key"] = cell["default_key"]
            RESULTS[req.call_sid] = res

    if not res or not res.get("voice_key"):
        log.info("assignment call_sid=%s -> fallback (%s)",
                 req.call_sid,
                 (res or {}).get("source", "no result yet"))
        return JSONResponse(FALLBACK)

    cell = lookup(res["language"], res["gender"], res["age_band"])
    name = cell["consultant_name"] if cell else "your consultant"

    body = {
        "matched_voice_key": res["voice_key"],
        "match_language": res["language"],
        "consultant_name": name,
    }
    log.info("assignment call_sid=%s -> %s", req.call_sid, body)
    return JSONResponse(body)


# ------------------------------------------------------------------- extras


@app.get("/health")
async def health() -> dict:
    return {
        "ok": True,
        "similar_voices": USE_SIMILAR,
        "calls_in_memory": len(RESULTS),
        "pool_cells": len(POOL),
    }


@app.get("/debug/{call_sid}")
async def debug(call_sid: str) -> dict:
    """What we worked out for one call. Handy while testing."""
    return RESULTS.get(call_sid, {"found": False})


@app.post("/mock/{voice_key}")
async def mock(voice_key: str, req: AssignmentRequest) -> JSONResponse:
    """
    Stand-in for the old mocky URL. Point the ElevenLabs tool here to force
    a specific voice while you are still testing the workflow.
    """
    lang = voice_key.split("_")[0]
    cell = None
    for c in POOL.values():
        if voice_key in [x["key"] for x in c["candidates"]]:
            cell = c
            break
    return JSONResponse({
        "matched_voice_key": voice_key,
        "match_language": lang,
        "consultant_name": cell["consultant_name"] if cell else "Elena",
    })
