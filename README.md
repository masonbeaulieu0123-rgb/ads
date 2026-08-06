# DroneShine Cleaning Services — Ad Assets

Instagram video ad builder for DroneShine Cleaning Services (droneshinecleaning.com).

## Contents

- `assets/` — source images (logo, before/after aerial photos, brand infographic) and
  fonts (Anton, Archivo — both SIL Open Font License)
- `scripts/build_ad.py` — renders the ad frame-by-frame with Pillow and encodes it
  with ffmpeg (via `imageio-ffmpeg`)
- `output/droneshine_reel.mp4` — 1080×1920 (Reels/Stories), 30 fps, 27.3 s, with audio
- `output/droneshine_feed.mp4` — 1080×1350 (4:5 feed) version
- `output/audio/` — Kokoro TTS voiceover lines (the ~350 MB Kokoro model files are
  gitignored; re-download from the thewh1teagle/kokoro-onnx model-files release)

## The ad

1. Three before → after wipe reveals (slider style) over the aerial photos, each with a
   brand-styled headline: "The Drone Difference", "Nobody On Your Roof",
   "Safer. Faster. Cheaper.", joined by film-dissolve transitions
2. End card: the original logo (background keyed out, sharpened), "Statewide in
   Florida", CALL 855-376-6392 pill, droneshinecleaning.com, trust line
3. Audio: Kokoro neural voiceover (am_michael; script mirrors the on-screen copy and
   ends with the phone number and website) over a synthesized bed that ducks under
   speech. Scene durations are derived from the voiceover line lengths

Brand colors sampled from the logo: background `#0E0E0E`, green `#4DAB55`.

## Rebuilding

```bash
pip install pillow numpy imageio-ffmpeg kokoro-onnx soundfile
python3 scripts/build_ad.py                 # 9:16 -> output/droneshine_reel.mp4
python3 scripts/build_ad.py --format 4x5    # 4:5  -> output/droneshine_feed.mp4
python3 scripts/build_ad.py --stills        # preview frames -> output/preview_*.png
```

Headlines and scene order live in `make_scenes()`; scene durations follow the
voiceover lengths automatically.
