"""Shared ComfyUI client helpers: graph construction, submit, poll, download,
last-frame extraction/upload for the split-generation continuation trick.
See SKILL.md's Stage 3 section for the reasoning behind every guardrail here."""
import json, subprocess, time, urllib.request, uuid
import config

def host(port):
    return f"http://{config.COMFYUI_HOST}:{port}"

def http_get(port, path, timeout=10):
    with urllib.request.urlopen(host(port) + path, timeout=timeout) as r:
        return json.loads(r.read().decode())

def get_queue_depth(port, timeout=5):
    """Live count of what a port is actually doing right now (running +
    pending in ComfyUI's own queue) -- the only ground truth for idle vs
    busy, since other processes on this machine submit to these same
    ports too and this client has no other way to see that."""
    q = http_get(port, "/queue", timeout=timeout)
    return len(q.get("queue_running", [])) + len(q.get("queue_pending", []))

def http_post_json(port, path, payload, timeout=15):
    req = urllib.request.Request(host(port) + path, data=json.dumps(payload).encode(),
                                  headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        raise RuntimeError(f"HTTP {e.code} from {path}: {body}") from None

def upload_image(port, image_path):
    boundary = uuid.uuid4().hex
    with open(image_path, "rb") as f:
        data = f.read()
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="image"; filename="{uuid.uuid4().hex}.png"\r\n'
        f"Content-Type: image/png\r\n\r\n"
    ).encode() + data + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        host(port) + "/upload/image", data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        resp = json.loads(r.read().decode())
    return resp["name"]

def make_graph(prompt_text, length, filename_prefix, seed, first_frame_name=None,
               unet="minimax_h3_ref2va_pruned_int8_convrot.safetensors",
               clip="qwen3vl_32b_minimax_h3_int8_convrot.safetensors",
               vae="minimax_h3_video_vae_fp16.safetensors",
               width=1088, height=1920):
    """One MiniMax-H3 text-or-image-to-video graph. Pass first_frame_name (an
    already-uploaded filename) to condition on a reference image -- required
    for stage 2's first-frame images, and for part-B continuation clips."""
    g = {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": unet, "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": clip, "type": "minimax"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": vae}},
        "4": {"class_type": "MiniMaxH3SigmaShift", "inputs": {"model": ["1", 0], "shift_video": 12.0, "shift_audio": 3.0}},
        "6": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["5", 0]}},
        "7": {"class_type": "KSampler", "inputs": {"model": ["4", 0], "seed": seed, "steps": 20, "cfg": 1.0,
                                                     "sampler_name": "euler", "scheduler": "simple",
                                                     "positive": ["5", 0], "negative": ["6", 0],
                                                     "latent_image": ["5", 1], "denoise": 1.0}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["7", 0], "vae": ["3", 0]}},
        "9": {"class_type": "CreateVideo", "inputs": {"images": ["8", 0], "fps": 24.0}},
        "10": {"class_type": "SaveVideo", "inputs": {"video": ["9", 0], "filename_prefix": filename_prefix,
                                                       "format": "auto", "codec": "auto"}},
    }
    node5 = {"clip": ["2", 0], "vae": ["3", 0], "prompt": prompt_text, "width": width, "height": height, "length": length}
    if first_frame_name is not None:
        g["11"] = {"class_type": "LoadImage", "inputs": {"image": first_frame_name}}
        node5["first_frame"] = ["11", 0]  # link, NOT the bare filename -- see SKILL.md
    g["5"] = {"class_type": "MiniMaxH3ImageToVideo", "inputs": node5}
    return g

def wait_and_download(port, prompt_id, local_path, log, label, timeout=7200, poll_interval=15):
    """7200s default is deliberate -- see SKILL.md on why a short timeout plus
    an eager /interrupt destroys real, still-progressing generations."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            hist = http_get(port, f"/history/{prompt_id}")
        except Exception as e:
            log(f"{label}: history check failed: {e}")
            time.sleep(poll_interval)
            continue
        if prompt_id in hist:
            status = hist[prompt_id].get("status", {})
            if status.get("status_str") == "success":
                outputs = hist[prompt_id].get("outputs", {})
                filename = subfolder = None
                for node_out in outputs.values():
                    for key_name in ("images", "gifs", "video"):
                        if key_name in node_out and node_out[key_name]:
                            filename = node_out[key_name][0].get("filename")
                            subfolder = node_out[key_name][0].get("subfolder")
                            break
                    if filename:
                        break
                if not filename:
                    raise RuntimeError(f"{label}: success but no output file in {outputs}")
                urllib.request.urlretrieve(f"{host(port)}/view?filename={filename}&subfolder={subfolder}&type=output", local_path)
                log(f"{label}: downloaded to {local_path}")
                return
            elif status.get("status_str") == "error":
                msgs = status.get("messages", [])
                raise RuntimeError(f"{label}: generation errored: {msgs[-1] if msgs else 'unknown'}")
        time.sleep(poll_interval)
    raise RuntimeError(f"{label}: timed out after {timeout}s waiting for completion")

def extract_last_frame(video_path, image_path):
    """The reliable way to grab the true last frame, not an approximate seek."""
    subprocess.run(["ffmpeg", "-y", "-sseof", "-1", "-i", video_path, "-update", "1", "-q:v", "2", image_path],
                    check=True, capture_output=True, text=True)

def concat_videos(part_paths, out_path):
    list_path = out_path + ".concat.txt"
    with open(list_path, "w") as f:
        for p in part_paths:
            f.write(f"file '{p}'\n")
    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_path, "-c", "copy", out_path],
                    check=True, capture_output=True, text=True)
