"""                                                                           
  yt-dlp Video Download Service                                                 
  Lightweight Flask API that wraps yt-dlp to extract direct video URLs          
  from social media platforms (Instagram, YouTube, Facebook, TikTok).           
                                                                                
  Endpoints:                                                                    
    POST /download      - Extract direct video URL via yt-dlp                   
    POST /transcript    - Fetch YouTube auto-captions (works on data center IPs)
    POST /proxy-fetch   - HTTP proxy for the webhook to use a different IP
                                                                                
  Deploy on Render with the included Dockerfile and render.yaml.
  """                                                                           
                                                            
  import os                                                                     
  import json                                               
  import subprocess                                                             
  import re
  import base64                                                                 
  import tempfile                                           
  from flask import Flask, request, jsonify
  from functools import wraps
                                                                                
                                                                                
  app = Flask(__name__)                                     

  API_KEY = os.environ.get("API_KEY", "")
  PROXY_URL = os.environ.get("PROXY_URL", "")          # e.g. 
  http://user:pass@proxy.webshare.io:80                                         
  INSTAGRAM_COOKIES_B64 = os.environ.get("INSTAGRAM_COOKIES_B64", "")  # 
  base64-encoded Netscape cookie file                                           
                                                            
                                                                                
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
      if "facebook.com" in url_lower or "fb.watch" in url_lower or "fb.me" in
  url_lower:                                                                    
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
                                                                                
      cmd = [                                               
          "yt-dlp",
          "--no-download",          # Don't actually download — just extract 
  info                                                                          
          "--dump-json",            # Output metadata as JSON
          "--no-playlist",          # Single video only                         
          "--no-warnings",                                                      
          "--socket-timeout", "20",
          "--extractor-retries", "2",                                           
      ]                                                     
                                                                                
      # Platform-aware format selection.
      # YouTube at 720p can be 100-200 MB — far over the 15 MB base64 limit in  
  the webhook.                                                                  
      # Keep YouTube at 480p max so short recipe clips stay under 15 MB for 
  Gemini inline video.                                                          
      if platform == "youtube":                             
          cmd.extend(["--format",                                               
              "bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]"
                                                                                
  "/best[height<=480][ext=mp4]/best[height<=480]/worst[ext=mp4]/worst"          
          ])                                                                    
      else:                                                                     
          cmd.extend(["--format", "best[ext=mp4]/best"])    
                                                                                
      # Route through residential proxy when configured — bypasses data center  
  IP blocks.                                                                    
      # Required for YouTube yt-dlp (YouTube blocks Render's IP without a       
  proxy).                                                                       
      if PROXY_URL:
          cmd.extend(["--proxy", PROXY_URL])                                    
                                                            
      # Cookie injection via base64-encoded env var.                            
      # Avoids needing a persistent file on Render's ephemeral filesystem.
      tmp_cookie_file = None                                                    
      if INSTAGRAM_COOKIES_B64 and platform in ("instagram", "youtube",
  "facebook"):                                                                  
          try:                                              
              cookies_data =                                                    
  base64.b64decode(INSTAGRAM_COOKIES_B64).decode("utf-8")                       
              tmp = tempfile.NamedTemporaryFile(
                  mode='w', suffix='.txt', delete=False, dir='/tmp'             
              )                                                                 
              tmp.write(cookies_data)
              tmp.flush()                                                       
              tmp.close()                                   
              tmp_cookie_file = tmp.name                                        
              cmd.extend(["--cookies", tmp_cookie_file])
          except Exception as e:                                                
              app.logger.warning(f"Cookie decode error: {e}")

      # Legacy COOKIES_FILE fallback (for file-mounted cookies)                 
      elif not INSTAGRAM_COOKIES_B64:
          cookies_file = os.environ.get("COOKIES_FILE")                         
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
              if "login" in stderr.lower() or "private" in stderr.lower():
                  return jsonify({"error": "Login required or private content",
  "platform": platform}), 403                                                   
              return jsonify({"error": f"yt-dlp failed: {stderr[:300]}",
  "platform": platform}), 422                                                   
                                                            
          info = json.loads(result.stdout)

          # Extract the best direct video URL
          video_url = info.get("url", "")
                                                                                
          # If no direct URL, find from formats (prefer mp4 with video stream)
          if not video_url and info.get("formats"):                             
              mp4_formats = [                               
                  f for f in info["formats"]
                  if f.get("ext") == "mp4"
                  and f.get("vcodec", "none") != "none"                         
                  and f.get("url")
              ]                                                                 
              if mp4_formats:                               
                  target_height = 480 if platform == "youtube" else 720
                  mp4_formats.sort(key=lambda f: abs((f.get("height") or 0) -   
  target_height))
                  video_url = mp4_formats[0]["url"]                             
                                                            
          # Fallback: any format with video
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
          return jsonify({"error": "Timeout: extraction took too long",
  "platform": platform}), 504                                                   
      except json.JSONDecodeError:
          return jsonify({"error": "Failed to parse yt-dlp output", "platform": 
  platform}), 500                                           
      except Exception as e:
          return jsonify({"error": str(e), "platform": platform}), 500
      finally:                                                                  
          if tmp_cookie_file and os.path.exists(tmp_cookie_file):
              os.unlink(tmp_cookie_file)                                        
                                                            

  @app.route("/transcript", methods=["POST"])
  @require_auth
  def transcript():                                                             
      """
      Fetch YouTube auto-generated captions using youtube-transcript-api.       
      Works from data center IPs (different mechanism than yt-dlp video 
  download).
      Returns the full spoken transcript — far better than description for
  recipe videos.
      """
      data = request.get_json(silent=True)                                      
      if not data or not data.get("url"):
          return jsonify({"error": "Missing 'url'"}), 400                       
                                                            
      url = data["url"]
      match = re.search(r"(?:v=|youtu\.be/|shorts/)([A-Za-z0-9_-]{11})", url)
      if not match:                                                             
          return jsonify({"error": "Could not extract YouTube video ID"}), 400
      video_id = match.group(1)                                                 
                                                                                
      try:
          from youtube_transcript_api import (                                  
              YouTubeTranscriptApi,                         
              NoTranscriptFound,
              TranscriptsDisabled,
          )

          transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)     
  
          # Prefer English or Hebrew; fall back to any auto-generated transcript
          try:                                              
              t = transcript_list.find_transcript(["en", "en-US", "en-GB",
  "he"])
          except Exception:
              generated = transcript_list._generated_transcripts
              if not generated:                                                 
                  return jsonify({"transcript": None, "error": "No captions 
  available"})                                                                  
              t = list(generated.values())[0]               

          entries = t.fetch()
          text = " ".join(e["text"] for e in entries if e.get("text"))
          return jsonify({"transcript": text, "language": t.language_code})     
  
      except Exception as e:                                                    
          error_name = type(e).__name__                     
          if "NoTranscriptFound" in error_name or "TranscriptsDisabled" in
  error_name:                                                                   
              return jsonify({"transcript": None, "error": "No captions 
  available"})                                                                  
          return jsonify({"transcript": None, "error": str(e)}), 500

                                                                                
  @app.route("/proxy-fetch", methods=["POST"])
  @require_auth                                                                 
  def proxy_fetch():                                        
      """
      HTTP proxy endpoint — fetches a URL from Render's IP (different from
  Supabase's
      Cloudflare IP range). Optionally routes through PROXY_URL if configured.
                                                                                
      Use for: Instagram ?__a=1 API calls that are rate-limited on Supabase's 
  IP.                                                                           
      Returns: { status, text, url }                        
      """
      import requests as req_lib 
      data = request.get_json(silent=True)
      if not data or not data.get("url"):
          return jsonify({"error": "Missing 'url'"}), 400                       
  
      url = data["url"]                                                         
      headers = data.get("headers", {})                     
      proxies = {"http": PROXY_URL, "https": PROXY_URL} if PROXY_URL else None
                                                                                
      try:
          resp = req_lib.get(                                                   
              url,                                          
              headers=headers,
              proxies=proxies,
              timeout=12,
              allow_redirects=True,
          )
          return jsonify({                                                      
              "status": resp.status_code,
              "text": resp.text[:60000],                                        
              "url": str(resp.url),                         
          })
      except Exception as e:
          return jsonify({"error": str(e), "status": 0}), 500
                                                                                
  
  if __name__ == "__main__":                                                    
      port = int(os.environ.get("PORT", 10000))             
      app.run(host="0.0.0.0", port=port)

