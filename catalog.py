"""Step 1: build the photo catalog and the web copies / thumbnails.

Reads SpotRiviere/ (never modifies it) and writes into cache/:
  cache/catalog.json   sorted list of photos
  cache/web/<id>.jpg   ~1920 px wide copy (unaligned, used by the alignment page)
  cache/thumb/<id>.jpg 320 px wide thumbnail

Run: .venv/bin/python catalog.py          (only missing/outdated copies are rebuilt)
     .venv/bin/python catalog.py --force  (rebuild every copy)
"""

import hashlib
import io
import json
import os
import re
import sys
import threading
import time
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

# Formats Pillow can decode (HEIC needs a plugin that is not installed).
UPLOAD_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff"}

# An optional "-<n>" suffix is added when an uploaded name is already taken.
EPOCH_MS_RE = re.compile(r"^(\d{13})(?:-\d+)?$")
IMG_RE = re.compile(r"^IMG_(\d{8})_(\d{6})(\d{3})(?:-\d+)?$")
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
    write_catalog(entries)
    return entries


def write_catalog(entries):
    tmp = CATALOG_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(entries, indent=1))
    tmp.replace(CATALOG_PATH)


# ---------- upload (step 5) ----------

_lock = threading.Lock()


class UploadError(ValueError):
    """The upload was refused; the message is shown to the user."""


class DuplicateError(UploadError):
    def __init__(self, entry):
        self.entry = entry
        super().__init__(f"same file as {entry['file']} ({entry['date'][:10]})")


def _free_name(stem, ext):
    """A filename in SOURCE_DIR whose stem (= photo id) is not taken yet."""
    taken = {p.stem.lower() for p in SOURCE_DIR.iterdir()}
    n, candidate = 1, stem
    while candidate.lower() in taken:
        n += 1
        candidate = f"{stem}-{n}"
    return candidate + ext


def add_upload(filename, data, mtime=None):
    """Save an uploaded image into SpotRiviere/ and add it to the catalog.

    filename: the name sent by the browser. data: the file bytes.
    mtime: the file's last-modified time from the browser (epoch seconds), used
    as the capture date when neither the name nor EXIF has one.
    Never overwrites: a "-<n>" suffix is added if the name is taken.
    Returns the new catalog entry; raises UploadError / DuplicateError.
    """
    from werkzeug.utils import secure_filename

    name = secure_filename(filename or "")
    stem, ext = os.path.splitext(name)
    ext = ext.lower()
    if ext not in UPLOAD_EXTS:
        raise UploadError(f"not a supported image type ({ext or 'no extension'})")
    try:
        with Image.open(io.BytesIO(data)) as img:
            img.draft("RGB", (THUMB_WIDTH, THUMB_WIDTH))
            img.load()  # decodes the whole file: catches truncated or fake images
    except Exception as exc:
        raise UploadError(f"not a readable image ({exc.__class__.__name__})") from exc
    sha = hashlib.sha256(data).hexdigest()

    with _lock:
        entries = json.loads(CATALOG_PATH.read_text()) if CATALOG_PATH.exists() else []
        dup = next((e for e in entries if e["sha256"] == sha), None)
        if dup:
            first = dup.get("duplicate_of")
            raise DuplicateError(next((e for e in entries if e["id"] == first), dup))
        path = SOURCE_DIR / _free_name(stem or time.strftime("upload_%Y%m%d_%H%M%S"), ext)
        with open(path, "xb") as f:  # "x": fail rather than overwrite
            f.write(data)
        try:
            if mtime and 0 < mtime < time.time():
                os.utime(path, (mtime, mtime))
            WEB_DIR.mkdir(parents=True, exist_ok=True)
            THUMB_DIR.mkdir(parents=True, exist_ok=True)
            entry = process(path, force=True)
        except Exception as exc:
            path.unlink()  # the file was created by this call, nothing else uses it
            raise UploadError(f"could not process the image ({exc})") from exc
        entry["duplicate_of"] = None
        entries.append(entry)
        entries.sort(key=lambda e: (e["timestamp"], e["id"]))
        write_catalog(entries)
    return entry


if __name__ == "__main__":
    entries = build(force="--force" in sys.argv)
    print(f"{len(entries)} photos, {entries[0]['date']} → {entries[-1]['date']}")
