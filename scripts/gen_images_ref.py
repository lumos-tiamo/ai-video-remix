#!/usr/bin/env python3
"""Generate first-frame reference images for every scene, IMAGE-CONDITIONED on
one or more real character reference photos (each scene's "ref_images" list
of file paths) via gemini-3-pro-image-preview through /v1/chat/completions.

Why this exists instead of gen_images.py: gpt-image-2 via /v1/images/generations
is text-prompt-only -- however carefully you describe an existing character in
words, style drifts (e.g. it invented realistic fur and random signage text for
a character whose real design is a smooth matte toy-like cartoon render with no
text anywhere). Feeding the actual reference photo as image input and asking
the model to preserve that exact design fixes this. Use gen_images.py only for
shots with no established character in them (pure environment/B-roll).

Resumable: skips scenes whose image already exists, same as gen_images.py.

Character-consistency verification (optional, auto-detected): if a
pipeline_shared/character_bible/ directory exists alongside the project this
scenes.json belongs to, every generated scene whose "characters" field matches
a bible-tracked character gets checked by verify_character.py (discrete
claims + a dedicated face-closeup fidelity comparison) and corrective-retried
on failure, instead of the old "no exception thrown = success" behavior. See
character_bible.schema.md and verify_character.py's module docstring. Projects
with no character_bible/ directory behave exactly as before -- this is additive,
not a breaking change to the existing contract.
"""
import base64, glob, json, os, re, sys, time, urllib.request
import config

try:
    import character_bible as cb
    import verify_character as vc
except Exception:  # pragma: no cover - keep gen_images_ref.py usable standalone
    cb = None
    vc = None


def _find_bible_dir(start_dir):
    """Walk up from start_dir looking for pipeline_shared/character_bible/,
    same search pattern as config.py's _find_env_file. Returns None if the
    project this scenes.json belongs to has no character bible yet."""
    d = os.path.abspath(start_dir)
    for _ in range(8):
        candidate = os.path.join(d, "pipeline_shared", "character_bible")
        if os.path.isdir(candidate):
            return candidate
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return None

