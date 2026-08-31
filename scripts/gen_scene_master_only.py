#!/usr/bin/env python3
"""Generate one scene's video, sequentially, on the master port only. This is
the default/recommended mode -- see SKILL.md before reaching for the
parallel variant. Splits automatically into two chained parts if the target
length would exceed the safe ~260-frame single-call ceiling; each scene is
conditioned on its Stage 2 first-frame image (part B is conditioned on part
A's actual last frame instead, to continue the shot rather than restart it).
"""
import json, subprocess, sys, time
import config
import comfy_client as cc

SAFE_MAX_FRAMES = 260
RETRY_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = 30

def run_one(port, prompt_text, length, filename_prefix, seed, first_frame_name, out_path, log, label,
            width=1088, height=1920):
    graph = cc.make_graph(prompt_text, length, filename_prefix, seed, first_frame_name=first_frame_name,
                           width=width, height=height)
    resp = cc.http_post_json(port, "/prompt", {"prompt": graph})
    pid = resp.get("prompt_id")
    if not pid:
        raise RuntimeError(f"{label}: submit failed: {resp}")
    cc.wait_and_download(port, pid, out_path, log, label)

def run_scene(scene, image_dir, video_dir, port, log, width=1088, height=1920):
    """Retries the whole scene (re-uploads, re-submits, same deterministic
    seed) on OOM/interrupt/timeout -- the transient errors actually seen in
    production, all self-clearing on a shared host. Anything else raises on
    the first attempt; retrying a real bug just wastes 3x the time finding
    out it's still broken."""
    n = scene["scene"]
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            return _run_scene_once(scene, image_dir, video_dir, port, log, width, height)
        except Exception as e:
            if attempt == RETRY_ATTEMPTS or not cc.is_transient_error(e):
                raise
            log(f"scene{n}: attempt {attempt}/{RETRY_ATTEMPTS} hit a transient error, "
                f"retrying in {RETRY_BACKOFF_SECONDS}s: {e}")
            time.sleep(RETRY_BACKOFF_SECONDS)

def _run_scene_once(scene, image_dir, video_dir, port, log, width=1088, height=1920):
    n = scene["scene"]
    duration = scene.get("tts_duration") or scene.get("target_duration")
    if duration is None:
        raise RuntimeError(f"scene{n}: no tts_duration or target_duration set")
    target_frames = round(duration * 24)
    ref_image_path = f"{image_dir}/scene{n:02d}.png"
    final_path = f"{video_dir}/scene{n:02d}.mp4"

    ref_image_name = cc.upload_image(port, ref_image_path)
    log(f"scene{n}: uploaded reference image as {ref_image_name}")

    seed = scene.get("seed_override", 20000 + n)
    if target_frames <= SAFE_MAX_FRAMES:
        log(f"scene{n}: single-shot generation, length={target_frames}, seed={seed}")
        run_one(port, scene["video_prompt"], target_frames, f"remix/scene{n:02d}", seed,
                ref_image_name, final_path, log, f"scene{n}", width=width, height=height)
    else:
        len_a = target_frames // 2
        len_b = target_frames - len_a
        part_a = f"{video_dir}/scene{n:02d}_partA.mp4"
        part_b = f"{video_dir}/scene{n:02d}_partB.mp4"
        last_frame = f"{video_dir}/scene{n:02d}_lastframe.png"
        log(f"scene{n}: split generation, A={len_a} B={len_b}")
        run_one(port, scene["video_prompt"], len_a, f"remix/scene{n:02d}A", 20000 + n,
                ref_image_name, part_a, log, f"scene{n} partA", width=width, height=height)
        cc.extract_last_frame(part_a, last_frame)
        continuation_name = cc.upload_image(port, last_frame)
        run_one(port, scene["video_prompt"], len_b, f"remix/scene{n:02d}B", 20100 + n,
                continuation_name, part_b, log, f"scene{n} partB", width=width, height=height)
        cc.concat_videos([part_a, part_b], final_path)

    dur = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", final_path],
                          capture_output=True, text=True).stdout.strip()
    scene["video_path"] = final_path
    scene["rendered_duration"] = float(dur) if dur else None
    log(f"scene{n}: DONE, rendered_duration={dur}s")
    return scene

if __name__ == "__main__":
    scenes_path, image_dir, video_dir = sys.argv[1], sys.argv[2], sys.argv[3]
    port = int(sys.argv[4]) if len(sys.argv) > 4 else config.MASTER_PORT
    width = int(sys.argv[5]) if len(sys.argv) > 5 else 1088
    height = int(sys.argv[6]) if len(sys.argv) > 6 else 1920
    import os
    os.makedirs(video_dir, exist_ok=True)
    log_path = f"{video_dir}/gen_log.txt"
    def log(msg):
        line = f"[{time.strftime('%H:%M:%S')}] {msg}"
        print(line, flush=True)
        with open(log_path, "a") as f:
            f.write(line + "\n")

    scenes = json.load(open(scenes_path))
    for sc in scenes:
        if sc.get("video_path"):
            log(f"scene{sc['scene']}: already done, skipping")
            continue
        try:
            run_scene(sc, image_dir, video_dir, port, log, width, height)
        except Exception as e:
            log(f"scene{sc['scene']}: FAILED: {e}")
        json.dump(scenes, open(scenes_path, "w"), indent=2, ensure_ascii=False)
    log("all scenes attempted")
