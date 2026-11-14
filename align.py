"""Step 2: branch alignment from 2 clicks per photo.

data/alignment.json holds the user's clicks, keyed by photo id, in ORIGINAL pixels:
  {"<id>": {"fork": [x, y], "point": [x, y]}}   aligned
  {"<id>": {"skip": true}}                       branch not visible
Photos with no entry are still to do.

Rendering (decision 4 in PLAN.md): fixed 2560x1440 frame, fork at the center,
the vector fork->point rotated to the reference angle (circular mean over all
aligned photos) and scaled to the reference length. The reference length comes
from the photo with the SHORTEST branch (widest shot), scaled so that photo
covers the frame; every other photo is shrunk, never enlarged relative to it.
The empty area is filled with a blurred, darkened copy of the photo.

Run: .venv/bin/python align.py          (render frames whose transform changed)
     .venv/bin/python align.py --force  (render every frame)
"""

import json
import math
import sys
import threading
from concurrent.futures import ProcessPoolExecutor

from PIL import Image, ImageEnhance, ImageFilter, ImageOps

from catalog import CACHE_DIR, CATALOG_PATH, ROOT, SOURCE_DIR

DATA_DIR = ROOT / "data"
ALIGNMENT_PATH = DATA_DIR / "alignment.json"
ALIGNED_DIR = CACHE_DIR / "aligned"
RENDERED_PATH = ALIGNED_DIR / "rendered.json"  # transform used for each frame

FRAME_W, FRAME_H = 2560, 1440
BG_DARKEN = 0.45
BG_BLUR = 12  # px, applied on a 1/8 size copy

_lock = threading.Lock()


# ---------- storage ----------


def load_catalog():
    return json.loads(CATALOG_PATH.read_text())


def timeline(catalog=None):
    """Catalog entries that belong in the timelapse (duplicates removed)."""
    return [e for e in (catalog or load_catalog()) if not e.get("duplicate_of")]


def load_alignment():
    if ALIGNMENT_PATH.exists():
        return json.loads(ALIGNMENT_PATH.read_text())
    return {}


def _write_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, indent=1, sort_keys=True))
    tmp.replace(path)


def set_alignment(photo_id, value):
    """value: {"fork":[x,y],"point":[x,y]} or {"skip": True} or None (= to do)."""
    with _lock:
        data = load_alignment()
        if value is None:
            data.pop(photo_id, None)
        else:
            data[photo_id] = value
        _write_json(ALIGNMENT_PATH, data)
        return data


# ---------- geometry ----------


def _vec(a):
    dx, dy = a["point"][0] - a["fork"][0], a["point"][1] - a["fork"][1]
    return math.hypot(dx, dy), math.atan2(dy, dx)


def compute_transforms(entries=None, alignment=None):
    """Return ({id: transform}, reference) for every timeline photo that has one.

    transform = {fork:[x,y] original px, scale: output px per original px,
                 rotation: radians, source: id whose clicks were used}
    Skipped / not-yet-done photos reuse the clicks of the nearest aligned photo
    before them in time (or after, if none before), in relative coordinates.
    """
    entries = entries or timeline()
    alignment = load_alignment() if alignment is None else alignment
    by_id = {e["id"]: e for e in entries}
    clicked = [e for e in entries if "fork" in alignment.get(e["id"], {})]
    if not clicked:
        return {}, None

    # Reference angle: circular mean of the clicked angles.
    sx = sum(math.cos(_vec(alignment[e["id"]])[1]) for e in clicked)
    sy = sum(math.sin(_vec(alignment[e["id"]])[1]) for e in clicked)
    ref_angle = math.atan2(sy, sx)

    # Reference length: the shortest branch, from the widest shot.
    ref_entry = min(clicked, key=lambda e: _vec(alignment[e["id"]])[0])
    ref_len = _vec(alignment[ref_entry["id"]])[0]
    cover = max(FRAME_W / ref_entry["width"], FRAME_H / ref_entry["height"])
    ref_out_len = ref_len * cover  # branch length in output px

    def transform_from(src_id, target):
        a = alignment[src_id]
        src = by_id[src_id]
        # Relative coordinates so clicks carry over between resolutions.
        fx = a["fork"][0] / src["width"] * target["width"]
        fy = a["fork"][1] / src["height"] * target["height"]
        px = a["point"][0] / src["width"] * target["width"]
        py = a["point"][1] / src["height"] * target["height"]
        length, angle = _vec({"fork": [fx, fy], "point": [px, py]})
        return {
            "fork": [round(fx, 2), round(fy, 2)],
            "scale": round(ref_out_len / length, 6),
            "rotation": round(ref_angle - angle, 6),
            "source": src_id,
        }

    transforms = {}
    clicked_idx = [i for i, e in enumerate(entries) if e in clicked]
    for i, e in enumerate(entries):
        if e in clicked:
            transforms[e["id"]] = transform_from(e["id"], e)
            continue
        before = [j for j in clicked_idx if j < i]
        after = [j for j in clicked_idx if j > i]
        j = before[-1] if before else after[0]
        transforms[e["id"]] = transform_from(entries[j]["id"], e)

    reference = {
        "id": ref_entry["id"],
        "angle": ref_angle,
        "length": ref_out_len,
        "frame": [FRAME_W, FRAME_H],
    }
    return transforms, reference


