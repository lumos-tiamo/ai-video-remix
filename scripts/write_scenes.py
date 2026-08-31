#!/usr/bin/env python3
"""Stage 1, both modes: turn a transcript/brief into scenes.json. This is a
plain chat-completion call to a strong text model -- Mode A (reverse-engineer)
just means the "brief" you pass in is a transcript of an existing video
instead of original notes; there is no separate code path.

Usage: write_scenes.py <output_scenes.json> <target_seconds> <brief_or_transcript_file> [style_notes]

Prefer reading an existing .txt transcript next to a source video over
re-transcribing it yourself -- see SKILL.md.
"""
import json, sys, urllib.request
import config

SYSTEM_PROMPT = """You write tight scripts for short vertical AI-generated explainer videos.
Given source material and a target duration, produce a JSON array of scenes. Each scene has:
- "scene": integer, 1-indexed
- "narration": the spoken line for this beat, in the material's original language, concise
  enough that the WHOLE narration across all scenes reads naturally in roughly the target
  duration at a measured speaking pace of about 3.3 characters/second for Chinese (adjust
  proportionally for other languages) -- err SHORTER, TTS duration will be measured and used
  as ground truth downstream, not estimated from character count.
- "video_prompt": an English prompt for a text/image-to-video generation model describing
  the visual action for this beat -- concrete, single continuous shot, one clear subject and
  action, no more than ~2 sentences.
- "image_prompt": an English prompt for a still-image generation model describing this
  scene's first frame in the same visual style throughout (name the art style explicitly and
  consistently across every scene) -- concrete enough to reliably reproduce.

Respond with ONLY the JSON array, no prose, no markdown fences."""

if __name__ == "__main__":
    out_path, target_seconds, material_path = sys.argv[1], sys.argv[2], sys.argv[3]
    style_notes = sys.argv[4] if len(sys.argv) > 4 else ""
    material = open(material_path, encoding="utf-8").read()

    user_prompt = (
        f"Target duration: ~{target_seconds} seconds.\n"
        + (f"Style notes: {style_notes}\n" if style_notes else "")
        + f"Source material:\n{material}"
    )

    req = urllib.request.Request(
        f"{config.NEWAPI_URL}/v1/chat/completions",
        data=json.dumps({
            "model": "claude-opus-4-8",
            "max_tokens": 24000,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
        }).encode(),
        headers={"Authorization": f"Bearer {config.NEWAPI_KEY}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=600) as r:
        resp = json.loads(r.read().decode())
    content = resp["choices"][0]["message"]["content"].strip()
    if content.startswith("```"):
        content = content.split("\n", 1)[1].rsplit("```", 1)[0]
    try:
        scenes = json.loads(content)
    except json.JSONDecodeError as e:
        finish_reason = resp["choices"][0].get("finish_reason", "?")
        raise SystemExit(
            f"model output was not valid JSON (finish_reason={finish_reason}, "
            f"{len(content)} chars received) -- likely truncated by a token limit. "
            f"Original error: {e}"
        )
    json.dump(scenes, open(out_path, "w"), indent=2, ensure_ascii=False)
    print(f"wrote {len(scenes)} scenes to {out_path}")
