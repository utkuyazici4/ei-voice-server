"""
The approved voice pool.

Twenty slots: English and Turkish, male and female, five voices each.

Matching:
  caller audio -> /v1/similar-voices -> ranked list of LIBRARY voices
  -> keep only the ones in this pool
  -> keep only the ones whose language matches what the transcript reported
  -> take the best ranked one

Two ids per voice, and they are NOT the same thing:

  library_voice_id    what /v1/similar-voices returns, from the public
                      Voice Library
  workspace_voice_id  what your agent can actually speak with, created when
                      you add that library voice to your workspace

Missing library_voice_id  -> that voice can never be matched.
Missing workspace_voice_id -> the match cannot be spoken.

The label (en_f_01 and so on) must match the multi-voice label you configure
in the ElevenLabs Voice tab, exactly and case sensitively.

Run GET /pool/suggest on the deployed server to list the voices already in
your workspace, then paste the ids in below.
"""

POOL = [
    # ---------------- English, female
    {"label": "en_f_01", "language": "en", "gender": "female",
     "consultant_name": "Elena",
     "library_voice_id": "", "workspace_voice_id": "XW70ikSsadUbinwLMZ5w"},
    {"label": "en_f_02", "language": "en", "gender": "female",
     "consultant_name": "Claire",
     "library_voice_id": "", "workspace_voice_id": ""},
    {"label": "en_f_03", "language": "en", "gender": "female",
     "consultant_name": "Sophie",
     "library_voice_id": "", "workspace_voice_id": ""},
    {"label": "en_f_04", "language": "en", "gender": "female",
     "consultant_name": "Margaret",
     "library_voice_id": "", "workspace_voice_id": ""},
    {"label": "en_f_05", "language": "en", "gender": "female",
     "consultant_name": "Helen",
     "library_voice_id": "", "workspace_voice_id": ""},

    # ---------------- English, male
    {"label": "en_m_01", "language": "en", "gender": "male",
     "consultant_name": "Daniel",
     "library_voice_id": "", "workspace_voice_id": "NsFK0aDGLbVusA7tQfOB"},
    {"label": "en_m_02", "language": "en", "gender": "male",
     "consultant_name": "Adam",
     "library_voice_id": "", "workspace_voice_id": ""},
    {"label": "en_m_03", "language": "en", "gender": "male",
     "consultant_name": "Oliver",
     "library_voice_id": "", "workspace_voice_id": ""},
    {"label": "en_m_04", "language": "en", "gender": "male",
     "consultant_name": "Robert",
     "library_voice_id": "", "workspace_voice_id": ""},
    {"label": "en_m_05", "language": "en", "gender": "male",
     "consultant_name": "Charles",
     "library_voice_id": "", "workspace_voice_id": ""},

    # ---------------- Turkish, female
    {"label": "tr_f_01", "language": "tr", "gender": "female",
     "consultant_name": "Deniz",
     "library_voice_id": "", "workspace_voice_id": "JBFqnCBsd6RMkjVDRZzb"},
    {"label": "tr_f_02", "language": "tr", "gender": "female",
     "consultant_name": "Selin",
     "library_voice_id": "", "workspace_voice_id": ""},
    {"label": "tr_f_03", "language": "tr", "gender": "female",
     "consultant_name": "Ece",
     "library_voice_id": "", "workspace_voice_id": ""},
    {"label": "tr_f_04", "language": "tr", "gender": "female",
     "consultant_name": "Ayse",
     "library_voice_id": "", "workspace_voice_id": ""},
    {"label": "tr_f_05", "language": "tr", "gender": "female",
     "consultant_name": "Nur",
     "library_voice_id": "", "workspace_voice_id": ""},

    # ---------------- Turkish, male
    {"label": "tr_m_01", "language": "tr", "gender": "male",
     "consultant_name": "Emre",
     "library_voice_id": "", "workspace_voice_id": "xctasy8XvGp2cVO9HL9k"},
    {"label": "tr_m_02", "language": "tr", "gender": "male",
     "consultant_name": "Kerem",
     "library_voice_id": "", "workspace_voice_id": ""},
    {"label": "tr_m_03", "language": "tr", "gender": "male",
     "consultant_name": "Baris",
     "library_voice_id": "", "workspace_voice_id": ""},
    {"label": "tr_m_04", "language": "tr", "gender": "male",
     "consultant_name": "Murat",
     "library_voice_id": "", "workspace_voice_id": ""},
    {"label": "tr_m_05", "language": "tr", "gender": "male",
     "consultant_name": "Tolga",
     "library_voice_id": "", "workspace_voice_id": ""},
]

HOUSE_VOICE_ID = "jqcCZkN6Knx8BJ5TBdYR"

FALLBACK = {
    "matched_voice_key": "fallback",
    "match_language": "fallback",
    "consultant_name": "your consultant",
}


def by_library_id(language=None):
    out = {}
    for v in POOL:
        if not v["library_voice_id"]:
            continue
        if language and v["language"] != language:
            continue
        out[v["library_voice_id"]] = v
    return out


def by_label(label):
    for v in POOL:
        if v["label"] == label:
            return v
    return None


def ready():
    return [v for v in POOL
            if v["library_voice_id"] and v["workspace_voice_id"]]


def status():
    return {
        "total_slots": len(POOL),
        "ready": len(ready()),
        "languages": sorted({v["language"] for v in POOL}),
        "missing_library_id": [v["label"] for v in POOL
                               if not v["library_voice_id"]],
        "missing_workspace_id": [v["label"] for v in POOL
                                 if not v["workspace_voice_id"]],
    }