# ---------- rendering ----------


def render_frame(entry, t, out_path):
    with Image.open(SOURCE_DIR / entry["file"]) as img:
        # Decode at reduced size when possible (JPEG draft); keep 2x margin.
        want = (int(entry["width"] * t["scale"] * 2), int(entry["height"] * t["scale"] * 2))
        img.draft("RGB", want)
        src = ImageOps.exif_transpose(img).convert("RGB")
    k = src.width / entry["width"]  # loaded px per original px
    if t["scale"] / k < 0.5:  # pre-shrink so bicubic doesn't alias
        f = t["scale"] / k * 2
        src = src.resize(
            (max(1, round(src.width * f)), max(1, round(src.height * f))), Image.LANCZOS
        )
        k = src.width / entry["width"]

    s = t["scale"] / k
    fx, fy = t["fork"][0] * k, t["fork"][1] * k
    cos, sin = math.cos(t["rotation"]), math.sin(t["rotation"])
    cx, cy = FRAME_W / 2, FRAME_H / 2
    # Inverse map: output (ox, oy) -> source (x, y).
    a, b = cos / s, sin / s
    d, e = -sin / s, cos / s
    coeffs = (a, b, fx - a * cx - b * cy, d, e, fy - d * cx - e * cy)

    photo = src.transform((FRAME_W, FRAME_H), Image.AFFINE, coeffs, Image.BICUBIC)
    mask = Image.new("L", src.size, 255).transform(
        (FRAME_W, FRAME_H), Image.AFFINE, coeffs, Image.BILINEAR
    )

    # Background: the photo, rotated the same way, scaled to cover the frame.
    small = src.resize((max(1, src.width // 8), max(1, src.height // 8)), Image.BILINEAR)
    small = small.rotate(-math.degrees(t["rotation"]), Image.BILINEAR, expand=False)
    bg = ImageOps.fit(small, (FRAME_W // 8, FRAME_H // 8), Image.BILINEAR)
    bg = bg.filter(ImageFilter.GaussianBlur(BG_BLUR))
    bg = ImageEnhance.Brightness(bg).enhance(BG_DARKEN).resize((FRAME_W, FRAME_H), Image.BICUBIC)

    bg.paste(photo, (0, 0), mask)
    bg.save(out_path, "JPEG", quality=88, optimize=True, progressive=True)


def _render_one(args):
    entry, t, out_path = args
    render_frame(entry, t, out_path)
    return entry["id"]


progress = {"running": False, "done": 0, "total": 0, "error": None}


def render_all(force=False):
    """Render every frame whose transform changed since its last render."""
    entries = timeline()
    transforms, reference = compute_transforms(entries)
    ALIGNED_DIR.mkdir(parents=True, exist_ok=True)
    rendered = {} if force or not RENDERED_PATH.exists() else json.loads(RENDERED_PATH.read_text())
    jobs = []
    for e in entries:
        t = transforms.get(e["id"])
        out = ALIGNED_DIR / f"{e['id']}.jpg"
        if t and (rendered.get(e["id"]) != t or not out.exists()):
            jobs.append((e, t, out))
    progress.update(running=True, done=0, total=len(jobs), error=None)
    try:
        with ProcessPoolExecutor() as pool:
            for photo_id in pool.map(_render_one, jobs):
                rendered[photo_id] = transforms[photo_id]
                progress["done"] += 1
        rendered = {k: v for k, v in rendered.items() if k in transforms}
        _write_json(RENDERED_PATH, rendered)
    except Exception as exc:  # reported to the page
        progress["error"] = str(exc)
        raise
    finally:
        progress["running"] = False
    return len(jobs), reference


def start_render_thread(force=False):
    if progress["running"]:
        return False
    progress["running"] = True
    threading.Thread(target=render_all, kwargs={"force": force}, daemon=True).start()
    return True


if __name__ == "__main__":
    n, ref = render_all(force="--force" in sys.argv)
    print(f"rendered {n} frames; reference: {ref}")
