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
                      load_logo, ease_out, smoothstep, rounded_mask,
                      BG_TOP, BG_BOT, GREEN, WHITE, GRAY, PHONE, SITE)

W, H = 1080, 1920
FPS = 30
HEADROOM = 1.35
BEAT = 0.5          # cut grid; matches a 120 bpm track


# ---------------------------------------------------------------- assets

def grade(im, before):
    im = im.filter(ImageFilter.UnsharpMask(radius=2, percent=30, threshold=2))
    if before:
        im = ImageEnhance.Color(im).enhance(0.82)
        im = ImageEnhance.Brightness(im).enhance(0.90)
        im = ImageEnhance.Contrast(im).enhance(1.04)
    else:
        im = ImageEnhance.Color(im).enhance(1.10)
        im = ImageEnhance.Brightness(im).enhance(1.03)
        im = ImageEnhance.Contrast(im).enhance(1.06)
    return im


def blur_backdrop(im):
    """Blurred, darkened cover fill behind the full-photo card."""
    s = max(W / im.width, H / im.height)
    bg = im.resize((round(im.width * s), round(im.height * s)), Image.BILINEAR)
    x = (bg.width - W) // 2
    y = (bg.height - H) // 2
    bg = bg.crop((x, y, x + W, y + H)).filter(ImageFilter.GaussianBlur(26))
    bg = ImageEnhance.Brightness(bg).enhance(0.42)
    return ImageEnhance.Color(bg).enhance(0.80)


def sr_upscale(im, cache_name):
    """4x neural super-resolution so full-bleed crops keep real detail.
    Prefers the EDSR render (best quality) when present, else FSRCNN."""
    edsr = f"assets/sr_edsr/{cache_name}.png"
    if os.path.exists(edsr):
        return Image.open(edsr).convert("RGB")
    cache = f"assets/sr/{cache_name}.png"
    if os.path.exists(cache):
        return Image.open(cache).convert("RGB")
    import cv2
    sr = cv2.dnn_superres.DnnSuperResImpl_create()
    sr.readModel("assets/sr/FSRCNN_x4.pb")
    sr.setModel("fsrcnn", 4)
    out = sr.upsample(np.asarray(im)[:, :, ::-1])
    up = Image.fromarray(out[:, :, ::-1])
    up = up.filter(ImageFilter.UnsharpMask(radius=3, percent=42, threshold=2))
    up.save(cache)
    return up


MASTER_W = 1160      # full-photo masters keep a little headroom over the 1080 canvas


def load_pairs():
    pairs, bgs = [], []
    for path in ("assets/ba_lake_house.jpg", "assets/ba_pool_house.jpg",
                 "assets/ba_gray_roof.jpg"):
        stem = os.path.splitext(os.path.basename(path))[0]
        src = Image.open(path).convert("RGB")
        half = src.width // 2
        halves = []
        for name, box, before in (("before", (0, 0, half, src.height), True),
                                  ("after", (src.width - half, 0, src.width, src.height), False)):
            im = grade(sr_upscale(src.crop(box), f"{stem}_{name}"), before)
            halves.append(im.resize((MASTER_W, round(im.height * MASTER_W / im.width)),
                                    Image.LANCZOS))
        pairs.append(tuple(halves))
        bgs.append(tuple(blur_backdrop(h) for h in halves))
    return pairs, bgs


PAIRS, BGS = load_pairs()
LOGO = load_logo(660)

_MASK_CACHE = {}
_SHADOW_BASE = None


