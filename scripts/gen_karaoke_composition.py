#!/usr/bin/env python3
"""Scaffold (if needed) and write a HyperFrames composition that layers a
karaoke caption overlay on top of the finished PalmierPro export. Base video
layer is the export itself (muted) + a parallel <audio> using the same file
for its already-mixed audio -- the documented "video + separate audio
track" convention, not a second ffmpeg extraction step.

Karaoke mechanics follow the hard-kill / single-group / safe-zone rules
validated in the Phase-0 spike (see SKILL.md stage 6): every caption group's
own data-start/data-duration EXACTLY covers its GSAP-visible window (no
pre-roll lead) -- HyperFrames' own lint rejects overlapping clips on the
same track, and a caption mounted before its own data-start doesn't exist
in the DOM yet for GSAP to animate.

Usage: gen_karaoke_composition.py <caption_groups.json> <export_mp4_path> <project_dir>
"""
import json, os, subprocess, sys

GROUP_END_BUFFER = 0.25

def ffprobe_video(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=width,height",
         "-show_entries", "format=duration", "-of", "json", path],
        capture_output=True, text=True, check=True,
    ).stdout
    info = json.loads(out)
    stream = next(s for s in info["streams"] if "width" in s)
    return int(stream["width"]), int(stream["height"]), float(info["format"]["duration"])

def build_groups_html_and_js(groups, duration):
    divs = []
    css_ids = []
    js_groups = []
    for gi, g in enumerate(groups):
        gid = f"cg-{gi}"
        next_g = groups[gi + 1] if gi + 1 < len(groups) else None
        effective_end = duration if next_g is None else min(next_g["start"], g["end"] + GROUP_END_BUFFER)
        clip_start = g["start"]
        clip_duration = round(effective_end - clip_start, 3)

        word_spans = []
        js_words = []
        for wi, w in enumerate(g["words"]):
            wid = f"cw-{gi}-{wi}"
            word_spans.append(f'<span class="cw" id="{wid}">{w["text"]}</span>')
            js_words.append({"id": wid, "start": w["start"], "end": w["end"]})

        divs.append(
            f'      <div id="{gid}" class="clip cap-group" data-start="{clip_start}" '
            f'data-duration="{clip_duration}" data-track-index="1">\n'
            f'        {"".join(word_spans)}\n      </div>'
        )
        css_ids.append(gid)
        js_groups.append({
            "id": gid, "start": g["start"], "end": g["end"],
            "effectiveEnd": round(effective_end, 3), "words": js_words,
        })
    return "\n".join(divs), js_groups

TEMPLATE = """<!doctype html>
<html lang="zh" data-resolution="portrait">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width={width}, height={height}" />
    <script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script>
    <style>
      * {{ margin: 0; padding: 0; box-sizing: border-box; }}
      html, body {{ margin: 0; width: {width}px; height: {height}px; overflow: hidden; background: #000; }}
      @font-face {{ font-family: "Noto Sans SC"; src: local("PingFang SC"); }}
      .cap-group {{
        position: absolute; left: 0; right: 0; top: {caption_top}px;
        text-align: center; font-family: "Noto Sans SC", "Inter", sans-serif;
        font-weight: 700; font-size: 56px; opacity: 0; visibility: hidden;
      }}
      .cw {{
        color: rgb(200, 200, 200); margin: 0 8px;
        text-shadow: -3px -3px 0 #000, 3px -3px 0 #000, -3px 3px 0 #000,
          3px 3px 0 #000, 0 4px 14px rgba(0,0,0,.7);
      }}
    </style>
  </head>
  <body>
    <div id="root" data-composition-id="main" data-start="0" data-duration="{duration}"
         data-width="{width}" data-height="{height}">
      <video id="a-roll" class="clip" src="{video_filename}" muted playsinline
             data-start="0" data-duration="{duration}" data-track-index="0"
             style="position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover"></video>
      <audio id="a-roll-audio" src="{video_filename}" data-start="0"
             data-duration="{duration}" data-track-index="2" data-volume="1"></audio>

{group_divs}
    </div>

    <script>
      window.__timelines = window.__timelines || {{}};
      const tl = gsap.timeline({{ paused: true }});
      const GROUPS = {groups_json};

      GROUPS.forEach((group) => {{
        const groupEl = "#" + group.id;
        tl.set(groupEl, {{ visibility: "visible" }}, group.start);
        tl.fromTo(groupEl, {{ opacity: 0, y: 16 }}, {{ opacity: 1, y: 0, duration: 0.2, ease: "power2.out" }}, group.start);
        group.words.forEach((word) => {{
          const wordEl = "#" + word.id;
          tl.set(wordEl, {{ color: "rgb(200,200,200)" }}, group.start);
          tl.to(wordEl, {{ color: "#ff3b8d", duration: 0.1, ease: "none" }}, Math.max(group.start, word.start - 0.05));
        }});
        // Mandatory hard-kill -- see SKILL.md stage 6.
        tl.to(groupEl, {{ opacity: 0, y: -10, duration: 0.12, ease: "power2.in" }}, group.effectiveEnd - 0.12);
        tl.set(groupEl, {{ opacity: 0, visibility: "hidden" }}, group.effectiveEnd);
      }});

      window.__timelines["main"] = tl;
    </script>
  </body>
</html>
"""

if __name__ == "__main__":
    caption_groups_path, export_path, project_dir = sys.argv[1], sys.argv[2], sys.argv[3]
    groups = json.load(open(caption_groups_path))
    width, height, duration = ffprobe_video(export_path)
    print(f"export: {width}x{height}, {duration}s")

    if not os.path.exists(project_dir):
        # HYPERFRAMES_SKIP_SKILLS avoids init's own "check skills against
        # GitHub" network step, which was observed to hang indefinitely on
        # a flaky connection -- see SKILL.md stage 6.
        env = {**os.environ, "HYPERFRAMES_SKIP_SKILLS": "1"}
        subprocess.run(
            ["npx", "hyperframes", "init", project_dir, "--video", export_path,
             "--resolution", "portrait", "--skip-transcribe", "--non-interactive"],
            check=True, env=env, timeout=120,
        )
        print(f"scaffolded {project_dir}")

    video_filename = os.path.basename([f for f in os.listdir(project_dir) if f.lower().endswith((".mp4", ".mov", ".webm"))][0])
    group_divs, js_groups = build_groups_html_and_js(groups, duration)
    caption_top = height - 700  # safe-zone rule: ~600-700px from the bottom on a portrait canvas

    html = TEMPLATE.format(
        width=width, height=height, duration=duration, video_filename=video_filename,
        caption_top=caption_top, group_divs=group_divs,
        groups_json=json.dumps(js_groups, ensure_ascii=False),
    )
    index_path = os.path.join(project_dir, "index.html")
    open(index_path, "w").write(html)
    print(f"wrote {index_path}")

    check = subprocess.run(["npx", "hyperframes", "check"], cwd=project_dir, capture_output=True, text=True)
    print(check.stdout[-3000:])
    if check.returncode != 0:
        print("check reported issues -- review before rendering", file=sys.stderr)
