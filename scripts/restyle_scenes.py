#!/usr/bin/env python3
"""Re-style an existing scenes.json: keep every scene's "scene" number, narration,
tts_duration, audio_path, word_timestamps exactly as-is, and rewrite ONLY image_prompt
and video_prompt to a new visual style (e.g. illustrated -> photorealistic) while
preserving the same characters/action/framing described in the original prompts.

Usage: restyle_scenes.py <in_scenes.json> <out_scenes.json> <style_notes_file>
"""
import json, sys, urllib.request
import config

SYSTEM_PROMPT = """You restyle prompts for an AI image/video generation pipeline. You will be
given a JSON array of scenes, each with "scene", "narration", "image_prompt", "video_prompt".
Rewrite ONLY image_prompt and video_prompt for every scene, applying the new style guide the
user provides. Preserve exactly: which characters appear, their described physical identity
(hair, build, outfit), the action/blocking, the setting, the camera framing/shot type, and the
time of day/lighting situation described in the original -- only the rendering style and level
of photographic realism should change. Do not alter narration or scene numbers. Respond with
ONLY a JSON array of {"scene": int, "image_prompt": str, "video_prompt": str}, no prose, no
markdown fences, one object per input scene in the same order."""

if __name__ == "__main__":
    in_path, out_path, style_path = sys.argv[1], sys.argv[2], sys.argv[3]
    style_notes = open(style_path, encoding="utf-8").read()
    scenes = json.load(open(in_path))

    thin = [{"scene": s["scene"], "narration": s["narration"],
             "image_prompt": s["image_prompt"], "video_prompt": s["video_prompt"]} for s in scenes]

    user_prompt = f"New style guide:\n{style_notes}\n\nScenes to restyle:\n{json.dumps(thin, ensure_ascii=False)}"

    req = urllib.request.Request(
        f"{config.NEWAPI_URL}/v1/chat/completions",
        data=json.dumps({
            "model": "claude-opus-4-8",
            "max_tokens": 32000,
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
        restyled = json.loads(content)
    except json.JSONDecodeError as e:
        finish_reason = resp["choices"][0].get("finish_reason", "?")
        raise SystemExit(
            f"model output was not valid JSON (finish_reason={finish_reason}, "
            f"{len(content)} chars received) -- likely truncated. Original error: {e}"
        )

    by_scene = {r["scene"]: r for r in restyled}
    missing = [s["scene"] for s in scenes if s["scene"] not in by_scene]
    if missing:
        raise SystemExit(f"model dropped scenes: {missing}")

    out = []
    for s in scenes:
        r = by_scene[s["scene"]]
        new_s = dict(s)
        new_s["image_prompt"] = r["image_prompt"]
        new_s["video_prompt"] = r["video_prompt"]
        new_s.pop("image_path", None)  # force regeneration under the new style
        out.append(new_s)

    json.dump(out, open(out_path, "w"), indent=2, ensure_ascii=False)
    print(f"wrote {len(out)} restyled scenes to {out_path}")