def paste_card(frame, img, scale, dx=0.0, dy=0.0, radius=14):
    """Center the FULL photo at `scale` x canvas width on the blurred backdrop."""
    global _SHADOW_BASE
    w = max(2, int(W * scale))
    h = int(img.height * w / img.width)
    x = (W - w) // 2 + int(dx)
    y = (H - h) // 2 + int(dy)
    if _SHADOW_BASE is None:
        sh = Image.new("RGBA", (1080 + 100, 1060 + 100), (0, 0, 0, 0))
        ImageDraw.Draw(sh).rounded_rectangle([50, 50, 50 + 1079, 50 + 1059], 22,
                                             fill=(0, 0, 0, 120))
        _SHADOW_BASE = sh.filter(ImageFilter.GaussianBlur(20))
    sh = _SHADOW_BASE.resize((w + 100, h + 100), Image.BILINEAR)
    frame.paste(sh, (x - 50, y - 50 + 12), sh)
    card = img.resize((w, h), Image.LANCZOS)
    key = (w, h, radius)
    if key not in _MASK_CACHE:
        if len(_MASK_CACHE) > 64:
            _MASK_CACHE.clear()
        _MASK_CACHE[key] = rounded_mask((w, h), radius)
    frame.paste(card, (x, y), _MASK_CACHE[key])
    return x, y, w, h


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
    GRAIN.append((_rng.standard_normal((H // 2, W // 2, 1)) * 1.3)
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
    """CapCut-style pop-in: over-scale landing with a micro-rotation settle."""
    if p <= 0:
        return
    e = ease_out(min(p / 0.28, 1.0))
    scale = 1 + overshoot * (1 - e)
    rot = 2.2 * (1 - e)
    al = min(p / 0.12, 1.0)
    s = sprite
    if scale != 1 or al < 1 or rot > 0.05:
        s = sprite.resize(
            (max(int(sprite.width * scale), 1), max(int(sprite.height * scale), 1)),
            Image.BILINEAR)
        if rot > 0.05:
            s = s.rotate(rot, resample=Image.BILINEAR, expand=True)
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


def shot_photo_word(img, bg, word, color, size=150):
    def render(t, d, t0):
        frame = bg.copy()
        dx, dy = shake_at(t0 + t, t0)
        s = 0.955 + 0.045 * ease_out(min(t / 0.35, 1.0)) + 0.004 * (t / d)
        paste_card(frame, img, min(s, 1.0), dx, dy)
        frame.paste(VIGNETTE, (0, 0), VIGNETTE)
        pop(frame, sprite(word, word, size, color), W / 2, 930, t / 0.4)
        small_mark(frame, (200, 206, 201))
        return frame
    return render


def shot_transform(pair_idx, drift):
    before, after = PAIRS[pair_idx]
    bg_b, bg_a = BGS[pair_idx]
    after_pill = pill("AFTER", archivo(34, 700), (8, 14, 9), (*GREEN, 245),
                      pad_x=30, pad_y=14, tracking=3)

    def render(t, d, t0):
        half = d * 0.5
        if t < half:
            frame = bg_b.copy()
            s = 0.975 + 0.02 * (t / half)
            x, y, w, h = paste_card(frame, before, s, drift * (t / half), 0)
        else:
            u = (t - half) / (d - half)
            frame = bg_a.copy()
            dx, dy = shake_at(t0 + t, t0 + half, 0.8)
            s = 0.985 + 0.015 * u
            x, y, w, h = paste_card(frame, after, s, -drift * (1 - u) + dx, dy)
            p = after_pill
            e = ease_out(min((t - half) / 0.22, 1.0))
            ps = p.resize((int(p.width * (1 + 0.35 * (1 - e))),
                           int(p.height * (1 + 0.35 * (1 - e)))), Image.BILINEAR)
            frame.paste(ps, (int(W / 2 - ps.width / 2),
                             int(y + h - 46 - ps.height / 2)), ps)
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
    bg = BGS[pair_idx][1]

    def render(t, d, t0):
        frame = bg.copy()
        s = 0.985 + 0.015 * (t / d)
        # compose the slow wipe inside the full-photo card
        w = int(W * s)
        h = int(before.height * w / before.width)
        card = before.resize((w, h), Image.LANCZOS)
        wt = smoothstep((t - 0.15) / (d - 0.65))
        wx = int(wt * w)
        if wx > 0:
            av = after.resize((w, h), Image.LANCZOS)
            card.paste(av.crop((0, 0, wx, h)), (0, 0))
            if 0 < wx < w:
                pd = ImageDraw.Draw(card, "RGBA")
                pd.rectangle([wx - 24, 0, wx - 2, h], fill=(0, 0, 0, 40))
                pd.rectangle([wx - 2, 0, wx + 1, h], fill=(255, 255, 255, 240))
        x, y, w, h = paste_card(frame, card, s)
        frame.paste(VIGNETTE, (0, 0), VIGNETTE)
        pd = ImageDraw.Draw(frame)
        if t > 0.5:
            al = ease_out((t - 0.5) / 0.5)
            draw_tracked(pd, (W / 2, y + h + 72), "THE DRONE DIFFERENCE",
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
    (0 * B, 2 * B, shot_photo_word(PAIRS[0][0], BGS[0][0], "DIRTY ROOF?", WHITE)),
    (2 * B, 3 * B, shot_photo_word(PAIRS[1][0], BGS[1][0], "MOLD.", WHITE)),
    (3 * B, 4 * B, shot_photo_word(PAIRS[2][0], BGS[2][0], "GRIME.", WHITE)),
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
    (19 * B, 20 * B, shot_photo_word(PAIRS[1][1], BGS[1][1], "CLEAN.", WHITE)),
    (20 * B, 21 * B, shot_photo_word(PAIRS[2][1], BGS[2][1], "SPOTLESS.", GREEN)),
    (21 * B, 23 * B, shot_card_words([
        ("STATEWIDE", WHITE, 148, 830, 0.06),
        ("IN FLORIDA.", GREEN, 148, 1020, 0.32),
    ])),
    (23 * B, 34 * B, shot_end_card()),
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
    if amp > 0.25:
        # chromatic aberration on flash frames: R and B channels split apart
        px = int(4 + amp * 8)
        arr[:, :, 0] = np.roll(arr[:, :, 0], px, axis=1)
        arr[:, :, 2] = np.roll(arr[:, :, 2], -px, axis=1)
    if amp > 0:
        arr = arr * (1 - amp) + np.array(color, np.float32) * amp
    # one-frame motion ghost on shot-start shakes (fake motion blur)
    for s0, _, _ in SHOTS:
        di = int((t - s0) * FPS)
        if 0 <= di < 2:
            arr = arr * 0.72 + np.roll(arr, 9 - di * 4, axis=1) * 0.28
            break
    arr += GRAIN[fi % len(GRAIN)]
    return np.clip(arr, 0, 255).astype(np.uint8)


# ---------------------------------------------------------------- audio
# Voice + sound design only (booms, whooshes, ticks) — no music, so the user's
# own song sits cleanly underneath when they post.

SR_A = 44100

INCLUDE_VO = False     # flip to True to bring the voiceover back
INCLUDE_MUSIC = True   # beat-locked backing track under the SFX

VO_CUES = [   # (wav, start) — timed to the on-screen words (am_fenrir pitchman read)
    ("e1", 0.10), ("e2", 1.10), ("e3", 2.10), ("e4", 3.60),
    ("e5", 6.05), ("e6", 7.95), ("e7", 10.55), ("e8", 12.00),
]
BOOMS = [(0.08, 1.0), (2.02, 1.1), (3.5, 0.85), (4.5, 0.85), (5.5, 0.85),
         (6.02, 0.7), (6.52, 0.7), (7.02, 0.9), (10.52, 0.95), (11.52, 1.1)]
WHOOSH_ENDS = [2.0, 6.0, 7.5, 10.5, 11.5]
TICKS = [1.0, 1.5, 3.0, 4.0, 5.0, 9.5, 10.0]


_REVERB_IR = None


def _reverb(sig):
    """Short dark reverb tail via a decaying-noise impulse response."""
    global _REVERB_IR
    if _REVERB_IR is None:
        rng = np.random.default_rng(21)
        irn = int(0.45 * SR_A)
        ir = rng.standard_normal(irn) * np.exp(-np.arange(irn) / SR_A * 9)
        _REVERB_IR = np.convolve(ir, np.ones(16) / 16, mode="same") * 0.05
    wet = np.convolve(sig, _REVERB_IR)[:len(sig) + int(0.45 * SR_A)]
    out = np.zeros(len(wet))
    out[:len(sig)] = sig
    return out + wet


def _boom(gain):
    """Layered 808-style hit: gliding sub + saturation + thump + reverb tail."""
    st = np.arange(int(0.8 * SR_A)) / SR_A
    fr = 82 * np.exp(-st * 11) + 34
    sub = np.sin(2 * np.pi * np.cumsum(fr) / SR_A) * np.exp(-st * 5.5)
    sub = np.tanh(sub * 2.6)
    mid = np.sin(2 * np.pi * np.cumsum(fr * 2.02) / SR_A) * np.exp(-st * 16) * 0.3
    kn = int(0.05 * SR_A)
    rng = np.random.default_rng(5)
    thump = np.zeros_like(st)
    noise = np.convolve(rng.standard_normal(kn), np.ones(24) / 24, mode="same")
    thump[:kn] = noise * np.exp(-np.arange(kn) / SR_A * 120)
    return gain * _reverb(0.17 * sub + 0.05 * mid + 0.10 * thump)


def _whoosh():
    wn = int(0.6 * SR_A)
    rng = np.random.default_rng(9)
    noise = rng.standard_normal(wn)
    y = np.zeros(wn)
    alpha = np.linspace(0.02, 0.5, wn)
    acc = 0.0
    for i in range(wn):
        acc += alpha[i] * (noise[i] - acc)
        y[i] = acc
    return 0.14 * y * (np.arange(wn) / wn) ** 2.0


def _tick():
    tn = int(0.03 * SR_A)
    rng = np.random.default_rng(4)
    noise = np.diff(rng.standard_normal(tn), prepend=0)
    return 0.045 * noise * np.exp(-np.arange(tn) / SR_A * 160)


def _shutter():
    """Camera-shutter double click for the AFTER reveals."""
    tn = int(0.05 * SR_A)
    rng = np.random.default_rng(13)
    c1 = np.diff(rng.standard_normal(tn), prepend=0) * np.exp(-np.arange(tn) / SR_A * 220)
    out = np.zeros(int(0.11 * SR_A))
    out[:tn] += c1
    out[int(0.05 * SR_A):int(0.05 * SR_A) + tn] += c1 * 0.7
    return 0.05 * out


def _drone_whir():
    """Rising quadcopter whir under the 'SEND IN THE DRONE.' card."""
    dn = int(1.0 * SR_A)
    st = np.arange(dn) / SR_A
    f = 130 + 90 * (st / st[-1]) ** 1.4
    phase = 2 * np.pi * np.cumsum(f) / SR_A
    saw = (np.sin(phase) + 0.5 * np.sin(2 * phase) + 0.33 * np.sin(3 * phase)
           + 0.25 * np.sin(4 * phase))
    trem = 1 + 0.35 * np.sin(2 * np.pi * 33 * st * (f / 150))
    y = np.zeros(dn)
    acc = 0.0
    for i in range(dn):          # one-pole lowpass keeps it soft
        acc += 0.12 * (saw[i] * trem[i] - acc)
        y[i] = acc
    env = np.minimum(st / 0.25, 1.0) * np.minimum((st[-1] - st) / 0.2, 1.0)
    return 0.045 * y * np.clip(env, 0, 1)


def _music():
    """Beat-locked backing track: builds with the edit's sections.
    0-2 s pad+hats intro, kick+bass from the 'SEND IN THE DRONE' card (2 s),
    claps from 'SAFER FASTER CHEAPER' (6 s), strips back under the end card."""
    n = int(TOTAL * SR_A)
    m = np.zeros(n, dtype=np.float32)
    bar = BEAT * 4
    chords = [                                        # A minor — darker, harder
        ([220.00, 261.63, 329.63, 440.00], 55.00),    # Am
        ([174.61, 220.00, 261.63, 349.23], 43.65),    # F
        ([130.81, 196.00, 261.63, 329.63], 65.41),    # C
        ([196.00, 246.94, 293.66, 392.00], 49.00),    # G
    ]

    def chord_at(b):
        return chords[0] if b * bar >= 14.0 else chords[b % 4]

    def put(sig, at):
        i0 = int(at * SR_A)
        i1 = min(i0 + len(sig), n)
        if i1 > i0:
            m[i0:i1] += sig[:i1 - i0].astype(np.float32)

    # sidechain pump driven by the kick
    sc = np.ones(n, dtype=np.float32)
    bt = 2.0
    while bt < min(TOTAL, 15.5):
        i0 = int(bt * SR_A)
        seg = np.arange(min(int(BEAT * SR_A), n - i0)) / SR_A
        sc[i0:i0 + len(seg)] *= 1 - 0.45 * np.exp(-seg * 9)
        bt += BEAT

    rng = np.random.default_rng(17)

    def tom(freq_top, gain):
        """Pounding pitched tom with sub weight, saturated."""
        st = np.arange(int(0.16 * SR_A)) / SR_A
        fr = freq_top * np.exp(-st * 13) + 58
        body = np.sin(2 * np.pi * np.cumsum(fr) / SR_A) * np.exp(-st * 13)
        sub = np.sin(2 * np.pi * 55 * st) * np.exp(-st * 10) * 0.6
        knock = np.convolve(rng.standard_normal(int(0.012 * SR_A)),
                            np.ones(5) / 5, mode="same")
        head = np.zeros_like(st)
        head[:len(knock)] = knock * 0.5
        return np.tanh((body + sub + head) * 2.8) * gain

    def breath():
        """Rhythmic pant — bandpassed noise shaped like an exhale."""
        bn = int(0.16 * SR_A)
        noise = rng.standard_normal(bn)
        fast, slow = np.zeros(bn), np.zeros(bn)
        af, as_ = 0.30, 0.06
        f = s_ = 0.0
        for i in range(bn):
            f += af * (noise[i] - f)
            s_ += as_ * (noise[i] - s_)
            fast[i], slow[i] = f, s_
        band = fast - slow
        st = np.arange(bn) / SR_A
        env = np.minimum(st / 0.02, 1) * np.exp(-st * 16)
        return band * env

    # low droning root per bar — menace, not melody
    b = 0
    while b * bar < TOTAL:
        _, root = chord_at(b)
        seg_n = min(int(bar * SR_A), n - int(b * bar * SR_A))
        st = np.arange(seg_n) / SR_A
        env = np.clip(np.minimum(st / 0.15, (bar - st) / 0.15), 0, 1)
        drone = (np.sin(2 * np.pi * root * st)
                 + 0.5 * np.sin(2 * np.pi * root * 2.01 * st)
                 + 0.25 * np.sin(2 * np.pi * root * 3 * st))
        put(np.tanh(drone * 1.6) * 0.045 * env, b * bar)
        b += 1

    # the gallop: pounding toms on every eighth, accents on the quarters
    bt = 0.0
    while bt < min(TOTAL, 15.5):
        on_quarter = abs((bt % BEAT)) < 1e-6
        intro = bt < 2.0
        if intro and not on_quarter:
            bt += BEAT / 2
            continue
        g = 0.155 if on_quarter else 0.095
        put(tom(120 if on_quarter else 100, g), bt)
        bt += BEAT / 2
    m *= sc

    # stomp-clap on 2 & 4 — big, roomy
    bt = BEAT
    while bt < min(TOTAL, 15.0):
        st = np.arange(int(0.14 * SR_A)) / SR_A
        noise = np.convolve(rng.standard_normal(len(st)), np.ones(3) / 3, mode="same")
        stomp = (0.065 * noise + 0.03 * np.sin(2 * np.pi * 160 * st)) * np.exp(-st * 22)
        put(_reverb(stomp)[:int(0.5 * SR_A)], bt)
        bt += BEAT * 2

    # the pant: breaths on the off-beats, pushing the whole thing forward
    bt = BEAT / 2
    while bt < min(TOTAL, 15.5):
        put(breath() * (0.055 if bt >= 2.0 else 0.035), bt)
        bt += BEAT

    t = np.arange(n) / SR_A
    return m * np.clip(t / 0.4, 0, 1) * np.clip((TOTAL - t) / 1.4, 0, 1)


def build_audio():
    import soundfile as sf_
    n = int(TOTAL * SR_A)
    mix = np.zeros((n, 2), dtype=np.float32)

    def add(sig, at, pan=0.0):
        """pan: -1 left .. +1 right; (a, b) tuple pans across the clip."""
        i0 = int(at * SR_A)
        i1 = min(i0 + len(sig), n)
        if i1 <= i0:
            return
        seg = sig[:i1 - i0].astype(np.float32)
        if isinstance(pan, tuple):
            p = np.linspace(pan[0], pan[1], len(seg))
        else:
            p = np.full(len(seg), pan)
        mix[i0:i1, 0] += seg * np.sqrt((1 - p) / 2 + 0.5 * (1 - np.abs(p)))
        mix[i0:i1, 1] += seg * np.sqrt((1 + p) / 2 + 0.5 * (1 - np.abs(p)))

    vo = np.zeros(n, dtype=np.float32)
    for name, at in (VO_CUES if INCLUDE_VO else []):
        data, src_sr = sf_.read(f"output/audio/{name}.wav", dtype="float32")
        if data.ndim > 1:
            data = data.mean(axis=1)
        tt = np.arange(int(len(data) * SR_A / src_sr)) / SR_A
        clip = np.interp(tt, np.arange(len(data)) / src_sr, data)
        i0 = int(at * SR_A)
        i1 = min(i0 + len(clip), n)
        vo[i0:i1] += clip[:i1 - i0]
    vo = np.tanh(vo * 1.7) / np.tanh(1.7)
    vo = vo + 0.18 * np.diff(vo, prepend=0)     # presence lift
    mix[:, 0] += vo * 0.95
    mix[:, 1] += vo * 0.95

    whoosh = _whoosh()
    for i, end in enumerate(WHOOSH_ENDS):
        add(whoosh * 1.4, end - 0.6, pan=(-0.7, 0.7) if i % 2 == 0 else (0.7, -0.7))
    for at, g in BOOMS:
        add(_boom(g * 1.35), at)
    tick = _tick()
    for i, at in enumerate(TICKS):
        add(tick * 1.3, at, pan=0.35 if i % 2 == 0 else -0.35)
    shutter = _shutter()
    for at in (3.55, 4.55, 5.55):
        add(shutter * 1.3, at, pan=0.2)
    add(_drone_whir() * 1.3, 2.05, pan=(-0.5, 0.5))

    if INCLUDE_MUSIC:
        bed = "output/audio/music_bed.wav"
        if os.path.exists(bed):
            # user-supplied track, pre-stretched to the 0.5 s beat grid and loop-filled
            data, src_sr = sf_.read(bed, dtype="float32")
            if data.ndim > 1:
                data = data.mean(axis=1)
            tt = np.arange(int(len(data) * SR_A / src_sr)) / SR_A
            music = np.interp(tt, np.arange(len(data)) / src_sr, data)[:n] * 1.05
        else:
            music = _music() * 2.1
        mix[:len(music), 0] += music
        mix[:len(music), 1] += music

    # master bus: gentle drive for loudness, then normalize hot
    mix = np.tanh(mix * 1.5) / np.tanh(1.5)
    peak = np.abs(mix).max()
    if peak > 0:
        mix *= 0.95 / peak
    import wave
    with wave.open("output/audio/edit_mix.wav", "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR_A)
        w.writeframes((mix * 32767).astype(np.int16).tobytes())
    print(f"edit audio: {TOTAL:.2f}s (VO={INCLUDE_VO}, music={INCLUDE_MUSIC})")


# ---------------------------------------------------------------- main

def main():
    if "--stills" in sys.argv:
        for t in [0.3, 1.4, 2.6, 3.4, 4.6, 6.4, 8.6, 10.2, 10.6, 13.6]:
            Image.fromarray(frame_at(t, int(t * FPS))).save(
                f"output/edit_preview_{t:04.1f}s.png")
        print("stills saved")
        return

    import imageio_ffmpeg
    import subprocess
    build_audio()
    out = "output/droneshine_edit.mp4"
    silent = "output/_edit_silent.mp4"
    writer = imageio_ffmpeg.write_frames(
        silent, (W, H), fps=FPS, codec="libx264", macro_block_size=1,
        input_params=[], output_params=["-crf", "17", "-preset", "slow",
                                        "-pix_fmt", "yuv420p"],
    )
    writer.send(None)
    n = int(TOTAL * FPS)
    for i in range(n):
        writer.send(frame_at(i / FPS, i).tobytes())
        if i % 120 == 0:
            print(f"{i}/{n} frames", flush=True)
    writer.close()

    ff = imageio_ffmpeg.get_ffmpeg_exe()
    subprocess.run([ff, "-y", "-i", silent, "-i", "output/audio/edit_mix.wav",
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                    "-movflags", "+faststart", "-shortest", out],
                   check=True, capture_output=True)
    os.remove(silent)
    print(f"done: {out} ({TOTAL:.1f}s, {n} frames, VO+SFX)")


if __name__ == "__main__":
    main()
