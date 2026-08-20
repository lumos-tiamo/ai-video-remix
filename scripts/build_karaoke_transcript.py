#!/usr/bin/env python3
"""Project every scene's word_timestamps (scene-relative seconds) onto the
whole assembled video's absolute timeline, grouped into the same
punctuation-bounded phrases gen_srt.py already uses for the plain-caption
track -- so stage 6's karaoke groups read the same as the SRT you already
reviewed, just with real per-word timing added inside each group.

Why a simple additive offset is correct (no per-scene rescaling): Palmier
only speed-adjusts the AI-generated VIDEO to fill each scene's target frame
window -- the narration AUDIO track always plays at 1x, unmodified, so it
occupies exactly [startFrame/fps, endFrame/fps) with no stretching. A word
timestamp measured against that scene's own TTS clip therefore lands on the
whole-video timeline with nothing more than startFrame/fps added to it.

Usage: build_karaoke_transcript.py <scenes.json> <timeline_fps> <out_dir>
Outputs <out_dir>/caption_groups.json and <out_dir>/word_timestamps.json.
"""
import json, os, sys
import compute_placement
from gen_srt import split_phrases, SPLIT_RE

def content_len(text):
    """Character count with punctuation stripped -- word_timestamps entries
    never include punctuation as their own word, so phrase-length targets
    must be computed the same way or the boundary drifts by one word per
    punctuation mark."""
    return len(SPLIT_RE.sub("", text))

if __name__ == "__main__":
    scenes_path, fps, out_dir = sys.argv[1], float(sys.argv[2]), sys.argv[3]
    os.makedirs(out_dir, exist_ok=True)
    scenes = json.load(open(scenes_path))

    missing = [str(sc["scene"]) for sc in scenes if not sc.get("word_timestamps")]
    if missing:
        sys.exit(
            f"Scenes missing word_timestamps: {', '.join(missing)}\n"
            f"Run gen_word_timestamps_fallback.py first for scenes generated "
            f"with the newapi TTS backend."
        )

    plan_by_scene = {p["scene"]: p for p in compute_placement.compute_placement(scenes, fps)}

    all_groups = []
    for sc in scenes:
        n = sc["scene"]
        offset = plan_by_scene[n]["startFrame"] / fps
        words = sc["word_timestamps"]
        phrases = split_phrases(sc["narration"]) or [sc["narration"]]

        word_i = 0
        chars_consumed = 0
        cumulative_target = 0
        for phrase in phrases:
            cumulative_target += content_len(phrase)
            group_words = []
            while word_i < len(words) and chars_consumed < cumulative_target:
                w = words[word_i]
                group_words.append({
                    "text": w["text"],
                    "start": round(w["start"] + offset, 3),
                    "end": round(w["end"] + offset, 3),
                })
                chars_consumed += len(w["text"])
                word_i += 1
            if not group_words:
                continue
            all_groups.append({
                "words": group_words,
                "start": group_words[0]["start"],
                "end": group_words[-1]["end"],
            })

    all_groups.sort(key=lambda g: g["start"])
    all_words = [w for g in all_groups for w in g["words"]]
    json.dump(all_groups, open(f"{out_dir}/caption_groups.json", "w"), indent=2, ensure_ascii=False)
    json.dump(all_words, open(f"{out_dir}/word_timestamps.json", "w"), indent=2, ensure_ascii=False)
    print(f"wrote {len(all_groups)} caption groups, {len(all_words)} words to {out_dir}/")
