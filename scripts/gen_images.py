#!/usr/bin/env python3
"""Generate first-frame reference images for every scene. High-quality
generations can take 2-4 minutes each -- the 300s timeout here is deliberate,
not a mistake. Resumable: skips scenes whose image already exists.

Falls back to the local, free Z-Image-Turbo model on the ComfyUI cluster
(gen_images_zimage.py) when gpt-image-2 is exhausted (billing/quota/gateway
outage -- this project has hit all three). The fallback's illustration style
is flatter/less painterly than gpt-image-2 (verified side by side on this
project's own scenes -- see gen_images_zimage.py's module docstring), so
every scene that used it is tagged image_source="zimage-fallback" in
scenes.json -- grep for that to find which scenes are placeholders still
worth re-rolling with gpt-image-2 once the primary gateway is back."""
import base64, json, os, sys, urllib.request
import config
import gen_images_zimage as zimg

def _parse_size(size):
    w, h = size.lower().split("x")
    return int(w), int(h)

def generate(prompt, model="gpt-image-2", size="1024x1536", quality="medium", retries=2, allow_fallback=True):
    """quality="high" reliably 504s on this gateway somewhere past ~5-10
    minutes (its own server-side timeout, shorter than any client timeout
    you set) -- "medium" is the practical reliable default; bump to "high"
    only if you can tolerate a meaningful failure rate and have retries.

    Handles two response shapes: data[0].b64_json (inline, e.g. the
    elevatesphere gateway) and data[0].url (hosted on a third-party CDN,
    e.g. the n.lconai.com gateway) -- fetches the URL if b64_json is absent.

    Returns (image_bytes, source) where source is "gpt-image-2" or
    "zimage-fallback". Raises only if both the primary call and the fallback
    fail (or allow_fallback=False and the primary call fails)."""
    req = urllib.request.Request(
        f"{config.IMAGE_API_URL}/v1/images/generations",
        data=json.dumps({"model": model, "prompt": prompt, "n": 1, "size": size, "quality": quality}).encode(),
        headers={"Authorization": f"Bearer {config.IMAGE_API_KEY}", "Content-Type": "application/json"},
    )
    last_exc = None
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=280) as r:
                resp = json.loads(r.read().decode())
            item = resp["data"][0]
            if item.get("b64_json"):
                return base64.b64decode(item["b64_json"]), "gpt-image-2"
            with urllib.request.urlopen(item["url"], timeout=60) as img_r:
                return img_r.read(), "gpt-image-2"
        except Exception as e:
            last_exc = e
            print(f"  attempt {attempt + 1} failed: {e}, retrying" if attempt < retries else f"  attempt {attempt + 1} failed: {e}, giving up")

    if not allow_fallback:
        raise last_exc
    print(f"  gpt-image-2 exhausted ({last_exc}), falling back to local Z-Image-Turbo")
    width, height = _parse_size(size)
    try:
        return zimg.generate_bytes(prompt, width=width, height=height, log=print), "zimage-fallback"
    except Exception as fallback_exc:
        raise RuntimeError(f"gpt-image-2 failed ({last_exc}) AND zimage fallback failed ({fallback_exc})") from fallback_exc

if __name__ == "__main__":
    scenes_path, image_dir = sys.argv[1], sys.argv[2]
    size = sys.argv[3] if len(sys.argv) > 3 else "1024x1536"
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
            data, source = generate(sc["image_prompt"], size=size)
            with open(out_path, "wb") as f:
                f.write(data)
            sc["image_path"] = out_path
            sc["image_source"] = source
            print(f"scene{n}: saved {out_path} (source: {source})")
        except Exception as e:
            print(f"scene{n}: FAILED, leaving for a re-run: {e}")
        json.dump(scenes, open(scenes_path, "w"), indent=2, ensure_ascii=False)
