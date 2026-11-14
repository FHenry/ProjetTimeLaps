# Development plan: SpotRiviere timelapse web page

Status: **step 2 built, waiting for the user's clicks** (last updated 2026-11-14)

## Resume here (where we stopped on 2026-11-14)

- All open decisions answered (2026-11-14). Step 1 done (2026-11-14). **Step 2 code written and tested (2026-11-14); next action: the user clicks the photos on `/align`, then generates the frames and checks them (step 2 check). Then step 3.**
- Step 2 code: `align.py` (transforms + rendering; `.venv/bin/python align.py [--force]` renders from the command line), `app.py` (Flask server), `static/align.html` (alignment page). Run `.venv/bin/python app.py`, open http://localhost:5000/align. Clicks are saved in `data/alignment.json` (user data, keep it); frames go to `cache/aligned/<id>.jpg`, and `cache/aligned/rendered.json` records the transform of each frame so only changed frames are re-rendered.
- Step 2 choices made while building: the reference angle is the circular mean of all clicked fork→point angles. The reference length comes from the shortest branch, scaled so that photo would cover the frame if its fork were centered. Skipped and not-yet-done photos reuse the clicks of the nearest aligned photo (before, else after), in relative coordinates. The page shows the previous aligned photo, zoomed on its branch, so point 2 is clicked on the same spot each time. Frames are generated only on demand (button or CLI), because each new click can change the reference and so every frame.
- Step 1 result: `catalog.py` (run `.venv/bin/python catalog.py`, add `--force` to rebuild every copy) writes `cache/catalog.json`, `cache/web/<id>.jpg` (1920 px wide) and `cache/thumb/<id>.jpg` (320 px). It only rebuilds missing or outdated copies. 160 photos, 2021-01-03 → 2026-11-13, all dated from the filename. Each entry has id, file, date, timestamp, date_source, original width/height, sha256, web/thumb paths and `duplicate_of`.
- 4 originals are byte-identical copies of earlier photos under later names (1614151643752, 1614151643757, 1616334649422, 1616334649423). They get `duplicate_of` set and must be skipped by the timeline and the alignment page, so 156 photos remain. The files stay in `SpotRiviere/`.
- Dev tooling (2026-11-14): git repo; `.pre-commit-config.yaml` runs a guard that blocks committing `SpotRiviere/`, `cache/` or `.venv/`, plus check-added-large-files (1 MB), json/toml/yaml checks and ruff (lint + format; settings in `pyproject.toml`). Setup: `.venv/bin/pip install -e ".[dev]" && .venv/bin/pre-commit install`. Possible next: pytest tests for the date parsing and the alignment math.
- Done so far: plan written; branch alignment added as step 2; tools installed (see below).
- Project venv `.venv/` has Flask 3.1.3 + Pillow 13.0.0. System tools: Python 3.14 + Pillow 12, `ffmpeg`/`ffprobe` 8.0.1 (libx264, libx265, libvpx, libsvtav1), `exiftool` 13.50, ImageMagick 7.1.2 (`magick`). Not installed: `numpy`, `opencv` (only needed for the optional point guessing in step 2), Flask is only in the venv.
- What a contact sheet of every 10th photo showed (basis for choosing manual alignment over automatic):
  - Framing and zoom vary a lot between visits: some shots are close-ups of the water, others wide views with a large ivy-covered trunk on the right.
  - Summer foliage hides most of the frame, and often the Y branch. In winter only bare branches show.
  - Some shots are dark (night / low light).
- Possible later extra: ffmpeg could also export the aligned frames as an MP4 timelapse (not in the steps yet).

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
Goal: the Y-shaped tree branch (an upside-down Y) stays at the exact center of every frame, at the same angle and size, so the crossfade doesn't jump.
Fully automatic alignment was ruled out: in summer the leaves hide the branch, the framing and zoom change a lot between visits, and night shots have little contrast.
- Alignment page (`/align`): shows one photo at a time. The user clicks **(1) the fork of the Y**, then **(2) a second point on the branch** (e.g. lower down its trunk). Keys: Enter = next, S = skip, Backspace = redo the clicks.
- From the 2 points, compute a similarity transform (shift X/Y, rotation, scale): the fork maps to the frame center, and the vector fork→point 2 maps to a fixed reference angle and length.
- Save the clicks (in original-pixel coordinates) to `alignment.json`, keyed by image id. Never touch the originals.
- Skipped photos (branch not visible) reuse the transform of the nearest aligned photo before them in time.
- Generate the aligned web copies from the originals with that transform (Pillow `Image.transform`, bicubic), into a fixed-size output frame. Areas outside the original photo are filled with a blurred, darkened copy of it (decision 4).
- Show which photos are still unaligned; allow re-opening any photo to fix its clicks.
- (Later, only if clicking feels slow) Suggest the 2 points from the previous aligned photo with OpenCV template matching, so the user just presses Enter. Needs `numpy` + `opencv-python-headless`, which are not installed.
- **Check:** step through the aligned frames; the fork stays on the center crosshair.

### 3. Player page (crossfade)
- Two stacked image layers with a CSS opacity transition; preload the next image.
- Controls: play/pause, **fade duration** slider, **time each image stays on screen** slider. Remember the settings in localStorage.

### 4. Date slider
- Slider over the timeline, showing the current date while dragging; dragging jumps to that image.
- Option: space images evenly on the slider, or space them by real time (shows gaps between visits).
- Left and right arrow keys step to the previous or next image.

### 5. Upload
- Drag-and-drop and a file picker, sent to the Flask endpoint.
- The server saves the original into `SpotRiviere/`, opens it on the alignment page for its 2 clicks, then generates its aligned web copy, updates the catalog, and the page refreshes the timeline.
- Reject files that aren't images and duplicates (based on a hash of the file contents).

## Open decisions (to answer before starting)

1. ~~Mixed sizes~~: superseded by decision 4 (the alignment defines a common output frame).
2. ~~Server~~ **Decided (2026-11-14):** Flask, installed in a project virtual environment `.venv/` (`python3 -m venv .venv && .venv/bin/pip install -e .`, dependencies listed in `pyproject.toml`). Nothing is installed in the system Python. Run with `.venv/bin/python app.py`.
3. ~~Is alignment in scope?~~ **Decided (2026-11-13):** yes, as the 2-click branch alignment in step 2.
4. ~~Output frame~~ **Decided (2026-11-14):** fixed 2560×1440 (16:9) frame, shown as large as the browser window allows. Photos are never enlarged: the smallest branch length (fork→point 2) among the aligned photos sets the reference size, so wide shots fill the frame and close-ups are shrunk and show as a smaller picture inside it. The fork stays at the frame center. The empty area around a photo is filled with a blurred, darkened copy of that photo. If a new upload has a smaller branch length than the reference, the reference changes and all aligned frames are regenerated.
