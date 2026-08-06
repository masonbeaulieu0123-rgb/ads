"""Build the DroneShine Instagram video ad from the before/after photos.

Renders every frame with Pillow, pipes them to ffmpeg (imageio-ffmpeg), then
mixes the Kokoro voiceover with a synthesized music bed and muxes the audio in.

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
import soundfile as sf
from PIL import Image, ImageDraw, ImageFilter, ImageFont

FPS = 30
BG_TOP = (19, 21, 20)
BG_BOT = (9, 10, 9)
GREEN = (77, 171, 85)
WHITE = (245, 247, 245)
SOFT = (178, 186, 180)     # sub-headline
GRAY = (140, 148, 142)     # watermark / trust line
PHONE = "855-376-6392"
SITE = "DRONESHINECLEANING.COM"

ANTON = "assets/fonts/Anton-Regular.ttf"
ARCHIVO = "assets/fonts/Archivo.ttf"

LAYOUTS = {
    "9x16": dict(
        size=(1080, 1920), out="output/droneshine_reel.mp4",
        kicker=(30, 228), headline=(84, 338), sub=(38, 448),
        panel=1000, panel_xy=(40, 550), radius=32, watermark=(27, 1748),
        outro=dict(logo_w=660, logo_y=320, state=(68, 1180), phone=(56, 1280),
                   site=(38, 1500), trust=(26, 1585)),
    ),
    "4x5": dict(
        size=(1080, 1350), out="output/droneshine_feed.mp4",
        kicker=(26, 120), headline=(66, 210), sub=(34, 302),
        panel=880, panel_xy=(100, 375), radius=28, watermark=(25, 1302),
        outro=dict(logo_w=460, logo_y=125, state=(56, 715), phone=(48, 800),
                   site=(34, 1000), trust=(23, 1068)),
    ),
}


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


def make_background(L):
    """Vertical gradient with a faint green glow behind the panel."""
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
    """Original logo art with its flat background keyed out, upscaled and sharpened."""
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


def vo_len(name):
    info = sf.info(f"output/audio/{name}.wav")
    return info.frames / info.samplerate


class BeforeAfterScene:
    def __init__(self, path, headline, sub, dur, L):
        self.dur = dur
        self.headline = headline
        self.sub = sub
        self.L = L
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
        f_label = archivo(29, 650)
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
        # sub-pixel affine sampling: smooth drift, no integer-crop jitter
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
        wipe_end = self.dur - 1.45
        wipe_t = smoothstep((t - 1.0) / (wipe_end - 1.0))
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

        ks, ky = L["kicker"]
        hs, hy = L["headline"]
        ss, sy = L["sub"]
        draw_tracked(d, (W / 2, ky), "DRONE SHINE", archivo(ks, 600), GREEN, tracking=14)
        d.text((W / 2, hy), self.headline, font=anton(hs), fill=WHITE, anchor="mm")
        draw_tracked(d, (W / 2, sy), self.sub, archivo(ss, 500), SOFT, tracking=2)

        ws, wy = L["watermark"]
        draw_tracked(d, (W / 2, wy), f"{SITE}  •  {PHONE}", archivo(ws, 550), GRAY,
                     tracking=4)
        return frame


class OutroScene:
    def __init__(self, dur, cues, L):
        self.dur = dur
        self.cues = cues  # dict: state, phone, site, trust (local seconds)
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
        c = self.cues

        def fade(start, dur=0.55):
            return ease_out((t - start) / dur)

        a = fade(0.0, 0.7)
        if a > 0:
            lift = int((1 - a) * 26)
            logo = self.logo if a >= 1 else faded(self.logo, a)
            frame.paste(logo, ((W - logo.width) // 2, O["logo_y"] + lift), logo)

        d = ImageDraw.Draw(frame)
        if fade(c["state"]) > 0:
            col = lerp_color(BG_BOT, WHITE, fade(c["state"]))
            ss_, sy_ = O["state"]
            d.text((W / 2, sy_), "STATEWIDE IN FLORIDA", font=anton(ss_),
                   fill=col, anchor="mm")
        if fade(c["phone"]) > 0:
            a3 = fade(c["phone"])
            p = faded(self.phone_pill, a3)
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
        return frame


# -------- timing: scene lengths follow the voiceover --------
V1, V2, V3, V4A, V4B = (vo_len(n) for n in ("vo1", "vo2", "vo3", "vo4a", "vo4b"))
DURS = [0.4 + V1 + 0.7, 0.4 + V2 + 0.6, 0.4 + V3 + 0.7,
        0.35 + V4A + 0.35 + V4B + 1.1]
XFADE = 0.5
STARTS = []
_t = 0.0
for _d in DURS:
    STARTS.append(_t)
    _t += _d - XFADE
TOTAL = STARTS[-1] + DURS[-1]

VO_CUES = [
    ("vo1", 0.40),
    ("vo2", STARTS[1] + 0.40),
    ("vo3", STARTS[2] + 0.40),
    ("vo4a", STARTS[3] + 0.35),
    ("vo4b", STARTS[3] + 0.35 + V4A + 0.35),
]
OUTRO_CUES = dict(
    state=0.35,
    phone=0.35 + V4A + 0.35,
    site=0.35 + V4A + 0.35 + V4B * 0.52,
    trust=0.35 + V4A + 0.35 + V4B * 0.75,
)


def make_scenes(L):
    return [
        BeforeAfterScene("assets/ba_lake_house.jpg",
                         "THE DRONE DIFFERENCE", "SOFT-WASH ROOF CLEANING", DURS[0], L),
        BeforeAfterScene("assets/ba_pool_house.jpg",
                         "NOBODY ON YOUR ROOF", "NO LADDERS • ZERO DAMAGE RISK", DURS[1], L),
        BeforeAfterScene("assets/ba_gray_roof.jpg",
                         "SAFER. FASTER. CHEAPER.", "50–70% QUICKER THAN CREWS", DURS[2], L),
        OutroScene(DURS[3], OUTRO_CUES, L),
    ]


def dissolve(a_img, b_img, p, W, H):
    """Film dissolve: incoming scene settles from a slight over-scale while fading in."""
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


def load_vo(name):
    data, src_sr = sf.read(f"output/audio/{name}.wav", dtype="float32")
    if data.ndim > 1:
        data = data.mean(axis=1)
    t = np.arange(int(len(data) * SR / src_sr)) / SR
    return np.interp(t, np.arange(len(data)) / src_sr, data).astype(np.float32)


def synth_music(total):
    """Understated bed: warm pad chords, soft bass, whisper-level hats."""
    n = int(total * SR)
    t = np.arange(n) / SR
    music = np.zeros(n, dtype=np.float32)
    beat = 60 / 100
    chord_len = beat * 8
    chords = [
        ([261.63, 329.63, 392.00, 493.88], 130.81),   # Cmaj7
        ([196.00, 246.94, 293.66, 392.00], 98.00),    # G
        ([220.00, 261.63, 329.63, 392.00], 110.00),   # Am7
        ([174.61, 220.00, 261.63, 349.23], 87.31),    # Fmaj7
    ]
    ci = 0
    start = 0.0
    while start < total:
        tones, bass = chords[ci % len(chords)]
        seg_n = min(int(chord_len * SR), n - int(start * SR))
        if seg_n <= 0:
            break
        st = np.arange(seg_n) / SR
        env = np.clip(np.minimum(st / 0.9, (chord_len - st) / 0.9), 0, 1)
        seg = np.zeros(seg_n, dtype=np.float32)
        for f in tones:
            seg += 0.040 * np.sin(2 * np.pi * f * st) + 0.010 * np.sin(2 * np.pi * 2 * f * st)
        seg += 0.10 * np.sin(2 * np.pi * bass * st)
        i0 = int(start * SR)
        music[i0:i0 + seg_n] += (seg * env).astype(np.float32)
        start += chord_len
        ci += 1
    rng = np.random.default_rng(7)
    bt = 0.0
    k = 0
    while bt < total - 0.2:
        if k % 2 == 0:
            i0 = int(bt * SR)
            kn = int(0.12 * SR)
            kt = np.arange(kn) / SR
            fr = 82 * np.exp(-kt * 14) + 44
            music[i0:i0 + kn] += 0.055 * np.sin(2 * np.pi * np.cumsum(fr) / SR) * np.exp(-kt * 24)
        for eighth in (0.0, 0.5):
            i0 = int((bt + eighth * beat) * SR)
            hn = int(0.03 * SR)
            if i0 + hn < n:
                noise = rng.standard_normal(hn).astype(np.float32)
                noise = np.diff(noise, prepend=0)
                music[i0:i0 + hn] += 0.008 * noise * np.exp(-np.arange(hn) / SR * 90)
        bt += beat
        k += 1
    music *= np.clip(t / 0.8, 0, 1) * np.clip((total - t) / 1.6, 0, 1)
    return music


def build_audio():
    n = int(TOTAL * SR)
    vo = np.zeros(n, dtype=np.float32)
    speech = np.zeros(n, dtype=bool)
    for name, start in VO_CUES:
        clip = load_vo(name)
        edge = int(0.012 * SR)
        clip[:edge] *= np.linspace(0, 1, edge)
        clip[-edge:] *= np.linspace(1, 0, edge)
        i0 = int(start * SR)
        i1 = min(i0 + len(clip), n)
        vo[i0:i1] += clip[:i1 - i0]
        speech[i0:i1] = True
    music = synth_music(TOTAL)
    duck = np.where(speech, 0.34, 1.0).astype(np.float32)
    kernel = np.ones(int(0.18 * SR), dtype=np.float32)
    kernel /= len(kernel)
    duck = np.convolve(duck, kernel, mode="same")
    mix = vo * 0.90 + music * 0.24 * duck
    peak = np.abs(mix).max()
    if peak > 0.97:
        mix *= 0.97 / peak
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
        probes = [0.5, DURS[0] * 0.55, STARTS[1] + 0.2, STARTS[2] + DURS[2] * 0.6,
                  STARTS[3] + 1.2, STARTS[3] + OUTRO_CUES["phone"] + 0.8, TOTAL - 1.0]
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
