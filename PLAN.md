# Development plan: SpotRiviere timelapse web page

Status: **steps 1-4 done; next: step 5 (upload)** (last updated 2026-11-14)

## Resume here (where we stopped on 2026-11-14)

**Steps 1-4 are done and committed. Next action: step 5 (upload).**

- Start: `.venv/bin/python app.py` → http://localhost:5000/ (player with date slider), http://localhost:5000/align (alignment).
- State on 2026-11-14:
  - 156 photos in the timeline (160 files minus 4 byte-identical duplicates, which are marked `duplicate_of`).
  - 155 aligned, 1 skipped (#124, 2024-10-18 night shot); all 156 frames rendered and checked.
  - Clicks are in `data/alignment.json`, which is in git.
- Last change (2026-11-14): the fork sits at (1280, 450), 270 frame px above the center (`FORK_RAISE` in `align.py`). Frames were re-rendered and checked, and are ~95% covered on average. The user wanted to see it in the player; its commit may still be pending (check `git status`).
- Optional touch-ups: #90 (2023-11-22, 1700632809351) and #104 (2024-03-12, 1710267052026) have the fork ~40-50 px off its target (dusk/night shots). Re-click them on `/align` if they jump in the player.
- Notes for step 5 (upload):
  - Reuse `catalog.process()` for the web copy, thumbnail, date (filename → EXIF → file time) and sha256. Reject an upload whose sha256 is already in the catalog.
  - Save into `SpotRiviere/` under the original name. Never overwrite: add a suffix if the name exists.
  - Then open `/align` on the new photo. After its 2 clicks, re-render; `render_all()` only rebuilds what changed. Every frame is rebuilt if the new photo becomes the widest shot (new reference length) or shifts the mean angle.
  - `catalog.build()` currently re-reads every file. That is fine at this size (~5 s), but an incremental add would be nicer.
- Possible extras, not planned yet: MP4 export of the frames with ffmpeg; pytest tests for date parsing and the alignment math.

### Code map
- `catalog.py` (step 1): `cache/catalog.json`, `cache/web/` (1920 px), `cache/thumb/` (320 px). Rebuilds only missing or outdated copies; `--force` rebuilds all.
- `align.py` (step 2): transforms from `data/alignment.json`, renders `cache/aligned/<id>.jpg`. `cache/aligned/rendered.json` stores each frame's transform, so only changed frames are re-rendered; `--force` renders all.
  - Reference angle: circular mean of the clicked angles.
  - Reference length: the shortest branch at `MAX_SCALE` = 1.0, so no photo is shown above its real resolution.
  - Skipped photos reuse the nearest aligned photo's clicks.
- `app.py`: Flask server, pages and JSON APIs (see `CLAUDE.md`).
- `static/align.html` (step 2), `static/player.html` (steps 3-4).
- Dev tooling: `pyproject.toml` (deps; `dev` and `suggest` extras; ruff settings), `.pre-commit-config.yaml` (guard against committing photos/cache/venv, 1 MB limit, json/toml/yaml, ruff).

### Background
- Environment: the project venv `.venv/` has Flask 3.1, Pillow 13, pre-commit and ruff. System: Python 3.14, ffmpeg 8, exiftool, ImageMagick 7, Chromium (snap) for headless page tests. numpy and opencv are not installed.
- Why alignment is manual: framing and zoom vary a lot between visits, summer foliage often hides the Y branch, and some shots are dark (night / low light).

## Constraints driving the design

- Uploads must write to disk, so a page opened with `file://` is not enough. A small local server is needed.
  Proposed: **Python + Flask** (single `app.py`, image processing with Pillow, which is already installed).
  Run: `.venv/bin/python app.py` → `http://localhost:5000` (Flask + Pillow live in the project venv `.venv/`, not in the system Python).
- Originals are 5–6K px and about 4 MB each. The browser must never load them. Serve cached web copies instead.

## Steps

### 1. Catalog + web copies (Python)
- Parse the capture date from the filename (`<epoch ms>.jpg` or `IMG_YYYYMMDD_HHMMSSmmm.jpg`). For uploads, fall back to the EXIF `DateTimeOriginal`, then to the upload time.
- Write a sorted `catalog.json` (id, original filename, date, web copy path, thumbnail path).
- Generate a web copy (~1920 px wide, high-quality JPEG) and a small thumbnail for each image, into a separate cache folder.
- These first web copies are unaligned and used by the alignment page; the final frames come from step 2.
- Never modify or delete originals.
- **Check:** dates are correctly ordered and the web copies look right. **Done 2026-11-14:** order verified and a contact sheet shows the seasons in sequence.

### 2. Branch alignment (2 clicks per photo)
Goal: the Y-shaped tree branch (an upside-down Y) stays at the exact center of every frame, at the same angle and size, so the crossfade doesn't jump. (Later moved 270 px above the center; see decision 4.)
Fully automatic alignment was ruled out: in summer the leaves hide the branch, the framing and zoom change a lot between visits, and night shots have little contrast.
- Alignment page (`/align`): shows one photo at a time. The user clicks **(1) the fork of the Y**, then **(2) a second point on the branch** (e.g. lower down its trunk). Keys: Enter = next, S = skip, Backspace = redo the clicks.
- From the 2 points, compute a similarity transform (shift X/Y, rotation, scale): the fork maps to the frame center, and the vector fork→point 2 maps to a fixed reference angle and length.
- Save the clicks (in original-pixel coordinates) to `alignment.json`, keyed by image id. Never touch the originals.
- Skipped photos (branch not visible) reuse the transform of the nearest aligned photo before them in time.
- Generate the aligned web copies from the originals with that transform (Pillow `Image.transform`, bicubic), into a fixed-size output frame. Areas outside the original photo are filled with a blurred, darkened copy of it (decision 4).
- Show which photos are still unaligned; allow re-opening any photo to fix its clicks.
- (Later, only if clicking feels slow) Suggest the 2 points from the previous aligned photo with OpenCV template matching, so the user just presses Enter. Needs `numpy` + `opencv-python-headless`, which are not installed.
- **Check:** step through the aligned frames; the fork stays on the center crosshair. **Done 2026-11-14** with a contact sheet of every frame's center.

### 3. Player page (crossfade)
- Two stacked image layers with a CSS opacity transition; preload the next image.
- Controls: play/pause, **fade duration** slider, **time each image stays on screen** slider. Remember the settings in localStorage.
- **Built 2026-11-14:** `static/player.html`, served at `/`; frames come from `GET /api/frames` (timeline photos with a rendered frame, URL versioned by mtime so the browser caches them). The incoming frame fades in on top of the outgoing one, which stays opaque, so there is no brightness dip mid-fade. Fade 0-5 s and hold 0-10 s (defaults 0.8 s / 0.7 s), loop on/off, full screen, date overlay; keys Space / F / D / L; click the image to play or pause; the controls hide while playing; `?autoplay` starts playing on load. 4 frames are preloaded ahead.

### 4. Date slider
- Slider over the timeline, showing the current date while dragging; dragging jumps to that image.
- Option: space images evenly on the slider, or space them by real time (shows gaps between visits).
- Left and right arrow keys step to the previous or next image.
- **Built 2026-11-14** in `static/player.html`: a range input laid over a strip of ticks (one per photo) with year labels. A date bubble follows the handle while dragging, and dragging shows the photo at once (no fade). Playback pauses during a drag and resumes after. The "Spacing" select (even / real time) is saved in localStorage; real time snaps to the nearest photo and shows the gaps between visits (e.g. most of 2025). Keys: ← → (also ↑ ↓), Home, End, with a short fade (≤ 0.25 s). Fast repeated presses add up, because steps count from the last requested frame (`target`), not from the frame on screen (`cur`).

### 5. Upload
- Drag-and-drop and a file picker, sent to the Flask endpoint.
- The server saves the original into `SpotRiviere/`, opens it on the alignment page for its 2 clicks, then generates its aligned web copy, updates the catalog, and the page refreshes the timeline.
- Reject files that aren't images and duplicates (based on a hash of the file contents).

## Open decisions (to answer before starting)

1. ~~Mixed sizes~~: superseded by decision 4 (the alignment defines a common output frame).
2. ~~Server~~ **Decided (2026-11-14):** Flask, installed in a project virtual environment `.venv/` (`python3 -m venv .venv && .venv/bin/pip install -e .`, dependencies listed in `pyproject.toml`). Nothing is installed in the system Python. Run with `.venv/bin/python app.py`.
3. ~~Is alignment in scope?~~ **Decided (2026-11-13):** yes, as the 2-click branch alignment in step 2.
4. ~~Output frame~~ **Decided (2026-11-14), revised the same day after seeing the frames:** fixed 2560×1440 (16:9) frame, shown as large as the browser window allows. No photo is ever shown above its real resolution: the widest shot (shortest branch fork→point 2) is shown at 1 output px per original px (`MAX_SCALE = 1.0` in `align.py`), and every other photo is smaller. Wide shots extend past the frame edges and lose their borders. The first version scaled the widest shot to just cover the frame; photos then covered only ~46% of the frame on average, against ~81% now. **Also 2026-11-14:** the fork sits 270 frame px above the frame center, at (1280, 450) (`FORK_RAISE` in `align.py`; about 200 screen px on a full-screen 1080p display). The user asked for this, and it pushes most of the photo into view: about 95% of the frame is covered on average, and 83/156 frames are ≥ 90% covered. The fork stays at the frame center. The empty area around a photo is filled with a blurred, darkened copy of that photo. If a new upload has a smaller branch length than the reference, the reference changes and all aligned frames are regenerated.
