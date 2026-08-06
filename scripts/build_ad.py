"""Build the DroneShine Instagram video ad from the before/after photos.

Renders every frame with Pillow, pipes them to ffmpeg (imageio-ffmpeg), then
mixes a Piper voiceover with a synthesized music bed and muxes the audio in.

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
BG = (14, 14, 14)
GREEN = (77, 171, 85)
DARK_GREEN = (30, 77, 61)
WHITE = (245, 247, 245)
GRAY = (160, 168, 162)
RADIUS = 26
PHONE = "855-376-6392"
SITE = "DRONESHINECLEANING.COM"

ANTON = "assets/fonts/Anton-Regular.ttf"
ARCHIVO = "assets/fonts/Archivo.ttf"

LAYOUTS = {
    "9x16": dict(
        size=(1080, 1920), out="output/droneshine_reel.mp4",
        kicker=(34, 205), headline=(92, 320), sub=(46, 432),
        panel=1080, panel_xy=(0, 530), watermark=(30, 1712),
        outro=dict(icon_w=560, icon_y=290, word=(118, 700), tagline=(44, 812),
                   state=(76, 985), phone=(64, 1090), site=(42, 1330),
                   trust=(28, 1424)),
    ),
    "4x5": dict(
        size=(1080, 1350), out="output/droneshine_feed.mp4",
        kicker=(30, 118), headline=(74, 205), sub=(40, 298),
        panel=880, panel_xy=(100, 366), watermark=(27, 1298),
        outro=dict(icon_w=440, icon_y=120, word=(94, 448), tagline=(38, 538),
                   state=(60, 680), phone=(54, 768), site=(38, 968),
                   trust=(25, 1046)),
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


def build_logo_icon():
    """Vectorize the drone+roof icon from the 400px logo into a crisp RGBA image.

    The icon is flat two-color art, so we classify pixels into color masks,
    upscale the masks 6x, and re-threshold for smooth anti-aliased edges.
    """
    cache = "assets/logo_icon.png"
    if os.path.exists(cache):
        return Image.open(cache)
    src = np.asarray(Image.open("assets/logo.jpg").convert("RGB")).astype(int)
    icon = src[74:188]
    # classes: 0 = background, 1 = dark drone, 2 = bright roof/sparkle
    nonbg = np.abs(icon - 14).sum(axis=2) > 60
    bright = nonbg & (icon[:, :, 1] > 100)
    nearest = np.where(bright, 2, np.where(nonbg, 1, 0))
    # mode-filter the class map to kill JPEG speckle before masking
    cls = Image.fromarray(nearest.astype(np.uint8))
    for _ in range(2):
        cls = cls.filter(ImageFilter.ModeFilter(5))
    nearest = np.asarray(cls)
    up = 6
    layers = []
    for ci, color in ((1, DARK_GREEN), (2, GREEN)):
        mask = (nearest == ci).astype(np.float32)
        m = Image.fromarray((mask * 255).astype(np.uint8))
        m = m.resize((m.width * up, m.height * up), Image.BICUBIC)
        m = m.filter(ImageFilter.GaussianBlur(up * 0.7))
        m = m.point(lambda v: 255 if v > 127 else 0).filter(ImageFilter.GaussianBlur(1.2))
        layers.append((color, m))
    out = Image.new("RGBA", layers[0][1].size, (0, 0, 0, 0))
    for color, m in layers:
        solid = Image.new("RGBA", out.size, (*color, 255))
        out.paste(solid, (0, 0), m)
    out = out.crop(out.getbbox())
    out.save(cache)
    return out


class BeforeAfterScene:
    def __init__(self, path, headline, sub, dur, L):
        self.dur = dur
        self.headline = headline
        self.sub = sub
        self.L = L
        self.PANEL = L["panel"]
        src = Image.open(path).convert("RGB")
        half_w = src.width // 2
        before = src.crop((0, 0, half_w, src.height))
        after = src.crop((src.width - half_w, 0, src.width, src.height))
        big = int(self.PANEL * 1.10) + 4
        self.before = self._cover(before, big)
        self.after = self._cover(after, big)
        self.mask = rounded_mask((self.PANEL, self.PANEL), RADIUS)
        f_label = archivo(36 if self.PANEL >= 1000 else 32, 700)
        self.pill_before = pill("BEFORE", f_label, WHITE, (0, 0, 0, 165))
        self.pill_after = pill("AFTER", f_label, (10, 20, 10), (*GREEN, 235))

    @staticmethod
    def _cover(im, size):
        s = max(size / im.width, size / im.height)
        im = im.resize((round(im.width * s), round(im.height * s)), Image.LANCZOS)
        x = (im.width - size) // 2
        y = (im.height - size) // 2
        return im.crop((x, y, x + size, y + size))

    def _panel_view(self, im, zoom):
        view = int(round(im.width / zoom))
        off = (im.width - view) // 2
        return im.crop((off, off, off + view, off + view)).resize(
            (self.PANEL, self.PANEL), Image.LANCZOS)

    def render(self, t):
        L = self.L
        W, H = L["size"]
        P = self.PANEL
        px, py = L["panel_xy"]
        frame = Image.new("RGB", (W, H), BG)
        d = ImageDraw.Draw(frame)

        zoom = 1.02 + 0.07 * (t / self.dur)
        wipe_end = self.dur - 1.55
        wipe_t = smoothstep((t - 0.9) / (wipe_end - 0.9))
        wipe_x = int(wipe_t * P)

        panel = self._panel_view(self.before, zoom)
        if wipe_x > 0:
            after_view = self._panel_view(self.after, zoom)
            panel.paste(after_view.crop((0, 0, wipe_x, P)), (0, 0))
            if 0 < wipe_x < P:
                pd = ImageDraw.Draw(panel)
                pd.rectangle([wipe_x - 3, 0, wipe_x + 2, P], fill=(255, 255, 255))
                cy = P // 2
                pd.ellipse([wipe_x - 34, cy - 34, wipe_x + 34, cy + 34], fill=(255, 255, 255))
                ah = anton(30)
                pd.text((wipe_x - 15, cy), "‹", font=ah, fill=(20, 20, 20), anchor="mm")
                pd.text((wipe_x + 15, cy), "›", font=ah, fill=(20, 20, 20), anchor="mm")
        frame.paste(panel, (px, py), self.mask)

        lbl_y = py + 28
        b_alpha = 1.0 if wipe_t < 1 else max(0.0, 1 - (t - wipe_end - 0.05) / 0.3)
        if b_alpha > 0:
            p = faded(self.pill_before, b_alpha)
            frame.paste(p, (px + P - p.width - 28, lbl_y), p)
        a_alpha = smoothstep((wipe_x - 200) / 220) if wipe_x > 0 else 0.0
        if a_alpha > 0:
            p = faded(self.pill_after, a_alpha)
            frame.paste(p, (px + 28, lbl_y), p)

        ks, ky = L["kicker"]
        hs, hy = L["headline"]
        ss, sy = L["sub"]
        draw_tracked(d, (W / 2, ky), "DRONE SHINE", archivo(ks, 700), GREEN, tracking=10)
        d.text((W / 2, hy), self.headline, font=anton(hs), fill=WHITE, anchor="mm")
        d.text((W / 2, sy), self.sub, font=archivo(ss, 700), fill=GREEN, anchor="mm")

        ws, wy = L["watermark"]
        draw_tracked(d, (W / 2, wy), f"{SITE} • {PHONE}", archivo(ws, 600), GRAY, tracking=4)
        return frame


class OutroScene:
    def __init__(self, dur, L):
        self.dur = dur
        self.L = L
        O = L["outro"]
        icon = build_logo_icon()
        w = O["icon_w"]
        self.icon = icon.resize((w, round(icon.height * w / icon.width)), Image.LANCZOS)
        self.phone_pill = pill(f"CALL {PHONE}", anton(O["phone"][0]), (10, 20, 10),
                               (*GREEN, 255), pad_x=56, pad_y=24, tracking=3)

    def render(self, t):
        L = self.L
        W, H = L["size"]
        O = L["outro"]
        frame = Image.new("RGB", (W, H), BG)

        def fade(start, dur=0.5):
            return ease_out((t - start) / dur)

        # logo lockup: icon + wordmark + tagline
        a = fade(0.0, 0.6)
        if a > 0:
            lift = int((1 - a) * 40)
            icon = faded(self.icon, a)
            frame.paste(icon, ((W - icon.width) // 2, O["icon_y"] + lift), icon)
            d = ImageDraw.Draw(frame)
            ws_, wy_ = O["word"]
            c = tuple(int(BG[i] + (WHITE[i] - BG[i]) * a) for i in range(3))
            d.text((W / 2, wy_ + lift), "DroneShine", font=archivo(ws_, 800),
                   fill=c, anchor="mm")
            ts_, ty_ = O["tagline"]
            cg = tuple(int(BG[i] + (GREEN[i] - BG[i]) * a) for i in range(3))
            draw_tracked(d, (W / 2, ty_ + lift), "CLEANING SERVICES",
                         archivo(ts_, 600), cg, tracking=12)

        d = ImageDraw.Draw(frame)
        if fade(0.5) > 0:
            a2 = fade(0.5)
            c = tuple(int(BG[i] + (WHITE[i] - BG[i]) * a2) for i in range(3))
            ss_, sy_ = O["state"]
            d.text((W / 2, sy_), "STATEWIDE IN FLORIDA", font=anton(ss_), fill=c, anchor="mm")
        if fade(1.9) > 0:
            a3 = fade(1.9)
            p = faded(self.phone_pill, a3)
            pop = 1 + 0.08 * (1 - a3)
            pw, ph = int(p.width * pop), int(p.height * pop)
            p = p.resize((pw, ph), Image.LANCZOS)
            frame.paste(p, ((W - pw) // 2, O["phone"][1]), p)
            d = ImageDraw.Draw(frame)
        if fade(5.4) > 0:
            a4 = fade(5.4)
            c = tuple(int(BG[i] + (WHITE[i] - BG[i]) * a4) for i in range(3))
            draw_tracked(d, (W / 2, O["site"][1]), SITE,
                         archivo(O["site"][0], 700), c, tracking=6)
        if fade(6.4) > 0:
            a5 = fade(6.4)
            c = tuple(int(BG[i] + (GRAY[i] - BG[i]) * a5) for i in range(3))
            draw_tracked(d, (W / 2, O["trust"][1]),
                         "FREE QUOTES • FULLY INSURED • FAA CERTIFIED",
                         archivo(O["trust"][0], 600), c, tracking=3)
        return frame


# scene timing is shared by the video render and the audio mix
DURS = [5.7, 4.5, 4.0, 10.4]
XFADE = 0.45
STARTS = []
_t = 0.0
for _d in DURS:
    STARTS.append(_t)
    _t += _d - XFADE
TOTAL = STARTS[-1] + DURS[-1]

VO_CUES = [  # (wav name, start time)
    ("vo1", 0.35),
    ("vo2", STARTS[1] + 0.30),
    ("vo3", STARTS[2] + 0.35),
    ("vo4a", STARTS[3] + 0.30),
    ("vo4b", STARTS[3] + 2.00),
]


def make_scenes(L):
    return [
        BeforeAfterScene("assets/ba_lake_house.jpg",
                         "THE DRONE DIFFERENCE", "SOFT-WASH ROOF CLEANING", DURS[0], L),
        BeforeAfterScene("assets/ba_pool_house.jpg",
                         "NOBODY ON YOUR ROOF", "0% DAMAGE RISK", DURS[1], L),
        BeforeAfterScene("assets/ba_gray_roof.jpg",
                         "SAFER. FASTER. CHEAPER.", "50–70% QUICKER THAN CREWS", DURS[2], L),
        OutroScene(DURS[3], L),
    ]


def swipe(a_img, b_img, p, W, H):
    """Brand transition: angled green band sweeps across, revealing the next scene."""
    a = np.asarray(a_img, dtype=np.float32)
    b = np.asarray(b_img, dtype=np.float32)
    e = -420 + p * (W + 840)
    yy = np.arange(H, dtype=np.float32)[:, None]
    xx = np.arange(W, dtype=np.float32)[None, :]
    dist = xx + (yy - H / 2) * 0.21 - e
    out = np.where((dist < 0)[..., None], b, a)
    band = np.clip(1 - np.abs(dist) / 130.0, 0, 1) ** 1.6
    out = out * (1 - band[..., None] * 0.95) + np.array(GREEN, np.float32) * band[..., None] * 0.95
    return Image.fromarray(out.astype(np.uint8))


def frame_at(t, scenes, L):
    W, H = L["size"]
    active = [(s, t - st) for s, st in zip(scenes, STARTS) if st <= t < st + s.dur]
    if not active:
        return scenes[-1].render(scenes[-1].dur - 0.001)
    if len(active) == 1:
        return active[0][0].render(active[0][1])
    (s1, t1), (s2, t2) = active
    return swipe(s1.render(t1), s2.render(t2), smoothstep(t2 / XFADE), W, H)


# ---------------------------------------------------------------- audio

SR = 44100


def load_wav_resampled(path):
    with wave.open(path) as w:
        data = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
        data = data.astype(np.float32) / 32768.0
        src_sr = w.getframerate()
    t = np.arange(int(len(data) * SR / src_sr)) / SR
    return np.interp(t, np.arange(len(data)) / src_sr, data)


def synth_music(total):
    """Subtle upbeat bed: warm pad chords, soft bass, light hats and kick."""
    n = int(total * SR)
    t = np.arange(n) / SR
    music = np.zeros(n, dtype=np.float32)
    beat = 60 / 104
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
        env = np.minimum(st / 0.7, 1.0) * np.minimum((chord_len - st) / 0.7, 1.0)
        env = np.clip(env, 0, 1)
        seg = np.zeros(seg_n, dtype=np.float32)
        for f in tones:
            seg += 0.045 * np.sin(2 * np.pi * f * st) + 0.012 * np.sin(2 * np.pi * 2 * f * st)
        seg += 0.11 * np.sin(2 * np.pi * bass * st)
        i0 = int(start * SR)
        music[i0:i0 + seg_n] += (seg * env).astype(np.float32)
        start += chord_len
        ci += 1
    # hats on eighths, kick on beats 1 and 3
    rng = np.random.default_rng(7)
    bt = 0.0
    k = 0
    while bt < total - 0.2:
        if k % 2 == 0:
            i0 = int(bt * SR)
            kn = int(0.13 * SR)
            kt = np.arange(kn) / SR
            fr = 85 * np.exp(-kt * 14) + 45
            music[i0:i0 + kn] += 0.10 * np.sin(2 * np.pi * np.cumsum(fr) / SR) * np.exp(-kt * 22)
        for eighth in (0.0, 0.5):
            i0 = int((bt + eighth * beat) * SR)
            hn = int(0.03 * SR)
            if i0 + hn < n:
                noise = rng.standard_normal(hn).astype(np.float32)
                noise = np.diff(noise, prepend=0)  # brighten
                music[i0:i0 + hn] += 0.016 * noise * np.exp(-np.arange(hn) / SR * 90)
        bt += beat
        k += 1
    music *= np.clip(t / 0.6, 0, 1) * np.clip((total - t) / 1.4, 0, 1)
    return music


def build_audio():
    n = int(TOTAL * SR)
    vo = np.zeros(n, dtype=np.float32)
    speech = np.zeros(n, dtype=bool)
    for name, start in VO_CUES:
        clip = load_wav_resampled(f"output/audio/{name}.wav")
        i0 = int(start * SR)
        i1 = min(i0 + len(clip), n)
        vo[i0:i1] += clip[:i1 - i0]
        speech[i0:i1] = True
    music = synth_music(TOTAL)
    # duck music under speech with 0.15 s ramps
    duck = np.where(speech, 0.38, 1.0).astype(np.float32)
    kernel = np.ones(int(0.15 * SR), dtype=np.float32)
    kernel /= len(kernel)
    duck = np.convolve(duck, kernel, mode="same")
    mix = vo * 0.92 + music * 0.30 * duck
    peak = np.abs(mix).max()
    if peak > 0.98:
        mix *= 0.98 / peak
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
        for t in [0.4, 2.6, 5.4, 8.5, 13.4, 15.5, 20.5]:
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
        if i % 120 == 0:
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
