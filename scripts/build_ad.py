"""Build the DroneShine Instagram video ad from the before/after photos.

Music-only cut: no voiceover — a synthesized beat-driven track carries the ad,
with scene cuts landing on bar lines and whoosh transitions. Renders every
frame with Pillow, pipes them to ffmpeg (imageio-ffmpeg), then muxes the audio.

Usage:
    python3 scripts/build_ad.py                  # 9:16 Reels -> output/droneshine_reel.mp4
    python3 scripts/build_ad.py --format 4x5     # 4:5 feed  -> output/droneshine_feed.mp4
    python3 scripts/build_ad.py --stills         # preview frames -> output/preview_*.png
"""

import os
import sys
import wave
import subprocess
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

FPS = 30
BG_TOP = (19, 21, 20)
BG_BOT = (9, 10, 9)
GREEN = (77, 171, 85)
WHITE = (245, 247, 245)
SOFT = (178, 186, 180)
GRAY = (140, 148, 142)
PHONE = "855-376-6392"
SITE = "DRONESHINECLEANING.COM"

ANTON = "assets/fonts/Anton-Regular.ttf"
ARCHIVO = "assets/fonts/Archivo.ttf"

LAYOUTS = {
    "9x16": dict(
        size=(1080, 1920), out="output/droneshine_reel.mp4",
        bars_y=150, kicker=(30, 240), headline=(84, 348), sub=(38, 456),
        panel=900, panel_xy=(90, 526), radius=32, watermark=(27, 1760),
        bullets=(33, 1496, 84),
        outro=dict(logo_w=660, logo_y=320, state=(66, 1150), services=(33, 1234),
                   phone=(54, 1330), site=(38, 1545), trust=(26, 1628)),
    ),
    "4x5": dict(
        size=(1080, 1350), out="output/droneshine_feed.mp4",
        bars_y=58, kicker=(26, 126), headline=(66, 212), sub=(34, 302),
        panel=740, panel_xy=(170, 354), radius=28, watermark=(23, 1316),
        bullets=(24, 1124, 52),
        outro=dict(logo_w=460, logo_y=125, state=(54, 645), services=(28, 714),
                   phone=(46, 784), site=(34, 990), trust=(23, 1056)),
    ),
}

# -------- timing: four scenes, cuts land on 2 s bars (120 bpm) --------
DURS = [6.5, 6.5, 6.5, 6.5]
XFADE = 0.5
STARTS = []
_t = 0.0
for _d in DURS:
    STARTS.append(_t)
    _t += _d - XFADE
TOTAL = STARTS[-1] + DURS[-1]          # 24.5 s; transitions begin at 6 / 12 / 18 s

OUTRO_CUES = dict(state=0.6, services=1.1, phone=1.7, site=2.6, trust=3.2)


def anton(size):
    return ImageFont.truetype(ANTON, size)


def archivo(size, weight=600):
    f = ImageFont.truetype(ARCHIVO, size)
    vals = []
    for ax in f.get_variation_axes():
        name = ax["name"]
        name = name.decode() if isinstance(name, bytes) else name
        vals.append(weight if "eight" in name else ax["default"])
    f.set_variation_by_axes(vals)
    return f


def smoothstep(t):
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


def ease_out(t):
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) ** 3


def draw_tracked(draw, xy, text, font, fill, tracking=0):
    widths = [draw.textlength(ch, font=font) for ch in text]
    total = sum(widths) + tracking * (len(text) - 1)
    x = xy[0] - total / 2
    for ch, w in zip(text, widths):
        draw.text((x, xy[1]), ch, font=font, fill=fill, anchor="lm")
        x += w + tracking


def rounded_mask(size, radius):
    m = Image.new("L", size, 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, size[0] - 1, size[1] - 1], radius, fill=255)
    return m


