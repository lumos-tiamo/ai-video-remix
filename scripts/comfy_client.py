"""Shared ComfyUI client helpers: graph construction, submit, poll, download,
last-frame extraction/upload for the split-generation continuation trick.
See SKILL.md's Stage 3 section for the reasoning behind every guardrail here."""
import json, os, subprocess, time, urllib.request, uuid
import config

def host(port):
    return f"http://{config.COMFYUI_HOST}:{port}"

def http_get(port, path, timeout=10):
    with urllib.request.urlopen(host(port) + path, timeout=timeout) as r:
        return json.loads(r.read().decode())

TRANSIENT_ERROR_MARKERS = ("OutOfMemoryError", "execution_interrupted", "timed out")

def is_transient_error(exc):
    """True for the error classes actually observed to clear up on their own:
    GPU OOM on a shared/rented host (someone else's load can free up), a job
    getting interrupted (worker-hang recovery), or a bare network timeout
    under momentary host load. Everything else is treated as a real bug and
    surfaced immediately instead of retried."""
    return any(marker in str(exc) for marker in TRANSIENT_ERROR_MARKERS)

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

def upload_audio(port, audio_path):
    """Same /upload/image endpoint as upload_image (it just saves to the input/
    folder regardless of the 'image' field name), but with a real audio filename
    extension and content-type -- LoadAudio's decoder sniffs/relies on the
    extension server-side, so uploading an mp3 with a fake '.png' name (as
    upload_image always does) makes it fail with 'No audio stream found'."""
    ext = os.path.splitext(audio_path)[1].lstrip(".") or "mp3"
    mime = {"mp3": "audio/mpeg", "wav": "audio/wav", "m4a": "audio/mp4", "ogg": "audio/ogg"}.get(ext, "audio/mpeg")
    boundary = uuid.uuid4().hex
    with open(audio_path, "rb") as f:
        data = f.read()
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="image"; filename="{uuid.uuid4().hex}.{ext}"\r\n'
        f"Content-Type: {mime}\r\n\r\n"
    ).encode() + data + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        host(port) + "/upload/image", data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        resp = json.loads(r.read().decode())
    return resp["name"]

# Ops-delivered "8步增速" recipe (Minimax+H3+最新8步增速工作流.215修复版.json, node
# group 60/67): same unet+lora pair reused verbatim for BOTH the ReferenceToVideo
# branch (node 387/389) and the ImageToVideo branch (node 437/447) of that workflow --
# so there's no separate ref2va-vs-fl2va checkpoint choice to make per node type.
# Verified present and parameter-compatible on the live cluster (192.168.100.215)
# on 2026-08-26: all of UNETLoader/LoraLoaderBypassModelOnly/MiniMaxH3DualClockSamplerT8
# /RandomNoise/BasicGuider/SamplerCustomAdvanced are registered with matching input names.
DEFAULT_TURBO_UNET = "minimax_h3_fl2va_int8_convrot.safetensors"
DEFAULT_TURBO_LORA = "minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors"
DEFAULT_TURBO_STEPS = 8

