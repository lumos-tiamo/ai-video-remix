#!/usr/bin/env python3
"""Prepend a shared style-lock string to every scene's image_prompt in a
scenes.json, in code -- instead of asking the writer model to retype the
same ~400-char preamble in every single scene. That retyping was blowing up
output length on longer/denser transcripts and truncating the JSON response
(see write_scenes.py's max_tokens). Idempotent: skips scenes whose
image_prompt already starts with the prefix, so it's safe to re-run.

Usage: prepend_style_prefix.py <scenes.json> <prefix_text_path>
"""
import json, sys

if __name__ == "__main__":
    scenes_path, prefix_path = sys.argv[1], sys.argv[2]
    prefix = open(prefix_path, encoding="utf-8").read().strip()
    scenes = json.load(open(scenes_path))
    changed = 0
    for sc in scenes:
        ip = sc.get("image_prompt", "").strip()
        if not ip.startswith(prefix):
            sc["image_prompt"] = f"{prefix} {ip}"
            changed += 1
    json.dump(scenes, open(scenes_path, "w"), indent=2, ensure_ascii=False)
    print(f"prepended style prefix to {changed}/{len(scenes)} scenes")
