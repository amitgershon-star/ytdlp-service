"""                                                                           
  yt-dlp Video Download Service                             
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
  PROXY_URL = os.environ.get("PROXY_URL", "")
  INSTAGRAM_COOKIES_B64 = os.environ.get("INSTAGRAM_COOKIES_B64", "")           
                                                                                
                                        
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
                                                            
                                                                                
  def detect_platform(url):                                                     
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
          "--no-download",                                                      
          "--dump-json",                                                        
          "--no-playlist",
          "--no-warnings",                                                      
          "--socket-timeout", "20",                                            
          "--extractor-retries", "2",                                           
      ]                                 

      if platform == "youtube":                                                 
          cmd.extend(["--format",
              "bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]"              
                                                                                
  "/best[height<=480][ext=mp4]/best[height<=480]/worst[ext=mp4]/worst"          
          ])                                                                    
      else:                                                                     
          cmd.extend(["--format", "best[ext=mp4]/best"])                        
                                                                                
      if PROXY_URL:                                                             
          cmd.extend(["--proxy", PROXY_URL])                                    
                                                            
      tmp_cookie_file = None                                                    
      if INSTAGRAM_COOKIES_B64 and platform in ("instagram", "youtube",
  "facebook"):                                                                  
          try:                                                                  
              cookies_data =            
  base64.b64decode(INSTAGRAM_COOKIES_B64).decode("utf-8")                      
              tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.txt',        
  delete=False, dir='/tmp')                                                    
              tmp.write(cookies_data)                                           
              tmp.flush()                                                       
              tmp.close()                                                      
              tmp_cookie_file = tmp.name                                        
              cmd.extend(["--cookies", tmp_cookie_file])    
          except Exception as e:                                                
              app.logger.warning("Cookie decode error: " + str(e))              
      elif not INSTAGRAM_COOKIES_B64:                                          
          cookies_file = os.environ.get("COOKIES_FILE")                         
          if cookies_file and os.path.exists(cookies_file):                    
              cmd.extend(["--cookies", cookies_file])                           
                                                                                
      cmd.append(url)                                                           
                                                                                
      try:                                                  
          result = subprocess.run(cmd, capture_output=True, text=True,          
  timeout=30)                                                                  
                                                                                
          if result.returncode != 0:                        
              stderr = result.stderr.strip()
              if "login" in stderr.lower() or "private" in stderr.lower():      
                  return jsonify({"error": "Login required or private content",
  "platform": platform}), 403                                                   
              return jsonify({"error": "yt-dlp failed: " + stderr[:300],        
  "platform": platform}), 422                                                  
                                                                                
          info = json.loads(result.stdout)                                      
          video_url = info.get("url", "")                                       
                                                                                
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
                                                            
          if not video_url and info.get("formats"):                             
              for fmt in info["formats"]:                                       
                  if fmt.get("url") and fmt.get("vcodec", "none") != "none":    
                      video_url = fmt["url"]                                    
                      break                                                     
                                        
          return jsonify({                                                      
              "videoUrl": video_url,                                            
              "thumbnail": info.get("thumbnail", ""),
              "title": info.get("title", ""),                                   
              "description": (info.get("description", "") or "")[:2000],        
              "platform": platform,                                            
              "duration": info.get("duration"),                                 
          })                                                                    
  
      except subprocess.TimeoutExpired:                                         
          return jsonify({"error": "Timeout", "platform": platform}), 504
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
      data = request.get_json(silent=True)                                      
      if not data or not data.get("url"):                                      
          return jsonify({"error": "Missing 'url'"}), 400                       
                                        
      url = data["url"]
      match = re.search(r"(?:v=|youtu\.be/|shorts/)([A-Za-z0-9_-]{11})", url)   
      if not match:                                                            
          return jsonify({"error": "Could not extract YouTube video ID"}), 400  
      video_id = match.group(1)                                                
                                                                                
      try:                                                                      
          from youtube_transcript_api import YouTubeTranscriptApi
          transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)     
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
      import requests
      data = request.get_json(silent=True)                                      
      if not data or not data.get("url"):                                       
          return jsonify({"error": "Missing 'url'"}), 400

      url = data["url"]                                                         
      headers = data.get("headers", {})
      proxies = {"http": PROXY_URL, "https": PROXY_URL} if PROXY_URL else None  
      try:                                                                      
          resp = requests.get(url, headers=headers, proxies=proxies, timeout=12,
   allow_redirects=True)                                                        
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
