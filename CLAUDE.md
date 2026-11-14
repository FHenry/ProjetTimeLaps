# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Goal

A local web page that plays the `SpotRiviere/` photos as a timelapse:
- crossfade (fade-in/fade-out) between images, with adjustable timing
- a date slider to move through the images in chronological order
- upload of new images, which then appear in the timeline
- a Y-shaped tree branch (an upside-down Y) that is in almost every photo stays at the center of the frame, aligned from 2 clicks per photo, not automatically

The step-by-step plan, the decisions made, and the "Resume here" notes are in `PLAN.md`. Check it, and update its status, before starting work.

## Project state

Steps 1 (catalog + web copies) and 2 (alignment, all photos clicked and frames rendered) of `PLAN.md` are done. Step 3 (player) is built. Steps 4-5 (date slider, upload) are not started. No tests yet.

## Commands

All Python runs in the project venv `.venv/`. Never install packages into the system Python.

```
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"   # setup (deps in pyproject.toml)
.venv/bin/pre-commit install                                  # once, enables the git hook
.venv/bin/python catalog.py [--force]   # step 1: cache/catalog.json + web copies/thumbnails
.venv/bin/python align.py [--force]     # step 2: render aligned frames from data/alignment.json
.venv/bin/python app.py                 # server: http://localhost:5000/ (player), /align
.venv/bin/pre-commit run --all-files    # guard + json/toml/yaml checks + ruff lint/format
```

## Architecture

- `catalog.py`: reads `SpotRiviere/`, writes `cache/catalog.json` (sorted by capture time), `cache/web/<id>.jpg` (1920 px wide) and `cache/thumb/<id>.jpg` (320 px). The id is the filename stem. Only missing or outdated copies are rebuilt. Byte-identical files get `duplicate_of` set (4 today), and everything downstream skips them through `align.timeline()`.
- `align.py`: the user's clicks live in `data/alignment.json` (original-pixel coordinates; `{"fork","point"}` or `{"skip": true}`). `compute_transforms()` derives each photo's similarity transform. Reference angle = circular mean of the clicked angles. Reference length = the shortest branch (widest shot) shown at `MAX_SCALE` = 1.0 output px per original px, so no photo is ever shown above its real resolution; wide shots extend past the frame edges. Unclicked or skipped photos reuse the nearest aligned photo's clicks. `render_all()` writes 2560x1440 frames to `cache/aligned/` with a blurred, darkened copy of the photo behind; `cache/aligned/rendered.json` records the transform of each frame so only changed frames are re-rendered. Rendering is on demand, because one new click can change the reference and so every frame.
- `app.py`: Flask. Serves `static/player.html` at `/`, `static/align.html` at `/align`, `/cache/...`, and JSON APIs: `GET /api/catalog`, `GET /api/frames` (rendered frames, mtime-versioned URLs cached as immutable), `GET /api/alignment`, `PUT /api/alignment/<id>` (body: fork+point, `skip`, or `reset`), `POST/GET /api/render` (render runs in a background thread).
- `static/align.html`: a single page with inline JS/CSS: click the fork, then point 2, with a loupe and a reference panel showing the previous aligned photo's marks. Keyboard-driven (Enter, S, Backspace, Del, arrows, N, V).
- `static/player.html`: the timelapse player. Two stacked `<img>` layers; the incoming one fades in on top. Settings are kept in localStorage (`player.settings`).
- Front-end gotcha: never wait on `img.decode()` alone. It never finished in headless Chromium and froze the player; use the `ready()` helper in `player.html` (load event, then decode with a time limit).

## Data and git rules

- `data/alignment.json` is the user's manual work and cannot be regenerated: never delete or overwrite it, and keep it in git. Everything in `cache/` can be rebuilt.
- `SpotRiviere/`, `cache/`, `.venv/` and `*.egg-info/` are git-ignored. A pre-commit guard also refuses them, and check-added-large-files blocks anything over 1 MB.

## Source data quirks (matter for any pipeline)

- **Two filename schemes, both encode capture time:**
  - `<13 digits>.jpg` (154 files): Unix epoch in **milliseconds** (e.g. `1609693047057` → 2021-01-03). Most of these have no usable EXIF camera model.
  - `IMG_YYYYMMDD_HHMMSSmmm.jpg` (6 files, Nov 2026): Fairphone (Gen. 6) photos.
  - Sort chronologically by the time parsed from the filename, not by filename string.
- **Mixed resolutions and aspect ratios:** 5184×2392, 6016×2776 (~2.17:1), 6016×4512 (4:3), 4208×3120 (4:3, Fairphone). Frames must be cropped/aligned to a common size and framing before they can be assembled. EXIF orientation is 1 (normal) on all files.
- Handheld shots from different devices: framing and zoom drift a lot between visits, and summer foliage often hides the branch. That is why alignment is manual (2 clicks), not automatic.
- 4 files are byte-identical re-saves of earlier photos under later epoch names (marked `duplicate_of` in the catalog), so 156 photos are in the timeline.

## Environment

- Project venv `.venv/`: Flask, Pillow 13, plus pre-commit and ruff (the `dev` extra). Optional `suggest` extra: numpy + opencv-python-headless (not installed).
- System: `python3` 3.14 with Pillow 12, and `ffmpeg`/`ffprobe` 8.0.1 (with libx264, libx265, libvpx, libsvtav1), `exiftool` 13.50 and ImageMagick 7.1.2 (`magick`; `convert`/`identify` also present) are available.
- Treat `SpotRiviere/` as original data: never modify or delete existing files in it. Only the upload feature adds new files there. Write processed frames and outputs to a separate directory.
