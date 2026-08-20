#!/usr/bin/env python3
"""Generate first-frame reference images for every scene. High-quality
generations can take 2-4 minutes each -- the 300s timeout here is deliberate,
not a mistake. Resumable: skips scenes whose image already exists."""
import base64, json, os, sys, urllib.request
import config

def generate(prompt, model="gpt-image-2", size="1024x1536", quality="medium", retries=2):
    """quality="high" reliably 504s on this gateway somewhere past ~5-10
    minutes (its own server-side timeout, shorter than any client timeout
    you set) -- "medium" is the practical reliable default; bump to "high"
    only if you can tolerate a meaningful failure rate and have retries."""
    req = urllib.request.Request(
        f"{config.NEWAPI_URL}/v1/images/generations",
        data=json.dumps({"model": model, "prompt": prompt, "n": 1, "size": size, "quality": quality}).encode(),
        headers={"Authorization": f"Bearer {config.NEWAPI_KEY}", "Content-Type": "application/json"},
    )
    last_exc = None
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=280) as r:
                resp = json.loads(r.read().decode())
            return base64.b64decode(resp["data"][0]["b64_json"])
        except Exception as e:
            last_exc = e
            print(f"  attempt {attempt + 1} failed: {e}, retrying" if attempt < retries else f"  attempt {attempt + 1} failed: {e}, giving up")
    raise last_exc

if __name__ == "__main__":
    scenes_path, image_dir = sys.argv[1], sys.argv[2]
    os.makedirs(image_dir, exist_ok=True)
    scenes = json.load(open(scenes_path))
    for sc in scenes:
        n = sc["scene"]
        out_path = f"{image_dir}/scene{n:02d}.png"
        if os.path.exists(out_path):
            print(f"scene{n}: already exists, skipping")
            sc["image_path"] = out_path
            continue
        try:
            data = generate(sc["image_prompt"])
            with open(out_path, "wb") as f:
                f.write(data)
            sc["image_path"] = out_path
            print(f"scene{n}: saved {out_path}")
        except Exception as e:
            print(f"scene{n}: FAILED, leaving for a re-run: {e}")
        json.dump(scenes, open(scenes_path, "w"), indent=2, ensure_ascii=False)
