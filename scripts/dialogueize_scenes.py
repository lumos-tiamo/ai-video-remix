#!/usr/bin/env python3
"""Rewrite a scenes.json's narrator-style "narration" into actual English
on-screen dialogue for a live-cast drama: each scene keeps its existing
"scene" number, video_prompt, and image_prompt (so all already-generated
Stage 2/3 assets stay valid), but "narration" becomes a short spoken line
attributed to a "speaker" and cast to a "voice" (edge-tts voice name) from
the provided cast list. Scenes with no natural speaker (pure B-roll/
establishing shots) get speaker="NARRATOR" sparingly.

Usage: dialogueize_scenes.py <in_scenes.json> <out_scenes.json> <cast_notes_file>
"""
import json, sys, urllib.request
import config

SYSTEM_PROMPT = """You are converting a narrator-voiced scene-by-scene script for an AI-generated
video into an actual DIALOGUE script for the same shots, in English. You'll receive a JSON array
of scenes; each has "scene" (index), "narration" (the OLD Chinese narrator-style line, for
context on what happens in this beat only -- do not translate it), "video_prompt" (the visual
action in this shot), and "image_prompt" (shot composition, which names which character(s)
appear). You'll also receive a cast list mapping character names to edge-tts voice names.

For each scene, decide:
- If the shot naturally shows one of the cast members speaking, reacting with an exclamation,
  or delivering a line (most scenes should land here) -- write ONE short, natural English line
  of dialogue that character would actually say in that moment, consistent with the ongoing
  story across all scenes. Typically 4-16 words; only longer if the moment calls for it. Set
  "speaker" to that character's exact name from the cast list and "voice" to their assigned
  edge-tts voice name.
- Only if the shot is truly a silent visual beat with nobody speaking (a pure establishing shot,
  a silent action beat, a montage cut with no dialogue) -- you may leave "narration" as a very
  brief bridging line OR set it to an empty string "" for a fully silent shot with no audio line
  at all. Use empty string liberally for pure B-roll; do not force dialogue into every scene.
  When you do write a bridging narration line, set "speaker":"NARRATOR" and "voice":"en-US-AndrewNeural".

Keep the exact same number of scenes, in the exact same order, telling the exact same story
beats as the original narration sequence (you're recasting HOW it's said, not changing WHAT
happens). Never change "scene", "video_prompt", or "image_prompt".

Respond with ONLY a JSON array of {"scene": int, "speaker": str, "voice": str, "narration": str},
no prose, no markdown fences, one object per input scene in the same order."""

if __name__ == "__main__":
    in_path, out_path, cast_path = sys.argv[1], sys.argv[2], sys.argv[3]
    cast_notes = open(cast_path, encoding="utf-8").read()
    scenes = json.load(open(in_path))

    thin = [{"scene": s["scene"], "narration": s["narration"],
             "video_prompt": s["video_prompt"], "image_prompt": s["image_prompt"]} for s in scenes]

    user_prompt = f"Cast list:\n{cast_notes}\n\nScenes to convert:\n{json.dumps(thin, ensure_ascii=False)}"

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
        dialogue = json.loads(content)
    except json.JSONDecodeError as e:
        finish_reason = resp["choices"][0].get("finish_reason", "?")
        raise SystemExit(
            f"model output was not valid JSON (finish_reason={finish_reason}, "
            f"{len(content)} chars received) -- likely truncated. Original error: {e}"
        )

    by_scene = {d["scene"]: d for d in dialogue}
    missing = [s["scene"] for s in scenes if s["scene"] not in by_scene]
    if missing:
        raise SystemExit(f"model dropped scenes: {missing}")

    out = []
    for s in scenes:
        d = by_scene[s["scene"]]
        new_s = dict(s)
        new_s["narration_zh"] = s["narration"]
        new_s["narration"] = d["narration"]
        new_s["speaker"] = d["speaker"]
        new_s["voice"] = d["voice"]
        for k in ("tts_duration", "audio_path", "word_timestamps", "rendered_duration", "video_path"):
            new_s.pop(k, None)
        out.append(new_s)

    json.dump(out, open(out_path, "w"), indent=2, ensure_ascii=False)
    silent = sum(1 for o in out if not o["narration"])
    print(f"wrote {len(out)} scenes to {out_path} ({silent} silent/no-dialogue scenes)")
