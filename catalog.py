"""Step 1: build the photo catalog and the web copies / thumbnails.

Reads SpotRiviere/ (never modifies it) and writes into cache/:
  cache/catalog.json   sorted list of photos
  cache/web/<id>.jpg   ~1920 px wide copy (unaligned, used by the alignment page)
  cache/thumb/<id>.jpg 320 px wide thumbnail

Run: .venv/bin/python catalog.py          (only missing/outdated copies are rebuilt)
     .venv/bin/python catalog.py --force  (rebuild every copy)
"""

import hashlib
import json
import re
import sys
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parent
SOURCE_DIR = ROOT / "SpotRiviere"
CACHE_DIR = ROOT / "cache"
WEB_DIR = CACHE_DIR / "web"
THUMB_DIR = CACHE_DIR / "thumb"
CATALOG_PATH = CACHE_DIR / "catalog.json"

WEB_WIDTH = 1920
THUMB_WIDTH = 320
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".heic"}

EPOCH_MS_RE = re.compile(r"^(\d{13})$")
IMG_RE = re.compile(r"^IMG_(\d{8})_(\d{6})(\d{3})$")
EXIF_IFD = 0x8769
DATETIME_ORIGINAL = 36867


def date_from_name(stem):
    """Capture time from the filename, as a local naive datetime, or None."""
    m = EPOCH_MS_RE.match(stem)
    if m:
        return datetime.fromtimestamp(int(m.group(1)) / 1000)
    m = IMG_RE.match(stem)
    if m:
        dt = datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S")
        return dt.replace(microsecond=int(m.group(3)) * 1000)
    return None


def date_from_exif(img):
    try:
        raw = img.getexif().get_ifd(EXIF_IFD).get(DATETIME_ORIGINAL)
        return datetime.strptime(raw.strip(), "%Y:%m:%d %H:%M:%S") if raw else None
    except (ValueError, AttributeError, TypeError):
        return None


def file_hash(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def resized(img, width):
    if img.width <= width:
        return img.copy()
    height = round(img.height * width / img.width)
    return img.resize((width, height), Image.LANCZOS)


def process(path, force=False):
    """Build web copy + thumbnail for one original; return its catalog entry."""
    photo_id = path.stem
    web_path = WEB_DIR / f"{photo_id}.jpg"
    thumb_path = THUMB_DIR / f"{photo_id}.jpg"
    mtime = path.stat().st_mtime
    up_to_date = (
        not force
        and web_path.exists()
        and thumb_path.exists()
        and web_path.stat().st_mtime >= mtime
    )

    with Image.open(path) as img:
        width, height = img.size  # EXIF orientation is 1 on all current files
        orientation = img.getexif().get(0x0112, 1)
        date = date_from_name(photo_id)
        date_source = "filename"
        if date is None:
            date, date_source = date_from_exif(img), "exif"
        if date is None:
            date, date_source = datetime.fromtimestamp(mtime), "file_time"

        if not up_to_date:
            img.draft("RGB", (WEB_WIDTH, WEB_WIDTH))  # fast JPEG downscale on load
            im = ImageOps.exif_transpose(img).convert("RGB")
            web = resized(im, WEB_WIDTH)
            web.save(web_path, "JPEG", quality=88, optimize=True, progressive=True)
            resized(web, THUMB_WIDTH).save(thumb_path, "JPEG", quality=80)

    if orientation in (5, 6, 7, 8):  # rotated 90°: report displayed size
        width, height = height, width

    return {
        "id": photo_id,
        "file": path.name,
        "date": date.isoformat(timespec="seconds"),
        "timestamp": date.timestamp(),
        "date_source": date_source,
        "width": width,
        "height": height,
        "sha256": file_hash(path),
        "web": f"cache/web/{photo_id}.jpg",
        "thumb": f"cache/thumb/{photo_id}.jpg",
    }


def build(force=False):
    WEB_DIR.mkdir(parents=True, exist_ok=True)
    THUMB_DIR.mkdir(parents=True, exist_ok=True)
    files = sorted(
        p for p in SOURCE_DIR.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTS
    )
    with ProcessPoolExecutor() as pool:
        entries = list(pool.map(process, files, [force] * len(files)))
    entries.sort(key=lambda e: (e["timestamp"], e["id"]))
    # Byte-identical files saved again under a later name: keep the earliest,
    # mark the others so the timeline and alignment page skip them.
    first_by_hash = {}
    for e in entries:
        e["duplicate_of"] = first_by_hash.setdefault(e["sha256"], e["id"])
        if e["duplicate_of"] == e["id"]:
            e["duplicate_of"] = None
    tmp = CATALOG_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(entries, indent=1))
    tmp.replace(CATALOG_PATH)
    return entries


if __name__ == "__main__":
    entries = build(force="--force" in sys.argv)
    print(f"{len(entries)} photos, {entries[0]['date']} → {entries[-1]['date']}")
