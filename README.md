# DroneShine Cleaning Services — Ad Assets

Instagram video ad builder for DroneShine Cleaning Services (droneshinecleaning.com).

## Contents

- `assets/` — source images (logo, before/after aerial photos, brand infographic) and
  fonts (Anton, Archivo — both SIL Open Font License)
- `scripts/build_ad.py` — renders the ad frame-by-frame with Pillow and encodes it
  with ffmpeg (via `imageio-ffmpeg`)
- `output/droneshine_reel.mp4` — 1080×1920 (Reels/Stories), 30 fps, 24.5 s, music only
- `output/droneshine_feed.mp4` — 1080×1350 (4:5 feed) version

## The ad

1. Three before → after wipe reveals (slider style) over the aerial photos, each with a
   brand-styled headline: "The Drone Difference", "Nobody On Your Roof",
   "Safer. Faster. Cheaper.", joined by film-dissolve transitions. Each scene
   carries three check-mark info bullets drawn from the brand one-pager
   (surface-safe pressure, deionized rinse, 0% damage risk, FAA Part 107,
   50-70% quicker, no lifts or scaffolds, eco-friendly options)
2. End card: the original logo (background keyed out, sharpened), "Statewide in
   Florida", services line (roofs / windows / solar / exteriors), CALL
   855-376-6392 pill, droneshinecleaning.com, trust line
3. Audio: no voiceover — a synthesized beat-driven track (120 bpm) carries the ad.
   Scene cuts land on bar lines, whooshes rise into each cut, and the arrangement
   builds with the scenes: pad intro, drums+bass at scene 2, claps at scene 3,
   wind-down under the end card

Brand colors sampled from the logo: background `#0E0E0E`, green `#4DAB55`.

## Rebuilding

```bash
pip install pillow numpy imageio-ffmpeg
python3 scripts/build_ad.py                 # 9:16 -> output/droneshine_reel.mp4
python3 scripts/build_ad.py --format 4x5    # 4:5  -> output/droneshine_feed.mp4
python3 scripts/build_ad.py --stills        # preview frames -> output/preview_*.png
```

Headlines, bullets, and scene order live in `make_scenes()`; timing constants sit
at the top of the script (scene cuts are aligned to music bars).