def pill(text, font, fg, bg, pad_x=26, pad_y=14, tracking=2):
    probe = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    tw = sum(probe.textlength(c, font=font) for c in text) + tracking * (len(text) - 1)
    asc, desc = font.getmetrics()
    im = Image.new("RGBA", (int(tw) + pad_x * 2, asc + desc + pad_y * 2), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([0, 0, im.width - 1, im.height - 1], im.height // 2, fill=bg)
    draw_tracked(d, (im.width / 2, im.height / 2), text, font, fg, tracking)
    return im


def faded(im, alpha):
    im = im.copy()
    im.putalpha(im.getchannel("A").point(lambda a: int(a * alpha)))
    return im


def lerp_color(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def check_icon(size):
    s = size * 3
    im = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    w = int(s * 0.14)
    d.line([(s * 0.12, s * 0.55), (s * 0.40, s * 0.80), (s * 0.88, s * 0.22)],
           fill=(*GREEN, 255), width=w, joint="curve")
    return im.resize((size, size), Image.LANCZOS)


def bullet_row(text, font, icon):
    probe = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    tw = int(probe.textlength(text, font=font))
    asc, desc = font.getmetrics()
    h = max(icon.height, asc + desc)
    gap = int(icon.width * 0.55)
    im = Image.new("RGBA", (icon.width + gap + tw, h), (0, 0, 0, 0))
    im.paste(icon, (0, (h - icon.height) // 2), icon)
    ImageDraw.Draw(im).text((icon.width + gap, h / 2), text, font=font,
                            fill=(216, 223, 217), anchor="lm")
    return im


def draw_progress(frame, L, idx, p):
    """Story-style progress bars: one segment per scene, active one fills."""
    W = L["size"][0]
    y = L["bars_y"]
    n = len(DURS)
    seg_w, gap, h = 72, 12, 6
    total_w = n * seg_w + (n - 1) * gap
    x0 = (W - total_w) // 2
    d = ImageDraw.Draw(frame, "RGBA")
    for j in range(n):
        x = x0 + j * (seg_w + gap)
        d.rounded_rectangle([x, y, x + seg_w, y + h], h // 2, fill=(255, 255, 255, 40))
        fill = 1.0 if j < idx else (p if j == idx else 0.0)
        if fill > 0:
            d.rounded_rectangle([x, y, x + max(int(seg_w * fill), h), y + h],
                                h // 2, fill=(*GREEN, 235))


def make_background(L):
    W, H = L["size"]
    col = np.linspace(0, 1, H)[:, None]
    grad = (np.array(BG_TOP) * (1 - col) + np.array(BG_BOT) * col)
    bg = np.repeat(grad[:, None, :], W, axis=1)
    px, py = L["panel_xy"]
    P = L["panel"]
    cx, cy = px + P / 2, py + P / 2
    yy = np.arange(H)[:, None] - cy
    xx = np.arange(W)[None, :] - cx
    glow = np.exp(-(xx ** 2 + yy ** 2) / (2 * (P * 0.75) ** 2))
    bg += glow[..., None] * np.array(GREEN) * 0.055
    return Image.fromarray(np.clip(bg, 0, 255).astype(np.uint8))


def make_panel_shadow(L):
    P, r = L["panel"], L["radius"]
    pad = 70
    sh = Image.new("RGBA", (P + pad * 2, P + pad * 2), (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle([pad, pad, pad + P - 1, pad + P - 1],
                                         r, fill=(0, 0, 0, 130))
    return sh.filter(ImageFilter.GaussianBlur(26)), pad


def load_logo(width):
    im = Image.open("assets/logo.jpg").convert("RGB")
    arr = np.asarray(im).astype(int)
    diff = np.abs(arr - 14).max(axis=2)
    mask = diff > 55
    ys, xs = np.where(mask)
    pad = 16
    box = (max(xs.min() - pad, 0), max(ys.min() - pad, 0),
           min(xs.max() + pad, im.width), min(ys.max() + pad, im.height))
    alpha = np.clip((diff - 10) / 28, 0, 1)
    a = Image.fromarray((alpha * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(0.8))
    im = im.convert("RGBA")
    im.putalpha(a)
    im = im.crop(box)
    im = im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)
    return im.filter(ImageFilter.UnsharpMask(radius=2, percent=55, threshold=2))


class BeforeAfterScene:
    def __init__(self, path, headline, sub, bullets, idx, dur, L):
        self.dur = dur
        self.idx = idx
        self.headline = headline
        self.sub = sub
        self.L = L
        bs, self.bullet_y, self.bullet_gap = L["bullets"]
        icon = check_icon(int(bs * 0.95))
        f_bullet = archivo(bs, 550)
        self.bullets = [bullet_row(b, f_bullet, icon) for b in bullets]
        P = self.P = L["panel"]
        src = Image.open(path).convert("RGB")
        half_w = src.width // 2
        before = src.crop((0, 0, half_w, src.height))
        after = src.crop((src.width - half_w, 0, src.width, src.height))
        self.big = int(P * 1.09)
        self.before = self._cover(before, self.big)
        self.after = self._cover(after, self.big)
        self.mask = rounded_mask((P, P), L["radius"])
        self.shadow, self.shadow_pad = make_panel_shadow(L)
        self.bg = make_background(L)
        f_label = archivo(29 if P >= 850 else 26, 650)
        self.pill_before = pill("BEFORE", f_label, WHITE, (8, 10, 9, 185),
                                pad_x=24, pad_y=12, tracking=3)
        self.pill_after = pill("AFTER", f_label, (8, 14, 9), (*GREEN, 240),
                               pad_x=24, pad_y=12, tracking=3)

    @staticmethod
    def _cover(im, size):
        s = max(size / im.width, size / im.height)
        im = im.resize((round(im.width * s), round(im.height * s)), Image.LANCZOS)
        x = (im.width - size) // 2
        y = (im.height - size) // 2
        return im.crop((x, y, x + size, y + size))

    def _panel_view(self, im, zoom):
        P = self.P
        a = self.big / (P * zoom)
        c = (self.big - P * a) / 2
        return im.transform((P, P), Image.AFFINE, (a, 0, c, 0, a, c),
                            resample=Image.BICUBIC)

    def render(self, t):
        L = self.L
        W, H = L["size"]
        P = self.P
        px, py = L["panel_xy"]
        frame = self.bg.copy()
        d = ImageDraw.Draw(frame)

        zoom = 1.022 + 0.038 * (t / self.dur)
        wipe_end = self.dur - 1.6
        wipe_t = smoothstep((t - 0.8) / (wipe_end - 0.8))
        wipe_x = int(wipe_t * P)

        panel = self._panel_view(self.before, zoom)
        if wipe_x > 0:
            after_view = self._panel_view(self.after, zoom)
            panel.paste(after_view.crop((0, 0, wipe_x, P)), (0, 0))
            if 0 < wipe_x < P:
                pd = ImageDraw.Draw(panel, "RGBA")
                pd.rectangle([wipe_x - 22, 0, wipe_x - 2, P], fill=(0, 0, 0, 36))
                pd.rectangle([wipe_x - 2, 0, wipe_x + 1, P], fill=(255, 255, 255, 235))

        frame.paste(self.shadow, (px - self.shadow_pad, py - self.shadow_pad + 16),
                    self.shadow)
        frame.paste(panel, (px, py), self.mask)
        d.rounded_rectangle([px, py, px + P - 1, py + P - 1], L["radius"],
                            outline=(255, 255, 255, 22), width=1)

        lbl_y = py + 26
        b_alpha = 1.0 if wipe_t < 1 else max(0.0, 1 - (t - wipe_end - 0.05) / 0.3)
        if b_alpha > 0:
            p = faded(self.pill_before, b_alpha)
            frame.paste(p, (px + P - p.width - 26, lbl_y), p)
        a_alpha = smoothstep((wipe_x - 190) / 210) if wipe_x > 0 else 0.0
        if a_alpha > 0:
            p = faded(self.pill_after, a_alpha)
            frame.paste(p, (px + 26, lbl_y), p)

        # staggered header entrance
        ks, ky = L["kicker"]
        hs, hy = L["headline"]
        ss, sy = L["sub"]
        ak = ease_out((t - 0.05) / 0.45)
        ah = ease_out((t - 0.18) / 0.5)
        asub = ease_out((t - 0.32) / 0.5)
        if ak > 0:
            draw_tracked(d, (W / 2, ky + (1 - ak) * 16), "DRONE SHINE",
                         archivo(ks, 600), lerp_color(BG_TOP, GREEN, ak), tracking=14)
        if ah > 0:
            d.text((W / 2, hy + (1 - ah) * 22), self.headline, font=anton(hs),
                   fill=lerp_color(BG_TOP, WHITE, ah), anchor="mm")
        if asub > 0:
            draw_tracked(d, (W / 2, sy + (1 - asub) * 16), self.sub,
                         archivo(ss, 500), lerp_color(BG_TOP, SOFT, asub), tracking=2)

        block_w = max(b.width for b in self.bullets)
        bx = (W - block_w) // 2
        for i, row in enumerate(self.bullets):
            al = ease_out((t - (0.7 + 0.4 * i)) / 0.5)
            if al <= 0:
                continue
            r = faded(row, al)
            rise = int((1 - al) * 14)
            frame.paste(r, (bx, self.bullet_y + i * self.bullet_gap + rise), r)

        ws, wy = L["watermark"]
        draw_tracked(d, (W / 2, wy), f"{SITE}  •  {PHONE}", archivo(ws, 550), GRAY,
                     tracking=4)
        draw_progress(frame, L, self.idx, t / self.dur)
        return frame


class OutroScene:
    def __init__(self, dur, idx, L):
        self.dur = dur
        self.idx = idx
        self.L = L
        O = L["outro"]
        self.logo = load_logo(O["logo_w"])
        self.bg = make_background(L)
        self.phone_pill = pill(f"CALL {PHONE}", anton(O["phone"][0]), (8, 14, 9),
                               (*GREEN, 255), pad_x=52, pad_y=22, tracking=3)

    def render(self, t):
        L = self.L
        W, H = L["size"]
        O = L["outro"]
        frame = self.bg.copy()
        c = OUTRO_CUES

        def fade(start, dur=0.55):
            return ease_out((t - start) / dur)

        a = fade(0.0, 0.7)
        if a > 0:
            lift = int((1 - a) * 26)
            z = 1.0 + 0.018 * (t / self.dur)
            lw = int(self.logo.width * z)
            logo = self.logo.resize((lw, round(self.logo.height * lw / self.logo.width)),
                                    Image.LANCZOS)
            logo = logo if a >= 1 else faded(logo, a)
            frame.paste(logo, ((W - logo.width) // 2, O["logo_y"] + lift), logo)

        d = ImageDraw.Draw(frame)
        if fade(c["state"]) > 0:
            col = lerp_color(BG_BOT, WHITE, fade(c["state"]))
            ss_, sy_ = O["state"]
            d.text((W / 2, sy_), "STATEWIDE IN FLORIDA", font=anton(ss_),
                   fill=col, anchor="mm")
        if fade(c["services"]) > 0:
            col = lerp_color(BG_BOT, GREEN, fade(c["services"]))
            vs_, vy_ = O["services"]
            draw_tracked(d, (W / 2, vy_), "ROOFS • WINDOWS • SOLAR • BUILDING EXTERIORS",
                         archivo(vs_, 600), col, tracking=3)
        if fade(c["phone"]) > 0:
            a3 = fade(c["phone"])
            # gentle heartbeat pulse once the pill has landed
            pulse = 1.0 + (0.015 * np.sin(2 * np.pi * 1.0 * (t - c["phone"])) if a3 >= 1 else 0.0)
            p = faded(self.phone_pill, a3)
            pw = int(p.width * pulse)
            p = p.resize((pw, int(p.height * pulse)), Image.LANCZOS)
            rise = int((1 - a3) * 18)
            frame.paste(p, ((W - p.width) // 2, O["phone"][1] + rise), p)
            d = ImageDraw.Draw(frame)
        if fade(c["site"]) > 0:
            col = lerp_color(BG_BOT, WHITE, fade(c["site"]))
            draw_tracked(d, (W / 2, O["site"][1]), SITE,
                         archivo(O["site"][0], 650), col, tracking=6)
        if fade(c["trust"]) > 0:
            col = lerp_color(BG_BOT, GRAY, fade(c["trust"]))
            draw_tracked(d, (W / 2, O["trust"][1]),
                         "FREE QUOTES • FULLY INSURED • FAA CERTIFIED",
                         archivo(O["trust"][0], 550), col, tracking=3)
        draw_progress(frame, L, self.idx, t / self.dur)
        return frame


def make_scenes(L):
    return [
        BeforeAfterScene("assets/ba_lake_house.jpg",
                         "THE DRONE DIFFERENCE", "SOFT-WASH ROOF CLEANING",
                         ["Surface-safe soft-wash pressure",
                          "Spot-free deionized rinse",
                          "Before & after photos included"], 0, DURS[0], L),
        BeforeAfterScene("assets/ba_pool_house.jpg",
                         "NOBODY ON YOUR ROOF", "NO LADDERS • NO CREWS AT HEIGHT",
                         ["Zero workers at height",
                          "0% damage risk",
                          "Fully insured • FAA Part 107 certified"], 1, DURS[1], L),
        BeforeAfterScene("assets/ba_gray_roof.jpg",
                         "SAFER. FASTER. CHEAPER.", "THE MODERN WAY TO CLEAN",
                         ["50–70% quicker than crews",
                          "No lifts or scaffolds needed",
                          "Eco-friendly options"], 2, DURS[2], L),
        OutroScene(DURS[3], 3, L),
    ]


def dissolve(a_img, b_img, p, W, H):
    mix = smoothstep(p)
    s = 1.028 - 0.028 * ease_out(p)
    bw, bh = int(W * s), int(H * s)
    b = b_img.resize((bw, bh), Image.BILINEAR).crop(
        ((bw - W) // 2, (bh - H) // 2, (bw - W) // 2 + W, (bh - H) // 2 + H))
    return Image.blend(a_img, b, mix)


def frame_at(t, scenes, L):
    W, H = L["size"]
    active = [(s, t - st) for s, st in zip(scenes, STARTS) if st <= t < st + s.dur]
    if not active:
        return scenes[-1].render(scenes[-1].dur - 0.001)
    if len(active) == 1:
        return active[0][0].render(active[0][1])
    (s1, t1), (s2, t2) = active
    return dissolve(s1.render(t1), s2.render(t2), t2 / XFADE, W, H)


# ---------------------------------------------------------------- audio

SR = 44100
BEAT = 0.5          # 120 bpm
BAR = BEAT * 4


def _note(freq, dur, gain, harmonics=((1, 1.0),)):
    st = np.arange(int(dur * SR)) / SR
    w = np.zeros_like(st)
    for mult, amp in harmonics:
        w += amp * np.sin(2 * np.pi * freq * mult * st)
    return gain * w


def synth_music(total):
    """Beat-driven modern bed: pumping pad, bass groove, four-on-floor kick,
    claps, offbeat hats, 16th-note arp — sections build with the scenes."""
    n = int(total * SR)
    music = np.zeros(n, dtype=np.float32)
    chords = [
        ([261.63, 329.63, 392.00, 493.88], 65.41),   # Cmaj7
        ([196.00, 246.94, 293.66, 392.00], 49.00),   # G
        ([220.00, 261.63, 329.63, 392.00], 55.00),   # Am7
        ([174.61, 220.00, 261.63, 349.23], 43.65),   # Fmaj7
    ]

    def chord_at(bar):
        if bar * BAR >= 20.0:            # resolve home for the ending
            return chords[0]
        return chords[bar % 4]

    def add(sig, at):
        i0 = int(at * SR)
        i1 = min(i0 + len(sig), n)
        if i1 > i0:
            music[i0:i1] += sig[:i1 - i0].astype(np.float32)

    # sidechain envelope from the kick pattern (kick enters at 6 s)
    sc = np.ones(n, dtype=np.float32)
    bt = 6.0
    while bt < min(total, 20.5):
        i0 = int(bt * SR)
        seg = np.arange(min(int(BEAT * SR), n - i0)) / SR
        sc[i0:i0 + len(seg)] *= 1 - 0.45 * np.exp(-seg * 9)
        bt += BEAT

    # pad: whole-bar chords, slow attack
    pad = np.zeros(n, dtype=np.float32)
    bar = 0
    while bar * BAR < total:
        tones, _ = chord_at(bar)
        seg_n = min(int(BAR * SR), n - int(bar * BAR * SR))
        st = np.arange(seg_n) / SR
        env = np.clip(np.minimum(st / 0.5, (BAR - st) / 0.4), 0, 1)
        seg = np.zeros(seg_n)
        for f in tones:
            seg += 0.030 * np.sin(2 * np.pi * f * st) + 0.008 * np.sin(2 * np.pi * 2 * f * st)
        pad[int(bar * BAR * SR):int(bar * BAR * SR) + seg_n] += (seg * env)
        bar += 1
    music += pad

    # bass: eighth-note groove, from 6 s
    bt = 6.0
    while bt < min(total, 21.0):
        bar_i = int(bt // BAR)
        tones, root = chord_at(bar_i)
        eighth = int((bt % BAR) / (BEAT / 2)) % 8
        freq = root * (1.5 if eighth in (3, 6) else 1.0)
        dur = 0.21
        st = np.arange(int(dur * SR)) / SR
        env = np.exp(-st * 9) * np.minimum(st / 0.008, 1)
        sig = env * (np.sin(2 * np.pi * freq * st) * 0.13
                     + np.sin(2 * np.pi * freq * 2 * st) * 0.035
                     + np.sin(2 * np.pi * freq * 3 * st) * 0.012)
        add(sig, bt)
        bt += BEAT / 2

    # arp: 16th notes an octave up, echo, light in the intro
    arp = np.zeros(n, dtype=np.float32)
    bt = 0.0
    k = 0
    while bt < min(total, 22.5):
        bar_i = int(bt // BAR)
        tones, _ = chord_at(bar_i)
        freq = tones[k % 4] * 2
        st = np.arange(int(0.12 * SR)) / SR
        env = np.exp(-st * 26) * np.minimum(st / 0.005, 1)
        gain = 0.020 if bt >= 6.0 else 0.013
        sig = gain * env * (np.sin(2 * np.pi * freq * st)
                            + np.sin(2 * np.pi * freq * 3 * st) / 9)
        i0 = int(bt * SR)
        i1 = min(i0 + len(sig), n)
        arp[i0:i1] += sig[:i1 - i0]
        bt += BEAT / 2
        k += 1
    delay = int(0.375 * SR)
    arp[delay:] += 0.4 * arp[:-delay].copy()
    music += arp

    music *= sc  # pump pad/bass/arp against the kick

    # kick: four on the floor, 6 s -> 20.5 s
    bt = 6.0
    while bt < min(total, 20.5):
        st = np.arange(int(0.14 * SR)) / SR
        fr = 92 * np.exp(-st * 16) + 42
        add(0.115 * np.sin(2 * np.pi * np.cumsum(fr) / SR) * np.exp(-st * 18), bt)
        bt += BEAT

    # clap on 2 & 4, from 12 s
    rng = np.random.default_rng(11)
    bt = 12.0 + BEAT
    while bt < min(total, 20.0):
        st = np.arange(int(0.11 * SR)) / SR
        noise = rng.standard_normal(len(st))
        noise = np.convolve(noise, np.ones(8) / 8, mode="same")  # soften
        add(0.045 * noise * np.exp(-st * 30), bt)
        bt += BEAT * 2

    # hats: offbeats throughout (lighter before 6 s)
    bt = BEAT / 2
    while bt < min(total, 21.0):
        hn = int(0.03 * SR)
        noise = rng.standard_normal(hn)
        noise = np.diff(noise, prepend=0)
        g = 0.013 if bt >= 6.0 else 0.007
        add(g * noise * np.exp(-np.arange(hn) / SR * 95), bt)
        bt += BEAT

    # whooshes rising into each scene cut, small boom under the logo land
    for cut in (6.0, 12.0, 18.0):
        wn = int(0.7 * SR)
        noise = rng.standard_normal(wn)
        y = np.zeros(wn)
        alpha = np.linspace(0.015, 0.45, wn)
        acc = 0.0
        for i in range(wn):
            acc += alpha[i] * (noise[i] - acc)
            y[i] = acc
        ramp = (np.arange(wn) / wn) ** 2.2
        add(0.16 * y * ramp, cut - 0.7)
    st = np.arange(int(0.9 * SR)) / SR
    add(0.10 * np.sin(2 * np.pi * 55 * st) * np.exp(-st * 6), 18.35)

    t = np.arange(n) / SR
    music *= np.clip(t / 0.6, 0, 1) * np.clip((total - t) / 1.8, 0, 1)
    return music


def build_audio():
    mix = synth_music(TOTAL)
    peak = np.abs(mix).max()
    if peak > 0:
        mix *= 0.88 / peak
    stereo = np.repeat((mix * 32767).astype(np.int16)[:, None], 2, axis=1)
    with wave.open("output/audio/mix.wav", "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(stereo.tobytes())
    print(f"audio mix: {TOTAL:.2f}s")


# ---------------------------------------------------------------- main

def main():
    fmt = "4x5" if "4x5" in sys.argv else "9x16"
    L = LAYOUTS[fmt]
    W, H = L["size"]
    scenes = make_scenes(L)

    if "--stills" in sys.argv:
        probes = [0.5, 3.6, 6.25, 9.6, 15.6, 20.0, 23.5]
        for t in probes:
            frame_at(t, scenes, L).save(f"output/preview_{fmt}_{t:04.1f}s.png")
        print("stills saved")
        return

    import imageio_ffmpeg
    build_audio()
    silent = "output/_silent.mp4"
    writer = imageio_ffmpeg.write_frames(
        silent, (W, H), fps=FPS, codec="libx264", macro_block_size=1,
        output_params=["-crf", "19", "-preset", "medium", "-pix_fmt", "yuv420p"],
    )
    writer.send(None)
    nframes = int(TOTAL * FPS)
    for i in range(nframes):
        writer.send(np.asarray(frame_at(i / FPS, scenes, L), dtype=np.uint8).tobytes())
        if i % 150 == 0:
            print(f"{i}/{nframes} frames", flush=True)
    writer.close()

    ff = imageio_ffmpeg.get_ffmpeg_exe()
    subprocess.run([ff, "-y", "-i", silent, "-i", "output/audio/mix.wav",
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                    "-movflags", "+faststart", "-shortest", L["out"]],
                   check=True, capture_output=True)
    os.remove(silent)
    print(f"done: {L['out']} ({TOTAL:.1f}s, {nframes} frames)")


if __name__ == "__main__":
    main()
