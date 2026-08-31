#!/usr/bin/env python3
"""Compose a publish-ready portrait cover (1080x1440) from an existing stage-2
scene image: full-bleed crop, bottom gradient for legibility, small watermark,
a colored category badge, bold headline, accent-colored subtitle, and a
footer hook line. Matches the convention of this account's real thumbnails
(bold 2-line headline, high-contrast, portrait 3:4-ish canvas).

Usage: make_cover.py <base_image.png> <out.jpg> <badge_text> <title> <subtitle> <footer>
"""
import sys
from PIL import Image, ImageDraw, ImageFont

W, H = 1080, 1440
FONT_PATH = "/System/Library/Fonts/Hiragino Sans GB.ttc"


def font(size, bold=True):
    return ImageFont.truetype(FONT_PATH, size, index=2 if bold else 0)


def draw_text_stroke(draw, xy, text, f, fill, stroke_fill=(0, 0, 0), stroke_width=0, anchor="la"):
    draw.text(xy, text, font=f, fill=fill, stroke_width=stroke_width, stroke_fill=stroke_fill, anchor=anchor)


def make_cover(src_path, out_path, badge_text, title, subtitle, footer):
    im = Image.open(src_path).convert("RGB")
    scale = H / im.height
    new_w, new_h = int(im.width * scale), H
    im = im.resize((new_w, new_h), Image.LANCZOS)
    left = (new_w - W) // 2
    im = im.crop((left, 0, left + W, H))

    overlay = Image.new("L", (1, H), 0)
    grad = ImageDraw.Draw(overlay)
    for y in range(H):
        t = max(0, (y - H * 0.42) / (H * 0.58))
        t = min(1, t)
        alpha = int(215 * (t ** 1.4))
        grad.point((0, y), fill=alpha)
    overlay = overlay.resize((W, H))
    black = Image.new("RGB", (W, H), (5, 6, 10))
    im = Image.composite(black, im, overlay)

    top_overlay = Image.new("L", (1, H), 0)
    tgrad = ImageDraw.Draw(top_overlay)
    for y in range(H):
        t = max(0, 1 - y / (H * 0.18))
        tgrad.point((0, y), fill=int(120 * t))
    top_overlay = top_overlay.resize((W, H))
    im = Image.composite(black, im, top_overlay)

    draw = ImageDraw.Draw(im)

    wm_font = font(38, bold=True)
    draw_text_stroke(draw, (44, 40), "老胡说说", wm_font, (255, 255, 255), stroke_fill=(0, 0, 0), stroke_width=3)

    badge_font = font(30, bold=True)
    bbox = draw.textbbox((0, 0), badge_text, font=badge_font)
    bw, bh = bbox[2] - bbox[0], bbox[3] - bbox[1]
    pad_x, pad_y = 22, 12
    badge_x, badge_y = 44, H * 0.58
    draw.rectangle([badge_x, badge_y, badge_x + bw + pad_x * 2, badge_y + bh + pad_y * 2 + 10], fill=(196, 30, 30))
    draw.text((badge_x + pad_x, badge_y + pad_y), badge_text, font=badge_font, fill=(255, 255, 255))

    head_font_size = 118 if len(title) <= 8 else max(72, int(118 * 8 / len(title)))
    head_font = font(head_font_size, bold=True)
    hy = H * 0.66
    draw_text_stroke(draw, (W / 2, hy), title, head_font, (255, 255, 255), stroke_fill=(0, 0, 0), stroke_width=6, anchor="ma")

    sub_font_size = 46 if len(subtitle) <= 16 else max(32, int(46 * 16 / len(subtitle)))
    sub_font = font(sub_font_size, bold=True)
    sy = hy + head_font_size + 30
    draw_text_stroke(draw, (W / 2, sy), subtitle, sub_font, (235, 80, 70), stroke_fill=(0, 0, 0), stroke_width=4, anchor="ma")

    if footer:
        foot_font_size = 34 if len(footer) <= 20 else max(24, int(34 * 20 / len(footer)))
        foot_font = font(foot_font_size, bold=False)
        fy = H - 70
        draw_text_stroke(draw, (W / 2, fy), footer, foot_font, (220, 220, 220), stroke_fill=(0, 0, 0), stroke_width=3, anchor="ma")

    im.save(out_path, quality=95)
    print(f"saved {out_path} {im.size}")


if __name__ == "__main__":
    src, out, badge, title, subtitle, footer = sys.argv[1:7]
    make_cover(src, out, badge, title, subtitle, footer)
