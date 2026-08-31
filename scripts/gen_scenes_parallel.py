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

Scheduling: before every dispatch we scan each port's *live* ComfyUI queue
(GET /queue) rather than trusting what this process itself assigned --
other projects on this machine submit to the same 8 ports, so a port this
script thinks is "busy" may already be idle, and vice versa. Each finished
scene immediately frees its port and triggers a rescan, instead of waiting
for an entire same-sized batch to clear (the old lockstep-batch scheduler
let fast ports sit idle behind one slow scene).

Concurrency is capped at config.MAX_CONCURRENT (default 3), not
len(ports): a scene has OOM'd running completely alone at a frame count
well under the documented safe ceiling, meaning the 8 ports don't have 8
ports' worth of independent GPU headroom behind them. gen_scene_master_only
.run_scene() itself retries OOM/interrupt/timeout with backoff, so a scene
that fails this way gets a few staggered second chances before it's
counted as a real failure.

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
import comfy_client as cc

def pick_idle_port(ports, claimed, log):
    """Scan the live queue depth of every port not already claimed by this
    run and return the shallowest one. A port that fails to respond is
    treated as busy (a hung worker is not a fast lane) and logged, so a
    hang is visible instead of silently masked."""
    depths = {}
    for p in (p for p in ports if p not in claimed):
        try:
            depths[p] = cc.get_queue_depth(p)
        except Exception as e:
            log(f"port {p}: queue scan failed, treating as busy: {e}")
    if not depths:
        return None
    return min(depths, key=depths.get)

def run_all(scenes_path, image_dir, video_dir, scene_nums, log, width=1088, height=1920):
    scenes = json.load(open(scenes_path))
    by_num = {s["scene"]: s for s in scenes}
    ports = config.ALL_PORTS
    max_concurrent = min(len(ports), config.MAX_CONCURRENT)
    pending = [n for n in scene_nums if not by_num[n].get("video_path")]
    claimed = set()
    in_flight = {}

    def fill(ex):
        while pending and len(in_flight) < max_concurrent:
            port = pick_idle_port(ports, claimed, log)
            if port is None:
                if in_flight:
                    return
                log("all ports currently busy (likely another process) -- waiting to rescan")
                time.sleep(10)
                continue
            n = pending.pop(0)
            claimed.add(port)
            log(f"scene{n}: dispatching to port {port} (idlest of {ports}, "
                f"{len(in_flight) + 1}/{max_concurrent} concurrent, {len(pending)} left)")
            fut = ex.submit(gsmo.run_scene, by_num[n], image_dir, video_dir, port, log, width, height)
            in_flight[fut] = (n, port)

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_concurrent) as ex:
        fill(ex)
        while in_flight:
            done, _ = concurrent.futures.wait(in_flight, return_when=concurrent.futures.FIRST_COMPLETED)
            for fut in done:
                n, port = in_flight.pop(fut)
                try:
                    fut.result()
                except Exception as e:
                    log(f"scene{n}: FAILED: {e}")
                claimed.discard(port)
                json.dump(scenes, open(scenes_path, "w"), indent=2, ensure_ascii=False)
            fill(ex)
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

    if len(sys.argv) > 4 and sys.argv[4]:
        scene_nums = [int(x) for x in sys.argv[4].split(",")]
    else:
        scene_nums = [s["scene"] for s in json.load(open(scenes_path))]
    width = int(sys.argv[5]) if len(sys.argv) > 5 else 1088
    height = int(sys.argv[6]) if len(sys.argv) > 6 else 1920

    run_all(scenes_path, image_dir, video_dir, scene_nums, log, width, height)
