"""Character-bible loader/resolver/renderer. Pure stdlib, same register as
config.py: module-level functions, no classes, loud RuntimeError on bad input.

A "character bible" is one JSON file per established character (see
references/character_bible.schema.md for the full schema + a worked example).
It exists to replace "whoever writes a scene's image_prompt hand-types the
character's must-keep/must-not-add rules, worded differently every time, and
sometimes forgets" with "a script always produces the same, complete
constraint text." See the plan this implements: an 11-video batch shipped
with the fruit-vs-hat rule present in some videos' prompts and completely
absent from others (video 5: 13 scenes, zero mentions) despite the bug
having already been caught and "fixed" earlier in the same batch -- the fix
was a note in a markdown file, not a mechanism, so it didn't propagate.

This module also resolves a SEPARATE, more important failure mode the bible
alone can't catch: continuous/similarity-type drift (e.g. a character's face
proportions/line-weight subtly disagreeing with its reference sheet even
when every discrete "does it have the right accessory" claim passes). That
is why every bible carries `canonical_face_closeup_images` alongside the
discrete rules -- verify_character.py runs a dedicated close-up comparison
against those images on top of (not instead of) the discrete claims below.
"""
from __future__ import annotations

import glob
import json
import os

RESERVED_VARIANT = "base"


def load_bible(path):
    """Load and lightly validate one character-bible JSON file."""
    with open(path, encoding="utf-8") as f:
        bible = json.load(f)
    for required in ("character_id", "display_names", "canonical_reference_images", "variants"):
        if required not in bible:
            raise RuntimeError(f"{path}: character bible missing required field {required!r}")
    if RESERVED_VARIANT not in bible["variants"]:
        raise RuntimeError(
            f"{path}: every character bible must define a {RESERVED_VARIANT!r} variant "
            f"(the no-costume default), found variants={sorted(bible['variants'])}"
        )
    bible.setdefault("canonical_face_closeup_images", [])
    bible.setdefault("critical_invariants", [])
    bible.setdefault("default_rules", [])
    return bible


def load_character_index(bible_dir):
    """Load every *.json in bible_dir. Returns
    {"by_id": {character_id: bible}, "aliases": [(alias_str, character_id, variant_id_or_None), ...]}
    with aliases sorted by len(alias_str) descending, so a longer/more-specific
    alias (e.g. 'mecha_lulu_v2') is tried before a shorter one it contains
    ('mecha_lulu') when matching free-text scene tokens."""
    by_id = {}
    aliases = []
    for path in sorted(glob.glob(os.path.join(bible_dir, "*.json"))):
        bible = load_bible(path)
        cid = bible["character_id"]
        by_id[cid] = bible
        names = bible.get("display_names", {})
        for key in ("zh", "en"):
            if names.get(key):
                aliases.append((names[key], cid, None))
        for aka in names.get("aka", []):
            aliases.append((aka, cid, None))
        for variant_id, variant in bible.get("variants", {}).items():
            # The variant's own id and every asset_id_aliases entry both resolve
            # straight to (character, variant) -- these are the strings actually
            # seen in scenes.json's characters[]/ref_images asset_id lookups.
            aliases.append((variant_id, cid, variant_id))
            for asset_alias in variant.get("asset_id_aliases", []):
                aliases.append((asset_alias, cid, variant_id))
    aliases.sort(key=lambda triple: len(triple[0]), reverse=True)
    return {"by_id": by_id, "aliases": aliases}


def match_scene_token(token, index):
    """token is one raw, messy entry from a scene's characters[] list (e.g.
    'battle_lulu (mounted, charging toward camera)' or '噜噜 Lulu (mecha_lulu_v2
    form, hero pose)'). Returns (character_id, variant_id_or_None) for the
    first (longest) alias that appears as a substring of token, or None if
    this token isn't a bible-tracked character at all (e.g. 'generic enemy
    troops (episode-only design, no reference image)')."""
    if not token:
        return None
    for alias, cid, variant_id in index["aliases"]:
        if alias and alias in token:
            return (cid, variant_id)
    return None


