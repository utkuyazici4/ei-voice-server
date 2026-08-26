"""
The voice pool.

One cell per language x gender x age band. Twenty cells for five languages.

Each cell has:
  default_key       the voice used when similar-voices is off, or when it
                    fails, or when the cell has only one candidate
  candidates        the voices similar-voices may choose between, if enabled
  consultant_name   the name the agent introduces itself with, so name and
                    voice always match

The keys here MUST match the voice labels you configured in the ElevenLabs
Voice tab, exactly and case sensitively. en_03 here means a supported voice
labelled en_03 there.

library_voice_id is only needed when USE_SIMILAR_VOICES is on. It is the
shared-library id that /v1/similar-voices returns, which is not the same as
the workspace id the agent uses.
"""

LANGUAGES = ["en", "ar", "de", "ru", "tr"]
GENDERS = ["female", "male"]
AGE_BANDS = ["younger", "older"]


def _cell(keys, name):
    return {
        "default_key": keys[0],
        "consultant_name": name,
        "candidates": [{"key": k, "library_voice_id": ""} for k in keys],
    }


# Fill the names with whatever you want the agent to introduce itself as.
# Fill the key lists with the labels you created in the Voice tab.
POOL = {
    # ---- English
    ("en", "female", "younger"): _cell(["en_01"], "Elena"),
    ("en", "female", "older"):   _cell(["en_02"], "Margaret"),
    ("en", "male",   "younger"): _cell(["en_03"], "Daniel"),
    ("en", "male",   "older"):   _cell(["en_04"], "Robert"),

    # ---- Arabic
    ("ar", "female", "younger"): _cell(["ar_01"], "Layla"),
    ("ar", "female", "older"):   _cell(["ar_02"], "Samira"),
    ("ar", "male",   "younger"): _cell(["ar_03"], "Karim"),
    ("ar", "male",   "older"):   _cell(["ar_04"], "Tarek"),

    # ---- German
    ("de", "female", "younger"): _cell(["de_01"], "Lena"),
    ("de", "female", "older"):   _cell(["de_02"], "Ingrid"),
    ("de", "male",   "younger"): _cell(["de_03"], "Jonas"),
    ("de", "male",   "older"):   _cell(["de_04"], "Klaus"),

    # ---- Russian
    ("ru", "female", "younger"): _cell(["ru_01"], "Anna"),
    ("ru", "female", "older"):   _cell(["ru_02"], "Irina"),
    ("ru", "male",   "younger"): _cell(["ru_03"], "Dmitri"),
    ("ru", "male",   "older"):   _cell(["ru_04"], "Sergei"),

    # ---- Turkish
    ("tr", "female", "younger"): _cell(["tr_01"], "Deniz"),
    ("tr", "female", "older"):   _cell(["tr_02"], "Ayse"),
    ("tr", "male",   "younger"): _cell(["tr_03"], "Emre"),
    ("tr", "male",   "older"):   _cell(["tr_04"], "Murat"),
}


def lookup(language, gender, age_band):
    """
    Returns the cell, or None if anything is unknown. None means fallback,
    which is the right answer whenever we are not sure.
    """
    if not language or not gender or not age_band:
        return None
    if gender == "unknown" or age_band == "unknown":
        return None
    return POOL.get((language, gender, age_band))


def all_keys():
    keys = []
    for cell in POOL.values():
        keys.extend(c["key"] for c in cell["candidates"])
    return keys
