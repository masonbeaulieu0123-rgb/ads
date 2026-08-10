"""CapCut-style Instagram Reel edit for DroneShine — silent, user adds their own song.

Fast cuts on a strict 0.5 s beat grid (drop a ~120 bpm track and the cuts sync),
kinetic typography, flash cuts into the afters, one slow satisfying wipe, film
grain + vignette throughout, brand end card. Output has NO audio stream.

Usage:
    python3 scripts/build_edit.py             # -> output/droneshine_edit.mp4
    python3 scripts/build_edit.py --stills    # preview frames
"""

import os
import sys
import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

sys.path.insert(0, os.path.dirname(__file__))
from build_ad import (anton, archivo, draw_tracked, pill, faded, lerp_color,
                      load_logo, ease_out, smoothstep,
                      BG_TOP, BG_BOT, GREEN, WHITE, GRAY, PHONE, SITE)

W, H = 1080, 1920
FPS = 30
HEADROOM = 1.35
BEAT = 0.5          # cut grid; matches a 120 bpm track


# ---------------------------------------------------------------- assets

def cover_grade(im, before):
    s = max(W * HEADROOM / im.width, H * HEADROOM / im.height)
    im = im.resize((round(im.width * s), round(im.height * s)), Image.LANCZOS)
    x = (im.width - int(W * HEADROOM)) // 2
    y = (im.height - int(H * HEADROOM)) // 2
    im = im.crop((x, y, x + int(W * HEADROOM), y + int(H * HEADROOM)))
    im = im.filter(ImageFilter.UnsharpMask(radius=2, percent=45, threshold=2))
    if before:
        im = ImageEnhance.Color(im).enhance(0.82)
        im = ImageEnhance.Brightness(im).enhance(0.90)
        im = ImageEnhance.Contrast(im).enhance(1.04)
    else:
        im = ImageEnhance.Color(im).enhance(1.10)
        im = ImageEnhance.Brightness(im).enhance(1.03)
        im = ImageEnhance.Contrast(im).enhance(1.06)
    return im


def load_pairs():
    pairs = []
    for path in ("assets/ba_lake_house.jpg", "assets/ba_pool_house.jpg",
                 "assets/ba_gray_roof.jpg"):
        src = Image.open(path).convert("RGB")
        half = src.width // 2
        before = src.crop((0, 0, half, src.height))
        after = src.crop((src.width - half, 0, src.width, src.height))
        pairs.append((cover_grade(before, True), cover_grade(after, False)))
    return pairs


PAIRS = load_pairs()
LOGO = load_logo(660)


def make_vignette():
    yy = np.arange(H)[:, None] - H / 2
    xx = np.arange(W)[None, :] - W / 2
    r = np.sqrt((xx / (W * 0.72)) ** 2 + (yy / (H * 0.72)) ** 2)
    a = np.clip((r - 0.55) / 0.45, 0, 1) ** 1.6 * 105
    v = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    v.putalpha(Image.fromarray(a.astype(np.uint8)))
    return v


VIGNETTE = make_vignette()

