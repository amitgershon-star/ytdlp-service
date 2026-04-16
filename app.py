"""
yt-dlp Video Download Service
Lightweight Flask API that wraps yt-dlp to extract direct video URLs
from social media platforms (Instagram, YouTube, Facebook, TikTok).

Deploy on Render with the included Dockerfile and render.yaml.
"""

import os
import json
import subprocess
import re
from flask import Flask, request, jsonify
from functools import wraps

app = Flask(__name__)

API_KEY = os.environ.get("API_KEY", "")

def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not API_KEY:
            return f(*args, **kwargs)
        auth = request.headers.get("Authorization", "")
        if auth != f"Bearer {API_KEY}":
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated

def detect_platform(url: str) -> str:
    url_lower = url.lower()
    if "tiktok.com" in url_lower:
        return "tiktok"
    if "instagram.com" in url_lower or "instagr.am" in url_lower:
        return "instagram"
    if "youtube.com" in url_lower or "youtu.be" in url_lower:
        return "youtube"
    if "facebook.com" in url_lower or "fb.watch" in url_lower or "fb.me" in url_lower:
        return "facebook"
    return "other"

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})

@app.route("/download", methods=["POST"])
@require_auth
def download():
    data = request.get_json(silent=True)
    if not data or not data.get("url"):
        return jsonify({"error": "Missing 'url' in request body"}), 400

    url = data["url"]
    platform = detect_platform(url)
    cookies_file = os.environ.get("COOKIES_FILE")

    cmd = [
        "yt-dlp",
        "--no-download",          # Don't actually download — just extract info
        "--dump-json",            # Output metadata as JSON
        "--no-playlist",          # Single video only
        "--no-warnings",
        "--socket-timeout", "20",
        "--extractor-retries", "2",
    ]

    # Use cookies file if configured (helps with Instagram login walls)
    if cookies_file and os.path.exists(cookies_file):
        cmd.extend(["--cookies", cookies_file])

    cmd.append(url)

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode != 0:
            stderr = result.stderr.strip()
            # Check for common errors
            if "login" in stderr.lower() or "private" in stderr.lower():
                return jsonify({"error": "Login required or private content", "platform": platform}), 403
            return jsonify({"error": f"yt-dlp failed: {stderr[:300]}", "platform": platform}), 422

        info = json.loads(result.stdout)

        # Extract the best direct video URL
        video_url = info.get("url", "")

        # If no direct URL, find from formats (prefer mp4, moderate quality)
        if not video_url and info.get("formats"):
            # Filter for mp4 formats with video, sort by quality
            mp4_formats = [
                f for f in info["formats"]
                if f.get("ext") == "mp4"
                and f.get("vcodec", "none") != "none"
                and f.get("url")
            ]
            if mp4_formats:
                # Pick a moderate quality (720p or closest)
                target_height = 720
                mp4_formats.sort(key=lambda f: abs((f.get("height") or 0) - target_height))
                video_url = mp4_formats[0]["url"]

        # Fallback: any format with a URL
        if not video_url and info.get("formats"):
            for fmt in info["formats"]:
                if fmt.get("url") and fmt.get("vcodec", "none") != "none":
                    video_url = fmt["url"]
                    break

        thumbnail = info.get("thumbnail", "")
        title = info.get("title", "")
        description = info.get("description", "")
        duration = info.get("duration")

        return jsonify({
            "videoUrl": video_url,
            "thumbnail": thumbnail,
            "title": title,
            "description": description[:2000] if description else "",
            "platform": platform,
            "duration": duration,
        })

    except subprocess.TimeoutExpired:
        return jsonify({"error": "Timeout: extraction took too long", "platform": platform}), 504
    except json.JSONDecodeError:
        return jsonify({"error": "Failed to parse yt-dlp output", "platform": platform}), 500
    except Exception as e:
        return jsonify({"error": str(e), "platform": platform}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
