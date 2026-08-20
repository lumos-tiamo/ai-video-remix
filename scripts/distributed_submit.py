#!/usr/bin/env python3
"""Worked example of the *correct* ComfyUI-Distributed protocol: one
workflow, submitted once to the master, fanning out a DIFFERENT scene to
each participant via DistributedValue nodes -- not N raw /prompt POSTs to N
worker ports. See SKILL.md's Stage 3 section before using this: it got the
request right in development but hit an environment-specific bug (the
master's own worker health-probe reported 0 active workers due to what
looked like connection-pool exhaustion in a master process that had been up
for a long time) that no amount of correct request-building fixes. Confirm
`GET {master}/distributed/config` shows your workers as `enabled: true` and
that a fresh probe isn't returning 0 before relying on this for real work.

Usage: distributed_submit.py <scenes.json> <image_dir> <scene_num>[,<scene_num>...]
Assigns scenes to master + first N-1 enabled workers, in order.
"""
import json, sys, urllib.request, uuid
import config
import comfy_client as cc

def get_enabled_worker_ids():
    with urllib.request.urlopen(f"{cc.host(config.MASTER_PORT)}/distributed/config", timeout=10) as r:
        cfg = json.loads(r.read().decode())
    return [w["id"] for w in cfg.get("workers", []) if w.get("enabled")]

def distributed_value_node(default_value, worker_values, value_type=None):
    wv = dict(worker_values)
    if value_type:
        wv["_type"] = value_type
    return {"class_type": "DistributedValue", "inputs": {
        "default_value": str(default_value),
        "worker_values": json.dumps(wv),
    }}

def build_graph(scenes_by_position, first_frame_names_by_position=None):
    """scenes_by_position: [master_scene, worker1_scene, worker2_scene, ...]
    each scene a dict with narration/video_prompt/tts_duration (position 0 = master, uses
    default_value; positions 1..N = workers, keyed 1-indexed in worker_values)."""
    master_scene = scenes_by_position[0]
    worker_scenes = scenes_by_position[1:]

    prompt_default = master_scene["video_prompt"]
    prompt_worker_values = {str(i + 1): s["video_prompt"] for i, s in enumerate(worker_scenes)}

    length_default = round(master_scene["tts_duration"] * 24)
    length_worker_values = {str(i + 1): round(s["tts_duration"] * 24) for i, s in enumerate(worker_scenes)}

    prefix_default = f"remix/scene{master_scene['scene']:02d}"
    prefix_worker_values = {str(i + 1): f"remix/scene{s['scene']:02d}" for i, s in enumerate(worker_scenes)}

    g = {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": "minimax_h3_ref2va_pruned_int8_convrot.safetensors", "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": "qwen3vl_32b_minimax_h3_int8_convrot.safetensors", "type": "minimax"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": "minimax_h3_video_vae_fp16.safetensors"}},
        "4": {"class_type": "MiniMaxH3SigmaShift", "inputs": {"model": ["1", 0], "shift_video": 12.0, "shift_audio": 3.0}},
        "P": distributed_value_node(prompt_default, prompt_worker_values),
        "LEN": distributed_value_node(length_default, length_worker_values, value_type="INT"),
        "PFX": distributed_value_node(prefix_default, prefix_worker_values),
        "6": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["5", 0]}},
        "7": {"class_type": "KSampler", "inputs": {"model": ["4", 0], "seed": 424242, "steps": 20, "cfg": 1.0,
                                                     "sampler_name": "euler", "scheduler": "simple",
                                                     "positive": ["5", 0], "negative": ["6", 0],
                                                     "latent_image": ["5", 1], "denoise": 1.0}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["7", 0], "vae": ["3", 0]}},
        "9": {"class_type": "CreateVideo", "inputs": {"images": ["8", 0], "fps": 24.0}},
        "10": {"class_type": "SaveVideo", "inputs": {"video": ["9", 0], "filename_prefix": ["PFX", 0], "format": "auto", "codec": "auto"}},
    }
    node5 = {"clip": ["2", 0], "vae": ["3", 0], "prompt": ["P", 0], "width": 1088, "height": 1920, "length": ["LEN", 0]}
    if first_frame_names_by_position:
        ff_worker_values = {str(pos): fname for pos, fname in first_frame_names_by_position.items() if pos > 0}
        g["FF"] = distributed_value_node(first_frame_names_by_position.get(0, ""), ff_worker_values)
        g["FFIMG"] = {"class_type": "LoadImage", "inputs": {"image": ["FF", 0]}}
        node5["first_frame"] = ["FFIMG", 0]
    g["5"] = {"class_type": "MiniMaxH3ImageToVideo", "inputs": node5}
    return g

def submit(graph, enabled_worker_ids, delegate_master=False):
    payload = {"prompt": graph, "client_id": uuid.uuid4().hex,
               "enabled_worker_ids": enabled_worker_ids, "delegate_master": delegate_master}
    req = urllib.request.Request(f"{cc.host(config.MASTER_PORT)}/distributed/queue",
                                  data=json.dumps(payload).encode(),
                                  headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())

if __name__ == "__main__":
    scenes_path, image_dir, scene_nums = sys.argv[1], sys.argv[2], [int(x) for x in sys.argv[3].split(",")]
    scenes = json.load(open(scenes_path))
    by_num = {s["scene"]: s for s in scenes}
    positioned = [by_num[n] for n in scene_nums]

    worker_ids = get_enabled_worker_ids()
    if len(worker_ids) < len(positioned) - 1:
        raise RuntimeError(f"need {len(positioned) - 1} workers, only {len(worker_ids)} enabled")

    graph = build_graph(positioned)
    resp = submit(graph, worker_ids[:len(positioned) - 1], delegate_master=False)
    print(json.dumps(resp, indent=2))
    if resp.get("worker_count", -1) == 0 and len(positioned) > 1:
        print("worker_count is 0 despite requesting workers -- master-side probe problem, "
              "see SKILL.md. Falling back to gen_scene_master_only.py is the safe move.",
              file=sys.stderr)
