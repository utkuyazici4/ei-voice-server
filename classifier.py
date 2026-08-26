"""
Gender and age-band classification from 8kHz mu-law telephone audio.

Two backends:

  pitch      Pure signal processing. No model download, no GPU, milliseconds.
             Gender from fundamental frequency, which survives the telephone
             band intact. Age band is a rough guess from pitch stability and
             spectral tilt, and it is the weaker half of this.

  speechbrain
             A pretrained model. Better on age, slower, needs the download.
             Off by default so the service starts fast.

Swap with CLASSIFIER_BACKEND. Start on pitch, compare against speechbrain
once you have real calls to compare on.
"""

import audioop
import logging
import os

import numpy as np

log = logging.getLogger("vm.classifier")

BACKEND = os.getenv("CLASSIFIER_BACKEND", "pitch")
SAMPLE_RATE = 8000

# Fundamental frequency boundaries in Hz. The gap between them is the
# ambiguous zone where we lower confidence rather than guess.
MALE_MAX_F0 = 155.0
FEMALE_MIN_F0 = 185.0


def mulaw_to_float(mulaw: bytes) -> np.ndarray:
    """Twilio sends 8-bit mu-law. Convert to 16-bit PCM then to float."""
    pcm16 = audioop.ulaw2lin(mulaw, 2)
    samples = np.frombuffer(pcm16, dtype=np.int16).astype(np.float32)
    return samples / 32768.0


def _frame_f0(frame: np.ndarray, sr: int = SAMPLE_RATE) -> float | None:
    """
    Fundamental frequency of one frame by autocorrelation.
    Returns None for frames that look like silence or noise.
    """
    if np.sqrt(np.mean(frame ** 2)) < 0.01:
        return None

    frame = frame - np.mean(frame)
    corr = np.correlate(frame, frame, mode="full")[len(frame) - 1:]

    if corr[0] <= 0:
        return None
    corr = corr / corr[0]

    # Search 70Hz to 320Hz, which covers adult speech comfortably.
    min_lag = int(sr / 320)
    max_lag = int(sr / 70)
    if max_lag >= len(corr):
        return None

    window = corr[min_lag:max_lag]
    if len(window) == 0:
        return None

    peak = int(np.argmax(window)) + min_lag
    # A weak peak means no clear periodicity, so no usable pitch.
    if corr[peak] < 0.30:
        return None

    return sr / peak


def _spectral_tilt(samples: np.ndarray) -> float:
    """
    Ratio of high-band to low-band energy. Older voices tend to carry
    relatively more high-frequency noise from breathiness. Crude, but it is
    one of the few age cues that survives 8kHz.
    """
    spectrum = np.abs(np.fft.rfft(samples))
    freqs = np.fft.rfftfreq(len(samples), 1 / SAMPLE_RATE)
    low = spectrum[(freqs >= 100) & (freqs < 1000)].sum()
    high = spectrum[(freqs >= 2000) & (freqs < 3800)].sum()
    if low <= 0:
        return 0.0
    return float(high / low)


def _classify_pitch(mulaw: bytes) -> dict:
    samples = mulaw_to_float(mulaw)

    if len(samples) < SAMPLE_RATE:  # under one second
        return {"gender": "unknown", "age_band": "unknown", "confidence": 0.0}

    # 40ms frames, 20ms hop.
    frame_len = int(0.040 * SAMPLE_RATE)
    hop = int(0.020 * SAMPLE_RATE)

    f0s = []
    for start in range(0, len(samples) - frame_len, hop):
        f0 = _frame_f0(samples[start:start + frame_len])
        if f0 is not None:
            f0s.append(f0)

    if len(f0s) < 10:
        log.info("only %d voiced frames, not enough", len(f0s))
        return {"gender": "unknown", "age_band": "unknown", "confidence": 0.0}

    f0s_arr = np.array(f0s)
    # Trim outliers before taking the centre.
    lo, hi = np.percentile(f0s_arr, [10, 90])
    core = f0s_arr[(f0s_arr >= lo) & (f0s_arr <= hi)]
    median_f0 = float(np.median(core)) if len(core) else float(np.median(f0s_arr))
    f0_std = float(np.std(core)) if len(core) else 0.0

    # ---- gender
    if median_f0 <= MALE_MAX_F0:
        gender = "male"
        margin = (MALE_MAX_F0 - median_f0) / MALE_MAX_F0
    elif median_f0 >= FEMALE_MIN_F0:
        gender = "female"
        margin = (median_f0 - FEMALE_MIN_F0) / FEMALE_MIN_F0
    else:
        # Ambiguous zone. Lean on the nearer side but say so with low
        # confidence, which sends the call to fallback.
        midpoint = (MALE_MAX_F0 + FEMALE_MIN_F0) / 2
        gender = "male" if median_f0 < midpoint else "female"
        margin = 0.0

    # More voiced frames means a steadier estimate.
    coverage = min(len(f0s) / 150.0, 1.0)
    confidence = round(min(0.55 + margin * 1.6, 0.97) * (0.6 + 0.4 * coverage), 3)

    # ---- age band
    tilt = _spectral_tilt(samples)
    jitter = f0_std / median_f0 if median_f0 else 0.0

    # Older voices: breathier (higher tilt) and less stable (higher jitter).
    age_score = tilt * 2.0 + jitter * 3.0
    age_band = "older" if age_score > 1.15 else "younger"

    return {
        "gender": gender,
        "age_band": age_band,
        "confidence": confidence,
        "median_f0": round(median_f0, 1),
        "f0_std": round(f0_std, 1),
        "tilt": round(tilt, 3),
        "jitter": round(jitter, 3),
        "voiced_frames": len(f0s),
        "backend": "pitch",
    }


def _classify_speechbrain(mulaw: bytes) -> dict:
    """
    Placeholder for the model backend. Fill this in once you have decided
    which pretrained model to use, then set CLASSIFIER_BACKEND=speechbrain.
    Falls back to pitch so the service never breaks.
    """
    log.warning("speechbrain backend not wired up yet, using pitch")
    return _classify_pitch(mulaw)


def classify(mulaw: bytes) -> dict:
    if BACKEND == "speechbrain":
        return _classify_speechbrain(mulaw)
    return _classify_pitch(mulaw)
