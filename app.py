"""Local web server for the SpotRiviere timelapse.

Run: .venv/bin/python app.py   ->  http://localhost:5000
"""

from flask import Flask, abort, jsonify, request, send_from_directory

import align
from catalog import CACHE_DIR, ROOT

app = Flask(__name__, static_folder=None)
STATIC_DIR = ROOT / "static"


@app.get("/")
def index():
    return send_from_directory(STATIC_DIR, "player.html")


@app.get("/align")
def align_page():
    return send_from_directory(STATIC_DIR, "align.html")


@app.get("/cache/<path:path>")
def cache_file(path):
    resp = send_from_directory(CACHE_DIR, path)
    if path.startswith("aligned/"):
        if request.args.get("v"):  # versioned URL from /api/frames
            resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        else:
            resp.headers["Cache-Control"] = "no-cache"  # frames are re-rendered in place
    return resp


@app.get("/api/catalog")
def api_catalog():
    return jsonify(align.timeline())


@app.get("/api/frames")
def api_frames():
    """Timeline photos that have an aligned frame, in time order.

    `v` (the frame's mtime) changes when a frame is re-rendered, so the browser
    can cache frames forever under a versioned URL.
    """
    frames = []
    for e in align.timeline():
        path = align.ALIGNED_DIR / f"{e['id']}.jpg"
        if path.exists():
            v = int(path.stat().st_mtime)
            frames.append(
                {
                    "id": e["id"],
                    "date": e["date"],
                    "timestamp": e["timestamp"],
                    "src": f"/cache/aligned/{e['id']}.jpg?v={v}",
                }
            )
    return jsonify(frames)


@app.get("/api/alignment")
def api_alignment():
    transforms, reference = align.compute_transforms()
    return jsonify(
        clicks=align.load_alignment(),
        transforms=transforms,
        reference=reference,
        render=align.progress,
    )


@app.put("/api/alignment/<photo_id>")
def api_set_alignment(photo_id):
    if photo_id not in {e["id"] for e in align.timeline()}:
        abort(404)
    body = request.get_json(force=True)
    if body.get("skip"):
        value = {"skip": True}
    elif body.get("reset"):
        value = None
    else:
        try:
            value = {k: [float(body[k][0]), float(body[k][1])] for k in ("fork", "point")}
        except (KeyError, TypeError, ValueError, IndexError):
            abort(400, "need fork and point as [x, y]")
        if value["fork"] == value["point"]:
            abort(400, "fork and point must differ")
    return jsonify(clicks=align.set_alignment(photo_id, value))


@app.post("/api/render")
def api_render():
    started = align.start_render_thread(force=bool(request.args.get("force")))
    return jsonify(started=started, render=align.progress)


@app.get("/api/render")
def api_render_status():
    return jsonify(align.progress)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)
