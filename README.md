# DroneShine Cleaning Services — Ad Assets

Instagram video ad builder for DroneShine Cleaning Services (droneshinecleaning.com).

## Contents

- `assets/` — source images (logo, before/after aerial photos, brand infographic) and
  fonts (Anton, Archivo — both SIL Open Font License)
- `scripts/build_ad.py` — renders the ad frame-by-frame with Pillow and encodes it
  with ffmpeg (via `imageio-ffmpeg`)
- `output/droneshine_reel.mp4` — 1080×1920 (Reels/Stories), 30 fps, 23.2 s, with audio
- `output/droneshine_feed.mp4` — 1080×1350 (4:5 feed) version
- `output/audio/` — Piper TTS voiceover lines (the 120 MB voice model itself is
  gitignored; re-download from the rhasspy/piper v0.0.2 release to regenerate VO)

## The ad

1. Three before → after wipe reveals (slider style) over the aerial photos, each with a
   brand-styled headline: "The Drone Difference", "Nobody On Your Roof",
   "Safer. Faster. Cheaper.", joined by angled green swipe transitions
2. End card: re-vectorized hi-res logo, "Statewide in Florida", CALL 855-376-6392
   pill, droneshinecleaning.com, trust line
3. Audio: Piper neural voiceover (script mirrors the on-screen copy, ends with the
   phone number and website) over a synthesized music bed that ducks under speech

Brand colors sampled from the logo: background `#0E0E0E`, green `#4DAB55`.

## Rebuilding

```bash
pip install pillow numpy imageio-ffmpeg piper-tts
python3 scripts/build_ad.py                 # 9:16 -> output/droneshine_reel.mp4
python3 scripts/build_ad.py --format 4x5    # 4:5  -> output/droneshine_feed.mp4
python3 scripts/build_ad.py --stills        # preview frames -> output/preview_*.png
```

Headlines, durations, and scene order are defined in the `SCENES` list at the bottom
of `scripts/build_ad.py`.
