#!/usr/bin/env python3
"""Scan (or fix) an existing scenes.json for missing character-bible constraint
coverage. This is the mechanical version of the manual audit that first found
the fruit-vs-hat gap: video 5's 13 scenes had zero "CRITICAL"/"no hat" mentions
despite the bug having already been caught and fixed in videos 3/4/6 earlier in
the same batch -- the fix note in creative_decisions.md was scoped to "future
videos 10-13" with nothing to detect or backfill the gap in 5/7/9. This script
is that detection/backfill mechanism.

Usage:
    lint_scenes_against_bible.py <scenes.json> <bible_dir> [assets_json ...] report
    lint_scenes_against_bible.py <scenes.json> <bible_dir> [assets_json ...] fix
    lint_scenes_against_bible.py <scenes.json> <bible_dir> [assets_json ...] accept

report: prints per-scene coverage, non-zero exit if anything is uncovered.
fix:    appends render_constraint_block(...) to image_prompt for every
        bible-tracked character missing from scene["bible_check"], records the
        variant in scene["bible_check"]. Does NOT touch already-covered scenes.
accept: records scene["bible_check"] for detected characters WITHOUT touching
        image_prompt -- for scenes a human has confirmed already say the right
        thing by hand (e.g. videos 3/6's partial hand-written coverage).

Idempotency is tracked via the scene["bible_check"] sibling field, deliberately
NOT an embedded marker string inside image_prompt -- SKILL.md's own documented
lesson (a generic "documents on a table" prompt got a hallucinated fake trade
agreement rendered onto it) is exactly the risk of leaving placeholder-shaped
text in a prompt that gets fed to an image model.
"""
import json
import sys

import character_bible as cb


def _scan(scenes, index, asset_variant_map):
    """Returns [(scene, [(character_id, variant_id, covered_bool), ...]), ...]."""
    rows = []
    for scene in scenes:
        hits = cb.characters_in_scene(scene, index, asset_variant_map)
        bible_check = scene.get("bible_check", {})
        per_char = [(cid, variant_id, bible_check.get(cid) == variant_id) for cid, variant_id in hits]
        rows.append((scene, per_char))
    return rows


def cmd_report(scenes_path, bible_dir, assets_paths):
    scenes = json.load(open(scenes_path, encoding="utf-8"))
    index = cb.load_character_index(bible_dir)
    asset_variant_map = cb.load_asset_variant_map(*assets_paths)
    rows = _scan(scenes, index, asset_variant_map)

    total_pairs = 0
    uncovered_pairs = 0
    for scene, per_char in rows:
        n = scene.get("scene")
        if not per_char:
            print(f"scene{n:02d}: (no bible-tracked characters detected)")
            continue
        parts = []
        for cid, variant_id, covered in per_char:
            total_pairs += 1
            if not covered:
                uncovered_pairs += 1
            mark = "OK" if covered else "MISSING"
            parts.append(f"{cid}/{variant_id}:{mark}")
        print(f"scene{n:02d}: " + ", ".join(parts))

    print(f"\n{len(scenes)} scenes, {total_pairs} character-appearances, "
          f"{uncovered_pairs} missing bible coverage")
    return 1 if uncovered_pairs else 0


def cmd_fix(scenes_path, bible_dir, assets_paths):
    scenes = json.load(open(scenes_path, encoding="utf-8"))
    index = cb.load_character_index(bible_dir)
    asset_variant_map = cb.load_asset_variant_map(*assets_paths)
    rows = _scan(scenes, index, asset_variant_map)

    fixed = 0
    for scene, per_char in rows:
        bible_check = scene.setdefault("bible_check", {})
        for cid, variant_id, covered in per_char:
            if covered:
                continue
            bible = index["by_id"][cid]
            block = cb.render_constraint_block(bible, variant_id, include_positive=False)
            scene["image_prompt"] = scene["image_prompt"].rstrip() + "\n\n" + block
            bible_check[cid] = variant_id
            fixed += 1
            print(f"scene{scene.get('scene')}: injected {cid}/{variant_id} constraints")

    json.dump(scenes, open(scenes_path, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    print(f"\nfixed {fixed} character-appearances, wrote {scenes_path}")
    return 0


def cmd_accept(scenes_path, bible_dir, assets_paths):
    scenes = json.load(open(scenes_path, encoding="utf-8"))
    index = cb.load_character_index(bible_dir)
    asset_variant_map = cb.load_asset_variant_map(*assets_paths)
    rows = _scan(scenes, index, asset_variant_map)

    accepted = 0
    for scene, per_char in rows:
        bible_check = scene.setdefault("bible_check", {})
        for cid, variant_id, covered in per_char:
            if not covered:
                bible_check[cid] = variant_id
                accepted += 1

    json.dump(scenes, open(scenes_path, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    print(f"accepted {accepted} character-appearances without touching image_prompt, wrote {scenes_path}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print(__doc__, file=sys.stderr)
        raise SystemExit(2)
    scenes_path = sys.argv[1]
    bible_dir = sys.argv[2]
    mode = sys.argv[-1]
    if mode not in ("report", "fix", "accept"):
        print(f"unknown mode {mode!r}, expected report|fix|accept", file=sys.stderr)
        raise SystemExit(2)
    assets_paths = sys.argv[3:-1]

    fn = {"report": cmd_report, "fix": cmd_fix, "accept": cmd_accept}[mode]
    raise SystemExit(fn(scenes_path, bible_dir, assets_paths))