def generate(prompt, ref_paths, model="gemini-3-pro-image-preview", retries=3):
    content = [{"type": "text", "text": prompt}]
    for p in ref_paths:
        with open(p, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        ext = os.path.splitext(p)[1].lstrip(".").lower() or "jpeg"
        if ext == "jpg":
            ext = "jpeg"
        content.append({"type": "image_url", "image_url": {"url": f"data:image/{ext};base64,{b64}"}})

    body = {"model": model, "messages": [{"role": "user", "content": content}]}
    req_data = json.dumps(body).encode()

    last_exc = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(
                f"{config.NEWAPI_URL}/v1/chat/completions",
                data=req_data,
                headers={"Authorization": f"Bearer {config.NEWAPI_KEY}", "Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=180) as r:
                resp = json.loads(r.read().decode())
            msg_content = resp["choices"][0]["message"]["content"]
            m = re.search(r"data:image/\w+;base64,([A-Za-z0-9+/=]+)", msg_content)
            if not m:
                raise RuntimeError(f"no image in response: {msg_content[:300]}")
            return base64.b64decode(m.group(1))
        except Exception as e:
            last_exc = e
            print(f"  attempt {attempt + 1} failed: {e}, retrying" if attempt < retries else f"  attempt {attempt + 1} failed: {e}, giving up")
            time.sleep(5)
    raise last_exc

def _aggregate_verification_status(per_character):
    """Priority order so one bad character can't be masked by another good
    one landing later: error > flagged_for_review > verified > skipped."""
    statuses = {v.get("verification_status") for v in per_character.values()}
    for status in ("error", "flagged_for_review", "verified", "skipped"):
        if status in statuses:
            return status
    return "skipped"


_VERIFICATION_FIELDS = (
    "verification_status", "verification_attempts", "verification_model",
    "verification_action", "failed_claims", "uncertain_claims", "verification_history",
    "verification_tier1", "verification_error",
)


def _verify_scene_characters(sc, out_path, ref_images, bible_index, asset_variant_map, log=print):
    """Runs verify_character.verify_and_maybe_retry() once per bible-tracked
    character in this scene, sequentially (each pass sees whatever the prior
    pass's retries already wrote to out_path/image_prompt). Per-character
    results are kept under sc['verification_by_character'][character_id] so
    one character's outcome can't silently overwrite another's -- and the
    flat sc['verification_*'] fields (kept for jq-filter convenience, since
    that's the whole point of this system: filter scenes.json for
    flagged_for_review and read failed_claims[].reason without opening every
    image) are explicitly MERGED across all characters below, not just left
    as whatever the last character's call happened to write -- a scene where
    character A was flagged but character B (checked after) verified cleanly
    must still show A's failed_claims, not an empty list."""
    hits = cb.characters_in_scene(sc, bible_index, asset_variant_map)
    if not hits:
        return
    per_character = sc.setdefault("verification_by_character", {})
    for character_id, variant_id in hits:
        bible = bible_index["by_id"][character_id]
        checklist = cb.critical_checklist_for(bible, variant_id)
        vc.verify_and_maybe_retry(
            sc, out_path, checklist,
            generate_fn=lambda p: generate(p, ref_images),
            log=log,
        )
        per_character[character_id] = {"variant_id": variant_id,
                                        **{f: sc.get(f) for f in _VERIFICATION_FIELDS if f in sc}}
    sc["verification_status"] = _aggregate_verification_status(per_character)
    sc["failed_claims"] = [dict(item, character_id=cid) for cid, v in per_character.items()
                            for item in (v.get("failed_claims") or [])]
    sc["uncertain_claims"] = [dict(item, character_id=cid) for cid, v in per_character.items()
                               for item in (v.get("uncertain_claims") or [])]
    sc["verification_attempts"] = max((v.get("verification_attempts") or 0 for v in per_character.values()), default=0)
    errors = [v.get("verification_error") for v in per_character.values() if v.get("verification_status") == "error"]
    if errors:
        sc["verification_error"] = "; ".join(f"{cid}: {v.get('verification_error')}"
                                              for cid, v in per_character.items()
                                              if v.get("verification_status") == "error")


if __name__ == "__main__":
    scenes_path, image_dir = sys.argv[1], sys.argv[2]
    os.makedirs(image_dir, exist_ok=True)
    scenes = json.load(open(scenes_path))

    bible_index = asset_variant_map = None
    if cb is not None:
        bible_dir = _find_bible_dir(os.path.dirname(os.path.abspath(scenes_path)) or ".")
        if bible_dir:
            bible_index = cb.load_character_index(bible_dir)
            shared_dir = os.path.dirname(bible_dir)
            asset_variant_map = cb.load_asset_variant_map(
                os.path.join(shared_dir, "assets.json"), os.path.join(shared_dir, "assets2.json"))
            print(f"character bible: loaded {len(bible_index['by_id'])} character(s) from {bible_dir}")

    for sc in scenes:
        n = sc["scene"]
        out_path = f"{image_dir}/scene{n:02d}.png"
        if os.path.exists(out_path):
            print(f"scene{n}: already exists, skipping")
            sc["image_path"] = out_path
            continue
        ref_images = sc.get("ref_images", [])
        try:
            data = generate(sc["image_prompt"], ref_images)
            with open(out_path, "wb") as f:
                f.write(data)
            sc["image_path"] = out_path
            print(f"scene{n}: saved {out_path} (refs: {[os.path.basename(p) for p in ref_images]})")
            if bible_index is not None:
                _verify_scene_characters(sc, out_path, ref_images, bible_index, asset_variant_map)
        except Exception as e:
            print(f"scene{n}: FAILED, leaving for a re-run: {e}")
        json.dump(scenes, open(scenes_path, "w"), indent=2, ensure_ascii=False)