def load_asset_variant_map(*assets_json_paths):
    """Reverse-index one or more pipeline_shared/assets*.json files:
    {image_path: asset_id}. Missing files are skipped (not every project has
    an assets2.json)."""
    out = {}
    for path in assets_json_paths:
        if not path or not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as f:
            entries = json.load(f)
        for entry in entries:
            asset_id = entry.get("asset_id")
            image_path = entry.get("image_path")
            if asset_id and image_path:
                out[image_path] = asset_id
    return out


def resolve_variant_for_scene(bible, character_id, scene, asset_variant_map):
    """Priority: (1) scene['variant_overrides'][character_id] if the scene
    explicitly declares it (optional, forward-looking field) -> (2)
    cross-reference each of scene['ref_images'] against asset_variant_map,
    keep the first asset_id that is one of this character's variant ids ->
    (3) 'base'."""
    overrides = scene.get("variant_overrides") or {}
    declared = overrides.get(character_id)
    if declared and declared in bible["variants"]:
        return declared

    variants = bible["variants"]
    for ref_image in scene.get("ref_images", []) or []:
        asset_id = asset_variant_map.get(ref_image)
        if asset_id and asset_id in variants:
            return asset_id
        # ref_images sometimes point straight at a variant's own reference_image
        # path rather than going through assets.json at all.
        for variant_id, variant in variants.items():
            if variant.get("reference_image") == ref_image:
                return variant_id
    return RESERVED_VARIANT


def resolve_rules(bible, variant_id):
    """Merge critical_invariants + default_rules with variant_id's
    rule_overrides applied (waived rules dropped, replaced rules get their
    new text) + that variant's additional_negative_constraints. Returns a
    list of {"id", "severity", "text", "kind", "tier2_claim"} dicts, kind in
    {"invariant","rule","additional"}.

    tier2_claim (default True) marks whether this rule should become a
    discrete pass/fail/uncertain Tier-2 claim in critical_checklist_for().
    Set False for a rule whose real check is a SEPARATE, purpose-built
    mechanism -- concretely, every bible's "face_fidelity" invariant: its
    text is genuinely useful as generation-time prompt guidance, but judging
    "does the mouth-line weight match" via a generic discrete claim inherits
    that mechanism's "uncertain on a critical claim forces a retry" rule,
    which cannot succeed for the (extremely common) shots where the face
    isn't clearly on-camera -- verify_character.py's dedicated face-closeup
    comparison already handles exactly this claim correctly (an
    unjudgeable/not-visible face is a pass, not a failure). Confirmed on
    real production data: without this flag, wide/distant/back-facing shots
    were repeatedly flagged and retried for an unfixable "can't tell" reason
    via this claim, on top of (separately) the dedicated check."""
    variant = bible["variants"].get(variant_id)
    if variant is None:
        raise RuntimeError(
            f"{bible['character_id']}: unknown variant {variant_id!r}, "
            f"known variants={sorted(bible['variants'])}"
        )
    overrides = variant.get("rule_overrides", {})

    resolved = []
    for inv in bible.get("critical_invariants", []):
        resolved.append({"id": inv["id"], "severity": "critical", "text": inv["text"], "kind": "invariant",
                          "tier2_claim": inv.get("tier2_claim", True)})

    for rule in bible.get("default_rules", []):
        rid = rule["id"]
        override = overrides.get(rid)
        if override is None:
            resolved.append({"id": rid, "severity": rule.get("severity", "high"),
                              "text": rule["text"], "kind": "rule", "tier2_claim": rule.get("tier2_claim", True)})
        elif override.get("mode") == "waive":
            continue
        elif override.get("mode") == "replace":
            resolved.append({"id": rid, "severity": rule.get("severity", "high"),
                              "text": override["text"], "kind": "rule", "tier2_claim": rule.get("tier2_claim", True)})
        else:
            raise RuntimeError(f"{bible['character_id']}/{variant_id}: rule_overrides[{rid!r}] "
                                f"has unknown mode {override.get('mode')!r}")

    for i, text in enumerate(variant.get("additional_negative_constraints", [])):
        resolved.append({"id": f"{variant_id}_additional_{i}", "severity": "high",
                          "text": text, "kind": "additional", "tier2_claim": True})
    return resolved


