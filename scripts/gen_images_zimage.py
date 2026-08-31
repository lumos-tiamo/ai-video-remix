#!/usr/bin/env python3
"""Stage-2 first-frame generation via the LOCAL Z-Image-Turbo model already
loaded on the shared ComfyUI cluster (z_image_turbo_bf16.safetensors +
qwen_3_4b.safetensors text encoder + ae.safetensors VAE) -- free, no NEWAPI
credit spent, as an alternative to gen_images.py's paid gpt-image-2 call.

Graph verified against the official Comfy-Org workflow_templates
image_z_image_turbo.json (not guessed): CLIPLoader type MUST be "lumina2"
(Z-Image reuses Lumina2's CLIP loading path, there is no dedicated "z_image"
CLIPLoader type on this ComfyUI build) and the VAE is Flux's ae.safetensors,
not a Z-Image-specific file -- both look wrong at a glance but are correct.

Two ways this gets used:
- Run directly (see __main__ below) as a side-by-side comparison tool: never
  touches scenes.json or the production image_path field, writes into a
  separate output directory so existing gpt-image-2 renders are untouched.
  Verified against this project's own scenes: content is right but the style
  is noticeably flatter/more "vector illustration" than gpt-image-2's
  painterly-cinematic look -- good enough as a placeholder, not a silent
  drop-in for a whole batch. Eyeball a few scenes before trusting more.
- Imported by gen_images.py as its automatic fallback when gpt-image-2 is
  exhausted (billing/quota/gateway outage). That path calls generate_bytes().
"""
import json, os, sys, tempfile
import config
import comfy_client as cc

def make_graph(prompt_text, seed, filename_prefix, width=1536, height=1024,
               unet="z_image_turbo_bf16.safetensors", clip="qwen_3_4b.safetensors",
               vae="ae.safetensors", shift=3, steps=8, cfg=1,
               sampler_name="res_multistep", scheduler="simple"):
    g = {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": unet, "weight_dtype": "default"}},
        "2": {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": ["1", 0], "shift": shift}},
        "3": {"class_type": "CLIPLoader", "inputs": {"clip_name": clip, "type": "lumina2", "device": "default"}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["3", 0], "text": prompt_text}},
        "5": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["4", 0]}},
        "6": {"class_type": "VAELoader", "inputs": {"vae_name": vae}},
        "7": {"class_type": "EmptySD3LatentImage", "inputs": {"width": width, "height": height, "batch_size": 1}},
        "8": {"class_type": "KSampler", "inputs": {"model": ["2", 0], "positive": ["4", 0], "negative": ["5", 0],
                                                     "latent_image": ["7", 0], "seed": seed, "steps": steps,
                                                     "cfg": cfg, "sampler_name": sampler_name,
                                                     "scheduler": scheduler, "denoise": 1}},
        "9": {"class_type": "VAEDecode", "inputs": {"samples": ["8", 0], "vae": ["6", 0]}},
        "10": {"class_type": "SaveImage", "inputs": {"images": ["9", 0], "filename_prefix": filename_prefix}},
    }
    return g

def generate_one(port, prompt_text, seed, filename_prefix, out_path, log, label, width=1536, height=1024):
    graph = make_graph(prompt_text, seed, filename_prefix, width=width, height=height)
    resp = cc.http_post_json(port, "/prompt", {"prompt": graph})
    pid = resp.get("prompt_id")
    if not pid:
        raise RuntimeError(f"{label}: submit failed: {resp}")
    cc.wait_and_download(port, pid, out_path, log, label, timeout=600, poll_interval=5)

def pick_idle_port(candidates=None):
    """MASTER_PORT is NOT a safe default -- it's the port Stage 3 video jobs
    land on most often, and a queued-behind-a-video-job image request will
    sit for the full wait_and_download timeout without ever running (hit
    this for real: a fallback call queued behind a Stage 3 job on 8188 timed
    out at 600s while an idle worker port would have returned in ~15s).
    Scans config.ALL_PORTS via /queue and returns the first truly idle one,
    falling back to whichever has the shallowest queue if none are idle."""
    candidates = candidates or config.ALL_PORTS
    best_port, best_depth = candidates[0], None
    for p in candidates:
        try:
            depth = cc.get_queue_depth(p)
        except Exception:
            continue
        if depth == 0:
            return p
        if best_depth is None or depth < best_depth:
            best_port, best_depth = p, depth
    return best_port

def generate_bytes(prompt_text, width=1536, height=1024, port=None, seed=None, log=None):
    """Same graph as generate_one(), but returns raw PNG bytes instead of
    writing to a caller-chosen path -- what gen_images.py's fallback branch
    needs (it writes the final file itself, same as the gpt-image-2 path)."""
    log = log or (lambda msg: None)
    port = port or pick_idle_port()
    log(f"zimage-fallback: using port {port}")
    seed = seed if seed is not None else int.from_bytes(os.urandom(4), "big")
    with tempfile.TemporaryDirectory() as td:
        tmp_path = os.path.join(td, "out.png")
        generate_one(port, prompt_text, seed, "zimage_fallback/scene", tmp_path, log, "zimage-fallback",
                     width=width, height=height)
        with open(tmp_path, "rb") as f:
            return f.read()

if __name__ == "__main__":
    scenes_path, out_dir, scene_list = sys.argv[1], sys.argv[2], sys.argv[3]
    width = int(sys.argv[4]) if len(sys.argv) > 4 else 1536
    height = int(sys.argv[5]) if len(sys.argv) > 5 else 1024
    port = int(sys.argv[6]) if len(sys.argv) > 6 else config.MASTER_PORT

    os.makedirs(out_dir, exist_ok=True)
    def log(msg):
        print(msg, flush=True)

    wanted = {int(s) for s in scene_list.split(",")}
    scenes = json.load(open(scenes_path))
    for sc in scenes:
        n = sc["scene"]
        if n not in wanted:
            continue
        out_path = f"{out_dir}/scene{n:02d}_zimage.png"
        if os.path.exists(out_path):
            log(f"scene{n}: already exists, skipping")
            continue
        try:
            seed = 90000 + n
            generate_one(port, sc["image_prompt"], seed, f"zimage_test/scene{n:02d}", out_path, log, f"scene{n}",
                         width=width, height=height)
            log(f"scene{n}: saved {out_path}")
        except Exception as e:
            log(f"scene{n}: FAILED: {e}")
