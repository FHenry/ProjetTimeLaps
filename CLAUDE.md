# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Goal

A local web page that plays the `SpotRiviere/` photos as a timelapse:
- crossfade (fade-in/fade-out) between images, with adjustable timing
- a date slider to move through the images in chronological order
- upload of new images, which then appear in the timeline
- a Y-shaped tree branch (an upside-down Y) that is in almost every photo stays at the center of the frame, aligned from 2 clicks per photo, not automatically

The step-by-step plan and its open decisions are in `PLAN.md`. Check it, and update its status, before starting work.

## Project state

ProjetTimeLaps is meant to build a timelapse from repeated photos of one spot. The repository has **no code yet**: no build system, tests, README or git repo. It contains only source data:

- `SpotRiviere/`: 160 JPEGs (~595 MB) of the same river spot, taken between Jan 2021 and Nov 2026.

## Source data quirks (matter for any pipeline)

- **Two filename schemes, both encode capture time:**
  - `<13 digits>.jpg` (154 files): Unix epoch in **milliseconds** (e.g. `1609693047057` → 2021-01-03). Most of these have no usable EXIF camera model.
  - `IMG_YYYYMMDD_HHMMSSmmm.jpg` (6 files, Nov 2026): Fairphone (Gen. 6) photos.
  - Sort chronologically by the time parsed from the filename, not by filename string.
- **Mixed resolutions and aspect ratios:** 5184×2392, 6016×2776 (~2.17:1), 6016×4512 (4:3), 4208×3120 (4:3, Fairphone). Frames must be cropped/aligned to a common size and framing before they can be assembled. EXIF orientation is 1 (normal) on all files.
- Handheld shots from different devices: expect framing drift between frames, so registration/alignment will probably be needed.

## Environment

- `python3` with Pillow 12 and `ffmpeg`/`ffprobe` 8.0.1 (with libx264, libx265, libvpx, libsvtav1), `exiftool` 13.50 and ImageMagick 7.1.2 (`magick`; `convert`/`identify` also present) are available.
- Treat `SpotRiviere/` as original data: never modify or delete existing files in it. Only the upload feature adds new files there. Write processed frames and outputs to a separate directory.
