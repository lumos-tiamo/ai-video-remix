#!/usr/bin/env python3
"""Parallel scene generation across all 8 ports (master + 7 workers), bypassing
/distributed/queue entirely -- each scene is submitted as a fully independent
bare /prompt against its own port via gen_scene_master_only.run_scene().

Use this when scenes differ in length/content/prompt (the normal case for a
multi-scene remix). The official ComfyUI-Distributed protocol
(DistributedCollector, see distributed_submit.py) merges same-length
seed-variants of ONE scene into a single collected batch -- confirmed via a
live 2-scene test and the plugin's own docs (github.com/robertvoy/
ComfyUI-Distributed: "Does it speed up the generation of a single image or
video? No."). It's the right tool for "N seed takes of one scene, pick the
best" (optionally split back into N separate files with Image Batch
Divider), not for "N different scenes, each its own file" -- that's what
this script is for.

Known risk (see SKILL.md Stage 3): in prior production runs, individual
workers have occasionally hung 30+ minutes with root cause not fully
identified. A scene that doesn't complete is logged as FAILED and left
without a video_path in scenes.json -- rerun this script (or
gen_scene_master_only.py against one port) later and it'll skip scenes
that already succeeded and only retry the failed ones.
"""
import concurrent.futures, json, os, sys, time
import config
import gen_scene_master_only as gsmo

def run_batch(scenes, image_dir, video_dir, ports, log):
    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(scenes)) as ex:
        futures = {ex.submit(gsmo.run_scene, sc, image_dir, video_dir, port, log): sc["scene"]
                   for sc, port in zip(scenes, ports)}
        for fut in concurrent.futures.as_completed(futures):
            n = futures[fut]
            try:
                results[n] = fut.result()
            except Exception as e:
                log(f"scene{n}: FAILED: {e}")
    return results

def run_all(scenes_path, image_dir, video_dir, scene_nums, log):
    scenes = json.load(open(scenes_path))
    by_num = {s["scene"]: s for s in scenes}
    ports = config.ALL_PORTS
    pending = [n for n in scene_nums if not by_num[n].get("video_path")]
    for i in range(0, len(pending), len(ports)):
        batch_nums = pending[i:i + len(ports)]
        batch = [by_num[n] for n in batch_nums]
        batch_ports = ports[:len(batch)]
        log(f"batch {i // len(ports) + 1}: scenes {batch_nums} on ports {batch_ports}")
        run_batch(batch, image_dir, video_dir, batch_ports, log)
        json.dump(scenes, open(scenes_path, "w"), indent=2, ensure_ascii=False)
    log("all scenes attempted")

if __name__ == "__main__":
    scenes_path, image_dir, video_dir = sys.argv[1], sys.argv[2], sys.argv[3]
    os.makedirs(video_dir, exist_ok=True)
    log_path = f"{video_dir}/gen_log.txt"
    def log(msg):
        line = f"[{time.strftime('%H:%M:%S')}] {msg}"
        print(line, flush=True)
        with open(log_path, "a") as f:
            f.write(line + "\n")

    if len(sys.argv) > 4:
        scene_nums = [int(x) for x in sys.argv[4].split(",")]
    else:
        scene_nums = [s["scene"] for s in json.load(open(scenes_path))]

    run_all(scenes_path, image_dir, video_dir, scene_nums, log)
