"""Shared config loader. Reads .env from the project root (walking up from
this file) so no script ever hardcodes a key, host, or port list."""
import os

def _find_env_file():
    d = os.path.dirname(os.path.abspath(__file__))
    for _ in range(6):
        candidate = os.path.join(d, ".env")
        if os.path.exists(candidate):
            return candidate
        d = os.path.dirname(d)
    return None

def load_env():
    env = dict(os.environ)
    path = _find_env_file()
    if path:
        for line in open(path):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env.setdefault(k, v)
    return env

_ENV = load_env()

NEWAPI_URL = _ENV.get("NEWAPI_URL", "").rstrip("/")
NEWAPI_KEY = _ENV.get("NEWAPI_KEY", "")
FISHAUDIO_KEY = _ENV.get("FISHAUDIO_KEY", "")  # optional -- only needed by gen_tts_fishaudio.py
ELEVENLABS_KEY = _ENV.get("ELEVENLABS_KEY", "")  # optional -- only needed by gen_tts_elevenlabs.py

# Dedicated gateway for Stage 2 image generation (gen_images.py) -- falls back to
# NEWAPI_URL/NEWAPI_KEY when unset. Text writing, TTS, etc. always use NEWAPI_*
# directly and never look at these.
IMAGE_API_URL = _ENV.get("IMAGE_API_URL", NEWAPI_URL).rstrip("/")
IMAGE_API_KEY = _ENV.get("IMAGE_API_KEY", NEWAPI_KEY)
COMFYUI_HOST = _ENV.get("COMFYUI_HOST", "")
MASTER_PORT = int(_ENV.get("COMFYUI_MASTER_PORT", "8188"))
WORKER_PORTS = [int(p) for p in _ENV.get("COMFYUI_WORKER_PORTS", "").split(",") if p.strip()]
ALL_PORTS = [MASTER_PORT] + WORKER_PORTS

# Default is conservative, not len(ALL_PORTS): the 8 ports are independent
# ComfyUI queues but have been observed sharing one real GPU (and possibly
# other tenants on a rented host) -- a scene has OOM'd even running totally
# alone, so "queue is empty" does not mean "GPU has room." Raise via env
# once you've confirmed this deployment's ports are truly GPU-isolated.
MAX_CONCURRENT = int(_ENV.get("COMFYUI_MAX_CONCURRENT", "3"))

# Character-consistency verification (verify_character.py). VERIFIER_MODEL is a
# plain vision-in/text-out model -- deliberately NOT gemini-3-pro-image-preview,
# whose job on this gateway is emitting images, not judging them. MAX_GEN_ATTEMPTS
# is kept small (1 original + a couple corrective retries) on purpose: this
# project has already run its NEWAPI credit to zero once, and a wrong bible rule
# retrying across every scene of a character is the fastest way to do that again
# -- see verify_character.py's cross-scene circuit breaker for the other half of
# that guard. VERIFY_MODE="critical-only" only verifies scenes whose checklist
# has a critical claim or a face-closeup reference (i.e. any bible-tracked
# character scene); "off" is the emergency low-credit fallback.
VERIFIER_MODEL = _ENV.get("VERIFIER_MODEL", "gemini-2.5-pro")
MAX_GEN_ATTEMPTS = int(_ENV.get("MAX_GEN_ATTEMPTS", "3"))
VERIFY_MODE = _ENV.get("VERIFY_MODE", "critical-only")

if not NEWAPI_KEY or not COMFYUI_HOST:
    raise RuntimeError(
        "Missing NEWAPI_KEY/COMFYUI_HOST -- copy .env.example to .env in the project "
        "root and fill in your own values before running these scripts."
    )