GRAIN = []
_rng = np.random.default_rng(3)
for _ in range(6):
    GRAIN.append((_rng.standard_normal((H // 2, W // 2, 1)) * 3.0)
                 .repeat(2, axis=0).repeat(2, axis=1))


def make_gradient(glow_cy):
    col = np.linspace(0, 1, H)[:, None]
    bg = (np.array(BG_TOP) * (1 - col) + np.array(BG_BOT) * col)
    bg = np.repeat(bg[:, None, :], W, axis=1)
    yy = np.arange(H)[:, None] - glow_cy
    xx = np.arange(W)[None, :] - W / 2
    glow = np.exp(-(xx ** 2 + yy ** 2) / (2 * 640.0 ** 2))
    bg += glow[..., None] * np.array(GREEN) * 0.06
    return Image.fromarray(np.clip(bg, 0, 255).astype(np.uint8))


CARD_BG = make_gradient(900)
END_BG = make_gradient(650)


# ---------------------------------------------------------------- helpers

def view(cov, zoom, dx=0.0, dy=0.0):
    a = HEADROOM / min(zoom, HEADROOM)
    c = (cov.width - W * a) / 2 + dx
    f = (cov.height - H * a) / 2 + dy
    return cov.transform((W, H), Image.AFFINE, (a, 0, c, 0, a, f),
                         resample=Image.BICUBIC)


def text_sprite(text, size, color, font=None, tracking=0):
    font = font or anton(size)
    probe = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    tw = sum(probe.textlength(c, font=font) for c in text) + tracking * (len(text) - 1)
    asc, desc = font.getmetrics()
    pad = 60
    im = Image.new("RGBA", (int(tw) + pad * 2, asc + desc + pad * 2), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    draw_tracked(d, (im.width / 2, im.height / 2 + 7), text, font, (0, 0, 0, 150),
                 tracking)
    im = im.filter(ImageFilter.GaussianBlur(9))
    d = ImageDraw.Draw(im)
    draw_tracked(d, (im.width / 2, im.height / 2), text, font, color, tracking)
    return im


def pop(frame, sprite, cx, cy, p, overshoot=0.26):
    """CapCut-style pop-in: sprite lands from an over-scale with a fast ease."""
    if p <= 0:
        return
    e = ease_out(min(p / 0.28, 1.0))
    scale = 1 + overshoot * (1 - e)
    al = min(p / 0.12, 1.0)
    s = sprite if scale == 1 and al >= 1 else sprite.resize(
        (max(int(sprite.width * scale), 1), max(int(sprite.height * scale), 1)),
        Image.BILINEAR)
    if al < 1:
        s = faded(s, al)
    frame.paste(s, (int(cx - s.width / 2), int(cy - s.height / 2)), s)


SHAKE = [(7, -5), (-5, 4), (3, -2), (-1, 1)]


def shake_at(t, start, mag=1.0):
    i = int((t - start) * FPS)
    if 0 <= i < len(SHAKE):
        return SHAKE[i][0] * mag, SHAKE[i][1] * mag
    return 0.0, 0.0


def watermark(frame):
    d = ImageDraw.Draw(frame)
    draw_tracked(d, (W / 2, 1848), f"{SITE}  •  {PHONE}", archivo(24, 550),
                 (255, 255, 255, 0)[:3], tracking=4)


def small_mark(frame, color=(120, 128, 122)):
    d = ImageDraw.Draw(frame)
    draw_tracked(d, (W / 2, 1848), f"{SITE}  •  {PHONE}", archivo(24, 550),
                 color, tracking=4)


# ---------------------------------------------------------------- shots

SPRITES = {}


def sprite(key, *args, **kw):
    if key not in SPRITES:
        SPRITES[key] = text_sprite(*args, **kw)
    return SPRITES[key]


def shot_photo_word(cov, word, color, zoom_from, zoom_to, accel=1.6, size=150):
    def render(t, d, t0):
        z = zoom_from + (zoom_to - zoom_from) * (t / d) ** accel
        dx, dy = shake_at(t0 + t, t0)
        frame = view(cov, z, dx, dy)
        frame.paste(VIGNETTE, (0, 0), VIGNETTE)
        pop(frame, sprite(word, word, size, color), W / 2, 880, t / 0.4)
        small_mark(frame, (200, 206, 201))
        return frame
    return render


def shot_transform(pair_idx, drift):
    before, after = PAIRS[pair_idx]
    after_pill = pill("AFTER", archivo(34, 700), (8, 14, 9), (*GREEN, 245),
                      pad_x=30, pad_y=14, tracking=3)

    def render(t, d, t0):
        half = d * 0.5
        if t < half:
            frame = view(before, 1.16 + 0.05 * t / half, drift * (t / half), 0)
        else:
            u = (t - half) / (d - half)
            dx, dy = shake_at(t0 + t, t0 + half, 0.8)
            frame = view(after, 1.10 + 0.07 * u, -drift * (1 - u) + dx, dy)
            p = after_pill
            e = ease_out(min((t - half) / 0.22, 1.0))
            s = 1 + 0.35 * (1 - e)
            ps = p.resize((int(p.width * s), int(p.height * s)), Image.BILINEAR)
            frame.paste(ps, (int(W / 2 - ps.width / 2), int(1480 - ps.height / 2)), ps)
        frame.paste(VIGNETTE, (0, 0), VIGNETTE)
        small_mark(frame, (200, 206, 201))
        return frame
    return render


def shot_card_words(lines):
    """lines: (text, color, size, y, at)"""
    def render(t, d, t0):
        frame = CARD_BG.copy()
        drift = 1 + 0.015 * (t / d)
        for text, color, size, y, at in lines:
            sp = sprite(("card", text), text, size, color)
            if t >= at:
                s = sp.resize((int(sp.width * drift), int(sp.height * drift)),
                              Image.BILINEAR)
                pop(frame, s, W / 2, y, (t - at) / 0.4)
        small_mark(frame)
        return frame
    return render


def shot_satisfying(pair_idx):
    before, after = PAIRS[pair_idx]

    def render(t, d, t0):
        z = 1.08 + 0.05 * t / d
        frame = view(before, z)
        wt = smoothstep((t - 0.15) / (d - 0.65))
        wx = int(wt * W)
        if wx > 0:
            av = view(after, z)
            frame.paste(av.crop((0, 0, wx, H)), (0, 0))
            if 0 < wx < W:
                pd = ImageDraw.Draw(frame, "RGBA")
                pd.rectangle([wx - 26, 0, wx - 2, H], fill=(0, 0, 0, 40))
                pd.rectangle([wx - 2, 0, wx + 1, H], fill=(255, 255, 255, 240))
        frame.paste(VIGNETTE, (0, 0), VIGNETTE)
        # cinematic letterbox
        bar = int(150 * ease_out(min(t / 0.35, 1.0)))
        pd = ImageDraw.Draw(frame)
        pd.rectangle([0, 0, W, bar], fill=(5, 6, 5))
        pd.rectangle([0, H - bar, W, H], fill=(5, 6, 5))
        if t > 0.5:
            al = ease_out((t - 0.5) / 0.5)
            draw_tracked(pd, (W / 2, H - bar - 64), "THE DRONE DIFFERENCE",
                         archivo(30, 600), lerp_color((5, 6, 5), (222, 228, 223), al),
                         tracking=12)
        return frame
    return render


def shot_end_card():
    phone_pill = pill(f"CALL {PHONE}", anton(54), (8, 14, 9), (*GREEN, 255),
                      pad_x=52, pad_y=22, tracking=3)

    def render(t, d, t0):
        frame = END_BG.copy()

        a = ease_out(min(t / 0.4, 1.0))
        if a > 0:
            e = ease_out(min(t / 0.35, 1.0))
            scale = (1 + 0.18 * (1 - e)) * (1 + 0.015 * t / d)
            lw = int(LOGO.width * scale)
            lg = LOGO.resize((lw, round(LOGO.height * lw / LOGO.width)), Image.LANCZOS)
            lg = lg if a >= 1 else faded(lg, a)
            frame.paste(lg, ((W - lg.width) // 2, 330 + int((1 - a) * 30)), lg)

        d2 = ImageDraw.Draw(frame)
        if t >= 0.5:
            al = ease_out((t - 0.5) / 0.4)
            d2.text((W / 2, 1140), "STATEWIDE IN FLORIDA", font=anton(64),
                    fill=lerp_color(BG_BOT, WHITE, al), anchor="mm")
        if t >= 1.0:
            al = ease_out((t - 1.0) / 0.4)
            draw_tracked(d2, (W / 2, 1222), "ROOFS • WINDOWS • SOLAR • BUILDING EXTERIORS",
                         archivo(32, 600), lerp_color(BG_BOT, GREEN, al), tracking=3)
        if t >= 1.5:
            al = ease_out((t - 1.5) / 0.35)
            pulse = 1.0 + (0.015 * np.sin(2 * np.pi * (t - 1.5)) if al >= 1 else 0.0)
            e = ease_out(min((t - 1.5) / 0.3, 1.0))
            s = (1 + 0.25 * (1 - e)) * pulse
            p = faded(phone_pill, al) if al < 1 else phone_pill
            p = p.resize((int(p.width * s), int(p.height * s)), Image.BILINEAR)
            frame.paste(p, ((W - p.width) // 2, int(1318 - (p.height - phone_pill.height) / 2)), p)
            d2 = ImageDraw.Draw(frame)
        if t >= 2.0:
            al = ease_out((t - 2.0) / 0.4)
            draw_tracked(d2, (W / 2, 1530), SITE, archivo(38, 650),
                         lerp_color(BG_BOT, WHITE, al), tracking=6)
        if t >= 2.5:
            al = ease_out((t - 2.5) / 0.4)
            draw_tracked(d2, (W / 2, 1612), "FREE QUOTES • FULLY INSURED • FAA CERTIFIED",
                         archivo(26, 550), lerp_color(BG_BOT, GRAY, al), tracking=3)
        return frame
    return render


# ---------------------------------------------------------------- timeline

B = BEAT
SHOTS = [
    (0 * B, 2 * B, shot_photo_word(PAIRS[0][0], "DIRTY ROOF?", WHITE, 1.06, 1.20)),
    (2 * B, 3 * B, shot_photo_word(PAIRS[1][0], "MOLD.", WHITE, 1.24, 1.14, accel=1.0)),
    (3 * B, 4 * B, shot_photo_word(PAIRS[2][0], "GRIME.", WHITE, 1.10, 1.22)),
    (4 * B, 6 * B, shot_card_words([
        ("SEND IN", WHITE, 150, 810, 0.06),
        ("THE DRONE.", GREEN, 150, 1010, 0.32),
    ])),
    (6 * B, 8 * B, shot_transform(0, 26)),
    (8 * B, 10 * B, shot_transform(1, -26)),
    (10 * B, 12 * B, shot_transform(2, 26)),
    (12 * B, 15 * B, shot_card_words([
        ("SAFER.", WHITE, 140, 700, 0.0),
        ("FASTER.", WHITE, 140, 900, 0.5),
        ("CHEAPER.", GREEN, 140, 1100, 1.0),
    ])),
    (15 * B, 19 * B, shot_satisfying(0)),
    (19 * B, 20 * B, shot_photo_word(PAIRS[1][1], "CLEAN.", WHITE, 1.12, 1.22)),
    (20 * B, 21 * B, shot_photo_word(PAIRS[2][1], "SPOTLESS.", GREEN, 1.20, 1.10, accel=1.0)),
    (21 * B, 23 * B, shot_card_words([
        ("STATEWIDE", WHITE, 148, 830, 0.06),
        ("IN FLORIDA.", GREEN, 148, 1020, 0.32),
    ])),
    (23 * B, 31 * B, shot_end_card()),
]
TOTAL = SHOTS[-1][1]

WHITE_FLASH = [4 * B, 12 * B, 15 * B, 21 * B, 23 * B]
GREEN_FLASH = [7 * B, 9 * B, 11 * B]
MINI_FLASH = [19 * B, 20 * B]


def flash_amp(t):
    for ft in WHITE_FLASH:
        u = t - ft
        if 0 <= u < 0.1:
            return (255, 255, 255), 0.8 * (1 - u / 0.1) ** 1.5
    for ft in GREEN_FLASH:
        u = t - ft
        if 0 <= u < 0.09:
            return (205, 255, 214), 0.85 * (1 - u / 0.09) ** 1.5
    for ft in MINI_FLASH:
        u = t - ft
        if 0 <= u < 0.06:
            return (255, 255, 255), 0.45 * (1 - u / 0.06)
    return None, 0.0


def frame_at(t, fi):
    render = SHOTS[-1][2]
    lt, dur, t0 = TOTAL - SHOTS[-1][0], SHOTS[-1][1] - SHOTS[-1][0], SHOTS[-1][0]
    for s0, s1, fn in SHOTS:
        if s0 <= t < s1:
            render, lt, dur, t0 = fn, t - s0, s1 - s0, s0
            break
    frame = render(min(lt, dur - 1e-3), dur, t0)
    arr = np.asarray(frame, dtype=np.float32)
    color, amp = flash_amp(t)
    if amp > 0:
        arr = arr * (1 - amp) + np.array(color, np.float32) * amp
    arr += GRAIN[fi % len(GRAIN)]
    return np.clip(arr, 0, 255).astype(np.uint8)


# ---------------------------------------------------------------- main

def main():
    if "--stills" in sys.argv:
        for t in [0.3, 1.4, 2.6, 3.4, 4.6, 6.4, 8.6, 10.2, 10.6, 13.6]:
            Image.fromarray(frame_at(t, int(t * FPS))).save(
                f"output/edit_preview_{t:04.1f}s.png")
        print("stills saved")
        return

    import imageio_ffmpeg
    out = "output/droneshine_edit.mp4"
    writer = imageio_ffmpeg.write_frames(
        out, (W, H), fps=FPS, codec="libx264", macro_block_size=1,
        input_params=[], output_params=["-crf", "22", "-preset", "medium",
                                        "-pix_fmt", "yuv420p",
                                        "-movflags", "+faststart", "-an"],
    )
    writer.send(None)
    n = int(TOTAL * FPS)
    for i in range(n):
        writer.send(frame_at(i / FPS, i).tobytes())
        if i % 120 == 0:
            print(f"{i}/{n} frames", flush=True)
    writer.close()
    print(f"done: {out} ({TOTAL:.1f}s, {n} frames, silent)")


if __name__ == "__main__":
    main()
