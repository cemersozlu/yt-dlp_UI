from flask import Flask, request, jsonify, send_from_directory
import os
import sys
import re
import shutil
import subprocess
import threading
import time
import urllib.request
import uuid

def _app_dir():
    return os.path.dirname(os.path.abspath(__file__))

def _web_dir():
    if getattr(sys, "frozen", False):
        return os.path.join(sys._MEIPASS, "web")
    return os.path.abspath(os.path.join(_app_dir(), "..", "web"))


BASE_DIR = _web_dir()
app = Flask(__name__, static_folder=None)
_ALLOWED_STATIC_FILES = {"index.html", "style.css", "app.js"}
_ALLOWED_ASSET_FILES = {
    "icon.ico", "paste-icon.svg", "arrow-down.svg",
    "fonts/Manrope-Regular.ttf",
}

DEFAULT_FOLDER = os.path.join(os.path.expanduser("~"), "Downloads", "yt-dlp")
_NO_WINDOW_FLAG = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
YTDLP_RELEASE_URL = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe"

if getattr(sys, "frozen", False):
    YTDLP_DIR = os.path.dirname(sys.executable)
else:
    YTDLP_DIR = _app_dir()
YTDLP_EXE = os.path.join(YTDLP_DIR, "yt-dlp.exe")

_ytdlp_lock = threading.Lock()
_ytdlp_state = {"downloading": False, "error": None}


