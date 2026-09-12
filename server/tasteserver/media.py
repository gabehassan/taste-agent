"""Download media with yt-dlp, compress audio, grab keyframes, transcribe."""
import base64
import pathlib
import subprocess
import tempfile

from openai import OpenAI

from . import db, storage
from .config import (MAX_AUDIO_BYTES, MAX_MEDIA_MB, MAX_MEDIA_SECONDS, TRANSCRIBE_MODEL, YTDLP_COOKIES_B64,
                     YTDLP_PROXY)

_client = None


def client():
    global _client
    if _client is None:
        _client = OpenAI(timeout=300, max_retries=2)
    return _client


def _cookiefile(tmp):
    if not YTDLP_COOKIES_B64:
        return None
    p = pathlib.Path(tmp) / "cookies.txt"
    p.write_bytes(base64.b64decode(YTDLP_COOKIES_B64))
    return str(p)


def process(url, user_id, item_key, duration=None, want_video=True, job_id=None):
    """Returns {"transcript": str, "frames": [(media_type, bytes)], "media": [{key, bytes, type}], "seconds": float}."""
    out = {"transcript": "", "frames": [], "media": [], "seconds": 0.0}
    if duration and duration > MAX_MEDIA_SECONDS:
        out["skipped"] = f"too long ({duration}s)"
        return out
    with tempfile.TemporaryDirectory() as tmp:
        fmt = "bestvideo[height<=480]+bestaudio/best[height<=480]/best" if want_video and (duration or 0) <= 900 else "bestaudio/best"
        cmd = ["yt-dlp", "-f", fmt, "--no-playlist", "--no-warnings", "--socket-timeout", "30",
               "--max-filesize", f"{MAX_MEDIA_MB}m", "--match-filter", f"duration < {MAX_MEDIA_SECONDS}",
               "-o", f"{tmp}/media.%(ext)s", "--merge-output-format", "mp4"]
        if YTDLP_PROXY:
            cmd += ["--proxy", YTDLP_PROXY]
        ck = _cookiefile(tmp)
        if ck:
            cmd += ["--cookies", ck]
        r = subprocess.run(cmd + [url], capture_output=True, text=True, timeout=240)
        files = [p for p in pathlib.Path(tmp).iterdir() if p.name.startswith("media.")]
        if r.returncode != 0 or not files:
            out["error"] = (r.stderr or "download failed").strip()[-300:]
            return out
        src = files[0]
        seconds = _duration(src) or float(duration or 0)
        out["seconds"] = seconds

        # keyframes for the vision pass
        if want_video and _has_video(src):
            for i, frac in enumerate((0.1, 0.5, 0.9)):
                frame = pathlib.Path(tmp) / f"frame{i}.jpg"
                subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{seconds * frac:.2f}", "-i", str(src),
                                "-frames:v", "1", "-vf", "scale=640:-2", "-q:v", "5", str(frame)],
                               capture_output=True, timeout=60)
                if frame.exists() and frame.stat().st_size > 0:
                    data = frame.read_bytes()
                    out["frames"].append(("image/jpeg", data))
                    key = f"users/{user_id}/items/{item_key}/frame{i}.jpg"
                    storage.put(key, data, "image/jpeg")
                    out["media"].append({"key": key, "bytes": len(data), "type": "image/jpeg"})

        # audio -> transcript
        audio = pathlib.Path(tmp) / "audio.mp3"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-vn", "-ac", "1", "-ar", "16000",
                        "-b:a", "32k", str(audio)], capture_output=True, timeout=180)
        if audio.exists() and 0 < audio.stat().st_size <= MAX_AUDIO_BYTES:
            with open(audio, "rb") as f:
                t = client().audio.transcriptions.create(model=TRANSCRIBE_MODEL, file=f, response_format="text")
            out["transcript"] = (t if isinstance(t, str) else getattr(t, "text", "")).strip()[:30000]
            db.record_usage(user_id, "transcribe", TRANSCRIBE_MODEL, seconds=seconds, job_id=job_id)
    return out


def _duration(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                       capture_output=True, text=True, timeout=30)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def _has_video(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=codec_type",
                        "-of", "csv=p=0", str(path)], capture_output=True, text=True, timeout=30)
    return "video" in r.stdout


def image_b64(media_type, data):
    return f"data:{media_type};base64,{base64.standard_b64encode(data).decode()}"
