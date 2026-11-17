"""Video Downloader API (Flask + yt-dlp).

Run locally:   python app.py
Run in Docker: gunicorn app:app
"""
import logging
import os
import shutil
import tempfile
import uuid
from pathlib import Path
from urllib.parse import urlparse

from flask import (Flask, after_this_request, jsonify, request, send_file,
                   send_from_directory)
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("downloader")

# ---------------------------------------------------------------- config ----
BASE_DIR = Path(__file__).resolve().parent
PUBLIC_DIR = BASE_DIR / "public"  # only this folder is served as static files

# Serverless platforms only allow writing to the temp directory.
WORK_DIR = Path(tempfile.gettempdir()) / "downloads"
WORK_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_HOSTS = ("youtube.com", "youtu.be", "youtube-nocookie.com")
MAX_FILESIZE_MB = int(os.environ.get("MAX_FILESIZE_MB", "500"))
ALLOWED_ORIGIN = os.environ.get("ALLOWED_ORIGIN", "")  # e.g. https://my-site.vercel.app
ON_VERCEL = bool(os.environ.get("VERCEL"))

app = Flask(__name__, static_folder=str(PUBLIC_DIR), static_url_path="")


def find_ffmpeg():
    """Locate ffmpeg: env var -> system PATH -> bundled imageio-ffmpeg binary."""
    env = os.environ.get("FFMPEG_LOCATION")
    if env:
        return env
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # package missing or binary unavailable
        return None


FFMPEG = find_ffmpeg()
log.info("ffmpeg: %s", FFMPEG or "not available")


# --------------------------------------------------------------- helpers ----
def validate_url(raw):
    """Accept only http(s) YouTube links. Blocks file://, internal hosts, etc."""
    parsed = urlparse((raw or "").strip())
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in ("http", "https") or not host:
        raise ValueError("Please enter a valid YouTube link.")
    if not any(host == d or host.endswith("." + d) for d in ALLOWED_HOSTS):
        raise ValueError("Only YouTube links are supported.")
    return parsed.geturl()


def validate_quality(raw):
    if raw == "audio":
        return raw
    if raw and raw.isdigit() and 100 <= int(raw) <= 4320:
        return raw
    raise ValueError("Invalid quality selected.")


def build_format(quality):
    if quality == "audio":
        return "bestaudio[ext=m4a]/bestaudio/best"
    h = int(quality)
    if FFMPEG:  # can merge separate video + audio streams
        return (f"bestvideo[height<={h}][ext=mp4]+bestaudio[ext=m4a]"
                f"/best[height<={h}][ext=mp4]/best[height<={h}]")
    return f"best[height<={h}][ext=mp4]/best[height<={h}]"  # single-file only


def cookie_file():
    """Optional: paste a Netscape cookies.txt into the YT_COOKIES env var.
    Helps when YouTube blocks datacenter IPs. Never commit cookies to Git."""
    content = os.environ.get("YT_COOKIES")
    if not content:
        return None
    path = WORK_DIR / "cookies.txt"
    path.write_text(content)
    os.chmod(path, 0o600)
    return str(path)


def base_opts():
    opts = {"quiet": True, "no_warnings": True, "noplaylist": True,
            "socket_timeout": 20}
    cookies = cookie_file()
    if cookies:
        opts["cookiefile"] = cookies
    return opts


def friendly_error(exc):
    msg = str(exc)
    if "Sign in to confirm" in msg or "not a bot" in msg:
        return ("YouTube blocked this server's request (bot check). "
                "This is common on cloud hosts - see the README.")
    if "Private video" in msg or "unavailable" in msg.lower():
        return "This video is private or unavailable."
    if "ffmpeg" in msg.lower():
        return "Server is missing ffmpeg, so this format cannot be created."
    return "Could not process this video. Please try another link."


@app.after_request
def add_headers(resp):
    if ALLOWED_ORIGIN:
        resp.headers["Access-Control-Allow-Origin"] = ALLOWED_ORIGIN
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
        resp.headers["Access-Control-Expose-Headers"] = "Content-Disposition"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    return resp


# ---------------------------------------------------------------- routes ----
@app.route("/")
def index():
    return send_from_directory(PUBLIC_DIR, "index.html")


@app.route("/api/health")
def health():
    return jsonify({"status": "ok", "ffmpeg": bool(FFMPEG), "vercel": ON_VERCEL})


@app.route("/api/info", methods=["POST", "OPTIONS"])
def get_info():
    if request.method == "OPTIONS":
        return "", 204
    data = request.get_json(silent=True) or {}
    try:
        url = validate_url(data.get("url"))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    try:
        with YoutubeDL(base_opts()) as ydl:
            info = ydl.extract_info(url, download=False)
    except DownloadError as e:
        log.warning("info failed: %s", e)
        return jsonify({"error": friendly_error(e)}), 422
    except Exception:
        log.exception("info crashed")
        return jsonify({"error": "Unexpected server error."}), 500

    heights = sorted({f["height"] for f in info.get("formats", [])
                      if f.get("vcodec") != "none" and f.get("height")},
                     reverse=True)
    formats = [{"id": str(h), "label": f"{h}p (MP4)"} for h in heights]
    formats.append({"id": "audio", "label": "Audio only (MP3)" if FFMPEG
                    else "Audio only (M4A)"})

    return jsonify({
        "title": info.get("title"),
        "thumbnail": info.get("thumbnail"),
        "uploader": info.get("uploader"),
        "formats": formats,
    })


@app.route("/api/download")
def download():
    try:
        url = validate_url(request.args.get("url"))
        quality = validate_quality(request.args.get("quality"))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    job_dir = WORK_DIR / uuid.uuid4().hex
    job_dir.mkdir(parents=True)

    @after_this_request
    def cleanup(response):
        shutil.rmtree(job_dir, ignore_errors=True)
        return response

    opts = base_opts()
    opts.update({
        "format": build_format(quality),
        "outtmpl": str(job_dir / "media.%(ext)s"),
        "merge_output_format": "mp4",
        "max_filesize": MAX_FILESIZE_MB * 1024 * 1024,
        "concurrent_fragment_downloads": 4,
    })
    if FFMPEG:
        opts["ffmpeg_location"] = FFMPEG
        if quality == "audio":
            opts["postprocessors"] = [{"key": "FFmpegExtractAudio",
                                       "preferredcodec": "mp3",
                                       "preferredquality": "192"}]

    try:
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
    except DownloadError as e:
        log.warning("download failed: %s", e)
        return jsonify({"error": friendly_error(e)}), 422
    except Exception:
        log.exception("download crashed")
        return jsonify({"error": "Unexpected server error."}), 500

    files = [p for p in job_dir.glob("media.*") if p.suffix != ".part"]
    if not files:
        return jsonify({"error": f"File missing or larger than "
                                 f"{MAX_FILESIZE_MB} MB limit."}), 413
    file_path = max(files, key=lambda p: p.stat().st_size)

    title = "".join(c for c in (info.get("title") or "video")
                    if c not in '\\/:*?"<>|').strip() or "video"
    return send_file(file_path, as_attachment=True,
                     download_name=f"{title}{file_path.suffix}")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)