def render_constraint_block(bible, variant_id=RESERVED_VARIANT, *, include_positive=True):
    """The single most load-bearing function in this module: returns one
    prose string ready to be appended (with a leading blank line) to any
    scene's existing image_prompt. Pure string in, pure string out, no side
    effects, no network calls -- callable from a plain script or an agent."""
    variant = bible["variants"][variant_id]
    lines = []
    if include_positive:
        base_desc = bible.get("base_positive_description", "")
        variant_desc = variant.get("positive_description", "")
        positive = " ".join(p for p in (base_desc, variant_desc) if p)
        if positive:
            lines.append(positive)
    for rule in resolve_rules(bible, variant_id):
        prefix = "CRITICAL: " if rule["severity"] == "critical" else ""
        lines.append(f"{prefix}{rule['text']}")
    return " ".join(lines)


def critical_checklist_for(bible, variant_id=RESERVED_VARIANT):
    """For verify_character.py: turns resolved rules into a list of
    yes/no-checkable claims: [{"id","text","tier"}], tier in
    {"critical","important"}. Also returns this character's
    canonical_reference_images and canonical_face_closeup_images so the
    verifier never has to re-derive them from the bible structure itself."""
    claims = []
    for rule in resolve_rules(bible, variant_id):
        if not rule.get("tier2_claim", True):
            continue
        tier = "critical" if rule["severity"] == "critical" else "important"
        claims.append({"id": rule["id"], "text": rule["text"], "tier": tier})
    return {
        "character_id": bible["character_id"],
        "variant_id": variant_id,
        "claims": claims,
        "reference_images": bible.get("canonical_reference_images", []) + (
            [bible["variants"][variant_id]["reference_image"]]
            if bible["variants"][variant_id].get("reference_image") else []
        ),
        "face_closeup_images": bible.get("canonical_face_closeup_images", []),
    }


def characters_in_scene(scene, index, asset_variant_map):
    """Convenience wrapper: match every token in scene['characters'] against
    the bible index, resolve each hit's variant, dedupe by character_id
    (first match wins). Returns [(character_id, variant_id), ...]."""
    seen = {}
    for token in scene.get("characters", []) or []:
        match = match_scene_token(token, index)
        if match is None:
            continue
        cid, variant_from_alias = match
        if cid in seen:
            continue
        bible = index["by_id"][cid]
        variant_id = variant_from_alias or resolve_variant_for_scene(bible, cid, scene, asset_variant_map)
        seen[cid] = variant_id
    return list(seen.items())


def _cli_render(argv):
    bible_path = argv[0]
    variant_id = argv[1] if len(argv) > 1 else RESERVED_VARIANT
    bible = load_bible(bible_path)
    print(render_constraint_block(bible, variant_id))


def _cli_list(argv):
    bible_dir = argv[0]
    index = load_character_index(bible_dir)
    for cid, bible in index["by_id"].items():
        variants = ", ".join(sorted(bible["variants"]))
        print(f"{cid}: {variants}")


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print("usage: character_bible.py render <bible.json> [variant_id=base]", file=sys.stderr)
        print("       character_bible.py list <bible_dir>", file=sys.stderr)
        raise SystemExit(2)
    cmd, rest = sys.argv[1], sys.argv[2:]
    if cmd == "render":
        _cli_render(rest)
    elif cmd == "list":
        _cli_list(rest)
    else:
        print(f"unknown command {cmd!r}", file=sys.stderr)
        raise SystemExit(2)
