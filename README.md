# DroneShine Cleaning Services — Ad Assets

Instagram video ad builder for DroneShine Cleaning Services (droneshinecleaning.com).

## Contents

- `assets/` — source images (logo, before/after aerial photos, brand infographic) and
  fonts (Anton, Archivo — both SIL Open Font License)
- `scripts/build_ad.py` — renders the ad frame-by-frame with Pillow and encodes it
  with ffmpeg (via `imageio-ffmpeg`)
- `output/droneshine_reel.mp4` — final ad: 1080×1920 (Reels/Stories), 30 fps, 13.7 s

## The ad

1. Three before → after wipe reveals (slider style) over the aerial photos, each with a
   brand-styled headline: "The Drone Difference", "Nobody On Your Roof",
   "Safer. Faster. Cheaper."
2. End card: logo, "Statewide in Florida", Get A Free Quote button,
   droneshinecleaning.com

Brand colors sampled from the logo: background `#0E0E0E`, green `#4DAB55`.

## Rebuilding

```bash
pip install pillow numpy imageio-ffmpeg
python3 scripts/build_ad.py            # full render -> output/droneshine_reel.mp4
python3 scripts/build_ad.py --stills   # quick preview frames -> output/preview_*.png
```

Headlines, durations, and scene order are defined in the `SCENES` list at the bottom
of `scripts/build_ad.py`.
