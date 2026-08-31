# Character bible schema

One JSON file per established/fixed-IP character, loaded by `scripts/character_bible.py`.
Exists to stop "whoever writes a scene's `image_prompt` hand-types the character's
must-keep/must-not-add rules, worded differently every time, and sometimes forgets" —
see `噜噜二创/pipeline_shared/character_bible/lulu.json` for a complete, real, in-use
example (6 costume variants, migrated from an actual production batch).

## Where files live

- **This schema doc + the loader (`character_bible.py`) live in the skill** (`ai-video-remix/scripts/`,
  `ai-video-remix/references/`) — reusable by any project that uses this skill.
- **Actual bible data is per-project**: `<project>/pipeline_shared/character_bible/<character_id>.json`,
  one file per character, plus a `face_closeups/` subfolder for the cropped face-reference
  images every bible points at.

## Top-level fields

```
character_id            str   canonical slug, matches the filename stem
schema_version           int
display_names             {zh, en, aka: [str, ...]}
                          aka MUST include every messy alias actually seen in real
                          scenes.json "characters" fields for this character (full names,
                          nicknames, "General X", costume-prefixed forms, etc.) — the
                          matcher does substring matching against these, not exact string
                          equality, because scene text is always messier than you'd like.
canonical_reference_images   [str]   the character's real photo(s) — usually the same
                          file(s) already used as ref_images in generation prompts.
canonical_face_closeup_images  [str]   1-2 CLEAN face-only crops (no labels/UI chrome),
                          ideally cropped from an existing expression-grid reference
                          sheet if the character has one. This is NOT optional decoration
                          — it exists specifically to catch continuous/similarity-type
                          drift (facial proportions, mouth-line weight, shading) that a
                          discrete pass/fail checklist cannot detect at all. If a
                          character's face is small/absent from its full-body reference
                          photo, generation and verification both silently lose their best
                          tool against this failure mode.
base_positive_description   str   prose used for the "base" (no-costume) variant
critical_invariants      [{id, text}]   ALWAYS true, no variant may override these.
                          Reserve this for facts that are true regardless of costume:
                          species, render style, base palette, face fidelity. If a
                          costume genuinely needs to break one of these (see grass_cow's
                          cow_car variant needing an exception to "is a literal animal"),
                          that rule belongs in default_rules instead, NOT here — this
                          module does not support overriding critical_invariants, on
                          purpose, so "critical" keeps meaning "actually always true."
default_rules             [{id, type: "negative"|"positive",
                            severity: "critical"|"high", text}]
                          Conditional-by-default rules. Applied to every variant UNLESS
                          that variant declares a rule_overrides entry for this id.
variants                  {variant_id: {
                              label, asset_id_aliases: [str],
                              reference_image: str,
                              positive_description: str,
                              rule_overrides: {rule_id: {mode: "waive"|"replace", text?}},
                              additional_negative_constraints: [str],
                              notes: str
                          }, ...}
                          "base" is a RESERVED variant_id every file must define (the
                          no-costume default used when a scene's ref_images don't match
                          any known costume asset_id).
```

## `critical_invariants` vs `default_rules` — how to decide

Ask: **is there any costume/variant, existing or plausible-future, where this stops being
true?** If genuinely never (species, base render style) → `critical_invariants`. If a
variant might legitimately need an exception (e.g. a mecha helmet hiding the signature
head accessory, or a vehicle-transformation variant not having literal animal anatomy)
→ `default_rules`, so a variant can `waive` or `replace` it via `rule_overrides`.

Getting this wrong in the direction of "everything is critical_invariants" silently
breaks every future variant that needs a legitimate exception — the loader raises
`RuntimeError` if a variant's `rule_overrides` references anything other than a
`default_rules` id, specifically to catch this mistake early rather than let the
override be silently ignored.

## `character_bible.py` functions

See the module's own docstrings for exact signatures — `load_bible`, `load_character_index`,
`match_scene_token`, `load_asset_variant_map`, `resolve_variant_for_scene`, `resolve_rules`,
`render_constraint_block` (the single function everything else exists to support — turns a
bible + variant_id into ready-to-append prompt text), `critical_checklist_for` (turns the
same into a claims list + reference/face-closeup image paths for `verify_character.py`),
and `characters_in_scene` (resolves every bible-tracked character mentioned in a
`scenes.json` scene's `characters` field, with its costume variant, in one call).

## Adding a new character to a new project

1. Pick 1-2 canonical reference photos (or reuse an existing character-design-sheet image).
2. Crop 1-2 clean face-only close-ups from it (no text/labels) — see
   `噜噜二创/pipeline_shared/character_bible/face_closeups/` for examples of the crop tightness
   to aim for.
3. Write `critical_invariants` (species/render-style/palette/face-fidelity — face-fidelity
   is boilerplate, copy it from any existing bible almost verbatim) and any `default_rules`
   for signature accessories that must be visible by default.
4. If the character has costume variants already generated via `gen_images_ref.py`
   (check `pipeline_shared/assets*.json`), migrate each `asset_id` entry into a `variants`
   block — this is a restructure of existing content, not new authoring.
5. Run `python3 character_bible.py render <your_bible.json> <variant_id>` and read the
   output — confirm it doesn't duplicate wording (e.g. don't put "CRITICAL:" inside a rule's
   own `text` — the renderer already prefixes critical-severity rules with it).
