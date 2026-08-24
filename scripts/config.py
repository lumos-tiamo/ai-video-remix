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

if not NEWAPI_KEY or not COMFYUI_HOST:
    raise RuntimeError(
        "Missing NEWAPI_KEY/COMFYUI_HOST -- copy .env.example to .env in the project "
        "root and fill in your own values before running these scripts."
    )
