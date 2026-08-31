#!/usr/bin/env python3
"""Extract a plain-text transcript from a video's burned-in (hardcoded)
subtitles, without ASR. See SKILL.md "源视频自带硬字幕" section.

Approach: 1) ffmpeg scene-detect on just the subtitle-band crop to find
subtitle-change timestamps (much denser/more accurate than whole-frame scene
detection); 2) grab a cropped frame at each timestamp; 3) batch those crops
to a vision model to read the text; 4) dedup consecutive repeats and join.

Usage: extract_hardcoded_subs.py <video.mp4> <out_dir> [crop_y0_frac] [crop_h_frac]
  crop_y0_frac/crop_h_frac: fraction of frame height where the subtitle band
  starts / how tall it is (default 0.76 / 0.24 -- bottom quarter). Tune per
  video if a sample frame shows the text sitting outside this band.

Writes:
  <out_dir>/sub_frames/f0000.png ...   (cropped subtitle-band frames)
  <out_dir>/subs_timeline.json         ([{"time": seconds, "text": "..."}])
  <out_dir>/transcript.txt             (plain concatenated text, write_scenes.py input)
"""
import base64, json, os, re, subprocess, sys, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config

BATCH_SIZE = 15
MIN_GAP = 0.35  # seconds; collapse scene-change timestamps closer than this


def ffprobe_dims(video):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0", video],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    w, h = out.split(",")[:2]
    return int(w), int(h)


def detect_timestamps(video, crop_expr, threshold=0.12):
    cmd = [
        "ffmpeg", "-i", video,
        "-vf", f"crop={crop_expr},select='gt(scene\\,{threshold})',showinfo",
        "-vsync", "vfr", "-f", "null", "-",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    times = [0.0]  # always include the first frame
    for line in proc.stderr.splitlines():
        m = re.search(r"pts_time:([0-9.]+)", line)
        if m:
            times.append(float(m.group(1)))
    times.sort()
    deduped = []
    for t in times:
        if not deduped or t - deduped[-1] >= MIN_GAP:
            deduped.append(t)
    return deduped


def extract_crop_frame(video, crop_expr, t, out_path):
    subprocess.run(
        ["ffmpeg", "-y", "-ss", str(t), "-i", video, "-vf", f"crop={crop_expr}",
         "-frames:v", "1", "-q:v", "2", out_path],
        capture_output=True, check=True,
    )


def ocr_batch(paths):
    """Returns a list[str] the same length as paths."""
    content = [
        {"type": "text", "text": (
            f"These are {len(paths)} cropped video-subtitle-band images, in order, "
            "labeled frame 1.. by their position in this message. Each may contain "
            "Chinese burned-in subtitle text, or be blank/no text. "
            "Respond with ONLY a JSON array of exactly " + str(len(paths)) + " strings, "
            "one per frame in order, each being the EXACT text visible in that frame "
            "(empty string \"\" if no readable subtitle text). No prose, no markdown fences."
        )}
    ]
    for p in paths:
        b64 = base64.b64encode(open(p, "rb").read()).decode()
        content.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}})

    req = urllib.request.Request(
        f"{config.NEWAPI_URL}/v1/chat/completions",
        data=json.dumps({
            "model": "gemini-2.5-pro",
            "messages": [{"role": "user", "content": content}],
        }).encode(),
        headers={"Authorization": f"Bearer {config.NEWAPI_KEY}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=180) as r:
        resp = json.loads(r.read().decode())
    text = resp["choices"][0]["message"]["content"].strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]
    result = json.loads(text)
    if len(result) != len(paths):
        raise ValueError(f"OCR batch returned {len(result)} items for {len(paths)} frames")
    return result


if __name__ == "__main__":
    video, out_dir = sys.argv[1], sys.argv[2]
    y0_frac = float(sys.argv[3]) if len(sys.argv) > 3 else 0.76
    h_frac = float(sys.argv[4]) if len(sys.argv) > 4 else 0.24

    frames_dir = os.path.join(out_dir, "sub_frames")
    os.makedirs(frames_dir, exist_ok=True)

    w, h = ffprobe_dims(video)
    crop_h = int(h * h_frac)
    crop_y = int(h * y0_frac)
    crop_expr = f"{w}:{crop_h}:0:{crop_y}"
    print(f"video {w}x{h}, subtitle-band crop {crop_expr}")

    timestamps = detect_timestamps(video, crop_expr)
    print(f"detected {len(timestamps)} subtitle-change timestamps")

    paths = []
    for i, t in enumerate(timestamps):
        p = os.path.join(frames_dir, f"f{i:04d}.png")
        extract_crop_frame(video, crop_expr, t, p)
        paths.append(p)

    texts = []
    for i in range(0, len(paths), BATCH_SIZE):
        batch = paths[i:i + BATCH_SIZE]
        texts.extend(ocr_batch(batch))
        print(f"ocr {i + len(batch)}/{len(paths)}")

    timeline = [{"time": t, "text": txt.strip()} for t, txt in zip(timestamps, texts)]
    json.dump(timeline, open(os.path.join(out_dir, "subs_timeline.json"), "w"), indent=2, ensure_ascii=False)

    # Dedup consecutive repeats/empties, join into a flat transcript.
    lines = []
    prev = None
    for entry in timeline:
        txt = entry["text"]
        if not txt or txt == prev:
            continue
        lines.append(txt)
        prev = txt
    transcript = " ".join(lines)
    open(os.path.join(out_dir, "transcript.txt"), "w").write(transcript)
    print(f"wrote transcript.txt ({len(transcript)} chars, {len(lines)} lines) and subs_timeline.json")
