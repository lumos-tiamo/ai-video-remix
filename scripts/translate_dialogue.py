#!/usr/bin/env python3
"""Batch-translate every voiced scene's English "narration" dialogue line into
natural Chinese, writing the result to "narration_zh_translated" (does not
touch the stale "narration_zh" field, which is the OLD pre-dialogue narrator
text, not a translation of the new line). Silent scenes (empty narration)
are skipped.

Usage: translate_dialogue.py <scenes_dialogue.json>
"""
import json, sys, urllib.request
import config

SYSTEM_PROMPT = """Translate each English line of dialogue into natural, colloquial Chinese
suitable for a bilingual subtitle under the English line. Keep it short and speakable, matching
the tone (casual teen dialogue stays casual). You'll get a JSON array of {"scene": int, "en":
str}. Respond with ONLY a JSON array of {"scene": int, "zh": str}, same order, no prose, no
markdown fences."""

if __name__ == "__main__":
    path = sys.argv[1]
    scenes = json.load(open(path))
    voiced = [{"scene": s["scene"], "en": s["narration"]} for s in scenes if s.get("narration")]

    req = urllib.request.Request(
        f"{config.NEWAPI_URL}/v1/chat/completions",
        data=json.dumps({
            "model": "claude-opus-4-8",
            "max_tokens": 16000,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(voiced, ensure_ascii=False)},
            ],
        }).encode(),
        headers={"Authorization": f"Bearer {config.NEWAPI_KEY}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=300) as r:
        resp = json.loads(r.read().decode())
    content = resp["choices"][0]["message"]["content"].strip()
    if content.startswith("```"):
        content = content.split("\n", 1)[1].rsplit("```", 1)[0]
    translations = json.loads(content)
    by_scene = {t["scene"]: t["zh"] for t in translations}

    for s in scenes:
        if s["scene"] in by_scene:
            s["narration_zh_translated"] = by_scene[s["scene"]]

    json.dump(scenes, open(path, "w"), indent=2, ensure_ascii=False)
    print(f"translated {len(by_scene)} voiced scenes")
