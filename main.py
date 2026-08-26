"""
Voice matching server for Estetik International.

  WS   /twilio-stream     Twilio sends the caller's audio here. We buffer it
                          and, once there is enough, run it through
                          /v1/similar-voices against our approved pool.

  POST /assignment        ElevenLabs asks which voice to use. We answer from
                          what the stream worked out. Language comes from
                          ElevenLabs, since the transcript knows it and
                          similar-voices does not.

  GET  /pool/suggest      Lists the voices already in your workspace so you
                          can fill in pool.py without guessing ids.

  GET  /pool/status       How many pool slots are actually usable.
  GET  /debug/{call_sid}  What we worked out for one call, with the full
                          ranked list. Use this to judge whether matching is
                          meaningful on telephone audio.
  POST /mock/{label}      Fixed answer, for testing the workflow without any
                          audio at all.

Everything is in memory. A call is forgotten once it ages out.
"""

import asyncio
import base64
import json
import logging
import os
import time

import requests
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from pydantic import BaseModel

import pool
import similar

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("vm")

API_KEY = os.getenv("ELEVENLABS_API_KEY", "")

# Milliseconds of caller audio before the first matching attempt.
MIN_SPEECH_MS = int(os.getenv("MIN_SPEECH_MS", "5000"))
# Try again with a longer sample at this point, if the call is still going.
RETRY_SPEECH_MS = int(os.getenv("RETRY_SPEECH_MS", "12000"))
RESULT_TTL_SECS = int(os.getenv("RESULT_TTL_SECS", "1800"))

app = FastAPI(title="EI voice matching")

RESULTS: dict[str, dict] = {}


def _sweep():
    now = time.time()
    for k in [k for k, v in RESULTS.items()
              if now - v["at"] > RESULT_TTL_SECS]:
        RESULTS.pop(k, None)


# ------------------------------------------------------------------ door 1

@app.websocket("/twilio-stream")
async def twilio_stream(ws: WebSocket):
    await ws.accept()
    call_sid = None
    frames: list[bytes] = []
    attempts = 0

    try:
        while True:
            msg = json.loads(await ws.receive_text())
            event = msg.get("event")

            if event == "start":
                start = msg.get("start", {})
                custom = start.get("customParameters") or {}
                # Prefer an id we control, so ElevenLabs and Twilio agree.
                call_sid = (custom.get("match_id")
                            or start.get("callSid")
                            or start.get("streamSid"))
                lang = custom.get("language")
                log.info("stream start id=%s params=%s", call_sid, custom)
                if call_sid:
                    RESULTS[call_sid] = {"at": time.time(),
                                         "hint_language": lang,
                                         "state": "listening"}

            elif event == "media":
                frames.append(base64.b64decode(msg["media"]["payload"]))
                ms = len(frames) * 20  # 20ms per frame
                if attempts == 0 and ms >= MIN_SPEECH_MS:
                    attempts = 1
                    asyncio.create_task(_match(call_sid, b"".join(frames)))
                elif attempts == 1 and ms >= RETRY_SPEECH_MS:
                    attempts = 2
                    asyncio.create_task(_match(call_sid, b"".join(frames)))

            elif event == "stop":
                log.info("stream stop id=%s", call_sid)
                break

    except WebSocketDisconnect:
        log.info("stream disconnected id=%s", call_sid)
    except Exception:
        log.exception("stream error id=%s", call_sid)
    finally:
        if call_sid and attempts == 0 and frames:
            await _match(call_sid, b"".join(frames))


async def _match(call_sid, mulaw):
    if not call_sid:
        return
    existing = RESULTS.get(call_sid, {})
    language = existing.get("language") or existing.get("hint_language")

    out = await asyncio.to_thread(similar.rank, mulaw, language)

    RESULTS[call_sid] = {
        **existing,
        "at": time.time(),
        "state": "matched" if out["matched"] else "no_match",
        "language": language,
        "matched": out["matched"],
        "ranked": out["ranked"],
        "raw_count": out["raw_count"],
        "error": out["error"],
        "sample_ms": len(mulaw) // 8,
    }
    _sweep()


# ------------------------------------------------------------------ door 2

class AssignmentRequest(BaseModel):
    call_sid: str | None = None
    language: str | None = None


@app.post("/assignment")
async def assignment(req: AssignmentRequest):
    """Never errors. If unsure, answers fallback."""
    if not req.call_sid:
        return JSONResponse(pool.FALLBACK)

    res = RESULTS.get(req.call_sid)
    if not res:
        log.info("assignment id=%s -> fallback (nothing heard)", req.call_sid)
        return JSONResponse(pool.FALLBACK)

    # ElevenLabs knows the spoken language, similar-voices does not.
    # If it tells us and we matched without it, redo the intersection.
    if req.language and req.language != res.get("language"):
        res["language"] = req.language
        ranked = [r for r in res.get("ranked", [])
                  if (pool.by_label(r["label"]) or {}).get("language")
                  == req.language]
        res["matched"] = pool.by_label(ranked[0]["label"]) if ranked else None
        res["ranked"] = ranked
        RESULTS[req.call_sid] = res

    m = res.get("matched")
    if not m or not m.get("workspace_voice_id"):
        log.info("assignment id=%s -> fallback (%s)", req.call_sid,
                 res.get("error") or res.get("state"))
        return JSONResponse(pool.FALLBACK)

    body = {
        "matched_voice_key": m["label"],
        "match_language": m["language"],
        "consultant_name": m["consultant_name"],
    }
    log.info("assignment id=%s -> %s", req.call_sid, body)
    return JSONResponse(body)


# ------------------------------------------------------------------ helpers

@app.get("/health")
async def health():
    return {"ok": True, "calls_in_memory": len(RESULTS), "pool": pool.status()}


@app.get("/pool/status")
async def pool_status():
    return pool.status()


@app.get("/pool/suggest")
async def pool_suggest():
    """
    Lists the voices in your workspace, ready to paste into pool.py.

    Note: the id shown here is the WORKSPACE id. The library id has to come
    from the Voice Library page for that voice, or from a similar-voices
    response. Both are needed.
    """
    if not API_KEY:
        return JSONResponse({"error": "ELEVENLABS_API_KEY not set"},
                            status_code=400)
    try:
        r = requests.get("https://api.elevenlabs.io/v1/voices",
                         headers={"xi-api-key": API_KEY}, timeout=15)
        r.raise_for_status()
        voices = r.json().get("voices", [])
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=502)

    out = []
    for v in voices:
        labels = v.get("labels") or {}
        out.append({
            "name": v.get("name"),
            "workspace_voice_id": v.get("voice_id"),
            "gender": labels.get("gender"),
            "accent": labels.get("accent"),
            "age": labels.get("age"),
            "category": v.get("category"),
            "sharing_public_owner_id":
                (v.get("sharing") or {}).get("public_owner_id"),
            "sharing_original_voice_id":
                (v.get("sharing") or {}).get("original_voice_id"),
        })
    return {"count": len(out),
            "note": "sharing_original_voice_id is usually the library id you "
                    "need for library_voice_id",
            "voices": out}


@app.get("/debug/{call_sid}")
async def debug(call_sid: str):
    return RESULTS.get(call_sid, {"found": False})


@app.post("/mock/{label}")
async def mock(label: str, req: AssignmentRequest):
    entry = pool.by_label(label)
    if not entry:
        return JSONResponse(pool.FALLBACK)
    return JSONResponse({
        "matched_voice_key": entry["label"],
        "match_language": entry["language"],
        "consultant_name": entry["consultant_name"],
    })
