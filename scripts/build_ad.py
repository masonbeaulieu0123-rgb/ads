"""Build the DroneShine Instagram Reels ad (1080x1920) from the before/after photos.

Renders every frame with Pillow and pipes them to ffmpeg (via imageio-ffmpeg).
Usage:
    python3 scripts/build_ad.py            # full render -> output/droneshine_reel.mp4
    python3 scripts/build_ad.py --stills   # save preview frames -> output/preview_*.png
"""

import sys
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 1080, 1920
FPS = 30
BG = (14, 14, 14)
GREEN = (77, 171, 85)
WHITE = (245, 247, 245)
GRAY = (160, 168, 162)

PANEL = 1080          # before/after panel is full-width square
PANEL_Y = 530
RADIUS = 26

ANTON = "assets/fonts/Anton-Regular.ttf"
ARCHIVO = "assets/fonts/Archivo.ttf"

def anton(size):
    return ImageFont.truetype(ANTON, size)

def archivo(size, weight=600):
    f = ImageFont.truetype(ARCHIVO, size)
    f.set_variation_by_axes([100, weight])
    return f

def smoothstep(t):
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)

def ease_out(t):
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) ** 3

def draw_tracked(draw, xy, text, font, fill, tracking=0, anchor_center=True):
    """Draw text with letterspacing; xy is the center point when anchor_center."""
    widths = [draw.textlength(ch, font=font) for ch in text]
    total = sum(widths) + tracking * (len(text) - 1)
    x = xy[0] - total / 2 if anchor_center else xy[0]
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
    th = asc + desc
    im = Image.new("RGBA", (int(tw) + pad_x * 2, th + pad_y * 2), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([0, 0, im.width - 1, im.height - 1], im.height // 2, fill=bg)
    draw_tracked(d, (im.width / 2, im.height / 2), text, font, fg, tracking)
    return im


class BeforeAfterScene:
    def __init__(self, path, headline, sub, dur):
        self.dur = dur
        self.headline = headline
        self.sub = sub
        src = Image.open(path).convert("RGB")
        half_w = src.width // 2
        before = src.crop((0, 0, half_w, src.height))
        after = src.crop((src.width - half_w, 0, src.width, src.height))
        # pre-scale both halves to cover the panel with headroom for the zoom
        zoom_max = 1.10
        big = int(PANEL * zoom_max) + 4
        self.before = self._cover(before, big)
        self.after = self._cover(after, big)
        self.mask = rounded_mask((PANEL, PANEL), RADIUS)
        f_label = archivo(36, 700)
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
        return im.crop((off, off, off + view, off + view)).resize((PANEL, PANEL), Image.LANCZOS)

    def render(self, t):
        frame = Image.new("RGB", (W, H), BG)
        d = ImageDraw.Draw(frame)

        zoom = 1.02 + 0.07 * (t / self.dur)
        wipe_t = smoothstep((t - 0.9) / 1.15)
        wipe_x = int(wipe_t * PANEL)

        panel = self._panel_view(self.before, zoom)
        if wipe_x > 0:
            after_view = self._panel_view(self.after, zoom)
            panel.paste(after_view.crop((0, 0, wipe_x, PANEL)), (0, 0))
            if 0 < wipe_x < PANEL:
                pd = ImageDraw.Draw(panel)
                pd.rectangle([wipe_x - 3, 0, wipe_x + 2, PANEL], fill=(255, 255, 255))
                cy = PANEL // 2
                pd.ellipse([wipe_x - 34, cy - 34, wipe_x + 34, cy + 34],
                           fill=(255, 255, 255, 255))
                ad = ImageDraw.Draw(panel)
                ah = anton(30)
                ad.text((wipe_x - 15, cy), "‹", font=ah, fill=(20, 20, 20), anchor="mm")
                ad.text((wipe_x + 15, cy), "›", font=ah, fill=(20, 20, 20), anchor="mm")
        frame.paste(panel, (0, PANEL_Y), self.mask)

        # labels
        lbl_y = PANEL_Y + 28
        b_alpha = 1.0 if wipe_t < 1 else max(0.0, 1 - (t - 2.05) / 0.3)
        if b_alpha > 0:
            p = self.pill_before.copy()
            p.putalpha(p.getchannel("A").point(lambda a: int(a * b_alpha)))
            frame.paste(p, (PANEL - p.width - 28, lbl_y), p)
        a_alpha = smoothstep((wipe_x - 200) / 220) if wipe_x > 0 else 0.0
        if a_alpha > 0:
            p = self.pill_after.copy()
            p.putalpha(p.getchannel("A").point(lambda a: int(a * a_alpha)))
            frame.paste(p, (28, lbl_y), p)

        # header text
        draw_tracked(d, (W / 2, 205), "DRONE SHINE", archivo(34, 700), GREEN, tracking=10)
        d.text((W / 2, 320), self.headline, font=anton(92), fill=WHITE, anchor="mm")
        d.text((W / 2, 432), self.sub, font=archivo(46, 700), fill=GREEN, anchor="mm")

        # footer watermark
        draw_tracked(d, (W / 2, 1712), "DRONESHINECLEANING.COM",
                     archivo(34, 600), GRAY, tracking=6)
        return frame


class OutroScene:
    def __init__(self, dur):
        self.dur = dur
        logo = Image.open("assets/logo.jpg").convert("RGB")
        self.logo = logo.resize((680, 680), Image.LANCZOS)

    def render(self, t):
        frame = Image.new("RGB", (W, H), BG)
        d = ImageDraw.Draw(frame)

        def fade(start, dur=0.45):
            return ease_out((t - start) / dur)

        a = fade(0.0)
        if a > 0:
            z = 1.0 + 0.05 * (t / self.dur)
            size = int(680 * z)
            logo = self.logo.resize((size, size), Image.LANCZOS)
            im = Image.new("RGB", (W, H), BG)
            im.paste(logo, ((W - size) // 2, 330 + (680 - size) // 2))
            frame = Image.blend(frame, im, a)
            d = ImageDraw.Draw(frame)

        if fade(0.5) > 0:
            c = tuple(int(BG[i] + (WHITE[i] - BG[i]) * fade(0.5)) for i in range(3))
            d.text((W / 2, 1160), "STATEWIDE IN FLORIDA", font=anton(84), fill=c, anchor="mm")
        if fade(0.85) > 0:
            al = fade(0.85)
            btn = pill("GET A FREE QUOTE", archivo(46, 700), (10, 20, 10),
                       (*GREEN, int(255 * al)), pad_x=54, pad_y=26, tracking=3)
            frame.paste(btn, ((W - btn.width) // 2, 1268), btn)
            d = ImageDraw.Draw(frame)
        if fade(1.2) > 0:
            c = tuple(int(BG[i] + (WHITE[i] - BG[i]) * fade(1.2)) for i in range(3))
            draw_tracked(d, (W / 2, 1478), "DRONESHINECLEANING.COM",
                         archivo(40, 600), c, tracking=6)
        return frame


SCENES = [
    BeforeAfterScene("assets/ba_lake_house.jpg",
                     "THE DRONE DIFFERENCE", "SOFT-WASH ROOF CLEANING", 3.6),
    BeforeAfterScene("assets/ba_pool_house.jpg",
                     "NOBODY ON YOUR ROOF", "0% DAMAGE RISK", 3.4),
    BeforeAfterScene("assets/ba_gray_roof.jpg",
                     "SAFER. FASTER. CHEAPER.", "50–70% QUICKER THAN CREWS", 3.4),
    OutroScene(4.2),
]
XFADE = 0.3

starts = []
t0 = 0.0
for s in SCENES:
    starts.append(t0)
    t0 += s.dur - XFADE
TOTAL = starts[-1] + SCENES[-1].dur


def frame_at(t):
    active = []
    for s, st in zip(SCENES, starts):
        if st <= t < st + s.dur:
            active.append((s, t - st, st))
    if not active:
        return SCENES[-1].render(SCENES[-1].dur - 0.001)
    if len(active) == 1:
        return active[0][0].render(active[0][1])
    # crossfade: second scene fades in over the first
    (s1, t1, _), (s2, t2, st2) = active
    mix = smoothstep(t2 / XFADE)
    a = np.asarray(s1.render(t1), dtype=np.float32)
    b = np.asarray(s2.render(t2), dtype=np.float32)
    return Image.fromarray((a * (1 - mix) + b * mix).astype(np.uint8))


def main():
    if "--stills" in sys.argv:
        for t in [0.4, 1.5, 2.6, 4.8, 8.5, 12.9]:
            frame_at(t).save(f"output/preview_{t:04.1f}s.png")
        print("stills saved")
        return

    import imageio_ffmpeg
    n = int(TOTAL * FPS)
    writer = imageio_ffmpeg.write_frames(
        "output/droneshine_reel.mp4", (W, H), fps=FPS, codec="libx264",
        macro_block_size=1,
        output_params=["-crf", "19", "-preset", "medium", "-pix_fmt", "yuv420p",
                       "-movflags", "+faststart"],
    )
    writer.send(None)
    for i in range(n):
        writer.send(np.asarray(frame_at(i / FPS), dtype=np.uint8).tobytes())
        if i % 60 == 0:
            print(f"{i}/{n} frames", flush=True)
    writer.close()
    print(f"done: {TOTAL:.1f}s, {n} frames")


if __name__ == "__main__":
    main()