def _download_ytdlp_binary():
    with _ytdlp_lock:
        if _ytdlp_state["downloading"] or os.path.isfile(YTDLP_EXE):
            return
        _ytdlp_state["downloading"] = True
        _ytdlp_state["error"] = None

    tmp_path = YTDLP_EXE + ".tmp"
    try:
        req = urllib.request.Request(
            YTDLP_RELEASE_URL,
            headers={"User-Agent": "Mozilla/5.0 (yt-dlp UI)"},
        )
        with urllib.request.urlopen(req, timeout=60) as resp, open(tmp_path, "wb") as f:
            shutil.copyfileobj(resp, f)
        os.replace(tmp_path, YTDLP_EXE)
    except Exception as e:
        with _ytdlp_lock:
            _ytdlp_state["error"] = str(e)
        try:
            if os.path.isfile(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass
    finally:
        with _ytdlp_lock:
            _ytdlp_state["downloading"] = False


if not os.path.isfile(YTDLP_EXE):
    threading.Thread(target=_download_ytdlp_binary, daemon=True).start()


_jobs = {}
_jobs_lock = threading.Lock()

_JOB_TTL_SECONDS = 600  # finished jobs are cleaned up after this long


def _cleanup_old_jobs():
    now = time.time()
    with _jobs_lock:
        stale = [
            jid for jid, job in _jobs.items()
            if job.get("done") and (now - job.get("finished_at", now)) > _JOB_TTL_SECONDS
        ]
        for jid in stale:
            del _jobs[jid]


def _job_update(job_id, **kwargs):
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job is None:
            return
        job.update(kwargs)


# "[download]  45.2% of   12.34MiB at    1.23MiB/s ETA 00:07" format parser
_DL_RE = re.compile(
    r"\[download\]\s+([\d.]+)%\s+of\s+~?\s*([\d.]+\w+)"
    r"(?:\s+at\s+([\d.]+\w+/s|Unknown speed))?"
    r"(?:\s+ETA\s+([\d:]+|Unknown))?"
)


def _build_ytdlp_args(url, folder, audio_only):
    outtmpl = os.path.join(folder, "%(title)s [%(id)s].%(ext)s")
    args = [
        YTDLP_EXE,
        "--newline",
        "--no-warnings",
        "--windows-filenames",  # strips characters like : / \ ? " < > | from titles
        "--retries", "5",
        "-o", outtmpl,
    ]
    if audio_only:
        args += [
            "-f", "bestaudio/best",
            "--extract-audio",
            "--audio-format", "mp3",
            "--audio-quality", "192",
        ]
    else:
        args += ["-f", "bv*+ba/b", "--merge-output-format", "mp4"]
    args.append(url)
    return args


def _run_download(job_id, url, folder, audio_only):
    if not os.path.isfile(YTDLP_EXE):
        _job_update(
            job_id, done=True, ok=False, message="Error",
            error="yt-dlp.exe is not ready yet, try again shortly.",
            finished_at=time.time(),
        )
        return

    args = _build_ytdlp_args(url, folder, audio_only)
    error_lines = []

    try:
        proc = subprocess.Popen(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="ignore",
            creationflags=_NO_WINDOW_FLAG,
        )

        for raw_line in proc.stdout:
            line = raw_line.rstrip("\n").strip()
            if not line:
                continue

            m = _DL_RE.search(line)
            if m:
                percent = float(m.group(1))
                speed = m.group(3) or ""
                eta = m.group(4) or ""
                parts = [f"Downloading {percent:.1f}%"]
                if speed and speed != "Unknown speed":
                    parts.append(speed)
                if eta and eta != "Unknown":
                    parts.append(f"ETA {eta}")
                _job_update(job_id, percent=percent, message="  ".join(parts))
            elif line.startswith(("[Merger]", "[ExtractAudio]", "[VideoConvertor]", "[FixupM3u8]")):
                _job_update(job_id, percent=100.0, message="processing...")
            elif line.startswith("ERROR:"):
                error_lines.append(line[len("ERROR:"):].strip())
            elif line.startswith("["):
                _job_update(job_id, message=line)

        proc.wait()

        if proc.returncode == 0:
            _job_update(
                job_id, done=True, ok=True, percent=100.0,
                message="Done ✓", finished_at=time.time(),
            )
        else:
            _job_update(
                job_id, done=True, ok=False, message="Error",
                error="\n".join(error_lines) or f"yt-dlp exit code {proc.returncode}",
                finished_at=time.time(),
            )
    except Exception as e:
        _job_update(
            job_id, done=True, ok=False, message="Error",
            error=str(e), finished_at=time.time(),
        )
    finally:
        _cleanup_old_jobs()


@app.route("/")
def index():
    return send_from_directory(BASE_DIR, "index.html")


@app.route("/<path:filename>")
def static_files(filename):
    if filename in _ALLOWED_STATIC_FILES:
        return send_from_directory(BASE_DIR, filename)
    if filename.startswith("assets/") and filename.split("/", 1)[1] in _ALLOWED_ASSET_FILES:
        return send_from_directory(BASE_DIR, filename)
    return jsonify({"error": "not found"}), 404


@app.route("/default_folder")
def default_folder():
    return jsonify({"folder": DEFAULT_FOLDER})


@app.route("/version")
def version():
    if not os.path.isfile(YTDLP_EXE):
        with _ytdlp_lock:
            downloading = _ytdlp_state["downloading"]
            error = _ytdlp_state["error"]
        if error:
            return jsonify({"version": "download failed", "ready": False, "error": error})
        if downloading:
            return jsonify({"version": "downloading...", "ready": False})
        return jsonify({"version": "not found", "ready": False})

    try:
        result = subprocess.run(
            [YTDLP_EXE, "--version"],
            capture_output=True, text=True, timeout=15,
            creationflags=_NO_WINDOW_FLAG,
        )
        ver = result.stdout.strip() or "unknown"
    except Exception:
        ver = "unknown"
    return jsonify({"version": ver, "ready": True})


@app.route("/download", methods=["POST"])
def download():
    data = request.get_json(force=True)
    url = (data.get("url") or "").strip()
    folder = (data.get("folder") or DEFAULT_FOLDER).strip()
    audio_only = bool(data.get("audio_only"))

    if not url:
        return jsonify({"ok": False, "error": "URL is empty"})

    if not os.path.isfile(YTDLP_EXE):
        return jsonify({"ok": False, "error": "yt-dlp.exe is not ready yet, try again shortly."})

    if not os.path.isdir(folder):
        try:
            os.makedirs(folder, exist_ok=True)
        except Exception as e:
            return jsonify({"ok": False, "error": f"Could not create folder: {e}"})

    job_id = uuid.uuid4().hex
    with _jobs_lock:
        _jobs[job_id] = {
            "percent": 0.0,
            "message": "Starting...",
            "filename": "",
            "done": False,
            "ok": False,
            "error": None,
        }

    threading.Thread(
        target=_run_download,
        args=(job_id, url, folder, audio_only),
        daemon=True,
    ).start()

    return jsonify({"ok": True, "job_id": job_id})


@app.route("/status/<job_id>")
def status(job_id):
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job is None:
            return jsonify({"ok": False, "error": "job not found", "done": True}), 404
        return jsonify(job)


@app.route("/update", methods=["POST"])
def update_ytdlp():
    if not os.path.isfile(YTDLP_EXE):
        return jsonify({"ok": False, "error": "yt-dlp.exe has not been downloaded yet, try again shortly."})
    try:
        result = subprocess.run(
            [YTDLP_EXE, "-U"],
            capture_output=True, text=True, timeout=60,
            creationflags=_NO_WINDOW_FLAG,
        )
        output = ((result.stdout or "") + (result.stderr or "")).strip()
        if result.returncode == 0:
            return jsonify({"ok": True, "message": output or "yt-dlp updated."})
        return jsonify({"ok": False, "error": output or "Unknown error"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


if __name__ == "__main__":
    print("\n  yt-dlp web UI is running")
    print("  Open in browser: http://127.0.0.1:5050\n")
    app.run(host="127.0.0.1", port=5050, debug=False, threaded=True)
