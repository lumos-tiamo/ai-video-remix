#!/usr/bin/env python3
"""Compute exact Palmier Pro placement (startFrame/endFrame/speed) for every
scene from its target duration (TTS-measured) and actual rendered duration.
Palmier's MCP tools can only be called by the agent directly (not from a
standalone script), so this just does the math -- feed the printed plan into
import_media/add_clips/set_clip_properties calls yourself. See SKILL.md
Stage 4 for the reasoning.

Also imported by build_karaoke_transcript.py (stage 6) to reuse the same
startFrame math for projecting scene-relative word timestamps onto the
whole-video timeline -- don't duplicate this loop elsewhere.

Usage: compute_placement.py <scenes.json> <timeline_fps>
"""
import json, sys

def compute_placement(scenes, fps):
    cursor_frame = 0
    plan = []
    for sc in scenes:
        n = sc["scene"]
        target_seconds = sc["tts_duration"]
        target_frames = round(target_seconds * fps)
        start_frame = cursor_frame
        end_frame = start_frame + target_frames
        rendered = sc.get("rendered_duration")
        speed = None
        if rendered:
            natural_frames_at_timeline_fps = rendered * fps
            speed = round(natural_frames_at_timeline_fps / target_frames, 4)
        plan.append({
            "scene": n,
            "video_path": sc.get("video_path"),
            "startFrame": start_frame,
            "endFrame": end_frame,
            "durationFrames": target_frames,
            "speed": speed,
        })
        cursor_frame = end_frame
    return plan

if __name__ == "__main__":
    scenes_path, fps = sys.argv[1], float(sys.argv[2])
    scenes = json.load(open(scenes_path))
    plan = compute_placement(scenes, fps)
    print(json.dumps(plan, indent=2))
    total_frames = plan[-1]["endFrame"] if plan else 0
    print(f"# total timeline: {total_frames} frames = {total_frames / fps:.2f}s", file=sys.stderr)
