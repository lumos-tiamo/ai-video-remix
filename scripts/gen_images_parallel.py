#!/usr/bin/env python3
"""Same as gen_images.py but fires the remaining (not-yet-generated) scenes
concurrently via a thread pool -- image generation is a plain network call to
an external gateway, not local-GPU-bound like the ComfyUI cluster, so real
concurrency is safe here. Resumable: skips scenes whose image file already
exists, same as gen_images.py.

Usage: gen_images_parallel.py <scenes.json> <image_dir> [size] [workers]
"""
import json, os, sys
from concurrent.futures import ThreadPoolExecutor, as_completed
import gen_images

if __name__ == "__main__":
    scenes_path, image_dir = sys.argv[1], sys.argv[2]
    size = sys.argv[3] if len(sys.argv) > 3 else "1024x1536"
    workers = int(sys.argv[4]) if len(sys.argv) > 4 else 6
    os.makedirs(image_dir, exist_ok=True)
    scenes = json.load(open(scenes_path))

    todo = []
    for sc in scenes:
        n = sc["scene"]
        out_path = f"{image_dir}/scene{n:02d}.png"
        if os.path.exists(out_path):
            sc["image_path"] = out_path
        else:
            todo.append(sc)
    print(f"{len(scenes) - len(todo)} already done, {len(todo)} to generate with {workers} workers")

    def work(sc):
        n = sc["scene"]
        out_path = f"{image_dir}/scene{n:02d}.png"
        try:
            data, source = gen_images.generate(sc["image_prompt"], size=size)
            with open(out_path, "wb") as f:
                f.write(data)
            return n, out_path, source, None
        except Exception as e:
            return n, None, None, str(e)

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(work, sc): sc for sc in todo}
        for fut in as_completed(futures):
            n, out_path, source, err = fut.result()
            sc = futures[fut]
            if err:
                print(f"scene{n}: FAILED, leaving for a re-run: {err}")
            else:
                sc["image_path"] = out_path
                sc["image_source"] = source
                print(f"scene{n}: saved {out_path} (source: {source})")
            json.dump(scenes, open(scenes_path, "w"), indent=2, ensure_ascii=False)