def add_turbo_sampler_chain(g, model_node_id, positive_link, av_latent_link, seed, base_id="T",
                             lora=DEFAULT_TURBO_LORA, steps=DEFAULT_TURBO_STEPS,
                             shift_video=12.0, shift_audio=3.0,
                             sampler_name="dual_clock_euler", scheduler="native_flow"):
    """Mutates g in place: LoraLoaderBypassModelOnly -> MiniMaxH3DualClockSamplerT8 ->
    RandomNoise/BasicGuider -> SamplerCustomAdvanced. Drop-in replacement for the legacy
    MiniMaxH3SigmaShift + 20-step-KSampler chain -- same shift_video/shift_audio values,
    just distilled to `steps` steps via the turbo LoRA. Returns the ["<id>", 0] link for
    the resulting sampled LATENT (what VAEDecode's "samples" input expects)."""
    lora_id, dc_id, noise_id, guider_id, out_id = (f"{base_id}{s}" for s in ("lora", "dc", "noise", "guider", "out"))
    g[lora_id] = {"class_type": "LoraLoaderBypassModelOnly",
                  "inputs": {"model": [model_node_id, 0], "lora_name": lora, "strength_model": 1.0}}
    g[dc_id] = {"class_type": "MiniMaxH3DualClockSamplerT8",
                "inputs": {"model": [lora_id, 0], "av_latent": av_latent_link, "steps": steps,
                           "shift_video": shift_video, "shift_audio": shift_audio,
                           "sampler_name": sampler_name, "scheduler": scheduler}}
    g[noise_id] = {"class_type": "RandomNoise", "inputs": {"noise_seed": seed}}
    g[guider_id] = {"class_type": "BasicGuider", "inputs": {"model": [dc_id, 0], "conditioning": positive_link}}
    g[out_id] = {"class_type": "SamplerCustomAdvanced",
                 "inputs": {"noise": [noise_id, 0], "guider": [guider_id, 0], "sampler": [dc_id, 1],
                            "sigmas": [dc_id, 2], "latent_image": av_latent_link}}
    return [out_id, 0]

def make_graph(prompt_text, length, filename_prefix, seed, first_frame_name=None,
               unet=None,
               clip="qwen3vl_32b_minimax_h3_int8_convrot.safetensors",
               vae="minimax_h3_video_vae_fp16.safetensors",
               width=1088, height=1920,
               turbo=True, turbo_lora=DEFAULT_TURBO_LORA, turbo_steps=DEFAULT_TURBO_STEPS):
    """One MiniMax-H3 text-or-image-to-video graph. Pass first_frame_name (an
    already-uploaded filename) to condition on a reference image -- required
    for stage 2's first-frame images, and for part-B continuation clips.

    turbo=True (default) uses the ops-verified 8-step DualClockSamplerT8 recipe
    (~2.5x fewer sampling steps than the legacy 20-step KSampler path). Pass
    turbo=False to roll a specific call back to the original path unchanged."""
    if unet is None:
        unet = DEFAULT_TURBO_UNET if turbo else "minimax_h3_ref2va_pruned_int8_convrot.safetensors"
    g = {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": unet, "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": clip, "type": "minimax"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": vae}},
    }
    node5 = {"clip": ["2", 0], "vae": ["3", 0], "prompt": prompt_text, "width": width, "height": height, "length": length}
    if first_frame_name is not None:
        g["11"] = {"class_type": "LoadImage", "inputs": {"image": first_frame_name}}
        node5["first_frame"] = ["11", 0]  # link, NOT the bare filename -- see SKILL.md
    g["5"] = {"class_type": "MiniMaxH3ImageToVideo", "inputs": node5}

    if turbo:
        samples_link = add_turbo_sampler_chain(g, "1", ["5", 0], ["5", 1], seed, lora=turbo_lora, steps=turbo_steps)
    else:
        g["4"] = {"class_type": "MiniMaxH3SigmaShift", "inputs": {"model": ["1", 0], "shift_video": 12.0, "shift_audio": 3.0}}
        g["6"] = {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["5", 0]}}
        g["7"] = {"class_type": "KSampler", "inputs": {"model": ["4", 0], "seed": seed, "steps": 20, "cfg": 1.0,
                                                         "sampler_name": "euler", "scheduler": "simple",
                                                         "positive": ["5", 0], "negative": ["6", 0],
                                                         "latent_image": ["5", 1], "denoise": 1.0}}
        samples_link = ["7", 0]

    g["8"] = {"class_type": "VAEDecode", "inputs": {"samples": samples_link, "vae": ["3", 0]}}
    g["9"] = {"class_type": "CreateVideo", "inputs": {"images": ["8", 0], "fps": 24.0}}
    g["10"] = {"class_type": "SaveVideo", "inputs": {"video": ["9", 0], "filename_prefix": filename_prefix,
                                                       "format": "auto", "codec": "auto"}}
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
            f.write(f"file '{os.path.abspath(p)}'\n")
    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_path, "-c", "copy", out_path],
                    check=True, capture_output=True, text=True)
